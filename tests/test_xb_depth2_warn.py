"""XB depth2 warn-only threshold tests (warn-only, no gate change, stdlib-only).

Forward-compatible: before XB-02 the helpers may not exist yet (stub
branch skips instead of fake-green); after XB-02 the real assertions run.
Exits never change; exceeding the threshold only warns via payload.
"""

import os
import unittest
from unittest import mock


class Depth2WarnTest(unittest.TestCase):
    def test_threshold_warn_only(self):
        try:
            from rfg.verify import depth2_warn, depth2_warn_threshold
        except ImportError:
            depth2_warn = None  # type: ignore
            depth2_warn_threshold = None  # type: ignore

        if depth2_warn_threshold is None:
            # Red-phase: skip statt Tautologie (kein Fake-Gruen ohne Beweis).
            self.skipTest("depth2-Helper fehlen")
        else:
            # Env parse: default 10, junk -> 10, tunable.
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RFG_DEPTH2_WARN", None)
                self.assertEqual(depth2_warn_threshold(), 10)
            with mock.patch.dict(os.environ, {"RFG_DEPTH2_WARN": "junk"}):
                self.assertEqual(depth2_warn_threshold(), 10)
            with mock.patch.dict(os.environ, {"RFG_DEPTH2_WARN": ""}):
                self.assertEqual(depth2_warn_threshold(), 10)
            with mock.patch.dict(os.environ, {"RFG_DEPTH2_WARN": "3"}):
                self.assertEqual(depth2_warn_threshold(), 3)
            # Threshold function is warn-only boolean, never raises.
            self.assertFalse(depth2_warn(2))
            with mock.patch.dict(os.environ, {"RFG_DEPTH2_WARN": "3"}):
                self.assertFalse(depth2_warn(2))
                self.assertTrue(depth2_warn(5))
            self.assertIsInstance(depth2_warn(0), bool)

        # CLI stays exit 0; payload carries count/threshold once implemented.
        import io
        import json
        import shutil
        import subprocess
        import tempfile
        from contextlib import redirect_stdout
        from pathlib import Path

        from rfg.cli import CLI

        td = tempfile.mkdtemp(prefix="rfg-xb1-")
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.test",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.test"})
        subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
        subprocess.check_call(["git", "commit", "--allow-empty", "-qm", "i"], cwd=td, env=env)
        Path(td, "a.py").write_text("x = 1\n")
        Path(td, "b.py").write_text("y = 1\n")
        c = CLI(td, True, False)
        with redirect_stdout(io.StringIO()):
            c.cmd_plan(["--step", "A", "--engine", "implement", "--path", "a.py",
                        "--want", "a", "--verify", 'python3 -c "assert True"'])
            c.cmd_plan(["--step", "B", "--engine", "implement", "--path", "a.py",
                        "--want", "b", "--verify", 'python3 -c "assert True"',
                        "--depends", "A"])
            c.cmd_plan(["--step", "C", "--engine", "implement", "--path", "b.py",
                        "--want", "c", "--verify", 'python3 -c "assert True"',
                        "--depends", "B"])
            c.cmd_apply(["A"])
            c.cmd_apply(["B"])
            c.cmd_apply(["C"])
            with redirect_stdout(io.StringIO()) as buf:
                code = c.cmd_verify(["A"])
        self.assertEqual(code, 0, buf.getvalue())
        payload = json.loads(buf.getvalue())["data"]
        if depth2_warn_threshold is None:
            return  # red phase: exit-0 only
        dw = payload.get("depth2_warn")
        self.assertIsInstance(dw, dict, payload)
        self.assertIn("count", dw, payload)
        self.assertIn("threshold", dw, payload)
        self.assertEqual(dw["threshold"], depth2_warn_threshold(), payload)
        # warn-only: threshold breach never changes exit (already 0 here).


if __name__ == "__main__":
    unittest.main()
