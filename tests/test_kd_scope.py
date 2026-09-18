"""KD scope tests (warn-first, keine Gates, keine harten Limits)."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class KdScopeTest(unittest.TestCase):
    def test_kd1_broad_path_warns(self):
        from rfg import doctor
        from rfg.types import Step

        s = Step(id="KD-1x", title="t", engine="implement",
                 verify="python3 -m pytest tests/test_kd_scope.py -q")
        s.paths = [f"f{i}.py" for i in range(6)]
        warns = doctor.breadth_warnings([s])
        self.assertTrue(
            any("KD-1x" in w and "broad" in w.lower() for w in warns), warns)
        # warn-first: kein Gate, kein Raise, exit 0
        self.assertTrue(all("no gate" in w for w in warns), warns)
        # Dir-Expansion ueber MAX_FILES warnt ebenfalls (Tmp-Dir mit >8 Files)
        import tempfile
        from rfg.context import MAX_FILES

        with tempfile.TemporaryDirectory(prefix="rfg-kd1-") as td:
            d = Path(td) / "bigdir"
            d.mkdir()
            for i in range(int(MAX_FILES) + 2):
                (d / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")
            s2 = Step(id="KD-1y", title="t", engine="implement",
                      verify="pytest tests/test_kd_scope.py -q")
            s2.paths = ["bigdir"]
            warns2 = doctor.breadth_warnings([s2], root=td)
            self.assertTrue(any("KD-1y" in w for w in warns2), warns2)
        # schmaler Scope bleibt still
        s3 = Step(id="KD-1z", title="t", engine="implement", verify="pytest tests/test_a.py -q")
        s3.paths = ["a.py"]
        self.assertEqual(doctor.breadth_warnings([s3]), [])

    def test_kd2_verify_miss_warns(self):
        from rfg import doctor
        from rfg.types import Step

        # Dir-path[] vs File-verify ausserhalb warnt
        s = Step(id="KD-2x", title="t", engine="implement",
                 verify="pytest src/other.py -q")
        s.paths = ["src/mydir"]
        warns = doctor.oracle_warnings([s])
        self.assertTrue(
            any("KD-2x" in w and ("outside path" in w or "path[]" in w) for w in warns),
            warns)
        # Whole-Suite auf breitem Scope warnt extra
        s2 = Step(id="KD-2y", title="t", engine="implement", verify="pytest -q")
        s2.paths = [f"m{i}.py" for i in range(6)]
        warns2 = doctor.oracle_warnings([s2])
        self.assertTrue(any("whole-suite" in w for w in warns2), warns2)
        self.assertTrue(any("broad scope" in w.lower() for w in warns2), warns2)
        # survey-Exempt bleibt: kein path[]-Mismatch
        s3 = Step(id="KD-2z", title="t", engine="survey",
                  verify="pytest src/other.py -q")
        s3.paths = ["src/mydir"]
        warns3 = doctor.oracle_warnings([s3])
        self.assertFalse(any("outside path" in w and "KD-2z" in w for w in warns3), warns3)
        self.assertFalse(any("path[]" in w and "KD-2z" in w for w in warns3), warns3)

    def test_kd3_context_truncated_flag(self):
        import tempfile
        from rfg import context
        from rfg.types import Roadmap, State, Step

        with tempfile.TemporaryDirectory(prefix="rfg-kd3-") as td:
            root = Path(td)
            # breiter Scope: mehr path[] als MAX_FILES -> truncated + omitted
            files = []
            for i in range(int(context.MAX_FILES) + 3):
                p = root / f"m{i}.py"
                p.write_text(f"x{i} = {i}\n", encoding="utf-8")
                files.append(f"m{i}.py")
            rm = Roadmap()
            st = State()
            s = Step(id="KD-3x", title="t", engine="run",
                     verify="pytest tests/test_kd_scope.py -q")
            s.paths = list(files)
            pkt = context.packet(str(root), rm, st, s, sources=True)
            self.assertIn("truncated", pkt, pkt.keys())
            self.assertIn("omitted", pkt, pkt.keys())
            self.assertTrue(pkt["truncated"], pkt)
            self.assertGreater(int(pkt["omitted"]), 0, pkt)
            # contract meldet Kappung ebenfalls (snippets leben auf context)
            c = context.contract(str(root), rm, st, s)
            # contract nutzt sources=False; run ist non-contract -> fat -> Kappung sichtbar
            self.assertIn("truncated", c, c.keys())
            # Disk bleibt voll (Anzeige kappt, Disk voll)
            for f in files:
                self.assertTrue((root / f).is_file(), f)
                self.assertIn("x", (root / f).read_text(encoding="utf-8"))
            # schmaler Scope: kein truncated
            s2 = Step(id="KD-3y", title="t", engine="run",
                      verify="pytest tests/test_kd_scope.py -q")
            s2.paths = ["m0.py"]
            pkt2 = context.packet(str(root), rm, st, s2, sources=True)
            self.assertFalse(pkt2["truncated"], pkt2)
            self.assertEqual(int(pkt2["omitted"]), 0, pkt2)
            # K11-Regel: --max-chars 0 = unlimited
            from rfg.tokens import parse_max_chars

            self.assertIsNone(parse_max_chars(["--max-chars", "0"]))

    def test_kd4_scope_hint_no_gate(self):
        from rfg import doctor
        from rfg.types import Step

        hint = "Scope verkleinern statt Guard biegen"
        # breadth-Warnung endet mit Hint
        s = Step(id="KD-4x", title="t", engine="implement",
                 verify="pytest tests/test_kd_scope.py -q")
        s.paths = [f"b{i}.py" for i in range(6)]
        warns = doctor.breadth_warnings([s])
        self.assertTrue(warns, "breiter Scope muss warnen")
        for w in warns:
            self.assertIn(hint, w, w)
            self.assertTrue(w.rstrip().endswith(hint), w)
        # mismatch-Warnung endet mit Hint
        s2 = Step(id="KD-4y", title="t", engine="implement",
                  verify="pytest src/other.py -q")
        s2.paths = ["src/mydir"]
        warns2 = doctor.oracle_warnings([s2])
        scoped = [w for w in warns2 if "KD-4y" in w and ("outside path" in w or "path[]" in w)]
        self.assertTrue(scoped, warns2)
        for w in scoped:
            self.assertIn(hint, w, w)
            self.assertTrue(w.rstrip().endswith(hint), w)
        # kein Gate: Funktionen raisen nie, doctor.run bleibt ok (exit 0)
        try:
            doctor.oracle_warnings([s, s2])
            doctor.breadth_warnings([s])
        except BaseException as e:  # noqa: BLE001
            self.fail(f"Warnungen duerfen nie raisen: {e!r}")
        src = (ROOT / "rfg" / "doctor.py").read_text(encoding="utf-8")
        self.assertNotIn("sys.exit", src)
        rep = doctor.run(str(ROOT))
        self.assertTrue(rep["ok"], rep)
        self.assertTrue(rep["checks"]["oracles"]["ok"], rep)

    def test_kd5_glossary_guard_pin(self):
        text = (ROOT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8")
        low = text.lower()
        # broad-scope / truncated-context als Eintraege
        self.assertIn("broad-scope", low, text[:2000])
        self.assertIn("truncated-context", low, text[:4000])
        # cross-cutting rule
        self.assertIn("cross-cutting", low)
        # kein-hartes-Limit-Pin: keine Gates, keine harten Limits, warn-first
        for term in ("warn-first", "no gate", "kein-hartes-limit", "kein hartes limit"):
            self.assertIn(term, low, f"Glossar ohne Pin-Begriff {term!r}")
        # K11-Regel + Disk-voll + Exceptions/Prosa
        self.assertIn("--max-chars 0", text)
        self.assertIn("unlimited", low)
        self.assertIn("disk", low)
        self.assertIn("exception", low)
        self.assertIn("prosa", low)
        # Scope-Hint gepinnt
        self.assertIn("Scope verkleinern statt Guard biegen", text)


if __name__ == "__main__":
    unittest.main()
