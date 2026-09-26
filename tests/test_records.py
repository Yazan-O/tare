"""Record decoding: every field type and sign convention, and the errors a bad file raises."""
import unittest

from tare import records
from tests.helpers import EXAMPLE, load

S2 = {"name": "v", "type": "S9V9", "scale": 2, "sign": "trailing-overpunch"}


class Fields(unittest.TestCase):
    def test_text_keeps_leading_drops_trailing_spaces(self):
        self.assertEqual(records.decode_field(" AB  ", {"name": "t", "type": "X"}), " AB")

    def test_unsigned(self):
        self.assertEqual(records.decode_field("00012", {"name": "n", "type": "9"}), "12")
        self.assertEqual(records.decode_field("0004580", {"name": "n", "type": "9", "scale": 3}), "4.580")
        with self.assertRaises(ValueError):
            records.decode_field("00A12", {"name": "n", "type": "9"})

    def test_overpunch_ebcdic_letters(self):
        self.assertEqual(records.decode_field("000000100I", S2), "10.09")
        self.assertEqual(records.decode_field("000000072{", S2), "7.20")
        self.assertEqual(records.decode_field("000000072}", S2), "-7.20")
        self.assertEqual(records.decode_field("000000100R", S2), "-10.09")

    def test_overpunch_ascii_forms(self):
        self.assertEqual(records.decode_field("0000010099", S2), "100.99")
        self.assertEqual(records.decode_field("000000100y", S2), "-10.09")
        self.assertEqual(records.decode_field("000000000p", S2), "0.00")  # no negative zero

    def test_separate_and_none(self):
        self.assertEqual(records.decode_field("01250-", dict(S2, sign="separate")), "-12.50")
        self.assertEqual(records.decode_field("01250+", dict(S2, sign="separate")), "12.50")
        with self.assertRaises(ValueError):
            records.decode_field("012500", dict(S2, sign="separate"))
        self.assertEqual(records.decode_field("01250", dict(S2, sign="none")), "12.50")

    def test_bad_record_length_names_the_file(self):
        lay = {"record_length": 4, "key": ["a"], "fields": [{"name": "a", "offset": 0, "length": 4}]}
        with self.assertRaises(ValueError) as cm:
            records.decode_bytes(b"abcdef", lay, "x.dat")
        self.assertIn("x.dat", str(cm.exception))

    def test_layout_checks(self):
        with self.assertRaises(ValueError):
            records.check_layout("L", {"record_length": 4, "key": ["a"],
                                       "fields": [{"name": "a", "offset": 2, "length": 4}]})
        with self.assertRaises(ValueError):
            records.check_layout("L", {"record_length": 4, "key": ["b"],
                                       "fields": [{"name": "a", "offset": 0, "length": 4}]})


class TheFixture(unittest.TestCase):
    def test_answer_key_decodes_to_its_records_json(self):
        cfg = load("tare.json")
        recs = records.decode_file(EXAMPLE / "fixtures" / "answer_key" / "totals.dat", cfg["layouts"]["TOTAL"])
        self.assertEqual(recs, load("fixtures/answer_key/records.json")["files"]["totals"])
        self.assertEqual(recs[0], {"id": "A10001", "count": "2", "qty": "5", "total_kg": "4.580",
                                   "total_lb": "10.09"})


if __name__ == "__main__":
    unittest.main()
