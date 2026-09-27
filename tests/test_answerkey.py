import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tare import answerkey, config, records
from tests.helpers import EXAMPLE, has_cobc, load

NOOP = """\
      * TEST FIXTURE: shows its PARM and returns.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOOP.
       DATA DIVISION.
       LINKAGE SECTION.
       01  RUN-PARM.
           05 RUN-PARM-LENGTH         PIC S9(04) COMP.
           05 RUN-PARM-TEXT           PIC X(100).
       PROCEDURE DIVISION USING RUN-PARM.
           IF ADDRESS OF RUN-PARM NOT = NULL
               DISPLAY 'NOOP: [' RUN-PARM-TEXT(1:RUN-PARM-LENGTH) ']'
           END-IF
           GOBACK.
"""
PARM = "IT'S A LONGER PARM, OVER THIRTY CHARACTERS: 12345"

ROWS = ["C003AA000030", "A001BB000010", "B002AA000020", "D004CC000040"]


PACKOUT = """\
      * TEST FIXTURE: writes packed-decimal amounts; with CORRUPT a
      * third record carries bytes that are not packed decimal.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PACKOUT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO OUTFILE
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-REC.
           05 OUT-ID                  PIC X(04).
           05 OUT-AMT                 PIC S9(05)V99 COMP-3.
           05 OUT-QTY                 PIC 9(03) COMP-3.
       01  OUT-RAW.
           05 FILLER                  PIC X(04).
           05 OUT-AMT-BYTES           PIC X(04).
           05 FILLER                  PIC X(02).
       PROCEDURE DIVISION.
           OPEN OUTPUT OUT-FILE
           MOVE 'A001' TO OUT-ID
           COMPUTE OUT-AMT = -123.45
           MOVE 7 TO OUT-QTY
           WRITE OUT-REC
           MOVE 'B002' TO OUT-ID
           MOVE 99999.99 TO OUT-AMT
           MOVE 999 TO OUT-QTY
           WRITE OUT-REC
{corrupt}           CLOSE OUT-FILE
           GOBACK.
"""
CORRUPT = """\
           MOVE 'C003' TO OUT-ID
           MOVE X'1A2B3C4D' TO OUT-AMT-BYTES
           WRITE OUT-REC
"""


def packed_case(root: Path, corrupt: bool) -> dict:
    (root / "cbl").mkdir(exist_ok=True)
    (root / "cbl" / "PACKOUT.cbl").write_text(PACKOUT.format(corrupt=CORRUPT if corrupt else ""), encoding="utf-8")
    lay = {"record_length": 10, "key": ["id"], "fields": [
        {"name": "id", "offset": 0, "length": 4, "type": "X"},
        {"name": "amt", "offset": 4, "length": 4, "type": "COMP-3", "scale": 2},
        {"name": "qty", "offset": 8, "length": 2, "type": "COMP-3"}]}
    cfg = {"cobol": {"sources": ["cbl/PACKOUT.cbl"], "copybooks": []},
           "files": {"out": {"record_length": 10, "layout": "PACK", "output": True}},
           "steps": [{"program": "PACKOUT", "dd": {"OUTFILE": "out"}}],
           "layouts": {"PACK": lay}}
    (root / "tare.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def mini_case(root: Path):
    (root / "cbl").mkdir()
    (root / "cbl" / "NOOP.cbl").write_text(NOOP, encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "rows.txt").write_text("\n".join(ROWS) + "\n", encoding="utf-8")
    lay = {"record_length": 12, "key": ["code"], "fields": [
        {"name": "code", "offset": 0, "length": 4, "type": "X"},
        {"name": "grp", "offset": 4, "length": 2, "type": "X"},
        {"name": "qty", "offset": 6, "length": 6, "type": "9"}]}
    cfg = {"cobol": {"sources": ["cbl/NOOP.cbl"], "copybooks": []},
           "files": {"master": {"from": "data/rows.txt", "from_format": "lines", "record_length": 12,
                                "organization": "indexed", "key": {"offset": 0, "length": 4},
                                "alternate_keys": [{"offset": 4, "length": 2, "duplicates": True}],
                                "layout": "ROW", "output": True},
                     "plain": {"from": "data/rows.txt", "from_format": "lines", "record_length": 12,
                               "layout": "ROW", "output": True}},
           "steps": [{"program": "NOOP", "parm": PARM, "dd": {"MASTER": "master"}}],
           "layouts": {"ROW": lay}}
    (root / "tare.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


PACK = {"record_length": 10, "key": ["id"], "fields": [
    {"name": "id", "offset": 0, "length": 4, "type": "X"},
    {"name": "amt", "offset": 4, "length": 4, "type": "COMP-3", "scale": 2},
    {"name": "qty", "offset": 8, "length": 2, "type": "9"}]}
GOOD = b"A001" + bytes.fromhex("0012345D") + b"07" + b"B002" + bytes.fromhex("9999999C") + b"12"


def packed_key(root: Path, out: bytes, echo=None, ins=b"A001B002") -> dict:
    (root / "input").mkdir(exist_ok=True)
    (root / "input" / "ins.dat").write_bytes(ins)
    (root / "out.dat").write_bytes(out)
    return {"cobol": {"sources": ["P.cbl"]}, "steps": [{"program": "P", "dd": {"I": "ins", "O": "out"}}],
            "files": {"ins": {"from": "ins.txt", "record_length": 4, "layout": "IN"},
                      "out": dict({"record_length": 10, "layout": "PACK", "output": True},
                                  **({"echo": echo} if echo else {}))},
            "layouts": {"PACK": PACK, "IN": {"record_length": 4, "key": ["id"], "fields": [
                {"name": "id", "offset": 0, "length": 4, "type": "X"}]}}}


class Soundness(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_sound_key_passes(self):
        cfg = packed_key(self.root, GOOD)
        self.assertEqual(answerkey.soundness(cfg, self.root), [])
        answerkey.check_sound(cfg, self.root)

    def test_invalid_packed_digit_fails(self):
        cfg = packed_key(self.root, GOOD[:14] + bytes.fromhex("99A9999C") + b"12")
        self.assertEqual(answerkey.soundness(cfg, self.root),
                         ["field amt in record 2 of out is not valid packed decimal (bytes 99 a9 99 9c)"])
        with self.assertRaises(answerkey.UnsoundAnswerKey) as cm:
            answerkey.check_sound(cfg, self.root)
        self.assertTrue(str(cm.exception).startswith(
            "answer key unsound: field amt in record 2 of out is not valid packed decimal"), str(cm.exception))

    def test_invalid_packed_sign_fails(self):
        cfg = packed_key(self.root, b"A001" + bytes.fromhex("00123456") + GOOD[8:])
        self.assertEqual(answerkey.soundness(cfg, self.root),
                         ["field amt in record 1 of out is not valid packed decimal (bytes 00 12 34 56)"])

    def test_zoned_field_that_does_not_decode_fails(self):
        cfg = packed_key(self.root, GOOD[:8] + b"0X" + GOOD[10:])
        self.assertEqual(answerkey.soundness(cfg, self.root),
                         ["field qty in record 1 of out is not a valid 9 number ('0X')"])

    def test_echo_by_record(self):
        echo = [{"field": "id", "input": "ins", "input_field": "id"}]
        self.assertEqual(answerkey.soundness(packed_key(self.root, GOOD, echo), self.root), [])
        cfg = packed_key(self.root, GOOD, echo, ins=b"A001C003")
        self.assertEqual(answerkey.soundness(cfg, self.root),
                         ["field id in record 2 of out reads 'B002', not ins.id of input record 2 ('C003')"])

    def test_echo_any_record(self):
        echo = [{"field": "id", "input": "ins", "match": "any"}]
        self.assertEqual(answerkey.soundness(packed_key(self.root, GOOD, echo, ins=b"B002A001"), self.root), [])
        cfg = packed_key(self.root, GOOD, echo, ins=b"B002C003")
        self.assertEqual(answerkey.soundness(cfg, self.root),
                         ["field id in record 1 of out reads 'A001', which is no input record's ins.id"])

    def test_echo_declarations_are_validated(self):
        for bad in ({"field": "id", "input": "nosuch"}, {"field": "nosuch", "input": "ins"},
                    {"field": "id", "input": "ins", "input_field": "nosuch"},
                    {"field": "id", "input": "ins", "match": "sometimes"}):
            with self.assertRaises(answerkey.AnswerKeyError, msg=str(bad)):
                answerkey.validate(packed_key(self.root, GOOD, [bad]))

    def test_the_committed_example_is_sound(self):
        cfg = load("tare.json")
        self.assertTrue(cfg["files"]["totals"].get("echo"), "the example declares an echo check")
        self.assertEqual(answerkey.soundness(cfg, EXAMPLE / config.ANSWER_DIR), [])


class Generated(unittest.TestCase):
    def test_loader_declares_every_key_within_72_columns(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = mini_case(Path(td))
        src = answerkey.loader_source(cfg)
        self.assertTrue(src.startswith("      *HARNESS: generated by tare/answerkey.py"))
        self.assertIn("RECORD KEY   IS IDX-01-KEY0", src)
        self.assertIn("ALTERNATE RECORD KEY IS IDX-01-KEY1", src)
        self.assertIn("WITH DUPLICATES", src)
        self.assertTrue(all(len(l) <= 72 for l in src.splitlines()))

    def test_parm_driver(self):
        src = answerkey.parm_driver_source(3, "PROG", PARM)
        self.assertIn("PROGRAM-ID. TPARM03.", src)
        self.assertIn(f"MOVE {len(PARM)} TO JCL-PARM-LENGTH", src)
        self.assertIn("MOVE 'IT''S A LONGER PARM, OVER THIRT'\n             TO JCL-PARM-TEXT(1:30)", src)
        self.assertIn("CALL 'PROG' USING JCL-PARM", src)
        self.assertTrue(src.startswith("      *HARNESS:"))

    def test_validation(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = mini_case(Path(td))
        bad = json.loads(json.dumps(cfg))
        bad["steps"][0]["dd"]["X"] = "nosuchfile"
        with self.assertRaises(answerkey.AnswerKeyError):
            answerkey.validate(bad)
        bad = json.loads(json.dumps(cfg))
        bad["steps"][0]["parm"] = "x" * 101
        with self.assertRaises(answerkey.AnswerKeyError):
            answerkey.validate(bad)
        bad = json.loads(json.dumps(cfg))
        bad["files"]["master"]["key"] = {"offset": 10, "length": 4}
        with self.assertRaises(answerkey.AnswerKeyError):
            answerkey.validate(bad)
        answerkey.validate(load("tare.json"))


@unittest.skipUnless(has_cobc(), "GnuCOBOL (cobc, cobcrun) not on PATH")
class RealRun(unittest.TestCase):
    def test_loader_round_trip_parm_and_sequential_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mini_case(root)
            s = answerkey.build(root, say=lambda _: None)
            self.assertEqual(s["records"], {"master": 4, "plain": 4})
            out = root / config.ANSWER_DIR
            self.assertEqual((out / "master.dat").read_bytes(), "".join(sorted(ROWS)).encode())
            self.assertEqual((out / "plain.dat").read_bytes(), "".join(ROWS).encode())
            self.assertEqual((out / "input" / "master.dat").read_bytes(), "".join(ROWS).encode())
            log = (out / "logs" / "step01_NOOP.log").read_text(encoding="latin-1")
            self.assertIn(f"NOOP: [{PARM}]", log)
            doc = records.load_side(out / "records.json")
            self.assertEqual(doc["files"]["master"][0], {"code": "A001", "grp": "BB", "qty": "10"})
            self.assertEqual(doc["side"], "answer_key")

    def test_refuses_to_replace_a_folder_that_is_not_an_answer_key(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mini_case(root)
            (root / "keep").mkdir()
            (root / "keep" / "notes.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(answerkey.AnswerKeyError):
                answerkey.build(root, "keep", say=lambda _: None)
            self.assertTrue((root / "keep" / "notes.txt").is_file())

    def test_packed_output_decodes_and_a_corrupted_one_stops_the_build(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = packed_case(root, corrupt=False)
            answerkey.build(root, say=lambda _: None)
            doc = records.load_side(root / config.ANSWER_KEY)
            self.assertEqual(doc["files"]["out"], [{"id": "A001", "amt": "-123.45", "qty": "7"},
                                                   {"id": "B002", "amt": "99999.99", "qty": "999"}])
            packed_case(root, corrupt=True)
            with self.assertRaises(answerkey.UnsoundAnswerKey) as cm:
                answerkey.build(root, say=lambda _: None)
            self.assertIn("answer key unsound: field amt in record 3 of out is not valid packed decimal",
                          str(cm.exception))
            self.assertFalse((root / config.ANSWER_KEY).exists(), "no records.json from an unsound key")
            packed_case(root, corrupt=False)
            answerkey.build(root, say=lambda _: None)
            self.assertEqual(len(records.load_side(root / config.ANSWER_KEY)["files"]["out"]), 2)
            self.assertEqual(cfg["layouts"]["PACK"]["record_length"], 10)

    def test_the_committed_example_reproduces(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copy(EXAMPLE / "tare.json", root / "tare.json")
            shutil.copytree(EXAMPLE / "mainframe", root / "mainframe")
            answerkey.build(root, "fresh", say=lambda _: None)
            self.assertEqual(answerkey.compare(EXAMPLE / config.ANSWER_DIR, root / "fresh", load("tare.json")), [])


if __name__ == "__main__":
    unittest.main()
