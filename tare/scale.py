import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, S = 768, 432, 4
PAPER, INK, RED = (0xFE, 0xFE, 0xFE), (0x1E, 0x1E, 0x1E), (0xC8, 0x10, 0x2E)
FONTS = Path(__file__).resolve().parent / "assets" / "fonts"
MAX_DEG, MIN_RED_DEG = 12.0, 2.0

PIVOT = (384, 124)
HALF_BEAM = 214
CHAIN = 100
PAN_HALF, PAN_DEPTH = 72, 22
GROUND = 340
MARGIN = 24


def _font(name, size, weight):
    f = ImageFont.truetype(str(FONTS / name), size * S)
    try:
        f.set_variation_by_name(weight)
    except (OSError, ValueError):
        pass
    return f


def tilt(summary: dict) -> float:
    if summary.get("verdict") == "balanced":
        return 0.0
    total = max(summary.get("records_total") or 0, 1)
    mag = min(MAX_DEG, MAX_DEG * (summary.get("records_differ") or 0) / total)
    mag = max(mag, MIN_RED_DEG)
    heavier = ((summary.get("higher", 0) - summary.get("lower", 0))
               or (summary.get("extra", 0) - summary.get("missing", 0)) or 1)
    return mag if heavier > 0 else -mag


class _Pen:
    def __init__(self, draw):
        self.d = draw

    def line(self, pts, w=2, fill=INK):
        self.d.line([(x * S, y * S) for x, y in pts], fill=fill, width=round(w * S), joint="curve")

    def circle(self, c, r, w=2, fill=None, outline=INK):
        x, y = c
        self.d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=fill, outline=outline,
                       width=round(w * S))

    def text(self, xy, s, font, fill=INK, track=0.0, anchor="l"):
        x, y = xy
        adv = [font.getlength(ch) / S + track for ch in s]
        width = sum(adv) - (track if s else 0)
        x = x - width / 2 if anchor == "c" else (x - width if anchor == "r" else x)
        for ch, a in zip(s, adv):
            self.d.text((x * S, y * S), ch, font=font, fill=fill)
            x += a
        return width

    def width(self, s, font, track=0.0):
        return sum(font.getlength(ch) / S + track for ch in s) - (track if s else 0)


def display(side: str) -> str:
    return f"PORT {side}".upper()


def _clamp(x, width, lo=MARGIN, hi=W - MARGIN):
    return min(max(x, lo + width / 2), hi - width / 2)


def _pan(pen, hx, hy, label, fonts, broken=False):
    rim_y = hy + CHAIN
    pen.circle((hx, hy), 3.5, w=2, fill=PAPER)
    for dx in (-PAN_HALF + 6, PAN_HALF - 6):
        a, b = (hx, hy + 3.5), (hx + dx, rim_y)
        if broken and dx > 0:
            pen.line([a, (a[0] + (b[0] - a[0]) * .42, a[1] + (b[1] - a[1]) * .42)], w=1.6)
            pen.line([(b[0] - 3, b[1] - 26), b], w=1.6)
        else:
            pen.line([a, b], w=1.6)
    pen.line([(hx - PAN_HALF, rim_y), (hx + PAN_HALF, rim_y)], w=2.5)
    pen.d.arc([(hx - PAN_HALF + 4) * S, (rim_y - PAN_DEPTH) * S, (hx + PAN_HALF - 4) * S, (rim_y + PAN_DEPTH) * S],
              0, 180, fill=INK, width=round(2.5 * S))
    for k in range(-3, 4):
        x = hx + k * 14
        t = 1 - ((x - hx) / (PAN_HALF - 4)) ** 2
        if t > 0.15:
            pen.line([(x, rim_y + 4), (x, rim_y + PAN_DEPTH * math.sqrt(t) - 4)], w=1)
    y = rim_y + PAN_DEPTH + 10
    w = pen.width(label.upper(), fonts["label"], 1.6)
    pen.text((_clamp(hx, w), y), label.upper(), fonts["label"], track=1.6, anchor="c")
    return y + 28


def wrote_nothing(summary: dict) -> bool:
    n = summary.get("records_total", 0)
    return bool(n) and summary.get("missing") == n


def details(summary: dict) -> list:
    n = summary.get("records_total", 0)
    if wrote_nothing(summary):
        return [f"0 of {n} written"]
    return [f"{summary.get('records_differ', 0)} of {n} records differ"]


def render(summary: dict, side: str, out_path, program=None) -> Path:
    img = Image.new("RGB", (W * S, H * S), PAPER)
    pen = _Pen(ImageDraw.Draw(img))
    fonts = {
        "title": _font("JetBrainsMono-wght.ttf", 16, "Medium"),
        "label": _font("JetBrainsMono-wght.ttf", 22, "Medium"),
        "line": _font("JetBrainsMono-wght.ttf", 26, "Regular"),
    }
    balanced = summary.get("verdict") == "balanced"
    n = summary.get("records_total", 0)

    title = "TARE · " + (f"{program} · " if program else "") + f"{n} RECORDS"
    pen.text((24, 16), title.upper(), fonts["title"], track=0.6)
    pen.text((W - 24, 16), "BALANCED" if balanced else "RED", fonts["title"],
             fill=INK if balanced else RED, track=1.2, anchor="r")
    pen.line([(24, 40), (W - 24, 40)], w=1)

    px, py = PIVOT
    pen.line([(px - 96, GROUND), (px + 96, GROUND)], w=2.5)
    for k in range(-11, 12):
        x = px + k * 8
        pen.line([(x, GROUND + 3), (x - 6, GROUND + 11)], w=1)
    pen.line([(px - 44, GROUND), (px - 22, GROUND - 16), (px + 22, GROUND - 16), (px + 44, GROUND)], w=2.5)
    pen.line([(px - 6, GROUND - 16), (px - 6, py + 10)], w=2.5)
    pen.line([(px + 6, GROUND - 16), (px + 6, py + 10)], w=2.5)
    pen.line([(px - 14, py + 10), (px + 14, py + 10)], w=2.5)

    pen.line([(px, py - 44), (px, py - 34)], w=2)
    pen.line([(px - 7, py - 44), (px + 7, py - 44)], w=2)

    th = math.radians(tilt(summary))
    c, s_ = math.cos(th), math.sin(th)

    def rot(dx, dy):
        return px + dx * c - dy * s_, py + dx * s_ + dy * c

    pen.line([rot(0, 0), rot(0, -30)], w=2)
    L = HALF_BEAM
    top = [rot(-L, -2), rot(-60, -5), rot(60, -5), rot(L, -2)]
    bot = [rot(L, 2), rot(60, 5), rot(-60, 5), rot(-L, 2)]
    pen.d.polygon([(x * S, y * S) for x, y in top + bot], fill=PAPER)
    pen.line(top + bot + [top[0]], w=2.2)
    pen.circle((px, py), 7, w=2.2, fill=PAPER)
    pen.circle((px, py), 1.8, w=1, fill=INK)

    lx, ly = rot(-L, 0)
    rx, ry = rot(L, 0)
    _pan(pen, lx, ly, "ORIGINAL", fonts)
    y = _pan(pen, rx, ry, display(side), fonts, broken=wrote_nothing(summary))

    if balanced:
        pen.text((px, GROUND + 20), f"{n} of {n} records balance", fonts["line"], anchor="c")
    else:
        lo = px + 96 + 16
        for detail in details(summary):
            parts = [detail]
            if pen.width(detail, fonts["line"]) > W - MARGIN - lo and " records " in detail:
                head, tail = detail.split(" records ", 1)
                parts = [head, "records " + tail]
            for part in parts:
                pen.text((_clamp(rx, pen.width(part, fonts["line"]), lo=lo), y), part, fonts["line"], fill=RED, anchor="c")
                y += 30

    out = img.resize((W, H), Image.LANCZOS)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, "PNG", optimize=True)
    return out_path


def ink_bottom(path) -> int:
    img = Image.open(path).convert("RGB")
    diff = Image.eval(img, lambda v: 255 if v < 0xF4 else 0).convert("L")
    box = diff.getbbox()
    return box[3] - 1 if box else -1


def contact_sheet(states, out_path, program=None) -> Path:
    import tempfile
    tiles = []
    with tempfile.TemporaryDirectory() as td:
        for i, (summ, side) in enumerate(states):
            p = render(summ, side, Path(td) / f"s{i}.png", program=program)
            tiles.append(Image.open(p).copy())
    gap, cap = 16, 28
    sheet = Image.new("RGB", (W + W // 2 + 3 * gap, max(len(tiles), 1) * (H + gap + cap) + gap),
                      (0xE6, 0xE6, 0xE6))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(FONTS / "JetBrainsMono-wght.ttf"), 16)
    for i, (t, (_, label)) in enumerate(zip(tiles, states)):
        y = gap + i * (H + gap + cap)
        draw.text((gap, y + 4), label, font=font, fill=INK)
        sheet.paste(t, (gap, y + cap))
        sheet.paste(t.resize((W // 2, H // 2), Image.LANCZOS), (W + 2 * gap, y + cap))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG", optimize=True)
    return out_path
