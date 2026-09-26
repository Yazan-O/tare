"""One weigh, as the CLI and the MCP server both run it: ledger + record files + scale image."""
import datetime
import json
from pathlib import Path

from . import config, ledger, localport, records, sides


def _write(path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="\n")


def _is_port_under_test(root: Path, port: str, port_path: Path) -> bool:
    if port == config.PORT_SIDE:
        return True
    canonical = (root / localport.OUT / config.RECORDS).resolve()
    if port_path.resolve() == canonical:
        return True
    try:
        return port_path.is_file() and records.load_side(port_path).get("side") == config.PORT_SIDE
    except (OSError, ValueError):
        return False


def run(root: Path, port: str, answer=None, render=True) -> dict:
    """Weigh `port` (a side name or a path to records.json) against the answer key.

    Writes .tare/weigh_<side>.json (the record the gate reads), .tare/last_weigh.json (a copy of the
    most recent record, for display), .tare/ledger.md and .tare/scale.png. Returns the record.
    A declared side with no work/runs/<side>/records.json is weighed from its committed fixture. Any weigh
    of a committed fixture carries the label in the record's 'recorded' field.

    The port under test ('local') never falls back, is always weighed by name against the pinned answer
    key, and is rerun first (tare/localport.py) when its last run's provenance is missing or stale, so
    the record always describes the current sources. The record stores that provenance for the gate.
    """
    cfg = config.load_config(root)
    port_path = config.resolve_port_path(root, port)
    run_log = None
    provenance = None
    under_test = _is_port_under_test(root, port, port_path)
    if under_test:
        if port != config.PORT_SIDE:
            raise ValueError("weigh the port under test by its side name: --port local")
        if answer and config.answer_key_path(root, answer).resolve() != (root / config.ANSWER_KEY).resolve():
            raise ValueError(f"the port under test is weighed against {config.ANSWER_KEY} only")
        why = localport.staleness(root)
        if why:
            try:
                port_path, run_log = localport.run(root)
            except localport.PortRunError as e:
                raise ValueError(f"{why}; ran the port first and the run failed:\n{e}") from None
            run_log = f"{why}; ran the port first.\n{run_log}"
        provenance = localport.read_provenance(root)
    if port in sides.declared(root) and not port_path.is_file() and sides.fixture_path(root, port).is_file():
        port_path = sides.fixture_path(root, port)
    fixtures = (root / "fixtures" / "sides").resolve()
    recorded = sides.recorded_label(port_path) if port_path.resolve().parent.parent == fixtures else None
    a_path = root / config.ANSWER_KEY if under_test else config.answer_key_path(root, answer)
    a_json = records.load_side(a_path)
    port_json = records.load_side(port_path)
    accepted = cfg.get("accepted", [])
    result = ledger.weigh(a_json, port_json, cfg, accepted)
    side = port if config.SIDE_RE.match(port) and not port.lower().endswith(".json") \
        else str(port_json.get("side") or "unknown")
    if not config.SIDE_RE.match(side):
        side = "unknown"
    patterns = sides.source_patterns(root, side)
    record = {
        "side": side,
        "summary": result["summary"],
        "describe": ledger.describe(result["summary"]),
        "recorded": recorded,
        "port_path": str(port_path),
        "port_sha256": config.sha256_file(port_path),
        "provenance": provenance,
        "answer_path": str(a_path),
        "answer_sha256": config.sha256_file(a_path),
        "accepted_sha256": config.accepted_sha256(accepted),
        "protected": config.hash_protected(root),
        "source_patterns": patterns,
        "sources": config.hash_sources(root, patterns),
        "weighed_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": result["rows"],
    }
    sd = config.state_dir(root)
    body = json.dumps(record, indent=2) + "\n"
    _write(sd / f"weigh_{side}.json", body)
    _write(sd / "last_weigh.json", body)
    _write(sd / "ledger.md", ledger.format_markdown(result, record))
    if render:
        from . import scale
        scale.render(result["summary"], side, sd / "scale.png", program=cfg.get("program"))
        record["image_path"] = str(sd / "scale.png")
    record["_result"] = result
    record["_run_log"] = run_log
    return record
