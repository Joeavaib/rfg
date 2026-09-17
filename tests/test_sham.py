"""Sham-green tests (V2, test-first).

ShamStrictTest pins tautology detection (RED until V2-impl).
Scope decision (Red team, pinned here): targeted selection
(`-k`, `--deselect`, file targets) is legitimate scoping and is
NOT sham; only tautologies (`assert True`, `exit 0`) are.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RFG = [sys.executable, str(ROOT / "rfg.py")]
_BARE_TAUTOLOGY = re.compile(r"^\s*(self\.)?assertTrue\(True\)\s*$")


class ShamStrictTest(unittest.TestCase):
    def test_tautologies_are_sham(self):
        from rfg.verify import is_sham_verify

        self.assertTrue(is_sham_verify('python3 -c "assert True"'))
        self.assertTrue(is_sham_verify("python3 -c \"assertTrue(True)\""))
        self.assertTrue(is_sham_verify("sh -c 'exit 0'"))
        self.assertFalse(is_sham_verify("pytest tests/test_x.py -q"))
        self.assertFalse(is_sham_verify(""))
        self.assertFalse(is_sham_verify('python3 -c "assert True"', engine="survey"))

    def test_selection_is_not_sham(self):
        from rfg.verify import is_sham_verify

        self.assertFalse(is_sham_verify("pytest tests/test_x.py -q -k foo"))
        self.assertFalse(is_sham_verify("pytest tests/ --deselect tests/test_y.py -q"))

    def test_doctor_warns_sham(self):
        from rfg import doctor
        from rfg.types import Step

        s = Step(id="s1", title="t", engine="implement", verify='python3 -c "assert True"')
        warns = doctor.oracle_warnings([s])
        self.assertTrue(any("sham-verify" in w and "s1" in w for w in warns), warns)

    def test_no_bare_tautologies_in_suite(self):
        hits = []
        for t in sorted((ROOT / "tests").glob("test_*.py")):
            for n, line in enumerate(t.read_text(encoding="utf-8").splitlines(), 1):
                if _BARE_TAUTOLOGY.match(line):
                    hits.append(f"{t.name}:{n}")
        self.assertEqual(hits, [], hits)


class ShamCheckTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-sham-")
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
        subprocess.check_call(["git", "init", "-q"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)

    def rfg(self, *args, code=0):
        r = subprocess.run(
            RFG + ["--root", self.td, *args],
            cwd=self.td, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def test_check_default_ignores_sham_strict_errors(self):
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--path", "a.py", "--want", "w",
                 "--verify", "python3 -c \"assert True\"")
        out = json.loads(self.rfg("plan", "--check", "--format", "json"))["data"]
        self.assertTrue(out["ok"], out)
        out = json.loads(self.rfg("plan", "--check", "--strict", "--format", "json", code=5))["data"]
        self.assertFalse(out["ok"])
        kinds = {(f["kind"], f["step"]) for f in out.get("findings") or []}
        self.assertIn(("sham-verify", "s1"), kinds)


class DoctorRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-rec-")
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

    def rfg(self, *args, code=0):
        r = subprocess.run(
            RFG + ["--root", self.td, *args],
            cwd=self.td, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def _detail(self):
        from rfg import doctor

        got = doctor.run(Path(self.td))["checks"]["recovery"]
        self.assertTrue(got["ok"], got)
        return got["detail"]

    def test_missing_store_with_backups_warns_restore(self):
        bak = Path(self.td, ".rfg", "land-backups", "20240101T000000-abcdef01")
        bak.mkdir(parents=True)
        (bak / "roadmap.yaml").write_text("x\n")
        (bak / "state.json").write_text("{}\n")
        detail = self._detail()
        self.assertTrue(any("restore" in n for n in detail), detail)

    def test_healthy_store_reports_ok(self):
        subprocess.check_call(["git", "init", "-q"], cwd=self.td, env=self.env)
        Path(self.td, "app.py").write_text("x = 1\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-qm", "i"], cwd=self.td, env=self.env)
        self.rfg("init")
        self.assertEqual(self._detail(), "ok")

    def test_dirty_worktree_warns(self):
        from rfg import gitops

        subprocess.check_call(["git", "init", "-q"], cwd=self.td, env=self.env)
        Path(self.td, "app.py").write_text("x = 1\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-qm", "i"], cwd=self.td, env=self.env)
        self.rfg("init")
        wt = Path(gitops.ensure_worktree(self.td))
        (wt / "app.py").write_text("x = 2\n")
        subprocess.check_call(["git", "add", "-A"], cwd=wt, env=self.env, stdout=subprocess.DEVNULL)
        detail = self._detail()
        self.assertTrue(any("worktree" in n for n in detail), detail)


if __name__ == "__main__":
    unittest.main()
