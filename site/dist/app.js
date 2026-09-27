/* Tare parity receipt. Every number on the page is read from data/communes.js, data/run.js and data/map.js,
   which site/tools/build_site.py writes from the case's run output. */
(function () {
  "use strict";
  const D = window.TARE, RUN = window.TARE_RUN, M = window.TARE_MAP;
  const AI = "java-ai", FX = "java-ai-fixed";
  const N = D.records, F = D.compared_fields;
  const fmt = n => n.toLocaleString("en-US");
  const sgn = n => (n > 0 ? "+" : n < 0 ? "−" : "") + fmt(Math.abs(n));
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const LABEL = {
    tcthfr: ["Total before fees", "TCTHFR", "Before fees"],
    tctom: ["Household-waste tax", "TCTOM", "Waste tax"],
    mfa300: ["3% tier: assessment fee", "MFA300", "3% assessment"],
    mfn300: ["3% tier: relief and non-payment fee", "MFN300", "3% relief"],
    mfa800: ["8% tier: assessment fee", "MFA800", "8% assessment"],
    mfn800: ["8% tier: relief and non-payment fee", "MFN800", "8% relief"],
    mfa900: ["9% tier: assessment fee", "MFA900", "9% assessment"],
    mfn900: ["9% tier: relief and non-payment fee", "MFN900", "9% relief"],
    tctfra: ["Fees total", "TCTFRA", "Fees total"],
    tctdu: ["Total due", "TCTDU", "Total due"],
  };
  const ROWS = ["tcthfr", "tctom", "mfa300", "mfn300", "mfa800", "mfn800", "mfa900", "mfn900", "tctfra", "tctdu"];

  const byCode = new Map();
  D.insee.forEach((c, i) => byCode.set(c, i));
  const dep = i => (D.insee[i].startsWith("97") ? D.insee[i].slice(0, 3) : D.insee[i].slice(0, 2));
  const ak = (f, i) => D.answer_key[f][i];
  const sv = (s, f, i) => { const col = D.sides[s].values[f]; return col ? col[i] : ak(f, i); };
  const nd = (s, i) => D.sides[s].ndiff[i];
  const name = i => D.name[i];
  const lbl = f => `<span class="lbl-l">${LABEL[f][0]}</span><span class="lbl-s">${LABEL[f][2]}</span><span class="code">${LABEL[f][1]}</span>`;

  /* ---------- hero: commune record 01001 ---------- */
  const PEN = '<svg viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true"><path d="M8 22 C 6 8, 40 3, 62 4 C 88 5, 99 12, 96 23 C 93 34, 60 38, 36 36 C 14 34, 3 28, 9 15 C 12 10, 20 7, 27 6"/></svg>';
  function heroTable(i) {
    const rows = ROWS.filter(f => f !== "tctom" || ak(f, i) || sv(AI, f, i));
    let h = '<thead><tr><th>Field</th><th>COBOL</th><th>Published port</th><th>Port − COBOL</th></tr></thead><tbody>';
    for (const f of rows) {
      const a = ak(f, i), p = sv(AI, f, i), d = p - a, tot = f === "tctdu";
      let pv = fmt(p);
      if (tot && d) pv = '<span class="pen">' + pv + PEN + "</span>";
      h += `<tr${tot ? ' class="total"' : ""}><td>${lbl(f)}</td>` +
        `<td>${fmt(a)}</td><td${d ? ' class="diff"' : ""}>${pv}</td><td${d ? ' class="diff"' : ""}>${d ? sgn(d) : "0"}</td></tr>`;
    }
    return h + "</tbody>";
  }
  const H = byCode.get("01001");
  $("hero-label").textContent = `Commune record 01001 · ${name(H)} (Ain) · 2018 built-property tax, euros`;
  $("hero-h1").textContent = `The COBOL computes €${fmt(ak("tctdu", H))} due. The published port computes €${fmt(sv(AI, "tctdu", H))}.`;
  $("hero-table").innerHTML = heroTable(H);
  const withOm = D.answer_key.tctom.filter(v => v > 0).length;
  $("hero-note").textContent = ak("tctom", H) === 0
    ? `Record 01001 carries no household-waste tax, so only defect 1 moves its total. ${fmt(withOm)} of ${fmt(N)} commune records carry one; search Lyon or Bordeaux to see both defects at once.`
    : `${fmt(withOm)} of ${fmt(N)} commune records carry a household-waste tax.`;

  /* ---------- counts ---------- */
  const nAI = D.sides[AI].records_differ, nFX = D.sides[FX].records_differ;
  $("counts-h2").textContent = `${fmt(nAI)} of ${fmt(N)} commune records differ. After two fixes, ${fmt(nFX)} do.`;
  const ain = D.insee.map((c, i) => i).filter(i => dep(i) === "01");
  const ainAI = ain.filter(i => nd(AI, i) > 0).length, ainFX = ain.filter(i => nd(FX, i) > 0).length;
  const demo = RUN.demo;
  const cells = (a, b, red) => `<td class="big${red && a ? " red" : ""}">${fmt(a)}<span class="muted" style="font-size:.6em"> of ${fmt(b)}</span></td>`;
  $("counts-table").innerHTML =
    '<thead><tr><th>Commune records</th><th>Published port differs</th><th>Repaired port differs</th></tr></thead><tbody>' +
    `<tr><td>Ain (01), the demo slice<span class="code">committed fixtures, python -m tare reproduce --offline</span></td>${cells(demo.ai_differ, demo.records, true)}${cells(demo.fixed_differ, demo.records)}</tr>` +
    `<tr><td>France, every commune in REI 2018<span class="code">national replay, GnuCOBOL and both Java builds</span></td>${cells(nAI, N, true)}${cells(nFX, N)}</tr>` +
    `<tr><td>Fields, France<span class="code">${F} compared fields per record</span></td>${cells(D.sides[AI].fields_differ, F * N, true)}${cells(D.sides[FX].fields_differ, F * N)}</tr>` +
    "</tbody>";
  if (ainAI !== demo.ai_differ || ain.length !== demo.records) console.warn("Ain slice of the national replay:", ainAI, "of", ain.length);

  /* ---------- search ---------- */
  const norm = s => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const keys = D.name.map(norm);
  const q = $("q"), hits = $("hits");
  let sel = -1, list = [];
  function find(s) {
    const t = norm(s);
    if (!t) return [];
    const out = [], seen = new Set();
    const push = i => { if (!seen.has(i)) { seen.add(i); out.push(i); } };
    const code = s.trim().toUpperCase();
    if (/^[0-9][0-9AB]?[0-9]*$/.test(code)) D.insee.forEach((c, i) => { if (c.startsWith(code) && out.length < 12) push(i); });
    for (let i = 0; i < N && out.length < 12; i++) if (keys[i] === t) push(i);
    for (let i = 0; i < N && out.length < 12; i++) if (keys[i].startsWith(t)) push(i);
    for (let i = 0; i < N && out.length < 12; i++) if (keys[i].includes(" " + t)) push(i);
    for (let i = 0; i < N && out.length < 12; i++) if (keys[i].includes(t)) push(i);
    return out;
  }
  function renderHits() {
    hits.innerHTML = list.map((i, k) => `<li role="option" data-i="${i}" aria-selected="${k === sel}"><span>${esc(name(i))}</span><span class="num">${D.insee[i]}</span></li>`).join("");
    q.setAttribute("aria-expanded", list.length ? "true" : "false");
  }
  q.addEventListener("input", () => { list = find(q.value); sel = list.length ? 0 : -1; renderHits(); });
  q.addEventListener("keydown", e => {
    if (e.key === "ArrowDown" && list.length) { sel = (sel + 1) % list.length; renderHits(); e.preventDefault(); }
    else if (e.key === "ArrowUp" && list.length) { sel = (sel - 1 + list.length) % list.length; renderHits(); e.preventDefault(); }
    else if (e.key === "Enter" && sel >= 0) { pick(list[sel]); e.preventDefault(); }
    else if (e.key === "Escape") { list = []; renderHits(); }
  });
  hits.addEventListener("click", e => { const li = e.target.closest("li"); if (li) pick(+li.dataset.i); });

  function card(i) {
    const a = nd(AI, i), x = nd(FX, i);
    let h = `<div class="card-head"><p class="label">Commune record ${D.insee[i]} · département ${dep(i)}</p>` +
      `<p class="name">${esc(name(i))}</p>` +
      `<p class="verdict${a ? " red" : ""}">Published port: ${a} of ${F} fields differ</p>` +
      `<p class="verdict${x ? " red" : ""}">Repaired port: ${x} of ${F} fields differ</p></div>`;
    h += '<div style="overflow-x:auto"><table><thead><tr><th>Field, euros</th><th>COBOL</th><th>Published port</th><th>Repaired port</th></tr></thead><tbody>';
    for (const f of ROWS) {
      const c = ak(f, i), p = sv(AI, f, i), r = sv(FX, f, i);
      const cell = (v) => v === c ? `<td>${fmt(v)}</td>` : `<td class="diff">${fmt(v)}<span style="display:block;font-size:11px">${sgn(v - c)}</span></td>`;
      h += `<tr${f === "tctdu" ? ' class="total"' : ""}><td>${lbl(f)}</td><td>${fmt(c)}</td>${cell(p)}${cell(r)}</tr>`;
    }
    return h + "</tbody></table></div>";
  }
  function pick(i) {
    q.value = name(i) + " " + D.insee[i];
    list = []; renderHits();
    $("card").innerHTML = card(i);
  }
  const TRY = ["01001", "69123", "33063", "2A004", "75056"].filter(c => byCode.has(c));
  $("try").innerHTML = "Try " + TRY.map(c => `<button type="button" data-c="${c}">${c}</button>`).join("");
  $("try").addEventListener("click", e => { const b = e.target.closest("button"); if (b) pick(byCode.get(b.dataset.c)); });
  pick(byCode.get(TRY[1] || "01001"));

  /* ---------- map ---------- */
  const box = $("map-box"), cv = $("map-c"), tip = $("map-tip");
  const [x0, y0, x1, y1] = M.bbox;
  const drawn = [];                       // [data index, Path2D in map units]
  for (const code in M.communes) {
    const i = byCode.get(code);
    if (i === undefined) continue;
    const p = new Path2D();
    for (const ring of M.communes[code]) {
      let x = 0, y = 0;
      for (let k = 0; k < ring.length; k += 2) { x += ring[k]; y += ring[k + 1]; k ? p.lineTo(x, y) : p.moveTo(x, y); }
      p.closePath();
    }
    drawn.push([i, p]);
  }
  const depPath = new Path2D();
  for (const code in M.departements) for (const ring of M.departements[code]) {
    let x = 0, y = 0;
    for (let k = 0; k < ring.length; k += 2) { x += ring[k]; y += ring[k + 1]; k ? depPath.lineTo(x, y) : depPath.moveTo(x, y); }
    depPath.closePath();
  }
  const merged = s => { const r = new Path2D(), k = new Path2D(); for (const [i, p] of drawn) (nd(s, i) ? r : k).addPath(p); return [r, k]; };
  const layers = { [AI]: merged(AI), [FX]: merged(FX) };
  const countOn = s => drawn.filter(([i]) => nd(s, i) > 0).length;
  const counts = { [AI]: countOn(AI), [FX]: countOn(FX) };
  let side = AI, hitCtx = null, geo = null;
  const css = getComputedStyle(document.documentElement);
  const RED = css.getPropertyValue("--red").trim() || "#C8102E", INK = css.getPropertyValue("--ink").trim() || "#1E1E1E", BG = "#FEFEFE";

  function frame(w, h) {
    const pad = 6, sx = (w - 2 * pad) / (x1 - x0), sy = (h - 2 * pad) / (y1 - y0), s = Math.min(sx, sy);
    const ox = pad + ((w - 2 * pad) - s * (x1 - x0)) / 2, oy = pad + ((h - 2 * pad) - s * (y1 - y0)) / 2;
    return { s, ox, oy, h };
  }
  const setT = (ctx, g, dpr) => ctx.setTransform(g.s * dpr, 0, 0, -g.s * dpr, (g.ox - g.s * x0) * dpr, (g.h - g.oy + g.s * y0) * dpr);
  function draw() {
    const w = box.clientWidth, h = box.clientHeight, dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const ctx = cv.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.fillStyle = BG; ctx.fillRect(0, 0, cv.width, cv.height);
    geo = frame(w, h); setT(ctx, geo, dpr);
    const [r, k] = layers[side];
    ctx.fillStyle = INK; ctx.fill(k, "evenodd");
    ctx.fillStyle = RED; ctx.fill(r, "evenodd");
    ctx.lineJoin = "round"; ctx.strokeStyle = BG; ctx.lineWidth = 0.9 / geo.s; ctx.stroke(depPath);
    hitCtx = null;
    $("lg-red").textContent = fmt(counts[side]); $("lg-red").classList.toggle("red", counts[side] > 0); $("lg-ink").textContent = fmt(drawn.length - counts[side]);
    $("map-side").textContent = side === AI ? "Published port against the COBOL" : "Repaired port against the COBOL";
  }
  function hitMap() {                     // one flat colour per commune, drawn at CSS pixel size
    const w = box.clientWidth, h = box.clientHeight, c = document.createElement("canvas");
    c.width = w; c.height = h;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    setT(ctx, frame(w, h), 1);
    drawn.forEach(([, p], k) => { const id = k + 1; ctx.fillStyle = `rgb(${id >> 16 & 255},${id >> 8 & 255},${id & 255})`; ctx.fill(p, "evenodd"); });
    return ctx;
  }
  function at(e) {
    const b = cv.getBoundingClientRect(), x = Math.floor(e.clientX - b.left), y = Math.floor(e.clientY - b.top);
    hitCtx = hitCtx || hitMap();
    const d = hitCtx.getImageData(x - 2, y - 2, 5, 5).data, tried = new Set();
    for (let n = 0; n < 25; n++) {        // the centre pixel first, then its neighbours; the path test decides
      const j = 4 * (n === 0 ? 12 : n === 12 ? 0 : n), id = (d[j] << 16 | d[j + 1] << 8 | d[j + 2]) - 1;
      if (!d[j + 3] || id < 0 || id >= drawn.length || tried.has(id)) continue;
      tried.add(id);
      if (hitCtx.isPointInPath(drawn[id][1], x + .5, y + .5, "evenodd")) return { i: drawn[id][0], x, y };
    }
    return null;
  }
  cv.addEventListener("mousemove", e => {
    const h = at(e);
    if (!h) { tip.style.display = "none"; return; }
    const n = nd(side, h.i);
    tip.innerHTML = `${esc(name(h.i))} ${D.insee[h.i]}<br><span${n ? ' class="red"' : ""}>${n ? n + " of " + F + " fields differ" : "balances"}</span>`;
    tip.style.display = "block";
    const left = Math.min(h.x + 14, box.clientWidth - tip.offsetWidth - 2);
    tip.style.left = Math.max(0, left) + "px"; tip.style.top = (h.y + 14) + "px";
  });
  cv.addEventListener("mouseleave", () => { tip.style.display = "none"; });
  cv.addEventListener("click", e => { const h = at(e); if (h) { pick(h.i); $("search").scrollIntoView({ behavior: "smooth" }); } });
  function setSide(s) {
    side = s;
    $("t-ai").setAttribute("aria-pressed", s === AI); $("t-fx").setAttribute("aria-pressed", s === FX);
    draw();
  }
  $("t-ai").addEventListener("click", () => setSide(AI));
  $("t-fx").addEventListener("click", () => setSide(FX));
  const overseas = D.insee.filter(c => c.startsWith("97")).length, former = N - drawn.length - overseas;
  $("map-h2").textContent = `${fmt(drawn.length)} commune records of mainland France and Corsica, one shape each.`;
  $("map-cap").textContent = `Colored by the replay of each commune's record. Not drawn, and all in the search: ${fmt(overseas)} overseas communes and ${fmt(former)} former communes that the 2018 boundary file no longer shows. Hover for a commune; click to open it.`;
  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(draw, 120); });
  draw();

  /* ---------- gate ---------- */
  const shots = BOB_SHOTS.length ? BOB_SHOTS : RUN.scale;
  $("shots").innerHTML = shots.map(s => `<figure><a href="${esc(s.src)}"><img src="${esc(s.src)}" alt="${esc(s.caption)}" loading="lazy"></a><figcaption>${esc(s.caption)}</figcaption></figure>`).join("");
  $("runlog").innerHTML = RUN.log.map(l => /^TARE RED/.test(l) ? `<span class="r">${esc(l)}</span>` : esc(l)).join("\n");
  $("foot-data").textContent = `National replay ${RUN.date}; ${fmt(N)} commune records`;

  /* ---------- act two: Medicare hospice (data/medicare.js, site/tools/medicare_facts.py) ---------- */
  const V = window.TARE_MEDICARE.values, C = V.claims;
  const row = (who, code, n, what, red) =>
    `<tr><td>${who}<span class="code">${code}</span><span class="where-s">${what}</span></td>${cells(n, C, red)}<td class="where">${what}</td></tr>`;
  $("med-table").innerHTML =
    '<thead><tr><th>Java port</th><th>Claims that differ</th><th class="where" style="text-align:left">Where</th></tr></thead><tbody>' +
    row("CMS's own Java migration", "Hospice Pricer 2.5.1", V.cms_java_differ,
      `The claim total only, one cent each (${V.cms_java_cents_total} in all): it rounds after adding, the COBOL before. Every line payment matches.`, true) +
    row("AI-assisted port", "rcaran, README claims functional parity", V.java_ai_differ,
      `${fmt(V.java_ai_differ_chc)} of the ${fmt(V.chc_claims)} claims that bill continuous home care; ${fmt(V.java_ai_differ_non_chc)} of the other ${fmt(V.non_chc_claims)}. Three defects: a short care day counted as a routine day, the return code that follows, an hourly rate rounded instead of truncated.`, true) +
    row("The same port, three repairs", "five line edits, each checked by SHA-256", V.java_ai_fixed_differ,
      "Every field of every claim equals the COBOL's.", false) + "</tbody>";
  const EX = [["C00002", "total", "Claim total, $"], ["C00082", "high", "High-rate routine days"],
    ["C00033", "rtc", "Return code"], ["C00408", "pay_chc", "Continuous home care line, $"]];
  $("med-examples").innerHTML = '<thead><tr><th>Claim</th><th style="text-align:left">Field</th><th>COBOL</th><th>Port</th><th class="side" style="text-align:left">Side</th></tr></thead><tbody>' +
    EX.map(([c, f, l]) => { const [a, p, s] = V[`ex_${c}_${f}`];
      return `<tr><td class="mono">${c}</td><td style="text-align:left;font-family:var(--font)">${l}</td><td>${esc(a)}</td><td class="diff">${esc(p)}</td><td style="text-align:left" class="muted side">${s === "cms-java" ? "CMS's Java" : "AI-assisted port"}</td></tr>`; }).join("") + "</tbody>";
  $("med-units").textContent = `The ${fmt(C)} claims are constructed from public CMS tables with a fixed seed; no claim is a real claim and no person's data exists. ` +
    `${fmt(V.chc_claims)} of them bill continuous home care, far more than real hospice, where routine home care is ${V.medpac_rhc_share} of covered days, so the rate to quote is ${fmt(V.java_ai_differ_chc)} of ${fmt(V.chc_claims)} continuous-home-care claims. ` +
    `For scale, MedPAC reports that Medicare's hospice payment system paid about ${V.medpac_hospice_2024} in 2024. The finding is behaviour, not dollars: two ports that answer differently from the program they replace.`;
})();
