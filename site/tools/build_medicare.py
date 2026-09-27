import json
from pathlib import Path

from medicare_facts import facts

DIST = Path(__file__).resolve().parents[1] / "dist"


def main():
    F = facts()
    doc = {"values": {k: v for k, (v, _) in F.items()}, "sources": {k: s for k, (_, s) in F.items()}}
    out = DIST / "data" / "medicare.js"
    out.write_text("window.TARE_MEDICARE=" + json.dumps(doc, ensure_ascii=False) + ";\n", encoding="utf-8", newline="\n")
    print(f"{out.relative_to(DIST.parent)}: {len(F)} facts")


if __name__ == "__main__":
    main()
