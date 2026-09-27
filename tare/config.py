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
PORT_SIDE = "local"
PORT_SOURCES = ("port/**/*.java", "port/MAIN")
PROTECTED = ("tare.json", "fixtures", "mainframe", "sides", "tare", ".bob")
DEFAULT_CASE = "cases/taxe_fonciere"


def case_root(start: Path):
    start = Path(start).resolve()
    for d in (start, *start.parents):
        if (d / "tare.json").is_file():
            return d
    top = PACKAGE_DIR.parent
    if (start == top or top in start.parents) and (top / DEFAULT_CASE / "tare.json").is_file():
        return top / DEFAULT_CASE
    return None


def repo_root() -> Path:
    env = os.environ.get("TARE_ROOT")
    if env:
        return Path(env).resolve()
    hit = case_root(Path.cwd())
    if hit is not None:
        return hit
    default = PACKAGE_DIR.parent / DEFAULT_CASE
    return default if (default / "tare.json").is_file() else PACKAGE_DIR.parent


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
    try:
        return Path(os.path.relpath(p, root)).as_posix()
    except ValueError:
        return Path(p).resolve().as_posix()


def hash_protected(root: Path) -> dict:
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
    return [n for n, f in (cfg.get("files") or {}).items() if f.get("output")]


def inputs(cfg: dict) -> list:
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
    return {k: v for k, v in (cfg.get("sides") or {}).items() if SIDE_RE.match(k) and k != PORT_SIDE}


GATE_NEVER = ("tare.json", "tare", ".bob", "fixtures", "mainframe", ".tare", "work", "cache")


def gate_spec(cfg: dict):
    g = cfg.get("gate")
    if g is None:
        return None
    side = g.get("side") if isinstance(g, dict) else None
    srcs = g.get("sources") if isinstance(g, dict) else None
    if not (isinstance(side, str) and SIDE_RE.match(side) and side != PORT_SIDE and side in sides(cfg)):
        raise ValueError(f"tare.json 'gate': side {side!r} is not a declared side other than {PORT_SIDE!r}")
    if not (isinstance(srcs, list) and srcs and all(isinstance(s, str) and s for s in srcs)):
        raise ValueError("tare.json 'gate': sources must be a non-empty list of globs")
    for s in srcs:
        parts = s.split("/")
        if s.startswith("/") or ":" in s or "\\" in s or ".." in parts or parts[0] in GATE_NEVER:
            raise ValueError(f"tare.json 'gate': source {s!r} must be a relative path outside {', '.join(GATE_NEVER)}")
    return {"side": side, "sources": tuple(srcs)}


def glob_regex(pattern: str):
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def local_entry(cfg: dict) -> dict:
    e = (cfg.get("sides") or {}).get(PORT_SIDE)
    return e if isinstance(e, dict) else {}


def resolve_port_path(root: Path, port: str) -> Path:
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
