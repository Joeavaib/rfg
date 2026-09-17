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


class DocsDriftHelpTest(unittest.TestCase):
    def test_help_covers_core_verbs(self):
        from rfg import cli

        for verb in CORE_VERBS:
            self.assertIn(verb, cli.HELP, f"HELP missing core verb: {verb}")

    def test_grok_build_covers_core_tools(self):
        build = (ROOT / "docs" / "GROK-BUILD.md").read_text(encoding="utf-8")
        for tool in ("tick", "land", "verify", "doctor", "plan", "apply"):
            self.assertIn(tool, build, f"GROK-BUILD.md missing: {tool}")


if __name__ == "__main__":
    unittest.main()
