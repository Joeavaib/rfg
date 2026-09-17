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


class FrictionTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-fr-")
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
        subprocess.check_call(["git", "init"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)

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

    def test_path_json_array(self):
        from rfg.types import coerce_path_list

        self.assertEqual(coerce_path_list('["a.py","b.py"]'), ["a.py", "b.py"])
        self.assertEqual(coerce_path_list(["a.py", "b.py"]), ["a.py", "b.py"])
        self.rfg("init")
        self.rfg("plan", "--step", "S", "--path", '["backend/app.py","frontend/app.ts"]')
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertEqual(nxt["path"], ["backend/app.py", "frontend/app.ts"])
        self.assertNotIn("[", nxt["path"][0])

    def test_engine_default(self):
        self.rfg("init")
        self.rfg("plan", "--profile", "feature", "--step", "S", "--path", "app.py", "--want", "ship")
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertEqual(nxt["engine"], "implement")
        tick = json.loads(self.rfg("tick", "--format", "json"))
        self.assertEqual(tick["data"]["action"], "stop")
        self.assertNotEqual(tick.get("code"), 4)

    def test_implement_dirty(self):
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        Path(self.td, "app.py").write_text("ok\n")
        Path(self.td, "tests").mkdir()
        Path(self.td, "tests", "t.py").write_text("ok\n")
        self.rfg(
            "plan",
            "--step",
            "S",
            "--engine",
            "implement",
            "--path",
            "app.py",
            "--want",
            "x",
            "--verify",
            "python3 -c \"assert True\"",
        )
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)

    def test_verify_guess(self):
        from rfg.detect import default_verify

        nested = Path(self.td) / "backend" / "open_webui"
        nested.mkdir(parents=True)
        (nested / "pyproject.toml").write_text("[project]\nname='x'\n")
        self.assertEqual(default_verify(self.td), "")
        (nested / "tests").mkdir()
        cmd = default_verify(self.td)
        self.assertIn("backend/open_webui", cmd)
        self.assertTrue("pytest" in cmd or "unittest" in cmd)

    def test_survey(self):
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "map",
            "--engine",
            "notes",
            "--want",
            "map dataflow",
            "--verify",
            "echo mapped",
        )
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertEqual(nxt["engine"], "survey")
        tick = json.loads(self.rfg("tick", "--format", "json"))
        self.assertEqual(tick["data"]["action"], "stop")
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)
        ver = json.loads(self.rfg("verify", "--format", "json"))
        self.assertTrue(ver["ok"], ver)

    def test_context_slim(self):
        self.rfg("init")
        Path(self.td, "app.py").write_text("class A:\n    pass\n")
        Path(self.td, "noise.py").write_text("x = 1\n")
        self.rfg(
            "plan",
            "--step",
            "S",
            "--engine",
            "implement",
            "--path",
            "app.py",
            "--want",
            "ship",
        )
        ctx = json.loads(self.rfg("context", "--format", "json"))["data"]
        self.assertEqual(ctx["exists"], ["app.py"])
        self.assertEqual(ctx.get("neighbors") or [], [])
        self.assertEqual(ctx.get("snippets") or [], [])
        self.assertEqual(ctx.get("signatures") or [], [])
        sourced = json.loads(self.rfg("context", "--sources", "--format", "json"))["data"]
        self.assertTrue(sourced.get("neighbors") or sourced.get("signatures") is not None)

    def test_plan_slim(self):
        self.rfg("init")
        out = json.loads(
            self.rfg("plan", "--step", "S", "--path", "a.py", "--want", "x", "--format", "json")
        )["data"]
        self.assertIn("next", out)
        self.assertEqual(out["next"], "S")
        self.assertNotIn("hypothesis", out)
        self.assertNotIn("worktree", out)
        for s in out["steps"]:
            self.assertIn("id", s)
            self.assertIn("status", s)
            self.assertNotIn("title", s)
            self.assertNotIn("goal", s)

    def test_impact_counts(self):
        Path(self.td, "app.py").write_text("UserID = 1\n")
        Path(self.td, "pyproject.toml").write_text("[project]\nname='t'\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        slim = json.loads(self.rfg("impact", "--symbol", "UserID", "--format", "json"))["data"]
        self.assertGreater(slim["hits"], 0)
        self.assertEqual(slim.get("files") or [], [])
        self.assertGreater(slim.get("files_total") or 0, 0)
        fat = json.loads(self.rfg("impact", "--symbol", "UserID", "--files", "--format", "json"))["data"]
        self.assertTrue(fat.get("files"))

    def test_progress_no_logs(self):
        self.rfg("init")
        prog = json.loads(self.rfg("progress", "--format", "json"))["data"]
        self.assertNotIn("verify_logs", prog)

    def test_empty_engine_is_implement(self):
        from rfg.types import coerce_path_list, default_engine

        self.assertEqual(coerce_path_list("['a.py', 'b.py']"), ["a.py", "b.py"])
        self.assertEqual(default_engine(""), "implement")
        self.assertEqual(default_engine("", from_pat="Foo"), "replace")
        self.rfg("init")
        self.rfg("plan", "--step", "S", "--path", "app.py", "--want", "x")
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertEqual(nxt["engine"], "implement")
        ctx = json.loads(self.rfg("context", "--format", "json"))["data"]
        self.assertEqual(ctx["engine"], "implement")
        self.assertEqual(ctx.get("snippets") or [], [])
        tick = json.loads(self.rfg("tick", "--format", "json"))
        self.assertEqual(tick["data"]["action"], "stop")
        self.assertNotEqual(tick.get("code"), 4)

    def test_apply_lists_step_only(self):
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        Path(self.td, "keep.py").write_text("k\n")
        Path(self.td, "noise.py").write_text("n\n")
        self.rfg(
            "plan",
            "--step",
            "S",
            "--engine",
            "manual",
            "--path",
            "keep.py",
            "--want",
            "x",
            "--verify",
            "python3 -c \"assert True\"",
        )
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)
        staged = applied["data"].get("staged") or []
        extra = applied["data"].get("extra") or []
        self.assertIn("keep.py", staged)
        self.assertIn("noise.py", staged)
        self.assertIn("noise.py", extra)
        self.assertIn("warning", applied["data"])

    def test_tick_progress_next_slim(self):
        self.rfg("init")
        for i in range(3):
            self.rfg("plan", "--step", f"S{i}", "--path", f"f{i}.py", "--engine", "manual", "--want", "x")
        tick = json.loads(self.rfg("tick", "--format", "json"))["data"]
        ctx = tick.get("context") or {}
        self.assertNotIn("neighbors", ctx)
        self.assertNotIn("snippets", ctx)
        self.assertNotIn("signatures", ctx)
        self.assertNotIn("goal", ctx)
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertLessEqual(len(nxt.get("ready") or []), 8)
        prog = json.loads(self.rfg("progress", "--format", "json"))["data"]
        self.assertLessEqual(len(prog.get("ready") or []), 8)
        self.assertNotIn("verify_logs", prog)
        self.assertGreaterEqual(len(prog.get("ready") or []), 1)
