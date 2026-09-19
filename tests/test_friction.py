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

    def test_path_traversal_exit_4(self):
        # QD-12: DotDot and absolute paths are unsupported (exit 4).
        # FAIL: a traversal path is accepted.
        from rfg.types import coerce_path_list

        for bad in ("../x", "/abs", "foo/../bar"):
            with self.assertRaises(ValueError) as cm:
                coerce_path_list(bad)
            msg = str(cm.exception).lower()
            self.assertIn("unsupported", msg, bad)
            self.assertIn("traversal", msg, bad)
        self.assertEqual(coerce_path_list("a.py"), ["a.py"])
        self.assertEqual(coerce_path_list("src/a.py"), ["src/a.py"])
        self.rfg("init")
        for bad in ("../x", "/abs"):
            out = self.rfg(
                "plan", "--step", "S", "--path", bad, "--want", "x",
                "--format", "json", code=4,
            )
            self.assertIn("unsupported", out.lower(), out)
            self.assertIn("traversal", out.lower(), out)

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

    def test_implement_tracked_dirty_needs_force(self):
        # QW-05: run executes blindly at root -> tracked-dirty needs
        # --force (names files); untracked dirt stays free (G03).
        # FAIL: dirty root silently run.
        Path(self.td, "app.py").write_text("v1\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env,
                              stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env,
                              stdout=subprocess.DEVNULL)
        self.rfg("init")
        self.rfg(
            "plan", "--step", "S", "--engine", "run", "--path", "app.py",
            "--want", "x", "--verify", "test -n ok",
        )
        Path(self.td, "app.py").write_text("v2-dirty\n")
        out = self.rfg("apply", "--format", "json", code=3)
        self.assertIn("app.py", out, "dirty error must name the file")
        self.assertIn("--force", out)
        forced = json.loads(self.rfg("apply", "--force", "--format", "json"))
        self.assertTrue(forced["ok"], forced)
        self.assertIn("app.py", (forced["data"] or {}).get("forced_dirty") or [], forced)

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

    def test_apply_verify_test_extra_named(self):
        # CF-02: undeclared verify test file is named on tick/apply (exit 0).
        # FAIL: no warning mentioning test_x.py; plan --check becomes a gate;
        # extras allowlist still warns; survey warns.
        subprocess.check_call(
            ["git", "commit", "-m", "i", "--allow-empty"],
            cwd=self.td,
            env=self.env,
            stdout=subprocess.DEVNULL,
        )
        self.rfg("init")
        Path(self.td, "app.py").write_text("x = 1\n")
        Path(self.td, "tests").mkdir()
        Path(self.td, "tests", "test_x.py").write_text("def test_ok():\n    assert True\n")
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
            "python3 -m pytest tests/test_x.py -q",
        )
        chk = json.loads(self.rfg("plan", "--check", "--format", "json"))
        self.assertTrue(chk["data"].get("ok"), chk)
        tick = json.loads(self.rfg("tick", "--format", "json"))
        self.assertTrue(tick["ok"], tick)
        tblob = (tick["data"].get("contract_warning") or "") + " " + (tick["data"].get("warning") or "")
        self.assertIn("test_x.py", tblob)
        self.assertIn("plan --path", tblob)
        self.assertIn("plan --extras", tblob)
        dry = json.loads(self.rfg("apply", "--dry-run", "--format", "json"))
        self.assertTrue(dry["ok"], dry)
        dblob = (dry["data"].get("contract_warning") or "") + " " + (dry["data"].get("warning") or "")
        self.assertIn("test_x.py", dblob)
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)
        ablob = (applied["data"].get("contract_warning") or "") + " " + (applied["data"].get("warning") or "")
        self.assertIn("test_x.py", ablob)
        self.assertTrue(applied["data"].get("contract_warning"))

        self.rfg("verify")
        self.rfg(
            "plan",
            "--step",
            "E",
            "--engine",
            "implement",
            "--path",
            "app.py",
            "--extras",
            "tests/test_x.py",
            "--want",
            "x",
            "--verify",
            "python3 -m pytest tests/test_x.py -q",
        )
        tick_e = json.loads(self.rfg("tick", "--format", "json"))
        self.assertTrue(tick_e["ok"], tick_e)
        self.assertFalse(tick_e["data"].get("contract_warning"))
        eblob = (tick_e["data"].get("contract_warning") or "") + (tick_e["data"].get("warning") or "")
        self.assertNotIn("test_x.py", eblob)

        self.rfg("release")
        self.rfg(
            "plan",
            "--step",
            "map",
            "--engine",
            "survey",
            "--want",
            "map",
            "--verify",
            "python3 -m pytest tests/test_x.py -q",
        )
        tick_s = json.loads(self.rfg("tick", "--format", "json"))
        self.assertTrue(tick_s["ok"], tick_s)
        self.assertFalse(tick_s["data"].get("contract_warning"))
        sblob = (tick_s["data"].get("contract_warning") or "") + (tick_s["data"].get("warning") or "")
        self.assertNotIn("test_x.py", sblob)

    def test_snapshot_identity_fallback(self):
        from rfg import gitops

        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "--unset", "user.email"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "--unset", "user.name"], cwd=self.td, env=self.env)
        (Path(self.td) / "x.txt").write_text("x\n")
        cleared = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        with unittest.mock.patch.dict(os.environ, cleared, clear=True):
            sha = gitops.snapshot(self.td, "rfg checkpoint before x")
        self.assertTrue(sha)
        self.assertTrue(gitops.snapshot_fallback)
