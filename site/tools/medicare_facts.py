"""Act two's numbers, each read from the Medicare hospice case's committed fixtures (or quoted from its primary
source), with where it came from. Used by build_medicare.py (the page) and deck/build.py (the slides).

  python site/tools/medicare_facts.py      print every fact and its source
"""
import sys
from decimal import Decimal
from pathlib import Path

TARE = Path(__file__).resolve().parents[2]
CASE = TARE / "cases" / "medicare_hospice"
sys.path.insert(0, str(TARE))
from tare import config, ledger, records  # noqa: E402

SIDES = ("cms-java", "java-ai", "java-ai-fixed")
EXAMPLES = (("C00002", "total", "cms-java"), ("C00082", "high", "java-ai"),
            ("C00033", "rtc", "java-ai"), ("C00408", "pay_chc", "java-ai"))
MEDPAC_URL = "https://www.medpac.gov/wp-content/uploads/2026/03/Mar26_Ch10_MedPAC_Report_To_Congress_SEC.pdf"
# Quoted, not measured: MedPAC, March 2026 report to Congress, chapter 10 (read at the source 2026-09-26,
# _runs/2026-09-26_medicare_case/REPORT.md, deliverable 7).
MEDPAC = {"medpac_hospice_2024": ("$28.3 billion", "MedPAC March 2026 ch. 10: 'In 2024, Medicare's hospice ... paid "
                                  "about $28.3 billion for hospice services' " + MEDPAC_URL),
          "medpac_rhc_share": ("98.8%", "MedPAC March 2026 ch. 10: routine home care is 98.8 percent of Medicare-covered "
                               "hospice days in 2024 " + MEDPAC_URL)}


def facts() -> dict:
    """{key: (value, source)}"""
    F = {}
    cfg = config.load_config(CASE)
    ak_path = CASE / "fixtures" / "answer_key" / "records.json"
    ak = records.load_side(ak_path)
    rows = ak["files"]["ratefile"]
    F["claims"] = (len(rows), "cases/medicare_hospice/fixtures/answer_key/records.json: ratefile records")
    bills = records.decode_bytes((CASE / "fixtures" / "answer_key" / "input" / "billfile.dat").read_bytes(),
                                 config.layout_for(cfg, "billfile"))
    chc = {b["claim"] for b in bills if b["rev2"].strip() == "0652"}
    F["chc_claims"] = (len(chc), "fixtures/answer_key/input/billfile.dat: claims with revenue code 0652")
    F["non_chc_claims"] = (len(bills) - len(chc), "claims - chc_claims")
    a = {r["claim"]: r for r in rows}
    for side in SIDES:
        doc = records.load_side(CASE / "fixtures" / "sides" / side / "records.json")
        w = ledger.weigh(ak, doc, cfg, [])
        src = f"cases/medicare_hospice/fixtures/sides/{side}/records.json weighed against the answer key"
        key = side.replace("-", "_")
        F[f"{key}_differ"] = (w["summary"]["records_differ"], src)
        b = {r["claim"]: r for r in doc["files"]["ratefile"]}
        if side == "java-ai":
            F["java_ai_differ_chc"] = (sum(1 for c in chc if a[c] != b[c]), src + ", CHC claims only")
            F["java_ai_differ_non_chc"] = (sum(1 for c in set(a) - chc if a[c] != b[c]), src + ", claims without CHC")
        if side == "cms-java":
            diffs = {abs(Decimal(b[c]["total"]) - Decimal(a[c]["total"])) for c in a if a[c] != b[c]}
            fields = {r["field"] for r in w["rows"] if r["status"] != "accepted"}
            assert fields == {"total"} and diffs == {Decimal("0.01")}, (fields, diffs)
            F["cms_java_cents_total"] = (f"${Decimal('0.01') * F['cms_java_differ'][0]:.2f}",
                                         src + ": every difference is $0.01 on the total field")
    for claim, field, side in EXAMPLES:
        b = next(r for r in records.load_side(CASE / "fixtures" / "sides" / side / "records.json")["files"]["ratefile"]
                 if r["claim"] == claim)
        F[f"ex_{claim}_{field}"] = ((a[claim][field], b[field], side),
                                    f"fixtures/answer_key and fixtures/sides/{side}: claim {claim}, field {field}")
    F.update(MEDPAC)
    return F


if __name__ == "__main__":
    for k, (v, s) in facts().items():
        print(f"{k:26} {str(v):32} {s}")
