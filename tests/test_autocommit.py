"""Auto-commit after land (H1): opt-in, local only, never push."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RFG = [sys.executable, str(ROOT / "rfg.py")]


class AutocommitTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-ac-")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.td], check=False))
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
        subprocess.check_call(["git", "commit", "--allow-empty", "-m", "i"], cwd=self.td, env=self.env,
                              stdout=subprocess.DEVNULL)
        # realistic: .rfg/ ignored (prod failure mode for explicit pathspecs)
        Path(self.td, ".gitignore").write_text(".rfg/\n")

    def rfg(self, *args, code=0, env=None):
        r = subprocess.run(
            RFG + ["--root", self.td, *args],
            cwd=self.td, env=env or self.env, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def _campaign(self):
        self.rfg("init")
        Path(self.td, "app.py").write_text("x = 1\n")
        self.rfg("plan", "--step", "s1", "--engine", "implement", "--path", "app.py",
                 "--want", "w", "--verify", "python3 -c \"assert True\"")
        self.rfg("tick", "s1")
        self.rfg("apply", "s1")
        self.rfg("verify", "s1")

    def _commits(self):
        r = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=self.td,
                           env=self.env, capture_output=True, text=True)
        return int(r.stdout.strip())

    def test_land_without_optin_does_not_commit(self):
        self._campaign()
        before = self._commits()
        land = json.loads(self.rfg("land", "--format", "json"))["data"]
        self.assertNotIn("commit", land)
        self.assertEqual(self._commits(), before)

    def test_land_with_flag_commits(self):
        self._campaign()
        before = self._commits()
        land = json.loads(self.rfg("land", "--commit", "--format", "json"))["data"]
        self.assertIn("commit", land, land)
        self.assertEqual(self._commits(), before + 1)
        msg = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=self.td,
                             env=self.env, capture_output=True, text=True).stdout
        self.assertIn("rfg land", msg)

    def test_land_with_env_commits(self):
        self._campaign()
        before = self._commits()
        env = dict(self.env, RFG_AUTO_COMMIT="1")
        land = json.loads(self.rfg("land", "--format", "json", env=env))["data"]
        self.assertIn("commit", land, land)
        self.assertEqual(self._commits(), before + 1)

    def test_no_commit_flag_wins_over_env(self):
        self._campaign()
        before = self._commits()
        env = dict(self.env, RFG_AUTO_COMMIT="1")
        land = json.loads(self.rfg("land", "--no-commit", "--format", "json", env=env))["data"]
        self.assertNotIn("commit", land)
        self.assertEqual(self._commits(), before)

    def test_clean_tree_skips_commit(self):
        self._campaign()
        first = json.loads(self.rfg("land", "--commit", "--format", "json"))["data"]
        self.assertIn("commit", first, first)
        before = self._commits()
        second = json.loads(self.rfg("land", "--commit", "--format", "json"))["data"]
        self.assertIn("commit_skipped", second, second)
        self.assertEqual(self._commits(), before)

    def test_commit_failure_warns_but_land_stays_ok(self):
        from rfg import gitops

        self._campaign()
        # break the commit (no identity) while landing must still succeed
        env = dict(self.env, RFG_AUTO_COMMIT="1",
                   GIT_AUTHOR_NAME="", GIT_AUTHOR_EMAIL="",
                   GIT_COMMITTER_NAME="", GIT_COMMITTER_EMAIL="")
        subprocess.run(["git", "config", "--unset", "user.email"], cwd=self.td, env=self.env)
        subprocess.run(["git", "config", "--unset", "user.name"], cwd=self.td, env=self.env)
        # git auto-detects identity from OS user/host when unconfigured;
        # force the no-identity failure this test needs.
        subprocess.run(["git", "config", "user.useConfigOnly", "true"], cwd=self.td, env=self.env)
        r = subprocess.run(RFG + ["--root", self.td, "land", "--format", "json"],
                           cwd=self.td, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("commit_warning", r.stdout, r.stdout)
        self.assertRaises(RuntimeError, gitops.commit_all, self.td, "x")

    def test_commit_all_clean_tree_returns_empty(self):
        from rfg import gitops

        sha = gitops.commit_all(self.td, "snap")
        self.assertTrue(sha)
        # ignored .rfg/ churn must not trigger commits either (prod failure mode)
        Path(self.td, ".rfg").mkdir(exist_ok=True)
        Path(self.td, ".rfg", "state.json").write_text("{}\n")
        self.assertEqual(gitops.commit_all(self.td, "nothing"), "")

    def test_never_pushes(self):
        self._campaign()
        env = dict(self.env, RFG_AUTO_COMMIT="1")
        self.rfg("land", "--format", "json", env=env)
        # no remote configured and none must have been added by the commit path
        r = subprocess.run(["git", "remote"], cwd=self.td, env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "")
        # the commit helper issues no push invocation (quoted arg form)
        src = (ROOT / "rfg" / "gitops.py").read_text(encoding="utf-8")
        self.assertNotIn('"push"', src)
        self.assertNotIn("'push'", src)

    def test_maybe_autocommit_off_by_default(self):
        from types import SimpleNamespace

        from rfg.cli import CLI

        c = CLI(self.td, True, False)
        rm = SimpleNamespace(steps=[], goal=SimpleNamespace(statement="g"))
        st = SimpleNamespace(verified=[])
        self.assertEqual(c._maybe_autocommit(rm, st, []), {})

    def test_rfg_dir_never_committed(self):
        self._campaign()
        env = dict(self.env, RFG_AUTO_COMMIT="1")
        self.rfg("land", "--format", "json", env=env)
        r = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=self.td,
                           env=self.env, capture_output=True, text=True)
        names = r.stdout.split()
        self.assertIn("app.py", names)
        self.assertFalse(any(n == ".rfg" or n.startswith(".rfg/") for n in names), names)


if __name__ == "__main__":
    unittest.main()
