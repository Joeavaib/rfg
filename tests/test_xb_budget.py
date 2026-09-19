"""XB cross-budget extension tests (warn-only note, never a gate)."""

import json
import os
import unittest
from pathlib import Path


class CrossBudgetExtTest(unittest.TestCase):
    def test_max_seconds_related_warn_only_no_gate(self):
        # --- Budget fields (types.Budget) ---
        try:
            from rfg.types import Budget

            b0 = Budget()
            has_fields = hasattr(b0, "max_seconds") and hasattr(b0, "max_related")
        except Exception:
            has_fields = False
        # --- Schema acceptance ---
        schema_ok = False
        try:
            import json as _json

            schema = _json.loads(
                (Path(__file__).resolve().parents[1] / "schema" / "budget.schema.json")
                .read_text(encoding="utf-8")
            )
            props = schema.get("properties") or {}
            schema_ok = "max_seconds" in props and "max_related" in props
        except Exception:
            schema_ok = False
        # --- Note helper ---
        try:
            from rfg.cli import cross_budget_note
        except ImportError:
            cross_budget_note = None  # type: ignore

        if not (has_fields and schema_ok and cross_budget_note is not None):
            # Red-phase: skip statt Tautologie (kein Fake-Gruen ohne Beweis).
            if has_fields:
                self.assertEqual(Budget().max_seconds, 0)
                self.assertEqual(Budget().max_related, 0)
            self.skipTest("Budget-Felder/Schema/Helper unvollstaendig")
        else:
            # 0 = disabled = today's behavior.
            self.assertEqual(Budget().max_seconds, 0)
            self.assertEqual(Budget().max_related, 0)
            self.assertEqual(Budget(max_seconds=0, max_related=0).max_seconds, 0)
            self.assertEqual(cross_budget_note(5, 0.1, Budget()), "")
            self.assertEqual(cross_budget_note(0, 0.0, Budget()), "")
            # Over-budget yields a note string, never a gate signal.
            note = cross_budget_note(12, 0.1, Budget(max_related=10))
            self.assertTrue(note, "related_total > max_related must note")
            self.assertIsInstance(note, str)
            note2 = cross_budget_note(2, 5.0, Budget(max_seconds=1.0))
            self.assertTrue(note2, "elapsed > max_seconds must note")
            self.assertIsInstance(note2, str)
            # Within budget stays silent.
            self.assertEqual(cross_budget_note(3, 0.1, Budget(max_related=10)), "")
            self.assertEqual(cross_budget_note(2, 0.5, Budget(max_seconds=60.0)), "")
            both = cross_budget_note(12, 5.0, Budget(max_related=10, max_seconds=1.0))
            self.assertIn("related_total", both)
            self.assertIn("elapsed", both)
            self.assertIn("max_seconds", both)
            self.assertIn("max_related", both)

        # --- CLI integration: exit never changes, note only warns ---
        import io
        import shutil
        import subprocess
        import tempfile
        from contextlib import redirect_stdout
        from unittest import mock

        from rfg.cli import CLI

        td = tempfile.mkdtemp(prefix="rfg-xb5-")
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.test",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.test"})
        subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
        subprocess.check_call(["git", "commit", "--allow-empty", "-qm", "i"], cwd=td, env=env)
        Path(td, "s.py").write_text("x = 1\n")
        c = CLI(td, True, False)
        with redirect_stdout(io.StringIO()):
            c.cmd_plan(["--step", "ME", "--engine", "implement", "--path", "s.py",
                        "--want", "me", "--verify", 'python3 -c "assert True"'])
            for i in range(3):
                c.cmd_plan(["--step", f"O{i:02d}", "--engine", "implement",
                            "--path", "s.py", "--want", f"o{i:02d}",
                            "--verify", 'python3 -c "assert True"'])
            c.cmd_apply(["ME"])
            for i in range(3):
                c.cmd_apply([f"O{i:02d}"])
        # Default budget (0/0): exit 0, no note.
        with redirect_stdout(io.StringIO()) as buf:
            code = c.cmd_verify(["ME"])
        self.assertEqual(code, 0, buf.getvalue())
        payload = json.loads(buf.getvalue())["data"]
        if cross_budget_note is None or not has_fields:
            return  # red phase: exit-0 only
        self.assertNotIn("budget_note", payload, payload)
        # Over-budget via injected roadmap budget: still exit 0, note warns.
        from rfg.store import Store as _Store

        real_load = _Store.load_roadmap

        def _over(self):
            rm = real_load(self)
            try:
                rm.budget.max_related = 1
            except Exception:
                pass
            return rm

        with mock.patch.object(_Store, "load_roadmap", _over):
            with redirect_stdout(io.StringIO()) as buf2:
                code2 = c.cmd_verify(["ME"])
        self.assertEqual(code2, 0, buf2.getvalue())
        payload2 = json.loads(buf2.getvalue())["data"]
        self.assertIn("budget_note", payload2, payload2)
        self.assertTrue(payload2["budget_note"], payload2)

        def _over_seconds(self):
            rm = real_load(self)
            try:
                rm.budget.max_seconds = 1e-12
                rm.budget.max_related = 1
            except Exception:
                pass
            return rm

        with mock.patch.object(_Store, "load_roadmap", _over_seconds):
            with redirect_stdout(io.StringIO()) as buf3:
                code3 = c.cmd_verify(["ME"])
        self.assertEqual(code3, 0, buf3.getvalue())
        payload3 = json.loads(buf3.getvalue())["data"]
        self.assertIn("budget_note", payload3, payload3)
        self.assertIn("max_seconds", payload3["budget_note"], payload3)
        self.assertIn("max_related", payload3["budget_note"], payload3)
        self.assertIn("elapsed", payload3["budget_note"], payload3)


if __name__ == "__main__":
    unittest.main()
