"""Tare's commit gate: no commit or push while the port under test is not balanced.

Two entry points apply the same rule (verdict()):
- the Bob PreToolUse hook (.bob/settings.json): reads the hook payload from stdin; exit 0 allows the tool
  call, exit 2 blocks it (Bob's contract). Any internal error blocks (exit 2): it never fails open.
- git's own hooks (python -m tare install-hooks): pre-commit, pre-merge-commit, pre-push, pre-rebase,
  pre-applypatch and reference-transaction run `python -m tare gate --git-hook <name>`; exit 1 aborts the
  git command. They cover every route to a commit the command matcher cannot see: aliases, scripts,
  subprocesses, other clients, and cherry-pick and revert (which run no pre-commit hook).

Threat model: the gate stops an agent's honest mistakes and casual workarounds inside Bob (stale output,
a relaxed tare.json, an edited answer key, `Git commit`, `git merge`, a python one-liner). The CI check on a
clean runner is the backstop against deliberate tampering (forging .tare/ records or provenance, a port
that opens the answer key by absolute path, `git commit --no-verify`, TARE_MAINTAINER=1 in a script).

Policy fixed in code, not read from tare.json: the side under test is 'local', its sources are
port/**/*.java and port/MAIN, and its answer key is fixtures/answer_key/records.json. tare.json, fixtures/,
mainframe/, sides/, tare/ and .bob/ must equal git HEAD (working tree and index); tare/ and .bob/ are the case
root's, else the Tare package and the nearest .bob/ above the case root. The one allowed difference is
tare.json's 'accepted' list when `python -m tare accept` wrote it (sealed in .tare/accept_seal.json).

Completion (attempt_completion) is allowed even while red, with a notice on stdout and stderr: blocking it
can trap Bob in a task it cannot finish, and the commit gate already keeps a red port out of history.
"""
import datetime
import json
import os
import re
import shlex
import sys
from pathlib import Path

LOG_KEEP = 500
TOOL_KEYS = ("tool", "tool_name", "toolName", "name")
INPUT_KEYS = ("input", "tool_input", "toolInput", "params", "arguments")
GIT_GLOBAL_OPTS_WITH_ARG = {"-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                            "--super-prefix", "--config-env"}  # lowercased: -C and -c both take one
SEPARATORS = re.compile(r"&&|\|\||;|\||\n|&")
# git subcommands that make a commit or move history onto a remote: always gated.
# Not gated, by decision: stash (its commits live in refs/stash, never on a branch), reset, checkout,
# switch, branch and tag (they point at commits that already exist), notes (refs/notes only).
GATED_SUB = {"commit", "commit-tree", "push", "merge", "pull", "cherry-pick", "revert", "am", "rebase",
             "update-ref", "filter-branch", "send-pack", "replace", "fast-import", "citool", "gui"}
# git subcommands known not to commit. Anything else (an alias such as `git ci`, a plugin) is gated.
SAFE_SUB = {"status", "log", "diff", "show", "add", "rm", "mv", "restore", "checkout", "switch", "branch",
            "fetch", "init", "clone", "config", "ls-files", "ls-tree", "rev-parse", "blame", "grep", "remote",
            "tag", "stash", "reset", "clean", "describe", "shortlog", "reflog", "help", "version", "cat-file",
            "hash-object", "count-objects", "fsck", "gc", "worktree", "submodule", "sparse-checkout", "notes",
            "bisect", "apply", "format-patch", "archive", "bundle", "var", "check-ignore", "check-attr",
            "difftool", "mergetool", "range-diff", "whatchanged", "show-ref", "symbolic-ref", "for-each-ref",
            "name-rev", "merge-base", "write-tree", "read-tree", "update-index", "diff-files", "diff-index",
            "diff-tree", "rev-list", "ls-remote", "credential", "lfs", "maintenance", "prune", "repack",
            "verify-commit", "verify-tag", "show-branch", "annotate", "cherry", "request-pull", "column",
            "--version", "--help"}
# interpreters whose inline code (-c, -e, /c, -Command ...) may run git: gated when the command names git
INTERPRETERS = {"python", "python3", "py", "pythonw", "node", "nodejs", "deno", "bun", "perl", "ruby", "php",
                "bash", "sh", "zsh", "dash", "ksh", "fish", "pwsh", "powershell", "cmd", "wsl", "busybox"}
INLINE_FLAG = re.compile(r"^(-[a-z]*[ce]|--eval|--print|-p|-command|-encodedcommand|/[ck]|-r)$")
FALLBACK = re.compile(r"\bgit(\.exe)?\b(\s+-{1,2}\S+(\s+\S+)?)*\s+(commit|commit-tree|push|merge|pull|cherry-pick|"
                      r"revert|am|rebase|update-ref)(?![\w-])")
MCP_GIT_TOOL = re.compile(r"commit|push|merge|create_or_update_file|delete_file")
BLOCKED = "TARE: blocked. "


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def tool_name(payload) -> str:
    if isinstance(payload, dict):
        for k in TOOL_KEYS:
            if isinstance(payload.get(k), str):
                return payload[k]
    return ""


def _as_command(v):
    if isinstance(v, str):
        return v
    if isinstance(v, list) and v and all(isinstance(x, str) for x in v):  # list form: ["git", "commit", ...]
        return " ".join(shlex.quote(x) for x in v)
    return None


def command_strings(payload) -> list:
    """input.command (Bob's documented shape, a string or an argv list), else tool_input.command, else every
    string in the payload."""
    if isinstance(payload, dict):
        for k in INPUT_KEYS:
            v = payload.get(k)
            if isinstance(v, dict) and _as_command(v.get("command")) is not None:
                return [_as_command(v["command"])]
        if _as_command(payload.get("command")) is not None:
            return [_as_command(payload["command"])]
        name = tool_name(payload).lower()
        if name and not re.search(r"command|exec|shell|bash|terminal|run", name):
            return []  # e.g. write_file: its content may mention git commit without running it
    return list(_strings(payload))


def _split(segment: str):
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _base(tok: str) -> str:
    """'C:\\Git\\cmd\\git.exe' -> 'git', '$(git' -> 'git', 'python3.12' -> 'python3'."""
    t = re.split(r"[\\/]", tok.strip("\"'"))[-1]
    t = t.lstrip("($`{").rstrip(")}`")
    t = re.sub(r"\.exe$", "", t)
    return re.sub(r"(\d)\.\d+$", r"\1", t)


def _git_args_gated(args) -> bool:
    j = 0
    while j < len(args) and args[j].startswith("-") and args[j] not in ("--version", "--help"):
        opt, eq, val = args[j].partition("=")
        if opt == "-c":
            value = val if eq else (args[j + 1] if j + 1 < len(args) else "")
            if value.startswith("alias."):
                return True  # git -c alias.ci=commit ci
        j += 2 if (opt in GIT_GLOBAL_OPTS_WITH_ARG and not eq) else 1
    if j >= len(args):
        return False
    sub = args[j]
    if sub in GATED_SUB:
        return True
    if sub == "config":
        return any(a.startswith("alias.") for a in args[j + 1:])  # git config alias.ci commit
    return sub not in SAFE_SUB


def runs_git_write(command: str, depth=0) -> bool:
    """True when the shell command may make a commit or push: any git subcommand in GATED_SUB or unknown
    to SAFE_SUB (aliases), in any letter case, behind global options, inside sh -c '...', cmd /c,
    pwsh -Command or an interpreter one-liner (python -c, node -e), `gh pr merge`, or `xargs git`."""
    c = command.lower()
    if depth > 4 or not re.search(r"git|\bgh\b", c):
        return False
    names_git = re.search(r"\bgit\b", c) is not None
    for segment in SEPARATORS.split(c):
        toks = _split(segment)
        for i, t in enumerate(toks):
            if (" " in t.strip() or any(s in t for s in ("&&", ";", "|"))) and runs_git_write(t, depth + 1):
                return True
            base = _base(t)
            if base == "gh" and toks[i + 1:i + 3] == ["pr", "merge"]:
                return True
            if base == "xargs" and any(_base(x) == "git" for x in toks[i + 1:]):
                return True
            if base in INTERPRETERS and names_git and (
                    i == len(toks) - 1 or any(INLINE_FLAG.match(x) for x in toks[i + 1:])):
                return True  # python -c "...git...", `echo git commit | sh`
            if base == "git" and _git_args_gated(toks[i + 1:]):
                return True
    # quoting the shell could not parse: fall back to a plain pattern so the gate errs toward blocking
    return FALLBACK.search(c) is not None


def gated(payload) -> bool:
    """True when this tool call can make a commit or push."""
    name = tool_name(payload).lower()
    if re.search(r"(^|[_\-.])(commit|push|merge)", name):
        return True  # a native git tool
    if "mcp" in name and isinstance(payload, dict):  # use_mcp_tool: look at the tool it calls
        for k in INPUT_KEYS:
            v = payload.get(k)
            if isinstance(v, dict):
                for kk in ("tool_name", "toolName", "name", "tool"):
                    if isinstance(v.get(kk), str) and MCP_GIT_TOOL.search(v[kk].lower()):
                        return True
        return False
    return any(runs_git_write(c) for c in command_strings(payload))


def _log(root: Path, raw: str, payload):
    try:
        d = root / ".tare"
        d.mkdir(exist_ok=True)
        p = d / "hook_payloads.log"
        entry = {"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "tool": tool_name(payload), "payload": payload if payload is not None else raw}
        lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
        lines.append(json.dumps(entry, ensure_ascii=False))
        p.write_text("\n".join(lines[-LOG_KEEP:]) + "\n", encoding="utf-8", newline="\n")
    except OSError:
        pass  # logging must never decide the gate


def _git(root: Path, *args):
    """git -C root ... . Inside a git hook, git exports GIT_INDEX_FILE for the repository making the commit;
    when that is another repository (a commit in the nested clone port/), it is dropped so that the query
    reads root's own repository."""
    import subprocess
    env = dict(os.environ)
    idx = env.get("GIT_INDEX_FILE")
    if idx:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--absolute-git-dir"], capture_output=True,
                           timeout=30, env={k: v for k, v in env.items() if k != "GIT_INDEX_FILE"})
        own = Path(r.stdout.decode("utf-8", "replace").strip()).resolve() if r.returncode == 0 else None
        if own is None or Path(idx).resolve().parent != own:
            env.pop("GIT_INDEX_FILE")
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=30, env=env)


def _git_top(root: Path):
    """The top of the git working tree holding the case root, or None when it is not in one."""
    import shutil
    if shutil.which("git") is None:
        return None
    r = _git(root, "rev-parse", "--show-toplevel")
    if r.returncode:
        return None
    return Path(r.stdout.decode("utf-8", "replace").strip()).resolve()


def _sealed_tare_json(root: Path) -> bool:
    """tare.json differs from HEAD only in 'accepted', and `tare accept` wrote this exact file."""
    from . import config
    try:
        seal = json.loads((root / ".tare" / "accept_seal.json").read_text(encoding="utf-8"))
        if seal.get("tare_json_sha256") != config.sha256_file(root / "tare.json"):
            return False
        r = _git(root, "show", "HEAD:./tare.json")
        if r.returncode:
            return False
        head = json.loads(r.stdout.decode("utf-8"))
        now = json.loads((root / "tare.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    head.pop("accepted", None)
    now.pop("accepted", None)
    return head == now


def protected_changes(root: Path, rec):
    """([changed paths], 'git' | 'record' | None): PROTECTED paths that differ from git HEAD in the working
    tree or index (untracked files included); without git, those whose hash differs from the last weigh.
    git reports paths relative to the top of the working tree."""
    from . import config
    top = _git_top(root)
    if top is not None:
        root_r = Path(root).resolve()
        specs = [config.rel_to(root_r, p) for p in config.protected_paths(root_r)
                 if p.resolve() == top or top in p.resolve().parents]
        r = _git(root, "--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--",
                 *specs)
        if r.returncode == 0:
            items, paths, i = r.stdout.decode("utf-8", "replace").split("\0"), [], 0
            while i < len(items):
                e = items[i]
                if len(e) > 3:
                    paths.append(e[3:])
                    if "R" in e[:2] or "C" in e[:2]:
                        i += 1  # the rename's source path follows
                        if i < len(items) and items[i]:
                            paths.append(items[i])
                i += 1
            tare_json = (root_r / "tare.json").relative_to(top).as_posix() if top in root_r.parents \
                else "tare.json"
            if tare_json in paths and _sealed_tare_json(root):
                paths = [p for p in paths if p != tare_json]
            return sorted(set(paths)), "git"
    if rec and isinstance(rec.get("protected"), dict):
        now, old = config.hash_protected(root), rec["protected"]
        return sorted(k for k in set(now) | set(old) if now.get(k) != old.get(k)), "record"
    return [], None


def _few(paths, n=3):
    return ", ".join(paths[:n]) + (f" and {len(paths) - n} more" if len(paths) > n else "")


def verdict(root: Path, git_hook=False):
    """(allowed, message) for the port under test ('local', pinned in code)."""
    from . import config
    rec_path = root / ".tare" / f"weigh_{config.PORT_SIDE}.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.is_file() else None
    if not (git_hook and os.environ.get("TARE_MAINTAINER") == "1"):
        changed, how = protected_changes(root, rec)
        if changed:
            verb = "differs" if len(changed) == 1 else "differ"
            where = f"{verb} from git HEAD" if how == "git" else "changed after the last weigh"
            return False, (f"{BLOCKED}{_few(changed)} {where}. tare.json, fixtures/, mainframe/, sides/, tare/ and "
                           ".bob/ are read-only in a Tare session: restore them (git restore <path>), or ask the "
                           "repo's owner. An accepted difference is added only with python -m tare accept.")
    now = config.hash_sources(root, config.PORT_SOURCES)
    if not now:
        return True, "TARE: no port sources yet (port/**/*.java, port/MAIN); nothing to weigh."
    if rec is None:
        return False, (f"{BLOCKED}No weigh on record for the port under test (local). "
                       "Run weigh with side local (it runs the port first).")
    if rec.get("sources") != now:
        changed = sorted(set(now) ^ set(rec.get("sources") or {})
                         | {k for k in now if (rec.get("sources") or {}).get(k) not in (None, now[k])})
        return False, (f"{BLOCKED}The port changed after the last weigh ({_few(changed)}). "
                       "Weigh it again with side local (it reruns the port).")
    prov = rec.get("provenance") or {}
    if prov.get("sources") != now or prov.get("output_sha256") != rec.get("port_sha256"):
        return False, (f"{BLOCKED}The last weigh is not tied to a run of the current port sources. "
                       "Weigh again with side local (it reruns the port).")
    key = root / config.ANSWER_KEY
    if not key.is_file() or rec.get("answer_sha256") != config.sha256_file(key):
        return False, f"{BLOCKED}The answer key changed after the last weigh. Weigh it again."
    if rec.get("accepted_sha256") != config.accepted_sha256(config.load_config(root).get("accepted", [])):
        return False, f"{BLOCKED}tare.json's accepted differences changed after the last weigh. Weigh it again."
    s = rec.get("summary", {})
    if s.get("verdict") != "balanced":
        return False, f"{BLOCKED}{rec.get('describe', 'The last weigh is red')}. Run weigh, fix, weigh again."
    return True, f"TARE: {s.get('result_line', 'balanced')}"


def _say(msg):
    print(msg)
    print(msg, file=sys.stderr)


def advances_a_branch(root: Path, lines) -> bool:
    """reference-transaction input ('<old> <new> <ref>' per line): True when a branch moves forward to new
    commits (old is an ancestor of new). Creating or deleting a branch, a reset to an older commit, fetch
    (refs/remotes) and stash (refs/stash) do not count."""
    for line in lines:
        parts = line.split()
        if len(parts) != 3 or not parts[2].startswith("refs/heads/"):
            continue
        old, new = parts[0], parts[1]
        if old == new or not all(re.fullmatch(r"[0-9a-f]{40,64}", x) and x.strip("0") for x in (old, new)):
            continue
        if _git(Path(os.environ.get("TARE_HOOK_REPO") or root), "merge-base", "--is-ancestor", old,
                new).returncode == 0:
            return True
    return False


GIT_C = re.compile(r"\bgit(?:\.exe)?\b[^;&|\n]*?\s-C\s+(\"[^\"]+\"|'[^']+'|\S+)", re.I)


def case_for(payload, cwd=None):
    """The case a command acts on: the case holding the folder of a `git -C <dir>` in it (such as the nested
    clone cases/<case>/port), else None."""
    from . import config
    cwd = Path(cwd or Path.cwd())
    for c in command_strings(payload):
        for m in GIT_C.finditer(c):
            d = Path(m.group(1).strip("\"'"))
            d = d if d.is_absolute() else cwd / d
            if d.is_dir():
                hit = config.case_root(d)
                if hit is not None:
                    return hit
    return None


def main(stdin=None, git_hook=None) -> int:
    from . import config
    if git_hook:
        try:
            # the hook script cds to the case root and sets TARE_ROOT to it, so that is the root even when
            # a commit being made deletes tare.json; run by hand at the top of a working tree, cwd is
            if os.environ.get("TARE_ROOT") or not (Path.cwd() / ".git").exists():
                root = config.repo_root()
            else:
                root = Path.cwd().resolve()
            if git_hook == "reference-transaction" and not advances_a_branch(
                    root, (stdin if stdin is not None else sys.stdin).read().splitlines()):
                return 0
            ok, msg = verdict(root, git_hook=True)
        except Exception as e:  # never fail open
            ok, msg = False, f"{BLOCKED}The gate hit an error: {type(e).__name__}: {e}"
        if not ok:
            print(f"{msg} (git {git_hook} hook)", file=sys.stderr)
        return 0 if ok else 1
    try:
        raw = (stdin if stdin is not None else sys.stdin).read()
        root = config.repo_root()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        _log(root, raw, payload)
        if payload is None:
            raise ValueError(f"hook payload is not JSON: {raw[:200]!r}")
        if "completion" in tool_name(payload).lower():
            try:
                ok, msg = verdict(root)
            except Exception as e:
                ok, msg = False, f"{BLOCKED}The gate hit an error: {type(e).__name__}: {e}"
            if not ok:
                _say("TARE: completion allowed, but the port is red or not weighed: "
                     + msg[len(BLOCKED):] + " Commit and push stay blocked until the weigh balances.")
            return 0
        if not gated(payload):
            return 0
        if not os.environ.get("TARE_ROOT"):
            root = case_for(payload) or root
        ok, msg = verdict(root)
        if ok:
            return 0
        _say(msg)
        return 2
    except Exception as e:  # never fail open
        _say(f"{BLOCKED}The gate hit an error: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
