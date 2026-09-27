import json
import unittest

from tests.helpers import BALANCED, RED, Sandbox, has_jdk, load

COMMIT = {"tool": "execute_command", "input": {"command": "git commit -m port"}}


@unittest.skipUnless(has_jdk(), "no JDK >= 17 on this machine")
class Loop(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.close()

    def weigh(self):
        return self.sb.tare("weigh", "--port", "local", "--no-image")

    def test_correct_port_balances_and_commits(self):
        self.sb.use_port("exact")
        w = self.weigh()
        self.assertEqual(w.returncode, 0, w.stdout + w.stderr)
        self.assertIn("weigh: 5 of 5 records balance", w.stdout)
        run = json.loads((self.sb.root / "work" / "runs" / "local" / "records.json").read_text(encoding="utf-8"))
        self.assertEqual(run["files"], load(BALANCED)["files"])
        g = self.sb.gate(COMMIT)
        self.assertEqual((g.returncode, g.stdout), (0, ""))

    def test_half_up_port_is_red_explained_and_accepted(self):
        self.sb.use_port("halfup")
        w = self.weigh()
        self.assertEqual(w.returncode, 1, w.stdout + w.stderr)
        self.assertIn("weigh: 3 of 5 records differ", w.stdout)
        self.assertEqual(json.loads((self.sb.root / "work" / "runs" / "local" / "records.json")
                                    .read_text(encoding="utf-8"))["files"], load(RED)["files"])
        g = self.sb.gate(COMMIT)
        self.assertEqual(g.returncode, 2)
        self.assertIn("TARE: blocked. 3 of 5 records differ from the answer key", g.stdout)
        e = self.sb.tare("explain", "--key", "B20003", "--field", "total_lb")
        self.assertEqual(e.returncode, 0, e.stderr)
        self.assertIn("mainframe/cbl/UNITSUM.cbl:100", e.stdout)
        self.assertIn("COMPUTE OUT-TOTAL-LB = OUT-TOTAL-KG * 2.20462", e.stdout)
        self.assertIn("= 3.270 * 2.20462 = 7.2091074", e.stdout)
        self.assertIn("port wrote               7.21   matches half-up (ROUNDED)", e.stdout)
        for key in ("A10001", "B20003", "C30005"):
            a = self.sb.tare("accept", "--key", key, "--by", "Test Owner", "--reason", "self-test")
            self.assertEqual(a.returncode, 0, a.stdout + a.stderr)
        w = self.weigh()
        self.assertEqual(w.returncode, 0, w.stdout)
        self.assertIn("weigh: 5 of 5 records balance (3 accepted differences)", w.stdout)
        self.assertEqual(self.sb.gate(COMMIT).returncode, 0)
        self.sb.use_port("exact")
        self.assertEqual(self.weigh().returncode, 0)

    def test_declared_sides_run_like_the_port(self):
        for side, want in (("exact", BALANCED), ("halfup", RED)):
            r = self.sb.tare("run-port", side)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            got = json.loads((self.sb.root / "work" / "runs" / side / "records.json").read_text(encoding="utf-8"))
            self.assertEqual(got["files"], load(want)["files"])
            self.assertEqual(got["command"], f"python -m tare run-port {side}")


if __name__ == "__main__":
    unittest.main()
