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


class H2Test(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-h2-")
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

    def rfg(self, *args, code=0, env=None):
        e = env or self.env
        r = subprocess.run(
            RFG + ["--root", self.td, *args],
            cwd=self.td,
            env=e,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def test_claim_blocks_other_agent(self):
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        a = self.env.copy()
        a["RFG_AGENT"] = "alice"
        self.rfg("claim", "--agent", "alice", env=a)
        b = self.env.copy()
        b["RFG_AGENT"] = "bob"
        r = subprocess.run(
            RFG + ["--root", self.td, "apply", "--format", "json"],
            cwd=self.td,
            env=b,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.rfg("apply", "--format", "json", env=a)
        self.assertIn("UID", (Path(self.td) / ".rfg" / "worktree" / "user.go").read_text())

    def test_apply_budget_exhausted(self):
        self.rfg("init")
        self.rfg("plan", "--budget", "1")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        self.rfg("plan", "--step", "s2", "--from", "Lookup", "--to", "Lookup", "--path", "user.go", "--depends", "s1")
        self.rfg("apply", "--format", "json")
        r = subprocess.run(
            RFG + ["--root", self.td, "apply", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)

    def test_audit_records_claim_and_apply(self):
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        env = self.env.copy()
        env["RFG_AGENT"] = "grok"
        self.rfg("claim", "--agent", "grok", env=env)
        self.rfg("apply", "--format", "json", env=env)
        out = json.loads(self.rfg("audit", "--format", "json"))
        events = [e["event"] for e in out["data"]["events"]]
        self.assertIn("claim", events)
        self.assertIn("apply", events)

    def test_mcp_lists_claim(self):
        from rfg.mcp import handle

        listed = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, self.td)
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertTrue({"claim", "next", "apply", "verify"} <= names)

    def test_status_includes_claim_and_budget(self):
        self.rfg("init")
        self.rfg("plan", "--budget", "8")
        st = json.loads(self.rfg("status", "--format", "json"))
        self.assertEqual(st["data"]["budget"]["max_applies"], 8)
        self.assertEqual(st["data"]["claim_step"], "")


if __name__ == "__main__":
    unittest.main()
