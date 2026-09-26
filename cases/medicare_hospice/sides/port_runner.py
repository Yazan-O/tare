"""Side runner for the two Java ports (tare.json 'sides'): price the answer key's claims through one of
them and write the 315-byte RATEFILE records Tare weighs.

  --which cms                       CMS's own Java migration, Hospice Pricer 2.5.1 (the executable JAR
                                    fetched into cache/cms_java by fetch.py), started as a Dropwizard
                                    server with its 2021 tables and priced over POST /v2/price-claim
  --which ai --variant published    rcaran/hospice-cms-pricer-java as published, built with Maven
  --which ai --variant fixed        the same commit with sides/ai-port-fixes.patch applied, built
                                    with Maven into cache/build/fixed/

Tare runs it from the case root with --input <answer key input dir> --out work/runs/<side>. It reads
<input>/billfile.dat with the BILL315 layout and writes <out>/ratefile.dat in the RATE315 layout: every
315-byte record of the input is written back whole with the pricer's returned amounts, return code and
day counts in their COBOL slots, exactly as harness/HOSRUN.cbl writes back what HOSDR210 returns. The
claim id in the record's trailing FILLER is never touched, so the weigh matches records by it.

Every field offset comes from tare.json's layouts; this file holds none of its own. Neither port is
committed: the CMS JAR and the AI port live under cache/ and are fetched at run time. Needs a JDK >= 21
(the AI port targets 21) and, for the AI port, Maven.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent              # the case folder
CASE = HERE.parent
sys.path.insert(0, str(CASE.parents[1]))
from tare import config, localport, records  # noqa: E402

CACHE = CASE / "cache"
CMS_JAR = CACHE / "cms_java" / "hospice-pricer-application-2.5.1.jar"
AI_ROOT = CACHE / "repos" / "rcaran"                     # the port's root, as cloned
AI_REPO = AI_ROOT / "hospice-pricer-api"               # its Maven module
PATCH = HERE / "ai-port-fixes.patch"
AI_JAR_NAME = "hospice-pricer-api-1.0.0-SNAPSHOT.jar"
AI_MAIN = "com.cms.hospice.HospicePricerApplication"
M2 = CACHE / "m2"                                    # the Maven repository, inside the git-ignored cache
# FY2021 is the only fiscal year in the input (every claim's service date is 2020-10-01..2021-09-30),
# so CMS's server is started with that year's tables; its pricer.yml lists 2020-2026 by default.
FY = 2021
FY_FIRST, FY_LAST = "20201001", "20210930"
SLOTS = ("rev1", "rev2", "rev3", "rev4")
# The four per-level-of-care payments, in COBOL slot order: 0651 routine home care, 0652 continuous
# home care, 0655 inpatient respite care, 0656 general inpatient care. Every port returns them in that
# order (the revenue code CMS's Java labels each with follows the claim's own billing order instead).
PAY = ("pay_rhc", "pay_chc", "pay_irc", "pay_gic")


def find_mvn() -> str:
    for name in ("mvn.cmd", "mvn") if os.name == "nt" else ("mvn",):
        hit = shutil.which(name)
        if hit:
            return hit
    homes = [os.environ.get("MAVEN_HOME", ""), os.environ.get("M2_HOME", "")] + sorted(
        glob.glob("C:/Tools/apache-maven-*") + glob.glob("/opt/apache-maven-*") + glob.glob("/usr/share/maven"))
    for h in homes:
        for name in ("mvn.cmd", "mvn") if os.name == "nt" else ("mvn",):
            p = Path(h) / "bin" / name if h else None
            if p and p.is_file():
                return str(p)
    sys.exit("Maven not found (PATH, MAVEN_HOME, C:/Tools/apache-maven-*); needed to build the AI port")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- the claims, read and written through the layouts in tare.json ------------------------------------

def read_claims(input_dir: Path, cfg: dict) -> list:
    """The input records as claims (each keeping its 315 bytes), with the fiscal year checked."""
    lay = config.layout_for(cfg, "billfile")
    data = (Path(input_dir) / "billfile.dat").read_bytes()
    out = []
    for i, r in enumerate(records.decode_bytes(data, lay, str(input_dir))):
        if not FY_FIRST <= r["from_date"] <= FY_LAST:
            sys.exit(f"record {i + 1} ({r['claim']}): service date {r['from_date']} is outside FY{FY} "
                     f"({FY_FIRST}..{FY_LAST}); rebuild the input with build_input.py")
        lines = [dict(slot=n, revenueCode=r[slot], dateOfService=r[f"dos{n}"], units=int(r[f"units{n}"]))
                 for n, slot in enumerate(SLOTS, 1) if r[slot].strip()]
        out.append(dict(id=r["claim"], raw=data[i * lay["record_length"]:(i + 1) * lay["record_length"]],
                        npi=r["npi"], ccn=r["prov_no"], from_date=r["from_date"],
                        admission=r["admission_date"], prov_cbsa=r["prov_cbsa"], bene_cbsa=r["bene_cbsa"],
                        prior=int(r["na_addon_day1_units"]), qip=r["qip"],
                        eol=[int(r[f"eol_addon_day{d}_units"]) for d in range(1, 8)], lines=lines))
    return out


def money(value) -> int:
    """A payment as the integer cents its PIC 9(06)V99 field holds."""
    return int(round(float(value or 0) * 100))


def encode(record: bytes, result: dict, lay: dict) -> bytes:
    """The claim's 315-byte record with the pricer's fields written into their COBOL slots.

    The input record is the base, because the pricer returns the same 315-byte record it was given with
    its own fields filled in: every byte the pricer does not write (the claim id, the bill itself) is
    carried through unchanged, exactly as HOSRUN writes back what HOSDR210 returns."""
    out = bytearray(record)
    for f in lay["fields"]:
        v = result.get(f["name"])
        if v is None:
            if f["name"] in lay["key"]:
                continue                            # the claim id, already in the record
            sys.exit(f"the port returned no {f['name']} for claim {result.get('id')}")
        if f.get("type", "X") == "X":
            text = str(v)[:f["length"]].ljust(f["length"])
        elif f.get("scale"):
            text = f"{money(v):0{f['length']}d}"          # PIC 9(06)V99 holds integer cents
        else:
            text = f"{int(v):0{f['length']}d}"
        out[f["offset"]:f["offset"] + f["length"]] = text.encode("latin-1")
    return bytes(out)


# --- the two ports ------------------------------------------------------------------------------------

def post(url: str, body: dict, tries: int = 1) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode("latin-1"),
                                 {"Content-Type": "application/json", "Accept": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            sys.exit(f"HTTP {e.code} from {url}: {e.read().decode(errors='replace')[:400]}")
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            if attempt + 1 == tries:
                sys.exit(f"{url} not reachable after {tries} tries: {e}")
            time.sleep(2)
    raise AssertionError("unreachable")


def iso(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


class Server:
    """A port's HTTP server: start it, wait for the port, yield, stop it."""

    def __init__(self, argv, port: int, log: Path):
        self.argv, self.port, self.log = argv, port, log
        self.p = self.fh = None

    def __enter__(self):
        print(f"  $ {' '.join(str(a) for a in self.argv)}", flush=True)
        self.fh = open(self.log, "w", encoding="utf-8", errors="replace")
        self.p = subprocess.Popen([str(a) for a in self.argv], stdout=self.fh, stderr=subprocess.STDOUT)
        for _ in range(120):
            if self.p.poll() is not None:
                sys.exit(f"the server exited {self.p.returncode} before answering; see {self.log}")
            with socket.socket() as s:
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return self
            time.sleep(1)
        sys.exit(f"the server did not open port {self.port} within 120s; see {self.log}")

    def __exit__(self, *exc):
        if self.p and self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(30)
            except subprocess.TimeoutExpired:
                self.p.kill()
        self.fh.close()
        return False


def patched_files() -> list:
    """The files ai-port-fixes.patch touches, read out of the patch itself."""
    return [l[len("+++ b/"):].strip() for l in PATCH.read_text(encoding="utf-8").splitlines()
            if l.startswith("+++ b/")]


def build_ai(variant: str, env: dict) -> Path:
    """The AI port's jar for this variant, built once per (commit, patch) under cache/build/<variant>/."""
    if not (AI_REPO / "pom.xml").is_file():
        sys.exit(f"the AI port is not in {AI_REPO}; run: python fetch.py")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=AI_REPO, capture_output=True, text=True,
                          check=True).stdout.strip()
    want = f"{head} {variant} " + (hashlib.sha256(PATCH.read_bytes()).hexdigest()
                                  if variant == "fixed" else "-")
    out = CACHE / "build" / variant
    src, stamp = out / "hospice-pricer-api", out / "stamp"
    jar = src / "target" / AI_JAR_NAME
    if stamp.is_file() and stamp.read_text().strip() == want and jar.is_file():
        return jar
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(AI_REPO, src, ignore=shutil.ignore_patterns("target", ".git"))
    if variant == "fixed":
        # The copy gets a repository of its own: git apply resolves a patch's paths against the
        # enclosing work tree, and cache/ sits inside this one, where the port's paths do not exist.
        subprocess.run(["git", "init", "-q", str(out)], check=True)
        r = subprocess.run(["git", "apply", "--verbose", str(PATCH)], cwd=out, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"{PATCH.name} did not apply to the port at {head}:\n{r.stdout}{r.stderr}")
        # git apply outside the port's own repository can succeed and change nothing: check it did
        want_changed = patched_files()                       # paths relative to the port's root
        same = [rel for rel in want_changed if (out / rel).read_bytes() == (AI_ROOT / rel).read_bytes()]
        if same or not want_changed:
            sys.exit(f"{PATCH.name} reported success but left {', '.join(same) or 'nothing'} unchanged "
                     f"in {src}")
        print(f"  applied {PATCH.name} to {', '.join(want_changed)}", flush=True)
    print(f"  mvn package ({variant}; tests and coverage skipped; Maven repository {M2.name}/)", flush=True)
    r = subprocess.run([find_mvn(), "-q", "-B", f"-Dmaven.repo.local={M2}", "-DskipTests", "-Djacoco.skip=true",
                        "package"], cwd=src, env=env, capture_output=True, text=True, errors="replace")
    if r.returncode:
        sys.exit(f"mvn package failed ({variant}):\n{(r.stdout + r.stderr)[-3000:]}")
    if not jar.is_file():
        sys.exit(f"mvn package produced no {AI_JAR_NAME} ({variant})")
    stamp.write_text(want, encoding="utf-8")
    return jar


def price_cms(claims: list, port: int, jdk: Path, log: Path) -> list:
    if not CMS_JAR.is_file():
        sys.exit(f"{CMS_JAR} is missing; run: python fetch.py")
    argv = [jdk / "bin" / localport._exe("java"), "--add-opens", "java.base/java.lang=ALL-UNNAMED",
            f"-Ddw.supportedYears={FY}", f"-Ddw.server.applicationConnectors[0].port={port}",
            f"-Ddw.server.adminConnectors[0].port={free_port()}", "-jar", CMS_JAR, "server"]
    url = f"http://localhost:{port}/v2/price-claim"

    def one(c):
        data = dict(providerCcn=c["ccn"], serviceFromDate=iso(c["from_date"]), admissionDate=iso(c["admission"]),
                    providerCbsa=c["prov_cbsa"], patientCbsa=c["bene_cbsa"], priorBenefitDayUnits=c["prior"],
                    endOfLifeAddOnDaysUnits=c["eol"],
                    billingGroups=[dict(revenueCode=x["revenueCode"], dateOfService=iso(x["dateOfService"]),
                                        units=x["units"]) for x in c["lines"]])
        if c["qip"].strip():
            data["reportingQualityData"] = c["qip"]
        return c, post(url, dict(claimData=data), tries=3 if c["id"] == claims[0]["id"] else 1)

    out = []
    with Server(argv, port, log), ThreadPoolExecutor(8) as ex:
        for c, js in ex.map(one, claims):
            pay = js.get("paymentData") or {}
            # CMS's Java returns the four level-of-care amounts in COBOL slot order, so they are read
            # positionally; the revenue code it labels each with follows the claim's own billing order.
            bills = (pay.get("billPayments") or [])[:4]
            eol = [0.0] * 7
            for e in pay.get("endOfLifeAddOnDaysPayments") or []:
                eol[int(e["index"]) - 1] = float(e["payment"])
            out.append((c, dict(id=c["id"], total=float(pay.get("totalPayment") or 0),
                                **{name: float(b["amount"]) for name, b in zip(PAY, bills)},
                                rtc=str((js.get("returnCodeData") or {}).get("code") or ""),
                                high=int(pay.get("highRoutineHomeCareDays") or 0),
                                low=int(pay.get("lowRoutineHomeCareDays") or 0),
                                **{f"eol_{d + 1}": eol[d] for d in range(7)})))
    return out


def price_ai(claims: list, port: int, jdk: Path, variant: str, env: dict, log: Path) -> list:
    jar = build_ai(variant, env)
    url = f"http://localhost:{port}/api/v1/hospice/price"

    def one(c):
        body = dict(providerNumber=c["ccn"], npi=c["npi"], fromDate=c["from_date"], admissionDate=c["admission"],
                    providerCbsa=c["prov_cbsa"], beneficiaryCbsa=c["bene_cbsa"], priorBenefitDays=c["prior"],
                    priorBenefitDays2=0, qipIndicator=c["qip"], eolAddOnDayUnits=c["eol"],
                    lineItems=[dict(slot=x["slot"], revenueCode=x["revenueCode"],
                                    dateOfService=x["dateOfService"], units=x["units"]) for x in c["lines"]])
        return c, post(url, body, tries=3 if c["id"] == claims[0]["id"] else 1)

    out = []
    with Server([jdk / "bin" / localport._exe("java"), "-jar", jar, f"--server.port={port}"],
                port, log), ThreadPoolExecutor(8) as ex:
        for c, js in ex.map(one, claims):
            pays = [float(x) for x in (js.get("eolAddOnDayPayments") or [])][:7]
            pays += [0.0] * (7 - len(pays))
            out.append((c, dict(id=c["id"], total=float(js.get("payAmountTotal") or 0),
                                pay_rhc=float(js.get("payAmt1") or 0),
                                pay_chc=float(js.get("payAmt2") or 0), pay_irc=float(js.get("payAmt3") or 0),
                                pay_gic=float(js.get("payAmt4") or 0), rtc=str(js.get("returnCode") or ""),
                                high=int(js.get("highRhcDays") or 0), low=int(js.get("lowRhcDays") or 0),
                                **{f"eol_{d + 1}": pays[d] for d in range(7)})))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=("cms", "ai"), required=True)
    ap.add_argument("--variant", choices=("published", "fixed"), default="published")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    jdk = localport.find_jdk(min_major=21)
    if jdk is None:
        sys.exit("no JDK >= 21 found (the AI port targets Java 21; set JAVA_HOME)")
    home = jdk[0]
    env = dict(os.environ, JAVA_HOME=str(home))
    cfg = config.load_config(CASE)
    out_lay = config.layout_for(cfg, "ratefile")
    claims = read_claims(Path(a.input), cfg)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log = out / f"{a.which}{'-' + a.variant if a.which == 'ai' else ''}-server.log"
    print(f"{a.which} {a.variant}: pricing {len(claims)} claims from {a.input}", flush=True)
    t0 = time.time()
    port = free_port()
    results = (price_cms(claims, port, home, log) if a.which == "cms"
               else price_ai(claims, port, home, a.variant, env, log))
    raw = {c["id"]: c["raw"] for c in claims}
    recs = [encode(raw[c["id"]], r, out_lay) for c, r in results]
    if len({r[307:315] for r in recs}) != len(recs):
        sys.exit("two claims share an id; the output records cannot be matched to the input")
    (out / "ratefile.dat").write_bytes(b"".join(recs))
    print(f"wrote {out / 'ratefile.dat'}: {len(recs)} records in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
