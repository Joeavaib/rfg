"""Cross-verify triage tests (D3, test-first).

TriageTest pins: 127/timeout/pre-existing/assert-fail get labels,
exits never change (RED until D3).
"""

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TriageTest(unittest.TestCase):
    def test_labels(self):
        from rfg.cli import triage_cross_failure

        self.assertEqual(triage_cross_failure(127, "mvn: command not found", False),
                         "ENV/toolchain-missing")
        self.assertEqual(triage_cross_failure(4, "unsupported oracle", False),
                         "ENV/unsupported")
        self.assertEqual(triage_cross_failure(2, "verify timeout", False),
                         "COST/timeout")
        self.assertEqual(triage_cross_failure(1, "assert fail", True),
                         "PRE-EXISTING/neighbor-already-red")
        self.assertEqual(triage_cross_failure(1, "assert fail", False),
                         "REGRESS-SUSPECT/assert-fail")

    def test_fail_message_carries_triage_exits_unchanged(self):
        from rfg.cli import CLI

        td = tempfile.mkdtemp(prefix="rfg-ct-")
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(ROOT), "GIT_AUTHOR_NAME": "t",
                    "GIT_AUTHOR_EMAIL": "t@t.test", "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@t.test"})
        subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
        subprocess.check_call(["git", "commit", "--allow-empty", "-qm", "i"], cwd=td, env=env)
        Path(td, "a.py").write_text("x = 1\n")
        c = CLI(td, True, False)
        with redirect_stdout(io.StringIO()):
            c.cmd_plan(["--step", "A", "--engine", "implement", "--path", "a.py",
                        "--want", "a", "--verify", 'python3 -c "assert True"'])
            c.cmd_plan(["--step", "B", "--engine", "implement", "--path", "a.py",
                        "--want", "b", "--verify", 'python3 -c "assert False"',
                        "--depends", "A"])
            c.cmd_apply(["A"])
            c.cmd_apply(["B"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = c.cmd_verify(["A"])
        self.assertEqual(code, 2, buf.getvalue())
        err = json.loads(buf.getvalue())
        self.assertIn("triage:", err.get("error", ""))
        self.assertIn("REGRESS-SUSPECT", err.get("error", ""))

    def _applied_overlap(self, b_verify, mark_b_failed=False):
        td = tempfile.mkdtemp(prefix="rfg-ct-")
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(ROOT), "GIT_AUTHOR_NAME": "t",
                    "GIT_AUTHOR_EMAIL": "t@t.test", "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@t.test"})
        subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
        subprocess.check_call(["git", "commit", "--allow-empty", "-qm", "i"], cwd=td, env=env)
        Path(td, "a.py").write_text("x = 1\n")
        from rfg.cli import CLI

        c = CLI(td, True, False)
        with redirect_stdout(io.StringIO()):
            c.cmd_plan(["--step", "A", "--engine", "implement", "--path", "a.py",
                        "--want", "a", "--verify", 'python3 -c "assert True"'])
            c.cmd_plan(["--step", "B", "--engine", "implement", "--path", "a.py",
                        "--want", "b", "--verify", b_verify, "--depends", "A"])
            c.cmd_apply(["A"])
            c.cmd_apply(["B"])
        if mark_b_failed:
            from rfg.store import Store

            st = Store(td)
            state = st.load_state()
            if "B" not in state.failed:
                state.failed.append("B")
            st.write_state(state)
        return c, td

    def test_e2e_127_env_label_exit_2(self):
        c, _ = self._applied_overlap("rfg-missing-binary-xyz --nope")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = c.cmd_verify(["A"])
        self.assertEqual(code, 2, buf.getvalue())
        err = json.loads(buf.getvalue())
        self.assertIn("ENV/toolchain-missing", err.get("error", ""))
        self.assertIn("triage:", err.get("error", ""))

    def test_e2e_preexisting_from_state_exit_2(self):
        c, _ = self._applied_overlap('python3 -c "assert False"', mark_b_failed=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = c.cmd_verify(["A"])
        self.assertEqual(code, 2, buf.getvalue())
        err = json.loads(buf.getvalue())
        self.assertIn("PRE-EXISTING/neighbor-already-red", err.get("error", ""))

    def test_e2e_timeout_label(self):
        from unittest import mock

        c, _ = self._applied_overlap('python3 -c "import time; time.sleep(30)"')
        env = dict(os.environ, RFG_VERIFY_TIMEOUT="1", RFG_CROSS_BUDGET="60")
        with mock.patch.dict(os.environ, env, clear=False):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = c.cmd_verify(["A"])
        self.assertEqual(code, 0, buf.getvalue())
        payload = json.loads(buf.getvalue())["data"]
        skipped = payload.get("skipped") or []
        hit = [s for s in skipped if s.get("step") == "B" and "timeout" in s.get("reason", "")]
        self.assertTrue(hit, payload)
        self.assertEqual(hit[0].get("triage"), "COST/timeout")


if __name__ == "__main__":
    unittest.main()
