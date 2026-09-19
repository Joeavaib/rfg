"""Depth-2 dry-run tests (D5, test-first).

Depth2Test pins: BFS one hop beyond related_step_ids counts only —
no state touch, cycle-safe, deterministic, depth-1/self excluded.
"""

import unittest

from rfg.types import Step


def _step(sid, paths=(), depends=()):
    s = Step(id=sid, title=sid, depends_on=list(depends))
    s.paths = list(paths)
    return s


class Depth2Test(unittest.TestCase):
    def test_counts_depth2_not_depth1(self):
        from rfg.verify import depth2_ids

        a = _step("a", ["a.py"])
        b = _step("b", ["a.py"], ["a"])
        c = _step("c", ["b.py"], ["b"])
        got = depth2_ids([a, b, c], a)
        self.assertIn("c", got)
        self.assertNotIn("a", got)
        self.assertNotIn("b", got)

    def test_cycle_safe_and_deduped(self):
        from rfg.verify import depth2_ids

        a = _step("a", ["a.py"], ["b"])
        b = _step("b", ["a.py"], ["a"])
        got = depth2_ids([a, b], a)
        self.assertEqual(got, sorted(set(got)))
        self.assertNotIn("a", got)

    def test_three_cycle_and_diamond_sorted(self):
        from rfg.verify import depth2_ids

        a = _step("a", ["a.py"])
        b = _step("b", ["b.py"], ["a"])
        c = _step("c", ["c.py"], ["b"])
        a.depends_on = ["c"]
        got = depth2_ids([a, b, c], a)
        self.assertEqual(got, sorted(got))
        self.assertNotIn("a", got)
        self.assertEqual(got, ["c"])

        a2 = _step("a", ["a.py"])
        b2 = _step("b", ["b.py"], ["a"])
        c2 = _step("c", ["c.py"], ["a"])
        d2 = _step("d", ["d.py"], ["b", "c"])
        diamond = depth2_ids([a2, b2, c2, d2], a2)
        self.assertEqual(diamond, ["d"])

        z = _step("z", ["z.py"], ["b"])
        m = _step("m", ["m.py"], ["c"])
        mixed = depth2_ids([a2, b2, c2, z, m], a2)
        self.assertEqual(mixed, ["m", "z"])

    def test_ghost_deps_logged_not_silent(self):
        from rfg.verify import depth2_ids

        a = _step("a", ["a.py"])
        b = _step("b", ["a.py"], ["ghost"])
        with self.assertLogs("rfg.verify", level="WARNING") as cm:
            got = depth2_ids([a, b], a)
        self.assertTrue(any("ghost" in m for m in cm.output), cm.output)
        self.assertEqual(got, sorted(got))
        self.assertNotIn("ghost", got)

    def test_pure_and_deterministic(self):
        import tempfile
        from rfg.verify import depth2_ids

        a = _step("a", ["a.py"])
        b = _step("b", ["a.py"], ["a"])
        c = _step("c", ["b.py"], ["b"])
        with tempfile.TemporaryDirectory(prefix="rfg-d2-") as td:
            import os

            before = set(os.listdir(td))
            r1 = depth2_ids([a, b, c], a)
            r2 = depth2_ids([a, b, c], a)
            self.assertEqual(r1, r2)
            self.assertEqual(set(os.listdir(td)), before)

    def test_verify_payload_carries_counter(self):
        import io
        import json
        import os
        import shutil
        import subprocess
        import tempfile
        from contextlib import redirect_stdout
        from pathlib import Path

        from rfg.cli import CLI

        td = tempfile.mkdtemp(prefix="rfg-d2-")
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.test",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.test"})
        subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
        subprocess.check_call(["git", "commit", "--allow-empty", "-qm", "i"], cwd=td, env=env)
        Path(td, "a.py").write_text("x = 1\n")
        Path(td, "b.py").write_text("y = 1\n")
        c = CLI(td, True, False)
        with redirect_stdout(io.StringIO()):
            c.cmd_plan(["--step", "A", "--engine", "implement", "--path", "a.py",
                        "--want", "a", "--verify", 'python3 -c "assert True"'])
            c.cmd_plan(["--step", "B", "--engine", "implement", "--path", "a.py",
                        "--want", "b", "--verify", 'python3 -c "assert True"',
                        "--depends", "A"])
            c.cmd_plan(["--step", "C", "--engine", "implement", "--path", "b.py",
                        "--want", "c", "--verify", 'python3 -c "assert True"',
                        "--depends", "B"])
            c.cmd_apply(["A"])
            c.cmd_apply(["B"])
            c.cmd_apply(["C"])
            with redirect_stdout(io.StringIO()) as buf:
                self.assertEqual(c.cmd_verify(["A"]), 0)
        payload = json.loads(buf.getvalue())["data"]
        self.assertIn("C", payload.get("depth2_would_warn") or [], payload)


if __name__ == "__main__":
    unittest.main()
