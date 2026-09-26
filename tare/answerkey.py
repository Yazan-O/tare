"""python -m tare answer-key: run the original COBOL job under GnuCOBOL and record its outputs.

tare.json describes the job as JCL would:
  cobol   {sources: [...], copybooks: [dirs], flags: [...]}   flags default to ["-std=ibm"]; add
          "-fsign=EBCDIC" when the data carries signs as EBCDIC overpunch ('{', 'A'-'I', '}', 'J'-'R').
  files   {name: {from, from_format, record_length, organization, key, alternate_keys, layout, output}}
          from           initial content (fixed-width records; from_format 'lines' pads LF-separated text
                         lines to record_length); these are the inputs the port reads.
          organization   'sequential' (default) or 'indexed' with key {offset, length} and
                         alternate_keys [{offset, length, duplicates}] (0-based byte offsets).
          output         true: the file is part of the answer key and is weighed.
  steps   [{program, dd: {DDNAME: file name}, parm, rc}]   rc lists the accepted return codes (default [0]).

The z/OS pieces are stood in for by harness programs generated here from that description, each headed
HARNESS: LOADER (IDCAMS DEFINE CLUSTER + REPRO: loads a fixed-width file into an indexed file with the
declared keys, and unloads it in key order), one PARM driver per step with a PARM (the halfword length plus
text layout a z/OS program receives), and the CEE3ABD abend stub.

Output (default fixtures/answer_key/): input/<file>.dat for every input, <file>.dat for every output,
records.json (the outputs decoded with their layouts), logs/ (each step's job log) and steps.log.
"""
import os
import shutil
import subprocess
from pathlib import Path

from . import config, records

HARNESS_DIR = config.PACKAGE_DIR / "harness"
WORK = "work/answer_key_build"
DEFAULT_FLAGS = ["-std=ibm"]
MAX_PARM = 100


class AnswerKeyError(RuntimeError):
    pass


def _tail(text: str, n=30) -> str:
    return "\n".join((text or "").strip().splitlines()[-n:])


def file_length(cfg: dict, name: str) -> int:
    f = cfg["files"][name]
    n = f.get("record_length")
    if n is None and f.get("layout"):
        n = config.layout_for(cfg, name)["record_length"]
    if not isinstance(n, int) or n <= 0:
        raise AnswerKeyError(f"file {name}: no record_length")
    return n


def indexed_files(cfg: dict) -> list:
    return [n for n, f in (cfg.get("files") or {}).items() if f.get("organization") == "indexed"]


def validate(cfg: dict):
    files = cfg.get("files") or {}
    if not files:
        raise AnswerKeyError("tare.json has no 'files'")
    if not (cfg.get("cobol") or {}).get("sources"):
        raise AnswerKeyError("tare.json has no cobol.sources")
    if not cfg.get("steps"):
        raise AnswerKeyError("tare.json has no 'steps'")
    for name, f in files.items():
        if not config.SIDE_RE.match(name):
            raise AnswerKeyError(f"file name {name!r}: letters, digits, '-' and '_' only")
        n = file_length(cfg, name)
        if f.get("organization", "sequential") not in ("sequential", "indexed"):
            raise AnswerKeyError(f"file {name}: organization must be 'sequential' or 'indexed'")
        if f.get("organization") == "indexed":
            keys = [f.get("key")] + list(f.get("alternate_keys") or [])
            if not isinstance(keys[0], dict):
                raise AnswerKeyError(f"file {name}: an indexed file needs key {{offset, length}}")
            for k in keys:
                if k["offset"] < 0 or k["length"] <= 0 or k["offset"] + k["length"] > n:
                    raise AnswerKeyError(f"file {name}: key {k} is outside the {n}-byte record")
        if f.get("output"):
            records.check_layout(f.get("layout", "?"), config.layout_for(cfg, name))
            if config.layout_for(cfg, name)["record_length"] != n:
                raise AnswerKeyError(f"file {name}: record_length {n} differs from its layout's")
    for i, s in enumerate(cfg["steps"], 1):
        if not s.get("program"):
            raise AnswerKeyError(f"step {i}: no program")
        for dd, fname in (s.get("dd") or {}).items():
            if fname not in files:
                raise AnswerKeyError(f"step {i}: DD {dd} names file {fname!r}, which is not in 'files'")
        parm = s.get("parm")
        if parm is not None and (len(parm) > MAX_PARM or not all(32 <= ord(c) < 127 for c in parm)):
            raise AnswerKeyError(f"step {i}: parm must be at most {MAX_PARM} printable ASCII characters")


# --- generated harness ------------------------------------------------------------------------------------

def _cobol_lines(text: str) -> str:
    for n, line in enumerate(text.splitlines(), 1):
        if len(line) > 72:
            raise AnswerKeyError(f"generated COBOL line {n} is longer than 72 columns: {line!r}")
    return text


def loader_source(cfg: dict) -> str:
    """The LOADER harness program for every indexed file in tare.json (kinds K01, K02, ...)."""
    idx = indexed_files(cfg)
    lens = {n: file_length(cfg, n) for n in idx}
    o = ["      *HARNESS: generated by tare/answerkey.py from tare.json.",
         "      * Stands in for IDCAMS DEFINE CLUSTER + REPRO on z/OS.",
         "      * LOADER IN  Knn: loads fixed-width records (DD SEQFILE) into",
         "      *   the indexed file (DD IDXFILE) with the declared keys.",
         "      * LOADER OUT Knn: unloads the indexed file (DD IDXFILE) to",
         "      *   fixed-width records (DD SEQFILE) in primary key order."]
    for i, n in enumerate(idx, 1):
        f = cfg["files"][n]
        keys = ", ".join(f"{k['offset']}+{k['length']}" for k in [f["key"], *(f.get("alternate_keys") or [])])
        o.append(f"      * K{i:02d} = {n[:30]}: {lens[n]} bytes, keys {keys}"[:72])
    o += ["       IDENTIFICATION DIVISION.",
          "       PROGRAM-ID. LOADER.",
          "       ENVIRONMENT DIVISION.",
          "       INPUT-OUTPUT SECTION.",
          "       FILE-CONTROL."]
    for i, n in enumerate(idx, 1):
        f = cfg["files"][n]
        o += [f"           SELECT SEQ-{i:02d} ASSIGN TO SEQFILE",
              "                  ORGANIZATION IS SEQUENTIAL",
              "                  FILE STATUS  IS WS-SEQ-STATUS.",
              f"           SELECT IDX-{i:02d} ASSIGN TO IDXFILE",
              "                  ORGANIZATION IS INDEXED",
              "                  ACCESS MODE  IS DYNAMIC",
              f"                  RECORD KEY   IS IDX-{i:02d}-KEY0"]
        for j, k in enumerate(f.get("alternate_keys") or [], 1):
            o.append(f"                  ALTERNATE RECORD KEY IS IDX-{i:02d}-KEY{j}")
            if k.get("duplicates"):
                o.append("                      WITH DUPLICATES")
        o.append("                  FILE STATUS  IS WS-IDX-STATUS.")
    o += ["       DATA DIVISION.", "       FILE SECTION."]
    for i, n in enumerate(idx, 1):
        f, ln = cfg["files"][n], lens[n]
        o += [f"       FD  SEQ-{i:02d}.",
              f"       01  SEQ-{i:02d}-REC                 PIC X({ln}).",
              f"       FD  IDX-{i:02d}.",
              f"       01  IDX-{i:02d}-REC                 PIC X({ln})."]
        for j, k in enumerate([f["key"], *(f.get("alternate_keys") or [])]):
            o.append(f"       01  IDX-{i:02d}-R{j}.")
            if k["offset"]:
                o.append(f"           05 FILLER                  PIC X({k['offset']}).")
            o.append(f"           05 IDX-{i:02d}-KEY{j}             PIC X({k['length']}).")
            rest = ln - k["offset"] - k["length"]
            if rest:
                o.append(f"           05 FILLER                  PIC X({rest}).")
    o += ["       WORKING-STORAGE SECTION.",
          "       01  WS-ARGS                    PIC X(80).",
          "       01  WS-DIR                     PIC X(04).",
          "       01  WS-KIND                    PIC X(04).",
          f"       01  WS-REC                     PIC X({max(lens.values())}).",
          "       01  WS-SEQ-STATUS              PIC X(02).",
          "       01  WS-IDX-STATUS              PIC X(02).",
          "       01  WS-STATUS                  PIC X(02).",
          "       01  WS-EOF                     PIC X(01) VALUE 'N'.",
          "       01  WS-COUNT                   PIC 9(09) VALUE 0.",
          "       01  WS-WHAT                    PIC X(30).",
          "       PROCEDURE DIVISION.",
          "           ACCEPT WS-ARGS FROM COMMAND-LINE",
          "           UNSTRING WS-ARGS DELIMITED BY ALL SPACE",
          "               INTO WS-DIR WS-KIND",
          "           END-UNSTRING",
          "           IF WS-DIR NOT = 'IN' AND WS-DIR NOT = 'OUT'",
          "               PERFORM 800-USAGE",
          "           END-IF",
          "           EVALUATE WS-KIND"]
    for i, _ in enumerate(idx, 1):
        o.append(f"             WHEN 'K{i:02d}' PERFORM K{i:02d}-COPY")
    o += ["             WHEN OTHER  PERFORM 800-USAGE",
          "           END-EVALUATE",
          "           DISPLAY 'LOADER ' WS-DIR ' ' WS-KIND ' RECORDS: ' WS-COUNT",
          "           GOBACK.", ""]
    for i, _ in enumerate(idx, 1):
        s, x = f"SEQ-{i:02d}", f"IDX-{i:02d}"
        o += [f"       K{i:02d}-COPY.",
              "           IF WS-DIR = 'IN'",
              f"               OPEN INPUT {s}",
              "               MOVE WS-SEQ-STATUS TO WS-STATUS",
              "               MOVE 'OPEN INPUT SEQFILE' TO WS-WHAT",
              "               PERFORM 900-CHECK",
              f"               OPEN OUTPUT {x}",
              "               MOVE WS-IDX-STATUS TO WS-STATUS",
              "               MOVE 'OPEN OUTPUT IDXFILE' TO WS-WHAT",
              "               PERFORM 900-CHECK",
              "               PERFORM UNTIL WS-EOF = 'Y'",
              "                   MOVE SPACES TO WS-REC",
              f"                   READ {s} INTO WS-REC",
              "                   IF WS-SEQ-STATUS = '10'",
              "                       MOVE 'Y' TO WS-EOF",
              "                   ELSE",
              "                       MOVE WS-SEQ-STATUS TO WS-STATUS",
              "                       MOVE 'READ SEQFILE' TO WS-WHAT",
              "                       PERFORM 900-CHECK",
              f"                       WRITE {x}-REC FROM WS-REC",
              "                       MOVE WS-IDX-STATUS TO WS-STATUS",
              "                       MOVE 'WRITE IDXFILE' TO WS-WHAT",
              "                       PERFORM 900-CHECK",
              "                       ADD 1 TO WS-COUNT",
              "                   END-IF",
              "               END-PERFORM",
              "           ELSE",
              f"               OPEN INPUT {x}",
              "               MOVE WS-IDX-STATUS TO WS-STATUS",
              "               MOVE 'OPEN INPUT IDXFILE' TO WS-WHAT",
              "               PERFORM 900-CHECK",
              f"               OPEN OUTPUT {s}",
              "               MOVE WS-SEQ-STATUS TO WS-STATUS",
              "               MOVE 'OPEN OUTPUT SEQFILE' TO WS-WHAT",
              "               PERFORM 900-CHECK",
              "               PERFORM UNTIL WS-EOF = 'Y'",
              "                   MOVE SPACES TO WS-REC",
              f"                   READ {x} NEXT RECORD INTO WS-REC",
              "                   IF WS-IDX-STATUS = '10'",
              "                       MOVE 'Y' TO WS-EOF",
              "                   ELSE",
              "                       MOVE WS-IDX-STATUS TO WS-STATUS",
              "                       MOVE 'READ IDXFILE' TO WS-WHAT",
              "                       PERFORM 900-CHECK",
              f"                       WRITE {s}-REC FROM WS-REC",
              "                       MOVE WS-SEQ-STATUS TO WS-STATUS",
              "                       MOVE 'WRITE SEQFILE' TO WS-WHAT",
              "                       PERFORM 900-CHECK",
              "                       ADD 1 TO WS-COUNT",
              "                   END-IF",
              "               END-PERFORM",
              "           END-IF",
              f"           CLOSE {s} {x}.", ""]
    o += ["       800-USAGE.",
          "           DISPLAY 'LOADER: usage LOADER IN|OUT Knn, got: ' WS-ARGS",
          "           MOVE 16 TO RETURN-CODE",
          "           STOP RUN.", "",
          "       900-CHECK.",
          "           IF WS-STATUS NOT = '00'",
          "               DISPLAY 'LOADER ' WS-DIR ' ' WS-KIND ': ' WS-WHAT",
          "                       ' FILE STATUS ' WS-STATUS",
          "                       ' AFTER RECORD ' WS-COUNT",
          "               MOVE 12 TO RETURN-CODE",
          "               STOP RUN",
          "           END-IF.", ""]
    return _cobol_lines("\n".join(o))


def parm_driver_name(step_no: int) -> str:
    return f"TPARM{step_no:02d}"


def parm_driver_source(step_no: int, program: str, parm: str) -> str:
    """A driver that CALLs `program` with the PARM layout z/OS passes: halfword length, then the text."""
    name = parm_driver_name(step_no)
    shown = parm.replace("'", "''")
    o = [f"      *HARNESS: generated by tare/answerkey.py from tare.json step {step_no}.",
         f"      * Stands in for the z/OS job step EXEC PGM={program},PARM=...",
         "      * z/OS passes the PARM text as a halfword binary length",
         "      * followed by the characters; this driver lays it out the",
         f"      * same way and CALLs the unmodified {program}.",
         "       IDENTIFICATION DIVISION.",
         f"       PROGRAM-ID. {name}.",
         "       DATA DIVISION.",
         "       WORKING-STORAGE SECTION.",
         "       01  JCL-PARM.",
         "           05 JCL-PARM-LENGTH         PIC S9(04) COMP.",
         "           05 JCL-PARM-TEXT           PIC X(100).",
         "       PROCEDURE DIVISION.",
         "           MOVE SPACES TO JCL-PARM-TEXT",
         f"           MOVE {len(parm)} TO JCL-PARM-LENGTH"]
    for start in range(0, len(parm), 30):
        chunk = parm[start:start + 30]
        o.append(f"           MOVE '{chunk.replace(chr(39), chr(39) * 2)}'")
        o.append(f"             TO JCL-PARM-TEXT({start + 1}:{len(chunk)})")
    o += [f"           DISPLAY '{name}: PARM={shown[:30]}' ' LENGTH ' JCL-PARM-LENGTH"
          if len(shown) <= 30 else f"           DISPLAY '{name}: PARM LENGTH ' JCL-PARM-LENGTH",
          f"           CALL '{program}' USING JCL-PARM",
          "           GOBACK.", ""]
    return _cobol_lines("\n".join(o))


def write_harness(cfg: dict, dest: Path) -> list:
    """Write every harness source into dest; return their paths."""
    dest.mkdir(parents=True, exist_ok=True)
    out = [dest / "CEE3ABD.cbl"]
    shutil.copyfile(HARNESS_DIR / "CEE3ABD.cbl", out[0])
    if indexed_files(cfg):
        p = dest / "LOADER.cbl"
        p.write_text(loader_source(cfg), encoding="utf-8", newline="\n")
        out.append(p)
    for i, s in enumerate(cfg["steps"], 1):
        if s.get("parm") is not None:
            p = dest / f"{parm_driver_name(i)}.cbl"
            p.write_text(parm_driver_source(i, s["program"], s["parm"]), encoding="utf-8", newline="\n")
            out.append(p)
    return out


# --- the run ----------------------------------------------------------------------------------------------

def _run(cmd, env=None, cwd=None, ok=(0,)):
    p = subprocess.run([str(c) for c in cmd], env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode("latin-1").replace("\r\n", "\n")
    if p.returncode not in ok:
        raise AnswerKeyError(f"{' '.join(map(str, cmd))} returned {p.returncode}\n{_tail(out)}")
    return p.returncode, out


def to_fixed(src: Path, lrecl: int, fmt="fixed") -> bytes:
    data = Path(src).read_bytes()
    if fmt == "fixed":
        if len(data) % lrecl:
            raise AnswerKeyError(f"{src}: {len(data)} bytes is not a multiple of record_length {lrecl}")
        return data
    if fmt != "lines":
        raise AnswerKeyError(f"{src}: from_format must be 'fixed' or 'lines'")
    recs = []
    for n, line in enumerate(data.splitlines(), 1):
        if len(line) > lrecl:
            raise AnswerKeyError(f"{src} line {n} is {len(line)} bytes, longer than record_length {lrecl}")
        recs.append(line.ljust(lrecl, b" "))
    return b"".join(recs)


def tools_missing() -> list:
    return [t for t in ("cobc", "cobcrun") if not shutil.which(t)]


def build(root: Path, out_rel: str = config.ANSWER_DIR, say=print) -> dict:
    """Run the job in tare.json under GnuCOBOL and write the answer key into out_rel. Returns a summary."""
    cfg = config.load_config(root)
    validate(cfg)
    missing = tools_missing()
    if missing:
        raise AnswerKeyError(f"{', '.join(missing)} not on PATH (GnuCOBOL 3.x; Linux: apt install gnucobol)")
    root = Path(root).resolve()
    work = root / WORK
    if work.exists():
        shutil.rmtree(work)
    lib, data, harness = work / "lib", work / "data", work / "harness"
    for d in (lib, data):
        d.mkdir(parents=True)
    out = (root / out_rel).resolve()
    if out.exists():
        if any(out.iterdir()) and not (out / config.RECORDS).is_file():
            raise AnswerKeyError(f"{out} is not empty and holds no {config.RECORDS}; not replacing it")
        shutil.rmtree(out)
    (out / "input").mkdir(parents=True)
    (out / "logs").mkdir()
    steps_log = []

    def note(line):
        say(line)
        steps_log.append(line)

    cob = cfg["cobol"]
    flags = list(cob.get("flags") or DEFAULT_FLAGS)
    incl = []
    for d in cob.get("copybooks") or []:
        incl += ["-I", str(root / d)]
    hsrc = write_harness(cfg, harness)
    for src in [root / s for s in cob["sources"]] + hsrc:
        if not src.is_file():
            raise AnswerKeyError(f"COBOL source not found: {src}")
        _run(["cobc", "-m", *flags, *incl, src], cwd=lib)
    note(f"compiled {', '.join(Path(s).stem for s in cob['sources'])} with cobc -m {' '.join(flags)}; "
         f"harness: {', '.join(p.stem for p in hsrc)} (generated from tare.json, see {WORK}/harness/)")
    base = dict(os.environ, COB_LIBRARY_PATH=str(lib))
    kinds = {n: f"K{i:02d}" for i, n in enumerate(indexed_files(cfg), 1)}
    where = {}

    def loader(direction, name, seqfile):
        _, o = _run(["cobcrun", "LOADER", direction, kinds[name]],
                    env=dict(base, DD_SEQFILE=str(seqfile), DD_IDXFILE=str(where[name])))
        note(f"{name}: {o.strip()}")

    for name, f in cfg["files"].items():
        indexed = f.get("organization") == "indexed"
        where[name] = data / (f"{name}.idx" if indexed else f"{name}.dat")
        if f.get("from"):
            n = file_length(cfg, name)
            recs = to_fixed(root / f["from"], n, f.get("from_format", "fixed"))
            (out / "input" / f"{name}.dat").write_bytes(recs)
            note(f"{name}: {len(recs) // n} records of {n} bytes from {f['from']}")
            if indexed:
                loader("IN", name, out / "input" / f"{name}.dat")
            else:
                shutil.copyfile(out / "input" / f"{name}.dat", where[name])

    for i, s in enumerate(cfg["steps"], 1):
        env = dict(base, **{f"DD_{dd}": str(where[fn]) for dd, fn in (s.get("dd") or {}).items()})
        prog = s["program"]
        cmd = ["cobcrun", parm_driver_name(i) if s.get("parm") is not None else prog]
        rc, o = _run(cmd, env=env, ok=tuple(s.get("rc") or (0,)))
        log = out / "logs" / f"step{i:02d}_{prog}.log"
        log.write_text(o + f"*** step {i}: {prog} return code {rc}\n", encoding="latin-1", newline="\n")
        note(f"step {i}: {prog}" + (f" PARM='{s['parm']}'" if s.get("parm") is not None else "")
             + f" DD {', '.join(f'{d}={fn}' for d, fn in (s.get('dd') or {}).items())}: return code {rc}")

    counts = {}
    for name in config.outputs(cfg):
        f = cfg["files"][name]
        dst = out / f"{name}.dat"
        if f.get("organization") == "indexed":
            if not where[name].exists():
                raise AnswerKeyError(f"output {name}: the job did not create the indexed file")
            loader("OUT", name, dst)
        else:
            if not where[name].is_file():
                raise AnswerKeyError(f"output {name}: the job did not write {where[name]}")
            shutil.copyfile(where[name], dst)
        counts[name] = len(dst.read_bytes()) // file_length(cfg, name)

    shown = config.rel_to(root, out)
    command = "python -m tare answer-key" + ("" if out_rel == config.ANSWER_DIR else f" --out {shown}")
    progs = ", ".join(s["program"] for s in cfg["steps"])
    records.collect(root, cfg, out, "answer_key", command, f"{shown}/input", notes=[
        f"Produced by the original COBOL ({progs}) under GnuCOBOL (cobc {' '.join(flags)}), run with the steps "
        "and DD names in tare.json; the harness (LOADER, PARM drivers, CEE3ABD) is generated from tare.json.",
        "Each output file is decoded with its layout in tare.json; <file>.dat beside this file holds its bytes."])
    note("records: " + ", ".join(f"{n} {c}" for n, c in counts.items()))
    (out / "steps.log").write_text("\n".join(steps_log) + "\n", encoding="utf-8", newline="\n")
    return {"out": out, "records": counts}


WHERE_FIELDS = ("command", "input")


def compare(committed: Path, fresh: Path, cfg: dict) -> list:
    """Differences between a fresh answer key and the committed one (empty list: identical): records.json
    except where it was written, the input files and the output files byte for byte."""
    diffs = []
    a, b = records.load_side(committed / config.RECORDS), records.load_side(fresh / config.RECORDS)
    for k in sorted(set(a) | set(b)):
        if k not in WHERE_FIELDS and a.get(k) != b.get(k):
            diffs.append(f"records.json field '{k}' differs")
    names = [f"input/{n}.dat" for n in config.inputs(cfg)] + [f"{n}.dat" for n in config.outputs(cfg)]
    for f in names:
        pa, pb = committed / f, fresh / f
        if not pb.is_file():
            diffs.append(f"{f}: not written by the fresh run")
        elif not pa.is_file() or pa.read_bytes() != pb.read_bytes():
            diffs.append(f"{f}: bytes differ")
    return diffs


def main_build(root: Path, out_rel=None) -> int:
    s = build(root, out_rel or config.ANSWER_DIR)
    print(f"wrote {config.rel_to(root, s['out'])}/records.json and the files beside it")
    return 0
