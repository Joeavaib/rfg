"""Validate structure tests (V1.1, test-first) + check tests (V1.2t).

ValidateStructureTest pins dag.structure_findings (RED until V1.1-impl);
ValidateCheckTest pins plan --check (RED until V1.2-impl).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rfg.types import Roadmap, Step

ROOT = Path(__file__).resolve().parents[1]
RFG = [sys.executable, str(ROOT / "rfg.py")]


def _rm(*steps: Step) -> Roadmap:
    return Roadmap(id="t", steps=list(steps))


def _step(sid: str, depends=()) -> Step:
    return Step(id=sid, title=sid, depends_on=list(depends))


class ValidateStructureTest(unittest.TestCase):
    def test_duplicate_ids(self):
        from rfg.dag import structure_findings

        found = structure_findings(_rm(_step("a"), _step("a")))
        kinds = {(f["kind"], f["step"]) for f in found}
        self.assertIn(("duplicate-id", "a"), kinds)

    def test_dangling_depends(self):
        from rfg.dag import structure_findings

        found = structure_findings(_rm(_step("a", ["ghost"])))
        kinds = {(f["kind"], f["step"]) for f in found}
        self.assertIn(("dangling-dep", "a"), kinds)
        self.assertTrue(any("ghost" in f["detail"] for f in found if f["step"] == "a"))

    def test_self_depend(self):
        from rfg.dag import structure_findings

        found = structure_findings(_rm(_step("a", ["a"])))
        kinds = {f["kind"] for f in found if f["step"] == "a"}
        self.assertTrue({"self-dep", "cycle"} & kinds, found)

    def test_cycle_names_path(self):
        from rfg.dag import structure_findings

        found = structure_findings(_rm(_step("a", ["b"]), _step("b", ["a"])))
        cycles = [f for f in found if f["kind"] == "cycle"]
        self.assertTrue(cycles, found)
        self.assertIn("a", cycles[0]["detail"])
        self.assertIn("b", cycles[0]["detail"])

    def test_clean_roadmap_no_findings(self):
        from rfg.dag import structure_findings

        found = structure_findings(_rm(_step("a"), _step("b", ["a"])))
        self.assertEqual(found, [])

    def test_doctor_reuses_findings(self):
        from rfg import doctor
        from rfg.dag import structure_findings

        steps = [_step("a", ["ghost"])]
        via_doctor = doctor.structure_warnings(steps)
        via_dag = structure_findings(_rm(*steps))
        self.assertEqual(via_doctor, via_dag)


class ValidateCheckTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-vcheck-")
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

    def test_check_clean_roadmap_ok(self):
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--path", "a.py", "--want", "w",
                 "--verify", "python3 -c \"assert True\"")
        out = json.loads(self.rfg("plan", "--check", "--format", "json"))["data"]
        self.assertTrue(out["ok"], out)
        self.assertEqual(out.get("findings"), [])

    def test_check_reports_dangling(self):
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--path", "a.py", "--want", "w",
                 "--verify", "python3 -c \"assert True\"", "--depends", "ghost")
        out = json.loads(self.rfg("plan", "--check", "--format", "json", code=5))["data"]
        self.assertFalse(out["ok"])
        text = json.dumps(out.get("findings"))
        self.assertIn("ghost", text)

    def test_check_readonly(self):
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--path", "a.py", "--want", "w",
                 "--verify", "python3 -c \"assert True\"")
        rp = Path(self.td) / ".rfg" / "roadmap.yaml"
        sp = Path(self.td) / ".rfg" / "state.json"
        m1, m2 = rp.stat().st_mtime_ns, sp.stat().st_mtime_ns
        self.rfg("plan", "--check")
        self.assertEqual(rp.stat().st_mtime_ns, m1)
        self.assertEqual(sp.stat().st_mtime_ns, m2)

    def test_check_duplicate_ids(self):
        from rfg.store import Store
        from rfg.types import Step as TStep

        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--path", "a.py", "--want", "w",
                 "--verify", "python3 -c \"assert True\"")
        st = Store(self.td)
        rm = st.load_roadmap()
        rm.steps.append(TStep(id="s1", title="dup"))
        st.save_roadmap(rm)
        out = json.loads(self.rfg("plan", "--check", "--format", "json", code=5))["data"]
        kinds = {(f["kind"], f["step"]) for f in out.get("findings") or []}
        self.assertIn(("duplicate-id", "s1"), kinds)

    def test_check_manual_missing_want(self):
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "M01",
            "--engine",
            "manual",
            "--path",
            "a.py",
            "--verify",
            "pytest tests/test_a.py -q",
        )
        out = json.loads(self.rfg("plan", "--check", "--format", "json", code=5))["data"]
        kinds = {(f["kind"], f["step"]) for f in out.get("findings") or []}
        self.assertIn(("missing-want", "M01"), kinds)

    def test_check_m01_m08_shared_testfile(self):
        self.rfg("init")
        for i in range(1, 9):
            self.rfg(
                "plan",
                "--step",
                f"M0{i}",
                "--engine",
                "manual",
                "--want",
                f"slice {i}",
                "--path",
                f"m{i}.py",
                "--verify",
                "pytest tests/test_all.py -q",
            )
        out = json.loads(self.rfg("plan", "--check", "--format", "json", code=5))["data"]
        shared = [f for f in out.get("findings") or [] if f["kind"] == "shared-test-file"]
        self.assertTrue(shared, out)
        detail = shared[0]["detail"]
        self.assertIn("test_all.py", detail)
        self.assertIn("M01", detail)
        self.assertIn("M08", detail)

    def test_mcp_plan_check_flag(self):
        from rfg import mcp

        self.assertIn("check", mcp.SCHEMAS["plan"]["properties"])
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--path", "a.py", "--want", "w",
                 "--verify", "python3 -c \"assert True\"")
        rp = Path(self.td) / ".rfg" / "roadmap.yaml"
        m1 = rp.stat().st_mtime_ns
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code, _ = mcp.call_tool("plan", {"check": True}, self.td)
        self.assertEqual(code, 0, buf.getvalue())
        self.assertEqual(rp.stat().st_mtime_ns, m1)


if __name__ == "__main__":
    unittest.main()
