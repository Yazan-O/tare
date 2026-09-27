import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tare import gate, ledger
from tests.helpers import BALANCED, REPO, RED, Sandbox, has_jdk, load
from tests.test_mcp import session

COMMIT = {"tool": "execute_command", "input": {"command": "git commit -m x"}}
DONE = {"tool": "attempt_completion", "input": {"result": "Port finished."}}


def one_off():
    doc = copy.deepcopy(load(BALANCED))
    doc["files"]["totals"][0]["total_lb"] = "10.10"
    return doc


class Base(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.close()

    def weigh_local(self):
        return self.sb.tare("weigh", "--port", "local", "--no-image")


class D1StaleOutput(Base):
    def test_weigh_reruns_the_edited_port(self):
        self.sb.put_run("local", BALANCED)
        (self.sb.root / "port" / "X.java").write_text("class X { int broken = 1/0; }\n", encoding="utf-8")
        w = self.weigh_local()
        self.assertNotEqual(w.returncode, 0, w.stdout + w.stderr)
        self.assertEqual(self.sb.gate(COMMIT).returncode, 2)

    def test_output_edited_after_the_run_is_stale(self):
        self.sb.put_run("local", RED)
        (self.sb.root / "work" / "runs" / "local" / "records.json").write_text(
            json.dumps(dict(load(BALANCED), side="local")), encoding="utf-8")
        w = self.weigh_local()
        self.assertNotEqual(w.returncode, 0, w.stdout)
        self.assertEqual(self.sb.gate(COMMIT).returncode, 2)

    @unittest.skipUnless(has_jdk(), "no JDK >= 17 on this machine")
    def test_weigh_alone_runs_the_port_and_records_provenance(self):
        self.sb.use_port("exact")
        w = self.weigh_local()
        self.assertEqual(w.returncode, 0, w.stdout + w.stderr)
        rec = json.loads((self.sb.root / ".tare" / "weigh_local.json").read_text(encoding="utf-8"))
        prov = rec["provenance"]
        self.assertEqual(set(prov["sources"]), {"port/Port.java", "port/MAIN"})
        self.assertEqual(set(prov["inputs"]), {"items.dat"})
        self.assertEqual(prov["output_sha256"], rec["port_sha256"])
        self.assertEqual(self.sb.gate(COMMIT).returncode, 0)
        self.sb.use_port("halfup")
        self.assertEqual(self.weigh_local().returncode, 1)
        self.assertEqual(self.sb.gate(COMMIT).returncode, 2)


@unittest.skipUnless(has_jdk(), "no JDK >= 17 on this machine")
class D2Sandbox(Base):
    def test_port_cannot_read_the_answer_key_by_relative_path(self):
        self.sb.java_port('byte[] k = Files.readAllBytes(Paths.get("fixtures/answer_key/totals.dat")); '
                          'Files.write(Paths.get(out, "totals.dat"), k);')
        w = self.weigh_local()
        self.assertNotEqual(w.returncode, 0, w.stdout + w.stderr)
        self.assertIn("NoSuchFileException", w.stdout + w.stderr)
        self.assertEqual(self.sb.gate(COMMIT).returncode, 2)

    def test_port_sees_only_inputs_and_classes(self):
        self.sb.java_port(
            'List<String> seen = new ArrayList<>(); '
            'try (java.util.stream.Stream<Path> s = Files.walk(Paths.get("."))) '
            '{ s.filter(Files::isRegularFile).forEach(p -> seen.add(p.toString().replace("\\\\", "/"))); } '
            'Collections.sort(seen); '
            'throw new RuntimeException("SEEN:" + String.join(",", seen));')
        w = self.weigh_local()
        self.assertNotEqual(w.returncode, 0)
        self.assertIn("SEEN:./classes/Port.class,./input/items.dat", w.stdout + w.stderr)


class D3PinnedPolicy(Base):
    def edit_cfg(self, fn):
        p = self.sb.root / "tare.json"
        cfg = json.loads(p.read_text(encoding="utf-8"))
        fn(cfg)
        p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    def test_emptied_source_globs_do_not_open_the_gate(self):
        self.sb.put_run("local", RED)
        self.assertEqual(self.weigh_local().returncode, 1)
        self.edit_cfg(lambda c: c.update(port={"sources": []}))
        self.assertEqual(self.sb.gate(COMMIT).returncode, 2)

    def test_another_side_cannot_stand_in_for_the_port(self):
        self.edit_cfg(lambda c: c.update(port={"side": "exact"}))
        self.sb.put_run("exact", BALANCED)
        self.assertEqual(self.sb.tare("weigh", "--port", "exact", "--no-image").returncode, 0)
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("No weigh on record", r.stdout)

    def test_no_git_tare_json_edit_after_weigh_blocks(self):
        self.sb.put_run("local", BALANCED)
        self.assertEqual(self.weigh_local().returncode, 0)
        self.edit_cfg(lambda c: c.update(note="x"))
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("tare.json", r.stdout)

    def test_git_answer_key_edit_blocks_even_after_a_balanced_reweigh(self):
        self.sb.git_init()
        self.sb.put_run("local", RED)
        shutil.copy(self.sb.root / "work" / "runs" / "local" / "records.json",
                    self.sb.root / "fixtures" / "answer_key" / "records.json")
        self.assertEqual(self.weigh_local().returncode, 0)
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("fixtures/answer_key/records.json", r.stdout)
        self.assertIn("differs from git HEAD", r.stdout)

    def test_git_new_file_under_bob_blocks(self):
        self.sb.git_init()
        self.sb.put_run("local", BALANCED)
        self.assertEqual(self.weigh_local().returncode, 0)
        self.assertEqual(self.sb.gate(COMMIT).returncode, 0)
        (self.sb.root / ".bob").mkdir()
        (self.sb.root / ".bob" / "settings.json").write_text("{}", encoding="utf-8")
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn(".bob/settings.json", r.stdout)

    def test_git_always_allow_in_mcp_json_passes_any_other_bob_edit_blocks(self):
        mcp = self.sb.root / ".bob" / "mcp.json"
        mcp.parent.mkdir()
        server = {"command": "python", "args": ["${workspaceFolder}/tare/mcp_server.py"]}
        mcp.write_text(json.dumps({"mcpServers": {"tare": server}}, indent=2), encoding="utf-8")
        self.sb.git_init()
        self.sb.put_run("local", BALANCED)
        self.assertEqual(self.weigh_local().returncode, 0)
        allowed = dict(server, alwaysAllow=["weigh", "explain"])
        mcp.write_text(json.dumps({"mcpServers": {"tare": allowed}}), encoding="utf-8")
        self.assertEqual(self.sb.gate(COMMIT).returncode, 0, self.sb.gate(COMMIT).stdout)
        self.sb.git("add", ".bob/mcp.json")
        self.assertEqual(self.sb.gate(COMMIT).returncode, 0)
        mcp.write_text(json.dumps({"mcpServers": {"tare": dict(allowed, args=["other.py"])}}), encoding="utf-8")
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn(".bob/mcp.json", r.stdout)
        mcp.write_text(json.dumps({"mcpServers": {"tare": allowed}}), encoding="utf-8")
        self.sb.git("add", ".bob/mcp.json")
        self.assertEqual(self.sb.gate(COMMIT).returncode, 0)
        mcp.write_text(json.dumps({"mcpServers": {"tare": dict(allowed, env={"X": "1"})}}), encoding="utf-8")
        self.sb.git("add", ".bob/mcp.json")
        mcp.write_text(json.dumps({"mcpServers": {"tare": allowed}}), encoding="utf-8")
        self.assertEqual(self.sb.gate(COMMIT).returncode, 2)

    def test_git_hand_edit_of_accepted_blocks_but_tare_accept_is_sealed(self):
        self.sb.git_init()
        self.sb.put_run("local", BALANCED)
        self.assertEqual(self.weigh_local().returncode, 0)
        self.edit_cfg(lambda c: c["accepted"].append({"file": "totals", "key": "A10001", "fields": ["total_lb"],
                                                      "expect": {"total_lb": "9.99"}}))
        self.assertEqual(self.weigh_local().returncode, 0)
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("tare.json", r.stdout)
        self.sb.git("checkout", "--", "tare.json")
        self.sb.put_run("local", one_off())
        self.assertEqual(self.weigh_local().returncode, 1)
        a = self.sb.tare("accept", "--key", "A10001", "--by", "Owner", "--reason", "test")
        self.assertEqual(a.returncode, 0, a.stdout + a.stderr)
        self.assertEqual(self.weigh_local().returncode, 0)
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 0, r.stdout)


class D4Commands(unittest.TestCase):
    def test_commit_routes_are_caught(self):
        for c in ["Git commit -m x", "GIT commit -m x", 'cmd /c "GIT commit -m x"', "git merge --no-ff topic",
                  "git cherry-pick abc", "git revert HEAD", "git am x.patch", "git rebase --continue", "git pull",
                  "git commit-tree HEAD^{tree}", "git update-ref refs/heads/main abc", "git ci -m x",
                  "git config alias.ci commit", "git -c alias.ci=commit ci", "gh pr merge 1 --merge",
                  "python -c \"import subprocess; subprocess.run(['git','commit','-m','x'])\"",
                  "node -e \"require('child_process').execSync('git commit -m x')\"",
                  "pwsh -Command \"git commit -m x\"", "echo commit | xargs git",
                  r"C:\Program Files\Git\cmd\git.exe commit", "git --git-dir=.git commit", "git -C . push"]:
            self.assertTrue(gate.runs_git_write(c), c)

    def test_read_only_git_is_not_gated(self):
        for c in ["git status", "git log --grep commit", "git diff", "git show HEAD", "git add port/X.java",
                  "git merge-base HEAD main", "git fetch", "git stash", "python -m tare weigh --port local", "ls"]:
            self.assertFalse(gate.runs_git_write(c), c)

    def test_list_form_and_mcp_git_tools(self):
        p = {"tool": "execute_command", "input": {"command": ["git", "commit", "-m", "x"]}}
        self.assertTrue(any(gate.runs_git_write(c) for c in gate.command_strings(p)))
        m = {"tool": "use_mcp_tool", "input": {"server_name": "git", "tool_name": "git_commit",
                                               "arguments": {"message": "x"}}}
        self.assertTrue(gate.gated(m))
        self.assertFalse(gate.gated({"tool": "use_mcp_tool", "input": {"server_name": "tare", "tool_name": "weigh"}}))


class D4GitHooks(Base):
    def test_real_git_commit_is_refused_while_red(self):
        self.sb.git_init()
        i = self.sb.tare("install-hooks", env=self.sb.git_env)
        self.assertEqual(i.returncode, 0, i.stdout + i.stderr)
        self.sb.put_run("local", RED)
        self.assertEqual(self.weigh_local().returncode, 1)
        (self.sb.root / "port" / "Port.java").write_text("class Port { }\n", encoding="utf-8")
        self.sb.put_run("local", RED)
        self.assertEqual(self.weigh_local().returncode, 1)
        self.sb.git("add", "port")
        c = self.sb.git("commit", "-m", "red port")
        self.assertNotEqual(c.returncode, 0, c.stdout + c.stderr)
        self.assertIn("TARE: blocked", c.stderr)
        self.assertEqual(self.sb.git("rev-list", "--count", "HEAD").stdout.strip(), "1")
        self.sb.put_run("local", BALANCED)
        self.assertEqual(self.weigh_local().returncode, 0)
        c = self.sb.git("commit", "-m", "balanced port")
        self.assertEqual(c.returncode, 0, c.stdout + c.stderr)
        self.assertEqual(self.sb.git("rev-list", "--count", "HEAD").stdout.strip(), "2")


class D4GitHooksNoPreCommit(Base):
    def test_cherry_pick_revert_merge_refused_while_red(self):
        self.sb.git_init()
        g = self.sb.git
        g("checkout", "-q", "-b", "topic")
        (self.sb.root / "notes.txt").write_text("x", encoding="utf-8")
        g("add", "notes.txt")
        g("commit", "-q", "-m", "topic")
        topic = g("rev-parse", "HEAD").stdout.strip()
        g("checkout", "-q", "main")
        (self.sb.root / "other.txt").write_text("y", encoding="utf-8")
        g("add", "other.txt")
        g("commit", "-q", "-m", "main work")
        self.assertEqual(self.sb.tare("install-hooks", env=self.sb.git_env).returncode, 0)
        self.sb.put_run("local", RED)
        self.assertEqual(self.weigh_local().returncode, 1)
        for args in (["cherry-pick", topic], ["revert", "--no-edit", "HEAD"], ["merge", "--no-ff", "--no-edit", "topic"]):
            before = g("rev-parse", "HEAD").stdout.strip()
            r = g(*args)
            self.assertEqual(g("rev-parse", "HEAD").stdout.strip(), before, f"{args[0]} moved HEAD: {r.stderr}")
            self.assertIn("TARE: blocked", r.stderr, args[0])
            for abort in ("cherry-pick", "revert", "merge"):
                g(abort, "--abort")
            g("reset", "-q", "--hard", before)
        self.assertEqual(g("branch", "side").returncode, 0)
        (self.sb.root / "port" / "Port.java").write_text("class Port { int z; }\n", encoding="utf-8")
        self.assertEqual(g("stash").returncode, 0)


class D4CaseInSubfolder(Base):

    def test_subfolder_case(self):
        case = self.sb.root / "cases" / "one"
        case.mkdir(parents=True)
        for name in ("tare.json", "mainframe", "fixtures", "port"):
            shutil.move(str(self.sb.root / name), str(case / name))
        self.sb.git_init()
        env = self.sb.git_env

        def tare(*args):
            return subprocess.run([sys.executable, "-m", "tare", *args], cwd=case, env=env, capture_output=True,
                                  text=True, timeout=300)

        def gate_hook(payload):
            return subprocess.run([sys.executable, str(REPO / ".bob" / "hooks" / "gate.py")], cwd=case, env=env,
                                  input=json.dumps(payload), capture_output=True, text=True)

        self.assertEqual(tare("install-hooks").returncode, 0)
        d = case / "work" / "runs" / "local"
        d.mkdir(parents=True)
        (d / "records.json").write_text(json.dumps(dict(load(BALANCED), side="local")), encoding="utf-8")
        from tare import localport
        localport.write_provenance(case, d, jdk="test double")
        self.assertEqual(tare("weigh", "--port", "local", "--no-image").returncode, 0)
        self.assertEqual(gate_hook(COMMIT).returncode, 0)
        (case / "fixtures" / "answer_key" / "steps.log").write_text("edited\n", encoding="utf-8")
        r = gate_hook(COMMIT)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("cases/one/fixtures/answer_key/steps.log differs from git HEAD", r.stdout)
        (case / "notes.txt").write_text("x", encoding="utf-8")
        self.sb.git("add", "cases/one/notes.txt")
        c = self.sb.git("commit", "-m", "while the answer key is edited")
        self.assertNotEqual(c.returncode, 0, c.stdout + c.stderr)
        self.assertIn("TARE: blocked", c.stderr)
        self.sb.git("checkout", "--", "cases/one/fixtures/answer_key/steps.log")
        c = self.sb.git("commit", "-m", "notes")
        self.assertEqual(c.returncode, 0, c.stdout + c.stderr)


class D5AcceptCommand(Base):
    def test_accept_then_revoke(self):
        self.sb.put_run("local", one_off())
        self.assertEqual(self.weigh_local().returncode, 1)
        a = self.sb.tare("accept", "--key", "A10001", "--by", "Jane Owner", "--reason", "known difference")
        self.assertEqual(a.returncode, 0, a.stdout + a.stderr)
        self.assertIn("total_lb", a.stdout)
        self.assertIn("10.09", a.stdout)
        self.assertIn("10.10", a.stdout)
        self.assertLessEqual(len(a.stdout.splitlines()), 10, a.stdout)
        e = next(e for e in self.sb.cfg()["accepted"] if e["key"] == "A10001")
        self.assertEqual((e["file"], e["fields"], e["expect"], e["accepted_by"], e["reason"]),
                         ("totals", ["total_lb"], {"total_lb": "10.10"}, "Jane Owner", "known difference"))
        self.assertEqual(e["seal"], ledger.entry_seal(e))
        w = self.weigh_local()
        self.assertEqual(w.returncode, 0, w.stdout)
        self.assertIn("(1 accepted difference)", w.stdout)
        r = self.sb.tare("accept", "--revoke", "--key", "A10001")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.weigh_local().returncode, 1)

    def test_accept_pinned_to_the_answer_key_stays_red(self):
        self.sb.put_run("local", one_off())
        a = self.sb.tare("accept", "--key", "A10001", "--by", "Jane Owner", "--reason", "reviewed",
                         "--expect", "answer_key")
        self.assertEqual(a.returncode, 0, a.stdout + a.stderr)
        self.assertIn("still red", a.stdout)
        self.assertEqual(self.weigh_local().returncode, 1)

    def test_accept_needs_a_difference_and_a_known_record(self):
        self.sb.put_run("local", BALANCED)
        self.assertNotEqual(self.sb.tare("accept", "--key", "A10001", "--by", "x", "--reason", "y").returncode, 0)
        self.assertNotEqual(self.sb.tare("accept", "--key", "NOPE", "--by", "x", "--reason", "y").returncode, 0)


class D6ExplainFreshClone(Base):
    def test_port_value_from_the_recorded_fixture(self):
        from tare import explain
        t = explain.explain(self.sb.root, port="halfup")
        self.assertIn("10.10", t)
        self.assertIn("RECORDED OUTPUT", t)
        self.assertNotIn("no records.json", t)
        self.assertIn("ports/halfup/Port.java:46", t)


class D7FindJdk(unittest.TestCase):
    def test_finds_jdk17_without_java_home_or_javac_on_path(self):
        from tare import localport
        env = dict(os.environ)
        env.pop("JAVA_HOME", None)
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                      if not (Path(p) / ("javac.exe" if os.name == "nt" else "javac")).is_file())
        roots = [Path(r"C:\Program Files\Eclipse Adoptium"), Path("/usr/lib/jvm")]
        if not any(r.is_dir() for r in roots):
            self.skipTest("no JDK install root on this machine")
        found = localport.find_jdk(env=env)
        self.assertIsNotNone(found)
        home, major, version = found
        self.assertGreaterEqual(major, 17)
        self.assertTrue((home / "bin" / ("javac.exe" if os.name == "nt" else "javac")).is_file())

    def test_rejects_old_jdk(self):
        from tare import localport
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / "bin").mkdir()
            (home / "bin" / ("javac.exe" if os.name == "nt" else "javac")).write_text("", encoding="utf-8")
            (home / "release").write_text('JAVA_VERSION="1.8.0_481"\n', encoding="utf-8")
            self.assertEqual(localport.jdk_major(home), 8)
            (home / "release").write_text('JAVA_VERSION="21.0.12.1"\n', encoding="utf-8")
            self.assertEqual(localport.jdk_major(home), 21)


class D8McpRobust(Base):
    def test_batch_and_non_objects_do_not_crash(self):
        lines = ["[1,2]", "5", "[]", json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"})]
        r = subprocess.run([sys.executable, "-m", "tare.mcp_server"], cwd=self.sb.root, env=self.sb.env(),
                           input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=60)
        out = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([m["error"]["code"] for m in out[0]], [-32600, -32600])
        self.assertEqual(out[1]["error"]["code"], -32600)
        self.assertEqual(out[2]["error"]["code"], -32600)
        self.assertEqual(out[3], {"jsonrpc": "2.0", "id": 9, "result": {}})

    def test_side_and_key_validation(self):
        call = lambda i, name, args: {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                      "params": {"name": name, "arguments": args}}
        out, _ = session(self.sb, [call(1, "explain", {"key": "A10001", "side": "../x.json"}),
                                   call(2, "explain", {"key": "A10001", "side": 123}),
                                   call(3, "explain", {"key": "1" * 100000}),
                                   call(4, "explain", {"file": "../../etc"}),
                                   call(5, "weigh", {"side": "nosuchside"})])
        for m in out:
            self.assertTrue(m["result"]["isError"], m)
            text = m["result"]["content"][0]["text"]
            self.assertLess(len(text), 400, text[:400])
            self.assertNotIn("TypeError", text)


class D9HookLauncher(Base):
    def run_hook(self, cwd, payload):
        cmd = json.loads((REPO / ".bob" / "settings.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0][
            "hooks"][0]["command"]
        argv = f'cmd /d /s /c "{cmd}"' if os.name == "nt" else ["sh", "-c", cmd]
        return subprocess.run(argv, cwd=cwd, env=self.sb.env(), input=json.dumps(payload), capture_output=True,
                              text=True, timeout=60)

    def setUp(self):
        super().setUp()
        (self.sb.root / ".bob" / "hooks").mkdir(parents=True)
        shutil.copy(REPO / ".bob" / "hooks" / "gate.py", self.sb.root / ".bob" / "hooks" / "gate.py")

    def test_from_root_and_subfolder(self):
        read = {"tool": "read_file", "input": {"path": "x"}}
        for cwd in (self.sb.root, self.sb.root / "port"):
            r = self.run_hook(cwd, read)
            self.assertEqual(r.returncode, 0, f"{cwd}: {r.stdout}{r.stderr}")
            r = self.run_hook(cwd, COMMIT)
            self.assertEqual(r.returncode, 2, f"{cwd}: {r.stdout}{r.stderr}")

    def test_outside_the_repo_does_not_block(self):
        with tempfile.TemporaryDirectory() as td:
            r = self.run_hook(td, {"tool": "read_file", "input": {"path": "x"}})
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_non_git_call_is_fast(self):
        read = {"tool": "read_file", "input": {"path": "x"}}
        bare, hook = [], []
        for _ in range(3):
            t = time.perf_counter()
            subprocess.run("python -c pass" if os.name == "nt" else ["python3", "-c", "pass"], env=self.sb.env())
            bare.append(time.perf_counter() - t)
            t = time.perf_counter()
            self.assertEqual(self.run_hook(self.sb.root / "port", read).returncode, 0)
            hook.append(time.perf_counter() - t)
        self.assertLess(min(hook) - min(bare), 0.3, (bare, hook))


class D10Completion(Base):
    def test_completion_allowed_with_a_red_notice(self):
        self.sb.put_run("local", RED)
        self.assertEqual(self.weigh_local().returncode, 1)
        r = self.sb.gate(DONE)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("red", r.stdout + r.stderr)
        self.assertEqual(self.sb.gate(COMMIT).returncode, 2)


if __name__ == "__main__":
    unittest.main()
