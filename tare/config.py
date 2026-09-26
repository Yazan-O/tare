"""Case root, tare.json, and source hashing shared by the CLI, the gate and the MCP server.

A case is a folder holding tare.json: the COBOL program (mainframe/), its answer key (fixtures/answer_key/),
the port under test (port/) and optionally public ports (sides). tare.json describes the files, the job
steps and the record layouts; see README.md.
"""
import glob
import hashlib
import json
import os
import re
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ANSWER_DIR = "fixtures/answer_key"
ANSWER_KEY = ANSWER_DIR + "/records.json"
INPUT = ANSWER_DIR + "/input"
RECORDS = "records.json"
SIDE_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
# The gate's own policy, fixed in code so an edit to tare.json cannot change it: the side under test is
# always 'local', its sources are these globs, and it is weighed against ANSWER_KEY.
PORT_SIDE = "local"
PORT_SOURCES = ("port/**/*.java", "port/MAIN")
# Paths the gate requires to equal git HEAD (working tree and index) before a commit or push: the policy,
# the answer key and every recorded output (fixtures/), the COBOL, Tare itself and the Bob configuration.
# tare/ and .bob/ are taken from the case root when present there, else from the Tare package and the
# nearest .bob/ above the case root.
PROTECTED = ("tare.json", "fixtures", "mainframe", "tare", ".bob")


def repo_root() -> Path:
    """TARE_ROOT, else the nearest folder at or above cwd holding tare.json, else the package's parent."""
    env = os.environ.get("TARE_ROOT")
    if env:
        return Path(env).resolve()
    cwd = Path.cwd().resolve()
    for d in (cwd, *cwd.parents):
        if (d / "tare.json").is_file():
            return d
    return PACKAGE_DIR.parent


def load_config(root: Path) -> dict:
    p = root / "tare.json"
    if not p.is_file():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def state_dir(root: Path) -> Path:
    d = root / ".tare"
    d.mkdir(exist_ok=True)
    return d


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def hash_sources(root: Path, patterns) -> dict:
    """{relative posix path: sha256} for every file matching the glob patterns, relative to root."""
    out = {}
    for pat in patterns or []:
        for p in glob.glob(str(root / pat), recursive=True):
            pp = Path(p)
            if pp.is_file():
                out[pp.resolve().relative_to(root.resolve()).as_posix()] = sha256_file(pp)
    return dict(sorted(out.items()))


def _nearest_bob(root: Path):
    for d in (root, *root.parents):
        if (d / ".bob").is_dir():
            return d / ".bob"
    return None


def protected_paths(root: Path) -> list:
    """Absolute paths of everything under PROTECTED for this case root."""
    root = Path(root).resolve()
    out = []
    for rel in PROTECTED:
        p = root / rel
        if rel == "tare" and not p.is_dir():
            p = PACKAGE_DIR
        elif rel == ".bob" and not p.is_dir():
            p = _nearest_bob(root) or p
        out.append(p)
    return out


def rel_to(root: Path, p: Path) -> str:
    """p relative to root (with ../ when outside it), or p's absolute path when on another drive."""
    try:
        return Path(os.path.relpath(p, root)).as_posix()
    except ValueError:
        return Path(p).resolve().as_posix()


def hash_protected(root: Path) -> dict:
    """{path relative to root: sha256} for every file under the protected paths (no __pycache__ or .pyc)."""
    out = {}
    for p in protected_paths(root):
        files = [p] if p.is_file() else (sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [])
        for f in files:
            if "__pycache__" in f.parts or f.suffix == ".pyc":
                continue
            out[rel_to(root, f)] = sha256_file(f)
    return dict(sorted(out.items()))


def accepted_sha256(accepted) -> str:
    return sha256_json(accepted or [])


def outputs(cfg: dict) -> list:
    """Names of the files the weigh compares, in tare.json order."""
    return [n for n, f in (cfg.get("files") or {}).items() if f.get("output")]


def inputs(cfg: dict) -> list:
    """Names of the files the port reads (those with initial content), in tare.json order."""
    return [n for n, f in (cfg.get("files") or {}).items() if f.get("from")]


def layout_for(cfg: dict, file: str) -> dict:
    f = (cfg.get("files") or {}).get(file)
    if f is None:
        raise ValueError(f"tare.json has no file {file!r}")
    name = f.get("layout")
    lay = (cfg.get("layouts") or {}).get(name)
    if lay is None:
        raise ValueError(f"tare.json: file {file!r} names layout {name!r}, which is not in 'layouts'")
    return lay


def sides(cfg: dict) -> dict:
    """Public ports declared in tare.json: {name: {runner, repo, commit, licence, line}}."""
    return {k: v for k, v in (cfg.get("sides") or {}).items() if SIDE_RE.match(k) and k != PORT_SIDE}


def resolve_port_path(root: Path, port: str) -> Path:
    """A path to a records.json, or a side name resolved to work/runs/<side>/records.json."""
    p = Path(port)
    if p.suffix.lower() == ".json" or p.is_file():
        return p if p.is_absolute() else (Path.cwd() / p)
    if not SIDE_RE.match(port):
        raise ValueError(f"not a side name or a json path: {port!r}")
    return root / "work" / "runs" / port / RECORDS


def answer_key_path(root: Path, override=None) -> Path:
    if override:
        p = Path(override)
        return p if p.is_absolute() else (Path.cwd() / p)
    return root / ANSWER_KEY
