"""python -m tare accept: a person signs an accepted difference in tare.json, with exact values.

`accept --file <file> --key <key> --by "<name>" --reason "<text>" [--fields a,b] [--expect port|answer_key]`
writes one entry {file, key, fields, expect, reason, accepted_by, date, seal} for that record:
- --expect port (default): expect is {field: the port's current value} for each listed field (default: every
  field of the record that differs now). The port must keep writing exactly those values; the answer key's
  own values also pass; any other value is red.
- --expect answer_key: the listed fields are pinned to the answer key's values (a signed review; it accepts
  no other value).
It prints the answer key's values, the expected values and the port's current output (rerun first when stale).
`accept --revoke --file <file> --key <key>` removes the entry. Both write .tare/accept_seal.json, the hash of
the tare.json they wrote, so the gate lets that tare.json (differing from HEAD in 'accepted' only) be
committed; each entry carries its own seal, so a hand-edited entry covers nothing.
"""
import datetime
import json
from pathlib import Path

from . import config, ledger, localport, records


def _write(root: Path, cfg: dict):
    p = root / "tare.json"
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    (config.state_dir(root) / "accept_seal.json").write_text(
        json.dumps({"tare_json_sha256": config.sha256_file(p)}) + "\n", encoding="utf-8", newline="\n")


def _file(cfg: dict, file):
    outs = config.outputs(cfg)
    if file is None:
        if len(outs) != 1:
            raise ValueError(f"--file is required: tare.json has output files {', '.join(outs)}")
        return outs[0]
    if file not in outs:
        raise ValueError(f"{file!r} is not an output file in tare.json ({', '.join(outs)})")
    return file


def _record(doc: dict, file: str, key: str, layout: dict):
    for r in (doc.get("files") or {}).get(file, []):
        if ledger.key_text(records.key_of(r, layout)) == key:
            return r
    return None


def accept(root: Path, file, key: str, by: str, reason: str, fields=None, expect="port") -> int:
    if not (by or "").strip() or not (reason or "").strip():
        raise ValueError("--by and --reason are required")
    if expect not in ("port", "answer_key"):
        raise ValueError("--expect is 'port' or 'answer_key'")
    cfg = config.load_config(root)
    file = _file(cfg, file)
    lay = config.layout_for(cfg, file)
    if localport.staleness(root):
        localport.run(root)
    a = _record(records.load_side(root / config.ANSWER_KEY), file, key, lay)
    p = _record(records.load_side(root / localport.OUT / config.RECORDS), file, key, lay)
    if a is None or p is None:
        raise ValueError(f"{file} record {key} is not in the {'answer key' if a is None else 'port'}'s output")
    numeric = {f["name"]: records.is_numeric(f) for f in lay["fields"]}
    if fields:
        unknown = [f for f in fields if f not in numeric]
        if unknown:
            raise ValueError(f"no field {', '.join(unknown)} in layout {cfg['files'][file]['layout']}")
    else:
        fields = [f for f in numeric if not ledger.same(a.get(f), p.get(f), numeric[f])]
        if not fields:
            raise ValueError(f"{file} record {key}: the port already writes the answer key's values; nothing to accept")
    entry = {"file": file, "key": key, "fields": list(fields),
             "expect": {f: p.get(f) for f in fields} if expect == "port" else "answer_key",
             "reason": reason.strip(), "accepted_by": by.strip(), "date": datetime.date.today().isoformat()}
    entry["seal"] = ledger.entry_seal(entry)
    exp = ledger.expected_values(entry, a)
    cfg["accepted"] = [e for e in cfg.get("accepted", [])
                       if not (e.get("file") == file and str(e.get("key")) == key)] + [entry]
    _write(root, cfg)
    print(f"ACCEPTED  {file} record {key}, signed by {entry['accepted_by']} on {entry['date']}")
    print("  " + ("expect: the port's current values (the answer key's own values also pass)" if expect == "port"
                  else "expect: the answer key's values (a signed review; no other value passes)"))
    print(f"  {'field':<14}{'answer key':>14}{'expected':>14}{'port now':>14}")
    for f, v in exp.items():
        print(f"  {f:<14}{str(a.get(f)):>14}{v:>14}{str(p.get(f)):>14}")
    print(f"  reason: {entry['reason']}")
    if not all(ledger.same(p.get(f), v, numeric[f]) or ledger.same(p.get(f), a.get(f), numeric[f])
               for f, v in exp.items()):
        print("  note: the port writes neither the expected nor the answer key's values; still red")
    print("Written to tare.json; any other value is red. Next: weigh local, commit tare.json.")
    return 0


def revoke(root: Path, file, key: str) -> int:
    cfg = config.load_config(root)
    file = _file(cfg, file)
    gone = [e for e in cfg.get("accepted", []) if e.get("file") == file and str(e.get("key")) == key]
    if not gone:
        raise ValueError(f"no accepted difference for {file} record {key} in tare.json")
    cfg["accepted"] = [e for e in cfg.get("accepted", []) if e not in gone]
    _write(root, cfg)
    print(f"REVOKED  {file} record {key} (was signed by {gone[0].get('accepted_by')} on {gone[0].get('date')}). "
          "Next: weigh local, commit tare.json.")
    return 0
