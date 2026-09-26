"""Fetch the third-party pieces of this case into cache/ (git-ignored) at pinned commits.

The COBOL and the Java port are under CeCILL-2.1; they are fetched at run time and never committed to this
MIT repository. Only the built-property ("bati") calculator of 2018 is used:

  cache/cobol/   CTXTA3B.cob, EFITA3B8.cob, EFITAUX2.cob and the copybooks they include, exported from
                 etalab/taxe-fonciere @ COBOL_COMMIT (nothing else from that repository is checked out)
  cache/repos/omnipede/   omnipede/taxe-fonciere @ JAVA_COMMIT; the port is its taxe-fonciere-java/ folder

  python fetch.py          the two repositories (the demo input under input/ is committed)
  python fetch.py --full   also REI 2018 from data.gouv.fr, converted to CSV, and the national case under
                           full/ (35,389 communes): cd full && python -m tare reproduce
"""
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
# The built-property path of 2018: the router, the calculator, the rate reader, and their copybooks.
COBOL_FILES = ["CTXTA3B.cob", "EFITA3B8.cob", "EFITAUX2.cob",
               "XCOMBAT.cpy", "XRETB.cpy", "XBASEB.cpy", "XCOTB.cpy",
               "XBXTDAN.cpy", "XBXTDDIR.cpy", "XBXTDCOM.cpy", "XBXTDSR.cpy",
               "T800.cpy", "T84D.cpy", "T84C.cpy", "T84R.cpy", "LICENSE"]
# REI 2018, the commune-level local-tax statistics published by DGFiP (Licence Ouverte 2.0).
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
    """full/: the same case on every commune; paths in tare.json point back to this folder."""
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
    (full / "tare.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                    newline="\n")
    print("  full/tare.json and full/input/: cd full && python -m tare reproduce")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="also fetch REI 2018 and write the national case, full/")
    a = ap.parse_args()
    fetch_cobol()
    fetch_java()
    if a.full:
        fetch_rei()
        write_full_case()


if __name__ == "__main__":
    main()
