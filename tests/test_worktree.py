"""Worktree repair tests (V0.1, test-first).

WorktreePruneTest pins the missing behavior (RED until V0.1-impl);
WorktreeEnsureTest locks the already-working paths (characterization).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env() -> dict:
    e = os.environ.copy()
    e.update(
        {
            "PYTHONPATH": str(ROOT),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t.test",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t.test",
        }
    )
    return e


class _Repo(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-wt-")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.env = _env()
        subprocess.check_call(["git", "init", "-q"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)
        Path(self.td, "app.py").write_text("x = 1\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env,
                              stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-qm", "i"], cwd=self.td, env=self.env)

    def worktree_list(self) -> str:
        r = subprocess.run(["git", "worktree", "list"], cwd=self.td, env=self.env,
                           capture_output=True, text=True)
        return r.stdout


class WorktreePruneTest(_Repo):
    def test_prune_removes_stale_entry(self):
        from rfg import gitops

        wt = gitops.ensure_worktree(self.td)
        self.assertTrue(Path(wt).is_dir())
        # simulate manual deletion: path gone, registration stale (prunable)
        shutil.rmtree(wt)
        self.assertIn("prunable", self.worktree_list())
        gitops.prune_worktrees(self.td)
        self.assertNotIn("prunable", self.worktree_list())

    def test_broken_gitdir_healed(self):
        from rfg import gitops

        wt = Path(gitops.ensure_worktree(self.td))
        (wt / ".git").write_text("gitdir: /nonexistent/rcg/.git/worktrees/worktree\n")
        healed = Path(gitops.ensure_worktree(self.td))
        self.assertEqual(healed.resolve(), wt.resolve())
        r = subprocess.run(["git", "-C", str(healed), "rev-parse", "HEAD"], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("prunable", self.worktree_list())

    def test_ensure_idempotent(self):
        from rfg import gitops

        wt1 = Path(gitops.ensure_worktree(self.td))
        (wt1 / "marker.txt").write_text("keep\n")
        wt2 = Path(gitops.ensure_worktree(self.td))
        self.assertEqual(wt1.resolve(), wt2.resolve())
        self.assertTrue((wt2 / "marker.txt").is_file())


class WorktreeEnsureTest(_Repo):
    def test_worktree_usable_predicate(self):
        from rfg import gitops

        wt = Path(gitops.ensure_worktree(self.td))
        self.assertTrue(gitops._worktree_usable(wt))
        (wt / ".git").write_text("gitdir: /nonexistent/nowhere\n")
        self.assertFalse(gitops._worktree_usable(wt))
        self.assertFalse(gitops._worktree_usable(Path(self.td) / "nope"))

    def test_deleted_worktree_recreated(self):
        from rfg import gitops

        wt = Path(gitops.ensure_worktree(self.td))
        (wt / "app.py").write_text("x = 2\n")
        shutil.rmtree(wt, ignore_errors=True)
        wt2 = Path(gitops.ensure_worktree(self.td))
        self.assertTrue((wt2 / "app.py").is_file())
        self.assertNotIn("prunable", self.worktree_list())

    def test_root_work_untouched(self):
        from rfg import gitops

        wt = Path(gitops.ensure_worktree(self.td))
        (wt / ".git").write_text("gitdir: /nonexistent/nowhere\n")
        before = Path(self.td, "app.py").read_text()
        gitops.ensure_worktree(self.td)
        self.assertEqual(Path(self.td, "app.py").read_text(), before)


if __name__ == "__main__":
    unittest.main()
