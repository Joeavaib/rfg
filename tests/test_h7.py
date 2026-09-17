import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RFG = [sys.executable, str(ROOT / "rfg.py")]


class H7Test(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-h7-")
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(ROOT)

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

    def test_recipe_list_and_apply_cxx_ffi(self):
        Path(self.td, "go.mod").write_text("module m\n")
        listed = json.loads(self.rfg("recipe", "list", "--format", "json"))
        ids = {r["id"] for r in listed["data"]["recipes"]}
        self.assertTrue(
            {"rename", "perf-budget", "debug-repro", "security-campaign", "cxx-ffi-manual", "feature-module"}
            <= ids
        )
        self.rfg("init")
        out = json.loads(self.rfg("recipe", "apply", "cxx-ffi-manual", "--format", "json"))
        self.assertIn("ffi-edge", out["data"]["steps"])
        nxt = json.loads(self.rfg("next", "--format", "json"))
        self.assertEqual(nxt["data"]["engine"], "manual")
        self.assertEqual(nxt["data"]["edge"], "cxx-ffi")
        st = json.loads(self.rfg("status", "--format", "json"))
        step = next(s for s in st["data"]["steps"] if s["id"] == "ffi-edge")
        self.assertEqual(step["engine"], "manual")
        self.assertEqual(step["edge"], "cxx-ffi")

    def test_export_dashboard_html(self):
        Path(self.td, "go.mod").write_text("module m\n")
        self.rfg("init")
        out = json.loads(self.rfg("export", "dashboard", "--format", "json"))
        p = Path(out["data"]["path"])
        self.assertTrue(p.is_file())
        html = p.read_text()
        self.assertIn("<table", html)
        self.assertIn("exceptions", html)

    def test_schema_v3_migrate(self):
        rfgdir = Path(self.td) / ".rfg"
        rfgdir.mkdir()
        (rfgdir / "roadmap.yaml").write_text(
            "version: 2\nid: old\nhypothesis:\n  id: h1\n  statement: s\nsteps:\n"
        )
        (rfgdir / "state.json").write_text('{"applied":[],"verified":[],"failed":[]}\n')
        out = json.loads(self.rfg("migrate", "--format", "json"))
        self.assertEqual(out["data"]["to"], 3)


if __name__ == "__main__":
    unittest.main()
