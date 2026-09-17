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
HANDOFF = ROOT / "testdata" / "h1-handoff"


class H1Test(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-h1-")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(ROOT)

    def rfg(self, *args, root=None, code=0):
        r = subprocess.run(
            RFG + ["--root", str(root or self.td), *args],
            cwd=str(root or self.td),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def test_handoff_status_and_next_without_yaml_read(self):
        st = json.loads(self.rfg("status", "--format", "json", root=HANDOFF))
        d = st["data"]
        self.assertEqual(d["goal"]["profile"], "refactor")
        self.assertTrue(d["goal"]["acceptance"])
        self.assertEqual(d["next"], "rename-type")
        kinds = {o["kind"] for o in d["oracles"]}
        self.assertEqual(kinds, {"test", "perf", "debug", "security"})
        nxt = json.loads(self.rfg("next", "--format", "json", root=HANDOFF))
        n = nxt["data"]
        self.assertEqual(n["id"], "rename-type")
        self.assertEqual(n["from"], "UserID")
        self.assertEqual(n["to"], "UID")
        self.assertEqual(n["path"], ["user.go"])
        self.assertEqual(d["next_step"]["id"], n["id"])

    def test_migrate_v0_fills_goal_and_oracle_stubs(self):
        rfgdir = Path(self.td) / ".rfg"
        rfgdir.mkdir()
        (rfgdir / "roadmap.yaml").write_text(
            "version: 0\nid: old\nhypothesis:\n  id: h1\n  statement: s\nsteps:\n"
        )
        (rfgdir / "state.json").write_text('{"applied":[],"verified":[],"failed":[]}\n')
        out = json.loads(self.rfg("migrate", "--format", "json"))
        self.assertTrue(out["data"]["changed"])
        self.assertEqual(out["data"]["to"], 3)
        from rfg.yamlio import unmarshal_roadmap

        rm = unmarshal_roadmap((rfgdir / "roadmap.yaml").read_text())
        self.assertEqual(rm.goal.statement, "s")
        self.assertEqual({o.kind for o in rm.oracles}, {"test", "perf", "debug", "security"})

    def test_perf_oracle_stub_exit_4(self):
        Path(self.td, "go.mod").write_text("module m\n")
        Path(self.td, "a.go").write_text("package m\n")
        subprocess.check_call(["git", "init"], cwd=self.td, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td)
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, stdout=subprocess.DEVNULL)
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "p1",
            "--from",
            "package m",
            "--to",
            "package m",
            "--path",
            "a.go",
            "--oracle",
            "perf",
            "--verify",
            "",
        )
        self.rfg("apply")
        r = subprocess.run(
            RFG + ["--root", self.td, "verify", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)

    def test_plan_goal_and_profile(self):
        Path(self.td, "go.mod").write_text("module m\n")
        self.rfg("init")
        self.rfg("plan", "--goal", "Ship typed IDs", "--profile", "refactor", "--acceptance", "CI green")
        st = json.loads(self.rfg("status", "--format", "json"))
        self.assertEqual(st["data"]["goal"]["statement"], "Ship typed IDs")
        self.assertEqual(st["data"]["profile"], "refactor")
        self.assertIn("CI green", st["data"]["goal"]["acceptance"])

    def test_coverage_doc_exists(self):
        text = (ROOT / "docs" / "rfg-coverage-roadmap.md").read_text()
        self.assertIn("H0", text)
        self.assertIn("H1", text)
        self.assertIn("Goal", text)


if __name__ == "__main__":
    unittest.main()
