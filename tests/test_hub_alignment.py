"""Hub-alignment tests (R2, test-first).

HubAlignmentTest pins: hubs overflow the related cap, leaves stay
small (≤3), each hub has an alignment neighbor. Uses a tmp roadmap
so editing ROOT .rfg/roadmap.yaml cannot break the pin.
"""

import unittest
from pathlib import Path

from rfg.types import Roadmap, Step

ROOT = Path(__file__).resolve().parents[1]

HUB_ID = "H04-cross-verify"
LEAF_ID = "V0.1t-wt-tests"


def _synthetic() -> Roadmap:
    rm = Roadmap(id="hub-tmp")
    hub = Step(id=HUB_ID, title="hub", engine="implement")
    hub.paths = ["hub.py"]
    rm.steps.append(hub)
    for i in range(12):
        n = Step(id=f"N{i:02d}", title="n", engine="implement")
        n.paths = ["hub.py"]
        rm.steps.append(n)
    leaf = Step(id=LEAF_ID, title="leaf", engine="implement")
    leaf.paths = ["leaf.py"]
    rm.steps.append(leaf)
    for i in range(2):
        n = Step(id=f"L{i}", title="l", engine="implement")
        n.paths = ["leaf.py"]
        rm.steps.append(n)
    return rm


class HubAlignmentTest(unittest.TestCase):
    def test_hubs_overflow(self):
        from rfg.dag import step_by_id
        from rfg.verify import related_step_ids

        rm = _synthetic()
        step = step_by_id(rm, HUB_ID)
        related = related_step_ids(rm.steps, step)
        self.assertEqual(len(related), 10, f"{HUB_ID} should overflow the cap")

    def test_leaves_stay_small(self):
        from rfg.dag import step_by_id
        from rfg.verify import related_step_ids

        rm = _synthetic()
        step = step_by_id(rm, LEAF_ID)
        self.assertLessEqual(len(related_step_ids(rm.steps, step)), 3, LEAF_ID)

    def test_each_hub_has_alignment_neighbor(self):
        from rfg.dag import step_by_id
        from rfg.verify import related_step_ids

        rm = _synthetic()
        ids = {s.id for s in rm.steps}
        related = related_step_ids(rm.steps, step_by_id(rm, HUB_ID))
        self.assertTrue(related, HUB_ID)
        self.assertTrue(all(r in ids for r in related), HUB_ID)

    def test_hub_rule_in_skill(self):
        skill = (ROOT / ".grok" / "skills" / "rfg" / "SKILL.md").read_text(encoding="utf-8")
        for marker in ("Hub", "Alignment", "Genug ="):
            self.assertIn(marker, skill, f"SKILL.md missing hub rule marker: {marker}")

    def test_root_roadmap_edit_does_not_break_hub_pin(self):
        from rfg.store import Store
        from rfg.verify import related_step_ids
        from rfg.dag import step_by_id

        live = Store(str(ROOT)).load_roadmap()
        live.steps.append(Step(id="noise-extra", title="n", engine="implement"))
        live.steps[-1].paths = ["hub.py"]
        rm = _synthetic()
        self.assertEqual(len(related_step_ids(rm.steps, step_by_id(rm, HUB_ID))), 10)
        self.assertIsNone(step_by_id(rm, "noise-extra"))


if __name__ == "__main__":
    unittest.main()
