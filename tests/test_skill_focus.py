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

    def test_plugin_and_grok_share_loop_markers(self):
        # CF-04: two budgets, shared loop markers, plugin points at canonical.
        # FAIL: plugin lacks MCP/RFG_ROOT/land/pointer, or plugin >=800, or
        # grok loses test-focus / Hub-Alignment or grows >=1800.
        grok = (ROOT / ".grok" / "skills" / "rfg" / "SKILL.md").read_text(encoding="utf-8")
        plugin = (ROOT / "plugin" / "rfg" / "skills" / "rfg" / "SKILL.md").read_text(encoding="utf-8")
        for text in (grok, plugin):
            self.assertIn("MCP", text)
            self.assertIn("RFG_ROOT", text)
            self.assertIn("land", text)
        self.assertIn("test-focus", grok)
        self.assertIn("Hub", grok)
        self.assertIn("Alignment", grok)
        self.assertIn("Genug =", grok)
        self.assertTrue(
            "test-focus" in plugin or "docs/agent.md" in plugin,
            plugin,
        )
        self.assertIn(".grok/skills/rfg/SKILL.md", plugin)
        self.assertLess(len(plugin.encode()), 800)
        self.assertLess(len(grok.encode()), 1800)


if __name__ == "__main__":
    unittest.main()
