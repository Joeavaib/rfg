"""DAG trap pins (QD): warn-first, no gate.

V02 pattern: a dependent step whose verify never names the dependency's
files must not stay silent.
"""

import unittest


class DagTrapsTest(unittest.TestCase):
    def test_depends_cross(self):
        from rfg import doctor
        from rfg.types import Step

        a = Step(
            id="V02a",
            title="t",
            engine="implement",
            verify="python3 -m pytest tests/test_lib.py -q",
        )
        a.paths = ["lib.py"]
        b = Step(
            id="V02b",
            title="t",
            engine="implement",
            verify="python3 -m pytest tests/test_app.py -q",
            depends_on=["V02a"],
        )
        b.paths = ["app.py"]
        warns = doctor.oracle_warnings([a, b])
        self.assertTrue(
            any(
                "V02b" in w and "V02a" in w and "depends_on" in w and "lib.py" in w
                for w in warns
            ),
            warns,
        )

        covered = Step(
            id="V02c",
            title="t",
            engine="implement",
            verify="python3 -m pytest tests/test_lib.py tests/test_app.py -q",
            depends_on=["V02a"],
        )
        covered.paths = ["app.py"]
        quiet = doctor.oracle_warnings([a, covered])
        self.assertFalse(
            any("V02c" in w and "depends_on" in w for w in quiet),
            quiet,
        )

    def test_shared_verify(self):
        from rfg import doctor
        from rfg.types import Step

        s = Step(
            id="F01x",
            title="t",
            engine="implement",
            verify="python3 -m pytest tests/test_a.py tests/test_b.py -q",
        )
        s.paths = [f"f{i}.py" for i in range(18)] + ["a.py", "b.py"]
        warns = doctor.oracle_warnings([s])
        self.assertTrue(
            any(
                "F01x" in w and "20" in w and ("a.py" in w or "f0.py" in w)
                for w in warns
            ),
            warns,
        )

        pred = Step(
            id="P",
            title="t",
            engine="implement",
            verify="python3 -m pytest tests/test_x.py -q",
        )
        pred.paths = ["x.py"]
        child = Step(
            id="C",
            title="t",
            engine="implement",
            verify="python3 -m pytest tests/test_x.py -q",
            depends_on=["P"],
        )
        child.paths = ["y.py"]
        shared = doctor.oracle_warnings([pred, child])
        self.assertTrue(
            any("C" in w and "P" in w and "identical" in w and "x.py" in w for w in shared),
            shared,
        )
