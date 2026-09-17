"""Skill-focus tests (R3, test-first).

SkillFocusTest pins: the 10-line ROI checklist lives in
docs/test-focus.md (full text, no gate promise) and the Skill
points at it with one line (slim-skill budget: SKILL.md <1800B).
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECKLIST_MARKERS = [
    "Verify <30s",
    "Crash auf Fehl-Input",
    "Boundary empty/1/n",
    "Shell-Quoting",
    "Stale-State",
    "Kein Mock-Framework",
    "Kein E2E pro Step",
    "Flaky-Verbot",
    "Pesticide-Regel",
    "Stopp-Regel",
]


class SkillFocusTest(unittest.TestCase):
    def test_checklist_complete(self):
        focus = (ROOT / "docs" / "test-focus.md").read_text(encoding="utf-8")
        for marker in CHECKLIST_MARKERS:
            self.assertIn(marker, focus, f"test-focus.md missing: {marker}")

    def test_no_gate_no_score_promise(self):
        focus = (ROOT / "docs" / "test-focus.md").read_text(encoding="utf-8")
        self.assertIn("kein Gate", focus)
        self.assertNotIn("score", focus.lower())

    def test_pointer_in_skill(self):
        skill = ROOT / ".grok" / "skills" / "rfg" / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        self.assertIn("test-focus", text)

    def test_skill_stays_slim(self):
        skill = (ROOT / ".grok" / "skills" / "rfg" / "SKILL.md")
        self.assertLess(len(skill.read_bytes()), 1800)


if __name__ == "__main__":
    unittest.main()
