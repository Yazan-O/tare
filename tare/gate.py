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
                            "--super-prefix", "--config-env"}
SEPARATORS = re.compile(r"&&|\|\||;|\||\n|&")
GATED_SUB = {"commit", "commit-tree", "push", "merge", "pull", "cherry-pick", "revert", "am", "rebase",
             "update-ref", "filter-branch", "send-pack", "replace", "fast-import", "citool", "gui"}
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
    if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
        return " ".join(shlex.quote(x) for x in v)
    return None


def command_strings(payload) -> list:
    if isinstance(payload, dict):
        for k in INPUT_KEYS:
            v = payload.get(k)
            if isinstance(v, dict) and _as_command(v.get("command")) is not None:
                return [_as_command(v["command"])]
        if _as_command(payload.get("command")) is not None:
            return [_as_command(payload["command"])]
        name = tool_name(payload).lower()
        if name and not re.search(r"command|exec|shell|bash|terminal|run", name):
            return []
    return list(_strings(payload))


def _split(segment: str):
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _base(tok: str) -> str:
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
                return True
        j += 2 if (opt in GIT_GLOBAL_OPTS_WITH_ARG and not eq) else 1
    if j >= len(args):
        return False
    sub = args[j]
    if sub in GATED_SUB:
        return True
    if sub == "config":
        return any(a.startswith("alias.") for a in args[j + 1:])
    return sub not in SAFE_SUB


def runs_git_write(command: str, depth=0) -> bool:
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
                return True
            if base == "git" and _git_args_gated(toks[i + 1:]):
                return True
    return FALLBACK.search(c) is not None


def gated(payload) -> bool:
    name = tool_name(payload).lower()
    if re.search(r"(^|[_\-.])(commit|push|merge)", name):
        return True
    if "mcp" in name and isinstance(payload, dict):
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
        pass


def _git(root: Path, *args):
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
    import shutil
    if shutil.which("git") is None:
        return None
    r = _git(root, "rev-parse", "--show-toplevel")
    if r.returncode:
        return None
    return Path(r.stdout.decode("utf-8", "replace").strip()).resolve()


def _sealed_tare_json(root: Path) -> bool:
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


def _without_always_allow(obj):
    if isinstance(obj, dict):
        return {k: _without_always_allow(v) for k, v in obj.items() if k != "alwaysAllow"}
    if isinstance(obj, list):
        return [_without_always_allow(v) for v in obj]
    return obj


def _always_allow_only(root: Path, top: Path, rel: str) -> bool:
    try:
        head = _git(root, "show", f"HEAD:{rel}")
        index = _git(root, "show", f":{rel}")
        if head.returncode or index.returncode:
            return False
        want = _without_always_allow(json.loads(head.stdout.decode("utf-8")))
        return (_without_always_allow(json.loads(index.stdout.decode("utf-8"))) == want
                and _without_always_allow(json.loads((top / rel).read_text(encoding="utf-8"))) == want)
    except (OSError, ValueError):
        return False


def protected_changes(root: Path, rec, exempt=(), exempted=None):
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
                        i += 1
                        if i < len(items) and items[i]:
                            paths.append(items[i])
                i += 1
            tare_json = (root_r / "tare.json").relative_to(top).as_posix() if top in root_r.parents \
                else "tare.json"
            if tare_json in paths and _sealed_tare_json(root):
                paths = [p for p in paths if p != tare_json]
            paths = [p for p in paths if not ((p == ".bob/mcp.json" or p.endswith("/.bob/mcp.json"))
                                              and _always_allow_only(root, top, p))]
            if exempt and tare_json not in paths:
                pats = [config.glob_regex(g) for g in exempt]
                prefix = tare_json[:-len("tare.json")]
                free = [p for p in paths if p.startswith(prefix)
                        and any(x.match(p[len(prefix):]) for x in pats)]
                if exempted is not None:
                    exempted.extend(p[len(prefix):] for p in free)
                paths = [p for p in paths if p not in free]
            return sorted(set(paths)), "git"
    if rec and isinstance(rec.get("protected"), dict):
        now, old = config.hash_protected(root), rec["protected"]
        return sorted(k for k in set(now) | set(old) if now.get(k) != old.get(k)), "record"
    return [], None


def _few(paths, n=3):
    return ", ".join(paths[:n]) + (f" and {len(paths) - n} more" if len(paths) > n else "")


def verdict(root: Path, git_hook=False):
    from . import config
    maintainer = git_hook and os.environ.get("TARE_MAINTAINER") == "1"
    declared = config.gate_spec(config.load_config(root))
    if declared and not maintainer and _git_top(root) is None:
        declared = None
    side, sources = (declared["side"], declared["sources"]) if declared else (config.PORT_SIDE,
                                                                             config.PORT_SOURCES)
    local = side == config.PORT_SIDE
    rec_path = root / ".tare" / f"weigh_{side}.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.is_file() else None
    edited = []
    if not maintainer:
        changed, how = protected_changes(root, rec, sources if declared else (), edited)
        if changed:
            verb = "differs" if len(changed) == 1 else "differ"
            where = f"{verb} from git HEAD" if how == "git" else "changed after the last weigh"
            return False, (f"{BLOCKED}{_few(changed)} {where}. tare.json, fixtures/, mainframe/, sides/, tare/ and "
                           ".bob/ are read-only in a Tare session: restore them (git restore <path>), or ask the "
                           "repo's owner. An accepted difference is added only with python -m tare accept.")
    now = config.hash_sources(root, sources)
    if not now:
        return True, f"TARE: no port sources yet ({', '.join(sources)}); nothing to weigh."
    if rec is None:
        return False, (f"{BLOCKED}No weigh on record for the port under test ({side}). "
                       f"Run weigh with side {side}" + (" (it runs the port first)." if local else "."))
    if rec.get("sources") != now:
        changed = sorted(set(now) ^ set(rec.get("sources") or {})
                         | {k for k in now if (rec.get("sources") or {}).get(k) not in (None, now[k])})
        return False, (f"{BLOCKED}The port changed after the last weigh ({_few(changed)}). "
                       f"Weigh it again with side {side}" + (" (it reruns the port)." if local else "."))
    if local:
        prov = rec.get("provenance") or {}
        if prov.get("sources") != now or prov.get("output_sha256") != rec.get("port_sha256"):
            return False, (f"{BLOCKED}The last weigh is not tied to a run of the current port sources. "
                           "Weigh again with side local (it reruns the port).")
    else:
        out = Path(rec.get("port_path") or "")
        if not out.is_file() or config.sha256_file(out) != rec.get("port_sha256"):
            return False, (f"{BLOCKED}The output the last weigh of {side} read has changed or is gone. "
                           f"Weigh it again with side {side}.")
        if edited and rec.get("recorded"):
            return False, (f"{BLOCKED}The last weigh of {side} read its recorded output in fixtures/, not a run "
                           f"of the edited port ({_few(sorted(set(edited)))}). Run the port (python -m tare "
                           f"run-port {side}), then weigh it again with side {side}.")
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


def _case_and_dir(payload, cwd=None):
    from . import config
    cwd = Path(cwd or Path.cwd())
    for c in command_strings(payload):
        for m in GIT_C.finditer(c):
            d = Path(m.group(1).strip("\"'"))
            d = d if d.is_absolute() else cwd / d
            if d.is_dir():
                hit = config.case_root(d)
                if hit is not None:
                    return hit, d
    return None, None


def case_for(payload, cwd=None):
    return _case_and_dir(payload, cwd)[0]


def touched_cases(where: Path, skip=None) -> list:
    top = _git_top(where)
    if top is None:
        return []
    r = _git(where, "--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if r.returncode:
        raise ValueError(f"git status failed in {top}: {r.stderr.decode('utf-8', 'replace').strip()}")
    skip = Path(skip).resolve() if skip else None
    found, seen = [], {}
    for e in r.stdout.decode("utf-8", "replace").split("\0"):
        if len(e) <= 3:
            continue
        d = (top / e[3:]).parent
        while d != top and top in d.parents:
            if d not in seen:
                seen[d] = (d / "tare.json").is_file()
            if seen[d]:
                if d != skip and d not in found:
                    found.append(d)
                break
            d = d.parent
    return sorted(found)


def verdict_all(root: Path, where: Path, git_hook=False):
    ok, msg = verdict(root, git_hook=git_hook)
    return (ok, msg) if not ok else (_other_cases(root, where, git_hook) or (ok, msg))


def _other_cases(root: Path, where: Path, git_hook=False):
    for other in touched_cases(where, skip=root):
        ok, msg = verdict(other, git_hook=git_hook)
        if not ok:
            return ok, f"{msg} (case {other.name})"
    return None


def main(stdin=None, git_hook=None) -> int:
    from . import config
    if git_hook:
        try:
            if os.environ.get("TARE_ROOT") or not (Path.cwd() / ".git").exists():
                root = config.repo_root()
            else:
                root = Path.cwd().resolve()
            if git_hook == "reference-transaction" and not advances_a_branch(
                    root, (stdin if stdin is not None else sys.stdin).read().splitlines()):
                return 0
            hook_repo = os.environ.get("TARE_HOOK_REPO")
            if git_hook in ("pre-commit", "pre-merge-commit") and hook_repo and \
                    _git_top(root) == Path(hook_repo).resolve():
                ok, msg = verdict_all(root, root, git_hook=True)
            else:
                ok, msg = verdict(root, git_hook=True)
        except Exception as e:
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
        hit, where = (None, None) if os.environ.get("TARE_ROOT") else _case_and_dir(payload)
        if hit is None:
            ok, msg = verdict_all(root, Path.cwd())
        else:
            ok, msg = verdict(hit)
            if ok and _git_top(where) == _git_top(hit):
                ok, msg = _other_cases(hit, where) or (ok, msg)
        if ok:
            return 0
        _say(msg)
        return 2
    except Exception as e:
        _say(f"{BLOCKED}The gate hit an error: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
