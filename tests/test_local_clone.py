"""The port under test as a case declares it: a runner in tare.json sides.local, a nested git clone under
port/ with the gate's hooks, `git -C port commit` routed to the case."""
import json
import tempfile
import unittest

from tare import config, gate
from tests.helpers import BALANCED, RED, Sandbox

RUNNER = '''import argparse, pathlib, shutil
ap = argparse.ArgumentParser()
ap.add_argument("--input"); ap.add_argument("--out"); ap.add_argument("--sandbox")
a = ap.parse_args()
out = pathlib.Path(a.out)
shutil.copyfile("fixtures/answer_key/totals.dat", out / "totals.dat")
pathlib.Path(a.sandbox, "ran.txt").write_text(" ".join(sorted(p.name for p in pathlib.Path(a.input).iterdir())))
'''


class LocalRunner(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        (self.sb.root / "sides").mkdir()
        (self.sb.root / "sides" / "runlocal.py").write_text(RUNNER, encoding="utf-8")
        cfg = self.sb.cfg()
        cfg["sides"]["local"] = {"runner": "python sides/runlocal.py", "line": "port/Port.java:1  the port"}
        (self.sb.root / "tare.json").write_text(json.dumps(cfg), encoding="utf-8")

    def tearDown(self):
        self.sb.close()

    def test_declared_runner_builds_and_runs_the_port_in_its_sandbox(self):
        w = self.sb.tare("weigh", "--port", "local", "--no-image")
        self.assertEqual(w.returncode, 0, w.stdout + w.stderr)
        self.assertIn("python sides/runlocal.py --input work/sandbox/local/input --out work/runs/local "
                      "--sandbox work/sandbox/local", w.stdout)
        self.assertEqual((self.sb.root / "work/sandbox/local/ran.txt").read_text(), "items.dat")
        prov = json.loads((self.sb.root / "work/runs/local/provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(prov["main"], "python sides/runlocal.py")
        self.assertEqual(list(prov["sources"]), ["port/MAIN", "port/Port.java"])
        self.assertEqual(self.sb.gate({"tool": "execute_command", "input": {"command": "git commit -m x"}})
                         .returncode, 0)
        # an edit to the port's Java makes the weigh stale: the gate blocks, the next weigh reruns the runner
        (self.sb.root / "port" / "Port.java").write_text("class Port { int x; }\n", encoding="utf-8")
        g = self.sb.gate({"tool": "execute_command", "input": {"command": "git commit -m x"}})
        self.assertEqual(g.returncode, 2)
        self.assertIn("The port changed after the last weigh (port/Port.java)", g.stdout)
        w = self.sb.tare("weigh", "--port", "local", "--no-image")
        self.assertIn("the port's sources changed since its last run; ran the port first.", w.stdout)

    def test_no_port_sources_is_an_error(self):
        (self.sb.root / "port" / "Port.java").unlink()
        w = self.sb.tare("weigh", "--port", "local", "--no-image")
        self.assertNotEqual(w.returncode, 0)
        self.assertIn("no port sources under port/", w.stderr)

    def test_the_runner_is_protected(self):
        self.assertIn("sides", config.PROTECTED)


class NestedClone(unittest.TestCase):
    """port/ is a git repository of its own, ignored by the repository holding the case."""

    def setUp(self):
        self.sb = Sandbox()
        sb = self.sb
        sb.git_init()
        (sb.root / ".gitignore").write_text("/work/\n/.tare/\n__pycache__/\n/port/\n", encoding="utf-8")
        for args in (["rm", "-r", "-q", "--cached", "port"], ["add", ".gitignore"], ["commit", "-q", "-m", "ignore port"]):
            r = sb.git(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "published port"]):
            r = self.port_git(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
        i = sb.tare("install-hooks", "--repo", "port", env=sb.git_env)
        self.assertEqual(i.returncode, 0, i.stdout + i.stderr)

    def tearDown(self):
        self.sb.close()

    def port_git(self, *args):
        return self.sb.git("-C", "port", *args)

    def commits(self):
        return self.port_git("rev-list", "--count", "HEAD").stdout.strip()

    def weigh(self, doc):
        self.sb.put_run("local", doc)
        return self.sb.tare("weigh", "--port", "local", "--no-image").returncode

    def test_commit_in_the_clone_follows_the_case_weigh(self):
        port = self.sb.root / "port" / "Port.java"
        port.write_text("class Port { int repaired; }\n", encoding="utf-8")
        self.assertEqual(self.weigh(RED), 1)
        c = self.port_git("commit", "-q", "-am", "x")
        self.assertNotEqual(c.returncode, 0, c.stdout + c.stderr)
        self.assertIn("TARE: blocked", c.stderr)
        self.assertEqual(self.commits(), "1")
        self.assertEqual(self.weigh(BALANCED), 0)
        c = self.port_git("commit", "-q", "-am", "x")
        self.assertEqual(c.returncode, 0, c.stdout + c.stderr)
        self.assertEqual(self.commits(), "2")
        # an edit after the balanced weigh: stale, blocked
        port.write_text("class Port { int again; }\n", encoding="utf-8")
        c = self.port_git("commit", "-q", "-am", "y")
        self.assertIn("The port changed after the last weigh", c.stderr)
        self.assertEqual(self.commits(), "2")

    def test_protected_paths_of_the_outer_repository_still_apply(self):
        (self.sb.root / "port" / "Port.java").write_text("class Port { int b; }\n", encoding="utf-8")
        self.assertEqual(self.weigh(BALANCED), 0)
        log = self.sb.root / "fixtures" / "answer_key" / "steps.log"
        before = log.read_bytes()
        log.write_text("edited\n", encoding="utf-8")
        c = self.port_git("commit", "-q", "-am", "x")
        self.assertIn("fixtures/answer_key/steps.log differs from git HEAD", c.stderr)
        self.assertEqual(self.commits(), "1")
        log.write_bytes(before)
        c = self.port_git("commit", "-q", "-am", "x")
        self.assertEqual(c.returncode, 0, c.stdout + c.stderr)

    def test_bob_payload_with_git_c_goes_to_the_case(self):
        payload = {"tool": "execute_command",
                   "input": {"command": f'git -C "{(self.sb.root / "port").as_posix()}" commit -am x'}}
        with tempfile.TemporaryDirectory() as elsewhere:
            self.assertEqual(gate.case_for(payload, cwd=elsewhere), self.sb.root.resolve())
        self.assertIsNone(gate.case_for({"tool": "execute_command", "input": {"command": "git commit -m x"}}))
        self.assertEqual(self.weigh(RED), 1)
        r = self.sb.gate({"tool": "execute_command", "input": {"command": "git -C port commit -am x"}})
        self.assertEqual(r.returncode, 2, r.stdout)


if __name__ == "__main__":
    unittest.main()
