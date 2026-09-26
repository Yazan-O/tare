"""The ledger on the test fixture's records, accepted differences, and explain's arithmetic."""
import copy
import unittest
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from fractions import Fraction

from tare import explain, ledger, scale
from tests.helpers import ANSWER, BALANCED, RED, Sandbox, load

CFG = load("tare.json")


def sealed(entry):
    return dict(entry, seal=ledger.entry_seal(entry))


class Weigh(unittest.TestCase):
    def setUp(self):
        self.a, self.ok, self.red = load(ANSWER), load(BALANCED), load(RED)

    def test_balanced(self):
        s = ledger.weigh(self.a, self.ok, CFG)["summary"]
        self.assertEqual((s["verdict"], s["records_total"], s["records_differ"]), ("balanced", 5, 0))
        self.assertEqual(s["result_line"], "weigh: 5 of 5 records balance")
        self.assertEqual(scale.tilt(s), 0.0)

    def test_half_up_port_is_red_on_three(self):
        r = ledger.weigh(self.a, self.red, CFG)
        s = r["summary"]
        self.assertEqual((s["verdict"], s["records_differ"], s["fields_differ"]), ("red", 3, 3))
        self.assertEqual(s["numeric"]["totals"]["total_lb"], {"higher": 3, "lower": 0, "net": "+0.03"})
        self.assertEqual(s["numeric"]["totals"]["total_kg"], {"higher": 0, "lower": 0, "net": "0"})
        self.assertEqual(s["result_line"], "weigh: 3 of 5 records differ")
        self.assertEqual([(x["key"], x["field"], x["answer"], x["port"], x["delta"]) for x in r["rows"]],
                         [("A10001", "total_lb", "10.09", "10.10", "+0.01"),
                          ("B20003", "total_lb", "7.20", "7.21", "+0.01"),
                          ("C30005", "total_lb", "11.56", "11.57", "+0.01")])
        self.assertIn("total_lb: 3 higher, 0 lower, net +0.03", ledger.describe(s))
        self.assertAlmostEqual(scale.tilt(s), 12 * 3 / 5)

    def test_missing_extra_and_text_fields(self):
        p = copy.deepcopy(self.ok)
        gone = p["files"]["totals"].pop(0)
        p["files"]["totals"].append(dict(gone, id="Z99999"))
        s = ledger.weigh(self.a, p, CFG)["summary"]
        self.assertEqual((s["missing"], s["extra"], s["records_differ"], s["verdict"]), (1, 1, 2, "red"))
        self.assertEqual(s["numeric"]["totals"]["total_lb"]["net"], "0.00")  # -10.09 missing, +10.09 extra

    def test_port_that_wrote_nothing(self):
        p = dict(self.ok, files={"totals": []})
        s = ledger.weigh(self.a, p, CFG)["summary"]
        self.assertEqual((s["missing"], s["records_differ"]), (5, 5))
        self.assertTrue(ledger.describe(s).startswith("0 of 5 records written by the port (all 5 missing)"))
        self.assertEqual(scale.details(s), ["0 of 5 written"])
        self.assertLess(scale.tilt(s), 0)

    def test_decimal_equality_not_text(self):
        p = copy.deepcopy(self.ok)
        p["files"]["totals"][0]["total_kg"] = "4.58"  # same number, other scale
        self.assertEqual(ledger.weigh(self.a, p, CFG)["summary"]["verdict"], "balanced")


class Accepted(unittest.TestCase):
    def setUp(self):
        self.a, self.red = load(ANSWER), load(RED)
        self.entry = sealed({"file": "totals", "key": "A10001", "fields": ["total_lb"],
                             "expect": {"total_lb": "10.10"}, "reason": "t", "accepted_by": "T", "date": "d"})

    def test_pinned_value_covers_only_that_record(self):
        r = ledger.weigh(self.a, self.red, CFG, [self.entry])
        s = r["summary"]
        self.assertEqual((s["records_differ"], s["accepted"], s["accepted_fields"]), (2, 1, 1))
        self.assertIn("ACCEPTED (expected 10.10)", ledger.format_table(r))

    def test_other_value_or_unlisted_field_stays_red(self):
        p = copy.deepcopy(self.red)
        p["files"]["totals"][0]["total_lb"] = "10.11"
        r = ledger.weigh(self.a, p, CFG, [self.entry])
        self.assertEqual(r["summary"]["accepted"], 0)
        self.assertIn("(accepted value 10.10)", ledger.format_table(r))
        p = copy.deepcopy(self.red)
        p["files"]["totals"][0]["qty"] = "6"
        s = ledger.weigh(self.a, p, CFG, [self.entry])["summary"]
        self.assertEqual((s["accepted"], s["fields_differ"]), (1, 3))

    def test_answer_key_expect_accepts_nothing_else(self):
        e = sealed(dict(self.entry, expect="answer_key"))
        s = ledger.weigh(self.a, self.red, CFG, [e])["summary"]
        self.assertEqual((s["accepted"], s["records_differ"]), (0, 3))
        self.assertEqual(ledger.expected_values(e, self.a["files"]["totals"][0]), {"total_lb": "10.09"})

    def test_hand_edited_entry_covers_nothing(self):
        e = dict(self.entry, expect={"total_lb": "10.10"}, reason="edited by hand")
        s = ledger.weigh(self.a, self.red, CFG, [e])["summary"]
        self.assertEqual((s["accepted"], s["unsealed_entries"], s["records_differ"]), (0, 1, 3))

    def test_missing_records_are_never_accepted(self):
        p = dict(self.red, files={"totals": self.red["files"]["totals"][1:]})
        e = sealed(dict(self.entry, fields=["*"], expect={"*": "missing"}))
        s = ledger.weigh(self.a, p, CFG, [e])["summary"]
        self.assertEqual((s["missing"], s["accepted"]), (1, 0))


class ExplainMath(unittest.TestCase):
    def test_pic_scale(self):
        self.assertEqual(explain.pic_scale("S9(08)V99"), 2)
        self.assertEqual(explain.pic_scale("9(04)V9(3)"), 3)
        self.assertEqual(explain.pic_scale("9(11)"), 0)

    def test_exact_decimal(self):
        self.assertEqual(explain.exact_decimal(Fraction(1, 3)), "0.(3)")
        self.assertEqual(explain.exact_decimal(Fraction(-7, 4)), "-1.75")
        self.assertEqual(explain.exact_decimal(Fraction(1, 12)), "0.08(3)")

    def test_truncate_and_half_up(self):
        f = Fraction(Decimal("4.580")) * Fraction(Decimal("2.20462"))  # 10.0971596
        self.assertEqual(str(explain._to_scale(f, 2, ROUND_DOWN)), "10.09")
        self.assertEqual(str(explain._to_scale(f, 2, ROUND_HALF_UP)), "10.10")
        self.assertEqual(str(explain._to_scale(-f, 2, ROUND_DOWN)), "-10.09")
        self.assertEqual(str(explain._to_scale(-f, 2, ROUND_HALF_UP)), "-10.10")
        self.assertEqual(str(explain._to_scale(Fraction(5, 1000), 2, ROUND_HALF_UP)), "0.01")

    def test_expression(self):
        vals = {"A": Fraction(3), "B": Fraction(1, 2)}
        ev = lambda s: explain._Expr(explain.TOKEN.findall(s), vals.__getitem__).expr()
        self.assertEqual(ev("A * (B + 1) / 2"), Fraction(9, 4))
        self.assertEqual(ev("-A ** 2 + 0.5"), Fraction(19, 2))  # COBOL: unary minus binds before **

    def test_receivers(self):
        st = lambda verb, text: {"verb": verb, "tokens": explain.TOKEN.findall(text)}
        self.assertEqual(explain.receivers(st("MOVE", "0 TO A B(1) C OF D")), ["A", "B", "C"])
        self.assertEqual(explain.receivers(st("COMPUTE", "X ROUNDED Y = A * B")), ["X", "Y"])
        self.assertEqual(explain.receivers(st("ADD", "A TO B GIVING C")), ["C"])
        self.assertEqual(explain.receivers(st("ADD", "1 TO N ON SIZE ERROR")), ["N"])
        self.assertEqual(explain.receivers(st("SUBTRACT", "A FROM B")), ["B"])
        self.assertEqual(explain.receivers(st("DIVIDE", "A INTO B GIVING Q REMAINDER R")), ["Q", "R"])

    def test_chain_reads_the_program(self):
        sb = Sandbox()
        try:
            sb.put_run("local", RED)
            text = explain.explain(sb.root, port="local")
            self.assertIn("totals record A10001  field total_lb", text)
            self.assertIn("mainframe/cbl/UNITSUM.cbl:100", text)
            self.assertIn("COMPUTE OUT-TOTAL-LB = OUT-TOTAL-KG * 2.20462", text)
            self.assertIn("MOVE SPACES TO TOTAL-RECORD", text)
            self.assertIn("PIC S9(08)V99  USAGE DISPLAY   mainframe/cpy/TOTALREC.cpy:7", text)
            self.assertIn("= 4.580 * 2.20462 = 10.0971596", text)
            self.assertIn("answer key wrote        10.09   matches truncation (no ROUNDED)", text)
            self.assertIn("port wrote              10.10   matches half-up (ROUNDED)", text)
            self.assertIn("truncation occurs unless ROUNDED is specified.", text)
            self.assertIn("https://www.ibm.com/docs/en/cobol-zos/6.3.0?topic=operations-rounded-phrase", text)
            kg = explain.explain(sb.root, key="A10001", field="total_kg", port="local")
            self.assertIn("ADD WS-LINE-KG TO OUT-TOTAL-KG", kg)
            self.assertIn("PIC 9(08)V999", kg)
            self.assertNotIn("4. The arithmetic", kg)  # equal values: no reconstruction
        finally:
            sb.close()


if __name__ == "__main__":
    unittest.main()
