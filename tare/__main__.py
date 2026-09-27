import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tare.__main__ import main
    sys.exit(main())

import argparse
import os

from . import config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tare", description="Weigh a port of a COBOL batch program against the "
                                                          "original's own output (the answer key).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("answer-key", help="run the original COBOL job in tare.json under GnuCOBOL and record "
                                          "fixtures/answer_key/")
    k.add_argument("--out", help="output folder (default: fixtures/answer_key)")
    rp = sub.add_parser("run-port", help="build and run a port on the answer key's input: 'local' (port/) or "
                                         "a side declared in tare.json")
    rp.add_argument("side", nargs="?", default=config.PORT_SIDE)
    w = sub.add_parser("weigh", help="compare a port's records.json with the answer key's; exit 0 balanced, 1 red")
    w.add_argument("--port", required=True, help="a side name (work/runs/<side>/records.json) or a path to "
                                                "records.json; side local reruns the port first when its "
                                                "last run is stale")
    w.add_argument("--answer", help="answer key records.json (default: fixtures/answer_key/records.json)")
    w.add_argument("--no-image", action="store_true", help="skip .tare/scale.png")
    e = sub.add_parser("explain", help="the evidence for one field of one record")
    e.add_argument("--file", help="output file name in tare.json (default: the first)")
    e.add_argument("--key", help="record key; several key fields are joined with '|' (default: the first "
                                 "differing record)")
    e.add_argument("--field", help="field name in the layout (default: the first differing field)")
    e.add_argument("--port", help="side name or records.json path (default: local)")
    e.add_argument("--answer")
    g = sub.add_parser("gate", help="run the Bob PreToolUse gate on a payload from stdin")
    g.add_argument("--git-hook", metavar="NAME", help="run as git's NAME hook (no stdin payload; exit 1 blocks)")
    h = sub.add_parser("install-hooks", help="install git pre-commit, pre-merge-commit, pre-push, pre-rebase, "
                                             "pre-applypatch and reference-transaction hooks that apply the "
                                             "gate to any git client")
    h.add_argument("--uninstall", action="store_true")
    h.add_argument("--repo", help="install into this git working tree inside the case (e.g. port/, a clone of "
                                  "the port under test) instead of the repository holding the case")
    f = sub.add_parser("fetch", help="run the case's fetch.py (third-party sources at pinned commits); "
                                     "--local makes port/ a clone of the published port, with the gate's hooks")
    f.add_argument("--local", action="store_true", help="clone the published port into port/ (the port under "
                                                        "test), a git repository of its own")
    f.add_argument("--reset-local", action="store_true", help="put port/ back at the published commit, "
                                                              "discarding its uncommitted changes and commits")
    f.add_argument("--full", action="store_true", help="also the national data")
    ac = sub.add_parser("accept", help="a person signs an accepted difference for one record in tare.json")
    ac.add_argument("--file", help="output file name (default: the only one)")
    ac.add_argument("--key", help="record key")
    ac.add_argument("--fields", help="comma-separated field names (default: the fields that differ now)")
    ac.add_argument("--expect", choices=("port", "answer_key"), default="port",
                    help="port: pin the port's current values (default); answer_key: pin the answer key's")
    ac.add_argument("--by", help="the name of the person accepting")
    ac.add_argument("--reason", help="why the difference is accepted")
    ac.add_argument("--revoke", action="store_true", help="remove the accepted difference for --file/--key")
    ct = sub.add_parser("contract", help="write .bob/skills/replay/PORT_CONTRACT.md from tare.json")
    ct.add_argument("--out")
    s = sub.add_parser("sheet", help="render the contact sheet of the committed side fixtures")
    s.add_argument("--out", default="work/scale_states.png")
    r = sub.add_parser("reproduce", help="rerun the answer key and every declared side, weigh each, print the "
                                         "scoreboard; exit 0 when every verdict is tare.json's expected one")
    r.add_argument("--offline", action="store_true", help="weigh only the committed fixtures (Python only)")
    r.add_argument("--record", action="store_true", help="copy each fresh side run to fixtures/sides/<side>/")
    c = sub.add_parser("check", help="answer key, one declared side, weigh; exit 0 balanced, 1 red, 2 error")
    c.add_argument("side")
    c.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"),
                   help="append the ledger as Markdown here (default: $GITHUB_STEP_SUMMARY)")
    c.add_argument("--offline", action="store_true", help="weigh the committed fixture only")
    sub.add_parser("reset", help="delete .tare/weigh_local.json and .tare/last_weigh.json before a session")
    a = ap.parse_args(argv)
    root = config.repo_root()

    try:
        if a.cmd == "answer-key":
            from . import answerkey
            return answerkey.main_build(root, a.out)
        if a.cmd == "run-port":
            from . import localport, sides
            if a.side == config.PORT_SIDE:
                _, text = localport.run(root)
            else:
                _, text = sides.run(root, a.side)
            print(text)
            return 0
        if a.cmd == "weigh":
            from . import ledger, weighing
            rec = weighing.run(root, a.port, a.answer, render=not a.no_image)
            if rec.get("_run_log"):
                print(rec["_run_log"])
                print()
            print(ledger.format_table(rec["_result"]))
            print()
            print(rec["summary"]["result_line"])
            print(f"wrote .tare/weigh_{rec['side']}.json, .tare/last_weigh.json, .tare/ledger.md"
                  + ("" if a.no_image else ", .tare/scale.png"))
            return 0 if rec["summary"]["verdict"] == "balanced" else 1
        if a.cmd == "explain":
            from . import explain
            print(explain.explain(root, a.file, a.key, a.field, a.port, a.answer))
            return 0
        if a.cmd == "gate":
            from . import gate
            return gate.main(git_hook=a.git_hook)
        if a.cmd == "install-hooks":
            from . import githooks
            return githooks.install(root, uninstall=a.uninstall, repo=a.repo)
        if a.cmd == "fetch":
            import subprocess
            script = root / "fetch.py"
            if not script.is_file():
                print(f"tare: this case ({root}) has no fetch.py", file=sys.stderr)
                return 2
            flags = [x for x, on in (("--local", a.local), ("--reset-local", a.reset_local), ("--full", a.full))
                     if on]
            return subprocess.run([sys.executable, str(script), *flags], cwd=root).returncode
        if a.cmd == "accept":
            from . import accept
            if a.revoke:
                if not a.key:
                    ap.error("accept --revoke needs --key (and --file when there are several output files)")
                return accept.revoke(root, a.file, a.key)
            if not (a.key and a.by and a.reason):
                ap.error("accept needs --key, --by and --reason (or --revoke --key K)")
            fields = [f.strip() for f in a.fields.split(",") if f.strip()] if a.fields else None
            return accept.accept(root, a.file, a.key, a.by, a.reason, fields, a.expect)
        if a.cmd == "contract":
            from . import contract
            print(f"wrote {contract.write(root, a.out)}")
            return 0
        if a.cmd == "sheet":
            from . import reproduce, scale
            states = reproduce.fixture_states(root)
            p = scale.contact_sheet(states, root / a.out, program=config.load_config(root).get("program"))
            print(f"wrote {p} (committed fixtures: " + (", ".join(lbl for _, lbl in states) or "none") + ")")
            return 0
        if a.cmd == "reproduce":
            from . import reproduce
            return reproduce.reproduce(root, offline=a.offline, record=a.record)
        if a.cmd == "check":
            from . import reproduce, sides
            if a.side not in sides.declared(root):
                print(f"tare: check takes a side declared in tare.json ({', '.join(sides.declared(root)) or 'none'}), "
                      f"not {a.side!r}", file=sys.stderr)
                return 2
            return reproduce.check(root, a.side, a.summary, offline=a.offline)
        if a.cmd == "reset":
            from . import reproduce
            return reproduce.reset(root)
    except (FileNotFoundError, ValueError, KeyError, RuntimeError) as err:
        print(f"tare: {type(err).__name__}: {err}", file=sys.stderr)
        return 3
    return 2


if __name__ == "__main__":
    sys.exit(main())
