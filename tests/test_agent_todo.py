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
FIXTURE = ROOT / "testdata" / "fixture"
POLY = ROOT / "testdata" / "polyglot"

NEXT_FIELDS = (
    "id",
    "engine",
    "from",
    "to",
    "path",
    "depends",
    "verify",
    "blocked_reason",
)


class AgentTodoTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-todo-")
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

    def rfg_raw(self, *args):
        r = subprocess.run(
            RFG + ["--root", self.td, *args],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        return r.returncode, r.stdout, r.stderr

    def test_next_json_has_step_fields(self):
        for p in FIXTURE.iterdir():
            if p.is_file():
                shutil.copy(p, Path(self.td) / p.name)
        self.git()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "rename-type",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--verify",
            "test -n ok",
            "--engine",
            "replace",
        )
        nxt = json.loads(self.rfg("next", "--format", "json"))
        data = nxt["data"]
        for k in NEXT_FIELDS:
            self.assertIn(k, data, k)
        self.assertEqual(data["id"], "rename-type")
        self.assertEqual(data["from"], "UserID")
        self.assertEqual(data["to"], "UID")
        self.assertEqual(data["path"], ["user.go"])
        self.assertEqual(data["engine"], "replace")
        self.assertEqual(data["verify"], "test -n ok")
        self.assertEqual(data["blocked_reason"], "")
        self.assertNotIn("risk", data)
        nxt = json.loads(self.rfg("next", "--show-risk", "--format", "json"))
        self.assertIsInstance(nxt["data"]["risk"], dict)

    def test_dry_run_compact_and_diff_flag(self):
        for p in FIXTURE.iterdir():
            if p.is_file():
                shutil.copy(p, Path(self.td) / p.name)
        self.git()
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        compact = json.loads(self.rfg("apply", "--dry-run", "--format", "json"))
        self.assertNotIn("diff", compact)
        self.assertNotIn("diff", compact["data"])
        self.assertGreater(compact["data"]["hits"], 0)
        self.assertTrue(compact["data"]["files"])
        self.assertIn("hits", compact["data"]["files"][0])
        self.assertIn("examples", compact["data"]["files"][0])
        self.assertLessEqual(len(compact["data"]["files"][0]["examples"]), 3)
        self.assertIn("skipped", compact["data"])
        body = json.dumps(compact)
        self.assertNotIn("--- a/", body)

        full = json.loads(self.rfg("apply", "--dry-run", "--diff", "--format", "json"))
        diff = full.get("diff") or full["data"].get("diff") or ""
        self.assertIn("--- a/", diff)

    def test_literal_and_comment_not_replaced(self):
        Path(self.td, "go.mod").write_text("module m\n")
        Path(self.td, "user.go").write_text(
            'package users\n'
            'type UserID string\n'
            '// UserID leftover\n'
            'var wire = "UserID"\n'
        )
        self.git()
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        dry = json.loads(self.rfg("apply", "--dry-run", "--format", "json"))
        reasons = {s["reason"] for s in dry["data"]["skipped"]}
        self.assertTrue(reasons & {"string_literal", "comment"}, dry)
        self.rfg("apply")
        text = (Path(self.td) / ".rfg" / "worktree" / "user.go").read_text()
        self.assertIn("type UID string", text)
        self.assertIn("// UserID leftover", text)
        self.assertIn('"UserID"', text)
        self.assertNotIn("type UserID", text)

    def test_trivial_verify_exit_4(self):
        for p in FIXTURE.iterdir():
            if p.is_file():
                shutil.copy(p, Path(self.td) / p.name)
        self.git()
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go", "--verify", "true")
        self.rfg("apply")
        code, out, err = self.rfg_raw("verify", "--format", "json")
        self.assertEqual(code, 4, out + err)
        self.rfg("plan", "--step", "s2", "--from", "UID", "--to", "Uid", "--path", "user.go", "--verify", "")
        # empty on s1 still applied; verify s1 still trivial
        code, _, _ = self.rfg_raw("verify", "s1", "--format", "json")
        self.assertEqual(code, 4)

    def test_cpp_without_compile_db_still_4(self):
        for p in POLY.iterdir():
            if p.is_file():
                shutil.copy(p, Path(self.td) / p.name)
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
        code, out, err = self.rfg_raw("apply", "--dry-run", "--format", "json")
        self.assertEqual(code, 4, out + err)


if __name__ == "__main__":
    unittest.main()
