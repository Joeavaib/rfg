"""Ledger tests (R4, test-first).

LedgerEventsTest pins: append-only events, counters derived
exclusively from verify events (agent-supplied counters ignored),
function->tests map view, stale trigger on new overlapping test.
Tombstone/drop is parked (SCOUT-D I3).
"""

import json
import unittest
from pathlib import Path


class LedgerEventsTest(unittest.TestCase):
    def test_append_only_and_derived_counters(self):
        import tempfile
        from rfg import ledger

        with tempfile.TemporaryDirectory(prefix="rfg-ledger-") as td:
            root = Path(td)
            ledger.record_test_added(root, "clip_output", "t.py::T::test_tail", "V19", "pytest t.py -k tail -q")
            ledger.record_verify_event(root, "t.py::T::test_tail", "V19", 0, ".rfg/verify/V19.log")
            ledger.record_verify_event(root, "t.py::T::test_tail", "V20", 1, ".rfg/verify/V20.log")
            # agent-supplied counters must not leak into derived counters
            ledger.record_verify_event(root, "t.py::T::test_tail", "V21", 0, "x.log", passes=999)
            counts = ledger.counters(root)
            self.assertEqual(counts["t.py::T::test_tail"]["passes"], 2)
            self.assertEqual(counts["t.py::T::test_tail"]["fails"], 1)
            lines = (root / ".rfg" / "ledger-events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 4)
            for line in lines:
                row = json.loads(line)
                self.assertNotIn("passes", row)
                self.assertNotIn("fails", row)

    def test_map_view_groups_by_function(self):
        import tempfile
        from rfg import ledger

        with tempfile.TemporaryDirectory(prefix="rfg-ledger-") as td:
            root = Path(td)
            ledger.record_test_added(root, "clip_output", "t.py::T::test_tail", "V19", "pytest t.py -q")
            ledger.record_test_added(root, "clip_output", "t.py::T::test_head", "V20", "pytest t.py -q")
            ledger.record_test_added(root, "run", "t.py::T::test_run", "V21", "pytest t.py -q")
            view = ledger.map_view(root)
            self.assertEqual(sorted(view["clip_output"]), ["t.py::T::test_head", "t.py::T::test_tail"])
            self.assertEqual(view["run"], ["t.py::T::test_run"])

    def test_stale_on_new_overlapping_test(self):
        import tempfile
        from rfg import ledger

        with tempfile.TemporaryDirectory(prefix="rfg-ledger-") as td:
            root = Path(td)
            self.assertFalse(ledger.new_test_overlaps(root, "clip_output", "t.py::T::test_tail"))
            ledger.record_test_added(root, "clip_output", "t.py::T::test_tail", "V19", "pytest t.py -q")
            self.assertFalse(ledger.new_test_overlaps(root, "clip_output", "t.py::T::test_tail"))
            self.assertTrue(ledger.new_test_overlaps(root, "clip_output", "t.py::T::test_head"))
            ledger.record_test_added(root, "clip_output", "t.py::T::test_head", "V20", "pytest t.py -q")
            self.assertIn("clip_output", ledger.stale_functions(root))


if __name__ == "__main__":
    unittest.main()
