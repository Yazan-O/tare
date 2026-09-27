import datetime
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import config, records

SIDE = config.PORT_SIDE
SOURCES = config.PORT_SOURCES
INPUT = config.INPUT
OUT = "work/runs/local"
SANDBOX = "work/sandbox/local"
PROVENANCE = "provenance.json"
MIN_MAJOR = 17
RUN_TIMEOUT = 600
JDK_ROOTS_NT = (r"C:\Program Files\Eclipse Adoptium\*", r"C:\Program Files\Java\*",
                r"C:\Program Files\Microsoft\jdk-*", r"C:\Program Files\Zulu\*",
                r"C:\Program Files\Amazon Corretto\*")
JDK_ROOTS_POSIX = ("/usr/lib/jvm/*", "/Library/Java/JavaVirtualMachines/*/Contents/Home", "/opt/java/*")


class PortRunError(RuntimeError):
    pass


def _exe(name):
    return name + (".exe" if os.name == "nt" else "")


def _version_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def jdk_version(home: Path) -> str:
    rel = Path(home) / "release"
    if rel.is_file():
        m = re.search(r'^JAVA_VERSION="([^"]+)"', rel.read_text(encoding="utf-8", errors="replace"), re.M)
        if m:
            return m.group(1)
    try:
        r = subprocess.run([str(Path(home) / "bin" / _exe("javac")), "-version"], capture_output=True,
                           text=True, timeout=30)
        m = re.search(r"javac\s+(\S+)", r.stdout + r.stderr)
        return m.group(1) if m else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def jdk_major(home: Path) -> int:
    t = _version_tuple(jdk_version(home))
    if not t:
        return 0
    return t[1] if t[0] == 1 and len(t) > 1 else t[0]


def find_jdk(env=None, min_major=MIN_MAJOR):
    env = os.environ if env is None else env

    def ok(home):
        if home and (Path(home) / "bin" / _exe("javac")).is_file():
            major = jdk_major(Path(home))
            if major >= min_major:
                return Path(home), major, jdk_version(Path(home))
        return None

    hit = ok(env.get("JAVA_HOME"))
    if hit:
        return hit
    on_path = shutil.which("javac", path=env.get("PATH", ""))
    if on_path:
        hit = ok(Path(on_path).resolve().parent.parent)
        if hit:
            return hit
    found = []
    for pat in (JDK_ROOTS_NT if os.name == "nt" else JDK_ROOTS_POSIX):
        for home in glob.glob(pat):
            hit = ok(home)
            if hit:
                found.append(hit)
    return max(found, key=lambda h: _version_tuple(h[2])) if found else None


def input_hashes(root: Path, input_rel=INPUT) -> dict:
    d = root / input_rel
    return {p.name: config.sha256_file(p) for p in sorted(d.iterdir()) if p.is_file()} if d.is_dir() else {}


def write_provenance(root: Path, out_dir: Path, jdk="", main_class="", input_rel=INPUT) -> dict:
    out = Path(out_dir) / config.RECORDS
    prov = {
        "runner": "tare.localport",
        "sources": config.hash_sources(root, SOURCES),
        "main": main_class,
        "input_dir": input_rel,
        "inputs": input_hashes(root, input_rel),
        "output": out.resolve().relative_to(root.resolve()).as_posix() if out.resolve().is_relative_to(
            root.resolve()) else str(out),
        "output_sha256": config.sha256_file(out),
        "jdk": jdk,
        "ran_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (Path(out_dir) / PROVENANCE).write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8", newline="\n")
    return prov


def read_provenance(root: Path):
    p = root / OUT / PROVENANCE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def staleness(root: Path):
    out = root / OUT / config.RECORDS
    prov = read_provenance(root)
    if prov is None:
        return "no run of the port on record (work/runs/local/provenance.json)"
    if not out.is_file():
        return "no work/runs/local/records.json"
    if prov.get("sources") != config.hash_sources(root, SOURCES):
        return "the port's sources changed since its last run"
    if prov.get("input_dir") != INPUT or prov.get("inputs") != input_hashes(root):
        return "the input changed since the port's last run"
    if prov.get("output_sha256") != config.sha256_file(out):
        return "work/runs/local/records.json changed after the port wrote it"
    return None


def _tail(text: str, n=30) -> str:
    return "\n".join((text or "").strip().splitlines()[-n:])


def build_and_run(root: Path, src_rel: str, sandbox_rel: str, out_rel: str, side: str, command: str,
                  input_rel=INPUT):
    log = []
    src = root / src_rel
    out = root / out_rel
    out.mkdir(parents=True, exist_ok=True)
    for stale in [out / config.RECORDS, out / PROVENANCE, *out.glob("*.dat")]:
        stale.unlink(missing_ok=True)
    sources = sorted(p for p in src.rglob("*.java")) if src.is_dir() else []
    if not sources:
        raise PortRunError(f"no .java files under {src}")
    main_file = src / "MAIN"
    if not main_file.is_file():
        raise PortRunError(f"{main_file} is missing; it must hold the main class name on one line")
    main_class = (main_file.read_text(encoding="utf-8").strip().splitlines() or [""])[0].strip()
    inp = root / input_rel
    if not inp.is_dir():
        raise PortRunError(f"input directory not found: {inp} (run python -m tare answer-key first)")
    cfg = config.load_config(root)
    wanted = config.outputs(cfg)
    if not wanted:
        raise PortRunError("tare.json declares no output files")
    jdk = find_jdk()
    if jdk is None:
        raise PortRunError(f"no JDK >= {MIN_MAJOR} found (JAVA_HOME, PATH, and the common install roots)")
    home, major, version = jdk
    log.append(f"JDK: {home} (version {version})")

    box = root / sandbox_rel
    if box.exists():
        shutil.rmtree(box)
    (box / "input").mkdir(parents=True)
    (box / "classes").mkdir()
    for f in sorted(inp.iterdir()):
        if f.is_file():
            shutil.copyfile(f, box / "input" / f.name)

    javac = [str(home / "bin" / _exe("javac")), "-encoding", "UTF-8", "-d", str(box / "classes"),
             *map(str, sources)]
    log.append(f"$ javac -d {sandbox_rel}/classes ({len(sources)} files)")
    r = subprocess.run(javac, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=RUN_TIMEOUT)
    log.append(_tail(r.stdout + r.stderr))
    if r.returncode:
        raise PortRunError("\n".join(x for x in log if x) + f"\njavac exit {r.returncode}")
    java = [str(home / "bin" / _exe("java")), "-cp", "classes", main_class, "--input", "input", "--out", "out"]
    log.append(f"$ (cd {sandbox_rel}) java -cp classes {main_class} --input input --out out")
    r = subprocess.run(java, cwd=box, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=RUN_TIMEOUT)
    log.append(_tail(r.stdout + r.stderr))
    if r.returncode:
        raise PortRunError("\n".join(x for x in log if x) + f"\nthe port exited {r.returncode}")
    written = [n for n in wanted if (box / "out" / f"{n}.dat").is_file()]
    if not written:
        raise PortRunError("\n".join(x for x in log if x) + "\nthe port exited 0 but wrote none of "
                           + ", ".join(f"out/{n}.dat" for n in wanted))
    for n in written:
        shutil.copyfile(box / "out" / f"{n}.dat", out / f"{n}.dat")
    try:
        path = records.collect(root, cfg, out, side, command, input_rel)
    except ValueError as e:
        raise PortRunError("\n".join(x for x in log if x) + f"\nthe port's output does not decode: {e}") from None
    log.append(f"wrote {out_rel}/{config.RECORDS} from {', '.join(f'{n}.dat' for n in written)}")
    return path, "\n".join(x for x in log if x), f"{home} ({version})", main_class


def run_command(root: Path, runner: str, side: str, out_rel: str, input_rel=INPUT, extra=()):
    argv = shlex.split(str(runner))
    if not argv:
        raise PortRunError(f"side {side}: empty runner")
    if Path(argv[0]).name.lower().startswith("python"):
        argv[0] = sys.executable
    out = root / out_rel
    out.mkdir(parents=True, exist_ok=True)
    for stale in [out / config.RECORDS, out / PROVENANCE, *out.glob("*.dat")]:
        stale.unlink(missing_ok=True)
    argv += ["--input", input_rel, "--out", out_rel, *extra]
    r = subprocess.run(argv, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=RUN_TIMEOUT)
    log = (f"$ {runner} --input {input_rel} --out {out_rel}{''.join(' ' + x for x in extra)}  "
           f"(exit {r.returncode})\n" + _tail(r.stdout + r.stderr))
    if r.returncode:
        raise PortRunError(log)
    path = out / config.RECORDS
    if not path.is_file():
        try:
            path = records.collect(root, config.load_config(root), out, side, runner, input_rel)
        except ValueError as err:
            raise PortRunError(f"{log}\nthe side's output does not decode: {err}") from None
    return path, log


def run(root: Path, input_rel=INPUT, out_rel=OUT):
    runner = config.local_entry(config.load_config(root)).get("runner")
    if runner:
        if not any(k.endswith(".java") for k in config.hash_sources(root, SOURCES)):
            raise PortRunError("no port sources under port/ (port/**/*.java); fetch the port under test first")
        inp = root / input_rel
        if not inp.is_dir():
            raise PortRunError(f"input directory not found: {inp} (run python -m tare answer-key first)")
        box = root / SANDBOX
        if box.exists():
            shutil.rmtree(box)
        shutil.copytree(inp, box / "input")
        path, log = run_command(root, runner, SIDE, out_rel, f"{SANDBOX}/input", ("--sandbox", SANDBOX))
        jdk = find_jdk()
        write_provenance(root, root / out_rel, jdk=f"{jdk[0]} ({jdk[2]})" if jdk else "", main_class=runner,
                         input_rel=input_rel)
        return path, log + f"\nwrote {out_rel}/{PROVENANCE}"
    path, log, jdk, main_class = build_and_run(root, "port", SANDBOX, out_rel, SIDE,
                                               "python -m tare run-port local", input_rel)
    write_provenance(root, root / out_rel, jdk=jdk, main_class=main_class, input_rel=input_rel)
    return path, log + f"\nwrote {out_rel}/{PROVENANCE}"
