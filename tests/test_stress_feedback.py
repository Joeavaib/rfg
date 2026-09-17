"""Stress-feedback hardening tests (H01-H05)."""
import unittest

from rfg.types import coerce_depends_list


class StressFeedbackTest(unittest.TestCase):
    def test_depends_array_string(self):
        # '["G02", "G03"]' must become two deps, not broken bracket entries
        self.assertEqual(coerce_depends_list('["G02", "G03"]'), ["G02", "G03"])
        self.assertEqual(coerce_depends_list(["G02", "G03"]), ["G02", "G03"])
        self.assertEqual(coerce_depends_list("G02,G03"), ["G02", "G03"])
        self.assertEqual(coerce_depends_list("G02"), ["G02"])
        # CLI path
        from rfg.cli import CLI
        import tempfile, os
        from pathlib import Path
        from rfg.store import Store
        with tempfile.TemporaryDirectory() as td:
            os.system(f"git init -q {td} 2>/dev/null")
            Path(td, "a.py").write_text("x=1\n")
            c = CLI(td, True, False)
            self.assertEqual(c.cmd_plan(["--step", "S1", "--path", "a.py", "--want", "w",
                                         "--verify", "true", "--depends", '["G02", "G03"]']), 0)
            rm = Store(td).load_roadmap()
            s = next(x for x in rm.steps if x.id == "S1")
            self.assertEqual(s.depends_on, ["G02", "G03"])

    def test_extra_visible(self):
        import json, os, subprocess, tempfile
        from pathlib import Path
        from rfg.cli import CLI
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            subprocess.check_call(["git", "add", "-A"], cwd=td, env=env)
            subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"],
                                  cwd=td, env=env, stdout=subprocess.DEVNULL)
            Path(td, "app.py").write_text("ok\n")
            Path(td, "extra2.py").write_text("ok2\n")
            c = CLI(td, True, False)
            self.assertEqual(c.cmd_plan(["--step", "S", "--engine", "implement",
                                         "--path", "app.py", "--want", "x",
                                         "--verify", 'python3 -c "assert True"']), 0)
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = c.cmd_apply([])
            self.assertEqual(code, 0)
            payload = json.loads(buf.getvalue())
            data = payload.get("data", payload)
            # extras must be staged (in worktree), not silently omitted
            self.assertIn("extra2.py", data.get("staged") or [])
            # warning when extras exist
            self.assertTrue(data.get("warning") or data.get("extra_warning"),
                            f"expected extra warning, got {data}")

    def test_verify_dedup(self):
        from rfg.doctor import oracle_warnings
        from rfg.types import Step
        steps = [Step(id=f"S{i}", verify="python3 -m pytest -q") for i in range(5)]
        warns = oracle_warnings(steps)
        # must warn but must NOT contain a hard conflict marker
        self.assertTrue(any("pytest" in w for w in warns))
        self.assertFalse(any("used on 5" in w for w in warns),
                         f"5x identical verify must not be a conflict brake: {warns}")
        # plan with 5 identical verifies must not return CONFLICT (5)
        import tempfile, os
        from pathlib import Path
        from rfg.cli import CLI
        with tempfile.TemporaryDirectory() as td:
            os.system(f"git init -q {td} 2>/dev/null")
            Path(td, "a.py").write_text("x=1\n")
            c = CLI(td, True, False)
            for i in range(5):
                code = c.cmd_plan(["--step", f"S{i}", "--path", "a.py",
                                   "--want", "w", "--verify", "python3 -m pytest -q"])
                self.assertNotEqual(code, 5, f"plan S{i} blocked by verify brake")

    def test_cross_verify(self):
        # verify must also run dependents + path-overlap steps
        import tempfile, os, subprocess
        from pathlib import Path
        from rfg.cli import CLI
        from rfg.store import Store
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            subprocess.check_call(["git", "commit", "--allow-empty", "-m", "i"],
                                  cwd=td, env=env, stdout=subprocess.DEVNULL)
            Path(td, "a.py").write_text("x=1\n")
            Path(td, "b.py").write_text("y=2\n")
            c = CLI(td, True, False)
            c.cmd_plan(["--step", "A", "--engine", "implement", "--path", "a.py",
                        "--want", "a", "--verify", 'python3 -c "assert True"'])
            c.cmd_plan(["--step", "B", "--engine", "implement", "--path", "a.py",
                        "--want", "b", "--verify", 'python3 -c "assert False, overlap-fail"',
                        "--depends", "A"])
            # apply A and B then verify A -> must surface B's overlapping verify failure
            # (B is applied so its failing verify is a real regression signal)
            import io
            from contextlib import redirect_stdout
            with redirect_stdout(io.StringIO()):
                c.cmd_apply(["A"])
            with redirect_stdout(io.StringIO()):
                c.cmd_apply(["B"])
            with redirect_stdout(io.StringIO()):
                code = c.cmd_verify(["A"])
            # cross-verify surfaces overlap failure (nonzero or payload mentions it)
            self.assertNotEqual(code, 0, "cross-verify must fail when overlapping step fails")

    def test_land_gate(self):
        # land must run a global gate (rm.verify / acceptance) even if last step verify passed
        import tempfile, os, subprocess
        from pathlib import Path
        from rfg.cli import CLI
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            subprocess.check_call(["git", "commit", "--allow-empty", "-m", "i"],
                                  cwd=td, env=env, stdout=subprocess.DEVNULL)
            Path(td, "a.py").write_text("x=1\n")
            c = CLI(td, True, False)
            c.cmd_plan(["--step", "A", "--engine", "implement", "--path", "a.py",
                        "--want", "a", "--verify", 'python3 -c "assert True"'])
            c.cmd_plan(["--verify", 'python3 -c "assert False, gate-fail"'])
            import io
            from contextlib import redirect_stdout
            with redirect_stdout(io.StringIO()):
                c.cmd_apply(["A"])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(c.cmd_verify(["A"]), 0)
            with redirect_stdout(io.StringIO()):
                code = c.cmd_land([])
            self.assertNotEqual(code, 0, "land must fail when global gate fails")


if __name__ == "__main__":
    unittest.main()
