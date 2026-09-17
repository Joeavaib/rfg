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


class H4Test(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-h4-")
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
        for p in GO.iterdir():
            if p.is_file():
                shutil.copy(p, Path(self.td) / p.name)
        subprocess.check_call(["git", "init"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)

    def rfg(self, *args, code=0):
        r = subprocess.run(
            RFG + ["--root", self.td, *args],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def test_perf_max_ms_gate(self):
        self.rfg("init")
        self.rfg("plan", "--profile", "perf", "--oracle-cmd", 'python3 -c "print(5)"', "--max-ms", "100")
        self.rfg(
            "plan",
            "--step",
            "p1",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--oracle",
            "perf",
        )
        self.rfg("apply")
        self.rfg("verify", "--format", "json")
        self.rfg("plan", "--oracle-cmd", 'python3 -c "print(9999)"', "--max-ms", "10")
        r = subprocess.run(
            RFG + ["--root", self.td, "verify", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_baseline_then_regression(self):
        self.rfg("init")
        self.rfg("plan", "--profile", "perf", "--oracle-cmd", 'python3 -c "print(10)"', "--max-ratio", "1.2")
        self.rfg(
            "plan",
            "--step",
            "p1",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--oracle",
            "perf",
        )
        self.rfg("apply")
        base = json.loads(self.rfg("baseline", "--format", "json"))
        self.assertEqual(base["data"]["metric"], 10)
        self.assertTrue((Path(self.td) / ".rfg" / "baseline.json").is_file())
        self.rfg("verify", "--format", "json")
        self.rfg("plan", "--oracle-cmd", 'python3 -c "print(50)"')
        r = subprocess.run(
            RFG + ["--root", self.td, "verify", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_debug_repro(self):
        self.rfg("init")
        self.rfg("plan", "--profile", "debug", "--oracle-cmd", "python3 -c \"raise SystemExit(1)\"")
        r = subprocess.run(
            RFG + ["--root", self.td, "repro", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertTrue((Path(self.td) / ".rfg" / "repro.log").is_file())
        self.rfg("plan", "--oracle-cmd", "python3 -c \"raise SystemExit(0)\"")
        self.rfg("repro", "--format", "json")

    def test_security_still_stub(self):
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "s1",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--oracle",
            "security",
        )
        self.rfg("apply")
        r = subprocess.run(
            RFG + ["--root", self.td, "verify", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
