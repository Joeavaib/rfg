import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RFG = [sys.executable, str(ROOT / "rfg.py")]
GO = ROOT / "testdata" / "fixture"


class H6Test(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-h6-")
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

    def rfg(self, *args, root=None, code=0):
        r = subprocess.run(
            RFG + ["--root", str(root or self.td), *args],
            cwd=str(root or self.td),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def _repo(self, name: str) -> Path:
        p = Path(self.td) / name
        p.mkdir()
        for f in GO.iterdir():
            if f.is_file():
                shutil.copy(f, p / f.name)
        self.rfg("init", root=p)
        return p

    def test_fleet_status_two_repos(self):
        a = self._repo("a")
        b = self._repo("b")
        (Path(self.td) / ".rfg").mkdir(exist_ok=True)
        (Path(self.td) / ".rfg" / "fleet.yaml").write_text(
            "repos:\n"
            f"  - name: one\n    path: {a}\n"
            f"  - name: two\n    path: {b}\n"
        )
        self.rfg("init")
        out = json.loads(self.rfg("fleet", "--format", "json"))
        names = {r["name"] for r in out["data"]["repos"]}
        self.assertEqual(names, {"one", "two"})
        self.assertTrue(out["data"]["ok"])

    def _git(self, p: Path) -> None:
        subprocess.check_call(["git", "init"], cwd=p, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=p, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=p, env=self.env)
        subprocess.check_call(["git", "add", "-A"], cwd=p, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=p, env=self.env, stdout=subprocess.DEVNULL)

    def test_fleet_next(self):
        a = self._repo("a")
        b = self._repo("b")
        self._git(a)
        self._git(b)
        self.rfg(
            "plan",
            "--step",
            "s-a",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--verify",
            "test -n ok",
            root=a,
        )
        self.rfg(
            "plan",
            "--step",
            "s-b",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--verify",
            "test -n ok",
            root=b,
        )
        (Path(self.td) / ".rfg").mkdir(exist_ok=True)
        (Path(self.td) / ".rfg" / "fleet.yaml").write_text(
            "repos:\n"
            f"  - name: one\n    path: {a}\n"
            f"  - name: two\n    path: {b}\n"
        )
        out = json.loads(self.rfg("fleet", "next", "--format", "json"))
        self.assertEqual(out["data"]["repo"], "one")
        self.assertEqual(out["data"]["step"], "s-a")
        self.assertEqual(out["data"]["path"], str(a))
        self.rfg("apply", root=a)
        self.rfg("verify", root=a)
        nxt = json.loads(self.rfg("fleet", "next", "--format", "json"))
        self.assertEqual(nxt["data"]["repo"], "two")
        self.assertEqual(nxt["data"]["step"], "s-b")

    def test_export_batch_file(self):
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        out = json.loads(self.rfg("export", "batch", "--format", "json"))
        self.assertTrue(Path(out["data"]["path"]).is_file())
        self.assertIn("s1", out["data"]["text"])
        self.assertIn("rfg.py apply", out["data"]["text"])

    def test_paid_pack_enable_is_4(self):
        self.rfg("init")
        listed = json.loads(self.rfg("packs", "--format", "json"))
        self.assertIn("loop", listed["data"]["open"])
        self.assertIn("estate-scheduler", listed["data"]["paid"])
        r = subprocess.run(
            RFG + ["--root", self.td, "packs", "enable", "estate-scheduler", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
