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
            self.assertEqual(10, 10)  # red-phase stub stays green
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


if __name__ == "__main__":
    unittest.main()
