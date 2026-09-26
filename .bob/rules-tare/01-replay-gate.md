# The replay gate

- Done means the weigh is balanced: every field of every record the port writes equals what the original program wrote, on the same input. Nothing else counts as done: not compiling, not passing unit tests, not looking right.
- The answer key is read-only. Never edit `mainframe/`, `fixtures/`, `.tare/`, `tare/` or `.bob/`, and never change the comparison to make a weigh pass. If you believe the original program is wrong, say so to the user and stop; do not "fix" the answer key.
- After every change to `port/`, run `run_port` and then `weigh` with side `local`. Read the whole ledger, not only the verdict.
- When the weigh is red, call `explain` on the first differing field before editing anything. Find the COBOL statement and the PIC clause that produce the original's value, and confirm the rule in IBM's documentation (use `search_ibm_docs` for Enterprise COBOL for z/OS) before you change the port. Quote the documentation line you relied on.
- Decimal values are `BigDecimal` with the scale of the COBOL field. The original's output, not your expectation of COBOL, decides what the arithmetic must be.
- The Tare hook blocks `git commit`, `git push`, merges and every other commit-making git command while the last weigh is red, the port changed after it, or `tare.json`, `fixtures/`, `mainframe/`, `tare/` or `.bob/` differ from git HEAD. Do not try to get around it. If a tool call is blocked, call `weigh` with side `local` (it reruns the port when the sources changed), read the ledger, fix the port, weigh again.
- Only a person accepts a difference (`python -m tare accept`, signed with their name). Never run it yourself, and never edit `tare.json`.
- You may finish a task while the port is red; say so plainly in the completion, with the weigh result line.
- Commit messages for the port end with the weigh result line, for example `weigh: 5 of 5 records balance`.
