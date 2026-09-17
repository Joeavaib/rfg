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
HANDOFF = ROOT / "testdata" / "h1-handoff"


class H3Test(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-h3-")
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

    def test_progress_goal_and_no_exceptions_when_clean(self):
        self.rfg("init")
        self.rfg("plan", "--goal", "Ship typed IDs", "--acceptance", "CI green")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        out = json.loads(self.rfg("progress", "--format", "json"))
        d = out["data"]
        self.assertEqual(d["goal"]["statement"], "Ship typed IDs")
        self.assertIn("CI green", d["goal"]["acceptance"])
        self.assertEqual(d["counts"]["total"], 1)
        self.assertEqual(d["counts"]["ready"], 1)
        self.assertEqual(d["next"], "s1")
        self.assertTrue(d["ok"])
        self.assertEqual(d["exceptions"], [])

    def test_progress_exceptions_on_verify_fail(self):
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
            "false",
        )
        self.rfg("apply", "--format", "json")
        subprocess.run(
            RFG + ["--root", self.td, "verify", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        r = subprocess.run(
            RFG + ["--root", self.td, "progress", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        env = json.loads(r.stdout)
        self.assertFalse(env["ok"])
        d = env["data"]
        kinds = {e["kind"] for e in d["exceptions"]}
        self.assertIn("failed", kinds)

    def test_digest_writes_file(self):
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        out = json.loads(self.rfg("digest", "--format", "json"))
        path = Path(out["data"]["path"])
        self.assertTrue(path.is_file())
        body = json.loads(path.read_text())
        self.assertIn("exceptions", body)
        self.assertIn("goal", body)
        self.assertEqual(body["next"], "s1")

    def test_handoff_progress_from_fixture(self):
        r = subprocess.run(
            RFG + ["--root", str(HANDOFF), "progress", "--format", "json"],
            cwd=str(HANDOFF),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = json.loads(r.stdout)["data"]
        self.assertEqual(d["next"], "rename-type")
        self.assertTrue(d["goal"]["statement"])


if __name__ == "__main__":
    unittest.main()
