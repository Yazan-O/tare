"""Public ports ('sides') declared in tare.json: how to run each one and its committed fixture.

A side is {runner, repo, commit, licence, line}. runner is either 'java:<dir>' (a Java port under <dir>,
built and run in its own sandbox exactly as the port under test is) or a command such as
'python ports/<name>/run.py', run from the case root with --input <input dir> --out work/runs/<side>; the
command writes <out>/<file>.dat for every output file (or <out>/records.json). line is 'file:line  source'
of the port's statement that decides its result. The committed fixture of a side is
fixtures/sides/<side>/records.json (recorded output, labelled RECORDED wherever it is used).
"""
import json
import shlex
import shutil
from pathlib import Path

from . import config, localport


def declared(root: Path) -> dict:
    return config.sides(config.load_config(root))


def entry(root: Path, side: str) -> dict:
    d = declared(root)
    if side not in d:
        raise ValueError(f"no side {side!r} in tare.json 'sides' (declared: {', '.join(d) or 'none'})")
    return d[side]


def _java_dir(e: dict):
    r = str(e.get("runner") or "")
    return r[len("java:"):].strip() if r.startswith("java:") else None


def missing_tools(root: Path, side: str) -> list:
    """Tools the side's runner needs that are not on this machine (empty list: it can run)."""
    e = entry(root, side)
    if _java_dir(e) is not None:
        return [] if localport.find_jdk() else ["JDK >= 17"]
    argv = shlex.split(str(e.get("runner") or ""))
    if not argv:
        return ["runner"]
    if Path(argv[0]).name.lower().startswith("python"):
        return []
    return [] if shutil.which(argv[0]) else [argv[0]]


def run_path(root: Path, side: str) -> Path:
    return root / "work" / "runs" / side / config.RECORDS


def fixture_path(root: Path, side: str) -> Path:
    return root / "fixtures" / "sides" / side / config.RECORDS


def recorded_label(path: Path) -> str:
    """The label every recorded (not freshly run) output carries."""
    with open(path, encoding="utf-8") as f:
        command = json.load(f).get("command")
    return f"RECORDED OUTPUT (committed fixture, produced by: {command})"


def use_fixture(root: Path, side: str) -> Path:
    """Copy the committed fixture to work/runs/<side>/records.json and return the copy's path."""
    src, dst = fixture_path(root, side), run_path(root, side)
    if not src.is_file():
        raise FileNotFoundError(f"no committed fixture for {side} at {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def source_patterns(root: Path, side: str) -> list:
    if side == config.PORT_SIDE:
        return list(config.PORT_SOURCES)
    try:
        g = config.gate_spec(config.load_config(root))
    except ValueError:
        g = None
    if g and g["side"] == side:
        return list(g["sources"])
    d = _java_dir(declared(root).get(side, {}))
    return [f"{d}/**/*.java", f"{d}/MAIN"] if d else []


def run(root: Path, side: str):
    """Run one side on the answer key's input. Returns (records.json path, log). Raises PortRunError."""
    e = entry(root, side)
    out_rel = f"work/runs/{side}"
    command = f"python -m tare run-port {side}"
    d = _java_dir(e)
    if d is not None:
        path, log, _, _ = localport.build_and_run(root, d, f"work/sandbox/{side}", out_rel, side, command)
        return path, log
    return localport.run_command(root, e["runner"], side, out_rel)


def line(root: Path, side: str) -> str:
    """'file:line  source text' of the side's deciding statement, from tare.json."""
    cfg = config.load_config(root)
    e = config.local_entry(cfg) if side == config.PORT_SIDE else config.sides(cfg).get(side) or {}
    return str(e.get("line") or "(no line declared in tare.json)")
