# Act two: US Medicare hospice, in one page

For the film and the site. Every number here was measured by a command in the run report; the file and
line each claim rests on is named so a judge can check it in a minute.

## The three numbers, with their denominators

| | What was measured | Denominator |
|---|---|---|
| **270 of 5,000** | claims the AI-assisted Java port prices differently from CMS's own COBOL, field for field | the 5,000 constructed claims of `cases/medicare_hospice` (seed 20260926) |
| **270 of 776, about 35%** | the same, over the claims that bill continuous home care (revenue code 0652) | the 776 of 5,000 claims that bill a CHC line; **0 of the other 4,224** |
| **140 of 5,000, one cent each** | claims CMS's own Java migration prices differently: the claim total only, every line payment identical | the same 5,000 claims; $1.40 in total |

The three defects, one example claim each, both values:

| Claim | Field | COBOL | Java port | What the port does differently |
|---|---|---|---|---|
| `C00082` | high-rate routine home care days | **7** | 8 | bills 7 RHC days and one short CHC day; the port counts the CHC day as an RHC day too |
| `C00033` | return code | **00** | 73 | bills only a short CHC line; the port calls it low-rate routine home care, because of the line above |
| `C00408` | continuous home care line payment | **$1,421.42** | $1,421.43 | 76 CHC units; the exact product is $1,421.425679 and the port rounds it up |
| `C00002` | claim total | **$2,162.16** | $2,162.15 | CMS's own Java: $1,548.61 + $613.55, added unrounded and rounded once at the end |

With the five line edits of `sides/ai_port_fixes.json` applied, the AI port balances on all 5,000 claims, field for field.

## Why it matters, in MedPAC's own numbers

"In 2024, Medicare's hospice prospective payment system (PPS) paid about **$28.3 billion** for hospice
services for more than **1.8 million** Medicare beneficiaries" from about 6,700 providers.
[MedPAC, March 2026 report to Congress, chapter 10](https://www.medpac.gov/wp-content/uploads/2026/03/Mar26_Ch10_MedPAC_Report_To_Congress_SEC.pdf)
(read 2026-09-26; the same chapter: routine home care is 98.8% of Medicare-covered hospice days).

The finding is not $1.40. It is that both Java implementations of the same payment rules disagree with
the original program on the same 5,000 claims, and that the AI port's parity claim rests on 10 decoded
cases (its own validation report, `docs/validacao-cobol-java.md`). Tare replays every claim against the
original program and names the COBOL line and the port line behind each difference.

## Three candidate lines, in plain words

1. **An AI-assisted Java rewrite of Medicare's hospice pricer says it matches the original. We ran 5,000 claims through both. One in three of the continuous-home-care claims came back different.**
2. **Even Medicare's own Java version of its hospice pricer misses the original's total by a cent on 140 of 5,000 claims, because it rounds after adding instead of before.**
3. **We let CMS's FY2021 COBOL check the AI-assisted rewrite, claim by claim: 270 differences, every one traced to one of three defects, each a line or two of Java. Three small repairs and the two agree on all 5,000.**

## What to say if asked

- **Are these real claims?** No. CMS publishes no hospice test claims, so the 5,000 are constructed from
  public CMS tables (the FY2021 wage-index file, the revenue codes and unit limits in the COBOL) with a
  fixed seed. No person's data exists. 15.5% of them bill continuous home care, where real hospice is
  98.8% routine home care, which is why the honest rate is 35% of CHC claims and not a rate over all
  hospice claims.
- **Is the cent CMS's fault?** The finding is a difference, not a verdict. The COBOL is the answer key here;
  the difference is the order of rounding, and every line payment agrees.
- **Is the port bad?** It is a public port with no licence file, AI-assisted judging by the agent files
  it ships (`.cursor/`, `.windsurf/`, `.specs/`), and its README claims functional parity for FY1998 to
  FY2021. On these claims three specific statements differ from the COBOL, each a line or two, each with
  the COBOL paragraph it contradicts.
- **Where is the code?** `cases/medicare_hospice/`. `python -m tare reproduce --offline` reprints the
  three verdicts in two seconds from the committed fixtures; the full run rebuilds the COBOL and both
  Java ports in about two minutes from a cold cache.
