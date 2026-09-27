import argparse
import csv
import json
from pathlib import Path

SHOWN = ["tcthfr", "tctom", "mfa300", "mfn300", "mfa800", "mfn800", "mfa900", "mfn900", "tctfra", "tctdu"]


def key_of(row):
    d, dr, com = row["DEP"].strip(), row["DIR"].strip(), row["COM"].strip()
    if len(d) == 3:
        return d[:2] + d[2] + d[2] + com.zfill(2), d + com.zfill(2)
    return d.zfill(2) + (dr or "0") + com.zfill(3), d.zfill(2) + com.zfill(3)


def load(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {r["commune"]: r for r in doc["files"]["retours"]}, doc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rei", type=Path, required=True)
    ap.add_argument("--answer", type=Path, required=True)
    ap.add_argument("--side", action="append", default=[])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--names", action="append", default=[])
    a = ap.parse_args()
    usual = {}
    for dbf in a.names:
        import shapefile
        with open(dbf, "rb") as f:
            r = shapefile.Reader(dbf=f, encoding="cp1252")
            fl = [x[0] for x in r.fields[1:]]
            for rec in r.iterRecords():
                usual[rec[fl.index("INSEE_COM")]] = rec[fl.index("NOM_COM")].strip()

    names, insee = {}, {}
    with open(a.rei, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if not row["DEP"].strip() or not row["COM"].strip():
                continue
            k, code = key_of(row)
            insee[k], names[k] = code, usual.get(code) or row["LIBCOM"].strip()
    ak, _ = load(a.answer)
    keys = list(ak)
    missing = [k for k in keys if k not in insee]
    assert not missing, f"answer-key records with no REI row: {missing[:5]}"
    compared = [f for f in ak[keys[0]] if f != "commune"]
    if a.names:
        print(f"names: {sum(insee[k] in usual for k in keys)} of {len(keys)} from ADMIN EXPRESS, the rest from REI")

    out = {
        "about": ("2018 built-property property tax (taxe foncière bâtie), one record per commune: the commune's "
                  "REI 2018 totals and voted rates reshaped into one calculator input. Not household bills. "
                  "Amounts in whole euros, as the calculator returns them."),
        "records": len(keys), "compared_fields": len(compared), "fields": SHOWN,
        "insee": [insee[k] for k in keys], "name": [names[k] for k in keys],
        "answer_key": {f: [int(ak[k][f] or 0) for k in keys] for f in SHOWN},
        "sides": {},
    }
    for spec in a.side:
        name, path = spec.split("=", 1)
        side, _ = load(path)
        assert set(side) == set(keys), f"{name}: records differ in keys from the answer key"
        ndiff = [sum(side[k][f] != ak[k][f] for f in compared) for k in keys]
        cols, equal = {}, []
        for f in SHOWN:
            vals = [int(side[k][f] or 0) for k in keys]
            if any(v != int(ak[k][f] or 0) for v, k in zip(vals, keys)):
                cols[f] = vals
            else:
                equal.append(f)
        out["sides"][name] = {"source": str(path).replace("\\", "/"), "records_differ": sum(n > 0 for n in ndiff),
                              "fields_differ": sum(ndiff), "ndiff": ndiff, "values": cols,
                              "equal_to_answer_key_on_every_record": equal}
        print(f"{name}: {out['sides'][name]['records_differ']} of {len(keys)} records differ, "
              f"{sum(ndiff)} fields; columns {sorted(cols)}; equal {equal}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"wrote {a.out} ({a.out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
