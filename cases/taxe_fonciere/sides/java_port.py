import argparse
import glob
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parents[1]))
from tare import localport  # noqa: E402

PORT = HERE / "cache" / "repos" / "omnipede" / "taxe-fonciere-java"
LOCAL = HERE / "port" / "taxe-fonciere-java"
ADAPTER = Path(__file__).resolve().parent / "java" / "TareJavaSide.java"
JAR = "target/taxe-fonciere-java-1.0.0.jar"
CALC = "src/main/java/fr/dgfip/taxefonciere/calculator/BuiltPropertyCalculator.java"
RET = "src/main/java/fr/dgfip/taxefonciere/model/output/RetourB.java"
FIXES = {
    "fixed": [
        (CALC, "FRAIS_300_FRS = DecimalUtils.of(0.0800, 4);  // 8%", "FRAIS_300_FRS = DecimalUtils.of(0.0300, 4);  // 3%"),
        (CALC, "FRAIS_300_ARN = DecimalUtils.of(0.0440, 4);  // 4.4%", "FRAIS_300_ARN = DecimalUtils.of(0.0100, 4);  // 1%"),
        (CALC, "FRAIS_800_FRS = DecimalUtils.of(0.0300, 4);  // 3%", "FRAIS_800_FRS = DecimalUtils.of(0.0800, 4);  // 8%"),
        (CALC, "FRAIS_800_ARN = DecimalUtils.of(0.0100, 4);  // 1%", "FRAIS_800_ARN = DecimalUtils.of(0.0440, 4);  // 4.4%"),
        (RET, "tcthfr = tcthfr.add(mcibt13[1] != null ? mcibt13[1] : BigDecimal.ZERO);",
         "tcthfr = tcthfr.add(mcibt13[1] != null ? mcibt13[1] : BigDecimal.ZERO);{nl}"
         "        tcthfr = tcthfr.add(tctom != null ? tctom : BigDecimal.ZERO);  // household-waste tax"),
    ],
    "ai": [],
    "local": [],
}


def find_mvn() -> str:
    for name in ("mvn.cmd", "mvn") if os.name == "nt" else ("mvn",):
        hit = shutil.which(name)
        if hit:
            return hit
    homes = [os.environ.get("MAVEN_HOME", ""), os.environ.get("M2_HOME", "")] + sorted(
        glob.glob("C:/Tools/apache-maven-*") + glob.glob("/opt/apache-maven-*") + glob.glob("/usr/share/maven"))
    for h in homes:
        for name in ("mvn.cmd", "mvn") if os.name == "nt" else ("mvn",):
            p = Path(h) / "bin" / name
            if h and p.is_file():
                return str(p)
    sys.exit("Maven not found (PATH, MAVEN_HOME, C:/Tools/apache-maven-*)")


def run(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, errors="replace", **kw)
    if r.returncode:
        sys.exit(f"$ {' '.join(map(str, cmd))} (exit {r.returncode})\n{(r.stdout + r.stderr)[-3000:]}")
    return r.stdout


def build_dir(variant: str, sandbox) -> Path:
    return Path(sandbox).resolve() / "build" if variant == "local" else HERE / "cache" / "build" / variant


def build(variant: str, env: dict, sandbox=None) -> Path:
    origin = LOCAL if variant == "local" else PORT
    if not (origin / "pom.xml").is_file():
        sys.exit(f"the Java port is not in {origin}; run: python fetch.py" + (" --local" if variant == "local" else ""))
    out = build_dir(variant, sandbox)
    stamp = hashlib.sha256(repr((variant, FIXES[variant])).encode()).hexdigest()
    src = out / "taxe-fonciere-java"
    if variant != "local" and (src / JAR).is_file() and (out / "stamp").is_file()             and (out / "stamp").read_text() == stamp:
        return src / JAR
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(origin, src, ignore=shutil.ignore_patterns("target", ".git"))
    for rel, old, new in FIXES[variant]:
        p = src / rel
        text = p.read_bytes().decode("utf-8")
        if text.count(old) != 1:
            sys.exit(f"fix not applied: {rel} holds {text.count(old)} copies of {old!r}")
        nl = "\r\n" if "\r\n" in text else "\n"
        p.write_bytes(text.replace(old, new.replace("{nl}", nl)).encode("utf-8"))
    print(f"mvn package ({variant}, tests skipped; {len(FIXES[variant])} edits applied)", flush=True)
    run([find_mvn(), "-q", "-B", "-DskipTests", "package"], cwd=src, env=env)
    (out / "stamp").write_text(stamp)
    return src / JAR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=sorted(FIXES), required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sandbox", help="build and scratch folder (the local variant needs it)")
    a = ap.parse_args()
    if a.variant == "local" and not a.sandbox:
        sys.exit("--variant local needs --sandbox")
    jdk = localport.find_jdk()
    if jdk is None:
        sys.exit("no JDK >= 17 found")
    home = jdk[0]
    env = dict(os.environ, JAVA_HOME=str(home))
    jar = build(a.variant, env, a.sandbox)
    work = build_dir(a.variant, a.sandbox)
    classes = work / "adapter"
    classes.mkdir(parents=True, exist_ok=True)
    run([home / "bin" / localport._exe("javac"), "-encoding", "UTF-8", "-cp", jar, "-d", classes, ADAPTER])
    cp = os.pathsep.join([str(jar), str(classes)])
    print(run([home / "bin" / localport._exe("java"), "-cp", cp, "TareJavaSide", Path(a.input).resolve(),
               Path(a.out).resolve(), work / "scratch"]).strip())


if __name__ == "__main__":
    main()
