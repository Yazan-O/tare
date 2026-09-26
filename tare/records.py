"""Record decoding: fixed-width files to normalized JSON records, driven by tare.json's layouts.

A layout is {record_length, key: [field names], fields: [{name, offset, length, type, scale, sign, cobol}]}.
type 'X' is text (trailing spaces dropped); '9' is unsigned digits; 'S9V9' is signed digits. scale is the
number of implied decimal places (default 0). sign for 'S9V9': 'trailing-overpunch' (the sign in the last
digit's zone: '{', 'A'-'I' positive and '}', 'J'-'R' negative as GnuCOBOL writes with -fsign=EBCDIC, or
'p'-'y' negative as it writes by default), 'separate' (a trailing '+' or '-' byte) or 'none'. type 'COMP-3' is
packed decimal (USAGE COMP-3 / PACKED-DECIMAL): two digits a byte, the sign in the last half-byte (C, A, E or F
positive, D or B negative); a digit half-byte above 9 or a sign half-byte of 0-9 is not packed decimal.
Numbers become decimal strings with exactly `scale` places ('-12.50', '0.00'), so money never meets a float.

A records document ('records.json') is {side, command, input, files: {file: [record, ...]}, notes: [...]}.
"""
import json
from decimal import Decimal
from pathlib import Path

from . import config

POS = {c: i for i, c in enumerate("{ABCDEFGHI")}
NEG = {c: i for i, c in enumerate("}JKLMNOPQR")}
NEG_ASCII = {c: i for i, c in enumerate("pqrstuvwxy")}
TYPES = ("X", "9", "S9V9", "COMP-3")
PACKED_NEGATIVE = (0xB, 0xD)
SIGNS = ("trailing-overpunch", "separate", "none")


def is_numeric(field: dict) -> bool:
    return field.get("type") in ("9", "S9V9", "COMP-3")


def fmt(d: Decimal, scale: int) -> str:
    d = Decimal(d)
    if d == 0:
        d = abs(d)
    return f"{d:.{scale}f}"


def decode_field(raw: str, field: dict) -> str:
    """One field's bytes (as latin-1 text) to its normalized value. Raises ValueError on bad content."""
    t = field.get("type", "X")
    if t == "X":
        return raw.rstrip(" ")
    scale = int(field.get("scale", 0))
    if t == "COMP-3":
        return decode_packed(raw.encode("latin-1"), field["name"], scale)
    sign = field.get("sign", "none" if t == "9" else "trailing-overpunch")
    if t == "9" or sign == "none":
        digits, neg = raw, False
    elif sign == "trailing-overpunch":
        last = raw[-1:]
        if last in POS:
            digits, neg = raw[:-1] + str(POS[last]), False
        elif last in NEG:
            digits, neg = raw[:-1] + str(NEG[last]), True
        elif last in NEG_ASCII:
            digits, neg = raw[:-1] + str(NEG_ASCII[last]), True
        else:
            digits, neg = raw, False
    elif sign == "separate":
        if raw[-1:] not in ("+", "-"):
            raise ValueError(f"{field['name']}: no trailing sign in {raw!r}")
        digits, neg = raw[:-1], raw[-1] == "-"
    else:
        raise ValueError(f"{field['name']}: unknown sign {sign!r} (expected one of {', '.join(SIGNS)})")
    if not digits.isdigit() or not digits.isascii():
        raise ValueError(f"{field['name']}: not a {t} value: {raw!r}")
    d = Decimal(digits).scaleb(-scale)
    return fmt(-d if neg else d, scale)


def decode_packed(data: bytes, name: str, scale: int = 0) -> str:
    nibbles = [n for b in data for n in (b >> 4, b & 0xF)]
    digits, sign = nibbles[:-1], nibbles[-1]
    if not data or any(d > 9 for d in digits) or sign < 0xA:
        raise ValueError(f"{name}: not valid packed decimal: {data.hex(' ')}")
    d = Decimal("".join(map(str, digits)) or "0").scaleb(-scale)
    return fmt(-d if sign in PACKED_NEGATIVE else d, scale)


def check_layout(name: str, layout: dict):
    n = layout.get("record_length")
    if not isinstance(n, int) or n <= 0:
        raise ValueError(f"layout {name}: record_length must be a positive integer")
    names = set()
    for f in layout.get("fields", []):
        for k in ("name", "offset", "length"):
            if k not in f:
                raise ValueError(f"layout {name}: a field has no {k!r}: {f}")
        if f.get("type", "X") not in TYPES:
            raise ValueError(f"layout {name}: field {f['name']} type {f.get('type')!r} is not one of {TYPES}")
        if f["offset"] < 0 or f["length"] <= 0 or f["offset"] + f["length"] > n:
            raise ValueError(f"layout {name}: field {f['name']} ({f['offset']}+{f['length']}) is outside "
                             f"the {n}-byte record")
        names.add(f["name"])
    missing = [k for k in layout.get("key", []) if k not in names]
    if not layout.get("key") or missing:
        raise ValueError(f"layout {name}: key must name its fields; unknown {missing}" if missing
                         else f"layout {name}: no key fields")


def decode_record(rec: str, layout: dict) -> dict:
    return {f["name"]: decode_field(rec[f["offset"]:f["offset"] + f["length"]], f) for f in layout["fields"]}


def decode_bytes(data: bytes, layout: dict, where="") -> list:
    n = layout["record_length"]
    if len(data) % n:
        raise ValueError(f"{where}: {len(data)} bytes is not a multiple of the record length {n}")
    out = []
    for i in range(0, len(data), n):
        try:
            out.append(decode_record(data[i:i + n].decode("latin-1"), layout))
        except ValueError as e:
            raise ValueError(f"{where} record {i // n + 1}: {e}") from None
    return out


def decode_file(path: Path, layout: dict) -> list:
    return decode_bytes(Path(path).read_bytes(), layout, str(path))


def key_of(rec: dict, layout: dict) -> tuple:
    return tuple(str(rec.get(k)) for k in layout["key"])


def collect(root: Path, cfg: dict, out_dir: Path, side: str, command: str, input_rel: str, notes=None) -> Path:
    """Decode <out_dir>/<file>.dat for every output file in tare.json into <out_dir>/records.json.
    A file the run did not write is recorded as empty with a note, so each of its records weighs as missing."""
    out_dir = Path(out_dir)
    doc = {"side": side, "command": command, "input": input_rel, "files": {}, "notes": list(notes or [])}
    for name in config.outputs(cfg):
        p = out_dir / f"{name}.dat"
        if not p.is_file():
            doc["files"][name] = []
            doc["notes"].append(f"no {name}.dat was written")
            continue
        doc["files"][name] = decode_file(p, config.layout_for(cfg, name))
    path = out_dir / config.RECORDS
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


def load_side(path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no records.json at {path}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise ValueError(f"{path}: not a records.json (no 'files' object)")
    return data
