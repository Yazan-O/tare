# TEST FIXTURE: unitsum

A self-test for Tare, not a case. `UNITSUM` is a small COBOL batch program written for the test suite: it reads shipped item lines (id, quantity, unit weight in kg with 3 decimals) and writes one total per id, with the weight in kg and in pounds. The pounds `COMPUTE` has no `ROUNDED` phrase, so it truncates.

- `mainframe/`: the program, its copybooks and the 10-record input (`data/items.txt`).
- `tare.json`: the files, the job step (with a PARM), the record layouts and two declared sides.
- `ports/exact/`: a Java port that truncates like the COBOL. `ports/halfup/`: a Java port that rounds the pounds half-up.
- `fixtures/answer_key/`: written by `python -m tare answer-key`. `fixtures/sides/`: written by `python -m tare reproduce --record`.

Run from this folder with the repository root on `PYTHONPATH`, for example `PYTHONPATH=../.. python -m tare reproduce --offline`.
