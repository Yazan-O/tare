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

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
sys.path.insert(0, str(CASE.parents[1]))
from tare import config, localport, records  # noqa: E402
sys.path.insert(0, str(HERE))
import fix_port  # noqa: E402

CACHE = CASE / "cache"
CMS_JAR = CACHE / "cms_java" / "hospice-pricer-application-2.5.1.jar"
AI_ROOT = CACHE / "repos" / "rcaran"
AI_REPO = AI_ROOT / "hospice-pricer-api"
AI_JAR_NAME = "hospice-pricer-api-1.0.0-SNAPSHOT.jar"
AI_MAIN = "com.cms.hospice.HospicePricerApplication"
M2 = CACHE / "m2"
FY = 2021
FY_FIRST, FY_LAST = "20201001", "20210930"
SLOTS = ("rev1", "rev2", "rev3", "rev4")
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


def read_claims(input_dir: Path, cfg: dict) -> list:
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
    return int(round(float(value or 0) * 100))


def encode(record: bytes, result: dict, lay: dict) -> bytes:
    out = bytearray(record)
    for f in lay["fields"]:
        v = result.get(f["name"])
        if v is None:
            if f["name"] in lay["key"]:
                continue
            sys.exit(f"the port returned no {f['name']} for claim {result.get('id')}")
        if f.get("type", "X") == "X":
            text = str(v)[:f["length"]].ljust(f["length"])
        elif f.get("scale"):
            text = f"{money(v):0{f['length']}d}"
        else:
            text = f"{int(v):0{f['length']}d}"
        out[f["offset"]:f["offset"] + f["length"]] = text.encode("latin-1")
    return bytes(out)


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


def build_ai(variant: str, env: dict) -> Path:
    if not (AI_REPO / "pom.xml").is_file():
        sys.exit(f"the AI port is not in {AI_REPO}; run: python fetch.py")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=AI_REPO, capture_output=True, text=True,
                          check=True).stdout.strip()
    want = f"{head} {variant} " + (hashlib.sha256(fix_port.SPEC.read_bytes()).hexdigest()
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
        spec = fix_port.load()
        if spec["commit"] != head:
            sys.exit(f"{fix_port.SPEC.name} is for commit {spec['commit'][:7]}, the port is at {head[:7]}")
        try:
            changed = fix_port.apply(out, spec)
        except fix_port.FixError as e:
            sys.exit(str(e))
        same = [rel for rel in changed if (out / rel).read_bytes() == (AI_ROOT / rel).read_bytes()]
        if same or not changed:
            sys.exit(f"{fix_port.SPEC.name} left {', '.join(same) or 'nothing'} unchanged in {src}")
        print(f"  applied {fix_port.SPEC.name} to {', '.join(changed)}", flush=True)
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
