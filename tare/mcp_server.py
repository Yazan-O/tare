"""Tare MCP server over stdio: newline-delimited JSON-RPC 2.0, stdlib only. Logs go to stderr.

Tools: run_mainframe, run_port, weigh, explain.
"""
import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:  # run as a file path: python <repo>/tare/mcp_server.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tare.mcp_server import main
    sys.exit(main())

import base64
import json
import shlex
import traceback

from . import answerkey, config, ledger, localport, records, sides

SUPPORTED = ("2024-11-05", "2025-03-26", "2025-06-18")
SERVER_INFO = {"name": "tare", "version": "0.2.0"}
TEXT_ROWS = 60


def known_sides(root: Path) -> list:
    return [config.PORT_SIDE, *sides.declared(root)]


def side_schema(root: Path) -> dict:
    names = known_sides(root)
    others = [n for n in names if n != config.PORT_SIDE]
    return {"type": "string", "enum": names,
            "description": "Which port. 'local' is the port under test in this repository (port/, built and run "
                           "in a sandbox). " + (f"Declared public ports: {', '.join(others)}. " if others else "")
                           + "Example: \"local\"."}


def tools(root: Path) -> list:
    side = side_schema(root)
    return [
        {"name": "run_mainframe",
         "description": "Runs the original COBOL job described in tare.json under GnuCOBOL (python -m tare "
                        "answer-key --out work/runs/mainframe) to produce the answer key: the records the original "
                        "program wrote, decoded with the layouts in tare.json. Use it once at the start to see what "
                        "the port must reproduce. If the COBOL toolchain is not installed, it says so and returns "
                        "the summary of the committed answer key fixtures/answer_key/records.json instead, "
                        "labelled as the committed fixture. Takes no arguments.",
         "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "run_port",
         "description": "Builds and runs one port on the same input the original read, writing "
                        "work/runs/<side>/records.json. For side 'local' it compiles every .java under port/ and "
                        "runs the class in port/MAIN with its working directory in work/sandbox/local/, which holds "
                        "only copies of the input files and the compiled classes; the port writes each output file "
                        "in the original's fixed-width format and Tare decodes it. Returns the build/run output "
                        "tail and how many records the port wrote. Run it after every change to the port, then call "
                        "weigh with the same side. For a declared public port whose toolchain is missing, it says so "
                        "and copies the committed fixture fixtures/sides/<side>/records.json instead, labelled "
                        "RECORDED OUTPUT.",
         "inputSchema": {"type": "object", "properties": {"side": side}, "required": ["side"],
                         "additionalProperties": False}},
        {"name": "weigh",
         "description": "Compares a port's records (work/runs/<side>/records.json) with the answer key's, record by "
                        "record (matched by key) and field by field, numbers in decimal arithmetic. Returns the "
                        "ledger (verdict, counts, per numeric field higher/lower/net, and every differing field with "
                        "the answer key's value, the port's value and the delta, up to 60 rows) and a PNG image of "
                        "the balance scale. Balanced means every field of every record matches and nothing is "
                        "missing or extra; anything else is red. Also records the weigh in .tare/ (the commit gate "
                        "reads .tare/weigh_local.json). For side 'local' it reruns the port first when the sources "
                        "changed since its last run. A declared public port with no run output is weighed from its "
                        "committed fixture, labelled RECORDED OUTPUT.",
         "inputSchema": {"type": "object", "properties": {"side": side}, "required": ["side"],
                         "additionalProperties": False}},
        {"name": "explain",
         "description": "Explains one field of one record from the evidence up: the answer key's and the port's "
                        "values, the COBOL statements that write the field or a group holding it (file:line, read "
                        "from the program sources), the field's PIC and USAGE from the program or copybook, and for "
                        "a numeric difference the exact arithmetic of the COMPUTE when its operands are in the "
                        "record, truncated and rounded half-up, with IBM's documented rule and its URL. Call it on "
                        "the first differing field of a red weigh before changing the port.",
         "inputSchema": {"type": "object", "properties": {
             "file": {"type": "string", "maxLength": 40,
                      "description": "Output file name from tare.json. Optional; defaults to the first output file."},
             "key": {"type": "string", "maxLength": 200,
                     "description": "Record key as the ledger shows it (several key fields joined with '|'). "
                                    "Optional; defaults to the first differing record."},
             "field": {"type": "string", "maxLength": 60,
                       "description": "Field name from the layout. Optional; defaults to the first differing field."},
             "side": dict(side, description=side["description"] + " Optional; defaults to 'local'.")},
             "additionalProperties": False}},
    ]


def log(*a):
    print("[tare-mcp]", *a, file=sys.stderr, flush=True)


def _text(s):
    return {"type": "text", "text": s}


def _tail(s: str, n=40) -> str:
    lines = (s or "").strip().splitlines()
    return "\n".join(lines[-n:])


def _bad_side(root: Path, side):
    """An error message when `side` is not one of the known sides (never a path), else None."""
    names = known_sides(root)
    if isinstance(side, str) and side in names:
        return None
    return f"invalid side {str(side)[:40]!r}: expected one of {', '.join(names)}"


def _side_summary(path: Path, label: str) -> str:
    d = records.load_side(path)
    counts = ", ".join(f"{n} {len(v)} records" for n, v in d["files"].items()) or "no files"
    return f"{label}: {path}\n  side {d.get('side')}, {counts}\n  produced by: {d.get('command')}"


def tool_run_mainframe(root: Path, args: dict):
    fixture = root / config.ANSWER_KEY
    out = []
    missing = answerkey.tools_missing()
    if not missing:
        lines = []
        try:
            answerkey.build(root, "work/runs/mainframe", say=lines.append)
        except (answerkey.AnswerKeyError, ValueError, OSError) as e:
            out.append(f"$ python -m tare answer-key --out work/runs/mainframe  (failed)\n{_tail(str(e), 20)}")
        else:
            out.append("$ python -m tare answer-key --out work/runs/mainframe  (exit 0)\n" + "\n".join(lines))
            out.append(_side_summary(root / "work" / "runs" / "mainframe" / config.RECORDS, "Fresh run of the original"))
            if fixture.is_file():
                out.append(_side_summary(fixture, "Answer key used by weigh"))
            return [_text("\n\n".join(out))], False
    else:
        out.append(f"The COBOL toolchain ({', '.join(missing)}) is not on PATH.")
    if fixture.is_file():
        out.append(_side_summary(fixture, "COMMITTED FIXTURE (not a fresh run)"))
        return [_text("\n\n".join(out))], False
    out.append(f"No committed answer key at {fixture} either.")
    return [_text("\n\n".join(out))], True


def tool_run_port(root: Path, args: dict):
    side = args.get("side", "")
    if _bad_side(root, side):
        return [_text(_bad_side(root, side))], True
    if side == config.PORT_SIDE:
        out = root / localport.OUT / config.RECORDS
        try:
            _, text = localport.run(root)
        except localport.PortRunError as e:
            return [_text(f"run_port local failed:\n{e}")], True
        return [_text("\n".join([text, _side_summary(out, "Port output"), "Next: weigh with side 'local'."]))], False
    missing = sides.missing_tools(root, side)
    if missing:
        head = f"{side}: not run, {', '.join(missing)} not found on this machine."
        try:
            copy = sides.use_fixture(root, side)
        except FileNotFoundError as e:
            return [_text(f"{head} {e}")], True
        return [_text("\n".join([
            head, sides.recorded_label(copy),
            f"Copied fixtures/sides/{side}/records.json to work/runs/{side}/records.json.",
            _side_summary(copy, "RECORDED OUTPUT"), f"Next: weigh with side {side!r}."]))], False
    try:
        path, text = sides.run(root, side)
    except localport.PortRunError as e:
        return [_text(f"run_port {side} failed:\n{_tail(str(e))}")], True
    return [_text("\n".join([f"$ python -m tare run-port {shlex.quote(side)}", _tail(text),
                             _side_summary(path, "Port output"), f"Next: weigh with side {side!r}."]))], False


def tool_weigh(root: Path, args: dict):
    side = args.get("side", "")
    if _bad_side(root, side):
        return [_text(_bad_side(root, side))], True
    from . import weighing
    rec = weighing.run(root, side)
    text = ledger.format_table(rec["_result"], limit=TEXT_ROWS)
    if rec.get("_run_log"):
        text = rec["_run_log"] + "\n\n" + text
    if rec.get("recorded"):
        text = f"{rec['recorded']}; work/runs/{side}/records.json does not exist.\n\n" + text
    text += f"\n\n{rec['summary']['result_line']}\nRecorded in .tare/weigh_{side}.json; full ledger in .tare/ledger.md."
    png = Path(rec["image_path"]).read_bytes()
    return [_text(text), {"type": "image", "data": base64.b64encode(png).decode("ascii"),
                          "mimeType": "image/png"}], False


def tool_explain(root: Path, args: dict):
    from . import explain
    side = args.get("side", config.PORT_SIDE)
    if _bad_side(root, side):
        return [_text(_bad_side(root, side))], True
    for k, n in (("file", 40), ("key", 200), ("field", 60)):
        v = args.get(k)
        if v is not None and (not isinstance(v, str) or not 0 < len(v) <= n):
            return [_text(f"{k} must be a string of 1 to {n} characters, got {str(v)[:20]!r}")], True
    try:
        text = explain.explain(root, args.get("file"), args.get("key"), args.get("field"), side)
    except ValueError as e:
        return [_text(str(e)[:300])], True
    return [_text(text)], False


HANDLERS = {"run_mainframe": tool_run_mainframe, "run_port": tool_run_port,
            "weigh": tool_weigh, "explain": tool_explain}


def handle(msg: dict, root: Path):
    """Returns a response dict, or None for a notification."""
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    is_note = "id" not in msg

    def ok(result):
        return None if is_note else {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, text):
        return None if is_note else {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok({"protocolVersion": asked if asked in SUPPORTED else SUPPORTED[-1],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": SERVER_INFO,
                   "instructions": "Tare weighs a port of a COBOL batch program against the original program's own "
                                   "output (the answer key). Order: run_mainframe once, then run_port and weigh "
                                   "after each change; explain the first differing field of a red weigh."})
    if method in ("notifications/initialized", "initialized") or (method or "").startswith("notifications/"):
        return None
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tools(root)})
    if method == "tools/call":
        name = params.get("name")
        fn = HANDLERS.get(name)
        if fn is None:
            return err(-32602, f"unknown tool: {name}")
        try:
            content, is_error = fn(root, params.get("arguments") or {})
        except Exception as e:
            log(traceback.format_exc())
            content, is_error = [_text(f"{name} failed: {type(e).__name__}: {str(e)[:300]}")], True
        return ok({"content": content, "isError": is_error})
    return err(-32601, f"method not found: {method}")


def _invalid(why):
    return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": f"invalid request: {why}"}}


def _safe_handle(msg, root: Path):
    """handle() for one message; a non-object gets -32600 and an exception -32603, never a crash."""
    if not isinstance(msg, dict):
        return _invalid(f"expected a JSON object, got {type(msg).__name__}")
    try:
        return handle(msg, root)
    except Exception as e:
        log(traceback.format_exc())
        return {"jsonrpc": "2.0", "id": msg.get("id"),
                "error": {"code": -32603, "message": f"{type(e).__name__}: {str(e)[:200]}"}}


def main():
    root = config.repo_root()
    log("root", root, "" if (root / "tare.json").is_file() else "(no tare.json: set TARE_ROOT to a case folder)")
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    for raw in inp:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError as e:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {e}"}}
        else:
            if isinstance(msg, list):
                resp = ([r for r in (_safe_handle(m, root) for m in msg) if r is not None] or None) if msg \
                    else _invalid("empty batch")
            else:
                resp = _safe_handle(msg, root)
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False).encode("utf-8") + b"\n")
            out.flush()


if __name__ == "__main__":
    main()
