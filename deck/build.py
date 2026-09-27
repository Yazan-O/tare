"""Render Tare's cover and six-slide deck with Playwright, in the Parity Receipt page's identity.

Every number is read at build time from the case's committed data and two run logs, then checked:
each number that appears on a rendered slide must be a traced fact or a listed constant.

  deck/cover.png              1920x1080
  deck/cover_1280x720.png     1280x720
  deck/slides/slide_<n>.png   1920x1080, n = 1..6
  deck/tare_slides.pdf        the six slides, one page each
  deck/contact_sheet.png      cover and slides at a glance
  deck/facts.json             every traced number with its source

Usage (from the repository root):
  python deck/build.py --tests-log <RUN_LOG.txt with the port's Maven test lines> --gate-log <hero-loop transcript>
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

DECK = Path(__file__).resolve().parent
TARE = DECK.parent
SITE = TARE / "site"
CASE = TARE / "cases" / "taxe_fonciere"
PROJECT = TARE.parent

# Slide 3: crops of the owner's Bob IDE session (bob_sessions/, site/tools/crop_bob_shots.py).
BOB_SHOTS = [
    {"src": (SITE / "dist" / "img" / "bob_1_blocked.png").as_uri(), "caption": "Bob's first commit: no weigh on record"},
    {"src": (SITE / "dist" / "img" / "bob_3_stale_edit.png").as_uri(), "caption": "Edited after the weigh: refused again"},
]
sys.path.insert(0, str(SITE / "tools"))
from medicare_facts import facts as medicare_facts  # noqa: E402

SITE_URL = "https://yazan-o.github.io/tare/"
REPO_URL = "https://github.com/Yazan-O/tare"
HERO = "01001"
AI, FX = "java-ai", "java-ai-fixed"


# ---------------------------------------------------------------- facts

def fmt(n: int) -> str:
    return f"{n:,}"


def records(path: Path) -> dict:
    return {r["commune"]: r for r in json.loads(path.read_text(encoding="utf-8"))["files"]["retours"]}


def gather(tests_log: Path, gate_log: Path, take_log: Path) -> tuple[dict, dict]:
    F, src = {}, {}

    def put(key, value, source):
        F[key] = value
        src[key] = source

    # the port's own built-property tests
    log = tests_log.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+).*?BuiltPropertyCalculatorTest", log)
    if not m:
        raise SystemExit(f"no BuiltPropertyCalculatorTest line in {tests_log}")
    run, fail, err, skip = map(int, m.groups())
    put("tests_run", run, f"{tests_log.name}: '{m.group(0)[:60]}...'")
    put("tests_passed", run - fail - err - skip, f"{tests_log.name}: run - failures - errors - skipped")
    m = re.search(r"5124d1c \S+ \S+ .*?co-author: (Qwen-Coder)", log)
    if not m:
        raise SystemExit(f"no Qwen-Coder co-author line for 5124d1c in {tests_log}")
    put("coauthor", m.group(1), f"{tests_log.name}: git log of the port at 5124d1c")

    # the demo slice (Ain), from the committed fixtures, as site/tools/build_site.py counts it
    ak = records(CASE / "fixtures" / "answer_key" / "records.json")
    put("ain_records", len(ak), "cases/taxe_fonciere/fixtures/answer_key/records.json")
    for side, key in ((AI, "ain_ai_differ"), (FX, "ain_fx_differ")):
        s = records(CASE / "fixtures" / "sides" / side / "records.json")
        assert set(s) == set(ak)
        put(key, sum(any(s[k][f] != ak[k][f] for f in ak[k]) for k in ak),
            f"cases/taxe_fonciere/fixtures/sides/{side}/records.json against the answer key")

    # the national replay
    D = json.loads((SITE / "data" / "communes.json").read_text(encoding="utf-8"))
    put("fr_records", D["records"], "site/data/communes.json: records")
    put("fr_ai_differ", D["sides"][AI]["records_differ"], "site/data/communes.json: sides.java-ai.records_differ")
    put("fr_fx_differ", D["sides"][FX]["records_differ"], "site/data/communes.json: sides.java-ai-fixed.records_differ")
    ain = [i for i, c in enumerate(D["insee"]) if c.startswith("01") and not c.startswith("97")]
    assert len(ain) == F["ain_records"], (len(ain), F["ain_records"])
    assert sum(D["sides"][AI]["ndiff"][i] > 0 for i in ain) == F["ain_ai_differ"]
    assert sum(D["sides"][FX]["ndiff"][i] > 0 for i in ain) == F["ain_fx_differ"]

    # commune record 01001
    i = D["insee"].index(HERO)
    put("hero_name", D["name"][i], "site/data/communes.json: name")
    hero_rows = []
    for f in ("tcthfr", "mfa300", "mfn300", "tctfra", "tctdu"):
        a = D["answer_key"][f][i]
        col = D["sides"][AI]["values"].get(f)
        p = col[i] if col else a
        put(f"hero_{f}_cobol", a, f"site/data/communes.json: answer_key.{f}[{HERO}]")
        put(f"hero_{f}_port", p, f"site/data/communes.json: sides.java-ai.values.{f}[{HERO}]")
        hero_rows.append(f)
    fx_key = HERO[:2] + "0" + HERO[2:]   # the fixtures key: département, "0", commune (010001)
    assert int(ak[fx_key]["tctdu"]) == F["hero_tctdu_cobol"]
    assert int(records(CASE / "fixtures" / "sides" / AI / "records.json")[fx_key]["tctdu"]) == F["hero_tctdu_port"]
    F["_hero_rows"] = hero_rows

    # the map: the communes the boundary file draws, and the drawn records that differ
    M = json.loads((SITE / "data" / "map.json").read_text(encoding="utf-8"))
    idx = {c: k for k, c in enumerate(D["insee"])}
    drawn = [idx[c] for c in M["communes"] if c in idx]
    put("map_drawn", len(drawn), "site/data/map.json communes present in communes.json (as app.js draws them)")
    put("map_ai_red", sum(D["sides"][AI]["ndiff"][k] > 0 for k in drawn), "drawn communes with java-ai ndiff > 0")
    put("map_fx_red", sum(D["sides"][FX]["ndiff"][k] > 0 for k in drawn), "drawn communes with java-ai-fixed ndiff > 0")

    # the gate's messages, as Tare printed them in the hero-loop run on the Ain slice
    g = gate_log.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"TARE: blocked\. (\d+) of (\d+) records differ from the answer key", g)
    if not m:
        raise SystemExit(f"no blocked message in {gate_log}")
    assert (int(m.group(1)), int(m.group(2))) == (F["ain_ai_differ"], F["ain_records"])
    put("gate_blocked", f"TARE: blocked. {m.group(1)} of {m.group(2)} records differ from the answer key",
        f"{gate_log.name}: hook exit 2")
    m = re.search(r"TARE BALANCED\s+local vs answer_key: (\d+) of (\d+) records balance", g)
    if not m:
        raise SystemExit(f"no balanced line in {gate_log}")
    assert int(m.group(1)) == int(m.group(2)) == F["ain_records"]
    put("gate_balanced", f"TARE BALANCED: {m.group(1)} of {m.group(2)} records balance", f"{gate_log.name}: weigh exit 0")
    if "[hook exit 0]" not in g or "HERO LOOP: PASS" not in g:
        raise SystemExit(f"{gate_log} does not end in a passing loop")

    # the owner's IBM Bob IDE take, as verified frame by frame on the recording (the film's footage map)
    t = take_log.read_text(encoding="utf-8", errors="replace")
    for key, pat in (("take_still_red", r"Still (\d+) records differing"),
                     ("take_coins", r"live coin counter reads \*?\*?(\d+\.\d+)"),
                     ("take_commit", r"Committed at (\w{7})")):
        m = re.search(pat, t)
        if not m:
            raise SystemExit(f"no {key} ({pat}) in {take_log}")
        put(key, int(m.group(1)) if m.group(1).isdigit() else m.group(1), f"{take_log.name}: '{m.group(0)}'")
    m = re.search(r"BALANCED \S+ (\d+) of (\d+) records balance", t)
    if not m or int(m.group(1)) != F["ain_records"]:
        raise SystemExit(f"no balanced line for {F['ain_records']} records in {take_log}")
    for key, pat in (("take_block_1", r'"(TARE: blocked\. No weigh on record[^"]*)"'),
                     ("take_block_2", r'"(TARE: blocked\. The port changed after the last weigh[^"]*)"')):
        m = re.search(pat, t)
        if not m:
            raise SystemExit(f"no {key} in {take_log}")
        put(key, m.group(1), f"{take_log.name}, the hook's string at tare/gate.py")

    for k, (v, s) in medicare_facts().items():
        put(f"med_{k}", v, s)

    run = (SITE / "dist" / "data" / "run.js").read_text(encoding="utf-8")
    RUN = json.loads(run[run.index("=") + 1:].rstrip().rstrip(";"))
    F["_scale"] = [{"src": (SITE / "dist" / s["src"]).as_uri(), "caption": s["caption"]} for s in RUN["scale"]]
    return F, src


# ---------------------------------------------------------------- pages

PEN = ('<svg viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true"><path d="M8 22 C 6 8, 40 3, 62 4 '
       'C 88 5, 99 12, 96 23 C 93 34, 60 38, 36 36 C 14 34, 3 28, 9 15 C 12 10, 20 7, 27 6"/></svg>')

LABEL = {"tcthfr": "Total before fees", "mfa300": "3% tier: assessment fee", "mfn300": "3% tier: relief fee",
         "tctfra": "Fees total", "tctdu": "Total due"}


def css() -> str:
    fonts = SITE / "dist" / "fonts"
    return f"""
@font-face{{font-family:"Archivo";src:url({(fonts / 'Archivo.woff2').as_uri()}) format("woff2");font-weight:100 900}}
@font-face{{font-family:"JetBrains Mono";src:url({(fonts / 'JetBrainsMono.woff2').as_uri()}) format("woff2");font-weight:100 800}}
:root{{--bg:#FEFEFE;--ink:#1E1E1E;--ink-2:rgba(30,30,30,.62);--line:#DEDEDE;--code-bg:#F3F3F3;--red:#C8102E;
--font:"Archivo","Helvetica Neue",Helvetica,Arial,sans-serif;--mono:"JetBrains Mono",ui-monospace,Consolas,monospace}}
@page{{size:1920px 1080px;margin:0}}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:var(--bg);color:var(--ink);font-family:var(--font)}}
.slide{{width:1920px;height:1080px;position:relative;overflow:hidden;background:var(--bg);padding:64px 120px 0;break-after:page}}
.mono,.num{{font-family:var(--mono)}}
.red{{color:var(--red)}} .muted{{color:var(--ink-2)}}
.top{{display:flex;justify-content:space-between;font:500 22px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-2);padding-bottom:18px;border-bottom:1px solid var(--ink)}}
.label{{font:500 22px/1.35 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--ink-2)}}
h1{{font-weight:500;font-size:76px;line-height:1.04;letter-spacing:-.02em;margin:52px 0 0;max-width:1560px;text-wrap:balance}}
.pen{{position:relative;display:inline-block}}
.pen svg{{position:absolute;left:-11%;top:-24%;width:122%;height:148%;overflow:visible}}
.pen path{{fill:none;stroke:var(--red);stroke-width:2.4;stroke-linecap:round;vector-effect:non-scaling-stroke}}
table{{border-collapse:collapse;width:100%}}
th{{font:500 20px/1.3 var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--ink-2);text-align:right;padding:0 0 14px 20px}}
th:first-child{{text-align:left;padding-left:0}}
td{{border-top:1px solid var(--line);padding:16px 0 16px 20px;text-align:right;font:400 32px/1.2 var(--mono);white-space:nowrap}}
td:first-child{{text-align:left;padding-left:0;font:500 28px/1.2 var(--font);white-space:normal}}
tr.total td{{border-top:1px solid var(--ink);font-weight:500}} tr.total td:first-child{{font-weight:700}}
td.diff{{color:var(--red)}}
pre{{background:var(--code-bg);border:1px solid var(--line);padding:22px 26px;font:400 28px/1.5 var(--mono);white-space:pre-wrap}}
figure img{{display:block;width:100%;border:1px solid var(--line)}}
figcaption{{font-size:20px;line-height:1.35;color:var(--ink-2);margin-top:12px}}

/* cover */
.cover{{padding:96px 120px 0}}
.cv-grid{{display:grid;grid-template-columns:1060px 1fr;gap:80px;margin-top:0;align-items:start}}
.cv-tests{{font:500 180px/1 var(--font);letter-spacing:-.03em}}
.cv-sub{{font:400 34px/1.3 var(--mono);color:var(--ink-2);margin-top:22px}}
.cv-rule{{border-top:1px solid var(--ink);margin:56px 0 44px}}
.cv-big{{font:500 180px/1 var(--mono);letter-spacing:-.04em;color:var(--red)}}
.cv-big2{{font:500 42px/1.15 var(--font);letter-spacing:-.01em;margin-top:24px;white-space:nowrap}}
.slip{{margin-top:6px;border-top:1px solid var(--ink)}}
.slip .label{{padding:18px 0 8px}}
.slip-row{{border-top:1px solid var(--line);padding:26px 0 34px}}
.slip-row:first-of-type{{border-top:0}}
.slip-row .who{{display:block;font:500 26px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--ink-2)}}
.slip-row .amt{{display:inline-block;font:500 124px/1 var(--mono);letter-spacing:-.04em;margin-top:22px}}
.cv-foot{{position:absolute;left:120px;right:120px;bottom:80px;display:flex;justify-content:space-between;align-items:baseline;
  border-top:1px solid var(--line);padding-top:26px}}
.cv-name{{font:500 72px/1 var(--font);letter-spacing:-.01em}} .cv-name b{{font-weight:700}}
.cv-line{{font:400 34px/1 var(--mono);color:var(--ink-2)}}

/* slide 1 */
.s1{{display:grid;grid-template-columns:720px 1fr;gap:110px;margin-top:64px}}
.s1 .big{{font:500 112px/1 var(--mono);white-space:nowrap;letter-spacing:-.04em;color:var(--red);margin-top:18px}}
.s1 .say{{font:500 40px/1.15 var(--font);margin-top:10px}}
.s1 .pass{{font:500 96px/1 var(--font);letter-spacing:-.02em;margin-top:16px}}
.s1 .rule{{border-top:1px solid var(--line);margin:40px 0 34px}}

/* slide 2 */
.rows{{margin-top:60px}}
.rows .r{{display:grid;grid-template-columns:360px 1fr;gap:40px;border-top:1px solid var(--line);padding:22px 0}}
.rows .r:last-child{{border-bottom:1px solid var(--line)}}
.rows .r .label{{padding-top:8px}}
.rows .r p{{font:500 34px/1.25 var(--font);max-width:1240px}}

/* slide 3 */
.flow{{display:grid;grid-template-columns:repeat(6,1fr);margin-top:48px;border-top:2px solid var(--ink)}}
.flow .st{{padding:20px 22px 0 0;border-right:1px solid var(--line);margin-right:22px}}
.flow .st:last-child{{border-right:0;margin-right:0}}
.flow .n{{font:500 22px/1 var(--mono);color:var(--ink-2)}}
.flow .t{{font:500 30px/1.12 var(--font);margin-top:12px;min-height:68px}}
.flow .d{{font:400 19px/1.4 var(--mono);margin-top:10px}}
.flow .d+.d{{border-top:1px solid var(--line);padding-top:8px;margin-top:8px}}
.shots{{display:grid;grid-template-columns:repeat(2,820px);gap:40px;margin-top:30px;align-items:start}}
.shots img{{width:820px;height:auto}}
.cap3{{position:absolute;left:120px;bottom:48px;font:400 22px/1.3 var(--mono);color:var(--ink-2)}}

/* slide 5, act two */
table.med{{margin-top:56px}}
table.med td{{padding:26px 0 26px 20px;vertical-align:baseline}}
table.med td:first-child{{width:560px}}
table.med td .code{{display:block;font:400 20px/1.3 var(--mono);color:var(--ink-2);margin-top:6px}}
table.med td .of{{font-size:.55em;color:var(--ink-2)}}
table.med td:nth-child(2){{font-size:60px;letter-spacing:-.03em;width:380px}}
table.med td.what{{text-align:left;white-space:normal;font:400 26px/1.35 var(--font)}}
.mednote{{position:absolute;left:120px;right:120px;bottom:72px;border-top:1px solid var(--line);padding-top:22px}}
.mednote p{{font:400 24px/1.4 var(--font);color:var(--ink-2);max-width:1500px}}

/* slide 4 */
.s4{{display:grid;grid-template-columns:600px 600px 1fr;gap:56px;margin-top:28px}}
.s4 canvas{{width:600px;height:470px;display:block}}
.s4 .cnt{{border-top:1px solid var(--ink);padding-top:14px;margin-top:6px}}
.s4 .cnt .big{{font:500 60px/1 var(--mono);letter-spacing:-.03em;margin-top:8px}}
.s4 .cnt .of{{font-size:.55em;color:var(--ink-2)}}
.s4 .cnt .sub{{font:400 22px/1.35 var(--mono);margin-top:8px}}
.s4 .notes p{{font-size:22px;line-height:1.4;color:var(--ink-2);border-top:1px solid var(--line);padding:16px 0}}
.s4 .key{{display:flex;gap:14px;align-items:center;font:500 24px/1 var(--font);color:var(--ink);padding:12px 0}}
.s4 .sw{{width:22px;height:22px;flex:0 0 22px}}

/* slide 5 */
.s5{{display:grid;grid-template-columns:1fr 700px;gap:80px;margin-top:64px}}
.s5 .r{{border-top:1px solid var(--line);padding:26px 0}}
.s5 .url{{font:500 48px/1.2 var(--mono);letter-spacing:-.01em;margin-top:12px}}
.s5 pre{{margin-top:16px}}
.slide .foot{{position:absolute;left:120px;right:120px;bottom:72px;display:flex;justify-content:space-between;align-items:baseline;
  border-top:1px solid var(--line);padding-top:24px}}
.slide .foot .a{{font:500 44px/1 var(--font)}} .slide .foot .b{{font:400 30px/1 var(--mono);color:var(--ink-2)}}
"""


SLIDES = 6


def top(left: str, n: int) -> str:
    return f'<div class="top"><span>{left}</span><span>{n} / {SLIDES}</span></div>'


def cover(F) -> str:
    return f"""<section class="slide cover">
<div class="cv-grid">
  <div>
    <p class="cv-tests">Tests passed.</p>
    <p class="cv-sub">The AI-written port's own tests: {F['tests_passed']} of {F['tests_run']}</p>
    <div class="cv-rule"></div>
    <p class="cv-big">{F['ain_ai_differ']} of {F['ain_records']}</p>
    <p class="cv-big2">commune records differ from the original COBOL</p>
  </div>
  <div class="slip">
    <p class="label">Commune {HERO} · total due, €</p>
    <div class="slip-row"><span class="who">COBOL</span><span class="amt">{fmt(F['hero_tctdu_cobol'])}</span></div>
    <div class="slip-row"><span class="who">AI-written port</span><span class="amt red pen">{fmt(F['hero_tctdu_port'])}{PEN}</span></div>
  </div>
</div>
<div class="cv-foot"><span class="cv-name"><b>Tare</b> · a plugin for IBM Bob</span><span class="cv-line">Close enough doesn't commit.</span></div>
</section>"""


def slide1(F) -> str:
    rows = ""
    for f in F["_hero_rows"]:
        a, p = F[f"hero_{f}_cobol"], F[f"hero_{f}_port"]
        d = p - a
        tot = f == "tctdu"
        pv = f'<span class="pen">{fmt(p)}{PEN}</span>' if tot and d else fmt(p)
        dc = ' class="diff"' if d else ""
        ds = ("+" if d > 0 else "−") + fmt(abs(d)) if d else "0"
        rows += (f'<tr{" class=total" if tot else ""}><td>{LABEL[f]}</td><td>{fmt(a)}</td>'
                 f'<td{dc}>{pv}</td><td{dc}>{ds}</td></tr>')
    return f"""<section class="slide">{top("Tare · the catch", 1)}
<h1>The AI-written port passes its own tests. The original COBOL disagrees on every Ain commune record.</h1>
<div class="s1">
  <div>
    <p class="label">The port's own built-property tests</p>
    <p class="pass">Tests passed.</p>
    <p class="say muted mono" style="font-size:30px;font-weight:400">{F['tests_passed']} of {F['tests_run']} · BuiltPropertyCalculatorTest</p>
    <div class="rule"></div>
    <p class="label">Replayed against the unmodified COBOL</p>
    <p class="big">{F['ain_ai_differ']} of {F['ain_records']}</p>
    <p class="say">commune records of Ain differ</p>
  </div>
  <div>
    <p class="label" style="margin-bottom:26px">Commune record {HERO} · {html.escape(F['hero_name'])} · euros</p>
    <table><thead><tr><th>Field</th><th>COBOL</th><th>AI port</th><th>Port − COBOL</th></tr></thead><tbody>{rows}</tbody></table>
  </div>
</div></section>"""


def slide2(F) -> str:
    rows = [
        ("The engineer", "A public-sector modernization engineer, signing off the Java port meant to replace France's 2018 property-tax COBOL."),
        ("The port", f"Published on GitHub; one commit co-authored by the {F['coauthor']} agent."),
        ("Its evidence", f"Its own built-property tests: {F['tests_passed']} of {F['tests_run']} pass."),
        ("The answer key", "The tax administration's COBOL, unmodified under GnuCOBOL, replayed on public 2018 commune statistics."),
        ("The sign-off", "Tare lets the commit through only when every commune record balances."),
    ]
    body = "".join(f'<div class="r"><span class="label">{a}</span><p>{b}</p></div>' for a, b in rows)
    return f"""<section class="slide">{top("Tare · who signs off", 2)}
<h1>Someone has to sign off a port an AI wrote. Its own tests are not the answer key.</h1>
<div class="rows">{body}</div></section>"""


def slide3(F) -> str:
    steps = [
        ("Commit blocked", ['<span class="red">No weigh on record</span>']),
        ("Weigh", [f'<span class="red">{F["ain_ai_differ"]} of {F["ain_records"]} records differ</span>']),
        ("Two subagents, in parallel", ["fee fields", "total fields"]),
        ("Fee fix, commit", ['<span class="red">blocked again: edited after the weigh</span>']),
        ("First totals fix", [f'<span class="red">wrong term: {F["take_still_red"]} still differ</span>', "explain, then the COBOL line"]),
        ("Waste tax added", [f'{F["ain_records"]} of {F["ain_records"]} balance', f'committed {F["take_commit"]}']),
    ]
    flow = "".join(f'<div class="st"><p class="n">{k}</p><p class="t">{t}</p>' +
                   "".join(f'<p class="d">{d}</p>' for d in ds) + "</div>" for k, (t, ds) in enumerate(steps, 1))
    figs = "".join(f'<figure><img src="{html.escape(s["src"])}" alt=""><figcaption>{html.escape(s["caption"])}</figcaption></figure>'
                   for s in BOB_SHOTS)
    return f"""<section class="slide">{top("Tare · recorded in IBM Bob IDE", 3)}
<h1>Bob's commit stayed blocked until the port balanced on every record.</h1>
<div class="flow">{flow}</div>
<div class="shots">{figs}</div>
<p class="cap3">The owner's IBM Bob IDE session, 2026-09-26: one prompt, {F['take_coins']} Bobcoins, stills from the screen recording.</p></section>"""


def slide_medicare(F) -> str:
    def v(k):
        return F[f"med_{k}"]
    C = v("claims")
    rows = [("CMS's own Java migration", "Hospice Pricer 2.5.1", v("cms_java_differ"),
             f"the claim total only, one cent each: it rounds after adding, the COBOL before", True),
            ("AI-assisted port", "its README claims functional parity", v("java_ai_differ"),
             f"{fmt(v('java_ai_differ_chc'))} of {fmt(v('chc_claims'))} continuous-home-care claims; "
             f"{fmt(v('java_ai_differ_non_chc'))} of the other {fmt(v('non_chc_claims'))}", True),
            ("The same port, three repairs", "five line edits", v("java_ai_fixed_differ"), "every field equal", False)]
    body = "".join(f'<tr><td>{a}<span class="code">{b}</span></td><td class="{"diff" if red and n else ""}">{fmt(n)}'
                   f'<span class="of"> of {fmt(C)}</span></td><td class="what">{w}</td></tr>' for a, b, n, w, red in rows)
    return f"""<section class="slide">{top("Tare · act two, US Medicare hospice", 5)}
<h1>Another agency's COBOL, the same test: CMS's own hospice pricer is the answer key.</h1>
<table class="med"><thead><tr><th>Java port, weighed against CMS's FY2021 COBOL</th><th>Claims that differ</th><th style="text-align:left">Where</th></tr></thead><tbody>{body}</tbody></table>
<div class="mednote">
  <p>{fmt(C)} claims constructed from public CMS tables, seed-fixed, no person's data. For scale, Medicare's hospice payment system paid about {v('medpac_hospice_2024')} in 2024 (MedPAC, March 2026, chapter 10).</p>
</div></section>"""


def slide4(F) -> str:
    def cnt(label, a, b, ain_a, red):
        return (f'<div class="cnt"><p class="label">{label}</p>'
                f'<p class="big{" red" if red else ""}">{fmt(a)}<span class="of"> of {fmt(b)}</span></p>'
                f'<p class="sub">commune records differ, France</p>'
                f'<p class="sub{" red" if ain_a else ""}">Ain: {fmt(ain_a)} of {fmt(F["ain_records"])}</p></div>')
    return f"""<section class="slide">{top("Tare · measured", 4)}
<h1>After two fixes, no commune record differs, in Ain or across France.</h1>
<div class="s4">
  <div><canvas id="map-ai" width="1200" height="940"></canvas>{cnt("Published AI port", F['fr_ai_differ'], F['fr_records'], F['ain_ai_differ'], True)}</div>
  <div><canvas id="map-fx" width="1200" height="940"></canvas>{cnt("Repaired port", F['fr_fx_differ'], F['fr_records'], F['ain_fx_differ'], False)}</div>
  <div class="notes">
    <p class="key"><span class="sw" style="background:var(--red)"></span>Record differs</p>
    <p class="key" style="border-top:0;padding-top:0"><span class="sw" style="background:var(--ink)"></span>Record balances</p>
    <p>Each shape is one commune's record, replayed through the COBOL and the port. The maps draw the {fmt(F['map_drawn'])} communes of mainland France and Corsica; the counts include overseas communes.</p>
    <p>A commune record is one commune's 2018 totals and voted rates from public statistics, reshaped into one calculator input. It is not a household's bill.</p>
  </div>
</div></section>"""


def slide6(F) -> str:
    scale = F["_scale"][1]["src"]
    return f"""<section class="slide">{top("Tare · check it yourself", 6)}
<h1>The old program stopped the AI's commit, then graded its repair.</h1>
<div class="s5">
  <div>
    <div class="r"><p class="label">Search any commune</p><p class="url">{SITE_URL}</p></div>
    <div class="r"><p class="label">Rerun the Ain replay in seconds, Python only</p>
<pre>git clone {REPO_URL}
cd tare
python -m tare reproduce --offline</pre></div>
  </div>
  <figure><img src="{scale}" alt=""></figure>
</div>
<div class="foot"><span class="a"><b>Tare</b> · a plugin for IBM Bob</span><span class="b">Close enough doesn't commit.</span></div>
</section>"""


MAP_JS = """
(function(){
  const D=window.TARE, M=window.TARE_MAP, idx=new Map(); D.insee.forEach((c,i)=>idx.set(c,i));
  const [x0,y0,x1,y1]=M.bbox, RED="#C8102E", INK="#1E1E1E", BG="#FEFEFE";
  const ring=(p,r)=>{let x=0,y=0;for(let k=0;k<r.length;k+=2){x+=r[k];y+=r[k+1];k?p.lineTo(x,y):p.moveTo(x,y);}p.closePath();};
  const dep=new Path2D(); for(const c in M.departements) for(const r of M.departements[c]) ring(dep,r);
  function draw(id, side){
    const cv=document.getElementById(id); if(!cv) return;
    const ctx=cv.getContext("2d"), w=cv.width, h=cv.height, pad=8;
    const s=Math.min((w-2*pad)/(x1-x0),(h-2*pad)/(y1-y0)), ox=pad+((w-2*pad)-s*(x1-x0))/2, oy=pad+((h-2*pad)-s*(y1-y0))/2;
    ctx.fillStyle=BG; ctx.fillRect(0,0,w,h);
    ctx.setTransform(s,0,0,-s,ox-s*x0,h-oy+s*y0);
    const r=new Path2D(), k=new Path2D();
    for(const c in M.communes){const i=idx.get(c); if(i===undefined) continue; const p=D.sides[side].ndiff[i]>0?r:k; for(const g of M.communes[c]) ring(p,g);}
    ctx.fillStyle=INK; ctx.fill(k,"evenodd"); ctx.fillStyle=RED; ctx.fill(r,"evenodd");
    ctx.lineJoin="round"; ctx.strokeStyle=BG; ctx.lineWidth=1.4/s; ctx.stroke(dep);
  }
  draw("map-ai","java-ai"); draw("map-fx","java-ai-fixed");
})();
"""


def page(body: str, with_map: bool) -> str:
    scripts = ""
    if with_map:
        d = SITE / "dist" / "data"
        scripts = (f'<script src="{(d / "communes.js").as_uri()}"></script>'
                   f'<script src="{(d / "map.js").as_uri()}"></script><script>{MAP_JS}</script>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Tare deck</title>'
            f'<style>{css()}</style></head><body>{body}{scripts}</body></html>')


# ---------------------------------------------------------------- checks

FORBIDDEN = re.compile(r"badge|pill|chip|\btag\b|eyebrow|gradient|border-radius|\bInter\b|Roboto|system-ui|Space Grotesk|"
                       r"green|emoji", re.I)                                   # design terms, in the HTML
FORBIDDEN_TEXT = re.compile(r"Empower|Unlock|Transform|Streamline|Seamless|Supercharge|world-class|enterprise-grade|"
                            r"interest|billion|5[.,]996|overcharg|\bloss\b", re.I)  # copy and claims, in the rendered text
CONSTANTS = {"2018": "tax year of the calculator and of the REI data",
             "3": "the 3% fee tier", "8": "the 8% fee tier", "01": "Ain's département code",
             HERO: "the commune code of record 01001", "5": "slide number", "1": "slide or step number",
             "2": "step number; two defects", "4": "step number", "6": "step number; slide count",
             "2026": "year of the Bob session and of the MedPAC report", "09": "month of the Bob session",
             "26": "day of the Bob session", "2024": "MedPAC's payment year", "10": "MedPAC chapter"}
# A quoted figure, allowed only in this exact sentence with its source (site/tools/medicare_facts.py MEDPAC).
CITED = re.compile(r"about \$(28)\.3 billion in 2024 \(MedPAC, March 2026, chapter 10\)")


def allowed(F) -> dict:
    ok = dict(CONSTANTS)
    for k, v in F.items():
        if isinstance(v, int):
            ok[fmt(v)] = k
            ok[str(v)] = k
    for f in F["_hero_rows"]:
        d = F[f"hero_{f}_port"] - F[f"hero_{f}_cobol"]
        ok[fmt(abs(d))] = f"hero_{f}_port - hero_{f}_cobol"
    return ok


def check_numbers(text: str, ok: dict, where: str) -> list:
    text = CITED.sub("about [MedPAC] in 2024 (MedPAC, March 2026, chapter 10)", text)
    bad = [f"{where}: forbidden '{m.group(0)}'" for m in FORBIDDEN_TEXT.finditer(text)]
    for tok in re.findall(r"(?<![\w.:/])\d[\d,]*(?![\w])", text):
        tok = tok.rstrip(",")
        if tok not in ok:
            bad.append(f"{where}: '{tok}'")
    return bad


# ---------------------------------------------------------------- render

def contact_sheet(paths, out: Path):
    tw, th, pad, lab = 640, 360, 24, 34
    cols = 3
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (pad + cols * (tw + pad), pad + rows * (th + lab + pad)), "#FEFEFE")
    dr = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("consola.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for k, p in enumerate(paths):
        im = Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS)
        x, y = pad + (k % cols) * (tw + pad), pad + (k // cols) * (th + lab + pad)
        sheet.paste(im, (x, y + lab))
        dr.rectangle([x - 1, y + lab - 1, x + tw, y + lab + th], outline="#DEDEDE")
        dr.text((x, y + 6), p.name, fill="#1E1E1E", font=font)
    sheet.save(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tests-log", type=Path,
                    default=PROJECT / "_runs" / "2026-09-26_no_interest" / "taxe_fonciere" / "RUN_LOG.txt")
    ap.add_argument("--gate-log", type=Path, default=PROJECT / "_runs" / "2026-09-26_hero_loop" / "TRANSCRIPT.txt")
    ap.add_argument("--take-log", type=Path,
                    default=PROJECT / "_runs" / "2026-09-26_film" / "A_weigh_station" / "FOOTAGE_MAP.md")
    a = ap.parse_args()
    F, src = gather(a.tests_log, a.gate_log, a.take_log)

    build = DECK / "build"
    build.mkdir(exist_ok=True)
    (DECK / "slides").mkdir(exist_ok=True)
    cover_html = build / "cover.html"
    deck_html = build / "deck.html"
    cover_html.write_text(page(cover(F), False), encoding="utf-8")
    deck_html.write_text(page("".join(s(F) for s in (slide1, slide2, slide3, slide4, slide_medicare, slide6)), True),
                         encoding="utf-8")

    for p in (cover_html, deck_html):
        text = re.sub(r"<script>.*?</script>", "", p.read_text(encoding="utf-8"), flags=re.S)
        hits = sorted({m.group(0) for m in FORBIDDEN.finditer(text)})
        if hits:
            raise SystemExit(f"forbidden terms in {p.name}: {hits}")

    ok, bad = allowed(F), []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for name, dsf in (("cover.png", 1), ("cover_1280x720.png", 2 / 3)):
            pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=dsf)
            pg.goto(cover_html.as_uri())
            pg.evaluate("document.fonts.ready")
            pg.screenshot(path=str(DECK / name))
            if dsf == 1:
                bad += check_numbers(pg.inner_text("body"), ok, "cover")
            pg.close()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto(deck_html.as_uri(), wait_until="load", timeout=240000)   # two commune maps take about 40 s
        pg.evaluate("document.fonts.ready")
        slides = pg.query_selector_all("section.slide")
        assert len(slides) == SLIDES
        for k, el in enumerate(slides, 1):
            el.screenshot(path=str(DECK / "slides" / f"slide_{k}.png"))
            bad += check_numbers(el.inner_text(), ok, f"slide {k}")
        pg.pdf(path=str(DECK / "tare_slides.pdf"), width="1920px", height="1080px", print_background=True)
        b.close()
    if bad:
        raise SystemExit("numbers without a source:\n  " + "\n  ".join(bad))

    shots = [DECK / "cover.png"] + [DECK / "slides" / f"slide_{k}.png" for k in range(1, SLIDES + 1)]
    contact_sheet(shots, DECK / "contact_sheet.png")
    (DECK / "facts.json").write_text(json.dumps({k: {"value": F[k], "source": src[k]} for k in src}, ensure_ascii=False, indent=1),
                                     encoding="utf-8", newline="\n")
    for k in src:
        print(f"{k:22} {str(F[k])[:60]:60} {src[k]}")
    print("numbers checked: every number on the cover and slides is a traced fact or a listed constant")


if __name__ == "__main__":
    main()
