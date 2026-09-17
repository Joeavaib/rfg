import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RFG = [sys.executable, str(ROOT / "rfg.py")]
FIXTURE = ROOT / "testdata" / "fixture"


class CLITest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        for p in FIXTURE.iterdir():
            shutil.copy(p, Path(self.td) / p.name)
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t.test",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t.test",
                "PYTHONPATH": str(ROOT),
            }
        )
        self.env = env
        self._git("init")
        self._git("config", "user.email", "t@t.test")
        self._git("config", "user.name", "t")
        self._git("add", "-A")
        self._git("commit", "-m", "init")

    def _git(self, *args):
        subprocess.check_call(["git", *args], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)

    def rfg(self, *args, code=0):
        cmd = RFG + ["--root", self.td, *args]
        r = subprocess.run(cmd, cwd=self.td, env=self.env, capture_output=True, text=True)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, code, out)
        return r.stdout

    def rfg_raw(self, *args):
        cmd = RFG + ["--root", self.td, *args]
        r = subprocess.run(cmd, cwd=self.td, env=self.env, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def test_help_lists_commands(self):
        code, out, err = self.rfg_raw("--help")
        text = out + err
        self.assertEqual(code, 0)
        for c in ("init", "status", "plan", "next", "apply", "verify", "rollback", "why"):
            self.assertIn(c, text)

    def test_full_loop(self):
        self.rfg("init", "--format", "json")
        self.rfg("plan", "--hypothesis", "Rename UserID string to typed ID", "--symbol", "UserID")
        self.rfg(
            "plan",
            "--step",
            "rename-type",
            "--title",
            "Rename type alias",
            "--from",
            "type UserID = string",
            "--to",
            "type UserID struct{ v string }",
            "--path",
            "user.go",
            "--verify",
            "test -n ok",
        )
        self.rfg(
            "plan",
            "--step",
            "rename-lookup",
            "--title",
            "Touch lookup",
            "--from",
            "func Lookup",
            "--to",
            "func Lookup",
            "--depends",
            "rename-type",
            "--path",
            "user.go",
            "--verify",
            "test -n ok",
        )
        self.rfg(
            "plan",
            "--step",
            "rename-store",
            "--title",
            "Touch store",
            "--from",
            "func Store",
            "--to",
            "func StoreX",
            "--depends",
            "rename-type",
            "--path",
            "store.go",
            "--verify",
            "false",
        )
        self.rfg(
            "plan",
            "--step",
            "final",
            "--title",
            "noop",
            "--from",
            "package users",
            "--to",
            "package users",
            "--depends",
            "rename-lookup,rename-store",
            "--path",
            "user.go",
            "--verify",
            "test -n ok",
        )

        st = json.loads(self.rfg("status", "--format", "json"))
        nxt = json.loads(self.rfg("next", "--format", "json"))
        self.assertEqual(st["data"]["next"], "rename-type")
        self.assertEqual(nxt["data"]["next"], "rename-type")
        self.assertTrue(st["data"]["steps"])
        self.assertEqual(st["data"]["roadmap_id"], "roadmap-1")

        dry = self.rfg("apply", "--dry-run", "--format", "json")
        denv = json.loads(dry)
        self.assertNotIn("diff", denv)
        self.assertNotIn("diff", denv["data"])
        self.assertGreater(denv["data"]["hits"], 0)
        self.assertTrue(denv["data"]["files"])

        self.rfg("apply", "--format", "json")
        wt_user = Path(self.td) / ".rfg" / "worktree" / "user.go"
        self.assertIn("struct{", wt_user.read_text())
        self.rfg("verify", "--format", "json")

        self.rfg("apply", "rename-store", "--format", "json")
        store = (Path(self.td) / ".rfg" / "worktree" / "store.go").read_text()
        self.assertIn("func StoreX", store)
        code, out, err = self.rfg_raw("verify", "--format", "json")
        self.assertEqual(code, 2, out + err)

        self.rfg("rollback", "last", "--format", "json")
        store2 = (Path(self.td) / ".rfg" / "worktree" / "store.go").read_text()
        self.assertIn("func Store(", store2)
        self.assertNotIn("func StoreX", store2)
        after = json.loads(self.rfg("status", "--format", "json"))
        self.assertIn(after["data"]["next"], ("rename-store", "rename-lookup"))
        store_st = next(x for x in after["data"]["steps"] if x["id"] == "rename-store")
        self.assertEqual(store_st["status"], "ready")
        # previous step remains
        self.assertIn("struct{", wt_user.read_text())

        imp = json.loads(self.rfg("impact", "--files", "--format", "json"))
        self.assertGreater(imp["data"]["hits"], 0)
        self.assertTrue(imp["data"]["files"])
        self.assertTrue(imp["data"]["files"][0]["path"])

        why = json.loads(self.rfg("why", "--format", "json"))
        self.assertIn("reason", why["data"])

    def test_status_twice_agrees(self):
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--title", "one", "--from", "UserID", "--to", "UID")
        a = json.loads(self.rfg("status", "--format", "json"))
        b = json.loads(self.rfg("status", "--format", "json"))
        self.assertEqual(a["data"]["roadmap_id"], b["data"]["roadmap_id"])
        self.assertEqual(a["data"]["next"], b["data"]["next"])
        self.assertEqual(a["data"]["next"], "s1")
        self.assertTrue(a["data"]["steps"])


class DagTest(unittest.TestCase):
    def test_next(self):
        from rfg.dag import next_id, compute
        from rfg.types import Roadmap, State, Step

        rm = Roadmap(
            id="r",
            steps=[
                Step(id="a", title="A"),
                Step(id="b", title="B", depends_on=["a"]),
            ],
        )
        st = State()
        self.assertEqual(next_id(rm, st), "a")
        st.applied = ["a"]
        self.assertEqual(next_id(rm, st), "b")
        self.assertEqual(compute(rm, st)["steps"][1]["status"], "ready")


class IndexTest(unittest.TestCase):
    def test_hits(self):
        from rfg.index import discover, impact

        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        Path(td, "go.mod").write_text("module m\n")
        Path(td, "a.go").write_text("package m\nvar UserID int\n")
        self.assertEqual(discover(td), "go")
        r = impact(td, "UserID")
        self.assertGreaterEqual(r["hits"], 1)
        self.assertTrue(r["files"])


class YamlTest(unittest.TestCase):
    def test_roundtrip(self):
        from rfg.types import Hypothesis, Replace, Roadmap, Step
        from rfg.yamlio import marshal_roadmap, unmarshal_roadmap

        r = Roadmap(
            id="roadmap-1",
            hypothesis=Hypothesis(id="h1", statement="Rename UserID", symbol="UserID"),
            verify="true",
            steps=[
                Step(
                    id="s1",
                    title="first",
                    replace=Replace(from_pat="UserID", to="UID", paths=["user.go"]),
                ),
                Step(id="s2", title="second", depends_on=["s1"], verify="true"),
            ],
        )
        got = unmarshal_roadmap(marshal_roadmap(r))
        self.assertEqual(got.id, "roadmap-1")
        self.assertEqual(got.steps[1].depends_on, ["s1"])
        self.assertEqual(got.steps[0].replace.from_pat, "UserID")


if __name__ == "__main__":
    unittest.main()
