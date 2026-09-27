import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = HERE / "ai_port_fixes.json"
PORT = HERE.parent / "cache" / "repos" / "rcaran"


class FixError(RuntimeError):
    pass


def load(spec: Path = SPEC) -> dict:
    return json.loads(spec.read_text(encoding="utf-8"))


def files(spec: dict) -> list:
    return sorted({e["file"] for e in spec["edits"]})


def line_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lines(path: Path) -> list:
    out = []
    for raw in path.read_bytes().decode("utf-8").splitlines(keepends=True):
        text = raw.rstrip("\r\n")
        out.append((text, raw[len(text):]))
    return out


def check(root: Path, spec: dict) -> list:
    bad = []
    for rel in files(spec):
        p = root / rel
        if not p.is_file():
            bad.append(f"{rel}: not found under {root}")
            continue
        lines = _lines(p)
        for e in (e for e in spec["edits"] if e["file"] == rel):
            n = e["line"]
            if n > len(lines):
                bad.append(f"{rel}:{n}: the file has {len(lines)} lines")
            elif line_sha(lines[n - 1][0]) != e["sha256"]:
                bad.append(f"{rel}:{n}: sha256 {line_sha(lines[n - 1][0])[:12]}, expected {e['sha256'][:12]}")
            elif e["action"] == "replace" and lines[n - 1][0].count(e["old"]) != 1:
                bad.append(f"{rel}:{n}: {e['old']!r} does not occur exactly once")
    return bad


def apply(root: Path, spec: dict) -> list:
    bad = check(root, spec)
    if bad:
        raise FixError(f"{SPEC.name} does not match the port at {root} (expected commit {spec['commit'][:7]}):\n  "
                       + "\n  ".join(bad))
    for rel in files(spec):
        p = root / rel
        lines = _lines(p)
        for e in sorted((e for e in spec["edits"] if e["file"] == rel), key=lambda e: -e["line"]):
            i = e["line"] - 1
            if e["action"] == "delete":
                del lines[i]
            elif e["action"] == "replace":
                text, end = lines[i]
                lines[i] = (text.replace(e["old"], e["new"]), end)
            else:
                raise FixError(f"{rel}:{e['line']}: unknown action {e['action']!r}")
        p.write_bytes("".join(t + end for t, end in lines).encode("utf-8"))
    return files(spec)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Apply sides/ai_port_fixes.json to a copy of the AI port, each edit checked by SHA-256.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", metavar="ROOT", type=Path)
    a = ap.parse_args(argv)
    spec = load()
    if a.check:
        if not PORT.is_dir():
            print(f"the AI port is not in {PORT}; run: python fetch.py", file=sys.stderr)
            return 2
        bad = check(PORT, spec)
        for b in bad:
            print(b, file=sys.stderr)
        print(f"{len(spec['edits']) - len(bad)} of {len(spec['edits'])} expected lines match in {PORT}")
        return 1 if bad else 0
    try:
        print("edited " + ", ".join(apply(a.apply, spec)))
    except FixError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
