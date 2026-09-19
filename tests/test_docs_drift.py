"""Doc-drift tests (V0.3, test-first).

DocsDriftTest pins the missing core verbs + boundary terms (RED until
V0.3-impl); DocsDriftHelpTest locks the already-correct HELP/Skill
coverage (characterization).
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_VERBS = ["context", "tick", "land", "claim", "release", "progress"]


class DocsDriftTest(unittest.TestCase):
    def test_core_verbs_in_manpage(self):
        man = (ROOT / "docs" / "rfg.1").read_text(encoding="utf-8")
        for verb in CORE_VERBS:
            self.assertIn(verb, man, f"rfg.1 missing core verb: {verb}")

    def test_manpage_exit_codes(self):
        man = (ROOT / "docs" / "rfg.1").read_text(encoding="utf-8")
        for code in ("0", "2", "3", "4", "5"):
            self.assertIn(code, man, f"rfg.1 missing exit code: {code}")

    def test_readme_uses_boundary_terms(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for term in ("Land-Gate", "Cross-Verify"):
            self.assertIn(term, readme, f"README missing boundary term: {term}")

    def test_plan_md_first_screen_is_historical(self):
        # CF-03: cold agents must not read plan.md as current v1.
        # FAIL: first screen still promises tree-sitter / live LSP / SCIP rename.
        head = "\n".join((ROOT / "plan.md").read_text(encoding="utf-8").splitlines()[:40])
        low = head.lower()
        self.assertIn("readme.md", low)
        self.assertTrue("historical" in low or "not current" in low or "nicht aktuell" in low, head)
        self.assertNotIn("ziel v1: ein nützliches", low)

    def test_capabilities_yaml_is_honest(self):
        # FAIL: rename: compile_commands.json or live index_semantic tool names.
        text = (ROOT / "schema" / "capabilities.yaml").read_text(encoding="utf-8")
        self.assertNotIn("rename: compile_commands.json", text)
        self.assertNotIn("index_semantic: rust-analyzer", text)
        self.assertNotIn("index_semantic: clangd", text)
        self.assertIn("index_semantic: false", text)
        self.assertIn("rename: false", text)


class DocsDriftHelpTest(unittest.TestCase):
    def test_help_covers_core_verbs(self):
        from rfg import cli

        for verb in CORE_VERBS:
            self.assertIn(verb, cli.HELP, f"HELP missing core verb: {verb}")

    def test_agent_md_covers_core_tools(self):
        build = (ROOT / "docs" / "agent.md").read_text(encoding="utf-8")
        for tool in ("tick", "land", "verify", "doctor", "plan", "apply"):
            self.assertIn(tool, build, f"agent.md missing: {tool}")


if __name__ == "__main__":
    unittest.main()
