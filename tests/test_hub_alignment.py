"""Hub-alignment tests (R2, test-first).

HubAlignmentTest pins: 6 echte Hubs (gecappt bei 10 Nachbarn),
Blätter mit ≤3 Nachbarn, je Hub 1 Alignment-Nachbar, und die
Hub-Regel im Skill (RED bis R2-impl sie hinschreibt).
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HUBS = [
    "H04-cross-verify",
    "H05-land-gate",
    "V1.1-struct-findings",
    "H03-verify-dedup",
    "M5-plan-merged",
    "R04-plan-fields",
]
LEAVES = [
    "V0.1t-wt-tests",
    "V0.2t-mcp-tests",
    "V0.3t-docs-tests",
    "V2t-sham-tests",
]


def _load():
    from rfg.store import Store

    rm = Store(str(ROOT)).load_roadmap()
    return rm


class HubAlignmentTest(unittest.TestCase):
    def test_hubs_overflow(self):
        from rfg.verify import related_step_ids
        from rfg.dag import step_by_id

        rm = _load()
        for hid in HUBS:
            step = step_by_id(rm, hid)
            self.assertIsNotNone(step, hid)
            related = related_step_ids(rm.steps, step)
            self.assertEqual(len(related), 10, f"{hid} should overflow the cap")

    def test_leaves_stay_small(self):
        from rfg.verify import related_step_ids
        from rfg.dag import step_by_id

        rm = _load()
        for lid in LEAVES:
            step = step_by_id(rm, lid)
            self.assertIsNotNone(step, lid)
            self.assertLessEqual(len(related_step_ids(rm.steps, step)), 3, lid)

    def test_each_hub_has_alignment_neighbor(self):
        from rfg.verify import related_step_ids
        from rfg.dag import step_by_id

        rm = _load()
        ids = {s.id for s in rm.steps}
        for hid in HUBS:
            related = related_step_ids(rm.steps, step_by_id(rm, hid))
            self.assertTrue(related, hid)
            self.assertTrue(all(r in ids for r in related), hid)

    def test_hub_rule_in_skill(self):
        skill = (ROOT / ".grok" / "skills" / "rfg" / "SKILL.md").read_text(encoding="utf-8")
        for marker in ("Hub", "Alignment", "Genug ="):
            self.assertIn(marker, skill, f"SKILL.md missing hub rule marker: {marker}")


if __name__ == "__main__":
    unittest.main()
