"""reproduce, check and reset on the test fixture; the recorded-fixture fallbacks; the scale; the contract."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tare import contract, ledger, scale
from tests.helpers import ANSWER, BALANCED, RED, Sandbox, load

CFG = load("tare.json")


class ReproduceCommand(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(with_port=False)

    def tearDown(self):
        self.sb.close()

    def edit_cfg(self, fn):
        cfg = self.sb.cfg()
        fn(cfg)
        (self.sb.root / "tare.json").write_text(json.dumps(cfg), encoding="utf-8")

    def test_offline_all_expected(self):
        r = self.sb.tare("reproduce", "--offline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("reproduce: OK, all 2 sides got their expected verdict", r.stdout)
        self.assertIn("3 of 5 records differ from the answer key (total_lb: 3 higher, 0 lower, net +0.03)", r.stdout)
        self.assertEqual(r.stdout.count("(recorded)"), 2)
        for side in ("exact", "halfup"):
            self.assertTrue((self.sb.root / ".tare" / f"weigh_{side}.json").is_file(), side)

    def test_no_cobol_toolchain_falls_back_to_recorded(self):
        env = self.sb.env()
        bare = self.sb.root / "empty-path"
        bare.mkdir()
        env["PATH"] = str(bare)
        r = self.sb.tare("reproduce", env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("answer key: cobc, cobcrun not found", r.stdout)

    def test_unsound_answer_key_stops_before_any_weigh(self):
        dat = self.sb.root / "fixtures" / "answer_key" / "totals.dat"
        data = bytearray(dat.read_bytes())
        data[40 + 6] = ord("X")  # record 2, the first digit of count PIC 9(03)
        dat.write_bytes(bytes(data))
        r = self.sb.tare("reproduce", "--offline")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("answer key unsound: field count in record 2 of totals is not a valid 9 number", r.stdout)
        self.assertNotIn("Scoreboard", r.stdout)
        self.assertFalse((self.sb.root / ".tare" / "weigh_exact.json").exists())
        c = self.sb.tare("check", "exact", "--offline")
        self.assertEqual(c.returncode, 2, c.stdout + c.stderr)
        self.assertIn("answer key unsound", c.stdout)

    def test_unexpected_verdict_fails(self):
        self.edit_cfg(lambda c: c["expected"].update(halfup="balanced"))
        r = self.sb.tare("reproduce", "--offline")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("unexpected verdict: halfup", r.stdout)

    def test_every_side_needs_an_expected_verdict(self):
        self.edit_cfg(lambda c: c["expected"].pop("halfup"))
        self.assertEqual(self.sb.tare("reproduce", "--offline").returncode, 2)

    def test_no_sides_reproduces_the_answer_key_only(self):
        self.edit_cfg(lambda c: c.update(sides={}, expected={}))
        r = self.sb.tare("reproduce", "--offline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("reproduce: OK (answer key only)", r.stdout)

    def test_check_summary_and_exit_codes(self):
        summary = self.sb.root / "summary.md"
        red = self.sb.tare("check", "halfup", "--offline", "--summary", str(summary))
        ok = self.sb.tare("check", "exact", "--offline", "--summary", str(summary))
        self.assertEqual((red.returncode, ok.returncode), (1, 0), red.stdout + ok.stdout)
        md = summary.read_text(encoding="utf-8")
        first = md.split("## Tare: halfup\n\n", 1)[1].splitlines()
        self.assertIn("TARE RED  halfup vs answer_key", first[0])
        self.assertEqual(first[2], "Port line: `" + CFG["sides"]["halfup"]["line"] + "`")
        self.assertIn("| records | differ | fields differ |", md)
        self.assertIn("## Tare: exact", md)
        self.assertEqual(self.sb.tare("check", "local", "--offline").returncode, 2)

    def test_command_runner_side(self):
        """A side whose runner is a command: it writes <out>/totals.dat and Tare decodes it."""
        d = self.sb.root / "ports" / "copy"
        d.mkdir(parents=True)
        (d / "run.py").write_text(
            "import argparse, pathlib, shutil\n"
            "ap = argparse.ArgumentParser(); ap.add_argument('--input'); ap.add_argument('--out')\n"
            "a = ap.parse_args(); pathlib.Path(a.out).mkdir(parents=True, exist_ok=True)\n"
            "shutil.copy('fixtures/answer_key/totals.dat', pathlib.Path(a.out) / 'totals.dat')\n",
            encoding="utf-8")
        self.edit_cfg(lambda c: (c["sides"].update(copy={"runner": "python ports/copy/run.py", "line": "run.py:4"}),
                                 c["expected"].update(copy="balanced")))
        r = self.sb.tare("check", "copy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("weigh: 5 of 5 records balance", r.stdout)

    def test_reset(self):
        sd = self.sb.root / ".tare"
        sd.mkdir()
        for n in ("weigh_local.json", "last_weigh.json", "weigh_halfup.json", "hook_payloads.log"):
            (sd / n).write_text("{}", encoding="utf-8")
        r = self.sb.tare("reset")
        self.assertEqual(r.returncode, 0)
        self.assertIn("removed .tare/weigh_local.json, .tare/last_weigh.json", r.stdout)
        self.assertEqual(sorted(p.name for p in sd.iterdir()), ["hook_payloads.log", "weigh_halfup.json"])
        self.assertIn("nothing to remove", self.sb.tare("reset").stdout)


class McpRecordedFallback(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(with_port=False)

    def tearDown(self):
        self.sb.close()

    def call(self, name, side):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": name, "arguments": {"side": side}}}]
        r = subprocess.run([sys.executable, "-m", "tare.mcp_server"], cwd=self.sb.root, env=self.sb.env(),
                           input="".join(json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True,
                           timeout=120)
        return json.loads(r.stdout.splitlines()[0])["result"]

    def test_weigh_without_run_uses_fixture(self):
        res = self.call("weigh", "halfup")
        text = res["content"][0]["text"]
        self.assertFalse(res["isError"], text)
        self.assertTrue(text.startswith("RECORDED OUTPUT (committed fixture, produced by: python -m tare "
                                        "run-port halfup)"), text)
        rec = json.loads((self.sb.root / ".tare" / "weigh_halfup.json").read_text(encoding="utf-8"))
        self.assertTrue(rec["recorded"].startswith("RECORDED OUTPUT"))

    def test_local_never_falls_back(self):
        for tool in ("run_port", "weigh"):
            res = self.call(tool, "local")
            self.assertTrue(res["isError"], tool)
            self.assertNotIn("RECORDED", res["content"][0]["text"])
        self.assertFalse((self.sb.root / "work" / "runs" / "local" / "records.json").exists())


class ScaleLayout(unittest.TestCase):
    def states(self):
        a = load(ANSWER)
        out = [(ledger.weigh(a, load(doc), CFG)["summary"], side) for doc, side in ((BALANCED, "exact"),
                                                                                    (RED, "halfup"))]
        out.append((ledger.weigh(a, dict(load(BALANCED), files={"totals": []}), CFG)["summary"], "nothing"))
        worst = dict(out[1][0], records_total=99999, records_differ=99999, higher=99999)
        out.append((worst, "a-long-side-name-40-characters-long-xxxx"))
        return out

    def test_details(self):
        d = {side: scale.details(s) for s, side in self.states()}
        self.assertEqual(d["halfup"], ["3 of 5 records differ"])
        self.assertEqual(d["nothing"], ["0 of 5 written"])
        self.assertEqual(scale.display("halfup"), "PORT HALFUP")

    def test_bottom_margin(self):
        with tempfile.TemporaryDirectory() as td:
            for s, side in self.states():
                p = scale.render(s, side, Path(td) / f"{side}.png", program="UNITSUM")
                bottom = scale.ink_bottom(p)
                self.assertGreater(bottom, 0, side)
                self.assertLess(bottom, scale.H - scale.MARGIN, f"{side}: ink at row {bottom}")


class Contract(unittest.TestCase):
    def test_contract_is_generated_from_the_layouts(self):
        sb = Sandbox(with_port=False)
        try:
            text = contract.render(sb.root)
        finally:
            sb.close()
        self.assertTrue(text.startswith("# Port contract: UNITSUM"))
        self.assertIn("| 27 | 10 | `total_lb` | OUT-TOTAL-LB | S9(8)V9(2) |", text)
        self.assertIn("**`items.dat`**, 20 bytes per record.", text)
        self.assertIn("**`totals.dat`**, 40 bytes per record, key `id`.", text)

    def test_contract_describes_packed_decimal(self):
        sb = Sandbox(with_port=False)
        try:
            cfg = sb.cfg()
            cfg["layouts"]["TOTAL"]["fields"][3].update(length=6, type="COMP-3")  # total_kg, 3 decimals
            (sb.root / "tare.json").write_text(json.dumps(cfg), encoding="utf-8")
            text = contract.render(sb.root)
        finally:
            sb.close()
        self.assertIn("| 16 | 6 | `total_kg` | OUT-TOTAL-KG | S9(8)V9(3) COMP-3 | packed decimal: two digits a byte, "
                      "the sign in the last half-byte (C positive, D negative, F unsigned), 3 implied decimals |", text)

    def test_committed_contract_is_current(self):
        from tests.helpers import EXAMPLE, REPO
        committed = (REPO / ".bob" / "skills" / "replay" / "PORT_CONTRACT.md").read_text(encoding="utf-8")
        self.assertEqual(committed, contract.render(EXAMPLE))


if __name__ == "__main__":
    unittest.main()
