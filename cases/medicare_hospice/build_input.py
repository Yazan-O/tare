import argparse
import datetime as dt
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
CBSA = HERE / "cache" / "cobol" / "CBSA2021"
OUT = HERE / "input"
NPI, CCN, PROV_EFF = "1234567890", "341234", "20201001"
FY_START = dt.date(2020, 10, 1)
MONTHS = [dt.date(2020 + (9 + i) // 12, (9 + i) % 12 + 1, 1) for i in range(12)]
SLOT = {"0651": 0, "0652": 1, "0655": 2, "0656": 3}
RECLEN = {"cbsafile.txt": 80, "provfile.txt": 240, "billfile.txt": 315}


def cbsa_rows() -> list:
    rows = []
    for line in CBSA.read_bytes().decode("latin-1").splitlines():
        if line[:5].isdigit():
            rows.append(line.ljust(80)[:80])
    return rows


def prov_row() -> str:
    rec = (NPI + CCN + PROV_EFF).ljust(240)
    return rec[:240]


def claims(n: int, seed: int) -> list:
    rng = random.Random(seed)
    cbsas = sorted({l[:5] for l in cbsa_rows() if l[6:14] == "20201001"})
    out = []
    for i in range(n):
        m = rng.choice(MONTHS)
        band = rng.random()
        if band < 0.3:
            los = rng.randint(0, 30)
        elif band < 0.6:
            los = rng.randint(31, 90)
        else:
            los = rng.randint(91, 400)
        if rng.random() < 0.7:
            frm = m
            adm = frm - dt.timedelta(days=los)
        else:
            frm = m + dt.timedelta(days=rng.randint(0, 27))
            adm = frm
        last = dt.date(frm.year + frm.month // 12, frm.month % 12 + 1, 1) - dt.timedelta(days=1)
        span = (last - frm).days + 1
        bene = rng.choice(cbsas)
        prov = bene if rng.random() < 0.8 else rng.choice(cbsas)
        prior = 0 if rng.random() < 0.75 else rng.randint(1, 99)
        qip = "1" if rng.random() < 0.05 else " "
        lines = {}
        if rng.random() < 0.95:
            lines["0651"] = (frm, rng.randint(1, span))
        if rng.random() < 0.15:
            lines["0652"] = (frm + dt.timedelta(days=rng.randint(0, span - 1)), rng.randint(1, 96))
        if rng.random() < 0.08:
            lines["0655"] = (frm + dt.timedelta(days=rng.randint(0, span - 1)), rng.randint(1, 5))
        if rng.random() < 0.08:
            lines["0656"] = (frm + dt.timedelta(days=rng.randint(0, span - 1)), rng.randint(1, 10))
        if not lines:
            lines["0656"] = (frm, rng.randint(1, 10))
        eol = []
        if "0651" in lines and rng.random() < 0.12:
            eol = [rng.randint(1, 24) for _ in range(rng.randint(1, 7))]
        out.append(dict(id=f"C{i + 1:05d}", from_date=frm, admission=adm, prov=prov, bene=bene,
                        prior=prior, qip=qip, eol=eol, lines=lines))
    return out


def bill_record(c: dict) -> str:
    groups = [" " * 32] * 4
    for rev, (dos, units) in c["lines"].items():
        groups[SLOT[rev]] = rev + " " * 5 + dos.strftime("%Y%m%d") + f"{units:07d}" + "0" * 8
    eol = (c["eol"] + [0] * 7)[:7]
    rec = (NPI + CCN + c["from_date"].strftime("%Y%m%d") + c["admission"].strftime("%Y%m%d") + " " * 10
           + c["prov"] + c["bene"] + "0" * 12
           + f"{c['prior']:02d}" + "00" + "".join(f"{u:02d}" for u in eol)
           + " " * 10 + c["qip"] + "".join(groups) + "0" * 72 + "0" * 8 + "00"
           + "0000" + c["id"].ljust(8))
    assert len(rec) == RECLEN["billfile.txt"], len(rec)
    return rec


def write(name: str, records: list) -> None:
    p = OUT / name
    p.write_text("".join(r + "\n" for r in records), encoding="latin-1", newline="\n")
    print(f"  {p.relative_to(HERE.parent.parent).as_posix()}: {len(records)} records of {RECLEN[name]} bytes")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--claims", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=20260926)
    a = ap.parse_args()
    if not CBSA.is_file():
        raise SystemExit(f"{CBSA} is missing; run: python fetch.py")
    OUT.mkdir(exist_ok=True)
    cs = claims(a.claims, a.seed)
    write("cbsafile.txt", cbsa_rows())
    write("provfile.txt", [prov_row()])
    write("billfile.txt", [bill_record(c) for c in cs])
    print(f"claims={len(cs)} cbsas_effective_20201001="
          f"{len({l[:5] for l in cbsa_rows() if l[6:14] == '20201001'})} seed={a.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
