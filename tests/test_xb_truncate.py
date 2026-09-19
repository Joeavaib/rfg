"""XB truncation visibility tests (warn-only, no gate/rank/cap change)."""

import os
import unittest
from unittest import mock


def _step(sid, paths=(), depends=()):
    from rfg.types import Step

    s = Step(id=sid, title=sid, depends_on=list(depends))
    s.paths = list(paths)
    return s


class TruncateTest(unittest.TestCase):
    def test_truncation_is_visible_warn_only(self):
        from rfg.verify import related_step_ids

        try:
            from rfg.verify import related_total_count
        except ImportError:
            related_total_count = None  # type: ignore

        me = _step("me", ["s.py"])
        others = [_step(f"o{i:02d}", ["s.py"]) for i in range(12)]
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RFG_RELATED_MAX", None)
            capped = related_step_ids([me, *others], me)
            self.assertLessEqual(len(capped), 10)
        if related_total_count is None:
            # Red-phase: skip statt Tautologie (kein Fake-Gruen ohne Beweis).
            self.skipTest("related_total_count fehlt")
        else:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RFG_RELATED_MAX", None)
                total = related_total_count([me, *others], me)
                self.assertGreater(total, 10)
                self.assertGreater(total, len(capped))
                # ranking/cap unchanged: capped is prefix of uncapped order
                from rfg.verify import uncapped_related_step_ids

                full = uncapped_related_step_ids([me, *others], me)
                self.assertEqual(len(full), total)
                self.assertEqual(capped, full[: len(capped)])

        # CLI: exit stays 0, truncation visible in payload once implemented.
        import io
        import json
        import shutil
        import subprocess
        import tempfile
        from contextlib import redirect_stdout
        from pathlib import Path

        from rfg.cli import CLI

        td = tempfile.mkdtemp(prefix="rfg-xb3-")
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.test",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.test"})
        subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
        subprocess.check_call(["git", "commit", "--allow-empty", "-qm", "i"], cwd=td, env=env)
        Path(td, "s.py").write_text("x = 1\n")
        c = CLI(td, True, False)
        with redirect_stdout(io.StringIO()):
            c.cmd_plan(["--step", "ME", "--engine", "implement", "--path", "s.py",
                        "--want", "me", "--verify", 'python3 -c "assert True"'])
            for i in range(12):
                c.cmd_plan(["--step", f"O{i:02d}", "--engine", "implement",
                            "--path", "s.py", "--want", f"o{i:02d}",
                            "--verify", 'python3 -c "assert True"'])
            c.cmd_apply(["ME"])
            for i in range(12):
                c.cmd_apply([f"O{i:02d}"])
            with redirect_stdout(io.StringIO()) as buf:
                code = c.cmd_verify(["ME"])
        self.assertEqual(code, 0, buf.getvalue())
        payload = json.loads(buf.getvalue())["data"]
        if related_total_count is None:
            return  # red phase: exit-0 only
        self.assertIn("related_total", payload, payload)
        self.assertIn("related_truncated", payload, payload)
        self.assertGreater(payload["related_total"], 10, payload)
        self.assertTrue(payload["related_truncated"], payload)

    def test_total_before_applied_untruncated_and_cap_boundary(self):
        from rfg.verify import (
            related_step_ids,
            related_total_count,
            related_was_truncated,
            uncapped_related_step_ids,
            _related_cap,
        )

        me = _step("me", ["s.py"])
        few = [_step(f"o{i:02d}", ["s.py"]) for i in range(3)]
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RFG_RELATED_MAX", None)
            capped = related_step_ids([me, *few], me)
            total = related_total_count([me, *few], me)
        self.assertEqual(total, 3)
        self.assertEqual(len(capped), 3)
        self.assertFalse(related_was_truncated(total, len(capped)))

        others = [_step(f"o{i:02d}", ["s.py"]) for i in range(12)]
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RFG_RELATED_MAX", None)
            full = uncapped_related_step_ids([me, *others], me)
            capped = related_step_ids([me, *others], me)
            cap = _related_cap()
        self.assertEqual(len(capped), cap)
        self.assertEqual(capped, full[:cap])
        self.assertEqual(capped[-1], full[cap - 1])
        self.assertNotIn(full[cap], capped)
        self.assertTrue(related_was_truncated(len(full), len(capped)))

        import io
        import json
        import shutil
        import subprocess
        import tempfile
        from contextlib import redirect_stdout
        from pathlib import Path

        from rfg.cli import CLI

        td = tempfile.mkdtemp(prefix="rfg-xb3b-")
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.test",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.test"})
        subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
        subprocess.check_call(["git", "commit", "--allow-empty", "-qm", "i"], cwd=td, env=env)
        Path(td, "s.py").write_text("x = 1\n")
        c = CLI(td, True, False)
        with redirect_stdout(io.StringIO()):
            c.cmd_plan(["--step", "ME", "--engine", "implement", "--path", "s.py",
                        "--want", "me", "--verify", 'python3 -c "assert True"'])
            for i in range(12):
                c.cmd_plan(["--step", f"O{i:02d}", "--engine", "implement",
                            "--path", "s.py", "--want", f"o{i:02d}",
                            "--verify", 'python3 -c "assert True"'])
            c.cmd_apply(["ME"])
            with redirect_stdout(io.StringIO()) as buf:
                code = c.cmd_verify(["ME"])
        self.assertEqual(code, 0, buf.getvalue())
        payload = json.loads(buf.getvalue())["data"]
        self.assertGreater(payload["related_total"], 10, payload)
        self.assertTrue(payload["related_truncated"], payload)

        td2 = tempfile.mkdtemp(prefix="rfg-xb3c-")
        self.addCleanup(shutil.rmtree, td2, ignore_errors=True)
        subprocess.check_call(["git", "init", "-q"], cwd=td2, env=env)
        subprocess.check_call(["git", "commit", "--allow-empty", "-qm", "i"], cwd=td2, env=env)
        Path(td2, "s.py").write_text("x = 1\n")
        c2 = CLI(td2, True, False)
        with redirect_stdout(io.StringIO()):
            c2.cmd_plan(["--step", "ME", "--engine", "implement", "--path", "s.py",
                         "--want", "me", "--verify", 'python3 -c "assert True"'])
            c2.cmd_plan(["--step", "O1", "--engine", "implement", "--path", "s.py",
                         "--want", "o1", "--verify", 'python3 -c "assert True"'])
            c2.cmd_plan(["--step", "O2", "--engine", "implement", "--path", "s.py",
                         "--want", "o2", "--verify", 'python3 -c "assert True"'])
            c2.cmd_apply(["ME"])
            with redirect_stdout(io.StringIO()) as buf2:
                code2 = c2.cmd_verify(["ME"])
        self.assertEqual(code2, 0, buf2.getvalue())
        p2 = json.loads(buf2.getvalue())["data"]
        self.assertEqual(p2["related_total"], 2, p2)
        self.assertFalse(p2["related_truncated"], p2)


if __name__ == "__main__":
    unittest.main()
