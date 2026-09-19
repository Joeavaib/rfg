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


class ImplementLoopTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-impl-")
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

    def rfg(self, *args, code=0, env=None):
        r = subprocess.run(
            RFG + ["--root", self.td, *args],
            cwd=self.td,
            env=env or self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def test_plan_step_goal_does_not_eat_product_goal(self):
        self.rfg("init")
        self.rfg("plan", "--goal", "Rechnung aus WhatsApp", "--profile", "feature")
        self.rfg(
            "plan",
            "--step",
            "M08",
            "--engine",
            "implement",
            "--want",
            "Beleg-Satz von M08",
            "--path",
            "app/invoice.py",
            "--verify",
            "test -n ok",
        )
        prog = json.loads(self.rfg("progress", "--format", "json"))["data"]
        self.assertEqual(prog["goal"]["statement"], "Rechnung aus WhatsApp")
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertEqual(nxt["want"], "Beleg-Satz von M08")
        self.assertEqual(nxt["engine"], "implement")
        self.assertEqual(nxt["missing"], ["app/invoice.py"])
        self.assertIn("M08", nxt["ready"])
        self.assertEqual(nxt["recommend"], "M08")
        yaml = (Path(self.td) / ".rfg" / "roadmap.yaml").read_text()
        self.assertNotIn("from:", yaml)

    def test_context_missing_is_contract_not_error(self):
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "M01",
            "--engine",
            "implement",
            "--want",
            "Berger extract",
            "--path",
            "extract.py",
            "--path",
            "ops.py",
            "--verify",
            "python3 -c \"assert False, 'orchestrator picks one observation'\"",
        )
        Path(self.td, "noise.py").write_text("x = 1\n")
        ctx = json.loads(self.rfg("context", "--format", "json"))["data"]
        self.assertEqual(ctx["want"], "Berger extract")
        self.assertEqual(ctx["missing"], ["extract.py", "ops.py"])
        self.assertEqual(ctx["exists"], [])
        self.assertEqual(ctx["tick"], "stop")
        self.assertEqual(ctx["snippets"], [])
        self.assertEqual(ctx.get("neighbors") or [], [])
        self.assertFalse(any(s.get("error") == "missing" for s in ctx["snippets"]))
        sourced = json.loads(self.rfg("context", "--sources", "--format", "json"))["data"]
        self.assertIn("noise.py", sourced.get("neighbors") or [])

    def test_greenfield_untracked_is_not_progress_dirty(self):
        self.rfg("init")
        self.rfg(
            "plan",
            "--want",
            "Rechnung aus WhatsApp",
            "--step",
            "M01",
            "--engine",
            "implement",
            "--path",
            "app.py",
            "--verify",
            "test -f app.py",
        )
        Path(self.td, "app.py").write_text("print('ok')\n")
        Path(self.td, "extra.txt").write_text("x\n")
        prog = json.loads(self.rfg("progress", "--format", "json"))
        self.assertTrue(prog["ok"], prog)
        kinds = {e["kind"] for e in prog["data"]["exceptions"]}
        self.assertNotIn("dirty", kinds)

    def test_claim_in_progress_then_verify_without_apply(self):
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "M02",
            "--engine",
            "implement",
            "--want",
            "Berger-Extrakt",
            "--path",
            "extract.py",
            "--verify",
            "python3 -c \"assert open('extract.py').read().strip() == 'ok'\"",
        )
        self.env["RFG_AGENT"] = "grok"
        claim = json.loads(self.rfg("claim", "--format", "json"))["data"]
        self.assertEqual(claim["step"], "M02")
        st = json.loads(self.rfg("status", "--format", "json"))["data"]
        step = next(s for s in st["steps"] if s["id"] == "M02")
        self.assertEqual(step["status"], "claimed")
        tick = json.loads(self.rfg("tick", "--format", "json"))["data"]
        self.assertEqual(tick["action"], "stop")
        self.assertEqual(tick["reason"], "implement")
        self.assertTrue(tick.get("claimed"))
        self.assertEqual(tick.get("after_edit"), "apply")
        self.assertEqual(tick.get("status"), "in_progress")
        Path(self.td, "extract.py").write_text("ok\n")
        r = subprocess.run(
            RFG + ["--root", self.td, "verify", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.rfg("apply")
        ver = json.loads(self.rfg("verify", "--format", "json"))
        self.assertTrue(ver["ok"], ver)
        self.assertTrue(ver["data"].get("log"))
        st = json.loads(self.rfg("status", "--format", "json"))["data"]
        step = next(s for s in st["steps"] if s["id"] == "M02")
        self.assertEqual(step["status"], "verified")
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertIsNone(nxt["id"])

    def test_implement_dep_waits_for_verify(self):
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "M04",
            "--engine",
            "implement",
            "--path",
            "a.py",
            "--verify",
            "test -f a.py",
        )
        self.rfg(
            "plan",
            "--step",
            "M05",
            "--engine",
            "implement",
            "--path",
            "b.py",
            "--depends",
            "M04",
            "--verify",
            "test -f b.py",
        )
        Path(self.td, "a.py").write_text("x\n")
        self.rfg("apply")
        st = json.loads(self.rfg("status", "--format", "json"))["data"]
        m04 = next(s for s in st["steps"] if s["id"] == "M04")
        m05 = next(s for s in st["steps"] if s["id"] == "M05")
        self.assertEqual(m04["status"], "implemented")
        self.assertEqual(m05["status"], "blocked")
        self.assertEqual(st["next"], None)
        self.rfg("verify")
        st = json.loads(self.rfg("status", "--format", "json"))["data"]
        self.assertEqual(st["next"], "M05")

    def test_claim_then_tick_states(self):
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "m1",
            "--engine",
            "implement",
            "--path",
            "a.py",
            "--verify",
            "test -f a.py",
        )
        self.env["RFG_AGENT"] = "grok"
        self.rfg("claim")
        st = json.loads(self.rfg("status", "--format", "json"))["data"]
        self.assertEqual(next(s for s in st["steps"] if s["id"] == "m1")["status"], "claimed")
        tick = json.loads(self.rfg("tick", "--format", "json"))["data"]
        self.assertEqual(tick["status"], "in_progress")
        st = json.loads(self.rfg("status", "--format", "json"))["data"]
        self.assertEqual(next(s for s in st["steps"] if s["id"] == "m1")["status"], "in_progress")

    def test_second_agent_claim_conflicts_with_claimed_by(self):
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "m1",
            "--engine",
            "implement",
            "--want",
            "held",
            "--path",
            "a.py",
            "--verify",
            "test -f a.py",
        )
        alice = self.env.copy()
        alice["RFG_AGENT"] = "alice"
        claimed = json.loads(self.rfg("claim", "--format", "json", env=alice))
        self.assertEqual(claimed["data"]["agent"], "alice")
        bob = self.env.copy()
        bob["RFG_AGENT"] = "bob"
        body = json.loads(self.rfg("claim", "--format", "json", env=bob, code=5))
        self.assertFalse(body["ok"])
        self.assertEqual(body.get("claimed_by"), "alice")
        self.assertEqual(body.get("claim_step"), "m1")
        self.assertIn("alice", body.get("error", ""))
        st = json.loads(self.rfg("status", "--format", "json", env=alice))["data"]
        self.assertEqual(st["claim_step"], "m1")
        self.assertEqual(st["claim_agent"], "alice")

    def test_contract_does_not_inherit_suite_verify(self):
        self.rfg("init")
        self.rfg("plan", "--verify", "pytest")
        self.rfg("plan", "--step", "m1", "--engine", "implement", "--path", "a.py")
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertEqual(nxt["verify"], "")
        Path(self.td, "a.py").write_text("x\n")
        self.rfg("apply")
        r = subprocess.run(
            RFG + ["--root", self.td, "verify", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)

    def test_feature_campaign_recipe(self):
        self.rfg("init")
        out = json.loads(
            self.rfg(
                "recipe",
                "apply",
                "feature-campaign",
                "--goal",
                "Rechnung aus WhatsApp",
                "--step",
                "M01:extract.py:python3 -c 'print(0)'",
                "--step",
                "M02:ops.py:python3 -c 'print(0)'",
                "--depends",
                "M02:M01",
                "--format",
                "json",
            )
        )
        self.assertEqual(out["data"]["goal"], "Rechnung aus WhatsApp")
        self.assertEqual(out["data"]["steps"][:2], ["M01", "M02"])
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertEqual(nxt["id"], "M01")
        self.assertEqual(nxt["engine"], "implement")
        self.assertEqual(nxt["path"], ["extract.py"])
        st = json.loads(self.rfg("status", "--format", "json"))["data"]
        self.assertEqual(st["goal"]["statement"], "Rechnung aus WhatsApp")
        self.assertEqual(st["profile"], "feature")
        m02 = next(s for s in st["steps"] if s["id"] == "M02")
        self.assertEqual(m02["status"], "blocked")

    def test_init_warns_without_git(self):
        td = tempfile.mkdtemp(prefix="rfg-nogit-")
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        r = subprocess.run(
            RFG + ["--root", td, "init", "--format", "json"],
            cwd=td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = json.loads(r.stdout)
        self.assertIn("git", (body["data"].get("warning") or "").lower())

    def test_plan_warns_bare_suite_verify(self):
        self.rfg("init")
        out = json.loads(
            self.rfg(
                "plan",
                "--step",
                "m1",
                "--engine",
                "implement",
                "--path",
                "a.py",
                "--verify",
                "pytest",
                "--format",
                "json",
            )
        )
        warns = out["data"].get("warnings") or []
        self.assertTrue(any("whole-suite" in w for w in warns), warns)

    def test_implement_apply_stages_into_worktree(self):
        Path(self.td, "keep.txt").write_text("k\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "m1",
            "--engine",
            "implement",
            "--path",
            "mod.py",
            "--verify",
            "test -f mod.py",
        )
        Path(self.td, "mod.py").write_text("ok\n")
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)
        wt = Path(self.td) / ".rfg" / "worktree" / "mod.py"
        self.assertTrue(wt.is_file(), applied)
        staged = applied["data"].get("staged") or []
        files = [f.get("path") for f in applied["data"].get("files") or [] if isinstance(f, dict)]
        self.assertTrue("mod.py" in staged or "mod.py" in files, applied)

    def test_apply_overwrites_and_stages_extras(self):
        Path(self.td, "db.py").write_text("old\n")
        Path(self.td, "tenant.py").write_text("old-tenant\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "W01",
            "--engine",
            "implement",
            "--path",
            "db.py",
            "--verify",
            "python3 -c \"assert 'new' in open('db.py').read()\"",
        )
        Path(self.td, "db.py").write_text("new\n")
        Path(self.td, "tenant.py").write_text("new-tenant\n")
        Path(self.td, "tests/test_db.py").parent.mkdir(parents=True, exist_ok=True)
        Path(self.td, "tests/test_db.py").write_text("ok\n")
        tick = json.loads(self.rfg("tick", "--format", "json"))
        self.assertEqual(tick["data"]["action"], "stop")
        self.assertNotEqual(tick.get("code"), 4)
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)
        wt = Path(self.td) / ".rfg" / "worktree"
        self.assertEqual((wt / "db.py").read_text(), "new\n")
        self.assertEqual((wt / "tenant.py").read_text(), "new-tenant\n")
        self.assertEqual((wt / "tests" / "test_db.py").read_text(), "ok\n")
        extra = applied["data"].get("extra") or []
        self.assertIn("tenant.py", extra)
        self.assertIn("tests/test_db.py", extra)
        self.assertGreaterEqual(applied["data"].get("extra_count") or 0, 1)
        ver = json.loads(self.rfg("verify", "--format", "json"))
        self.assertTrue(ver["ok"], ver)
        prog = json.loads(self.rfg("progress", "--format", "json"))["data"]
        self.assertEqual(prog["counts"]["implemented"], 0)
        self.assertEqual(prog["counts"]["verified"], 1)
        self.assertEqual(prog["counts"]["pending_verify"], 0)
        land = json.loads(self.rfg("land", "--format", "json"))
        self.assertTrue(land["ok"], land)
        self.assertEqual(Path(self.td, "db.py").read_text(), "new\n")
        self.assertEqual(Path(self.td, "tenant.py").read_text(), "new-tenant\n")

    def test_verify_output_is_clipped(self):
        from rfg.verify import clip_output

        huge = "x" * 8000
        clipped = clip_output(huge)
        self.assertLessEqual(len(clipped), 2100)
        self.assertIn("truncated", clipped)

    def test_tick_apply_without_rfg_agent_env(self):
        self.env.pop("RFG_AGENT", None)
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "m1",
            "--engine",
            "implement",
            "--path",
            "a.py",
            "--verify",
            "test -f a.py",
        )
        Path(self.td, "a.py").write_text("x\n")
        tick = json.loads(self.rfg("tick", "--format", "json"))
        self.assertEqual(tick["data"]["action"], "stop")
        self.assertTrue(tick["data"].get("claimed"))
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)

    def test_apply_without_env_after_claim(self):
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "m1",
            "--engine",
            "implement",
            "--path",
            "a.py",
            "--verify",
            "test -f a.py",
        )
        Path(self.td, "a.py").write_text("x\n")
        env_claim = self.env.copy()
        env_claim["RFG_AGENT"] = "agent"
        r = subprocess.run(
            RFG + ["--root", self.td, "claim", "--format", "json"],
            cwd=self.td,
            env=env_claim,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        env_apply = self.env.copy()
        env_apply.pop("RFG_AGENT", None)
        r = subprocess.run(
            RFG + ["--root", self.td, "apply", "--format", "json"],
            cwd=self.td,
            env=env_apply,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_tick_explicit_step(self):
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "G01",
            "--engine",
            "implement",
            "--path",
            "g.py",
            "--verify",
            "test -f g.py",
        )
        self.rfg(
            "plan",
            "--step",
            "D01",
            "--engine",
            "implement",
            "--path",
            "d.py",
            "--verify",
            "test -f d.py",
        )
        tick = json.loads(self.rfg("tick", "D01", "--format", "json"))
        self.assertEqual(tick["data"]["path"], ["d.py"])
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertEqual(nxt["recommend"], "D01")
        self.assertEqual(nxt["recommend_reason"], "claimed")

    def test_feature_campaign_keeps_all_paths(self):
        self.rfg("init")
        self.rfg(
            "recipe",
            "apply",
            "feature-campaign",
            "--goal",
            "MySQL RLS",
            "--step",
            "D01:db.py,tenant.py,tests/test_mysql_rls.py:pytest tests/test_mysql_rls.py",
            "--format",
            "json",
        )
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertEqual(nxt["id"], "D01")
        self.assertEqual(
            nxt["path"],
            ["db.py", "tenant.py", "tests/test_mysql_rls.py"],
        )

    def test_prose_acceptance_is_not_shell(self):
        from rfg.accept import is_command

        self.assertFalse(is_command("Register/Login"))
        self.assertFalse(is_command("CI green"))
        self.assertTrue(is_command("test -n ok"))
        self.assertTrue(is_command("python3 -c 'print(0)'"))
        self.rfg("init")
        self.rfg("plan", "--goal", "Auth", "--acceptance", "Register/Login")
        self.rfg(
            "plan",
            "--step",
            "m1",
            "--engine",
            "implement",
            "--path",
            "a.py",
            "--verify",
            "test -f a.py",
        )
        Path(self.td, "a.py").write_text("x\n")
        self.rfg("apply")
        self.rfg("verify")
        prog = json.loads(self.rfg("progress", "--format", "json"))
        self.assertTrue(prog["data"]["ok"], prog)
        kinds = {e["kind"] for e in prog["data"]["exceptions"]}
        self.assertNotIn("acceptance", kinds)

    def test_run_verify_runs_at_root_not_worktree(self):
        # run applies at root without isolation, so verify must run at root
        # too: a marker untracked at root is invisible in the worktree that
        # a prior stop-engine step left behind in state (Arm B: heal->smoke).
        self.rfg("init")
        Path(self.td, "app.py").write_text("x = 1\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env,
                              stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-qm", "i"], cwd=self.td, env=self.env)
        self.rfg(
            "plan", "--step", "M1", "--engine", "implement", "--want", "w",
            "--path", "app.py", "--verify", "test -f app.py",
        )
        self.rfg("tick", "M1")
        self.rfg("apply", "M1")
        self.rfg("verify", "M1")
        Path(self.td, "marker.txt").write_text("root-only\n")
        self.rfg(
            "plan", "--step", "R1", "--engine", "run", "--want", "w",
            "--path", "marker.txt", "--verify", "test -f marker.txt",
        )
        self.rfg("tick", "R1")
        self.rfg("verify", "R1")
        prog = json.loads(self.rfg("progress", "--format", "json"))
        self.assertTrue(prog["data"]["ok"], prog)


if __name__ == "__main__":
    unittest.main()
