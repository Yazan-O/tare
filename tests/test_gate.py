import io
import json
import os
import time
import unittest

from tare import gate
from tests.helpers import BALANCED, RED, Sandbox

COMMIT = {"tool": "execute_command", "input": {"command": "git commit -m x"}}


class GateExitCodes(unittest.TestCase):

    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.close()

    def weigh(self, side, doc):
        self.sb.put_run(side, doc)
        return self.sb.tare("weigh", "--port", side, "--no-image")

    def test_commit_without_weigh_blocks(self):
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("No weigh on record", r.stdout)
        self.assertIn("No weigh on record", r.stderr)

    def test_red_weigh_blocks(self):
        self.assertEqual(self.weigh("local", RED).returncode, 1)
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 2)
        self.assertIn("3 of 5 records differ from the answer key (total_lb: 3 higher, 0 lower, net +0.03)", r.stdout)

    def test_balanced_weigh_allows(self):
        self.assertEqual(self.weigh("local", BALANCED).returncode, 0)
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.sb.gate({"tool": "execute_command",
                                       "input": {"command": "cd port && git -C .. push origin main"}}).returncode, 0)

    def test_edit_after_balanced_weigh_blocks(self):
        self.assertEqual(self.weigh("local", BALANCED).returncode, 0)
        (self.sb.root / "port" / "Port.java").write_text("class Port { int x; }\n", encoding="utf-8")
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 2)
        self.assertIn("The port changed after the last weigh", r.stdout)

    def test_new_port_file_after_weigh_blocks(self):
        self.assertEqual(self.weigh("local", BALANCED).returncode, 0)
        (self.sb.root / "port" / "Extra.java").write_text("class Extra {}\n", encoding="utf-8")
        self.assertEqual(self.sb.gate(COMMIT).returncode, 2)

    def test_other_commands_pass(self):
        r = self.sb.gate({"tool": "execute_command", "input": {"command": "ls"}})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")

    def test_malformed_payload_blocks(self):
        r = self.sb.gate("{not json")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not JSON", r.stdout)

    def test_red_public_port_does_not_block_local(self):
        self.assertEqual(self.weigh("local", BALANCED).returncode, 0)
        self.assertEqual(self.weigh("halfup", RED).returncode, 1)
        r = self.sb.gate(COMMIT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_empty_port_allows_commit(self):
        sb = Sandbox(with_port=False)
        try:
            self.assertEqual(sb.gate(COMMIT).returncode, 0)
            self.assertEqual(sb.gate({"tool": "attempt_completion", "input": {"result": "done"}}).returncode, 0)
        finally:
            sb.close()

    def test_completion_is_never_trapped(self):
        done = {"tool": "attempt_completion", "input": {"result": "Port finished."}}
        r = self.sb.gate(done)
        self.assertEqual(r.returncode, 0)
        self.assertIn("completion allowed, but the port is red or not weighed", r.stdout)
        self.weigh("local", BALANCED)
        r = self.sb.gate(done)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_non_commit_is_fast_and_logged(self):
        t = time.perf_counter()
        r = self.sb.gate({"tool": "read_file", "input": {"path": "x"}})
        dt = time.perf_counter() - t
        self.assertEqual(r.returncode, 0)
        self.assertLess(dt, 1.0)
        log = (self.sb.root / ".tare" / "hook_payloads.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(log[-1])["tool"], "read_file")


class CommandParsing(unittest.TestCase):
    def test_detects_commit_and_push(self):
        for c in ["git commit -m x", "cd port && git commit -am 'fix'", "npm test; git push",
                  "git -C port commit -m x", "git -c user.name=x commit", "/usr/bin/git push origin main",
                  'sh -c "git commit -m y"', "bash -lc 'cd a && git push'", "git --no-pager commit",
                  "git.exe commit -m x", r"C:\Git\bin\git.exe push"]:
            self.assertTrue(gate.runs_git_write(c), c)

    def test_ignores_other_git(self):
        for c in ["git status", "git log --grep commit", "git diff", "ls", "echo hi", "git show HEAD",
                  "git add port/Port.java"]:
            self.assertFalse(gate.runs_git_write(c), c)

    def test_file_content_is_not_a_command(self):
        p = {"tool": "write_to_file", "input": {"path": "README.md", "content": "then run git commit"}}
        self.assertEqual(gate.command_strings(p), [])

    def test_unknown_shape_scans_strings(self):
        p = {"something": {"deep": ["git push"]}}
        self.assertTrue(any(gate.runs_git_write(c) for c in gate.command_strings(p)))


class LogCap(unittest.TestCase):
    def test_keeps_last_500(self):
        sb = Sandbox()
        os.environ["TARE_ROOT"] = str(sb.root)
        try:
            for i in range(510):
                self.assertEqual(gate.main(io.StringIO(json.dumps({"tool": "read_file", "i": i}))), 0)
            lines = (sb.root / ".tare" / "hook_payloads.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 500)
            self.assertEqual(json.loads(lines[-1])["payload"]["i"], 509)
        finally:
            os.environ.pop("TARE_ROOT", None)
            sb.close()


if __name__ == "__main__":
    unittest.main()
