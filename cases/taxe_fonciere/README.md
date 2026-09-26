# Case: French property tax, 2018 built-property calculator

The French tax administration's (DGFiP) COBOL that computes the 2018 property tax on buildings, run unmodified under GnuCOBOL on real public data, is the answer key. A public Java port of it, written with an AI coding agent, passes its own built-property tests (4 of 4) and gets the total due wrong for every commune of the demo slice.

| Side | What it is | Verdict |
|---|---|---|
| answer key | `CTXTA3B` → `EFITA3B8`, rates read by `EFITAUX2`; [etalab/taxe-fonciere](https://github.com/etalab/taxe-fonciere) @ `6bd40b2`, CeCILL-2.1 | |
| `java-ai` | [omnipede/taxe-fonciere](https://github.com/omnipede/taxe-fonciere) @ `5124d1c`, folder `taxe-fonciere-java`: one commit by hgseo-cubox-ai, co-authored by Qwen-Coder; CeCILL-2.1 | red |
| `java-ai-fixed` | the same port with two fixes, applied by `sides/java_port.py` in a build copy | balanced |

The two defects in `java-ai`:
- the 3% fee tier is charged the 8% tier's rates (8% and 4.4%) and the 8% tier the 3% tier's (3% and 1%);
- the total before fees leaves out the household-waste tax.

Each bill is one 600-byte input record (copybook `XCOMBAT`) and one 600-byte output record (copybook `XRETB`). The weigh compares all 28 amounts of the output record, the six waste-tax zone codes and the two return codes. Amounts are whole euros.

## Run it

From this folder, with the repository root on `PYTHONPATH`:

```
python fetch.py                                          # COBOL and Java port at pinned commits, into cache/
PYTHONPATH=../.. python -m tare reproduce --offline      # seconds, Python only: the committed fixtures
PYTHONPATH=../.. python -m tare reproduce                # GnuCOBOL, a JDK >= 17 and Maven: everything fresh
PYTHONPATH=../.. python -m tare explain --key 010001 --field tctdu --port java-ai
```

The demo slice is the 408 communes of the Ain département (01), one bill per commune. The first `reproduce` builds each Java side with Maven (about a minute); later runs take about 30 seconds.

The full run covers the 35,389 communes of REI 2018:

```
python fetch.py --full                                   # downloads REI 2018 (133 MB), converts it, writes full/
cd full
PYTHONPATH=../../.. python -m tare answer-key
PYTHONPATH=../../.. python -m tare reproduce
```

`--full` needs `openpyxl` to read the published spreadsheet.

## Files

- `fetch.py`: clones the two repositories at their pinned commits into `cache/` (git-ignored) and exports only the built-property COBOL files to `cache/cobol/`. The CeCILL-2.1 code is never committed to this MIT repository.
- `build_input.py`: builds `rates.txt` and `bills.txt` from REI 2018. Each commune's net bases and voted rates make one bill.
- `harness/LOADTAU.cbl`, `harness/TFBATCH.cbl`: our code, each headed `HARNESS:`. `LOADTAU` loads the rate file with the original record copybooks; `TFBATCH` stands in for the calling system and calls the unmodified `CTXTA3B` once per bill.
- `sides/java_port.py`, `sides/java/TareJavaSide.java`: build the port with Maven and run it on the same input. They write its results in the COBOL's output layout. The bill's identity block is copied from the input, because the port keeps the commune code as an integer. Every amount comes from the port.
- `input/`: the demo slice's input, derived from REI 2018.
- `fixtures/`: the answer key and both sides' recorded output for the demo slice.

## Data

`input/` is derived from **REI 2018** ("Impôts locaux : fichier de recensement des éléments d'imposition à la fiscalité directe locale"), published by the Direction générale des Finances publiques on [data.gouv.fr](https://www.data.gouv.fr/datasets/impots-locaux-fichier-de-recensement-des-elements-dimposition-a-la-fiscalite-directe-locale-rei-4). The file is `REI_2018.xlsx`, dated 2021-12-28, in [REI-2018-fichier-notice-trace.zip](https://data.economie.gouv.fr/api/v2/catalog/datasets/impots-locaux-fichier-de-recensement-des-elements-dimposition-a-la-fiscalite-dir/attachments/rei_2018_fichier_notice_trace_zip). It is published under the [Licence Ouverte / Open Licence v2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence), which allows reuse, including commercial reuse, with attribution.

REI holds commune-level totals and rates only, with no personal data. `input/` keeps the rows of the Ain communes, reshaped into the calculator's input records by `build_input.py`. Rebuild it with `python build_input.py cache/rei/REI_2018.csv --out input --dep 01` after `python fetch.py --full`.
