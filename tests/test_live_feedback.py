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


class LiveFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-live-")
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
        subprocess.check_call(["git", "commit", "-m", "i", "--allow-empty"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)

    def rfg(self, *args, code=0):
        r = subprocess.run(RFG + ["--root", self.td, *args], cwd=self.td, env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def test_plan_compact_definition(self):
        # B1/B3: plan without --step returns want/path/verify, --list lists all
        self.rfg("init")
        Path(self.td, "a.py").write_text("x=1\n")
        self.rfg("plan", "--step", "S1", "--engine", "implement", "--path", "a.py",
                 "--want", "ship s1", "--verify", "echo ok")
        self.rfg("plan", "--step", "S2", "--engine", "implement", "--path", "a.py",
                 "--want", "ship s2", "--verify", "echo ok", "--depends", "S1")
        bare = json.loads(self.rfg("plan", "--format", "json"))["data"]
        self.assertEqual(bare["step"], "S1")
        self.assertEqual(bare["want"], "ship s1")
        self.assertEqual(bare["path"], ["a.py"])
        self.assertEqual(bare["verify"], "echo ok")
        listed = json.loads(self.rfg("plan", "--list", "--format", "json"))["data"]
        self.assertTrue(listed.get("list"))
        self.assertEqual(len(listed["steps"]), 2)

    def test_plan_rejects_bash_engine_fast(self):
        # C4: unknown engine fails at plan, not only at tick
        self.rfg("init")
        out = self.rfg("plan", "--step", "B1", "--engine", "bash", "--want", "w",
                       "--path", "a.py", "--format", "json", code=4)
        self.assertIn("unsupported engine", out)
        self.assertIn("run", out)

    def test_verify_hint_mentions_apply(self):
        # D5: verify before apply tells the next command
        self.rfg("init")
        Path(self.td, "a.py").write_text("x=1\n")
        self.rfg("plan", "--step", "M1", "--engine", "manual", "--path", "a.py",
                 "--want", "w", "--verify", "echo ok")
        out = self.rfg("verify", "M1", "--format", "json", code=1)
        self.assertIn("rfg apply M1", out)

    def test_doctor_parses_export_wrapped_verify(self):
        # E6: export ... && mvn/go binaries are still detected
        from rfg.doctor import verify_bins, unknown_engine_warnings
        from rfg.types import Step

        self.assertIn("mvn", verify_bins("export JAVA_HOME=/x PATH=/y:$PATH && mvn -B verify"))
        self.assertIn("go", verify_bins("export PATH=/g:$PATH && go test ./..."))
        self.assertTrue(unknown_engine_warnings([Step(id="s", title="t", engine="bash")]))
        Path(self.td, "pom.xml").write_text("<project/>")
        Path(self.td, "Main.java").write_text("class A{}")
        self.rfg("init")
        self.rfg("plan", "--step", "J1", "--engine", "implement", "--path", "Main.java",
                 "--want", "w", "--verify", "export PATH=/tmp/x:$PATH && mvn verify")
        doc = json.loads(self.rfg("doctor", "--format", "json"))["data"]
        tc = json.dumps(doc["checks"]["toolchain"])
        self.assertIn("mvn", tc)

    def test_verify_env_file(self):
        # F7: .rfg/env provides toolchain env without wrapper scripts
        from rfg.verify import load_env, run

        Path(self.td, ".rfg").mkdir(parents=True, exist_ok=True)
        Path(self.td, ".rfg", "env").write_text("RFG_LIVE_TEST=hello42\n")
        self.assertEqual(load_env(self.td).get("RFG_LIVE_TEST"), "hello42")
        code, out = run(self.td, "echo $RFG_LIVE_TEST", env_extra=load_env(self.td))
        self.assertEqual(code, 0)
        self.assertIn("hello42", out)

    def test_extras_allowlist(self):
        # B2: extras staged without polluting path[]
        from rfg.types import step_allowed_paths, Step

        s = Step(id="s", title="t", paths=["a.py"], extras=["rfgfeedback.md"])
        self.assertIn("rfgfeedback.md", step_allowed_paths(s))
        self.rfg("init")
        Path(self.td, "a.py").write_text("ok\n")
        Path(self.td, "rfgfeedback.md").write_text("notes\n")
        self.rfg("plan", "--step", "S", "--engine", "implement", "--path", "a.py",
                 "--extras", "rfgfeedback.md", "--want", "w", "--verify", "echo ok")
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)
        self.assertIn("rfgfeedback.md", json.dumps(applied["data"]))

    def test_context_dir_exists(self):
        from rfg.context import path_split

        Path(self.td, "services", "core").mkdir(parents=True)
        exists, missing = path_split(self.td, ["services/core"])
        self.assertIn("services/core", exists)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
