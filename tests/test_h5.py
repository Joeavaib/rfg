import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RFG = [sys.executable, str(ROOT / "rfg.py")]
GO = ROOT / "testdata" / "fixture"
CGO = ROOT / "testdata" / "cgoedge"


class H5Test(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-h5-")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(ROOT)
        self.env["PATH"] = "/usr/bin:/bin"

    def rfg(self, *args, code=0):
        r = subprocess.run(
            RFG + ["--root", self.td, *args],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def test_scan_without_scanner_or_command_is_4(self):
        Path(self.td, "go.mod").write_text("module m\n")
        self.rfg("init")
        r = subprocess.run(
            RFG + ["--root", self.td, "scan", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)

    def test_scan_runs_security_oracle_command(self):
        Path(self.td, "go.mod").write_text("module m\n")
        self.rfg("init")
        self.rfg("plan", "--profile", "security", "--oracle-cmd", "python3 -c \"raise SystemExit(0)\"")
        out = json.loads(self.rfg("scan", "--format", "json"))
        self.assertTrue(out["data"]["ran"])

    def test_sbom_from_go_mod(self):
        Path(self.td, "go.mod").write_text(
            "module example.com/app\n\ngo 1.22\n\nrequire github.com/foo/bar v1.2.3\n"
        )
        self.rfg("init")
        out = json.loads(self.rfg("sbom", "--format", "json"))
        names = {c["name"] for c in out["data"]["components"]}
        self.assertIn("example.com/app", names)
        self.assertIn("github.com/foo/bar", names)
        self.assertTrue((Path(self.td) / ".rfg" / "sbom.json").is_file())

    def test_boundaries_cgo_is_trust_boundary(self):
        for p in CGO.iterdir():
            if p.is_file():
                shutil.copy(p, Path(self.td) / p.name)
        out = json.loads(self.rfg("boundaries", "--format", "json"))
        self.assertTrue(out["data"]["boundaries"])
        self.assertTrue(all(b.get("trust_boundary") for b in out["data"]["boundaries"]))
        types = {b["type"] for b in out["data"]["boundaries"]}
        self.assertIn("cgo", types)

    def test_no_exploit_helpers_in_source(self):
        import ast

        text = (ROOT / "rfg" / "security.py").read_text()
        self.assertIn("Does not generate exploits", text)
        names = [
            n.name.lower()
            for n in ast.walk(ast.parse(text))
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))
        ]
        for n in names:
            self.assertNotIn("exploit", n)
            self.assertNotIn("poc", n)
            self.assertNotIn("payload", n)


if __name__ == "__main__":
    unittest.main()
