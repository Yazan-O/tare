import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
COBOL_REPO = "https://github.com/etalab/taxe-fonciere.git"
COBOL_COMMIT = "6bd40b2d78eaeb3f2635fbd7a9eb1f952d0739ba"
JAVA_REPO = "https://github.com/omnipede/taxe-fonciere.git"
JAVA_COMMIT = "5124d1c07942e362922663e52dd8f2e641fb0e47"
LOCAL = HERE / "port"
LOCAL_BRANCH = "tare-local"
COBOL_FILES = ["CTXTA3B.cob", "EFITA3B8.cob", "EFITAUX2.cob",
               "XCOMBAT.cpy", "XRETB.cpy", "XBASEB.cpy", "XCOTB.cpy",
               "XBXTDAN.cpy", "XBXTDDIR.cpy", "XBXTDCOM.cpy", "XBXTDSR.cpy",
               "T800.cpy", "T84D.cpy", "T84C.cpy", "T84R.cpy", "LICENSE"]
REI_DATASET = ("https://www.data.gouv.fr/datasets/impots-locaux-fichier-de-recensement-des-elements-"
               "dimposition-a-la-fiscalite-directe-locale-rei-4")
REI_URL = ("https://data.economie.gouv.fr/api/v2/catalog/datasets/impots-locaux-fichier-de-recensement-des-"
           "elements-dimposition-a-la-fiscalite-dir/attachments/rei_2018_fichier_notice_trace_zip")
REI_ZIP = CACHE / "rei" / "REI-2018-fichier-notice-trace.zip"
REI_XLSX = "REI_2018.xlsx"
REI_CSV = CACHE / "rei" / "REI_2018.csv"


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    if r.returncode:
        sys.exit(f"git {' '.join(args)} failed:\n{r.stderr.decode(errors='replace')}")
    return r.stdout


def clone(url: str, dest: Path, commit: str, checkout: bool):
    if not (dest / ".git").is_dir():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"clone {url}")
        git("clone", "--quiet", "--no-checkout", url, str(dest))
    if subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=dest).returncode:
        git("fetch", "--quiet", "origin", commit, cwd=dest)
    if checkout:
        git("-c", "advice.detachedHead=false", "checkout", "--quiet", "--force", commit, cwd=dest)
    print(f"  {dest.relative_to(HERE).as_posix()} @ {commit}")


def fetch_cobol():
    repo = CACHE / "repos" / "etalab"
    clone(COBOL_REPO, repo, COBOL_COMMIT, checkout=False)
    out = CACHE / "cobol"
    out.mkdir(parents=True, exist_ok=True)
    for name in COBOL_FILES:
        path = name if name == "LICENSE" else f"src/{name}"
        (out / name).write_bytes(git("show", f"{COBOL_COMMIT}:{path}", cwd=repo))
    print(f"  exported {len(COBOL_FILES)} files to cache/cobol/ (built-property path only)")


def fetch_java():
    clone(JAVA_REPO, CACHE / "repos" / "omnipede", JAVA_COMMIT, checkout=True)


def fetch_local(reset=False):
    if (LOCAL / ".git").is_dir() and not reset:
        head = git("rev-parse", "--short", "HEAD", cwd=LOCAL).decode().strip()
        print(f"  port/ exists (HEAD {head}); left as it is (--reset-local puts it back at {JAVA_COMMIT[:7]})")
    else:
        if not (LOCAL / ".git").is_dir():
            if LOCAL.exists() and any(LOCAL.iterdir()):
                sys.exit(f"{LOCAL} exists and is not a git clone; move it away first")
            print("clone the Java port into port/")
            git("clone", "--quiet", "--no-checkout", str(CACHE / "repos" / "omnipede"), str(LOCAL))
            git("remote", "set-url", "origin", JAVA_REPO, cwd=LOCAL)
        git("-c", "advice.detachedHead=false", "checkout", "--quiet", "--force", "-B", LOCAL_BRANCH, JAVA_COMMIT,
            cwd=LOCAL)
        git("clean", "--quiet", "-fdx", cwd=LOCAL)
        print(f"  port/ @ {JAVA_COMMIT} on branch {LOCAL_BRANCH} (the published port, CeCILL-2.1; git-ignored)")
    sys.path.insert(0, str(HERE.parents[1]))
    from tare import githooks
    githooks.install(HERE, repo=LOCAL)


def fetch_rei():
    if not REI_ZIP.is_file():
        REI_ZIP.parent.mkdir(parents=True, exist_ok=True)
        print(f"download {REI_URL}")
        tmp = REI_ZIP.with_suffix(".part")
        with urllib.request.urlopen(REI_URL) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        tmp.replace(REI_ZIP)
    print(f"  {REI_ZIP.relative_to(HERE).as_posix()} ({REI_ZIP.stat().st_size} bytes)")
    if REI_CSV.is_file():
        return
    try:
        import openpyxl
    except ImportError:
        sys.exit("--full needs openpyxl to read REI_2018.xlsx: pip install openpyxl")
    import csv
    xlsx = REI_CSV.with_suffix(".xlsx")
    with zipfile.ZipFile(REI_ZIP) as z, z.open(REI_XLSX) as src, open(xlsx, "wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
    print(f"convert {REI_XLSX} to CSV (a few minutes)")
    wb = openpyxl.load_workbook(xlsx, read_only=True)
    tmp = REI_CSV.with_suffix(".part")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        for row in wb.worksheets[0].iter_rows(values_only=True):
            w.writerow(["" if v is None else v for v in row])
    wb.close()
    tmp.replace(REI_CSV)
    xlsx.unlink()
    print(f"  {REI_CSV.relative_to(HERE).as_posix()}")


def write_full_case():
    full = HERE / "full"
    subprocess.run([sys.executable, str(HERE / "build_input.py"), str(REI_CSV), "--out", str(full / "input")],
                   check=True)
    cfg = json.loads((HERE / "tare.json").read_text(encoding="utf-8"))
    cfg["about"] = cfg["about"] + " FULL RUN: every commune in REI 2018 (built by fetch.py --full)."
    cob = cfg["cobol"]
    cob["sources"] = ["../" + s for s in cob["sources"]]
    cob["copybooks"] = ["../" + s for s in cob["copybooks"]]
    for side in cfg["sides"].values():
        side["runner"] = side["runner"].replace("sides/", "../sides/", 1)
        if side.get("source"):
            side["source"] = "../" + side["source"]
        for cause in side.get("causes") or []:
            cause["cobol"] = ["../" + c for c in cause["cobol"]]
    (full / "tare.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                    newline="\n")
    print("  full/tare.json and full/input/: cd full && python -m tare reproduce")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="also fetch REI 2018 and write the national case, full/")
    ap.add_argument("--local", action="store_true", help="also make port/ a clone of the Java port (the port "
                                                         "under test), with the gate's git hooks")
    ap.add_argument("--reset-local", action="store_true", help="put port/ back at the published commit")
    a = ap.parse_args()
    fetch_cobol()
    fetch_java()
    if a.local or a.reset_local:
        fetch_local(reset=a.reset_local)
    if a.full:
        fetch_rei()
        write_full_case()


if __name__ == "__main__":
    main()
