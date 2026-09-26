---
description: Port a COBOL batch program to Java and prove it against the original program
argument-hint: <program-name>
---
Use the replay skill to port the COBOL batch program $1 from `mainframe/cbl/` to Java under `port/`, then prove it with the tare MCP tools.

The port is done only when `weigh` with side `local` is balanced: every field of every output record equal to the original's. When a weigh is red, explain the first differing field, confirm the COBOL rule in IBM's documentation, fix the port and weigh again. Then commit.
