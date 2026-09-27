import argparse
import collections
import csv
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

YEAR = "2018"
ZONES = [("P ", "F21"), ("RA", "F31"), ("RB", "F41"), ("RC", "F51"), ("RD", "F61"), ("RE", "F81")]
ZONE_RATES = ["F22", "F32", "F42", "F52", "F62", "F82"]


def num(row, k):
    v = (row.get(k) or "").strip().replace(",", ".")
    return Decimal(v) if v else Decimal(0)


def base(row, k):
    return int(num(row, k).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def rate(row, k):
    return format(num(row, k).quantize(Decimal("0.000001")), "f")


def s9(n: int, width=10) -> str:
    digits = str(abs(n)).zfill(width)
    if len(digits) > width:
        raise ValueError(f"{n} does not fit in S9({width})")
    return digits if n >= 0 else digits[:-1] + "pqrstuvwxy"[int(digits[-1])]


def combat(cc2dep, ccodir, ccocom, row) -> str:
    r = ["2", YEAR, cc2dep, ccodir, ccocom, "A",
         "A", "00001", " " * 8,
         s9(base(row, "E11")), s9(base(row, "E41")), s9(0),
         s9(base(row, "E21")), s9(base(row, "E31")), s9(0),
         s9(base(row, "E51")), s9(base(row, "E51A")),
         " " * 20]
    for code, col in ZONES:
        b = base(row, col)
        r += [code if b else "  ", s9(b)]
    teomi = base(row, "TIEOMC") + base(row, "TIEOMS") + base(row, "TIEOMG")
    r += [" " * 120, s9(teomi), " " * 16,
          s9(base(row, "E51gGEMAPI")), s9(base(row, "E51TASA")),
          ccocom, "001", " " * 230]
    rec = "".join(r)
    assert len(rec) == 600, len(rec)
    return rec.rstrip(" ")


def build(src: Path, out: Path, dep=None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    dirlevel, conflicts, n = {}, collections.Counter(), 0
    with open(src, encoding="utf-8", newline="") as f, \
            open(out / "rates.txt", "w", encoding="ascii", newline="\n") as fr, \
            open(out / "bills.txt", "w", encoding="ascii", newline="\n") as fb:
        for row in csv.DictReader(f, delimiter=";"):
            d, dr, com = row["DEP"].strip(), row["DIR"].strip(), row["COM"].strip()
            if not d or not com:
                continue
            if len(d) == 3:
                cc2dep, ccodir, ccocom = d[:2], d[2], d[2] + com.zfill(2)
            else:
                cc2dep, ccodir, ccocom = d.zfill(2), (dr or "0"), com.zfill(3)
            if dep and cc2dep != dep:
                continue
            n += 1
            ac3 = cc2dep + ccodir
            direction = (rate(row, "E42"), rate(row, "E52TASA"))
            if ac3 not in dirlevel:
                dirlevel[ac3] = direction
            else:
                for name, a, b in zip(("PTBDEP", "PTBTAS"), dirlevel[ac3], direction):
                    conflicts[name] += a != b
            fr.write(";".join([ac3, ccocom, ccocom, "001", *dirlevel[ac3],
                               rate(row, "E12"), rate(row, "E22"), rate(row, "E32"),
                               rate(row, "E52"), rate(row, "E52A"), rate(row, "E52gGEMAPI"),
                               *(rate(row, k) for k in ZONE_RATES)]) + "\n")
            fb.write(combat(cc2dep, ccodir, ccocom, row) + "\n")
    print(f"communes {n}; directions {len(dirlevel)}; communes whose direction-level rate differs from "
          f"their direction's first commune: {dict(+conflicts) or 'none'}; wrote {out}/rates.txt, bills.txt")
    return {"communes": n, "directions": len(dirlevel)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dep", help="one département code, e.g. 01 (default: every commune)")
    a = ap.parse_args()
    build(a.csv, a.out, a.dep)
