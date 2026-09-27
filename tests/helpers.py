import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "unitsum"


def load(rel: str) -> dict:
    return json.loads((EXAMPLE / rel).read_text(encoding="utf-8"))


ANSWER = "fixtures/answer_key/records.json"
BALANCED = "fixtures/sides/exact/records.json"
RED = "fixtures/sides/halfup/records.json"


def has_cobc() -> bool:
    return all(shutil.which(t) for t in ("cobc", "cobcrun"))


def has_jdk() -> bool:
    from tare import localport
    return localport.find_jdk() is not None


class Sandbox:
    def __init__(self, with_port=True, port=None):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        shutil.copy(EXAMPLE / "tare.json", self.root / "tare.json")
        for sub in ("mainframe", "fixtures", "ports"):
            shutil.copytree(EXAMPLE / sub, self.root / sub)
        (self.root / "port").mkdir()
        if port:
            self.use_port(port)
        elif with_port:
            (self.root / "port" / "Port.java").write_text("class Port {}\n", encoding="utf-8")
            (self.root / "port" / "MAIN").write_text("Port\n", encoding="utf-8")

    def use_port(self, name):
        for f in (self.root / "port").glob("*"):
            f.unlink()
        for f in (EXAMPLE / "ports" / name).iterdir():
            shutil.copy(f, self.root / "port" / f.name)

    def put_run(self, side, doc):
        if isinstance(doc, str):
            doc = load(doc)
        d = self.root / "work" / "runs" / side
        d.mkdir(parents=True, exist_ok=True)
        (d / "records.json").write_text(json.dumps(dict(doc, side=side)), encoding="utf-8")
        if side == "local":
            from tare import localport
            localport.write_provenance(self.root, d, jdk="test double (no JDK run)")

    def java_port(self, body: str, cls="Port"):
        for f in (self.root / "port").glob("*"):
            f.unlink()
        src = "\n".join([
            "import java.nio.file.*;", "import java.io.*;", "import java.util.*;",
            f"public class {cls} {{",
            "  public static void main(String[] a) throws Exception {",
            "    String out = null;",
            '    for (int i = 0; i < a.length - 1; i++) if (a[i].equals("--out")) out = a[i + 1];',
            "    Files.createDirectories(Paths.get(out));",
            "    " + body,
            "  }", "}", ""])
        (self.root / "port" / f"{cls}.java").write_text(src, encoding="utf-8")
        (self.root / "port" / "MAIN").write_text(cls + "\n", encoding="utf-8")

    def git_init(self):
        self.git_env = dict(self.env(), GIT_CONFIG_NOSYSTEM="1",
                            GIT_CONFIG_GLOBAL=str(self.root / "work" / "no-gitconfig"),
                            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                            GIT_COMMITTER_EMAIL="t@t")
        (self.root / ".gitignore").write_text("/work/\n/.tare/\n__pycache__/\n", encoding="utf-8")
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
            r = self.git(*args)
            assert r.returncode == 0, r.stderr

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, env=getattr(self, "git_env", self.env()),
                              capture_output=True, text=True)

    def env(self):
        e = dict(os.environ)
        e["PYTHONPATH"] = str(REPO)
        e.pop("TARE_ROOT", None)
        e.pop("TARE_MAINTAINER", None)
        e.pop("GITHUB_STEP_SUMMARY", None)
        return e

    def tare(self, *args, env=None):
        return subprocess.run([sys.executable, "-m", "tare", *args], cwd=self.root, env=env or self.env(),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)

    def gate(self, payload):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, str(REPO / ".bob" / "hooks" / "gate.py")], cwd=self.root,
                              env=self.env(), input=data, capture_output=True, text=True)

    def cfg(self) -> dict:
        return json.loads((self.root / "tare.json").read_text(encoding="utf-8"))

    def close(self):
        self.dir.cleanup()
