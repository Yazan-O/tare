"""python -m tare install-hooks: git's own hooks apply the gate's rule to every git client.

The Bob hook sees only the command text of a tool call; git's hooks see every commit, whatever made it
(an alias, a script, a subprocess, another editor). Each hook is a portable sh script that goes to the case
root, sets TARE_ROOT to it and runs the gate (`python -m tare gate --git-hook <name>`, or the package's
__main__.py by path when the case root does not hold tare/); a non-zero exit aborts the git command.
git runs no pre-commit hook for cherry-pick or revert, so reference-transaction (git 2.28+) vetoes any
update that moves a branch (refs/heads/*) forward to new commits while the port is red; fetch, stash, a
new branch and a reset to an older commit are not affected. Git's --no-verify skips pre-commit and pre-push
by design: that is deliberate tampering, left to CI.

The port under test may be a git repository of its own inside the case (port/, a clone of a published
port): `install-hooks --repo port` installs the same hooks there, so a commit made in that clone (cwd port/,
or git -C port commit) is gated by the case's weigh, and the case's protected paths are still checked
against the repository that holds the case.
"""
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
    """Install the hooks in the git repository holding the case root, or in `repo` (a working tree at or
    below the case root, such as port/) with the hooks going back up to the case root."""
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
