# Case: US Medicare hospice pricing, the FY2021.0 Hospice Pricer

The Centers for Medicare & Medicaid Services priced Medicare hospice claims with a mainframe COBOL program until it moved all ten of its pricers to Java. Tare runs the original COBOL unmodified under GnuCOBOL over 5,000 claims **constructed from public CMS tables**, and weighs two Java ports against it record by record, field by field.

| Side | What it is | Verdict |
|---|---|---|
| answer key | `HOSDR210` then `HOSPR210`, the FY2021.0 Hospice Pricer, from CMS's FY2021 mainframe release on [cms.gov](https://www.cms.gov/files/zip/fy-20210-hospice-mf-software-v210-claims-dated-100120-093021-posted-11172020.zip), sha256 `4b80ad69…` | |
| `cms-java` | CMS's own Java migration, Hospice Pricer 2.5.1 (executable JAR, sha256 `8463ea46…`), from [cms.gov/pricersourcecodesoftware](https://www.cms.gov/pricersourcecodesoftware); a FOIA release with no licence file | red, 140 of 5,000 |
| `java-ai` | [rcaran/hospice-cms-pricer-java](https://github.com/rcaran/hospice-cms-pricer-java) @ `6558476`, the published AI-assisted port; no licence file | red, 270 of 5,000 |
| `java-ai-fixed` | the same commit with the five line edits of `sides/ai_port_fixes.json` applied in a build copy | balanced, 0 of 5,000 |

Each claim is one 315-byte input record (copybook `BILL-315-DATA`, `HOSPR210.cbl:246`) and one 315-byte output record: the same record with the pricer filling in fourteen fields. The weigh compares all fourteen: the claim total, the four per-level-of-care payments, the seven end-of-life add-on payments, the return code and the two routine-home-care day counts. Amounts are whole cents, as the COBOL holds them (`PIC 9(06)V99`).

Every number below was measured by the command shown beside it. The run report holds the full output.

## What differs, and why

**`cms-java`: 140 of 5,000 claims differ, the total field only, one cent each, $1.40 in total.** Every line payment matches the COBOL; the claim total does not, because CMS's Java adds the *unrounded* per-level rates and rounds once at the end (`CalculateFinalPayments.java:36-43`), where the COBOL adds the per-level amounts it has already rounded into `WRK-PAY-RATE1` to `WRK-PAY-RATE4`, each `PIC 9(06)V9(02)` (`HOSPR210.cbl:5857-5862` and `:206-208`). On 140 claims the two orders land on different cents. Whether CMS meant to change this is unverified. The finding is the rounding order, not a missing amount. Claim C00002: lines $1,548.61 and $613.55, COBOL total $2,162.16, CMS's Java $2,162.15.

**`java-ai`: 270 of 5,000 claims differ, from three defects, all in continuous home care.** 776 of the 5,000 claims bill revenue code 0652 (continuous home care, CHC); 270 of those 776 come back different, and none of the 4,224 claims without CHC does.

1. **A short CHC day is counted as a routine home care day** (122 claims one high-rate day too many, 109 one low-rate day too many). A CHC line of fewer than 32 units is one CHC day, paid at the routine-home-care rate for that day; the COBOL paragraph `2021-V210-CHC-0652` computes `WRK-PAY-RATE2` and nothing else (`HOSPR210.cbl:6409-6411` and `:6418-6420`). The port also sets the flags and increments the counters that say the claim carries RHC days (`FullPricerStrategy.java:79-80` and `:85-86`). Only the RHC paragraphs write those: `BILL-HIGH-RHC-DAYS` at `HOSPR210.cbl:6036`, `BILL-LOW-RHC-DAYS` at `:5997`. Claim C00082 bills 7 RHC days and a 22-unit CHC day: COBOL 7 high-rate days, port 8.
2. **The return code follows** (15 claims, 10 returning 73 and 5 returning 75). The COBOL assigns 73, 74, 75 and 77 from the RHC day indicators alone (`V210-SUM-RHC-0651-RATE`, `HOSPR210.cbl:6274-6312`), so a claim billing nothing but a short CHC line comes back `00`. The port sets the same flags, so it answers 73 or 75. Claim C00033 bills one 25-unit CHC line: COBOL `00`, port `73`.
3. **The CHC hourly rate is rounded half-up instead of truncated** (39 claims, $0.39 in total). The COBOL computes `(((CHC-LS-RATE * wage index) + CHC-NLS-RATE) / 24) * (units / 4)` into a `PIC 9(06)V9(02)` field with `ROUNDED` (`HOSPR210.cbl:6430-6434`); the phrase applies to the store, not to the two divisions inside it, and a result with more decimal places than the receiving field is truncated unless the statement producing it says `ROUNDED` ([IBM Enterprise COBOL for z/OS, the ROUNDED phrase](https://www.ibm.com/docs/en/cobol-zos/6.3.0?topic=operations-rounded-phrase)). The port rounds the hourly rate half-up at ten places (`PaymentCalculator.java:81`). Claim C00408, 76 CHC units at wage index 1.3689: the exact product is $1,421.425679, the COBOL writes $1,421.42, the port $1,421.43.

`sides/ai_port_fixes.json` removes the four statements and changes the one division, by line number. With it applied the port balances on all 5,000 claims, field for field, so on this corpus those three points are the whole difference.

## Run it

From this folder, with the repository root on `PYTHONPATH`:

```
python -m tare reproduce --offline      # 2 s, Python only: the committed fixtures
python fetch.py                          # the three sources at pinned digests into cache/
python fetch.py --build                  # also builds both variants of the AI port with Maven
python -m tare reproduce                 # GnuCOBOL, a JDK >= 21 and Maven: everything fresh, 51 s
python -m tare explain --port java-ai --key C00082 --field high
```

`explain` prints both values, the COBOL statements that write the field, its `PIC`, and the port's own lines for the cause the case names in `tare.json`:

```
python -m tare explain --port java-ai       --key C00082 --field high     # the day count
python -m tare explain --port java-ai       --key C00033 --field rtc      # the return code
python -m tare explain --port java-ai       --key C00408 --field pay_chc  # the hourly rate
python -m tare explain --port cms-java      --key C00002 --field total    # CMS's own Java
```

`python -m tare reproduce` from the repository root opens on the France case; run it from this folder, or set `TARE_ROOT` to this folder.

Requirements: GnuCOBOL 3.2 (in Git Bash, `source /c/Tools/cobenv.sh` first), a JDK >= 21 (the AI port targets Java 21; `JAVA_HOME` or a JDK under the usual install roots), Maven 3.9 (`PATH`, `MAVEN_HOME` or `C:/Tools/apache-maven-*`), Python 3.13. The first `python fetch.py --build` downloads about 80 MB of Maven dependencies into `cache/m2`; `python fetch.py --clean` deletes `cache/build` and `cache/m2` once the fixtures are recorded.

## Files

- `fetch.py`: the three sources into `cache/` (git-ignored), each against a pinned digest. CMS's COBOL and the wage-index file, CMS's Java JAR and its source, and the AI port at its pinned commit. Neither the JAR nor the port's code is ever committed to this repository.
- `build_input.py`: builds `input/` from the fetched tables: 5,000 claims (seed 20260926), the 7,478-row wage-index file and one dummy provider record.
- `harness/HOSRUN.cbl`: our code, headed `HARNESS:`. It stands in for the wrapper JCL CMS ships but does not (`HOSOP210` in `TESTJCL`): it loads the wage-index and provider tables `HOSDR210` expects, reads each 315-byte bill, calls the unmodified `HOSDR210`, and writes the record back. The DD names are the ones `TESTJCL` uses.
- `sides/port_runner.py`: prices the answer key's claims through CMS's Java or through a Maven build of the AI port (published or patched), and writes each port's result back into a 315-byte record. Every field offset comes from `tare.json`; the runner holds none of its own.
- `sides/ai_port_fixes.json` and `sides/fix_port.py`: the three repairs as five edits by file and line number, against the pinned commit. Each edit names the SHA-256 of the line it expects, and `fix_port.py` changes nothing unless every expected line is in place (`python sides/fix_port.py --check`). No line of the port is stored here.
- `input/`: the corpus, committed. `input/billfile.txt` has sha256 `db7744b9063861c062a5f8e6a8c41e239e59a564d968d0d7cd50304e97f9603a`; the test suite pins it.
- `fixtures/`: the answer key (the COBOL's own output) and each side's recorded output.

## The input, honestly

`input/` is **constructed from public tables**, and no claim is a real claim. CMS publishes no test claims for hospice, so `build_input.py` builds them:

- **Dates and lengths** inside FY2021 (service dates 2020-10-01 to 2021-09-30), drawn from a fixed seed, so the corpus is the same bytes on every machine.
- **CBSA codes** from CMS's own FY2021 wage-index file `CBSA2021`: the 486 rows effective 20201001. Each claim's provider and beneficiary areas are drawn from them.
- **Revenue codes and unit limits** from the COBOL: 0651 routine home care in days, 0652 continuous home care in 15-minute units (up to 96), 0655 inpatient respite care, 0656 general inpatient care, and the end-of-life add-on units.
- **One dummy provider record**, built by `build_input.py` from the provider layout in `HOSDR210.cbl:550-560`: NPI 1234567890, CCN 341234, effective date 20201001, the rest of the 240 bytes blank. The two identifiers are the dummy test provider in the AI port's own test data (its `PROVFILE`), reused so that all three pricers price the same provider; no other byte comes from that file. The pricer reads the provider number to match the claim and the effective date to pick the record in force (`HOSDR210.cbl:951-970` and `:976`); it passes the record to nothing else (`HOSDR210.cbl:990`). No beneficiary data of any kind exists, here or in any source this case fetches.

**The mix is deliberately heavy in continuous home care: 776 of 5,000 claims, 15.5%, bill a CHC line.** In real hospice, routine home care is 98.8% of Medicare-covered hospice days and continuous home care is a small share ([MedPAC, March 2026 report to Congress, ch. 10](https://www.medpac.gov/wp-content/uploads/2026/03/Mar26_Ch10_MedPAC_Report_To_Congress_SEC.pdf), read 2026-09-26). So the honest rate for this case is **270 of 776 CHC claims, about 35%**, not a rate over all hospice claims. Quote that number, never 5.4% or anything else from the scout's notes: no such figure was measured here.

**The dollars are small.** The whole corpus is $15,441,527.20 of payments (mean $3,088.31 a claim), and the CMS Java side differs by $1.40 across 5,000 of them. This is a behaviour finding, not a money finding: a port that answers a cent differently, or counts a day the original never counted, is a port you cannot check by reading it.

**Scope.** No interest, no lending, no credit-card finance charge: the hospice pricer contains none of it, and this case adds none (a test in `tests/test_medicare_hospice.py` greps the case and both fetched ports for those words and finds nothing). The Medicare `PENALTY` payment reductions belong to other pricers; hospice has none. The MSA wage-index table is left empty, as the FY2021 release ships `CBSA2021` only; a claim dated before 2008 would find no wage index, and the input holds no such claim.

## Where each piece comes from, and under what licence

- **The COBOL** (`cache/cobol/`): CMS's FY2021.0 Hospice mainframe release, `HOSDR210.cbl`, `HOSPR210.cbl`, `HOSPRATE.cpy`, `CBSA2021`, `TESTJCL`, downloaded from cms.gov and pinned by the SHA-256 of the zip. A work of the U.S. Government, which 17 U.S.C. §105 places in the public domain; the release ships no licence file. CMS posts pricer source to fulfil Freedom of Information Act requests and for rate transparency, and its pricer page says: *As of January 2022, CMS no longer posts COBOL source code* (read 2026-09-26), which is why the digest is pinned rather than a URL alone. CMS also states it does not support running this software outside its own claims system.
- **`input/cbsafile.txt`** is CMS's `CBSA2021` verbatim, one row per line, padded to the 80 bytes the harness reads. The file ends with a single 0x1A end-of-file byte, which is not a row.
- **CMS's Java** (`cache/cms_java/`): the executable JAR and the source of the classes this case cites, from cms.gov, pinned by the SHA-256 of both the ZIP and the JAR. A FOIA transparency release with no licence file, so it is fetched at run time and never committed. Its own README says the Java was translated from the original COBOL listing.
- **The AI-assisted port** (`cache/repos/rcaran/`): [rcaran/hospice-cms-pricer-java](https://github.com/rcaran/hospice-cms-pricer-java) at `655847671859b67a188c5dae6a86c45a74bfa046`, one squashed commit dated 2026-06-05. **No licence file**: the GitHub API reports `licenseInfo: null`, so the code is fetched at run time and never committed. That it is AI-assisted is circumstantial, not declared: the tree ships `.cursor/`, `.windsurf/` and `.specs/` agent task files. Its README claims functional parity with the legacy batch pricer for FY1998 to FY2021; its own validation report says parity was confirmed on 10 decoded cases.
- **This case's own code** (`harness/`, `sides/port_runner.py`, `sides/fix_port.py`, `sides/ai_port_fixes.json`, `build_input.py`, `fetch.py`, `tare.json`, `input/provfile.txt`, the tests) is MIT, like the rest of this repository. `sides/ai_port_fixes.json` holds the two file paths, five line numbers, the SHA-256 digest of each expected line, and a 13-character argument fragment (`10, ROUNDING)`) with its replacement; it holds no line of the port. `input/provfile.txt` shares only the two dummy identifiers above with the port's test data.

## What Tare checks before it trusts a number

- **The answer key is sound or nothing is weighed.** Every numeric field of every output record must decode, and the output's claim id must read back as the input's, record for record (`echo` in `tare.json`). An unsound answer key stops the run.
- **The answer key is re-run and compared** with the committed fixture, byte for byte, whenever GnuCOBOL is present.
- **The record layout is the COBOL's**, field by field, with the offsets from `HOSPR210.cbl`'s copybook; the tests check the decisive lines the evidence rests on, in the fetched source.
- **The repairs are checked against the pinned commit**: every edited line must match its SHA-256 before any byte of the build copy changes, and the build fails if the edits changed nothing.
- **The corpus is pinned by SHA-256**, so a regeneration that moves it fails a test instead of quietly changing every number here.
