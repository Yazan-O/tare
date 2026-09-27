import shutil
import sys
from pathlib import Path

from . import answerkey, config, ledger, localport, records, sides, weighing

FRESH = "work/answer_key"


def answer_key(root: Path, offline=False) -> tuple:
    committed = root / config.ANSWER_DIR
    if (committed / config.RECORDS).is_file():
        problems = answerkey.soundness(config.load_config(root), committed)
        if problems:
            return False, f"{answerkey.unsound_text(problems)} (committed fixture {config.ANSWER_DIR})", False
    if offline:
        return True, f"answer key: RECORDED, committed fixture {config.ANSWER_KEY} (--offline)", True
    missing = answerkey.tools_missing()
    if missing:
        return True, (f"answer key: {', '.join(missing)} not found; using the committed fixture "
                      f"{config.ANSWER_KEY} (RECORDED, produced by: python -m tare answer-key)"), True
    print("$ python -m tare answer-key --out work/answer_key", flush=True)
    try:
        answerkey.build(root, FRESH, say=lambda s: print(f"  {s}", flush=True))
    except answerkey.UnsoundAnswerKey as e:
        return False, f"{e} (fresh GnuCOBOL run)", False
    except (answerkey.AnswerKeyError, ValueError, OSError) as e:
        print(str(e), file=sys.stderr)
        return False, f"answer key: python -m tare answer-key failed ({type(e).__name__})", True
    diffs = answerkey.compare(committed, root / FRESH, config.load_config(root))
    if diffs:
        return False, "answer key: fresh GnuCOBOL run DIFFERS from the committed fixture: " + "; ".join(diffs), True
    return True, ("answer key: fresh GnuCOBOL run equals the committed fixture (records.json; input and output "
                  "files byte for byte)"), True


def run_side(root: Path, side: str, offline=False) -> dict:
    fixture = sides.fixture_path(root, side)
    if offline:
        return {"path": fixture, "source": "recorded", "note": "--offline"}
    missing = sides.missing_tools(root, side)
    if missing:
        print(f"  {side}: {', '.join(missing)} not found; weighing the committed fixture", flush=True)
        return {"path": fixture, "source": "recorded", "note": f"{', '.join(missing)} not found"}
    print(f"$ python -m tare run-port {side}", flush=True)
    try:
        out, _ = sides.run(root, side)
    except (localport.PortRunError, ValueError, OSError) as e:
        print(localport._tail(str(e)), file=sys.stderr)
        return {"path": None, "source": "error", "note": f"port run failed ({type(e).__name__})"}
    note = "fresh run"
    if fixture.is_file():
        same = records.load_side(fixture).get("files") == records.load_side(out).get("files")
        note += ", same records as the committed fixture" if same else ", DIFFERS from the committed fixture"
    print(f"  {side}: {note}", flush=True)
    return {"path": out, "source": "fresh", "note": note}


def weigh_side(root: Path, side: str, run: dict) -> dict:
    rec = weighing.run(root, str(run["path"]))
    sd = config.state_dir(root)
    if rec.get("image_path"):
        shutil.copyfile(rec["image_path"], sd / f"scale_{side}.png")
    return rec


def _header(rec: dict) -> str:
    head = ledger.format_table(rec["_result"]).splitlines()[0]
    return (f"[{rec['recorded']}] " if rec.get("recorded") else "") + head


def _net(s: dict) -> str:
    parts = [f"{n} {st['net']}" for stats in (s.get("numeric") or {}).values() for n, st in stats.items()
             if st["higher"] or st["lower"]]
    return ", ".join(parts) or "0"


def reproduce(root: Path, offline=False, record=False) -> int:
    cfg = config.load_config(root)
    declared = sides.declared(root)
    expected = cfg.get("expected") or {}
    unknown = [s for s in expected if s not in declared]
    bad = [v for v in expected.values() if v not in ("balanced", "red")]
    if unknown or bad or set(declared) - set(expected):
        print(f"tare.json 'expected' must map every declared side ({', '.join(declared) or 'none'}) to "
              f"'balanced' or 'red'; got {expected}", file=sys.stderr)
        return 2
    if not declared:
        print("tare.json declares no sides to weigh ('sides' and 'expected' are empty)", file=sys.stderr)
        print("reproduce: FAIL (no side declared; nothing was weighed)")
        return 1
    ok, status, sound = answer_key(root, offline)
    print(status, flush=True)
    if not sound:
        print("reproduce: FAIL (the answer key is unsound; no side was weighed against it)")
        return 1
    rows = []
    for side, want in expected.items():
        run = run_side(root, side, offline)
        if run["source"] == "recorded" and not Path(run["path"]).is_file():
            print(f"{side}: MISSING, no committed fixture at {config.rel_to(root, run['path'])} and no run "
                  f"({run['note']})", flush=True)
            rows.append((side, "missing", want, "", "", "no fixture"))
            continue
        if run["source"] == "error":
            print(f"{side}: port run FAILED ({run['note']})", flush=True)
            rows.append((side, "error", want, "", "", run["note"]))
            continue
        if record and run["source"] == "fresh":
            dst = sides.fixture_path(root, side)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(run["path"], dst)
            print(f"  {side}: recorded to {config.rel_to(root, dst)}", flush=True)
        rec = weigh_side(root, side, run)
        s = rec["summary"]
        print(_header(rec), flush=True)
        rows.append((side, s["verdict"], want, f"{s['records_differ']} of {s['records_total']}", _net(s),
                     "fresh" if run["source"] == "fresh" else "(recorded)"))
    print()
    print("Scoreboard (records: records differing from the answer key; net: port minus answer key)")
    cols = ("side", "verdict", "expected", "records", "net", "run")
    widths = [max(len(c), *(len(str(r[i])) for r in rows)) for i, c in enumerate(cols)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*cols))
    for r in rows:
        print(fmt.format(*r))
        print(f"    line: {sides.line(root, r[0])}")
    wrong = [r[0] for r in rows if r[1] != r[2]]
    print()
    print(status)
    if not ok or wrong:
        print(f"reproduce: FAIL ({'answer key' if not ok else ''}{', ' if not ok and wrong else ''}"
              f"{'unexpected verdict: ' + ', '.join(wrong) if wrong else ''})")
        return 1
    print(f"reproduce: OK, all {len(rows)} sides got their expected verdict")
    return 0


def check(root: Path, side: str, summary_path=None, offline=False) -> int:
    ok, status, sound = answer_key(root, offline)
    print(status, flush=True)
    run = run_side(root, side, offline) if sound else {"source": "skipped", "note": "answer key unsound"}
    md = [f"## Tare: {side}", ""]
    if not ok or run["source"] == "error":
        why = status if not ok else f"{side}: port run FAILED ({run['note']})"
        print(why)
        md += [f"**ERROR.** {why}", ""]
        _write_summary(summary_path, md)
        return 2
    rec = weigh_side(root, side, run)
    res, s = rec["_result"], rec["summary"]
    print(ledger.format_table(res, limit=60))
    print()
    print(s["result_line"])
    md += [f"**{_header(rec)}**", "",
           f"Port line: `{sides.line(root, side)}`", "",
           f"Run: {run['note']}. {status[0].upper() + status[1:]}.", ""]
    md += ledger.format_markdown(res, rec).splitlines()[2:]
    _write_summary(summary_path, md)
    return 0 if s["verdict"] == "balanced" else 1


def _write_summary(path, md):
    if not path:
        return
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md) + "\n")
    print(f"wrote the ledger to {path}")


def reset(root: Path) -> int:
    sd = root / ".tare"
    removed = []
    for name in ("weigh_local.json", "last_weigh.json"):
        p = sd / name
        if p.is_file():
            p.unlink()
            removed.append(f".tare/{name}")
    print("removed " + ", ".join(removed) if removed else "nothing to remove (.tare/weigh_local.json and "
          ".tare/last_weigh.json do not exist)")
    return 0


def fixture_states(root: Path) -> list:
    cfg = config.load_config(root)
    a = records.load_side(root / config.ANSWER_KEY)
    out = []
    for side in sides.declared(root):
        p = sides.fixture_path(root, side)
        if p.is_file():
            out.append((ledger.weigh(a, records.load_side(p), cfg, cfg.get("accepted", []))["summary"], side))
    return out
