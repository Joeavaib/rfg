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
POLY = ROOT / "testdata" / "polyglot"
RUST = ROOT / "testdata" / "rustmac"
CGO = ROOT / "testdata" / "cgoedge"


class Phase3Test(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg3-")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.env = os.environ.copy()
        self.env.update(
            {
                "PYTHONPATH": str(ROOT),
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t.test",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t.test",
            }
        )

    def copy(self, src: Path):
        for p in src.iterdir():
            dest = Path(self.td) / p.name
            if p.is_file():
                shutil.copy(p, dest)

    def git(self):
        subprocess.check_call(["git", "init"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)

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

    def test_polyglot_roadmap_manual_cpp_ffi(self):
        self.copy(POLY)
        self.git()
        self.rfg("init", "--format", "json")
        self.rfg("plan", "--hypothesis", "Go+TS+C++ FFI UserID", "--symbol", "UserID")
        self.rfg(
            "plan",
            "--step",
            "go-core",
            "--title",
            "Go core",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "core.go",
            "--verify",
            "true",
        )
        self.rfg(
            "plan",
            "--step",
            "ts-front",
            "--title",
            "TS frontend",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "app.ts",
            "--depends",
            "go-core",
            "--verify",
            "true",
        )
        self.rfg(
            "plan",
            "--step",
            "cxx-ffi",
            "--title",
            "C++ FFI (manual)",
            "--engine",
            "manual",
            "--edge",
            "cxx-ffi",
            "--depends",
            "ts-front",
            "--verify",
            "true",
        )
        st = json.loads(self.rfg("status", "--format", "json"))
        ids = [s["id"] for s in st["data"]["steps"]]
        self.assertEqual(ids, ["go-core", "ts-front", "cxx-ffi"])
        self.assertEqual(st["data"]["steps"][2]["engine"], "manual")
        self.assertEqual(st["data"]["steps"][2]["edge"], "cxx-ffi")

        dry = json.loads(self.rfg("apply", "--dry-run", "--format", "json"))
        self.assertIn("risk", dry["data"])
        self.assertIn("score", dry["data"]["risk"])
        self.rfg("apply", "--format", "json")
        self.rfg("verify", "--format", "json")
        self.rfg("apply", "--format", "json")
        self.rfg("verify", "--format", "json")
        man = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(man["data"]["manual"])
        self.assertEqual(man["data"]["edge"], "cxx-ffi")
        # C++ sources unchanged
        self.assertIn("UserID", (Path(self.td) / "bridge.cc").read_text())

        ed = json.loads(self.rfg("edges", "--format", "json"))
        types = {e["type"] for e in ed["data"]["edges"]}
        self.assertIn("cxx-ffi", types)
        self.assertFalse(ed["data"]["complete"])

        langs = json.loads(self.rfg("impact", "--symbol", "UserID", "--format", "json"))
        self.assertTrue(set(langs["data"]["languages"]) >= {"go", "typescript", "cpp"})

    def test_cpp_replace_without_compile_db_is_unsupported(self):
        self.copy(POLY)
        self.git()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "cxx",
            "--from",
            "user_id",
            "--to",
            "uid",
            "--path",
            "bridge.cc",
            "--engine",
            "replace",
        )
        r = subprocess.run(
            RFG + ["--root", self.td, "apply", "--dry-run", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)

    def test_rust_macros_unsupported(self):
        self.copy(RUST)
        # rustmac has lib.rs at top; move to src? discover uses Cargo.toml
        shutil.copy(RUST / "lib.rs", Path(self.td) / "lib.rs")
        self.git()
        self.rfg("init")
        self.rfg("plan", "--step", "rs", "--from", "UserID", "--to", "UID", "--path", "lib.rs")
        r = subprocess.run(
            RFG + ["--root", self.td, "apply", "--dry-run", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)

    def test_cgo_edge_detected(self):
        self.copy(CGO)
        out = json.loads(self.rfg("edges", "--format", "json"))
        types = {e["type"] for e in out["data"]["edges"]}
        self.assertIn("cgo", types)

    def test_pyo3_and_napi_scan(self):
        from rfg.edges import scan

        Path(self.td, "lib.rs").write_text("use pyo3::prelude::*;\n#[pyfunction]\nfn x() {}\n")
        Path(self.td, "napi.rs").write_text("#[napi]\nfn y() {}\n")
        types = {e["type"] for e in scan(self.td)}
        self.assertIn("pyo3", types)
        self.assertIn("napi", types)

    def test_diff_budget_conflict(self):
        self.copy(POLY)
        self.git()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "go-core",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "core.go",
            "--diff-budget",
            "1",
        )
        r = subprocess.run(
            RFG + ["--root", self.td, "apply", "--dry-run", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
