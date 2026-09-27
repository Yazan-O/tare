# Tare

**Submitted for the IBM Bob 2.0 hackathon on [lablab.ai](https://lablab.ai).**

Governments still run high-stakes money on decades-old COBOL: property tax, health payments, and more. Those programs are being rewritten by AI agents. The GAO's latest look at critical U.S. federal legacy IT ([GAO-25-107795](https://www.gao.gov/products/gao-25-107795)) finds agencies spending most of their IT budgets keeping old systems running, and names Treasury systems that still depend on COBOL and Assembly while the people who know those languages grow scarce. The rewrite has to compute what the old program computes. "Looks right" is not enough.

<p align="center">
  <img src="assets/hero.svg" alt="Close enough doesn't commit." width="100%">
</p>

## The problem people miss

What teams check first is the port's own tests and a code review. That fails when the same agent wrote the port and the tests.

France publishes its property-tax COBOL and a public Java port co-written with an AI coding agent. The port's built-property unit tests pass **4 of 4**. Run the unmodified COBOL and the port on the same 2018 commune inputs and the totals differ on **408 of 408** Ain commune records, and on **35,268 of 35,389** nationally. These are commune-level statistics shaped into calculator inputs, not household bills. For commune 01001 the COBOL total due is €137,415 and the published port writes €144,041 — a replay difference on that record, not a claim about money lost.

Two defects pass the unit tests: the 3% and 8% fee rates swapped, and the household-waste tax left out of the total before fees.

<p align="center">
  <img src="assets/problem.svg" alt="Unit tests pass 4 of 4; the answer key finds 408 of 408 red." width="100%">
</p>

## What Tare does

To *tare* a scale is to zero it so it measures only what matters.

Tare treats the **original program as the answer key**. It replays that COBOL under GnuCOBOL, runs the port on the same inputs, and weighs every record and every field. A blocking gate inside IBM Bob — and git hooks for every other client — refuses a commit while the last weigh is red, missing, or stale. Bob cannot argue the numbers away. The records have to balance.

<p align="center">
  <img src="assets/architecture.svg" alt="Replay, run port, weigh, explain, gate." width="100%">
</p>

## The proof: one Bob session

Recorded in IBM Bob IDE (2026-09-26). One prompt. **3.74 Bobcoins.** Stills in [`bob_sessions/`](bob_sessions/).

1. Bob tries to commit the published port → **blocked** (no weigh on record).
2. Bob weighs → **red, 408 of 408**.
3. Two **parallel subagents** diagnose the fee fields and the totals.
4. Bob swaps the fee rates → commit refused again (**port changed after its weigh**).
5. First totals guess adds `mcttse` → **296** records still differ.
6. `explain` shows the COBOL never writes `mcttse` there; the missing term is `tctom` (household-waste tax).
7. Weigh → **balanced, 408 of 408**. Commit goes through: port `9ee1c3c`.

<p align="center">
  <img src="assets/bob_strip.svg" alt="Bob session strip: blocked, red, subagents, stale edit, wrong guess, balanced, committed." width="100%">
</p>

<p align="center">
  <img src="bob_sessions/tare_task01_01_first_block_no_weigh.png" alt="Blocked: no weigh" width="19%">
  <img src="bob_sessions/tare_task01_02_weigh_red_408_of_408.png" alt="Red 408 of 408" width="19%">
  <img src="bob_sessions/tare_task01_03_two_subagents_running.png" alt="Two parallel subagents" width="19%">
  <img src="bob_sessions/tare_task01_05_stale_edit_block.png" alt="Stale edit blocked" width="19%">
  <img src="bob_sessions/tare_task01_07_balanced_408_of_408.png" alt="Balanced 408 of 408" width="19%">
</p>
<p align="center">
  <img src="bob_sessions/tare_task01_06_wrong_guess_296_still_differ.png" alt="Wrong guess mcttse, 296 still differ" width="32%">
  <img src="bob_sessions/tare_task01_08_committed_task_summary_3.74.png" alt="Committed, 3.74 Bobcoins" width="32%">
  <img src="bob_sessions/tare_task01_09_bob_final_summary.png" alt="Bob closing summary" width="32%">
</p>

## Examples

### France property tax (taxe foncière)

DGFiP built-property calculator, 2018. Ain demo slice and full national run. Commune records from REI open data — not household bills.

<p align="center">
  <img src="assets/france_scales.svg" alt="Published port red nationally; repaired port balanced." width="100%">
</p>
<p align="center">
  <img src="assets/scale_published.png" alt="National scale: published port red" width="48%">
  &nbsp;
  <img src="assets/scale_repaired.png" alt="National scale: repaired port balanced" width="48%">
</p>

| Side | Ain | National |
|---|---|---|
| Published AI port (`java-ai`) | 408 of 408 red | 35,268 of 35,389 red |
| Repaired (`java-ai-fixed` / Bob's `local` port) | 0 of 408 | 0 of 35,389 |

### Medicare hospice pricer

CMS FY2021 Hospice Pricer COBOL as the answer key. 5,000 claims built from public CMS tables (no personal data).

| Side | Records differing |
|---|---|
| CMS's own Java (`cms-java`) | **140 of 5,000** |
| AI-assisted port (`java-ai`) | **270 of 5,000** |
| Repaired (`java-ai-fixed`) | **0 of 5,000** |

The gate now checks **every case a commit touches**, on the side each case declares (France: `local` / `port/`; Medicare: `java-ai-fixed` through its repair files). Commits `b50d981`, `4aa53e5`.

<p align="center">
  <img src="assets/results.svg" alt="Results table for France and Medicare." width="100%">
</p>

## The gate

<p align="center">
  <img src="assets/gate.svg" alt="Gate states: no weigh, red, stale edit block; balanced allows." width="100%">
</p>

```mermaid
flowchart LR
  A[git commit] --> B{Weigh on record?}
  B -->|no| X[BLOCK]
  B -->|yes| C{Verdict?}
  C -->|red| X
  C -->|balanced| D{Sources unchanged?}
  D -->|no · stale| X
  D -->|yes| E[ALLOW]
```

A PreToolUse hook finds the repo from any subfolder. Git `pre-commit` / `pre-push` / related hooks apply the same rule outside Bob. Completion while red is allowed with a notice so Bob is never trapped; the red port still cannot be committed.

## Under the hood

- **GnuCOBOL harness** generated from `tare.json`: loaders/unloaders for indexed files, PARM drivers, CEE3ABD stub.
- **Layouts** decode fixed-width output: COMP-3 packed decimal, zoned numerals, overpunch signs.
- **Answer-key soundness** check before `records.json` is written: invalid packed or zoned bytes stop the run.
- **Schema ledger** counts differing records and fields, missing/extra keys, and per-field net.
- **`explain`** expands `COPY … REPLACING`, cites COBOL and port lines, and shows arithmetic when operands are in the record.
- **`.bob` plugin**: custom mode `Tare`, rules, `replay` skill, `/prove` and `/judge`, MCP tools `run_mainframe` / `run_port` / `weigh` / `explain`, parallel subagents.
- **Case `gate` field**: each case names the side a commit must balance.

## Reproduce

```bash
git clone https://github.com/Yazan-O/tare
cd tare
python -m tare reproduce --offline
# seconds, Python only:
#   java-ai        red       408 of 408
#   java-ai-fixed  balanced  0 of 408

cd cases/medicare_hospice
PYTHONPATH=../.. python -m tare reproduce --offline
#   cms-java       red       140 of 5,000
#   java-ai        red       270 of 5,000
#   java-ai-fixed  balanced  0 of 5,000
```

Live site (commune search): https://yazan-o.github.io/tare/

With a JDK ≥ 17 and Maven: `python -m tare fetch --local` then `python -m tare weigh --port local`.

## Data sources

| Source | Use | Licence |
|---|---|---|
| [DGFiP property-tax COBOL](https://github.com/etalab/taxe-fonciere) @ 6bd40b2 | answer key | CeCILL-2.1 |
| [Java port](https://github.com/omnipede/taxe-fonciere) @ 5124d1c | port under test | CeCILL-2.1 |
| REI 2018, data.gouv.fr | commune inputs | Licence Ouverte 2.0 |
| IGN ADMIN EXPRESS COG 2018 | map boundaries | Licence Ouverte 2.0 |
| [CMS FY2021 Hospice Pricer](https://www.cms.gov/pricersourcecodesoftware) | Medicare answer key + tables | U.S. Government work |
| CMS Hospice Pricer 2.5.1 (Java) | `cms-java` side | FOIA transparency release |
| [rcaran/hospice-cms-pricer-java](https://github.com/rcaran/hospice-cms-pricer-java) @ 6558476 | AI-assisted port | no licence file in upstream |

No personal information. Medicare claims are constructed from public tables.

## Licence

MIT (`LICENSE`). Fonts in `tare/assets/fonts/` are SIL Open Font Licence.
