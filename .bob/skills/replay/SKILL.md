---
name: replay
description: Port a COBOL batch program to Java and prove it replays the original program's outputs field by field, using the tare MCP tools (run_mainframe, run_port, weigh, explain).
---
Port one COBOL batch program to Java and prove it against the original, using the Tare answer key in this repository.

<Steps>
<Step>
Plan. Read the program in `mainframe/cbl/`, every copybook it COPYs in `mainframe/cpy/`, and the job steps in `tare.json`. List each file the program reads and writes, its record layout, and every arithmetic statement that produces an output field, with its PIC clauses. When the program touches several files, you may give each file's layout to its own `explore` subagent in parallel and merge their summaries.
</Step>
<Step>
Run `run_mainframe` once to see the answer key: how many records the original wrote to each output file.
</Step>
<Step>
Write the port under `port/` following `PORT_CONTRACT.md` in this skill folder: its inputs, its output files and its command line. Keep the COBOL paragraph structure visible in the Java so a reviewer can follow one to the other.
</Step>
<Step>
Run `run_port` with side `local`, then `weigh` with side `local`. Show the user the ledger and the scale.
</Step>
<Step>
If the weigh is red: call `explain` on the first differing field. Confirm the COBOL rule behind the original's value in IBM's documentation with `search_ibm_docs`, and quote it. Change the port, then run and weigh again. Repeat until the weigh is balanced. Never edit the original side or the fixtures.
</Step>
<Step>
When the weigh is balanced, commit `port/` with a message that states the rule you fixed and ends with the weigh result line.
</Step>
</Steps>

The record layouts, the output format and the exact command line are in `PORT_CONTRACT.md`, generated from `tare.json` by `python -m tare contract`.
