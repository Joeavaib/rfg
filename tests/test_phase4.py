import hashlib
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
POLY = ROOT / "testdata" / "polyglot"
PYFIX = ROOT / "testdata" / "pyfix"


class Phase4Test(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg4-")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(ROOT)
        self.env.update(
            {
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t.test",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t.test",
            }
        )

    def copy(self, src: Path):
        for p in src.iterdir():
            if p.is_file():
                shutil.copy(p, Path(self.td) / p.name)

    def git(self):
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

    def test_migrate_v0_to_v1(self):
        self.copy(GO)
        rfgdir = Path(self.td) / ".rfg"
        rfgdir.mkdir()
        (rfgdir / "roadmap.yaml").write_text(
            "version: 0\nid: old\nhypothesis:\n  id: h1\n  statement: s\nsteps:\n"
        )
        (rfgdir / "state.json").write_text('{"applied":[],"verified":[],"failed":[]}\n')
        out = json.loads(self.rfg("migrate", "--format", "json"))
        self.assertTrue(out["data"]["changed"])
        self.assertEqual(out["data"]["to"], 3)
        again = json.loads(self.rfg("migrate", "--format", "json"))
        self.assertFalse(again["data"]["changed"])

    def test_apply_rollback_identity(self):
        self.copy(GO)
        self.git()
        original = (Path(self.td) / "user.go").read_bytes()
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
            "--verify",
            "test -n ok",
        )
        self.rfg("apply", "--format", "json")
        wt = Path(self.td) / ".rfg" / "worktree" / "user.go"
        self.assertNotEqual(wt.read_bytes(), original)
        self.rfg("rollback", "last", "--format", "json")
        self.assertEqual(wt.read_bytes(), original)

    def test_doctor_completion_man_version(self):
        self.copy(POLY)
        self.git()
        doc = json.loads(self.rfg("doctor", "--format", "json"))
        self.assertTrue(doc["data"]["ok"])
        self.assertEqual(doc["data"]["checks"]["telemetry"]["detail"], "off")
        self.assertEqual(doc["data"]["checks"]["network"]["detail"], "unused")
        self.assertIn("none", doc["data"]["checks"]["vendored_grammars"]["detail"])
        bash = self.rfg("completion", "bash")
        self.assertIn("doctor", bash)
        self.assertIn("migrate", bash)
        man = self.rfg("man")
        self.assertIn("RFG", man)
        ver = json.loads(self.rfg("version", "--format", "json"))
        self.assertEqual(ver["data"]["version"], "1.0.0")

    def test_v1_polyglot_five_steps_verify_fail_rollback(self):
        self.copy(POLY)
        self.git()
        self.rfg("doctor", "--format", "json")
        self.rfg("index", "--format", "json")
        self.rfg("init")
        self.rfg("plan", "--hypothesis", "polyglot UserID", "--symbol", "UserID")
        for i, (sid, path, from_pat) in enumerate(
            [
                ("s1", "core.go", "UserID"),
                ("s2", "app.ts", "UserID"),
                ("s3", "core.go", "package core"),
                ("s4", "app.ts", "export"),
                ("s5", "core.go", 'return "u"'),
            ],
            1,
        ):
            deps = [] if i == 1 else [f"s{i-1}"]
            args = [
                "plan",
                "--step",
                sid,
                "--title",
                sid,
                "--from",
                from_pat,
                "--to",
                {"s1": "UID", "s5": 'return "x"'}.get(sid, from_pat),
                "--path",
                path,
                "--verify",
                "test -n ok" if sid != "s5" else "false",
            ]
            if deps:
                args.extend(["--depends", deps[0]])
            self.rfg(*args)
        self.rfg("apply", "--format", "json")
        self.rfg("verify", "--format", "json")
        # skip to last: apply remaining with verify true until s5
        self.rfg("apply", "--format", "json")
        self.rfg("verify", "--format", "json")
        self.rfg("apply", "--format", "json")
        self.rfg("verify", "--format", "json")
        self.rfg("apply", "--format", "json")
        self.rfg("verify", "--format", "json")
        self.rfg("apply", "--format", "json")
        r = subprocess.run(
            RFG + ["--root", self.td, "verify", "--format", "json"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        before = (Path(self.td) / ".rfg" / "worktree" / "core.go").read_bytes()
        self.rfg("rollback", "last", "--format", "json")
        after = (Path(self.td) / ".rfg" / "worktree" / "core.go").read_bytes()
        # s5 replaced "func " — rollback restores pre-s5
        self.assertNotEqual(before, after)

    def test_golden_language_fixtures(self):
        def files_for(src, query, extra_copy=None):
            td = Path(self.td)
            for p in td.iterdir():
                if p.name != ".":
                    pass
            for p in src.iterdir():
                if p.is_file():
                    shutil.copy(p, td / p.name)
            out = json.loads(self.rfg("impact", "--symbol", query, "--files", "--format", "json"))
            names = sorted(f["path"] for f in out["data"]["files"])
            self.assertGreater(out["data"]["hits"], 0)
            return names

        go_files = files_for(GO, "UserID")
        expected = json.loads((ROOT / "testdata" / "golden" / "go-impact.json").read_text())
        self.assertEqual(go_files, expected["files"])

    def test_golden_python_fixture(self):
        self.copy(PYFIX)
        out = json.loads(self.rfg("impact", "--symbol", "UserID", "--files", "--format", "json"))
        names = sorted(f["path"] for f in out["data"]["files"])
        expected = json.loads((ROOT / "testdata" / "golden" / "py-impact.json").read_text())
        self.assertEqual(names, expected["files"])
        self.assertGreater(out["data"]["hits"], 0)

    def test_telemetry_opt_in_local_only(self):
        self.copy(GO)
        self.rfg("init")
        self.assertFalse((Path(self.td) / ".rfg" / "telemetry.log").is_file())
        env = self.env.copy()
        env["RFG_TELEMETRY"] = "1"
        subprocess.run(
            RFG + ["--root", self.td, "init", "--format", "json"],
            cwd=self.td,
            env=env,
            capture_output=True,
            text=True,
        )
        # second init conflicts; force a command that records: version doesn't. Use index.
        subprocess.run(
            RFG + ["--root", self.td, "status", "--format", "json"],
            cwd=self.td,
            env=env,
            capture_output=True,
        )
        # record is on init only currently; call doctor? add record on doctor via running init on fresh
        td2 = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td2, ignore_errors=True)
        env["RFG_TELEMETRY"] = "1"
        subprocess.run(
            RFG + ["--root", td2, "init", "--format", "json"],
            cwd=td2,
            env=env,
            capture_output=True,
        )
        log = Path(td2) / ".rfg" / "telemetry.log"
        self.assertTrue(log.is_file(), "opt-in should write local log")
        self.assertNotIn("http", log.read_text().lower())

    def test_remote_scip_rejected(self):
        r = subprocess.run(
            RFG + ["--root", self.td, "import-scip", "https://example.com/index.scip"],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 4)

    def test_license_check_script(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "license-check.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no vendored grammars", r.stdout)

    def test_integration_doc_exists(self):
        text = (ROOT / "docs" / "INTEGRATION.md").read_text()
        self.assertIn("just", text)
        self.assertIn("make", text)
        self.assertIn("status --format json", text)

    def test_grok_build_skill_and_mcp_config(self):
        skill = (ROOT / ".grok" / "skills" / "rfg" / "SKILL.md").read_text()
        self.assertIn("name: rfg", skill)
        self.assertIn("apply --dry-run", skill)
        cfg = (ROOT / ".grok" / "config.toml").read_text()
        self.assertIn("[mcp_servers.rfg]", cfg)
        self.assertIn("-m", cfg)
        self.assertIn("rfg", cfg)


if __name__ == "__main__":
    unittest.main()
