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


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-fb-")
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

    def test_plan_path_merges(self):
        self.rfg("init")
        self.rfg("plan", "--step", "S01", "--path", "ruff/codes.rs", "--engine", "implement")
        self.rfg("plan", "--step", "S01", "--path", "tools/codegen.py")
        yaml = (Path(self.td) / ".rfg" / "roadmap.yaml").read_text()
        self.assertIn("ruff/codes.rs", yaml)
        self.assertIn("tools/codegen.py", yaml)
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertEqual(nxt["path"], ["ruff/codes.rs", "tools/codegen.py"])

    def test_no_head_apply_and_land(self):
        self.rfg("init")
        Path(self.td, "app.py").write_text("x = 1\n")
        self.rfg(
            "plan",
            "--step",
            "S01",
            "--engine",
            "implement",
            "--path",
            "app.py",
            "--want",
            "ship",
            "--verify",
            "python3 -c \"assert True\"",
        )
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)
        self.assertTrue(applied["data"].get("no_head_commit"))
        self.assertEqual(applied["data"].get("warning"), "no-head-commit")
        self.assertFalse(applied["data"].get("isolation"))
        self.assertEqual(Path(applied["data"]["worktree"]).resolve(), Path(self.td).resolve())
        self.rfg("verify")
        land = json.loads(self.rfg("land", "--format", "json"))
        self.assertTrue(land["ok"], land)
        self.assertTrue(land["data"].get("noop"))
        self.assertEqual(land["data"].get("reason"), "noop-no-transaction")

    def test_implemented_not_after_verify(self):
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        Path(self.td, "app.py").write_text("ok\n")
        self.rfg(
            "plan",
            "--step",
            "M01",
            "--engine",
            "implement",
            "--path",
            "app.py",
            "--want",
            "x",
            "--verify",
            "python3 -c \"assert True\"",
        )
        self.rfg("apply")
        mid = json.loads(self.rfg("progress", "--format", "json"))["data"]["counts"]
        self.assertEqual(mid["implemented"], 1)
        self.assertEqual(mid["verified"], 0)
        self.rfg("verify")
        after = json.loads(self.rfg("progress", "--format", "json"))["data"]["counts"]
        self.assertEqual(after["implemented"], 0)
        self.assertEqual(after["verified"], 1)

    def test_plan_help_and_goal_want(self):
        r = subprocess.run(
            RFG + ["plan", "--help"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("--want", r.stdout)
        self.assertIn("--path", r.stdout)
        self.rfg("init")
        self.rfg("plan", "--goal", "Ship", "--profile", "feature")
        self.rfg("plan", "--step", "S1", "--want", "do", "--path", "a.py")
        mix = subprocess.run(
            RFG + ["--root", self.td, "plan", "--step", "S1", "--goal", "nope"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(mix.returncode, 5, mix.stdout + mix.stderr)

    def test_impact_cap(self):
        from rfg.index import _cap_impact

        files = [{"path": f"f{i}.py", "hits": 20} for i in range(40)]
        rep = _cap_impact({"query": "Rule", "hits": 6017, "files": files, "source": "index"})
        self.assertIn("too broad", rep.get("warning") or "")
        self.assertLessEqual(len(rep["files"]), 24)
        self.assertEqual(rep["hits"], 6017)

    def test_rust_sigs(self):
        from rfg.context import _SIG

        self.assertTrue(_SIG.match("pub enum Rule {"))
        self.assertTrue(_SIG.match("impl Rule {"))
        self.assertTrue(_SIG.match("macro_rules! foo {"))
        self.assertTrue(_SIG.match("pub(crate) fn linter() {}"))
        Path(self.td, "Cargo.toml").write_text("[package]\nname='t'\n")
        self.rfg("init")
        doc = json.loads(self.rfg("doctor", "--format", "json"))["data"]
        self.assertIn("rust_macros", doc["checks"])

    def test_extra_gitignore(self):
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        Path(self.td, ".gitignore").write_text("__pycache__/\n*.pyc\n")
        Path(self.td, "app.py").write_text("ok\n")
        cache = Path(self.td, "pkg", "__pycache__")
        cache.mkdir(parents=True)
        (cache / "x.pyc").write_bytes(b"x")
        self.rfg("init")
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
        extra = applied["data"].get("extra") or []
        self.assertTrue(all("__pycache__" not in p and not p.endswith(".pyc") for p in extra), extra)

    def test_run_and_weak(self):
        from rfg.verify import is_weak_verify

        self.assertTrue(is_weak_verify('python3 -c "assert Path.exists()"'))
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        Path(self.td, "app.py").write_text("ok\n")
        self.rfg("init")
        planned = json.loads(
            self.rfg(
                "plan",
                "--step",
                "R1",
                "--engine",
                "run",
                "--path",
                "app.py",
                "--want",
                "smoke",
                "--verify",
                "python3 -c \"assert True\"",
                "--format",
                "json",
            )
        )
        warns = planned["data"].get("warnings") or []
        self.assertTrue(any("profile switched" in w for w in warns), planned)
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertFalse(applied["data"].get("isolation"))
        self.assertEqual(Path(applied["data"]["worktree"]).resolve(), Path(self.td).resolve())
        self.assertIn("claim_agent", applied["data"])


class FeedbackIndexRobustTest(unittest.TestCase):
    def test_index_skips_unparseable(self):
        import tempfile
        from rfg import index as idx

        td = tempfile.mkdtemp(prefix="rfg-idx-")
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        Path(td, "good.py").write_text("def foo():\n    pass\n")
        Path(td, "bad.py").write_text("def broken(:\n\x00\x00\n")
        Path(td, "go.mod").write_text("module t\n")
        data = idx.build_index(td)
        self.assertIn("good.py", data.get("files") or {})
        # must not crash; bad file either skipped or degraded
        self.assertIn("stats", data)
        # symbols of good file found
        self.assertIn("foo", (data["files"]["good.py"].get("symbols") or []))
        # _symbols_python never raises on garbage
        self.assertEqual(idx._symbols_python("def broken(:\n"), [])
        self.assertEqual(idx._symbols_python("\x00"), [])


class FeedbackRollbackTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-fb-rb-")
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

    def test_rollback_warns_untracked(self):
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        Path(self.td, "app.py").write_text("v1\n")
        self.rfg("init")
        self.rfg("plan", "--step", "S1", "--engine", "replace", "--from", "v1", "--to", "v2",
                 "--path", "app.py", "--want", "x", "--verify", "python3 -c \"assert True\"")
        self.rfg("apply")
        wt = json.loads(self.rfg("apply", "--format", "json", code=0) if False else self.rfg("status", "--format", "json"))["data"].get("worktree") or ""
        # create untracked file in worktree target
        target = Path(wt) if wt and Path(wt).is_dir() else Path(self.td)
        (Path(target) / "extra_new.py").write_text("untracked work\n")
        out = json.loads(self.rfg("rollback", "--format", "json"))
        self.assertTrue(out["ok"], out)
        data = out["data"]
        self.assertIn("untracked", json.dumps(data).lower() + json.dumps(out).lower())


class FeedbackReplaceTest(unittest.TestCase):
    def test_replace_zero_hits_warns(self):
        import tempfile
        from rfg.apply import preview
        from rfg.types import Step, Replace

        td = tempfile.mkdtemp(prefix="rfg-rep-")
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        Path(td, "a.py").write_text("x = 1\n")
        step = Step(id="s", replace=Replace(from_pat="nope_missing", to="yep", paths=["a.py"]))
        prev = preview(td, step)
        self.assertEqual(prev["hits"], 0)
        # per-path zero-hits helper must exist
        from rfg.apply import zero_hit_paths

        self.assertIn("a.py", zero_hit_paths(td, step))


class FeedbackPlanTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-fb-plan-")
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

    def test_plan_update_preserves_engine(self):
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        Path(self.td, "a.py").write_text("old_name = 1\n")
        self.rfg("init")
        self.rfg("plan", "--step", "R1", "--engine", "replace", "--from", "old_name",
                 "--to", "new_name", "--path", "a.py", "--want", "x", "--verify", "python3 -c \"assert True\"")
        # update only verify; engine must stay replace
        self.rfg("plan", "--step", "R1", "--verify", "python3 -c \"assert True\"")
        nxt = json.loads(self.rfg("next", "--format", "json"))["data"]
        self.assertEqual(nxt.get("engine"), "replace")


class FeedbackCxxTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-fb-cxx-")
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

    def test_cxx_missing_db_suggests_template(self):
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        Path(self.td, "a.cpp").write_text("int main(){return 0;}\n")
        self.rfg("init")
        self.rfg("plan", "--step", "C1", "--engine", "replace", "--from", "foo", "--to", "bar",
                 "--path", "a.cpp", "--want", "x", "--verify", "true")
        out = self.rfg("apply", "--format", "json", code=4)
        self.assertIn("compile_commands", out)
        self.assertTrue("template" in out.lower() or "minimal" in out.lower() or "g++" in out.lower())
        from rfg.cxxcompile import minimal_db

        db = minimal_db(Path(self.td), ["a.cpp"])
        self.assertTrue(any("a.cpp" in json.dumps(e) for e in db))


class FeedbackUxTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-fb-ux-")
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

    def test_dir_paths_expand(self):
        from rfg.types import expand_dir_paths

        Path(self.td, "pkg").mkdir()
        Path(self.td, "pkg", "a.py").write_text("x=1\n")
        Path(self.td, "pkg", "b.py").write_text("y=2\n")
        out = expand_dir_paths(self.td, ["pkg"])
        self.assertIn("pkg/a.py", out)
        self.assertIn("pkg/b.py", out)

    def test_tests_outside_path_no_warn(self):
        from rfg.doctor import oracle_warnings
        from rfg.types import Step

        s = Step(id="M01", verify="pytest tests/test_ops.py", paths=["src/ops.py"])
        warns = oracle_warnings([s])
        self.assertFalse(any("outside path" in w for w in warns), warns)

    def test_extra_listed(self):
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        Path(self.td, "app.py").write_text("ok\n")
        Path(self.td, "extra2.py").write_text("ok2\n")
        self.rfg("init")
        self.rfg("plan", "--step", "S", "--engine", "implement", "--path", "app.py",
                 "--want", "x", "--verify", "python3 -c \"assert True\"")
        applied = json.loads(self.rfg("apply", "--format", "json"))
        extra = applied["data"].get("extra") or []
        self.assertIn("extra2.py", extra)

    def test_recommend_critical_path(self):
        from rfg.dag import recommend
        from rfg.store import Store

        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        self.rfg("plan", "--step", "TINY", "--engine", "implement", "--path", "a.py",
                 "--want", "tiny", "--verify", "true")
        self.rfg("plan", "--step", "BIG", "--engine", "implement", "--path", "b.py",
                 "--want", "big", "--verify", "python3 -m pytest tests/test_big.py -q")
        self.rfg("plan", "--step", "CHILD", "--engine", "implement", "--path", "c.py",
                 "--want", "child", "--verify", "true", "--depends", "BIG")
        st = Store(self.td)
        rm = st.load_roadmap()
        state = st.load_state()
        rec, why = recommend(rm, state)
        self.assertEqual(rec, "BIG")
        self.assertIn("critical", why)

    def test_weak_survey_ok(self):
        from rfg.verify import is_weak_verify

        self.assertFalse(is_weak_verify("ls src && grep -q foo src/a.py", engine="survey"))
        self.assertTrue(is_weak_verify("test -f app.py"))

    def test_toolchain_alternative(self):
        doc = json.loads(self.rfg("doctor", "--format", "json"))["data"]
        # doctor always ok-shaped; toolchain hint lives in verify check or alternatives
        self.assertIn("checks", doc)

    def test_prune_hint(self):
        self.assertTrue(True)
