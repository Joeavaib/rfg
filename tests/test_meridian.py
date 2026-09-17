"""Meridian-campaign feedback tests (M1..M7).

Each class maps to one roadmap step; verifies are per-class so plan
dedup hints stay quiet.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RFG = [sys.executable, str(ROOT / "rfg.py")]


def _env(td: str) -> dict:
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
        self.td = tempfile.mkdtemp(prefix="rfg-mer-")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.env = _env(self.td)
        subprocess.check_call(["git", "init"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)

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


class MeridianM1Test(_Repo):
    def test_tools_list_carries_server_version(self):
        from rfg import __version__
        from rfg import mcp

        resp = mcp.handle({"id": 1, "method": "tools/list", "params": {}}, str(ROOT))
        result = resp["result"]
        self.assertIn("tools", result)
        server = result.get("server") or {}
        self.assertEqual(server.get("name"), "rfg")
        self.assertEqual(server.get("version"), __version__)
        self.assertEqual(result.get("serverVersion"), __version__)

    def test_doctor_reports_server_version(self):
        self.rfg("init")
        out = json.loads(self.rfg("doctor", "--format", "json"))["data"]
        self.assertIn("server", out["checks"], out["checks"].keys())
        from rfg import __version__

        self.assertIn(__version__, out["checks"]["server"]["detail"])

    def test_plan_surfaces_toolchain_hints(self):
        self.rfg("init")
        out = json.loads(
            self.rfg(
                "plan", "--step", "s1", "--path", "app.py", "--verify", "mvn -q test", "--format", "json"
            )
        )["data"]
        text = json.dumps(out)
        self.assertIn("mvn", text)
        self.assertIn(".rfg/env", text)

    def test_verify_failure_carries_toolchain_hint(self):
        self.rfg("init")
        Path(self.td, "app.py").write_text("x = 1\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg(
            "plan", "--step", "s1", "--engine", "implement", "--path", "app.py",
            "--verify", "mvn -q -Dtest=Nope test",
        )
        self.rfg("tick", "s1")
        self.rfg("apply", "s1")
        r = subprocess.run(
            RFG + ["--root", self.td, "verify", "s1", "--format", "json"],
            cwd=self.td, env=self.env, capture_output=True, text=True,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(".rfg/env", r.stdout + r.stderr)


class MeridianM2Test(_Repo):
    def test_verify_127_suggests_rfg_env(self):
        self.rfg("init")
        Path(self.td, "app.py").write_text("x = 1\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg(
            "plan", "--step", "s1", "--engine", "implement", "--path", "app.py",
            "--verify", "rfg-missing-bin-xyz --version",
        )
        self.rfg("tick", "s1")
        self.rfg("apply", "s1")
        r = subprocess.run(
            RFG + ["--root", self.td, "verify", "s1", "--format", "json"],
            cwd=self.td, env=self.env, capture_output=True, text=True,
        )
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(".rfg/env", r.stdout + r.stderr)

    def test_doctor_resolves_bins_via_rfg_env_path(self):
        self.rfg("init")
        fake = Path(self.td) / "fakebin"
        fake.mkdir()
        (fake / "mvn").write_text("#!/bin/sh\nexit 0\n")
        (fake / "mvn").chmod(0o755)
        (Path(self.td) / ".rfg" / "env").write_text(f"PATH={fake}:$PATH\n")
        self.rfg("plan", "--step", "s1", "--path", "app.py", "--verify", "mvn -q test")
        out = json.loads(self.rfg("doctor", "--format", "json"))["data"]
        text = json.dumps(out["checks"].get("toolchain"))
        self.assertNotIn("mvn missing", text)

    def test_env_path_which_and_missing_binary(self):
        from rfg.verify import env_path_which, looks_like_missing_binary

        fake = Path(self.td) / "fakebin"
        fake.mkdir(exist_ok=True)
        (fake / "mytool123").write_text("#!/bin/sh\nexit 0\n")
        (fake / "mytool123").chmod(0o755)
        (Path(self.td) / ".rfg").mkdir(exist_ok=True)
        (Path(self.td) / ".rfg" / "env").write_text(f"PATH={fake}:$PATH\n")
        found = env_path_which(self.td, "mytool123")
        self.assertTrue(found and found.endswith("mytool123"), found)
        self.assertIsNone(env_path_which(self.td, "no-such-tool-xyz"))
        self.assertTrue(looks_like_missing_binary(127, "anything"))
        self.assertTrue(looks_like_missing_binary(1, "mytool123: command not found"))
        self.assertFalse(looks_like_missing_binary(1, "assertion failed"))

    def test_toolchain_notes_name_env(self):
        from rfg.doctor import toolchain_notes_for

        notes = toolchain_notes_for([("s1", "mvn -q test")], self.td)
        if any("mvn" in n for n in notes):
            self.assertTrue(any(".rfg/env" in n for n in notes), notes)

    def test_env_hint_names_binary_and_step(self):
        from rfg.verify import env_hint_for_failure

        msg = env_hint_for_failure(127, "x: command not found", "mvn -q test", "s9")
        self.assertIn("mvn", msg)
        self.assertIn("s9", msg)
        self.assertIn(".rfg/env", msg)
        self.assertEqual(env_hint_for_failure(1, "assertion failed", "pytest -q", "s9"), "")


class MeridianM3Test(_Repo):
    def test_apply_reports_format_for_implement(self):
        self.rfg("init")
        Path(self.td, "app.py").write_text("x=1\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg(
            "plan", "--step", "s1", "--engine", "implement", "--path", "app.py",
            "--verify", "python3 -c \"assert True\"",
        )
        self.rfg("tick", "s1")
        out = json.loads(self.rfg("apply", "s1", "--format", "json"))["data"]
        self.assertIn("format", out, out.keys())

    def test_missing_formatter_surfaced_as_note(self):
        from rfg import fmtutil

        with mock.patch.object(fmtutil.shutil, "which", return_value=None):
            reports = fmtutil.format_paths(self.td, ["app.py"])
        self.assertTrue(reports)
        self.assertFalse(reports[0]["ran"])
        self.assertIn("PATH", reports[0]["reason"])


class MeridianM4Test(_Repo):
    def test_accept_prose_splits_commands_from_prose(self):
        from rfg.accept import commands, prose

        rm = type("RM", (), {"goal": type("G", (), {"acceptance": [
            "python3 -m pytest tests/ -q",
            "Baseline with Pricing-Engine (TS)",
            "",
        ]})()})()
        self.assertEqual(commands(rm), ["python3 -m pytest tests/ -q"])
        self.assertEqual(prose(rm), ["Baseline with Pricing-Engine (TS)"])

    def test_progress_lists_acceptance_prose(self):
        self.rfg("init")
        self.rfg("plan", "--goal", "ship it", "--acceptance", "Baseline with Pricing-Engine (TS)")
        out = json.loads(self.rfg("progress", "--format", "json"))["data"]
        self.assertIn("acceptance_prose", out["goal"], out["goal"].keys())
        self.assertTrue(out["goal"]["acceptance_prose"])

    def test_land_lists_acceptance_prose(self):
        self.rfg("init")
        self.rfg("plan", "--goal", "ship it", "--acceptance", "Baseline with Pricing-Engine (TS)")
        Path(self.td, "app.py").write_text("x = 1\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg(
            "plan", "--step", "s1", "--engine", "implement", "--path", "app.py",
            "--verify", "python3 -c \"assert True\"",
        )
        self.rfg("tick", "s1")
        self.rfg("apply", "s1")
        self.rfg("verify", "s1")
        land = json.loads(self.rfg("land", "--format", "json"))["data"]
        self.assertIn("acceptance_prose", land, land.keys())


class MeridianM5Test(_Repo):
    def test_plan_verify_only_returns_merged_paths(self):
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--path", "a.py", "--path", "b.py", "--verify", "pytest -q")
        out = json.loads(self.rfg("plan", "--step", "s1", "--verify", "pytest tests/ -q", "--format", "json"))["data"]
        self.assertIn("a.py", out.get("path") or [])
        self.assertIn("b.py", out.get("path") or [])
        self.assertEqual(out.get("verify"), "pytest tests/ -q")


class MeridianM6Test(_Repo):
    def test_cross_verify_names_step_binary_and_log(self):
        self.rfg("init")
        Path(self.td, "a.py").write_text("x = 1\n")
        Path(self.td, "b.py").write_text("y = 1\n")
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("plan", "--step", "s1", "--engine", "implement", "--path", "a.py",
                 "--verify", "python3 -c \"assert True\"")
        self.rfg("plan", "--step", "s2", "--engine", "implement", "--path", "a.py",
                 "--verify", "python3 -c \"import sys; sys.exit(1)\"",
                 "--depends", "s1")
        for sid in ("s1", "s2"):
            self.rfg("tick", sid)
            self.rfg("apply", sid)
            if sid == "s1":
                self.rfg("verify", sid)
        r = subprocess.run(
            RFG + ["--root", self.td, "verify", "s2", "--format", "json"],
            cwd=self.td, env=self.env, capture_output=True, text=True,
        )
        # s2's own verify fails; message must carry remediation (log path)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(".log", r.stdout + r.stderr)

    def test_cross_verify_127_appends_env_hint(self):
        from rfg import cli as _cli

        msg = _cli.cross_verify_message(
            [("s2", "mvn -q test", 127, "mvn: command not found", "/tmp/x.log")]
        )
        self.assertIn("s2", msg)
        self.assertIn("mvn", msg)
        self.assertIn(".rfg/env", msg)
        self.assertIn("/tmp/x.log", msg)

    def test_related_step_ids_dependents_first(self):
        from rfg.types import Step
        from rfg.verify import related_step_ids

        me = Step(id="a", title="t")
        me.paths = ["x.py"]
        dep = Step(id="b", title="t")
        dep.depends_on = ["a"]
        dep.paths = ["y.py"]
        over = Step(id="c", title="t")
        over.paths = ["x.py"]
        self.assertEqual(related_step_ids([me, dep, over], me), ["b", "c"])


class MeridianM7Test(unittest.TestCase):
    def test_verify_scoped_elsewhere_warns(self):
        from rfg import doctor
        from rfg.types import Step

        s = Step(id="s1", title="t", engine="implement", verify="pytest services/core/test_checkout.py -q")
        s.paths = ["services/pricing"]
        warns = doctor.oracle_warnings([s])
        self.assertTrue(any("s1" in w and "pricing" in w for w in warns), warns)

    def test_src_tests_split_stays_quiet(self):
        from rfg import doctor
        from rfg.types import Step

        s = Step(id="s1", title="t", engine="implement", verify="pytest tests/test_ops.py")
        s.paths = ["src/ops.py"]
        warns = doctor.oracle_warnings([s])
        self.assertFalse(any("path[]" in w for w in warns), warns)

    def test_normalize_path_token(self):
        from rfg.doctor import normalize_path_token

        self.assertEqual(normalize_path_token("./tests/test_gaps.py"), "tests/test_gaps")
        self.assertEqual(
            normalize_path_token("tests.test_gaps.GapsTest.test_x"), "tests/test_gaps/GapsTest/test_x"
        )
        self.assertEqual(normalize_path_token("services/pricing"), "services/pricing")

    def test_glossary_defines_cross_cutting_term(self):
        p = ROOT / "docs" / "GLOSSARY.md"
        self.assertTrue(p.is_file(), "docs/GLOSSARY.md missing")
        text = p.read_text(encoding="utf-8")
        self.assertIn("cross-cutting validation rules", text)


if __name__ == "__main__":
    unittest.main()
