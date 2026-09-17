"""Quality-gate tests (H06-H08). stdlib-only, no hypothesis/coverage deps."""
import unittest


class QualityTest(unittest.TestCase):
    def test_diff_coverage(self):
        import tempfile, os, subprocess
        from pathlib import Path
        from scripts import diff_coverage as dc
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            (Path(td) / "rfg").mkdir()
            (Path(td) / "tests").mkdir()
            (Path(td) / "rfg" / "mod.py").write_text("def foo():\n    return 1\n")
            (Path(td) / "tests" / "test_mod.py").write_text("def test_x():\n    assert True\n")
            subprocess.check_call(["git", "add", "-A"], cwd=td, env=env)
            subprocess.check_call(["git", "commit", "-qm", "i"], cwd=td, env=env)
            # change foo without touching tests -> gate fails
            (Path(td) / "rfg" / "mod.py").write_text("def foo():\n    return 2\n")
            code, report = dc.check(td, "HEAD")
            self.assertEqual(code, 2, report)
            self.assertIn("foo", report)
            # reference foo in tests -> gate passes
            (Path(td) / "tests" / "test_mod.py").write_text(
                "from rfg.mod import foo\ndef test_x():\n    assert foo() == 2\n")
            code, report = dc.check(td, "HEAD")
            self.assertEqual(code, 0, report)

    def test_property_coerce(self):
        import json, random
        from rfg.types import coerce_depends_list, coerce_path_list
        rng = random.Random(20260916)
        alph = "abcXYZ019 _-./\"'[],"
        for _ in range(500):
            n = rng.randint(0, 4)
            ids = ["".join(rng.choice("ABab019_-") for _ in range(rng.randint(1, 8)))
                   for _ in range(n)]
            ids = [i for i in ids if i and "," not in i and '"' not in i and "'" not in i]
            # list roundtrip
            self.assertEqual(coerce_depends_list(list(ids)), ids)
            # JSON-array string roundtrip
            self.assertEqual(coerce_depends_list(json.dumps(ids)), ids)
            # comma string roundtrip (ids contain no comma/quotes by construction)
            if ids:
                self.assertEqual(coerce_depends_list(",".join(ids)), ids)
            else:
                self.assertEqual(coerce_depends_list(""), [])
        # bracket-list inputs never produce broken "[A" / "B]" fragments;
        # single tokens like "a[b]c" pass through unchanged (not a list).
        for s in ['["G02", "G03"]', "['A','B']", "[A, B]", "  ", ",", "["]:
            for dep in coerce_depends_list(s):
                self.assertNotIn("[", dep, s)
                self.assertNotIn("]", dep, s)
                self.assertNotIn('"', dep, s)
        self.assertEqual(coerce_depends_list("a[b]c"), ["a[b]c"])
        # path coercion keeps every file (no silent drop)
        for _ in range(200):
            n = rng.randint(0, 3)
            paths = ["".join(rng.choice("ab019/_-.") for _ in range(rng.randint(1, 12)))
                     for _ in range(n)]
            got = coerce_path_list(list(paths))
            self.assertEqual(sorted(got), sorted(p for p in paths if p))

    def test_property_yamlio_roundtrip(self):
        import random
        from rfg.types import Roadmap, Goal, Hypothesis, Step
        from rfg.yamlio import marshal_roadmap, unmarshal_roadmap
        rng = random.Random(7)
        for _ in range(50):
            steps = []
            for i in range(rng.randint(1, 5)):
                sid = f"S{i}-{rng.randint(0, 999)}"
                deps = [f"S{j}-{rng.randint(0, 999)}" for j in range(rng.randint(0, 2))]
                steps.append(Step(id=sid, title=f"t {sid}",
                                  depends_on=deps,
                                  verify=f"python3 -c 'assert {i} == {i}'",
                                  engine="implement",
                                  paths=[f"rfg/m{i}.py"],
                                  want=f"want-{i}"))
            rm = Roadmap(id="rm", hypothesis=Hypothesis(statement="h"),
                         goal=Goal(statement="g"), steps=steps)
            back = unmarshal_roadmap(marshal_roadmap(rm))
            self.assertEqual([s.id for s in back.steps], [s.id for s in steps])
            for a, b in zip(steps, back.steps):
                self.assertEqual(a.depends_on, b.depends_on)
                self.assertEqual(a.verify, b.verify)
                self.assertEqual(a.paths, b.paths)


    def test_mutation_sample(self):
        from scripts import mutation_sample as ms
        from pathlib import Path
        code, report = ms.run(Path(__file__).resolve().parent.parent)
        self.assertEqual(code, 0, report)
        self.assertIn("killed 4/4", report)


if __name__ == "__main__":
    unittest.main()
