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


class SweTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-swe-")
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

    def git_go(self):
        for p in GO.iterdir():
            if p.is_file():
                shutil.copy(p, Path(self.td) / p.name)
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

    def test_scaffold(self):
        self.git_go()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "sc",
            "--engine",
            "scaffold",
            "--path",
            "pkg/mod.py",
            "--verify",
            "test -f pkg/mod.py",
        )
        out = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(out["ok"], out)
        wt = Path(self.td) / ".rfg" / "worktree" / "pkg" / "mod.py"
        self.assertTrue(wt.is_file())
        self.assertIn("scaffold", wt.read_text())
        self.rfg("verify")

    def test_run_timeout(self):
        self.git_go()
        self.env["RFG_VERIFY_TIMEOUT"] = "0.2"
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "r1",
            "--engine",
            "run",
            "--verify",
            "python3 -c \"import time; time.sleep(2)\"",
        )
        self.rfg("apply")
        r = subprocess.run(
            RFG + ["--root", self.td, "verify", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("timeout", r.stdout + r.stderr)

    def test_acceptance_land(self):
        self.git_go()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "s1",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--verify",
            "python3 -c \"assert 'UID' in open('user.go').read()\"",
        )
        self.rfg("plan", "--acceptance", "test -n ok")
        self.rfg("apply")
        self.rfg("verify")
        land = json.loads(self.rfg("land", "--format", "json"))
        self.assertTrue(land["ok"], land)
        self.assertTrue(land["data"].get("acceptance"))

    def test_feature_module_recipe(self):
        self.git_go()
        self.rfg("init")
        listed = json.loads(self.rfg("recipe", "list", "--format", "json"))
        ids = {r["id"] for r in listed["data"]["recipes"]}
        self.assertIn("feature-module", ids)
        self.rfg(
            "recipe",
            "apply",
            "feature-module",
            "--path",
            "src/mod.py",
            "--verify",
            "python3 src/mod.py",
        )
        nxt = json.loads(self.rfg("next", "--format", "json"))
        self.assertEqual(nxt["data"]["id"], "scaffold")
        self.assertEqual(nxt["data"]["engine"], "scaffold")
        self.assertIn("src/mod.py", nxt["data"]["path"])

    def test_followup_step(self):
        Path(self.td, "mod.py").write_text('NAME = "Foo"\nFoo = 1\n')
        Path(self.td, "go.mod").write_text("module m\n")
        subprocess.check_call(["git", "init"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "s1",
            "--from",
            "Foo",
            "--to",
            "Bar",
            "--path",
            "mod.py",
            "--verify",
            "test -n ok",
        )
        self.rfg("apply")
        nxt = json.loads(self.rfg("next", "--format", "json"))
        self.assertEqual(nxt["data"]["id"], "s1-followup")
        self.assertEqual(nxt["data"]["engine"], "manual")


if __name__ == "__main__":
    unittest.main()
