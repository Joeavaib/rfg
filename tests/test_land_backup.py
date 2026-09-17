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


class LandBackupTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-landbak-")
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
        subprocess.check_call(["git", "init"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)

    def rfg(self, *args, code=0, env=None):
        r = subprocess.run(
            RFG + ["--root", self.td, *args],
            cwd=self.td,
            env=env or self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def _loop(self, verify_cmd):
        Path(self.td, "mod.py").write_text("old\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "B01",
            "--engine",
            "implement",
            "--path",
            "mod.py",
            "--verify",
            verify_cmd,
        )
        Path(self.td, "mod.py").write_text("new\n")
        tick = json.loads(self.rfg("tick", "--format", "json"))
        self.assertEqual(tick["data"]["action"], "stop")
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)
        ver = json.loads(self.rfg("verify", "--format", "json"))
        self.assertTrue(ver["ok"], ver)

    def test_land_writes_state_backup(self):
        self._loop("python3 -c \"assert 'new' in open('mod.py').read()\"")
        land = json.loads(self.rfg("land", "--format", "json"))
        self.assertTrue(land["ok"], land)
        bak = (land["data"] or {}).get("state_backup") or {}
        self.assertTrue(bak.get("dir"), land)
        self.assertIn("roadmap.yaml", bak.get("files") or [], land)
        self.assertIn("state.json", bak.get("files") or [], land)
        bdir = Path(self.td) / ".rfg" / "land-backups" / bak["dir"]
        for name in ("roadmap.yaml", "state.json"):
            src = Path(self.td) / ".rfg" / name
            dst = bdir / name
            self.assertTrue(dst.is_file(), land)
            self.assertEqual(dst.read_bytes(), src.read_bytes(), name)


    def test_failed_land_writes_no_backup(self):
        Path(self.td, "mod.py").write_text("old\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "B02",
            "--engine",
            "implement",
            "--path",
            "mod.py",
            "--verify",
            "exit 1",
        )
        Path(self.td, "mod.py").write_text("new\n")
        tick = json.loads(self.rfg("tick", "--format", "json"))
        self.assertEqual(tick["data"]["action"], "stop")
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)
        ver = json.loads(self.rfg("verify", "--format", "json", code=2))
        self.assertFalse(ver["ok"], ver)
        land = json.loads(self.rfg("land", "--format", "json", code=5))
        self.assertFalse(land["ok"], land)
        self.assertFalse((Path(self.td) / ".rfg" / "land-backups").exists(), land)


    def test_old_backups_pruned(self):
        self._loop("python3 -c \"assert 'new' in open('mod.py').read()\"")
        baks = Path(self.td) / ".rfg" / "land-backups"
        baks.mkdir(parents=True, exist_ok=True)
        for i in range(12):
            (baks / f"20000101T000000-000000{i:02d}").mkdir(parents=True, exist_ok=True)
        land = json.loads(self.rfg("land", "--format", "json"))
        self.assertTrue(land["ok"], land)
        bak = (land["data"] or {}).get("state_backup") or {}
        self.assertTrue(bak.get("dir"), land)
        remaining = sorted(p.name for p in baks.iterdir() if p.is_dir())
        self.assertEqual(len(remaining), 10, remaining)
        self.assertIn(bak["dir"], remaining)
        self.assertNotIn("20000101T000000-00000000", remaining)
        self.assertNotIn("20000101T000000-00000001", remaining)
        self.assertNotIn("20000101T000000-00000002", remaining)


    def test_restore_from_backup_recovers_roadmap(self):
        self._loop("python3 -c \"assert 'new' in open('mod.py').read()\"")
        land = json.loads(self.rfg("land", "--format", "json"))
        self.assertTrue(land["ok"], land)
        bak = (land["data"] or {}).get("state_backup") or {}
        self.assertTrue(bak.get("dir"), land)
        (Path(self.td) / ".rfg" / "roadmap.yaml").unlink()
        (Path(self.td) / ".rfg" / "state.json").unlink()
        sys.path.insert(0, str(ROOT))
        try:
            from rfg.gitops import restore_roadmap_state
            from rfg.store import Store
            restored = restore_roadmap_state(self.td, bak["dir"])
            self.assertIn("roadmap.yaml", restored.get("files") or [], restored)
            self.assertIn("state.json", restored.get("files") or [], restored)
            rm = Store(self.td).load_roadmap()
            self.assertTrue(any(s.id == "B01" for s in rm.steps), [s.id for s in rm.steps])
        finally:
            sys.path.remove(str(ROOT))


if __name__ == "__main__":
    unittest.main()
