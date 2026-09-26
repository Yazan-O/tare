"""explain's copybook expansion applies COPY ... REPLACING: pseudo-text, literals, words, LEADING and TRAILING."""
import json
import tempfile
import unittest
from pathlib import Path

from tare import explain

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 RETOURB.
          COPY XRET     REPLACING 'X' BY RETOURB.
       01 PAY-REC.
          COPY PAYREC   REPLACING ==:PFX:== BY ==PAY==
      * a comment line inside the COPY statement
               ==pic 9(05)== BY ==PIC S9(07)V99 COMP-3==.
       01 LEAD-REC.
          COPY LEADREC  REPLACING LEADING ==OLD-== BY ==NEW-==
                                  TRAILING ==-AMT== BY ==-AMOUNT==.
       01 WORD-REC.
          COPY WORDREC  REPLACING QTY BY ITEM-QTY.
       01 SPAN-REC.
          COPY SPANREC  REPLACING ==RATE PIC 9V99==
                               BY ==RATE PIC 9V9999==.
       01 PLAIN-REC.
          COPY PLAINREC.
       PROCEDURE DIVISION.
           GOBACK.
"""
COPYBOOKS = {
    "XRET.cpy": ["      * 'X' in a comment stays", "           10 'X'-TCTDU     PIC S9(12)."],
    "PAYREC.cpy": ["           05 :PFX:-ID      PIC X(06).", "           05 :PFX:-TOTAL   PIC 9(05)."],
    "LEADREC.cpy": ["           05 OLD-CODE      PIC X(02).", "           05 PRICE-AMT     PIC 9(05)V99.",
                    "           05 OLDER         PIC X(01)."],
    "WORDREC.cpy": ["           05 QTY           PIC 9(03).", "           05 QTY-MAX       PIC 9(03)."],
    "SPANREC.cpy": ["           05 RATE", "      * the PIC is on the next line", "              PIC 9V99."],
    "PLAINREC.cpy": ["           05 PLAIN-A       PIC X(04)."],
}


class CopyReplacing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        root = Path(cls.dir.name)
        (root / "cbl").mkdir()
        (root / "cpy").mkdir()
        (root / "cbl" / "PROG.cbl").write_text(PROGRAM, encoding="latin-1")
        for name, lines in COPYBOOKS.items():
            (root / "cpy" / name).write_text("\n".join(lines) + "\n", encoding="latin-1")
        cfg = {"cobol": {"sources": ["cbl/PROG.cbl"], "copybooks": ["cpy"]}}
        (root / "tare.json").write_text(json.dumps(cfg), encoding="utf-8")
        cls.entries = {e["name"]: e for e in explain.data_entries(root, cfg)}

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def entry(self, name):
        self.assertIn(name, self.entries, f"{name} not found; got {sorted(self.entries)}")
        return self.entries[name]

    def test_literal_joined_to_a_word(self):
        e = self.entry("RETOURB-TCTDU")
        self.assertEqual((e["pic"], e["file"], e["line"], e["groups"]), ("S9(12)", "cpy/XRET.cpy", 2, ["RETOURB"]))

    def test_pseudo_text_on_several_lines_of_the_copy_statement(self):
        self.assertEqual(self.entry("PAY-ID")["pic"], "X(06)")
        e = self.entry("PAY-TOTAL")
        self.assertEqual((e["pic"], e["usage"]), ("S9(07)V99", "COMP-3"))

    def test_leading_and_trailing(self):
        self.assertEqual(self.entry("NEW-CODE")["pic"], "X(02)")
        self.assertEqual(self.entry("PRICE-AMOUNT")["pic"], "9(05)V99")
        self.assertIn("OLDER", self.entries)  # 'OLD-' is not a leading part of OLDER

    def test_word_replaces_whole_words_only(self):
        self.assertEqual(self.entry("ITEM-QTY")["pic"], "9(03)")
        self.assertIn("QTY-MAX", self.entries)
        self.assertNotIn("QTY", self.entries)

    def test_pseudo_text_matched_across_lines_keeps_line_numbers(self):
        e = self.entry("RATE")
        self.assertEqual((e["pic"], e["line"]), ("9V9999", 1))

    def test_copy_without_replacing(self):
        self.assertEqual(self.entry("PLAIN-A")["pic"], "X(04)")

    def test_replacing_operands(self):
        name, rules = explain.copy_statement("COPY X REPLACING ==A B== BY ====  'L' BY W OF G  C BY D.")
        self.assertEqual(name, "X")
        self.assertEqual(rules, [(None, ["A", "B"], ""), (None, ["'L'"], "W OF G"), (None, ["C"], "D")])
        self.assertIsNone(explain.copy_statement("COPY X REPLACING ==A== BY"))  # the statement goes on
        with self.assertRaises(ValueError):
            explain.copy_statement("COPY X REPLACING ==A== ==B==.")


if __name__ == "__main__":
    unittest.main()
