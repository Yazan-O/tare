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
sys.path.insert(0, str(CASE / "sides"))
import fix_port  # noqa: E402
ANSWER = CASE / "fixtures" / "answer_key" / "records.json"
COMMITTED = CASE / "input" / "billfile.txt"
INPUT = CASE / "fixtures" / "answer_key" / "input" / "billfile.dat"
SIDES = ("cms-java", "java-ai", "java-ai-fixed")
BILLFILE_SHA256 = "db7744b9063861c062a5f8e6a8c41e239e59a564d968d0d7cd50304e97f9603a"
RECORD_LENGTH = 315
EXPECTED = {"cms-java": ("red", 140), "java-ai": ("red", 270), "java-ai-fixed": ("balanced", 0)}
EXAMPLES = (("C00002", "total", "2162.16", "2162.15"),
            ("C00082", "high", "7", "8"),
            ("C00033", "rtc", "00", "73"),
            ("C00408", "pay_chc", "1421.42", "1421.43"))
COBOL_LINES = ((207, "WRK-PAY-RATE2"), (4544, "BILL-HIGH-RHC-DAYS"), (5289, "BILL-HIGH-RHC-DAYS"),
               (5857, "BILL-PAY-AMT-TOTAL"), (5997, "BILL-LOW-RHC-DAYS"), (6018, "RHC-LOW-DAY-IND"),
               (6036, "BILL-HIGH-RHC-DAYS"), (6055, "RHC-HIGH-DAY-IND"), (6280, "BILL-RTC"),
               (6309, "BILL-RTC"), (6409, "WRK-PAY-RATE2"), (6418, "WRK-PAY-RATE2"),
               (6430, "WRK-PAY-RATE2"))
FORBIDDEN = ("interest", "loan", "credit card", "credit-card", "finance charge", "usury", "apr rate")


def cfg() -> dict:
    return config.load_config(CASE)


def side_records(name: str) -> dict:
    return records.load_side(CASE / "fixtures" / "sides" / name / "records.json")


def tally(weighed: dict) -> dict:
    return dict(collections.Counter(r["field"] for r in weighed["rows"] if r["status"] != "accepted"))


def value(name: str, claim: str, field: str) -> str:
    return next(r[field] for r in side_records(name)["files"]["ratefile"] if r["claim"] == claim)


class ConfigTest(unittest.TestCase):
    def test_tare_json_validates(self):
        answerkey.validate(cfg())

    def test_every_output_field_sits_inside_the_315_byte_record(self):
        lay = config.layout_for(cfg(), "ratefile")
        self.assertEqual(lay["record_length"], RECORD_LENGTH)
        self.assertEqual(lay["key"], ["claim"])
        for f in lay["fields"]:
            self.assertLessEqual(f["offset"] + f["length"], RECORD_LENGTH, f)
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
            self.assertTrue("20201001" <= r["from_date"] <= "20210930", r)
            self.assertLessEqual(r["admission_date"], r["from_date"], r)
            self.assertEqual(r["npi"], "1234567890")
            self.assertEqual(r["prov_no"], "341234")

    def test_the_wage_index_table_is_cms_own_and_holds_every_cbsa_the_claims_use(self):
        table = (CASE / "fixtures" / "answer_key" / "input" / "cbsafile.dat").read_bytes()
        self.assertEqual(len(table) % 80, 0)
        rows = [table[i:i + 80].decode("latin-1") for i in range(0, len(table), 80)]
        self.assertEqual(len(rows), 7478)
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
        self.assertEqual(tally(result), {"total": 140})
        cents = {abs(round(float(r["port"]) - float(r["answer"]), 2)) for r in result["rows"]}
        self.assertEqual(cents, {0.01})

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
        self.assertEqual(len(chc), 776)
        for claim in set(a) - chc:
            self.assertEqual(a[claim], b[claim], claim)
        self.assertEqual(sum(1 for c in chc if a[c] != b[c]), 270)


class ExplainWithoutCacheTest(unittest.TestCase):
    def test_a_fresh_clone_is_told_to_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "case"
            shutil.copytree(CASE, root, ignore=shutil.ignore_patterns("cache", "work"))
            text = explain.explain(root, key="C00082", field="high", port="java-ai")
        self.assertIn("answer key  7", text)
        self.assertIn("The COBOL is not on this machine (cache/cobol/HOSDR210.cbl, cache/cobol/HOSPR210.cbl)", text)
        self.assertIn("run: python fetch.py", text)


class ExplainTest(unittest.TestCase):

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
        self.assertRegex(text, r"\n\s+80 \| +\S")

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
        self.assertRegex(text, r"\n\s+81 \| +\S")

    def test_c00002_the_cms_java_total(self):
        text = explain.explain(CASE, key="C00002", field="total", port="cms-java")
        self.assertIn("answer key  2162.16", text)
        self.assertIn("port        2162.15", text)
        self.assertIn("cache/cobol/HOSPR210.cbl:5857-5862", text)
        self.assertIn("CalculateFinalPayments.java:36-43", text)
        self.assertRegex(text, r"\n\s+37 \| +\S")

    def test_the_repaired_port_balances_on_the_same_claims(self):
        for claim, field, _, _ in EXAMPLES:
            fixed = value("java-ai-fixed", claim, field)
            cobol = next(r[field] for r in records.load_side(ANSWER)["files"]["ratefile"]
                         if r["claim"] == claim)
            self.assertEqual(fixed, cobol, f"{claim} {field}")


class CitedLineTest(unittest.TestCase):

    def setUp(self):
        p = CASE / "cache" / "cobol" / "HOSPR210.cbl"
        if not p.is_file():
            self.skipTest("the CMS COBOL is not fetched (python fetch.py)")
        self.lines = p.read_text(encoding="latin-1").splitlines()

    def test_the_cited_lines_say_what_the_case_says_they_say(self):
        for n, text in COBOL_LINES:
            self.assertIn(text, self.lines[n - 1], f"HOSPR210.cbl:{n} does not hold {text!r}")

    def test_the_chc_paragraph_writes_no_day_count_and_no_return_code(self):
        paragraph = self.lines[6322:6440]
        code = [l[7:72] for l in paragraph if len(l) > 6 and l[6] not in "*/"]
        for forbidden in ("BILL-HIGH-RHC-DAYS", "BILL-LOW-RHC-DAYS", "BILL-RTC"):
            self.assertFalse([l for l in code if forbidden in l], forbidden)
        self.assertTrue([l for l in code if "WRK-PAY-RATE2 ROUNDED" in l])


class FixSpecTest(unittest.TestCase):

    SPEC_PATH = CASE / "sides" / "ai_port_fixes.json"
    FILES = ["hospice-pricer-api/src/main/java/com/cms/hospice/pricing/FullPricerStrategy.java",
             "hospice-pricer-api/src/main/java/com/cms/hospice/pricing/PaymentCalculator.java"]

    def spec(self):
        return fix_port.load(self.SPEC_PATH)

    def test_five_edits_in_two_files_at_the_pinned_commit(self):
        spec = self.spec()
        self.assertEqual(spec["commit"], "655847671859b67a188c5dae6a86c45a74bfa046")
        self.assertEqual(fix_port.files(spec), self.FILES)
        self.assertEqual([(e["line"], e["action"]) for e in spec["edits"]],
                         [(79, "delete"), (80, "delete"), (85, "delete"), (86, "delete"), (81, "replace")])
        for e in spec["edits"]:
            self.assertRegex(e["sha256"], r"^[0-9a-f]{64}$")

    def test_no_port_line_is_stored_only_its_digest(self):
        spec = self.spec()
        stored = {k for e in spec["edits"] for k in e} - {"file", "line", "sha256", "action", "why", "old", "new"}
        self.assertEqual(stored, set())
        replace = next(e for e in spec["edits"] if e["action"] == "replace")
        self.assertLessEqual(len(replace["old"]), 16)
        self.assertFalse((CASE / "sides" / "ai-port-fixes.patch").exists())

    def test_a_changed_line_stops_every_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in self.FILES:
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_bytes(b"x\r\n" * 120)
            before = {rel: (root / rel).read_bytes() for rel in self.FILES}
            with self.assertRaises(fix_port.FixError):
                fix_port.apply(root, self.spec())
            self.assertEqual({rel: (root / rel).read_bytes() for rel in self.FILES}, before)

    def test_the_edits_apply_to_the_fetched_port_and_change_only_their_lines(self):
        port = CASE / "cache" / "repos" / "rcaran"
        if not (port / "hospice-pricer-api" / "pom.xml").is_file():
            self.skipTest("the AI port is not fetched (python fetch.py)")
        self.assertEqual(fix_port.check(port, self.spec()), [])
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "port"
            shutil.copytree(port, work, ignore=shutil.ignore_patterns(".git", "target"))
            self.assertEqual(fix_port.apply(work, self.spec()), self.FILES)
            old = [l for l in (port / self.FILES[0]).read_bytes().splitlines(keepends=True)]
            new = (work / self.FILES[0]).read_bytes().splitlines(keepends=True)
            self.assertEqual(new, [l for n, l in enumerate(old, 1) if n not in (79, 80, 85, 86)])
            old = (port / self.FILES[1]).read_bytes().splitlines(keepends=True)
            new = (work / self.FILES[1]).read_bytes().splitlines(keepends=True)
            self.assertEqual(len(new), len(old))
            self.assertEqual([n for n, (a, b) in enumerate(zip(old, new), 1) if a != b], [81])
            self.assertIn(b"4, RoundingMode.DOWN)", new[80])


class OwnerRuleTest(unittest.TestCase):

    def sources(self) -> list:
        out = [p for p in (CASE / "sides").glob("*") if p.is_file()]
        out += [CASE / "tare.json", CASE / "fetch.py", CASE / "build_input.py", CASE.parent.parent / "README.md",
                CASE / "harness" / "HOSRUN.cbl"]
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
