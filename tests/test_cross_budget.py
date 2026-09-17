"""Cross-verify budget tests (D2, test-first).

BudgetTest pins: deadline with skip-with-reason (never silent),
per-verify timeout capped by remaining budget, neighbor timeout
degrades to warn instead of fail (RED until D2).
"""

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-cb-")
        self.addCleanup(__import__("shutil").rmtree, self.td, ignore_errors=True)
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
        subprocess.check_call(["git", "init", "-q"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "commit", "--allow-empty", "-qm", "i"], cwd=self.td, env=self.env)
        Path(self.td, "a.py").write_text("x = 1\n")

    def _cli(self):
        from rfg.cli import CLI

        return CLI(self.td, True, False)

    def _applied_pair(self, b_verify):
        c = self._cli()
        with redirect_stdout(io.StringIO()):
            c.cmd_plan(["--step", "A", "--engine", "implement", "--path", "a.py",
                        "--want", "a", "--verify", 'python3 -c "assert True"'])
            c.cmd_plan(["--step", "B", "--engine", "implement", "--path", "a.py",
                        "--want", "b", "--verify", b_verify, "--depends", "A"])
            c.cmd_apply(["A"])
            c.cmd_apply(["B"])
        return c

    def test_deadline_skips_with_reason(self):
        c = self._applied_pair('python3 -c "assert True"')
        with mock.patch.dict(os.environ, {"RFG_CROSS_BUDGET": "0.05"}):
            with redirect_stdout(io.StringIO()) as buf:
                code = c.cmd_verify(["A"])
        self.assertEqual(code, 0, buf.getvalue())
        payload = json.loads(buf.getvalue())["data"]
        skipped = payload.get("skipped") or []
        self.assertTrue(any(s.get("step") == "B" and s.get("reason") for s in skipped),
                        payload)

    def test_timeout_degrades_not_fails(self):
        c = self._applied_pair('python3 -c "import time; time.sleep(30)"')
        env = dict(os.environ, RFG_VERIFY_TIMEOUT="1", RFG_CROSS_BUDGET="60")
        with mock.patch.dict(os.environ, env, clear=False):
            with redirect_stdout(io.StringIO()) as buf:
                code = c.cmd_verify(["A"])
        self.assertEqual(code, 0, buf.getvalue())
        payload = json.loads(buf.getvalue())["data"]
        skipped = payload.get("skipped") or []
        self.assertTrue(any(s.get("step") == "B" and "timeout" in s.get("reason", "")
                            for s in skipped),
                        payload)

    def test_related_timeout_helper(self):
        from rfg.cli import cross_timeout_for

        self.assertEqual(cross_timeout_for(100.0, 60.0), 60.0)
        self.assertEqual(cross_timeout_for(3.0, 60.0), 3.0)
        self.assertLessEqual(cross_timeout_for(0.0, 60.0), 5.0)


if __name__ == "__main__":
    unittest.main()
