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
        # loop commands may have backed up (CR1), but the failed land itself
        # must not add a backup nor report one.
        baks = Path(self.td) / ".rfg" / "land-backups"
        before = sorted(p.name for p in baks.iterdir() if p.is_dir()) if baks.is_dir() else []
        land = json.loads(self.rfg("land", "--format", "json", code=5))
        self.assertFalse(land["ok"], land)
        self.assertNotIn("state_backup", land.get("data") or {}, land)
        after = sorted(p.name for p in baks.iterdir() if p.is_dir()) if baks.is_dir() else []
        self.assertEqual(before, after, land)

    def test_loop_writes_state_backup(self):
        # CR1: successful apply/verify back up without land (crash recovery).
        # ids are content-addressed (<ts>-<sha8>), so "latest" is not
        # name-ordered: any dir matching the live store proves the backup.
        self._loop("python3 -c \"assert 'new' in open('mod.py').read()\"")
        baks = Path(self.td) / ".rfg" / "land-backups"
        dirs = sorted(p for p in baks.iterdir() if p.is_dir())
        self.assertTrue(dirs, "apply/verify must leave a state backup")
        live = {n: (Path(self.td) / ".rfg" / n).read_bytes() for n in ("roadmap.yaml", "state.json")}
        self.assertTrue(
            any(all((d / n).is_file() and (d / n).read_bytes() == live[n] for n in live) for d in dirs),
            [d.name for d in dirs],
        )


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

    def test_backup_is_atomic_with_manifest(self):
        # QW-01: every backup dir is complete (manifest hashes match),
        # never torn; crash litter (*.tmp-*) is cleaned, never counted.
        self._loop("python3 -c \"assert 'new' in open('mod.py').read()\"")
        import hashlib

        baks = Path(self.td) / ".rfg" / "land-backups"
        (baks / "20200101T000000-deadbeef.tmp-crashlitter").mkdir(parents=True, exist_ok=True)
        land = json.loads(self.rfg("land", "--format", "json"))
        self.assertTrue(land["ok"], land)
        dirs = sorted(p for p in baks.iterdir() if p.is_dir())
        self.assertTrue(dirs)
        self.assertFalse([p.name for p in dirs if ".tmp-" in p.name],
                         "crash litter must be cleaned, never kept")
        for d in dirs:
            man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            for name in ("roadmap.yaml", "state.json"):
                digest = hashlib.sha256((d / name).read_bytes()).hexdigest()
                self.assertEqual((man.get("files") or {}).get(name), digest,
                                 f"{d.name}/{name}: torn backup without matching manifest")

    def test_corrupt_backup_restore_refuses(self):
        # QW-01: a torn backup must refuse (OSError), never half-restore.
        self._loop("python3 -c \"assert 'new' in open('mod.py').read()\"")
        land = json.loads(self.rfg("land", "--format", "json"))
        bak = (land["data"] or {}).get("state_backup") or {}
        bdir = Path(self.td) / ".rfg" / "land-backups" / bak["dir"]
        (bdir / "state.json").write_text("torn\n", encoding="utf-8")
        sys.path.insert(0, str(ROOT))
        try:
            from rfg.gitops import restore_roadmap_state
            with self.assertRaises(OSError):
                restore_roadmap_state(self.td, bak["dir"])
        finally:
            sys.path.remove(str(ROOT))

    def test_backup_idempotent_retry(self):
        # QW-01: same id twice with identical bytes is idempotent, no error.
        self._loop("python3 -c \"assert 'new' in open('mod.py').read()\"")
        sys.path.insert(0, str(ROOT))
        try:
            from rfg.gitops import backup_roadmap_state
            first = backup_roadmap_state(self.td, "manual-retry")
            second = backup_roadmap_state(self.td, "manual-retry")
            self.assertEqual(first["dir"], second["dir"])
            self.assertEqual(first["files"], second["files"])
            baks = Path(self.td) / ".rfg" / "land-backups"
            self.assertEqual(len([p for p in baks.iterdir()
                                  if p.is_dir() and p.name == "manual-retry"]), 1)
        finally:
            sys.path.remove(str(ROOT))

    def test_crash_between_apply_and_verify_recovers(self):
        # QW-03: crash after apply (store lost, worktree kept) recovers
        # from the apply-time backup; step is back in applied (not
        # verified), and verify passes afterwards. FAIL: crash window
        # loses the store without rescue.
        Path(self.td, "mod.py").write_text("old\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        self.rfg(
            "plan", "--step", "C01", "--engine", "implement", "--path", "mod.py",
            "--verify", "python3 -c \"assert 'new' in open('mod.py').read()\"",
        )
        Path(self.td, "mod.py").write_text("new\n")
        tick = json.loads(self.rfg("tick", "--format", "json"))
        self.assertEqual(tick["data"]["action"], "stop")
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)
        baks = Path(self.td) / ".rfg" / "land-backups"
        dirs = sorted(p for p in baks.iterdir() if p.is_dir())
        self.assertTrue(dirs, "apply must leave a backup (crash window rescue)")
        # crash: store gone (gitignored .rfg loss), worktree kept.
        (Path(self.td) / ".rfg" / "roadmap.yaml").unlink()
        (Path(self.td) / ".rfg" / "state.json").unlink()
        sys.path.insert(0, str(ROOT))
        try:
            from rfg.gitops import restore_roadmap_state
            from rfg.store import Store
            # name order is only second-granular (same ts sorts by hash):
            # choose by content — the backup holding the apply.
            holding = []
            for d in dirs:
                try:
                    snap = json.loads((d / "state.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if "C01" in (snap.get("applied") or []):
                    holding.append(d)
            self.assertTrue(holding, "no backup holds the apply")
            restored = restore_roadmap_state(self.td, sorted(holding)[-1].name)
            self.assertIn("roadmap.yaml", restored.get("files") or [], restored)
            st = Store(self.td).load_state()
            self.assertIn("C01", st.applied, "crash must not lose the apply")
            self.assertNotIn("C01", st.verified, "crash happened before verify")
        finally:
            sys.path.remove(str(ROOT))
        ver = json.loads(self.rfg("verify", "--format", "json"))
        self.assertTrue(ver["ok"], ver)


if __name__ == "__main__":
    unittest.main()
