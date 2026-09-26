"""The ledger: align a port's records against the answer key's, by key per output file, field by field.

Numeric fields compare in Decimal; text fields compare as strings. Every declared field is compared.
Accepted differences (tare.json 'accepted') are entries
  {file, key, fields, expect: {field: value} | "answer_key", reason, accepted_by, date, seal}
An entry covers only the listed fields of the one record it names, and only when the port writes exactly the
expected value: {field: value} pins that value; "answer_key" pins the answer key's own value (a signed review
that accepts no other value). The answer key's own value always passes. An entry whose seal does not match its
content (a hand edit) covers nothing. Missing and extra records are never accepted.
"""
from decimal import Decimal, InvalidOperation

from . import config, records


def entry_seal(entry: dict) -> str:
    """The seal `tare accept` writes: sha256 of the entry's content without the seal."""
    return config.sha256_json({k: v for k, v in entry.items() if k != "seal"})


def key_text(key: tuple) -> str:
    return "|".join(key)


def _dec(value, where) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError(f"{where}: not a decimal: {value!r}") from None


def same(a, b, numeric: bool) -> bool:
    if a is None or b is None:
        return a is b
    if not numeric:
        return str(a) == str(b)
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, TypeError):
        return False


def signed(d: Decimal) -> str:
    return ("+" if d > 0 else "") + str(d)


def _keyed(items, layout):
    """[(key + occurrence index, item)] so a repeated key still aligns in order."""
    seen, out = {}, []
    for it in items:
        k = records.key_of(it, layout)
        n = seen.get(k, 0)
        seen[k] = n + 1
        out.append((k + (n,), it))
    return out


def expected_values(entry: dict, answer_rec: dict) -> dict:
    """{field: value the port must write} for an accepted entry; {} when it covers nothing."""
    fields = [f for f in entry.get("fields") or [] if isinstance(f, str)]
    exp = entry.get("expect")
    if isinstance(exp, dict):
        return {f: str(exp[f]) for f in fields if f in exp}
    if exp == "answer_key" and answer_rec is not None:
        return {f: str(answer_rec.get(f)) for f in fields if f in answer_rec}
    return {}


def _entries_for(accepted, file, key):
    out = []
    for e in accepted or []:
        if isinstance(e, dict) and e.get("file") == file and str(e.get("key")) == key:
            out.append(e)
    return out


def weigh(answer: dict, port: dict, cfg: dict, accepted=None) -> dict:
    """Compare two records documents over tare.json's output files. Returns {'summary', 'rows'}.

    A row is one differing field of a matched record ({file, key, field, answer, port, delta, status}, status
    higher, lower, differs or accepted), or a whole record ({field: '*', status missing or extra}).
    """
    rows, numeric = [], {}
    total = differ = fields_differ = missing = extra = 0
    higher_all = lower_all = 0
    accepted_used, unsealed = [], []
    for e in accepted or []:
        if isinstance(e, dict) and e.get("seal") != entry_seal(e) and e not in unsealed:
            unsealed.append(e)
    for file in config.outputs(cfg):
        lay = config.layout_for(cfg, file)
        nums = [f["name"] for f in lay["fields"] if records.is_numeric(f)]
        stats = {n: {"higher": 0, "lower": 0, "net": Decimal(0)} for n in nums}
        numeric[file] = stats
        a_items = _keyed((answer.get("files") or {}).get(file, []), lay)
        p_items = dict(_keyed((port.get("files") or {}).get(file, []), lay))
        used = set()
        for key, a in a_items:
            total += 1
            kt = key_text(key[:-1])
            p = p_items.get(key)
            if p is None:
                missing += 1
                differ += 1
                for n in nums:
                    stats[n]["net"] -= _dec(a.get(n), f"answer key {file} {kt} {n}")
                rows.append({"file": file, "key": kt, "field": "*", "answer": None, "port": None,
                             "delta": None, "status": "missing"})
                continue
            used.add(key)
            entries = [e for e in _entries_for(accepted, file, kt) if e not in unsealed]
            red = False
            for f in lay["fields"]:
                name, is_num = f["name"], records.is_numeric(f)
                av, pv = a.get(name), p.get(name)
                if same(av, pv, is_num):
                    continue
                row = {"file": file, "key": kt, "field": name, "answer": None if av is None else str(av),
                       "port": None if pv is None else str(pv), "delta": None}
                if is_num and av is not None and pv is not None:
                    d = _dec(pv, f"port {file} {kt} {name}") - _dec(av, f"answer key {file} {kt} {name}")
                    row["delta"] = signed(d)
                    row["status"] = "higher" if d > 0 else "lower"
                    stats[name]["net"] += d
                    stats[name]["higher" if d > 0 else "lower"] += 1
                else:
                    row["status"] = "differs"
                for e in entries:
                    exp = expected_values(e, a)
                    if name in exp:
                        row["accepted_value"] = exp[name]
                        if same(pv, exp[name], is_num):
                            row.update(difference=row["status"], status="accepted", reason=e.get("reason"),
                                       accepted_by=e.get("accepted_by"), date=e.get("date"))
                            if e not in accepted_used:
                                accepted_used.append(e)
                            break
                if row["status"] != "accepted":
                    red = True
                    fields_differ += 1
                    if row["status"] == "higher":
                        higher_all += 1
                    elif row["status"] == "lower":
                        lower_all += 1
                rows.append(row)
            differ += red
        for key, p in p_items.items():
            if key in used:
                continue
            extra += 1
            differ += 1
            for n in nums:
                try:
                    stats[n]["net"] += _dec(p.get(n), f"port {file} {n}")
                except ValueError:
                    pass
            rows.append({"file": file, "key": key_text(key[:-1]), "field": "*", "answer": None, "port": None,
                         "delta": None, "status": "extra"})
    for stats in numeric.values():
        for s in stats.values():
            s["net"] = signed(s["net"])
    summary = {
        "answer_side": answer.get("side"),
        "port_side": port.get("side"),
        "records_total": total,
        "records_differ": differ,
        "fields_differ": fields_differ,
        "missing": missing,
        "extra": extra,
        "higher": higher_all,
        "lower": lower_all,
        "numeric": numeric,
        "accepted": len(accepted_used),
        "accepted_fields": sum(1 for r in rows if r["status"] == "accepted"),
        "accepted_entries": accepted_used,
        "unsealed_entries": len(unsealed),
        "port_notes": port.get("notes", []),
    }
    summary["verdict"] = "balanced" if differ == 0 else "red"
    summary["result_line"] = result_line(summary)
    return {"summary": summary, "rows": rows}


def _accepted_note(s: dict) -> str:
    n = s.get("accepted", 0)
    return f" ({n} accepted difference{'s' if n != 1 else ''})" if n else ""


def result_line(s: dict) -> str:
    n = s["records_total"]
    if s["verdict"] == "balanced":
        return f"weigh: {n} of {n} records balance" + _accepted_note(s)
    return f"weigh: {s['records_differ']} of {n} records differ" + _accepted_note(s)


def _field_detail(s: dict) -> list:
    out = []
    for file, stats in (s.get("numeric") or {}).items():
        for name, st in stats.items():
            if st["higher"] or st["lower"]:
                label = name if len(s["numeric"]) == 1 else f"{file}.{name}"
                out.append(f"{label}: {st['higher']} higher, {st['lower']} lower, net {st['net']}")
    return out


def describe(s: dict) -> str:
    """One plain sentence, e.g. '3 of 5 records differ from the answer key (total_lb: 3 higher, 0 lower, net +0.03)'."""
    n = s["records_total"]
    if s["verdict"] == "balanced":
        return f"{n} of {n} records balance" + _accepted_note(s)
    if n and s["missing"] == n:
        head = f"0 of {n} records written by the port (all {n} missing)"
        if s["extra"]:
            head += f"; {s['extra']} extra record{'s' if s['extra'] != 1 else ''} in the port"
        return head + _accepted_note(s)
    detail = _field_detail(s)
    if s["missing"]:
        detail.append(f"{s['missing']} missing from the port")
    if s["extra"]:
        detail.append(f"{s['extra']} extra in the port")
    return (f"{s['records_differ']} of {n} records differ from the answer key"
            + (f" ({'; '.join(detail)})" if detail else "") + _accepted_note(s))


def _pins(e: dict) -> str:
    exp = e.get("expect")
    if isinstance(exp, dict):
        return ", ".join(f"{k} {v}" for k, v in exp.items())
    if exp == "answer_key":
        return f"{', '.join(e.get('fields') or [])} as the answer key"
    return f"expect {exp!r} (covers nothing)"


def _accepted_tag(r: dict) -> str:
    v = r.get("accepted_value")
    if r["status"] == "accepted":
        return f"  ACCEPTED (expected {v})" if v is not None else "  ACCEPTED"
    return f"  (accepted value {v})" if v is not None else ""


def _r(v, w):
    return ("" if v is None else str(v)).rjust(w)


def format_table(result: dict, limit=None) -> str:
    """Header line, then only the differing rows."""
    s = result["summary"]
    head = (f"TARE {s['verdict'].upper()}  {s.get('port_side')} vs {s.get('answer_side')}: {describe(s)}. "
            f"Records {s['records_total']}, differ {s['records_differ']} (fields {s['fields_differ']}, "
            f"missing {s['missing']}, extra {s['extra']}), accepted {s.get('accepted', 0)}.")
    out = [head]
    rows = result["rows"]
    if rows:
        wk = max(8, *(len(r["key"]) for r in rows))
        wf = max(5, *(len(r["field"]) for r in rows))
        wv = max(10, *(len(str(r[c] or "")) for r in rows for c in ("answer", "port")))
        out.append("")
        out.append(f"{'file':<10}  {'key':<{wk}}  {'field':<{wf}}  {'answer key':>{wv}}  {'port':>{wv}}  "
                   f"{'delta':>10}")
        shown = rows if limit is None else rows[:limit]
        for r in shown:
            delta = r["delta"] if r["delta"] is not None else r["status"]
            out.append(f"{r['file']:<10}  {r['key']:<{wk}}  {r['field']:<{wf}}  {_r(r['answer'], wv)}  "
                       f"{_r(r['port'], wv)}  {delta:>10}" + _accepted_tag(r))
        if limit is not None and len(rows) > limit:
            out.append(f"... {len(rows) - limit} more differing fields in .tare/ledger.md")
    if s.get("accepted_entries"):
        out.append("")
    for e in s.get("accepted_entries", []):
        out.append(f"accepted: {e.get('file')} {e.get('key')} {_pins(e)}: {e.get('reason')} "
                   f"(accepted by {e.get('accepted_by')}, {e.get('date')}, tare.json)")
    if s.get("unsealed_entries"):
        out.append(f"note: {s['unsealed_entries']} accepted entr{'y' if s['unsealed_entries'] == 1 else 'ies'} "
                   "in tare.json not written by python -m tare accept (seal does not match); covering nothing")
    if s.get("port_notes"):
        out.append("")
        out.extend(f"port note: {n}" for n in s["port_notes"])
    return "\n".join(out)


def format_markdown(result: dict, meta: dict) -> str:
    s = result["summary"]
    out = [f"# Tare ledger: {s.get('port_side')} vs {s.get('answer_side')}", "",
           f"**{s['verdict'].upper()}.** {describe(s)}.", "",
           f"`{s['result_line']}`", "",
           *([f"- **{meta['recorded']}**"] if meta.get("recorded") else []),
           f"- Port: `{meta.get('port_path')}`",
           f"- Answer key: `{meta.get('answer_path')}`",
           f"- Weighed at {meta.get('weighed_at')} (UTC)", "",
           "| records | differ | fields differ | missing | extra | accepted |",
           "|---:|---:|---:|---:|---:|---:|",
           f"| {s['records_total']} | {s['records_differ']} | {s['fields_differ']} | {s['missing']} "
           f"| {s['extra']} | {s.get('accepted', 0)} |", ""]
    num = [(f, n, st) for f, stats in (s.get("numeric") or {}).items() for n, st in stats.items()]
    if num:
        out += ["| numeric field | higher | lower | net |", "|---|---:|---:|---:|"]
        out += [f"| {f}.{n} | {st['higher']} | {st['lower']} | {st['net']} |" for f, n, st in num]
        out.append("")
    if result["rows"]:
        out += ["## Differing fields", "", "| file | key | field | answer key | port | delta |",
                "|---|---|---|---:|---:|---:|"]
        for r in result["rows"]:
            delta = r["delta"] if r["delta"] is not None else r["status"]
            out.append(f"| {r['file']} | {r['key']} | {r['field']} | {r['answer'] or ''} | {r['port'] or ''} "
                       f"| {delta}" + _accepted_tag(r).lower().replace("  ", " ", 1) + " |")
        out.append("")
    if s.get("accepted_entries"):
        out += ["## Accepted differences (tare.json)", ""]
        out += [f"- {e.get('file')} {e.get('key')}, {_pins(e)}: {e.get('reason')} "
                f"Accepted by {e.get('accepted_by')} on {e.get('date')}." for e in s["accepted_entries"]]
        out.append("")
    if meta.get("sources"):
        out += ["## Port sources weighed", "", "| file | sha256 |", "|---|---|"]
        out += [f"| `{k}` | `{v}` |" for k, v in meta["sources"].items()]
        out.append("")
    return "\n".join(out)
