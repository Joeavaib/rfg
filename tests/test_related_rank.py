"""Ranked related tests (D1, test-first).

RankTest pins: dependents first, God-File damped by rarity,
deterministic id tiebreak, RFG_RELATED_MAX honored (RED until D1).
"""

import os
import unittest
from unittest import mock

from rfg.types import Step


def _step(sid, paths=(), depends=()):
    s = Step(id=sid, title=sid, depends_on=list(depends))
    s.paths = list(paths)
    return s


class RankTest(unittest.TestCase):
    def test_dependent_first(self):
        from rfg.verify import related_step_ids

        me = _step("x", ["x.py"])
        dep = _step("d", ["y.py"], ["x"])
        over = _step("o", ["x.py"])
        self.assertEqual(related_step_ids([me, dep, over], me)[0], "d")

    def test_god_file_damped(self):
        from rfg.verify import related_step_ids

        me = _step("me", ["cli.py", "rare.py"])
        crowd = [_step(f"c{i:02d}", ["cli.py"]) for i in range(12)]
        special = _step("special", ["rare.py"])
        got = related_step_ids([me, *crowd, special], me)
        self.assertIn("special", got)
        self.assertLess(got.index("special"), got.index("c00"))

    def test_deterministic_tiebreak(self):
        from rfg.verify import related_step_ids

        me = _step("me", ["s.py"])
        b2 = _step("b2", ["s.py"])
        b1 = _step("b1", ["s.py"])
        got = related_step_ids([me, b2, b1], me)
        self.assertEqual(got[:2], ["b1", "b2"])

    def test_cap_env(self):
        from rfg.verify import _related_cap, related_step_ids

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RFG_RELATED_MAX", None)
            self.assertEqual(_related_cap(), 10)
        with mock.patch.dict(os.environ, {"RFG_RELATED_MAX": "junk"}):
            self.assertEqual(_related_cap(), 10)
        me = _step("me", ["s.py"])
        others = [_step(f"o{i:02d}", ["s.py"]) for i in range(12)]
        with mock.patch.dict(os.environ, {"RFG_RELATED_MAX": "3"}):
            self.assertLessEqual(len(related_step_ids([me, *others], me)), 3)
        self.assertLessEqual(len(related_step_ids([me, *others], me)), 10)


if __name__ == "__main__":
    unittest.main()
