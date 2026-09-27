"""The gate on a case that declares its own port under test (tare.json 'gate'): the Medicare hospice case.

The case is copied into a throwaway git repository; its side under test is java-ai-fixed, guarded through
sides/ai_port_fixes.json and sides/fix_port.py. Weighs read the committed fixtures, so no JDK is needed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tare import config
from tests.helpers import EXAMPLE, REPO

CASE = REPO / "cases" / "medicare_hospice"
COMMIT = {"tool": "execute_command", "input": {"command": "git commit -am x"}}
FIXES = "sides/ai_port_fixes.json"


class MedicareGate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # Windows may hold a handle briefly
        self.top = Path(self.dir.name)
        self.case = self.top / "cases" / "medicare_hospice"
        shutil.copytree(CASE, self.case, ignore=shutil.ignore_patterns(".tare", "cache", "work", "__pycache__"))
        other = self.top / "cases" / "unitsum"
        shutil.copytree(EXAMPLE, other)
        (self.top / ".gitignore").write_text("**/work/\n**/.tare/\n**/cache/\n__pycache__/\n", encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("TARE_ROOT", "TARE_MAINTAINER", "GITHUB_STEP_SUMMARY", "GIT_INDEX_FILE")}
        self.env.update(PYTHONPATH=str(REPO), GIT_CONFIG_NOSYSTEM="1",
                        GIT_CONFIG_GLOBAL=str(self.top / "no-gitconfig"), GIT_AUTHOR_NAME="t",
                        GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
            r = subprocess.run(["git", *args], cwd=self.top, env=self.env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def tearDown(self):
        self.dir.cleanup()

    def gate(self, cwd=None):
        return subprocess.run([sys.executable, str(REPO / ".bob" / "hooks" / "gate.py")], cwd=cwd or self.case,
                              env=self.env, input=json.dumps(COMMIT), capture_output=True, text=True)

    def weigh(self, side="java-ai-fixed"):
        return subprocess.run([sys.executable, "-m", "tare", "weigh", "--port", side, "--no-image"],
                              cwd=self.case, env=self.env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300)

    def assertBlocked(self, r, text):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("TARE: blocked. ", r.stdout)
        self.assertIn(text, r.stdout)

    def test_declared_gate(self):
        g = config.gate_spec(config.load_config(CASE))
        self.assertEqual(g, {"side": "java-ai-fixed", "sources": (FIXES, "sides/fix_port.py")})

    def test_no_weigh_blocks(self):
        self.assertBlocked(self.gate(), "No weigh on record for the port under test (java-ai-fixed). "
                                        "Run weigh with side java-ai-fixed.")

    def test_red_weigh_blocks(self):
        run = self.case / "work" / "runs" / "java-ai-fixed"
        run.mkdir(parents=True)
        doc = json.loads((self.case / "fixtures" / "sides" / "java-ai" / "records.json").read_text(encoding="utf-8"))
        (run / "records.json").write_text(json.dumps(dict(doc, side="java-ai-fixed")), encoding="utf-8")
        self.assertEqual(self.weigh().returncode, 1)
        self.assertBlocked(self.gate(), "270 of 5000 records differ from the answer key")

    def test_balanced_allows_then_a_stale_edit_blocks(self):
        w = self.weigh()
        self.assertEqual(w.returncode, 0, w.stdout + w.stderr)
        r = self.gate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        fixes = self.case / FIXES
        before = fixes.read_bytes()
        fixes.write_bytes(before + b"\n")
        self.assertBlocked(self.gate(), f"The port changed after the last weigh ({FIXES}). "
                                        "Weigh it again with side java-ai-fixed.")
        # a weigh of the committed fixture says nothing about the edited repair
        self.assertEqual(self.weigh().returncode, 0)
        self.assertBlocked(self.gate(), "not a run of the edited port")
        fixes.write_bytes(before)
        self.assertEqual(self.weigh().returncode, 0)
        self.assertEqual(self.gate().returncode, 0)

    def test_other_protected_files_stay_read_only(self):
        self.assertEqual(self.weigh().returncode, 0)
        p = self.case / "sides" / "port_runner.py"
        p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.assertBlocked(self.gate(), "sides/port_runner.py differs from git HEAD")

    def test_a_commit_from_another_case_that_touches_medicare_is_gated(self):
        unitsum = self.top / "cases" / "unitsum"
        self.assertEqual(self.gate(cwd=unitsum).returncode, 0)  # nothing touched outside unitsum
        readme = self.case / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.assertBlocked(self.gate(cwd=unitsum), "(java-ai-fixed). Run weigh with side java-ai-fixed. "
                                                   "(case medicare_hospice)")
        self.assertEqual(self.weigh().returncode, 0)
        self.assertEqual(self.gate(cwd=unitsum).returncode, 0)

    def test_an_edited_gate_field_blocks(self):
        self.assertEqual(self.weigh().returncode, 0)
        p = self.case / "tare.json"
        cfg = json.loads(p.read_text(encoding="utf-8"))
        cfg["gate"]["side"] = "cms-java"
        p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.assertBlocked(self.gate(), "cases/medicare_hospice/tare.json differs from git HEAD")


class GateSpec(unittest.TestCase):
    def test_sources_cannot_name_read_only_paths(self):
        cfg = {"sides": {"x": {}}}
        for bad in ("tare.json", "fixtures/**", "tare/gate.py", ".bob/mcp.json", "../x", "/abs", "a\\b"):
            with self.assertRaises(ValueError, msg=bad):
                config.gate_spec(dict(cfg, gate={"side": "x", "sources": [bad]}))
        for bad in ({"side": "local", "sources": ["port/X"]}, {"side": "nope", "sources": ["sides/x"]},
                    {"side": "x", "sources": []}):
            with self.assertRaises(ValueError, msg=str(bad)):
                config.gate_spec(dict(cfg, gate=bad))
        self.assertIsNone(config.gate_spec(cfg))

    def test_glob_regex(self):
        rx = config.glob_regex("port/**/*.java")
        self.assertTrue(rx.match("port/A.java") and rx.match("port/a/b/C.java"))
        self.assertFalse(rx.match("port/A.javax") or rx.match("sides/A.java"))

    def test_without_git_the_pinned_policy_applies(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            root = Path(d)
            shutil.copy(EXAMPLE / "tare.json", root / "tare.json")
            for sub in ("mainframe", "fixtures", "ports"):
                shutil.copytree(EXAMPLE / sub, root / sub)
            cfg = json.loads((root / "tare.json").read_text(encoding="utf-8"))
            cfg["gate"] = {"side": "exact", "sources": ["ports/exact/*"]}
            (root / "tare.json").write_text(json.dumps(cfg), encoding="utf-8")
            (root / "port").mkdir()
            (root / "port" / "Port.java").write_text("class Port {}\n", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k not in ("TARE_ROOT", "TARE_MAINTAINER")}
            env.update(PYTHONPATH=str(REPO), GIT_CEILING_DIRECTORIES=str(root.parent))
            r = subprocess.run([sys.executable, "-m", "tare", "weigh", "--port", "exact", "--no-image"], cwd=root,
                               env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run([sys.executable, str(REPO / ".bob" / "hooks" / "gate.py")], cwd=root, env=env,
                               input=json.dumps(COMMIT), capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stdout)
            self.assertIn("No weigh on record for the port under test (local).", r.stdout)


if __name__ == "__main__":
    unittest.main()
