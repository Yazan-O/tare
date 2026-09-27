import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
DL = CACHE / "dl"
COBOL = CACHE / "cobol"
CMS_JAVA = CACHE / "cms_java"
REPOS = CACHE / "repos"

COBOL_URL = ("https://www.cms.gov/files/zip/"
             "fy-20210-hospice-mf-software-v210-claims-dated-100120-093021-posted-11172020.zip")
COBOL_ZIP = DL / "hospice-21.0-mf.zip"
COBOL_SHA256 = "4b80ad6964d02378431e853d8c716b33500607b9e09ef6d9f8f799459783e467"
COBOL_FILES = {"HOSDR210": "HOSDR210.cbl", "HOSPR210": "HOSPR210.cbl", "HOSPRATE": "HOSPRATE.cpy",
               "CBSA2021": "CBSA2021", "TESTJCL": "TESTJCL"}

CMS_JAR_URL = "https://www.cms.gov/files/zip/hospice-pricer-20250-v240-executable-jar.zip"
CMS_JAR_ZIP = DL / "hospice-pricer-executable-jar.zip"
CMS_ZIP_SHA256 = "6306acd8bc032d7240febc968d0d82ab2be6898ecb42dd3758ecc8e496271b9b"
CMS_SRC_URL = "https://www.cms.gov/files/zip/hospice-pricer-20250-v240-java-source-code.zip"
CMS_SRC_ZIP = DL / "hospice-pricer-20250-v240-java-source-code.zip"
CMS_SRC_SHA256 = "6cdba0a4a0a9c91f3460714aeb0352b9eaedefadff4d2d351c8c60edc532d19c"
CMS_JAR = CMS_JAVA / "hospice-pricer-application-2.5.1.jar"
CMS_JAR_SHA256 = "8463ea46eca855c9c3a2c8eaac2293688f1bc1919c6ce3af3d21b129871c72fe"
CMS_JAR_VERSION = "2.5.1.2025-11-13T21:19:01Z"

AI_URL = "https://github.com/rcaran/hospice-cms-pricer-java.git"
AI_COMMIT = "655847671859b67a188c5dae6a86c45a74bfa046"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, want: str) -> Path:
    if dest.is_file() and sha256(dest) == want:
        print(f"  {dest.relative_to(HERE).as_posix()} ({dest.stat().st_size} bytes, sha256 as pinned)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"download {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    got = sha256(tmp)
    if got != want:
        tmp.unlink()
        sys.exit(f"{url}\n  sha256 {got}\n  expected {want}\n"
                 f"  the file on cms.gov has changed; the case pins the digest it was measured with")
    tmp.replace(dest)
    print(f"  {dest.relative_to(HERE).as_posix()} ({dest.stat().st_size} bytes, sha256 verified)")
    return dest


def fetch_cobol():
    z = download(COBOL_URL, COBOL_ZIP, COBOL_SHA256)
    COBOL.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z) as f:
        for i in f.infolist():
            out = COBOL_FILES.get(i.filename.rsplit("/", 1)[-1])
            if out:
                (COBOL / out).write_bytes(f.read(i))
    missing = [out for out in COBOL_FILES.values() if not (COBOL / out).is_file()]
    if missing:
        sys.exit(f"{COBOL_ZIP.name} holds none of {', '.join(missing)}; the release on cms.gov has changed")
    print(f"  cache/cobol/: {', '.join(COBOL_FILES.values())} (unmodified, as fetched)")


def fetch_cms_java():
    jar_zip = download(CMS_JAR_URL, CMS_JAR_ZIP, CMS_ZIP_SHA256)
    CMS_JAVA.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar_zip) as f:
        f.extract(CMS_JAR.name, CMS_JAVA)
    got = sha256(CMS_JAR)
    if got != CMS_JAR_SHA256:
        sys.exit(f"the JAR inside {CMS_JAR_ZIP.name} has sha256 {got}, expected {CMS_JAR_SHA256}")
    src_zip = download(CMS_SRC_URL, CMS_SRC_ZIP, CMS_SRC_SHA256)
    src = CMS_JAVA / "src"
    if src.is_dir():
        shutil.rmtree(src)
    with zipfile.ZipFile(src_zip) as f:
        for i in f.infolist():
            with zipfile.ZipFile(io.BytesIO(f.read(i))) as inner:
                inner.extractall(src)
    n = len(list(src.rglob("*.java")))
    print(f"  cache/cms_java/{CMS_JAR.name} ({CMS_JAR.stat().st_size} bytes, "
          f"Implementation-Version {CMS_JAR_VERSION}, sha256 verified)")
    print(f"  cache/cms_java/src/: {n} Java source files (the two this case cites are in "
          f"gov/cms/fiss/pricers/hospice/core/rules/)")


def fetch_ai():
    dest = REPOS / "rcaran"
    if not (dest / ".git").is_dir():
        print(f"clone {AI_URL}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", AI_URL, str(dest)], check=True)
    if subprocess.run(["git", "cat-file", "-e", f"{AI_COMMIT}^{{commit}}"], cwd=dest).returncode:
        subprocess.run(["git", "fetch", "--quiet", "origin", AI_COMMIT], cwd=dest, check=True)
    subprocess.run(["git", "-c", "advice.detachedHead=false", "checkout", "--quiet", "--force",
                    AI_COMMIT], cwd=dest, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True,
                          check=True).stdout.strip()
    if head != AI_COMMIT:
        sys.exit(f"the port is at {head}, expected {AI_COMMIT}")
    print(f"  cache/repos/rcaran/ @ {AI_COMMIT} (one squashed commit; no licence file; never committed)")


def build_ai():
    from tare import localport
    sys.path.insert(0, str(HERE / "sides"))
    from port_runner import build_ai as build
    env = dict(os.environ)
    jdk = localport.find_jdk(min_major=21)
    if jdk:
        env["JAVA_HOME"] = str(jdk[0])
    for variant in ("published", "fixed"):
        jar = build(variant, env)
        print(f"  cache/build/{variant}/{jar.relative_to(HERE / 'cache' / 'build' / variant).as_posix()}"
              f" ({jar.stat().st_size} bytes)")


def clean():
    for d in (CACHE / "build", CACHE / "m2"):
        if d.is_dir():
            shutil.rmtree(d)
            print(f"  removed {d.relative_to(HERE).as_posix()}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", action="store_true", help="also build both variants of the AI port with Maven")
    ap.add_argument("--clean", action="store_true", help="delete cache/build and cache/m2")
    a = ap.parse_args()
    if a.clean:
        clean()
        return 0
    sys.path.insert(0, str(HERE.parents[1]))
    fetch_cobol()
    fetch_cms_java()
    fetch_ai()
    if a.build:
        build_ai()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
