import os
import subprocess
from pathlib import Path

from . import config

HOOKS = ("pre-commit", "pre-merge-commit", "pre-push", "pre-rebase", "pre-applypatch", "reference-transaction")
MARK = "# tare-gate: installed by python -m tare install-hooks"
SCRIPT = """#!/bin/sh
{mark}
{only_prepared}TARE_HOOK_REPO="$(git rev-parse --show-toplevel)"; export TARE_HOOK_REPO
cd "$TARE_HOOK_REPO{prefix}" || exit 1
TARE_ROOT="$(pwd)"; export TARE_ROOT
for py in python python3 py; do
  if command -v "$py" >/dev/null 2>&1; then exec "$py" {launch} gate --git-hook {name}; fi
done
echo "TARE: blocked. No python on PATH to run the commit gate ({name} hook)." >&2
exit 1
"""


def _git(root: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise ValueError(f"not a git repository: {root} ({r.stderr.strip()})")
    return r.stdout.strip()


def hooks_dir(root: Path) -> Path:
    p = Path(_git(root, "rev-parse", "--git-path", "hooks"))
    return p if p.is_absolute() else root / p


def _launch(root: Path) -> str:
    if (Path(root).resolve() / "tare" / "__main__.py").is_file():
        return "-m tare"
    main = (config.PACKAGE_DIR / "__main__.py").as_posix()
    if any(c in main for c in '"$`\\'):
        raise ValueError(f"cannot quote the path {main} in a hook script; move the repository")
    return f'"{main}"'


def install(root: Path, uninstall=False, repo=None) -> int:
    repo = Path(root) if repo is None else (Path(repo) if Path(repo).is_absolute() else Path(root) / repo)
    d = hooks_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    top = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    prefix = Path(os.path.relpath(Path(root).resolve(), top)).as_posix()
    prefix = "" if prefix == "." else prefix
    if any(c in prefix for c in '"$`\\'):
        raise ValueError(f"cannot quote the path {prefix} in a hook script")
    done = []
    for name in HOOKS:
        p = d / name
        ours = p.is_file() and MARK in p.read_text(encoding="utf-8", errors="replace")
        if uninstall:
            if ours:
                p.unlink()
                backup = d / f"{name}.pre-tare"
                if backup.is_file():
                    backup.rename(p)
                done.append(name)
            continue
        if p.is_file() and not ours:
            p.replace(d / f"{name}.pre-tare")
            print(f"moved your existing {name} hook to {name}.pre-tare")
        only = '[ "$1" = prepared ] || exit 0\n' if name == "reference-transaction" else ""
        p.write_text(SCRIPT.format(mark=MARK, name=name, only_prepared=only,
                                   prefix=f"/{prefix}" if prefix else "", launch=_launch(root)),
                     encoding="utf-8", newline="\n")
        os.chmod(p, 0o755)
        done.append(name)
    verb = "removed" if uninstall else "installed"
    print(f"{verb} git hooks in {d}: {', '.join(done) or 'none'}")
    if not uninstall:
        print("git commit, merge, cherry-pick, revert, am, rebase and push now refuse while the port is red.")
    return 0
