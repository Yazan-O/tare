"""Build the case's input from REI 2018 (DGFiP, Licence Ouverte 2.0): one built-property bill per commune.

REI holds commune-level totals and voted rates, no personal data. For each commune this writes:
  rates.txt  one line per commune, the built-property rates the rate file holds, read by harness/LOADTAU:
             dir;com;ifp;per;PTBDEP;PTBTAS;PTBCOM;PTBSYN;PTBCU;PTBTSN1;PTBTSN2;PTBGEM;
             PBBOMP;PBBOMA;PBBOMB;PBBOMC;PBBOMD;PBBOME
  bills.txt  one 600-byte COMBAT record per commune (the calculator's own input area, copybook XCOMBAT),
             trailing spaces trimmed; tare.json pads each line back to 600 bytes.
The commune's net bases are the bill's bases, so each record is the commune taken as one bill.
The département and TASA rates live at direction level in the rate file; each direction takes its first
commune's values, as the rate file has one value per direction.

Usage: python build_input.py <REI_2018.csv> --out <dir> [--dep 01]
"""
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
    """PIC S9(width) DISPLAY as GnuCOBOL writes it: digits, the sign carried in the last digit (p-y negative)."""
    digits = str(abs(n)).zfill(width)
    if len(digits) > width:
        raise ValueError(f"{n} does not fit in S9({width})")
    return digits if n >= 0 else digits[:-1] + "pqrstuvwxy"[int(digits[-1])]


def combat(cc2dep, ccodir, ccocom, row) -> str:
    """The 600-byte XCOMBAT area; unused fields are spaces, as the calling system leaves them."""
    r = ["2", YEAR, cc2dep, ccodir, ccocom, "A",          # CCOBNB, DAN, AC3DIR, CCOCOM, DSRPAR
         "A", "00001", " " * 8,                            # CGROUP, NNUPRO, GTOTAU(8)
         s9(base(row, "E11")), s9(base(row, "E41")), s9(0),  # MBACOM, MBADEP, MBAREG
         s9(base(row, "E21")), s9(base(row, "E31")), s9(0),  # MBASYN, MBACU, MBATSE
         s9(base(row, "E51")), s9(base(row, "E51A")),        # MBBT13(1), MBBT13(2)
         " " * 20]
    for code, col in ZONES:                                    # ABAOM(6): GTAUOM, MBAOM
        b = base(row, col)
        r += [code if b else "  ", s9(b)]
    teomi = base(row, "TIEOMC") + base(row, "TIEOMS") + base(row, "TIEOMG")
    r += [" " * 120, s9(teomi), " " * 16,                      # FILLER 9(10) x 12, MVLTIM, PVLTOM
          s9(base(row, "E51gGEMAPI")), s9(base(row, "E51TASA")),  # MBAGE3, MBATA3
          ccocom, "001", " " * 230]                            # CCOIFP, CCPPER, FILLER
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
            if len(d) == 3:          # overseas: INSEE 971xx is direction 971, commune 1xx
                cc2dep, ccodir, ccocom = d[:2], d[2], d[2] + com.zfill(2)
            else:
                cc2dep, ccodir, ccocom = d.zfill(2), (dr or "0"), com.zfill(3)
            if dep and cc2dep != dep:
                continue
            n += 1
            ac3 = cc2dep + ccodir
            direction = (rate(row, "E42"), rate(row, "E52TASA"))   # PTBDEP, PTBTAS
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
