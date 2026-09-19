"""Doctrine tests (V1, test-first).

DoctrineTest pins: no network/daemon imports in the core, subprocess
surface limited to known files, stdlib-only imports, and the written
factory line (tripwires, checklist, escalation) — RED until V1.
"""

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RFG = ROOT / "rfg"

ALLOWED_SUBPROCESS = {"verify.py", "security.py", "gitops.py", "astgrep.py", "fmtutil.py"}
FORBIDDEN_IMPORTS = ("socket", "urllib", "http.client", "threading", "multiprocessing")
DOC_MARKERS = ["T1", "T7", "STEMPEL", "REZEPT", "SCHLUESSEL", "STOPP", "Review-Checkliste", "Vorher/Nachher"]


def _rfg_sources():
    return sorted(RFG.glob("*.py"))


class DoctrineTest(unittest.TestCase):
    def test_no_network_or_daemon_imports(self):
        hits = []
        for p in _rfg_sources():
            tree = ast.parse(p.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            bad = imported & set(FORBIDDEN_IMPORTS)
            if bad:
                hits.append(f"{p.name}: {sorted(bad)}")
        self.assertEqual(hits, [], hits)

    def test_subprocess_surface(self):
        hits = []
        for p in _rfg_sources():
            text = p.read_text(encoding="utf-8")
            if "subprocess" in text and p.name not in ALLOWED_SUBPROCESS:
                hits.append(p.name)
        self.assertEqual(hits, [], hits)

    def test_stdlib_only(self):
        stdlib = set(sys.stdlib_module_names)
        hits = []
        for p in _rfg_sources():
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                for name in names:
                    if name not in stdlib and name != "rfg":
                        hits.append(f"{p.name}: {name}")
        self.assertEqual(hits, [], hits)

    def test_factory_line_complete(self):
        doc = (ROOT / "docs" / "factory-line.md").read_text(encoding="utf-8")
        for marker in DOC_MARKERS:
            self.assertIn(marker, doc, f"factory-line.md missing: {marker}")

    def test_factory_line_binds_behavior(self):
        doc = (ROOT / "docs" / "factory-line.md").read_text(encoding="utf-8")
        self.assertIn("warn-first", doc)
        self.assertIn("Exit 4", doc)

    def test_baseline_protocol_binds(self):
        """QB-02: Vorher/Nachher-Protokoll nennt Mittel und Konsequenz."""
        doc = (ROOT / "docs" / "factory-line.md").read_text(encoding="utf-8")
        self.assertIn("mutation_sample", doc)
        self.assertIn("kein Land", doc)


if __name__ == "__main__":
    unittest.main()
