# Tare

Tare replays a COBOL batch program and a port of it on the same input, and weighs their outputs record by record and field by field. The original program's output is the answer key. A commit gate for IBM Bob, and git hooks for every other client, refuse a commit while the port's last weigh is red.

To tare a scale is to zero it, so that it measures only what matters.

## How it works

1. **Answer key.** `python -m tare answer-key` compiles the original COBOL with GnuCOBOL and runs its job steps as `tare.json` describes them: DD names mapped to files, an optional PARM, indexed files loaded and unloaded with their keys. It writes `fixtures/answer_key/`: the input files, each output file byte for byte, `records.json` (the outputs decoded with their layouts) and each step's job log. The z/OS pieces are harness programs generated from `tare.json`, each headed `HARNESS:`: a loader/unloader standing in for IDCAMS REPRO, one PARM driver per step with a PARM, and a CEE3ABD abend stub. Before it writes `records.json`, it checks that the COBOL's own output is sound: every packed-decimal (COMP-3) field holds valid digit and sign half-bytes, every zoned numeric field decodes, and every declared `echo` reads back. An unsound output stops with `answer key unsound: field X in record N of <file> is not valid packed decimal (bytes ...)` and writes no `records.json`; `reproduce` and `check` run the same check on the committed answer key and stop before weighing any side.
2. **Port.** `python -m tare run-port local` compiles the Java under `port/`, runs it in a sandbox on the answer key's input, and decodes the fixed-width files it writes with the same layouts.
3. **Weigh.** `python -m tare weigh --port local` aligns the two sides by key per output file and compares every declared field, numbers in decimal. The ledger counts records, differing records and fields, missing and extra records, and for each numeric field how many values are higher, how many lower, and the net. The verdict is balanced or red, and a drawing of a balance scale shows it.
4. **Explain.** `python -m tare explain --key <key> --field <field>` shows both values, the COBOL statements that write the field or a group holding it (with file:line, read from the source), the field's PIC and USAGE (copybooks expanded with their `COPY ... REPLACING`: pseudo-text, literals, words, `LEADING` and `TRAILING`), and, for a numeric difference, the exact arithmetic of the `COMPUTE` when its operands are in the record: truncated and rounded half-up, beside what each side wrote, with IBM's documented rule for `ROUNDED`.

## A case

A case is a folder holding `tare.json`, the COBOL under `mainframe/`, the answer key under `fixtures/answer_key/` and the port under `port/`. `tare.json` describes it:

| Key | What it holds |
|---|---|
| `cobol` | `sources`, `copybooks` (folders) and `flags` (default `-std=ibm`; add `-fsign=EBCDIC` when signs are EBCDIC overpunch) |
| `files` | per file: `from` (initial content; `from_format` `fixed` or `lines`), `record_length`, `organization` (`sequential` or `indexed` with `key {offset, length}` and `alternate_keys`), `layout`, `output: true` for the files the weigh compares, and on an output file optional round-trip checks `echo: [{field, input, input_field, match}]` (the output field reads back equal to an input file's field, in the input record with the same number, `match: record`, or in any input record, `match: any`) |
| `steps` | per job step: `program`, `dd` (DD name to file), optional `parm` (passed as a halfword length plus text), `rc` (accepted return codes) |
| `layouts` | per layout: `record_length`, `key` (field names) and `fields`: `{name, offset, length, type: X, 9, S9V9 or COMP-3 (packed decimal), scale, sign: trailing-overpunch, separate or none, cobol}` |
| `sides` | public ports to weigh: `{name: {runner, repo, commit, licence, line}}`; `runner` is `java:<dir>` or a command |
| `expected` | the verdict `reproduce` expects for each side |
| `accepted` | differences a person has signed (see below) |

`python -m tare contract` writes the port contract for Bob's replay skill (`.bob/skills/replay/PORT_CONTRACT.md`) from these layouts. `python -m tare reproduce` rebuilds the answer key, runs every side and prints a scoreboard; `python -m tare check <side>` does the same for one side and writes the ledger to the GitHub step summary.

## How Bob uses it

Everything lives in `.bob/`, so anyone who opens the repository in Bob gets the same workflow:

| Piece | File | What it does |
|---|---|---|
| Mode `Tare` | `.bob/custom_modes.yaml`, `.bob/rules-tare/` | A modernization engineer for whom the original program is the answer key. Its edit tool reaches only `port/` and `docs/`; the hook covers the shell. |
| MCP server `tare` | `.bob/mcp.json`, `tare/mcp_server.py` | `run_mainframe`, `run_port`, `weigh` (a ledger plus an image of the scale) and `explain`. |
| Hook | `.bob/settings.json`, `tare/gate.py` | A blocking `PreToolUse` hook that finds the repository from any subfolder. It exits with code 2 on any git command that commits or pushes while the port's last weigh is red, the port changed after it, or the protected paths differ from git HEAD. Completion is allowed, with a notice. |
| Skill `replay` | `.bob/skills/replay/` | Plan, port, weigh, explain, fix, weigh again, commit. |
| Commands | `.bob/commands/prove.md`, `judge.md` | `/prove <program>` ports and proves; `/judge all` weighs the declared sides with parallel subagents. |

The MCP server and the CLI find the case as the nearest folder at or above the working directory that holds `tare.json`, or the folder named by `TARE_ROOT`.

## What the gate guarantees

The gate stops an agent's honest mistakes and casual workarounds inside Bob. The CI check on a clean runner is the backstop against deliberate tampering.

- **A weigh describes the current port.** `weigh local` reruns the port when a source, `port/MAIN`, an input file or the output changed since the port's last run (recorded in `work/runs/local/provenance.json`). The gate checks the weigh record against the current sources.
- **The port does not see the answer key.** It runs in `work/sandbox/local/`, which holds only copies of the input files and the compiled classes. A port that opens an absolute path or climbs out with `../` is deliberate tampering, out of scope like the items below.
- **The policy is fixed in code.** The side under test is always `local`, its sources are `port/**/*.java` and `port/MAIN`, and its answer key is `fixtures/answer_key/records.json`, whatever `tare.json` says. A commit is blocked while `tare.json`, `fixtures/`, `mainframe/`, `tare/` or `.bob/` differ from git HEAD in the working tree or the index, including when the case sits in a subfolder of the repository.
- **An accepted difference is signed, exact and sealed.** An entry is `{file, key, fields, expect, reason, accepted_by, date, seal}` and covers only the listed fields of the one record it names. `expect: {field: value}` pins exact values; `expect: "answer_key"` pins the answer key's values. The answer key's own values always pass; any other value is red, and the ledger row shows the value expected. Missing and extra records are never accepted. A person adds an entry with `python -m tare accept --key <key> --by "<name>" --reason "<text>"` and removes it with `python -m tare accept --revoke --key <key>`; the `tare.json` that command writes can be committed, and an entry edited by hand no longer matches its seal and covers nothing.
- **Every git route is covered.** `python -m tare install-hooks` installs git `pre-commit`, `pre-merge-commit`, `pre-push`, `pre-rebase`, `pre-applypatch` and `reference-transaction` hooks that apply the same rule to any git client: aliases, scripts, subprocesses, other editors. The last one vetoes any branch advance, which covers `cherry-pick` and `revert` (git runs no pre-commit hook for them); a vetoed one leaves its changes staged and HEAD where it was. Git commands are matched in any letter case.
- **Bob can always finish.** Completion while red is allowed with a notice, so Bob is never trapped in a task it cannot finish; the red port still cannot be committed.

Out of scope by design: forging `.tare/` records or the provenance file, `git commit --no-verify`, and `TARE_MAINTAINER=1`, the maintainers' switch that lets git's hooks commit changes to protected files (the Bob hook ignores it).

The same check is a GitHub Actions workflow, `.github/workflows/tare-check.yml`, which another repository can call with `workflow_call`.

## The self-test fixture

`examples/unitsum/` is a test fixture, not a case: a small COBOL program written for the test suite that totals shipping weights per item id, with a correct Java port and one that rounds half-up. The tests run the whole loop on it (answer key under GnuCOBOL, both ports weighed, gate exit codes, accept, explain).

```
python -m unittest discover -s tests -t .
cd examples/unitsum
PYTHONPATH=../.. python -m tare reproduce --offline   # seconds, Python only
PYTHONPATH=../.. python -m tare reproduce             # GnuCOBOL and a JDK >= 17
```

The devcontainer (`.devcontainer/`) has every toolchain.

## Layout

- `tare/`: the answer-key runner, record decoding, the ledger, the gate, the MCP server, the scale and the CLI.
- `.bob/`: the mode, rules, skill, commands, hook and MCP configuration for IBM Bob.
- `tests/`: the test suite.
- `examples/unitsum/`: the self-test fixture.

## Licence

MIT (`LICENSE`). The fonts in `tare/assets/fonts/` are under the SIL Open Font Licence.
