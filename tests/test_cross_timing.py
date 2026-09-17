"""Cross timing tests (D4, test-first).

TimingTest pins: elapsed_ms in the cross log header + ledger
verify event; explicitly NO sorting/budget use yet (measure only).
"""

import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TimingTest(unittest.TestCase):
    def test_log_header_has_elapsed(self):
        from rfg.verify import write_log as write_verify_log

        with tempfile.TemporaryDirectory(prefix="rfg-ct-") as td:
            root = Path(td)
            (root / ".rfg").mkdir()
            p = write_verify_log(root, "s1", "pytest -q", 0, "ok", elapsed_ms=123.0)
            head = Path(p).read_text(encoding="utf-8").splitlines()[0]
            self.assertIn("elapsed_ms", head)

    def test_ledger_event_has_elapsed(self):
        from rfg import ledger

        with tempfile.TemporaryDirectory(prefix="rfg-ct-") as td:
            root = Path(td)
            ledger.record_verify_event(root, "t", "s1", 0, "l.log", elapsed_ms=12.5)
            rows = ledger.read_events(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["elapsed_ms"], 12.5)
            self.assertEqual(ledger.counters(root)["t"], {"passes": 1, "fails": 0})

    def test_cross_log_carries_elapsed(self):
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
                        "--want", "b", "--verify", 'python3 -c "assert True"',
                        "--depends", "A"])
            c.cmd_apply(["A"])
            c.cmd_apply(["B"])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(c.cmd_verify(["A"]), 0)
        log = Path(td, ".rfg", "verify", "A__cross_B.log").read_text(encoding="utf-8")
        self.assertIn("elapsed_ms", log.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
