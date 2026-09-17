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


if __name__ == "__main__":
    unittest.main()
