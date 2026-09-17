"""Dedup-memo tests (F1, test-first).

DedupMemoTest pins: identical cross verifies run once (opt-in
RFG_DEDUP_MEMO=1), the rest is listed as deduped (never silent);
different commands always run each once; default stays off.
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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SAME = 'python3 -c "assert True"'


class DedupMemoTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-dm-")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.env = os.environ.copy()
        self.env.update({"PYTHONPATH": str(ROOT), "GIT_AUTHOR_NAME": "t",
                         "GIT_AUTHOR_EMAIL": "t@t.test", "GIT_COMMITTER_NAME": "t",
                         "GIT_COMMITTER_EMAIL": "t@t.test"})
        subprocess.check_call(["git", "init", "-q"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "commit", "--allow-empty", "-qm", "i"], cwd=self.td, env=self.env)
        Path(self.td, "a.py").write_text("x = 1\n")

    def _trio(self, b_verify, c_verify):
        from rfg.cli import CLI

        c = CLI(self.td, True, False)
        with redirect_stdout(io.StringIO()):
            c.cmd_plan(["--step", "A", "--engine", "implement", "--path", "a.py",
                        "--want", "a", "--verify", SAME])
            c.cmd_plan(["--step", "B", "--engine", "implement", "--path", "a.py",
                        "--want", "b", "--verify", b_verify, "--depends", "A"])
            c.cmd_plan(["--step", "C", "--engine", "implement", "--path", "a.py",
                        "--want", "c", "--verify", c_verify, "--depends", "B"])
            c.cmd_apply(["A"])
            c.cmd_apply(["B"])
            c.cmd_apply(["C"])
        return c

    def _verify_a(self, c, **env):
        with mock.patch.dict(os.environ, env, clear=False):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = c.cmd_verify(["A"])
        return code, json.loads(buf.getvalue())["data"]

    def test_memo_reuses_identical(self):
        c = self._trio(SAME, SAME)
        code, payload = self._verify_a(c, RFG_DEDUP_MEMO="1")
        self.assertEqual(code, 0, payload)
        deduped = payload.get("deduped") or []
        self.assertTrue(any(d.get("step") == "C" and d.get("via") == "B"
                            and d.get("reason") for d in deduped), payload)
        self.assertFalse((Path(self.td) / ".rfg" / "verify" / "A__cross_C.log").exists())

    def test_different_commands_always_run(self):
        c = self._trio('python3 -c "print(\'bee\')"', 'python3 -c "print(\'cee\')"')
        code, payload = self._verify_a(c, RFG_DEDUP_MEMO="1")
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload.get("deduped"), payload)
        self.assertTrue((Path(self.td) / ".rfg" / "verify" / "A__cross_B.log").is_file())
        self.assertTrue((Path(self.td) / ".rfg" / "verify" / "A__cross_C.log").is_file())

    def test_default_off(self):
        c = self._trio(SAME, SAME)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RFG_DEDUP_MEMO", None)
            code, payload = self._verify_a(c)
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload.get("deduped"), payload)
        self.assertTrue((Path(self.td) / ".rfg" / "verify" / "A__cross_C.log").is_file())


if __name__ == "__main__":
    unittest.main()
