"""Write the page's data files into site/dist/ from the case's run output.

  dist/data/communes.js   site/data/communes.json as one assignment (script tags work from file://)
  dist/data/map.js        site/data/map.json, likewise
  dist/data/run.js        the demo slice's counts (committed fixtures) and lines of the national reproduce log
  dist/img/scale_*.png    Tare's scale images from the national weigh (cases/taxe_fonciere/full/.tare/)

Usage (from site/tools): python build_site.py --log <reproduce log of the national run> --date 2026-09-26
"""
import argparse
import json
import shutil
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
CASE = SITE.parent / "cases" / "taxe_fonciere"
DIST = SITE / "dist"


def as_js(name: str, src: Path, dst: Path):
    body = src.read_text(encoding="utf-8")
    json.loads(body)
    dst.write_text(f"window.{name}=" + body + ";\n", encoding="utf-8", newline="\n")
    print(f"{dst.relative_to(SITE)} ({dst.stat().st_size} bytes)")


def records(path: Path) -> dict:
    return {r["commune"]: r for r in json.loads(path.read_text(encoding="utf-8"))["files"]["retours"]}


def demo_counts() -> dict:
    ak = records(CASE / "fixtures" / "answer_key" / "records.json")
    out = {"records": len(ak)}
    for side, key in (("java-ai", "ai_differ"), ("java-ai-fixed", "fixed_differ")):
        s = records(CASE / "fixtures" / "sides" / side / "records.json")
        assert set(s) == set(ak)
        out[key] = sum(any(s[k][f] != ak[k][f] for f in ak[k]) for k in ak)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--date", required=True)
    a = ap.parse_args()
    (DIST / "data").mkdir(parents=True, exist_ok=True)
    (DIST / "img").mkdir(parents=True, exist_ok=True)
    as_js("TARE", SITE / "data" / "communes.json", DIST / "data" / "communes.js")
    as_js("TARE_MAP", SITE / "data" / "map.json", DIST / "data" / "map.js")

    keep = ("TARE RED", "TARE BALANCED", "reproduce: OK")
    log = [ln.strip() for ln in a.log.read_text(encoding="utf-8").splitlines()]
    lines = []
    for ln in log:
        if ln.startswith(keep) and ln not in lines:
            lines.append(ln)
    assert any(ln.startswith("TARE RED") for ln in lines) and any(ln.startswith("TARE BALANCED") for ln in lines)

    d = json.loads((SITE / "data" / "communes.json").read_text(encoding="utf-8"))
    n, ai, fx = d["records"], d["sides"]["java-ai"]["records_differ"], d["sides"]["java-ai-fixed"]["records_differ"]
    tare_dir = CASE / "full" / ".tare"
    scale = []
    for side, dst, cap in (
            ("java-ai", "scale_published.png",
             f"Published port, national replay: {ai:,} of {n:,} commune records differ. Tare's scale image, "
             f"the picture its weigh returns to Bob's chat."),
            ("java-ai-fixed", "scale_repaired.png",
             f"Repaired port, national replay: {fx:,} of {n:,} commune records differ. The scale is level.")):
        shutil.copyfile(tare_dir / f"scale_{side}.png", DIST / "img" / dst)
        scale.append({"src": f"img/{dst}", "caption": cap})
    run = {"date": a.date, "demo": demo_counts(), "log": lines, "scale": scale}
    (DIST / "data" / "run.js").write_text("window.TARE_RUN=" + json.dumps(run, ensure_ascii=False) + ";\n",
                                          encoding="utf-8", newline="\n")
    print("run.js", run["demo"], len(lines), "log lines")


if __name__ == "__main__":
    main()
