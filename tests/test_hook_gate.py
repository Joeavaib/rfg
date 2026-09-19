"""CF-05: PreToolUse names next_id vs claim_step; does not rebind."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HookGateTest(unittest.TestCase):
    def test_hook_uses_next_id_not_claim_step(self):
        # FAIL: hook starts using claim_step for the allow set.
        src = (ROOT / "scripts" / "rfg-hook-pretool.py").read_text(encoding="utf-8")
        self.assertIn("dag.next_id", src)
        self.assertIn("claim_step", src)
        self.assertRegex(src, r"sid = dag\.next_id\(")
        self.assertIsNone(re.search(r"sid\s*=\s*.*claim_step", src))
        deny = src[src.find("reason") :]
        self.assertIn("next_id", deny)
        self.assertIn("claim_step", deny)
        self.assertIn("extras do not unlock", deny.lower())

    def test_agent_md_names_hook_mismatch(self):
        # FAIL: agent.md still says PreToolUse is replace-only.
        doc = (ROOT / "docs" / "agent.md").read_text(encoding="utf-8")
        self.assertIn("next_id", doc)
        self.assertIn("claim_step", doc)
        self.assertIn("extras", doc)
        low = doc.lower()
        self.assertIn("implement is gated", low)
        self.assertNotIn("on **replace** steps", doc)


if __name__ == "__main__":
    unittest.main()
