---
description: Weigh the public ports declared in tare.json against the original program and explain what differs
argument-hint: <side or all>
---
Judge the port $1 against the original COBOL program. The ports are the `sides` declared in `tare.json`; `all` means every side there.

For each side: run `run_port`, then `weigh`, and show the ledger and the scale. When there are several sides, give each side to its own `general` subagent in parallel, and have each return only its weigh summary line.

Then, for every side that is red, call `explain` on its first differing field and name the port's own line of code that causes it. Finish with one table: side, records that differ out of the total, direction (higher or lower) and net per numeric field, and the port's line. Do not edit any file.
