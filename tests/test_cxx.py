import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CXX = ROOT / "cxx" / "rfg"
GO = ROOT / "testdata" / "fixture"


class CxxDriverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["make", "-C", str(ROOT / "cxx")], capture_output=True, text=True)
        if r.returncode != 0:
            raise unittest.SkipTest("cxx build failed: " + r.stderr + r.stdout)
        if not CXX.is_file():
            raise unittest.SkipTest("cxx/rfg missing")

    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-cxx-")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.env = os.environ.copy()
        self.env.update(
            {
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t.test",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t.test",
            }
        )

    def cxx(self, *args, code=0):
        r = subprocess.run(
            [str(CXX), "--root", self.td, "--format", "json", *args],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stdout

    def git(self):
        subprocess.check_call(["git", "init"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)

    def test_init_plan_next_tick_manual(self):
        Path(self.td, "user.go").write_text("package users\ntype UserID string\n")
        Path(self.td, "go.mod").write_text("module m\n")
        self.git()
        self.cxx("init")
        self.cxx("plan", "--step", "m1", "--engine", "manual", "--path", "user.go", "--from", "UserID", "--to", "UID")
        nxt = self.cxx("next")
        self.assertEqual(nxt["data"]["id"], "m1")
        self.assertEqual(nxt["data"]["engine"], "manual")
        tick = self.cxx("tick")
        self.assertEqual(tick["data"]["action"], "stop")
        ctx = self.cxx("context")
        self.assertEqual(ctx["data"]["id"], "m1")
        self.assertTrue(ctx["data"]["snippets"])

    def test_replace_skips_comment_and_string(self):
        Path(self.td, "user.go").write_text(
            'package users\ntype UserID string\n// UserID leftover\nvar wire = "UserID"\n'
        )
        Path(self.td, "go.mod").write_text("module m\n")
        self.git()
        self.cxx("init")
        self.cxx(
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
            "test -n ok",
        )
        dry = self.cxx("apply", "--dry-run")
        self.assertGreater(dry["data"]["hits"], 0)
        self.cxx("apply")
        text = (Path(self.td) / ".rfg" / "worktree" / "user.go").read_text()
        self.assertIn("type UID string", text)
        self.assertIn("// UserID leftover", text)
        self.assertIn('"UserID"', text)

    def test_land(self):
        Path(self.td, "user.go").write_text("package users\ntype UserID string\n")
        Path(self.td, "go.mod").write_text("module m\n")
        self.git()
        self.cxx("init")
        self.cxx(
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
        self.cxx("apply")
        self.cxx("verify")
        self.assertIn("UserID", Path(self.td, "user.go").read_text())
        out = self.cxx("land")
        self.assertTrue(out["ok"], out)
        self.assertIn("UID", Path(self.td, "user.go").read_text())
        self.assertIn("user.go", out["data"]["files"])

    def test_help(self):
        r = subprocess.run([str(CXX), "help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("next", r.stdout)

    def test_claim_then_apply_without_agent_is_same_client(self):
        # empty agent is this client (Python same_claim_client), not a second
        # identity: claim stores "agent" by default, a later apply without
        # RFG_AGENT/--agent must not self-conflict (exit 5).
        Path(self.td, "user.go").write_text("package users\ntype UserID string\n")
        Path(self.td, "go.mod").write_text("module m\n")
        self.git()
        self.cxx("init")
        self.cxx(
            "plan", "--step", "s1", "--from", "UserID", "--to", "UID",
            "--path", "user.go", "--verify", "test -n ok",
        )
        self.cxx("claim", "s1")
        # a genuinely different agent must still conflict while free.
        env2 = dict(self.env, RFG_AGENT="other")
        r = subprocess.run(
            [str(CXX), "--root", self.td, "--format", "json", "apply"],
            cwd=self.td, env=env2, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.cxx("apply")


if __name__ == "__main__":
    unittest.main()
