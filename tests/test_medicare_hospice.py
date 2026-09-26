"""The Medicare hospice case: the three recorded verdicts, the corpus, the layouts, the repairs and the
evidence chain for one claim per defect.

Nothing here needs a JDK, Maven or the network. The tests that read a fetched source skip themselves
when cache/ is absent (python fetch.py), the way the France case's own explain test does.
"""
import collections
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tare import answerkey, config, explain, ledger, records, reproduce

REPO = Path(__file__).resolve().parents[1]
CASE = REPO / "cases" / "medicare_hospice"
ANSWER = CASE / "fixtures" / "answer_key" / "records.json"
COMMITTED = CASE / "input" / "billfile.txt"                  # the corpus as committed, one claim a line
INPUT = CASE / "fixtures" / "answer_key" / "input" / "billfile.dat"   # the same records, no separators
SIDES = ("cms-java", "java-ai", "java-ai-fixed")
# 5,000 constructed claims, seed 20260926: the corpus is fixed, so a regeneration that moves it fails
# here rather than quietly changing every number in README.md and ACT_TWO.md.
BILLFILE_SHA256 = "db7744b9063861c062a5f8e6a8c41e239e59a564d968d0d7cd50304e97f9603a"
RECORD_LENGTH = 315
# The verdicts `python -m tare reproduce` must print, side by side: (verdict, records differing).
EXPECTED = {"cms-java": ("red", 140), "java-ai": ("red", 270), "java-ai-fixed": ("balanced", 0)}
# One claim per defect, with both values: claim, field, the COBOL's, the port's.
EXAMPLES = (("C00002", "total", "2162.16", "2162.15"),      # CMS's Java: rounds the total once
            ("C00082", "high", "7", "8"),                  # the AI port: counts a short CHC day
            ("C00033", "rtc", "00", "73"),                 # the AI port: return code from that same day
            ("C00408", "pay_chc", "1421.42", "1421.43"))    # the AI port: rounds the hourly rate
# The line each defect's evidence rests on, and what it must contain (HOSPR210.cbl, fetched).
COBOL_LINES = ((207, "WRK-PAY-RATE2"), (4544, "BILL-HIGH-RHC-DAYS"), (5289, "BILL-HIGH-RHC-DAYS"),
               (5857, "BILL-PAY-AMT-TOTAL"), (5997, "BILL-LOW-RHC-DAYS"), (6018, "RHC-LOW-DAY-IND"),
               (6036, "BILL-HIGH-RHC-DAYS"), (6055, "RHC-HIGH-DAY-IND"), (6280, "BILL-RTC"),
               (6309, "BILL-RTC"), (6409, "WRK-PAY-RATE2"), (6418, "WRK-PAY-RATE2"),
               (6430, "WRK-PAY-RATE2"))
# No interest, no lending, no credit-card finance charge, anywhere in this case. The Medicare "PENALTY"
# payment reductions are a different pricer: the hospice pricer has none.
FORBIDDEN = ("interest", "loan", "credit card", "credit-card", "finance charge", "usury", "apr rate")


def cfg() -> dict:
    return config.load_config(CASE)


def side_records(name: str) -> dict:
    return records.load_side(CASE / "fixtures" / "sides" / name / "records.json")


def tally(weighed: dict) -> dict:
    """{field: records differing in it} for one weigh."""
    return dict(collections.Counter(r["field"] for r in weighed["rows"] if r["status"] != "accepted"))


def value(name: str, claim: str, field: str) -> str:
    return next(r[field] for r in side_records(name)["files"]["ratefile"] if r["claim"] == claim)


class ConfigTest(unittest.TestCase):
    def test_tare_json_validates(self):
        answerkey.validate(cfg())            # raises AnswerKeyError when the case is malformed

    def test_every_output_field_sits_inside_the_315_byte_record(self):
        lay = config.layout_for(cfg(), "ratefile")
        self.assertEqual(lay["record_length"], RECORD_LENGTH)
        self.assertEqual(lay["key"], ["claim"])
        for f in lay["fields"]:
            self.assertLessEqual(f["offset"] + f["length"], RECORD_LENGTH, f)
        # the claim id is the trailing FILLER of 01 BILL-315-DATA, which the pricer never writes
        claim = next(f for f in lay["fields"] if f["name"] == "claim")
        self.assertEqual((claim["offset"], claim["length"]), (307, 8))

    def test_the_fourteen_weighed_fields_are_the_sixteen_the_layout_declares(self):
        lay = config.layout_for(cfg(), "ratefile")
        self.assertEqual([f["name"] for f in lay["fields"]],
                         ["claim", "total", "rtc", "high", "low", "pay_rhc", "pay_chc", "pay_irc",
                          "pay_gic", "eol_1", "eol_2", "eol_3", "eol_4", "eol_5", "eol_6", "eol_7"])

    def test_fetch_pins_a_digest_for_each_of_the_three_sources(self):
        text = (CASE / "fetch.py").read_text(encoding="utf-8")
        for name in ("COBOL_SHA256", "CMS_ZIP_SHA256", "CMS_SRC_SHA256", "CMS_JAR_SHA256"):
            value_ = next(l for l in text.splitlines() if l.startswith(name))
            digest = value_.split('"')[1]
            self.assertRegex(digest, r"^[0-9a-f]{64}$", name)
        self.assertIn("AI_COMMIT = \"655847671859b67a188c5dae6a86c45a74bfa046\"", text)
        for url in ("fy-20210-hospice-mf-software", "hospice-pricer-20250-v240-executable-jar",
                    "hospice-pricer-20250-v240-java-source-code", "rcaran/hospice-cms-pricer-java"):
            self.assertIn(url, text)


class InputTest(unittest.TestCase):
    def test_the_committed_corpus_is_the_one_that_was_measured(self):
        self.assertEqual(hashlib.sha256(COMMITTED.read_bytes()).hexdigest(), BILLFILE_SHA256)
        # the answer key's input is the same records with the line separators taken off
        self.assertEqual(COMMITTED.read_bytes().replace(b"\n", b""), INPUT.read_bytes())

    def test_5000_claims_of_315_bytes_each_inside_fy2021(self):
        data = INPUT.read_bytes()
        self.assertEqual(len(data), 5000 * RECORD_LENGTH)
        lay = config.layout_for(cfg(), "billfile")
        rows = records.decode_bytes(data, lay)
        self.assertEqual([r["claim"] for r in rows[:2]], ["C00001", "C00002"])
        self.assertEqual(rows[-1]["claim"], "C05000")
        self.assertEqual(len({r["claim"] for r in rows}), 5000)
        for r in rows:
            # the fiscal year is the service date; the admission may be earlier, a stay spans periods
            self.assertTrue("20201001" <= r["from_date"] <= "20210930", r)
            self.assertLessEqual(r["admission_date"], r["from_date"], r)
            self.assertEqual(r["npi"], "1234567890")           # one dummy provider, no person's data
            self.assertEqual(r["prov_no"], "341234")

    def test_the_wage_index_table_is_cms_own_and_holds_every_cbsa_the_claims_use(self):
        table = (CASE / "fixtures" / "answer_key" / "input" / "cbsafile.dat").read_bytes()
        self.assertEqual(len(table) % 80, 0)
        rows = [table[i:i + 80].decode("latin-1") for i in range(0, len(table), 80)]
        self.assertEqual(len(rows), 7478)                      # CBSA2021, minus its 0x1A end-of-file byte
        used = {r["prov_cbsa"] for r in records.decode_bytes(INPUT.read_bytes(),
                                                            config.layout_for(cfg(), "billfile"))}
        have = {r[:5] for r in rows if r[6:14] == "20201001"}
        self.assertEqual(len(have), 486)
        self.assertTrue(used <= have, sorted(used - have)[:5])


class AnswerKeyTest(unittest.TestCase):
    def test_the_recorded_answer_key_is_sound(self):
        self.assertEqual(answerkey.soundness(cfg(), CASE / "fixtures" / "answer_key"), [])

    def test_the_answer_key_priced_every_claim_and_kept_its_id(self):
        a = records.load_side(ANSWER)
        self.assertEqual(a["side"], "answer_key")
        rows = a["files"]["ratefile"]
        self.assertEqual(len(rows), 5000)
        self.assertEqual(len({r["claim"] for r in rows}), 5000)
        # the echo check is what proves record alignment: every id is the input's
        want = [r["claim"] for r in records.decode_bytes(INPUT.read_bytes(),
                                                         config.layout_for(cfg(), "billfile"))]
        self.assertEqual([r["claim"] for r in rows], want)


class VerdictTest(unittest.TestCase):
    def test_the_three_recorded_fixtures_keep_their_verdicts(self):
        got = {name: s for s, name in reproduce.fixture_states(CASE)}
        self.assertEqual(sorted(got), sorted(SIDES))
        for name, (verdict, differ) in EXPECTED.items():
            self.assertEqual(got[name]["verdict"], verdict, name)
            self.assertEqual((got[name]["records_differ"], got[name]["records_total"]), (differ, 5000), name)

    def test_cms_java_differs_on_the_total_field_only_and_by_a_cent(self):
        result = ledger.weigh(records.load_side(ANSWER), side_records("cms-java"), cfg(), [])
        self.assertEqual(result["summary"]["records_differ"], 140)
        self.assertEqual(tally(result), {"total": 140})         # every line payment matches
        cents = {abs(round(float(r["port"]) - float(r["answer"]), 2)) for r in result["rows"]}
        self.assertEqual(cents, {0.01})                        # every difference is exactly one cent

    def test_the_ai_port_differs_on_day_counts_return_code_and_the_chc_line(self):
        result = ledger.weigh(records.load_side(ANSWER), side_records("java-ai"), cfg(), [])
        self.assertEqual(result["summary"]["records_differ"], 270)
        self.assertEqual(tally(result), {"high": 122, "low": 109, "rtc": 15, "pay_chc": 39, "total": 39})

    def test_one_claim_per_defect(self):
        for claim, field, want_cobol, want_port in EXAMPLES:
            port = "cms-java" if field == "total" else "java-ai"
            self.assertEqual(value(port, claim, field), want_port, f"{port} {claim} {field}")
            self.assertEqual(next(r[field] for r in records.load_side(ANSWER)["files"]["ratefile"]
                                  if r["claim"] == claim), want_cobol, f"answer key {claim} {field}")

    def test_the_ai_port_never_differs_on_a_claim_without_continuous_home_care(self):
        a = {r["claim"]: r for r in records.load_side(ANSWER)["files"]["ratefile"]}
        b = {r["claim"]: r for r in side_records("java-ai")["files"]["ratefile"]}
        inlay = config.layout_for(cfg(), "billfile")
        bills = {r["claim"]: r for r in records.decode_bytes(INPUT.read_bytes(), inlay)}
        chc = {c for c, r in bills.items() if r["rev2"].strip() == "0652"}
        self.assertEqual(len(chc), 776)                        # 15% of claims bill continuous home care
        for claim in set(a) - chc:
            self.assertEqual(a[claim], b[claim], claim)
        self.assertEqual(sum(1 for c in chc if a[c] != b[c]), 270)   # 270 of 776, 35% of them


class ExplainTest(unittest.TestCase):
    """The evidence chain, one claim per defect. Skipped until the sources are fetched."""

    def setUp(self):
        if not (CASE / "cache" / "cobol" / "HOSPR210.cbl").is_file():
            self.skipTest("the CMS COBOL is not fetched (python fetch.py)")

    def test_c00082_the_day_count(self):
        text = explain.explain(CASE, key="C00082", field="high", port="java-ai")
        self.assertIn("answer key  7", text)
        self.assertIn("port        8", text)
        self.assertIn("cache/cobol/HOSPR210.cbl:6036", text)
        self.assertIn("MOVE HR-BILL-UNITS1  TO BILL-HIGH-RHC-DAYS", text)
        self.assertIn("FullPricerStrategy.java:79-80", text)
        self.assertIn("highDaysCount++", text)

    def test_c00033_the_return_code(self):
        text = explain.explain(CASE, key="C00033", field="rtc", port="java-ai")
        self.assertIn("answer key  00", text)
        self.assertIn("port        73", text)
        self.assertIn("cache/cobol/HOSPR210.cbl:6274-6312", text)
        self.assertIn("FullPricerStrategy.java:79-86", text)

    def test_c00408_the_hourly_rate(self):
        text = explain.explain(CASE, key="C00408", field="pay_chc", port="java-ai")
        self.assertIn("answer key  1421.42", text)
        self.assertIn("port        1421.43", text)
        self.assertIn("cache/cobol/HOSPR210.cbl:6430-6434", text)
        self.assertIn("PaymentCalculator.java:78-84", text)
        self.assertIn("dailyRate.divide(TWENTY_FOUR, 10, ROUNDING)", text)

    def test_c00002_the_cms_java_total(self):
        text = explain.explain(CASE, key="C00002", field="total", port="cms-java")
        self.assertIn("answer key  2162.16", text)
        self.assertIn("port        2162.15", text)
        self.assertIn("cache/cobol/HOSPR210.cbl:5857-5862", text)
        self.assertIn("CalculateFinalPayments.java:36-43", text)
        self.assertIn(".setScale(2, RoundingMode.HALF_UP));", text)

    def test_the_repaired_port_balances_on_the_same_claims(self):
        for claim, field, _, _ in EXAMPLES:
            fixed = value("java-ai-fixed", claim, field)
            cobol = next(r[field] for r in records.load_side(ANSWER)["files"]["ratefile"]
                         if r["claim"] == claim)
            self.assertEqual(fixed, cobol, f"{claim} {field}")


class CitedLineTest(unittest.TestCase):
    """Every COBOL line the case's evidence rests on, read from the fetched source."""

    def setUp(self):
        p = CASE / "cache" / "cobol" / "HOSPR210.cbl"
        if not p.is_file():
            self.skipTest("the CMS COBOL is not fetched (python fetch.py)")
        self.lines = p.read_text(encoding="latin-1").splitlines()

    def test_the_cited_lines_say_what_the_case_says_they_say(self):
        for n, text in COBOL_LINES:
            self.assertIn(text, self.lines[n - 1], f"HOSPR210.cbl:{n} does not hold {text!r}")

    def test_the_chc_paragraph_writes_no_day_count_and_no_return_code(self):
        paragraph = self.lines[6322:6440]                     # 2021-V210-CHC-0652, :6323-6440
        code = [l[7:72] for l in paragraph if len(l) > 6 and l[6] not in "*/"]
        for forbidden in ("BILL-HIGH-RHC-DAYS", "BILL-LOW-RHC-DAYS", "BILL-RTC"):
            self.assertFalse([l for l in code if forbidden in l], forbidden)
        self.assertTrue([l for l in code if "WRK-PAY-RATE2 ROUNDED" in l])


class PatchTest(unittest.TestCase):
    """sides/ai-port-fixes.patch: three repairs, applied to the pinned commit, nothing else."""

    PORT = CASE / "cache" / "repos" / "rcaran"
    PATCH = CASE / "sides" / "ai-port-fixes.patch"

    def setUp(self):
        if not (self.PORT / "hospice-pricer-api" / "pom.xml").is_file():
            self.skipTest("the AI port is not fetched (python fetch.py)")

    def test_the_patch_touches_two_files_of_the_port_and_nothing_else(self):
        touched = [l[len("+++ b/"):].strip() for l in self.PATCH.read_text(encoding="utf-8").splitlines()
                   if l.startswith("+++ b/")]
        self.assertEqual(sorted(touched), ["hospice-pricer-api/src/main/java/com/cms/hospice/pricing/"
                                           "FullPricerStrategy.java",
                                           "hospice-pricer-api/src/main/java/com/cms/hospice/pricing"
                                           "/PaymentCalculator.java"])
        for rel in touched:
            self.assertTrue((self.PORT / rel).is_file(), rel)

    def test_the_patch_applies_and_removes_exactly_the_three_defects(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "port"
            shutil.copytree(self.PORT, work, ignore=shutil.ignore_patterns(".git", "target"))
            subprocess.run(["git", "init", "-q"], cwd=work, check=True)
            r = subprocess.run(["git", "apply", str(self.PATCH)], cwd=work, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            src = work / "hospice-pricer-api" / "src" / "main" / "java" / "com" / "cms" / "hospice"
            strat = (src / "pricing" / "FullPricerStrategy.java").read_text(encoding="utf-8")
            pay = (src / "pricing" / "PaymentCalculator.java").read_text(encoding="utf-8")
            self.assertNotIn("highDaysCount++", strat)
            self.assertNotIn("lowDaysCount++", strat)
            self.assertNotIn("hasHighDays = true;\n                } else {", strat)
            self.assertNotIn("hasLowDays = true;\n                }", strat)
            self.assertIn("divide(TWENTY_FOUR, 4, RoundingMode.DOWN)", pay)
            # the payment arithmetic of every other level of care is untouched
            self.assertIn("return rate.multiply(BigDecimal.valueOf(units))", pay)
            self.assertIn("dailyRate.divide(TWENTY_FOUR, 10, ROUNDING);", pay)   # chcHourly, FY1998-2007

    def test_the_published_port_still_carries_the_defects(self):
        src = self.PORT / "hospice-pricer-api" / "src" / "main" / "java" / "com" / "cms" / "hospice"
        strat = (src / "pricing" / "FullPricerStrategy.java").read_text(encoding="utf-8")
        pay = (src / "pricing" / "PaymentCalculator.java").read_text(encoding="utf-8")
        self.assertIn("highDaysCount++;", strat)
        self.assertIn("lowDaysCount++;", strat)
        self.assertIn("dailyRate.divide(TWENTY_FOUR, 10, ROUNDING);", pay)


class OwnerRuleTest(unittest.TestCase):
    """Nothing in this case, fetched or committed, prices interest, a loan or a credit-card charge."""

    def sources(self) -> list:
        out = [p for p in (CASE / "sides").glob("*") if p.is_file()]
        out += [CASE / "tare.json", CASE / "fetch.py", CASE / "build_input.py", CASE / "README.md",
                CASE / "ACT_TWO.md", CASE / "harness" / "HOSRUN.cbl"]
        for rel in ("cache/cobol/HOSDR210.cbl", "cache/cobol/HOSPR210.cbl", "cache/cobol/HOSPRATE.cpy"):
            if (CASE / rel).is_file():
                out.append(CASE / rel)
        return [p for p in out if p.is_file()]

    def test_no_interest_or_credit_logic(self):
        hits = []
        for p in self.sources():
            text = p.read_text(encoding="utf-8", errors="replace").lower()
            for w in FORBIDDEN:
                if w not in text:
                    continue
                # a line of prose that says the thing is absent is the point being made; code and
                # data are scanned with no exemption at all
                said = [ln for ln in text.splitlines() if w in ln]
                if p.suffix == ".md" and all(any(a in ln for a in ("no ", "none", "not ", "never",
                                                                  "without")) for ln in said):
                    continue
                hits.append(f"{p.name}: {w}")
        self.assertEqual(hits, [])

    def test_the_cms_java_and_the_ai_port_carry_none_either(self):
        roots = [CASE / "cache" / "cms_java" / "src",
                 CASE / "cache" / "repos" / "rcaran" / "hospice-pricer-api" / "src" / "main"]
        roots = [r for r in roots if r.is_dir()]
        if not roots:
            self.skipTest("the ports are not fetched (python fetch.py)")
        hits = []
        for root in roots:
            for p in root.rglob("*"):
                if p.is_file() and p.suffix in (".java", ".cbl", ".cpy", ".yaml", ".yml", ".json"):
                    text = p.read_text(encoding="utf-8", errors="replace").lower()
                    # "apr" alone is a month in the AI port's fiscal-year router; a rate is not
                    hits += [f"{p.name}: {w}" for w in FORBIDDEN if w in text]
        self.assertEqual(hits, [])


class ReproduceTest(unittest.TestCase):
    def test_reproduce_offline_gives_the_three_verdicts(self):
        env = dict(os.environ, PYTHONPATH=str(REPO))
        env.pop("TARE_ROOT", None)
        r = subprocess.run([sys.executable, "-m", "tare", "reproduce", "--offline"], cwd=CASE, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"cms-java\s+red\s+red\s+140 of 5000")
        self.assertRegex(r.stdout, r"java-ai\s+red\s+red\s+270 of 5000")
        self.assertRegex(r.stdout, r"java-ai-fixed\s+balanced\s+balanced\s+0 of 5000")
        self.assertIn("reproduce: OK, all 3 sides got their expected verdict", r.stdout)

    def test_every_declared_side_has_an_expected_verdict(self):
        c = cfg()
        self.assertEqual(sorted(c["expected"]), sorted(c["sides"]))
        self.assertEqual(c["expected"], {k: v[0] for k, v in EXPECTED.items()})
        self.assertEqual(c["accepted"], [])


if __name__ == "__main__":
    unittest.main()
