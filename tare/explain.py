import re
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path

from . import config, ledger, records, sides

IBM_RULE = ("When the size of the fractional result exceeds the number of places provided for its "
            "storage, truncation occurs unless ROUNDED is specified.")
IBM_URL = "https://www.ibm.com/docs/en/cobol-zos/6.3.0?topic=operations-rounded-phrase"
IBM_SOURCE = "IBM Enterprise COBOL for z/OS 6.3, Language Reference, ROUNDED phrase"

VERBS = {"MOVE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "IF", "ELSE", "PERFORM", "READ",
         "WRITE", "REWRITE", "DELETE", "START", "OPEN", "CLOSE", "DISPLAY", "ACCEPT", "STOP", "GOBACK", "EXIT",
         "EVALUATE", "WHEN", "INITIALIZE", "SET", "STRING", "UNSTRING", "INSPECT", "CALL", "GO", "CONTINUE",
         "SEARCH", "SORT", "MERGE", "RELEASE", "RETURN", "CANCEL"}
WRITERS = {"MOVE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"}
STOP_WORDS = {"ON", "NOT", "SIZE", "ERROR", "REMAINDER", "GIVING", "ROUNDED", "OF", "IN", "=", "EQUAL"}
TOKEN = re.compile(r"'[^']*'?|\"[^\"]*\"?|\d+\.\d+|\.\d+|\d+|[A-Za-z0-9][A-Za-z0-9-]*|\*\*|[*/+\-()=:.,]")
COPY = re.compile(r"(?<![A-Za-z0-9_-])COPY\s+['\"]?([A-Za-z0-9][A-Za-z0-9_-]*)['\"]?", re.I)
RTOKEN = re.compile(r"'[^']*'?|\"[^\"]*\"?|[A-Za-z0-9_-]+|[^\s,;]")
CTOKEN = re.compile(r"==.*?==|'[^']*'|\"[^\"]*\"|\.(?=\s|$)|[^\s'\".,;=()]+|[()]|\S", re.S)
DATA_ENTRY = re.compile(r"^\s*(\d{1,2})\s+([A-Za-z0-9][A-Za-z0-9-]*)(.*)$")
PIC = re.compile(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+?)(?=\.?(?:\s|$))", re.I)
USAGE = re.compile(r"\b(COMP(?:UTATIONAL)?-[1-5X]|COMP(?:UTATIONAL)?|BINARY|PACKED-DECIMAL|DISPLAY|INDEX|"
                   r"POINTER)\b", re.I)
SIGN = re.compile(r"\bSIGN\s+(?:IS\s+)?(LEADING|TRAILING)(\s+SEPARATE(?:\s+CHARACTER)?)?", re.I)


def _code(line: str):
    if len(line) > 6 and line[6] in "*/":
        return None
    return line[7:72] if len(line) > 7 else ""


def _read(path: Path):
    return path.read_text(encoding="latin-1").splitlines()


def _copybook(root: Path, cfg: dict, name: str):
    for d in (cfg.get("cobol") or {}).get("copybooks") or []:
        for ext in ("", ".cpy", ".CPY", ".cbl", ".CBL", ".cob", ".COB"):
            p = root / d / (name + ext)
            if p.is_file():
                return p
    return None


def _key(tok: str) -> str:
    return tok if tok[:1] in "'\"" else tok.upper()


def _operand(toks: list, i: int) -> tuple:
    t = toks[i]
    if len(t) >= 4 and t.startswith("==") and t.endswith("=="):
        return t[2:-2].strip(), i + 1
    if t[:1] in "'\"":
        return t, i + 1
    parts, i = [t], i + 1
    while i + 1 < len(toks) and toks[i].upper() in ("OF", "IN"):
        parts, i = parts + toks[i:i + 2], i + 2
    if i < len(toks) and toks[i] == "(":
        j = toks.index(")", i) + 1 if ")" in toks[i:] else len(toks)
        parts, i = parts + toks[i:j], j
    return " ".join(parts), i


def copy_statement(text: str):
    if text.count("==") % 2:
        return None
    toks = CTOKEN.findall(text)
    if "." not in toks:
        return None
    toks = toks[:toks.index(".")]
    name = toks[1].strip("'\"")
    ups = [t.upper() for t in toks]
    if "REPLACING" not in ups:
        return name, []
    rules, i = [], ups.index("REPLACING") + 1
    while i < len(toks):
        mode = ups[i] if ups[i] in ("LEADING", "TRAILING") else None
        i += 1 if mode else 0
        pat, i = _operand(toks, i)
        if i >= len(toks) or toks[i].upper() != "BY" or i + 1 >= len(toks):
            raise ValueError(f"COPY {name} REPLACING: expected '{pat} BY <text>'")
        rep, i = _operand(toks, i + 1)
        words = [_key(t) for t in RTOKEN.findall(pat)]
        if not words or (mode and len(words) != 1):
            raise ValueError(f"COPY {name} REPLACING: {mode or ''} operand =={pat}== must hold "
                             + ("one partial word" if mode else "at least one text word"))
        rules.append((mode, words, rep))
    return name, rules


def replace_copy(codes: list, rules) -> list:
    if not rules:
        return codes
    toks = [(n, m.start(), m.end(), m.group(0)) for n, c in enumerate(codes) if c is not None
            for m in RTOKEN.finditer(c)]
    edits, i = [], 0
    while i < len(toks):
        for mode, words, rep in rules:
            t = toks[i][3]
            if mode:
                k, w = t.upper(), words[0]
                if t[:1] not in "'\"" and (k.startswith(w) if mode == "LEADING" else k.endswith(w)):
                    edits.append((i, i, rep + t[len(w):] if mode == "LEADING" else t[:len(t) - len(w)] + rep))
                    i += 1
                    break
            elif [_key(x[3]) for x in toks[i:i + len(words)]] == words:
                edits.append((i, i + len(words) - 1, rep))
                i += len(words)
                break
        else:
            i += 1
    out = list(codes)
    for a, b, new in reversed(edits):
        (la, sa, _, _), (lb, _, eb, _) = toks[a], toks[b]
        if la == lb:
            out[la] = out[la][:sa] + new + out[la][eb:]
            continue
        out[la] = out[la][:sa] + new
        for n in range(la + 1, lb):
            if out[n] is not None:
                out[n] = ""
        out[lb] = " " * eb + out[lb][eb:]
    return out


def data_entries(root: Path, cfg: dict) -> list:
    out = []
    for src in (cfg.get("cobol") or {}).get("sources") or []:
        stack = []

        def walk(path: Path, depth=0, rules=()):
            rel = config.rel_to(root, path)
            codes = replace_copy([_code(line) for line in _read(path)], rules)
            in_data = path.suffix.lower() not in (".cbl", ".cob") or depth > 0
            i = 0
            while i < len(codes):
                code = codes[i]
                i += 1
                if code is None:
                    continue
                up = code.upper()
                if "DATA DIVISION" in up:
                    in_data = True
                if "PROCEDURE DIVISION" in up:
                    return
                m = COPY.search(code)
                if m and in_data:
                    where, text = f"{rel}:{i}", code[m.start():]
                    try:
                        parsed = copy_statement(text)
                        while parsed is None and i < len(codes):
                            if codes[i] is not None:
                                text += " " + codes[i]
                            i += 1
                            parsed = copy_statement(text)
                    except ValueError as e:
                        raise ValueError(f"{where}: {e}") from None
                    name, sub_rules = parsed or (m.group(1), [])
                    cb = _copybook(root, cfg, name)
                    if cb is not None and depth < 5:
                        walk(cb, depth + 1, sub_rules)
                    continue
                m = DATA_ENTRY.match(code)
                if not (m and in_data):
                    continue
                level, name, rest = int(m.group(1)), m.group(2).upper(), m.group(3)
                start = i
                while not rest.rstrip().endswith(".") and i < len(codes):
                    nxt = codes[i]
                    i += 1
                    if nxt is not None:
                        rest += " " + nxt.strip()
                if level in (66, 88):
                    continue
                while stack and (stack[-1][0] >= level or level in (1, 77)):
                    stack.pop()
                pic, usage, sign = PIC.search(rest), USAGE.search(rest), SIGN.search(rest)
                out.append({"level": level, "name": name, "pic": pic.group(1).rstrip(".") if pic else None,
                            "usage": usage.group(1).upper() if usage else "DISPLAY",
                            "sign": " ".join(x.strip().upper() for x in sign.groups() if x) if sign else None,
                            "file": rel, "line": start, "groups": [s[1] for s in stack]})
                stack.append((level, name))

        walk(root / src)
    return out


def _tokens(root: Path, cfg: dict):
    for src in (cfg.get("cobol") or {}).get("sources") or []:
        path = root / src
        rel = config.rel_to(root, path)
        in_proc = False
        for n, line in enumerate(_read(path), 1):
            code = _code(line)
            if code is None:
                continue
            if not in_proc:
                if "PROCEDURE DIVISION" in code.upper():
                    in_proc = True
                continue
            for m in TOKEN.finditer(code):
                yield m.group(0), rel, n


def statements(root: Path, cfg: dict) -> list:
    out, cur = [], None
    for tok, rel, n in _tokens(root, cfg):
        up = tok.upper()
        if up in VERBS:
            if cur:
                out.append(cur)
            cur = {"verb": up, "tokens": [], "file": rel, "start": n, "end": n}
            continue
        if tok == ".":
            if cur:
                out.append(cur)
            cur = None
            continue
        if cur is not None:
            if up.startswith("END-"):
                out.append(cur)
                cur = None
                continue
            cur["tokens"].append(tok)
            cur["end"] = n
    if cur:
        out.append(cur)
    return out


def _names(tokens) -> list:
    out, depth, skip = [], 0, False
    for t in tokens:
        up = t.upper()
        if t == "(":
            depth += 1
            continue
        if t == ")":
            depth -= 1
            continue
        if depth:
            continue
        if skip:
            skip = False
            continue
        if up in ("OF", "IN"):
            skip = True
            continue
        if up == "ROUNDED" or t == ",":
            continue
        if up in STOP_WORDS or not re.match(r"[A-Za-z]", t) and not re.match(r"\d+[A-Za-z-]", t):
            break
        out.append(up)
    return out


def _after(tokens, word):
    ups = [t.upper() for t in tokens]
    return tokens[ups.index(word) + 1:] if word in ups else None


def receivers(st: dict) -> list:
    toks, v = st["tokens"], st["verb"]
    if v == "MOVE":
        return _names(_after(toks, "TO") or [])
    if v == "COMPUTE":
        ups = [t.upper() for t in toks]
        cut = next((i for i, t in enumerate(ups) if t in ("=", "EQUAL")), len(toks))
        return _names(toks[:cut])
    giving = _after(toks, "GIVING")
    if giving is not None:
        out = _names(giving)
        rem = _after(toks, "REMAINDER")
        return out + (_names(rem) if rem else [])
    word = {"ADD": "TO", "SUBTRACT": "FROM", "MULTIPLY": "BY", "DIVIDE": "INTO"}[v]
    return _names(_after(toks, word) or [])


def writers_of(root: Path, cfg: dict, names: set) -> list:
    return [st for st in statements(root, cfg) if st["verb"] in WRITERS and set(receivers(st)) & names]


def pic_scale(pic: str) -> int:
    if not pic or "V" not in pic.upper():
        return 0
    frac = pic.upper().split("V", 1)[1]
    n = 0
    for m in re.finditer(r"9(?:\((\d+)\))?", frac):
        n += int(m.group(1)) if m.group(1) else 1
    return n


def exact_decimal(fr: Fraction) -> str:
    sign = "-" if fr < 0 else ""
    fr = abs(fr)
    whole, rem = divmod(fr.numerator, fr.denominator)
    if rem == 0:
        return f"{sign}{whole}"
    digits, seen = [], {}
    while rem and rem not in seen:
        seen[rem] = len(digits)
        rem *= 10
        digits.append(str(rem // fr.denominator))
        rem %= fr.denominator
    if rem:
        k = seen[rem]
        return f"{sign}{whole}.{''.join(digits[:k])}({''.join(digits[k:])})"
    return f"{sign}{whole}.{''.join(digits)}"


def _to_scale(fr: Fraction, scale: int, mode) -> Decimal:
    n = abs(fr) * 10 ** scale
    units = int(n) if mode == ROUND_DOWN else int(n + Fraction(1, 2))
    units = -units if fr < 0 else units
    return Decimal(units).scaleb(-scale).quantize(Decimal(1).scaleb(-scale))


class _Expr:

    def __init__(self, tokens, value):
        self.t, self.i, self.value = [x for x in tokens if x != ","], 0, value

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expr(self):
        v = self.term()
        while self.peek() in ("+", "-"):
            v = v + self.term() if self.take() == "+" else v - self.term()
        return v

    def term(self):
        v = self.power()
        while self.peek() in ("*", "/"):
            if self.take() == "*":
                v = v * self.power()
            else:
                d = self.power()
                if d == 0:
                    raise ValueError("division by zero")
                v = v / d
        return v

    def power(self):
        v = self.unary()
        if self.peek() == "**":
            self.take()
            e = self.power()
            if e.denominator != 1:
                raise ValueError("a non-integer exponent")
            v = v ** int(e)
        return v

    def unary(self):
        if self.peek() in ("+", "-"):
            return -self.unary() if self.take() == "-" else self.unary()
        return self.atom()

    def atom(self):
        tok = self.take()
        if tok is None:
            raise ValueError("the expression ends early")
        if tok == "(":
            v = self.expr()
            if self.take() != ")":
                raise ValueError("unbalanced parentheses")
            return v
        if re.fullmatch(r"\d+(\.\d+)?|\.\d+", tok):
            return Fraction(Decimal(tok))
        return self.value(tok.upper())


def expression(st: dict):
    ups = [t.upper() for t in st["tokens"]]
    i = next((k for k, t in enumerate(ups) if t in ("=", "EQUAL")), None)
    if i is None:
        return None
    out = []
    for t in st["tokens"][i + 1:]:
        if t.upper() in ("ON", "NOT", "SIZE"):
            break
        out.append(t)
    return out


def _pick(answer: dict, port, file: str, key, field, cfg: dict, accepted):
    lay = config.layout_for(cfg, file)
    a_recs = (answer.get("files") or {}).get(file, [])
    p_recs = (port or {}).get("files", {}).get(file, []) if port else []

    def find(recs, k):
        return next((r for r in recs if ledger.key_text(records.key_of(r, lay)) == k), None)

    diff = []
    if port is not None:
        diff = [r for r in ledger.weigh(answer, port, cfg, accepted)["rows"]
                if r["file"] == file and r["status"] != "accepted"]
    if key is None:
        key = next((r["key"] for r in diff), None) or (ledger.key_text(records.key_of(a_recs[0], lay))
                                                      if a_recs else None)
    a = find(a_recs, key) if key is not None else None
    if a is None:
        raise ValueError(f"no answer key record {key!r} in {file}")
    p = find(p_recs, key)
    names = [f["name"] for f in lay["fields"]]
    if field is None:
        field = next((r["field"] for r in diff if r["key"] == key and r["field"] != "*"), None) \
            or next((f["name"] for f in lay["fields"] if records.is_numeric(f)), names[0])
    if field not in names:
        raise ValueError(f"no field {field!r} in layout {cfg['files'][file]['layout']} ({', '.join(names)})")
    return key, field, a, p


def explain(root: Path, file=None, key=None, field=None, port=None, answer=None) -> str:
    cfg = config.load_config(root)
    outs = config.outputs(cfg)
    if file is None:
        if not outs:
            raise ValueError("tare.json declares no output files")
        file = outs[0]
    if file not in outs:
        raise ValueError(f"{str(file)[:40]!r} is not an output file in tare.json ({', '.join(outs)})")
    if key is not None and (not isinstance(key, str) or len(key) > 200):
        raise ValueError("key must be a string of at most 200 characters")
    port = port or config.PORT_SIDE
    a_path = config.answer_key_path(root, answer)
    port_path = config.resolve_port_path(root, port)
    recorded = None
    if port in sides.declared(root) and not port_path.is_file() and sides.fixture_path(root, port).is_file():
        port_path = sides.fixture_path(root, port)
        recorded = sides.recorded_label(port_path)
    a_doc = records.load_side(a_path)
    p_doc = records.load_side(port_path) if port_path.is_file() else None
    side = port if config.SIDE_RE.match(port) and not port.lower().endswith(".json") \
        else (p_doc or {}).get("side", port)
    key, field, a, p = _pick(a_doc, p_doc, file, key, field, cfg, cfg.get("accepted", []))
    lay = config.layout_for(cfg, file)
    fdef = next(f for f in lay["fields"] if f["name"] == field)
    cobol = (fdef.get("cobol") or field.replace("_", "-")).upper()
    numeric = records.is_numeric(fdef)
    av, pv = a.get(field), (p or {}).get(field)

    o = [f"EVIDENCE  {file} record {key}  field {field}  (port side: {side})"]
    if recorded:
        o.append(f"  port: {recorded}")
    o += ["", "1. The values", f"   answer key  {av}"]
    if p_doc is None:
        o.append(f"   port        no records.json at {port_path}")
    elif p is None:
        o.append(f"   port        (none): no record {key} in {port_path}")
    else:
        delta = ""
        if numeric and not ledger.same(av, pv, True):
            try:
                delta = f"   delta {ledger.signed(Decimal(str(pv)) - Decimal(str(av)))}"
            except ArithmeticError:
                delta = ""
        o.append(f"   port        {pv}{delta}" + ("   (same)" if ledger.same(av, pv, numeric) else ""))

    missing = [s for s in (cfg.get("cobol") or {}).get("sources") or [] if not (root / s).is_file()]
    if missing:
        fetch = "run: python fetch.py" + (f" (in {root})" if (root / "fetch.py").is_file() else "")
        o += ["", f"The COBOL is not on this machine ({', '.join(missing)}): {fetch}, then explain again."]
        return "\n".join(o)

    entries = data_entries(root, cfg)
    ent = next((e for e in entries if e["name"] == cobol), None)
    groups = set(ent["groups"]) if ent else set()
    writers = writers_of(root, cfg, {cobol} | groups)
    o += ["", f"2. The statements that write {cobol}" + (f" or a group holding it ({', '.join(ent['groups'])})"
                                                        if ent and ent["groups"] else "")]
    if not writers:
        o.append("   none found in the program sources named in tare.json")
    for st in writers:
        src = _read(root / st["file"])
        o.append(f"   {st['file']}:{st['start']}" + (f"-{st['end']}" if st["end"] != st["start"] else ""))
        o += [f"   {n:>5} | {src[n - 1].rstrip()}" for n in range(st["start"], st["end"] + 1)]

    o += ["", "3. The field"]
    if ent is None:
        o.append(f"   {cobol}: no data description found in the program sources or copybooks")
    else:
        o.append(f"   {cobol}  PIC {ent['pic'] or '(group)'}  USAGE {ent['usage']}"
                 + (f"  SIGN {ent['sign']}" if ent["sign"] else "") + f"   {ent['file']}:{ent['line']}")

    if numeric and p is not None and not ledger.same(av, pv, True):
        o += ["", "4. The arithmetic"]
        compute = next((st for st in writers if st["verb"] == "COMPUTE" and cobol in receivers(st)), None)
        if compute is None:
            o.append(f"   no COMPUTE into {cobol}; the statements above are the evidence")
        else:
            by_cobol = {(f.get("cobol") or f["name"].replace("_", "-")).upper(): f["name"] for f in lay["fields"]}
            missing = []

            def value(name):
                if name in by_cobol and records.is_numeric(next(f for f in lay["fields"]
                                                                if f["name"] == by_cobol[name])):
                    return Fraction(Decimal(str(a[by_cobol[name]])))
                missing.append(name)
                return Fraction(0)

            toks = expression(compute) or []
            text = " ".join(toks)
            try:
                exact = _Expr(toks, value).expr()
            except (ValueError, ZeroDivisionError, ArithmeticError) as e:
                exact, missing = None, missing or [f"({e})"]
            where = f"{compute['file']}:{compute['start']}"
            if missing or exact is None:
                o.append(f"   COMPUTE at {where}: {text}")
                o.append(f"   not recomputed: {', '.join(sorted(set(missing)))} "
                         f"{'is' if len(set(missing)) == 1 else 'are'} not a field of this record's layout")
            else:
                scale = pic_scale(ent["pic"]) if ent and ent["pic"] else int(fdef.get("scale", 0))
                trunc, halfup = _to_scale(exact, scale, ROUND_DOWN), _to_scale(exact, scale, ROUND_HALF_UP)
                rounded = any(t.upper() == "ROUNDED" for t in compute["tokens"])
                shown = " ".join(str(a[by_cobol[t.upper()]]) if t.upper() in by_cobol else t for t in toks)

                def which(v):
                    d = Decimal(str(v))
                    hits = (["truncation (no ROUNDED)"] if d == trunc else []) \
                        + (["half-up (ROUNDED)"] if d == halfup else [])
                    return "matches " + " and ".join(hits) if hits else "matches neither truncation nor half-up"

                o += [f"   COMPUTE at {where}, operands from the answer key's record",
                      f"   exact     {text}",
                      f"           = {shown} = {exact_decimal(exact)}",
                      f"   truncated to {scale} places (no ROUNDED)  = {trunc}",
                      f"   half-up to {scale} places (ROUNDED)       = {halfup}",
                      f"   answer key wrote {av:>12}   {which(av)}",
                      f"   port wrote       {pv:>12}   {which(pv)}",
                      "   The statement has a ROUNDED phrase." if rounded else "   The statement has no ROUNDED phrase."]
                if Decimal(str(pv)) in (trunc, halfup):
                    o += ["", f"5. The rule  {IBM_SOURCE}", f"   \"{IBM_RULE}\"", f"   {IBM_URL}"]
                else:
                    o.append("   Neither truncation nor rounding gives the port's value: the difference is not a "
                             "rounding rule; it comes from the operands.")

    entry = config.local_entry(cfg) if side == config.PORT_SIDE else config.sides(cfg).get(side) or {}
    if p is not None and not ledger.same(av, pv, numeric):
        o += known_causes(root, entry, field)

    o += ["", "The port's line"]
    if entry:
        o.append(f"   {side}: {entry.get('repo')}" + (f" @ {str(entry['commit'])[:7]}" if entry.get("commit") else ""))
        o.append(f"   {sides.line(root, side)}")
    else:
        pats = sides.source_patterns(root, side)
        o.append(f"   {side}: not declared in tare.json 'sides'; the port's sources are {pats or 'not configured'}")
    return "\n".join(o)


def _span(ref: str):
    path, _, lines = str(ref).rpartition(":")
    a, _, b = lines.partition("-")
    if not path or not a.isdigit() or (b and not b.isdigit()):
        raise ValueError(f"not a file:line or file:first-last reference: {ref!r}")
    return path, int(a), int(b or a)


def _quote(base: Path, ref: str, shown: str, hint: str) -> list:
    path, a, b = _span(ref)
    f = base / path
    if not f.is_file():
        return [f"{shown}:{a}-{b}  (not on this machine: {hint})"]
    src = f.read_text(encoding="utf-8", errors="replace").splitlines()
    return [f"{shown}:{a}" + (f"-{b}" if b != a else "")] + \
        [f"{n:>5} | {src[n - 1].rstrip()}" for n in range(a, min(b, len(src)) + 1)]


def known_causes(root: Path, entry: dict, field: str) -> list:
    hits = [c for c in entry.get("causes") or [] if field in (c.get("fields") or [])]
    if not hits:
        return []
    src = root / str(entry.get("source") or ".")
    o = ["", f"The known causes of a difference in {field} (tare.json: this side's causes)"]
    for n, c in enumerate(hits, 1):
        o += ["", f"   {n}. {c.get('what')}", "   the original:"]
        for ref in c.get("cobol") or []:
            o += ["     " + x for x in _quote(root, ref, _span(ref)[0], "python fetch.py")]
        if c.get("port"):
            shown = config.rel_to(root, src / _span(c["port"])[0])
            o += ["   the port:"] + ["     " + x for x in _quote(src, c["port"], shown,
                                                                f"{config.rel_to(root, src)} is not fetched")]
    return o
