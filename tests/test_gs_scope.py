"""GS scope tests (Rot/Grün-Paare, warn-first, stdlib-only)."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GsEpicScopeTest(unittest.TestCase):
    def test_epic_of_derives_prefix(self):
        from rfg.scope import epic_of

        self.assertEqual(epic_of("GS1-epic-scope"), "GS")
        self.assertEqual(epic_of("GS1t-epic-scope-tests"), "GS")
        self.assertEqual(epic_of("KD-1"), "KD")
        self.assertEqual(epic_of("XB-01"), "XB")
        self.assertEqual(epic_of("CR5-recovery-docs"), "CR")
        self.assertEqual(epic_of(""), "")
        self.assertEqual(epic_of(None), "")

    def test_filter_by_epic_filters(self):
        from rfg.scope import epic_of, filter_by_epic

        steps = ["GS1-epic-scope", "GS2-epic-filter", "KD-1", "XB-01"]
        got = filter_by_epic(steps, "GS")
        self.assertEqual(sorted(got), ["GS1-epic-scope", "GS2-epic-filter"])
        for s in got:
            self.assertEqual(epic_of(s), "GS")
        # leerer Filter = alles
        self.assertEqual(sorted(filter_by_epic(steps, "")), sorted(steps))

    def test_unknown_epic_empty_plus_warning(self):
        from rfg.scope import filter_by_epic, unknown_epic_warning

        steps = ["GS1-epic-scope", "KD-1"]
        # darf nicht abbrechen, sondern leer + Warnung
        try:
            got = filter_by_epic(steps, "ZZ")
        except BaseException as e:  # noqa: BLE001
            self.fail(f"filter_by_epic raised {type(e).__name__} statt [] + Warnung")
        self.assertEqual(got, [])
        warn = unknown_epic_warning(steps, "ZZ")
        self.assertTrue(warn, "unbekanntes Epic muss Warntext liefern")
        self.assertIn("ZZ", warn)
        self.assertEqual(unknown_epic_warning(steps, "GS"), "")

    def test_list_epics(self):
        from rfg.scope import list_epics

        steps = ["GS2-epic-filter", "GS1-epic-scope", "KD-1", "XB-01", "KD-2"]
        self.assertEqual(list_epics(steps), ["GS", "KD", "XB"])
        self.assertEqual(list_epics([]), [])

    def test_no_hard_gate_no_schema_field(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "rfg" / "scope.py").read_text(encoding="utf-8")
        self.assertNotIn("sys.exit", src)
        self.assertNotIn("os._exit", src)
        self.assertNotIn("SCHEMA_VERSION", src)
        self.assertNotIn("schema_version", src)
        # kein Schema-Feld-Zwang: Helfer arbeiten auf reinen Strings
        self.assertIn("def epic_of", src)
        self.assertIn("def filter_by_epic", src)
        self.assertIn("def list_epics", src)


class GsEpicFilterTest(unittest.TestCase):
    """Rot: plan/next/progress mit --epic filtern nur Epic-Steps."""

    def setUp(self):
        import os
        import shutil
        import subprocess
        import sys
        import tempfile

        self.subprocess = subprocess
        self.td = tempfile.mkdtemp(prefix="rfg-gs-filter-")
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
        self.rfg("init")
        for sid, path in (("GS9-a", "gs9a.py"), ("KD9-b", "kd9b.py")):
            self.rfg(
                "plan", "--step", sid, "--engine", "implement",
                "--want", f"want {sid}", "--path", path,
                "--verify", f"test -f {path}",
            )

    def rfg(self, *args, code=0):
        import json
        import sys

        r = self.subprocess.run(
            [sys.executable, str(ROOT / "rfg.py"), "--root", self.td, *args],
            cwd=self.td, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout)["data"]

    def test_next_epic_filters_only_epic_steps(self):
        nxt = self.rfg("next", "--epic", "GS")
        self.assertEqual(nxt["id"], "GS9-a")
        self.assertEqual(nxt["ready"], ["GS9-a"])
        self.assertEqual(nxt["recommend"], "GS9-a")
        self.assertEqual(nxt.get("epic"), "GS")

    def test_recommend_stays_in_epic(self):
        from rfg import dag
        from rfg.store import Store

        st = Store(self.td)
        rm = st.load_roadmap()
        state = st.load_state()
        rec, _why = dag.recommend(rm, state, "KD")
        self.assertEqual(rec, "KD9-b")
        rec2, why2 = dag.recommend(rm, state, "GS")
        self.assertEqual(rec2, "GS9-a")
        self.assertNotEqual(rec2, "KD9-b")

    def test_plan_list_epic_filters(self):
        out = self.rfg("plan", "--list", "--epic", "KD")
        ids = [s["id"] for s in out["steps"]]
        self.assertEqual(ids, ["KD9-b"])

    def test_progress_epic_filters(self):
        out = self.rfg("progress", "--epic", "GS")
        self.assertEqual(out["ready"], ["GS9-a"])
        self.assertEqual(out.get("epic"), "GS")

    def test_unknown_epic_warns_not_gates(self):
        nxt = self.rfg("next", "--epic", "ZZ")
        self.assertEqual(nxt["ready"], [])
        self.assertTrue(nxt.get("warning"), "unbekanntes Epic muss warnen")
        self.assertIn("ZZ", nxt["warning"])
        prog = self.rfg("progress", "--epic", "ZZ")
        self.assertEqual(prog["ready"], [])
        self.assertTrue(prog.get("warning"))

    def test_mcp_surface_unchanged(self):
        from rfg.mcp import CORE_TOOLS, SCHEMAS

        self.assertEqual(len(CORE_TOOLS), 16, CORE_TOOLS)
        for tool in ("plan", "next", "progress"):
            props = (SCHEMAS.get(tool) or {}).get("properties") or {}
            self.assertNotIn("epic", props, f"MCP {tool} darf kein epic-Param haben")


class GsProgressGroupsTest(unittest.TestCase):
    """Rot: progress meldet by_epic total/verified/ready, doctor warnt nur."""

    def setUp(self):
        import os
        import shutil
        import subprocess
        import sys
        import tempfile

        self.subprocess = subprocess
        self.td = tempfile.mkdtemp(prefix="rfg-gs-progress-")
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
        self.rfg("init")
        for sid, path in (("GS9-a", "gs9a.py"), ("KD9-b", "kd9b.py")):
            self.rfg(
                "plan", "--step", sid, "--engine", "implement",
                "--want", f"want {sid}", "--path", path,
                "--verify", f"test -f {path}",
            )

    def rfg(self, *args, code=0):
        import json
        import sys

        r = self.subprocess.run(
            [sys.executable, str(ROOT / "rfg.py"), "--root", self.td, *args],
            cwd=self.td, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout)["data"]

    def test_progress_has_by_epic(self):
        out = self.rfg("progress")
        by_epic = out.get("by_epic")
        self.assertIsInstance(by_epic, dict)
        self.assertIn("GS", by_epic)
        self.assertIn("KD", by_epic)
        for epic, counts in by_epic.items():
            for key in ("total", "verified", "ready"):
                self.assertIn(key, counts, f"by_epic[{epic}] ohne {key}")

    def test_by_epic_counts_total_verified_ready(self):
        out = self.rfg("progress")
        self.assertEqual(out["by_epic"]["GS"]["total"], 1)
        self.assertEqual(out["by_epic"]["GS"]["ready"], 1)
        self.assertEqual(out["by_epic"]["GS"]["verified"], 0)
        # einen Step verifizieren -> verified zaehlt
        from pathlib import Path

        Path(self.td, "gs9a.py").write_text("x = 1\n", encoding="utf-8")
        self.rfg("tick", "GS9-a")
        self.rfg("apply", "GS9-a")
        self.rfg("verify", "GS9-a")
        out2 = self.rfg("progress")
        self.assertEqual(out2["by_epic"]["GS"]["verified"], 1)

    def test_doctor_warns_empty_epic_only_warning(self):
        from rfg import doctor
        from rfg.store import Store

        st = Store(self.td)
        rm = st.load_roadmap()
        self.assertEqual(doctor.epic_warnings(rm.steps, "GS"), [])
        warns = doctor.epic_warnings(rm.steps, "ZZ")
        self.assertTrue(warns, "leeres Epic muss warnen")
        self.assertIn("ZZ", warns[0])
        rep = doctor.run(self.td)
        self.assertTrue(rep["ok"])
        self.assertTrue(rep["checks"]["epics"]["ok"])

    def test_no_exit5_on_empty_epic(self):
        prog = self.rfg("progress", "--epic", "ZZ")
        self.assertEqual(prog["ready"], [])
        self.assertTrue(prog.get("warning"))
        doc = self.rfg("doctor")
        self.assertTrue(doc["ok"])


class GsScopeDocsTest(unittest.TestCase):
    """Rot: Doku beschreibt GS-Praefix plus --epic plus by_epic, Rezept rendert."""

    def test_doc_exists_and_has_rule(self):
        doc = (ROOT / "docs" / "scope-scaling.md").read_text(encoding="utf-8")
        for term in ("epic_of", "--epic", "by_epic", "warn-first", "epic-campaign"):
            self.assertIn(term, doc, f"Doku ohne {term}")
        self.assertIn("GS", doc)

    def test_recipe_exists_and_renders(self):
        from rfg import recipes

        rm = recipes.load("epic-campaign", str(ROOT))
        self.assertGreaterEqual(len(rm.steps), 2)
        ids = [s.id for s in rm.steps]
        self.assertEqual(len(set(ids)), len(ids), "Rezept-IDs muessen eindeutig sein")
        for s in rm.steps:
            self.assertTrue(s.verify, f"Step {s.id} ohne verify rendert nicht")

    def test_recipe_chain_linked_single_epic(self):
        from rfg import recipes
        from rfg.scope import epic_of

        rm = recipes.load("epic-campaign", str(ROOT))
        ids = [s.id for s in rm.steps]
        epics = {epic_of(i) for i in ids}
        self.assertEqual(len(epics), 1, f"Epic-Kette braucht einen Praefix: {epics}")
        seen = set()
        for s in rm.steps:
            for d in s.depends_on or []:
                self.assertIn(d, seen, f"{s.id} haengt an unbekanntem {d}")
            seen.add(s.id)

    def test_doc_mentions_recipe(self):
        doc = (ROOT / "docs" / "scope-scaling.md").read_text(encoding="utf-8")
        self.assertIn("epic-campaign.yaml", doc)


if __name__ == "__main__":
    unittest.main()
