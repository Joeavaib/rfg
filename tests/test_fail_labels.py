"""FAIL:-Label-Tests (R1, test-first).

FailLabelTest pins: 19 GO-Steps tragen FAIL:-Zeilen (Auslöser+Fehler)
im want; No-Go-Klassen (want-lose manual-Steps, Sammel-Verifies,
Meta/Selbstreferenz, Prose) sind explizit ausgenommen und dokumentiert.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_FAIL_LINE = re.compile(r"(?m)^(FAIL|NEGATIV)\s*:\s*\S+")

# Step -> Keyword, das die FAIL:-Zeile enthalten muss (Auslöser+Fehler).
GO = {
    "F05": "too-broad",
    "F06": "makro",
    "F07": ".pyc",
    "F08": "weak-verify",
    "G01": "json-array",
    "G02": "--from",
    "G03": "untracked",
    "G04": "erfindet",
    "H01-depends-coerce": "G02",
    "H02-extra-visible": "--path",
    "H03-verify-dedup": "exit 5",
    "H04-cross-verify": "cross-verify-fail",
    "H05-land-gate": "trotz",
    "R01-index-robust": "skip",
    "R02-rollback-safe": "backup",
    "R03-replace-honest": "0 hits",
    "R04-plan-fields": "resettet",
    "M2-env-discover": ".rfg/env",
    "M6-cross-remedy": "log-pfad",
}

# No-Go-Klassen (bewusst ohne FAIL:-Pflicht, je mit Grund):
# - wantless-manual: 25 manual-Steps ohne want (z.B. progress-read) —
#   erst want nachtragen, dann FAIL (sonst erfundene Ziele).
# - shared-verify: F01-F04, skill-trim/root/land, R06, C01, K11 —
#   Sammel-Suites ohne ::-Target (erst splitten, sonst Sham).
# - meta: V2t/V2, H06, H07, H08, M7, K10, K11, K08 —
#   testen die Messlatte selbst (Selbstreferenz, kein Schwellenwert).
# - prose: skill-*, V0.3-docs-sync, G05-survey — notes-only/Doku.
NO_GO_SAMPLE = {
    "progress-read": "wantless-manual",
    "V0.1t-wt-tests": "shared-verify (Klasse, kein Einzel-Target)",
    "skill-trim": "shared-verify + prose",
    "K10-abschluss": "meta (kein Schwellenwert)",
    "G05": "prose (notes-only per Design)",
}


def _wants() -> dict:
    from rfg.store import Store

    rm = Store(str(ROOT)).load_roadmap()
    return {s.id: (s.want or "") for s in rm.steps}


class FailLabelTest(unittest.TestCase):
    def test_go_steps_have_fail_lines(self):
        wants = _wants()
        missing = []
        for sid, keyword in GO.items():
            want = wants.get(sid, "")
            if not _FAIL_LINE.search(want) or keyword.lower() not in want.lower():
                missing.append(sid)
        self.assertEqual(len(GO), 19)
        self.assertEqual(missing, [], missing)

    def test_no_go_sample_documented_and_exempt(self):
        wants = _wants()
        for sid, reason in NO_GO_SAMPLE.items():
            self.assertIn(sid, wants, f"sample step vanished: {sid}")
            self.assertNotIn(sid, GO, f"{sid} must stay exempt ({reason})")

    def test_go_no_go_disjoint(self):
        self.assertFalse(set(GO) & set(NO_GO_SAMPLE))


if __name__ == "__main__":
    unittest.main()
