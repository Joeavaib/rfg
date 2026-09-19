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
GO = ROOT / "testdata" / "fixture"


class GapsTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-gaps-")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.env = os.environ.copy()
        self.env.update(
            {
                "PYTHONPATH": str(ROOT),
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t.test",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t.test",
            }
        )

    def git(self):
        subprocess.check_call(["git", "init"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)

    def git_go(self):
        for p in GO.iterdir():
            if p.is_file():
                shutil.copy(p, Path(self.td) / p.name)
        self.git()

    def rfg(self, *args, code=0):
        r = subprocess.run(
            RFG + ["--root", self.td, *args],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def rfg_raw(self, *args):
        r = subprocess.run(
            RFG + ["--root", self.td, *args],
            cwd=self.td,
            env=self.env,
            capture_output=True,
            text=True,
        )
        return r.returncode, r.stdout, r.stderr

    def test_land_after_committed_worktree(self):
        self.git_go()
        Path(self.td, "other.go").write_text("package users\nvar Foo = 1\n")
        subprocess.check_call(["git", "add", "other.go"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "other"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "s1",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--verify",
            "python3 -c \"assert 'UID' in open('user.go').read()\"",
        )
        self.rfg(
            "plan",
            "--step",
            "s2",
            "--from",
            "Foo",
            "--to",
            "Bar",
            "--path",
            "other.go",
            "--depends",
            "s1",
            "--verify",
            "python3 -c \"assert 'Bar' in open('other.go').read()\"",
        )
        self.rfg("apply")
        self.rfg("verify")
        self.rfg("apply")
        self.rfg("verify")
        self.assertIn("UserID", Path(self.td, "user.go").read_text())
        Path(self.td, "notes.txt").write_text("keep\n")
        out = json.loads(self.rfg("land", "--format", "json"))
        self.assertTrue(out["ok"], out)
        self.assertIn("UID", Path(self.td, "user.go").read_text())
        self.assertIn("Bar", Path(self.td, "other.go").read_text())
        self.assertTrue((Path(self.td) / "notes.txt").is_file())
        files = out["data"]["files"]
        self.assertTrue(any(f.endswith("user.go") for f in files), files)

    def test_land_copies_and_verify_root(self):
        self.git_go()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "s1",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--verify",
            "python3 -c \"assert 'UID' in open('user.go').read()\"",
        )
        self.rfg("apply")
        self.rfg("verify")
        self.assertIn("UserID", Path(self.td, "user.go").read_text())
        wt = Path(self.td) / ".rfg" / "worktree" / "user.go"
        self.assertIn("UID", wt.read_text())
        out = json.loads(self.rfg("land", "--format", "json"))
        self.assertTrue(out["ok"], out)
        self.assertIn("user.go", out["data"]["files"])
        self.assertIn("UID", Path(self.td, "user.go").read_text())
        Path(self.td, "extra.txt").write_text("x\n")
        code, raw, err = self.rfg_raw("land", "--format", "json")
        self.assertEqual(code, 3, raw + err)

    def test_land_gate_table(self):
        # QW-04: Land-Gate-Tabelle — jede Zeile ein Pin (Exit + Meldung).
        doc = (ROOT / "docs" / "factory-line.md").read_text(encoding="utf-8")
        self.assertIn("Land-Gate-Tabelle", doc)
        self.assertIn("applied but not verified", doc)
        # (a) offene Steps -> Exit 5.
        Path(self.td, "a.py").write_text("a = 1\n")
        self.git()
        self.rfg("init")
        self.rfg("plan", "--step", "g1", "--engine", "implement",
                 "--path", "a.py", "--want", "w", "--verify", "test -n ok")
        code, raw, err = self.rfg_raw("land", "--format", "json")
        self.assertEqual(code, 5, raw + err)
        self.assertIn("unfinished", raw + err)
        # (b) applied aber nicht verifiziert -> Exit 5 (andere Meldung).
        self.rfg("tick", "g1")
        self.rfg("apply", "g1")
        code, raw, err = self.rfg_raw("land", "--format", "json")
        self.assertEqual(code, 5, raw + err)
        self.assertIn("not verified", raw + err)
        # (c) dirty tracked Root ohne Steps -> Exit 3.
        td2 = tempfile.mkdtemp(prefix="rfg-gaps-dirty-")
        self.addCleanup(shutil.rmtree, td2, ignore_errors=True)
        Path(td2, "b.py").write_text("b = 1\n")
        old_td, self.td = self.td, td2
        try:
            self.git()
            self.rfg("init")
            Path(td2, "b.py").write_text("b = 2\n")
            code, raw, err = self.rfg_raw("land", "--format", "json")
            self.assertEqual(code, 3, raw + err)
            self.assertIn("dirty", raw + err)
        finally:
            self.td = old_td

    def test_manual_apply_stages_new_file(self):
        self.git_go()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "s1",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--verify",
            "test -n ok",
        )
        self.rfg("apply")
        self.rfg("verify")
        rel = "src/07-fibonacci/python/fibonacci.py"
        dest = Path(self.td) / rel
        dest.parent.mkdir(parents=True)
        dest.write_text("print('fib-ok')\n")
        self.rfg(
            "plan",
            "--step",
            "port",
            "--engine",
            "manual",
            "--path",
            rel,
            "--depends",
            "s1",
            "--verify",
            f"python3 {rel}",
        )
        applied = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(applied["ok"], applied)
        wt = Path(self.td) / ".rfg" / "worktree"
        self.assertTrue((wt / rel).is_file(), applied)
        self.assertIn(rel, applied["data"].get("staged") or [])
        ver = json.loads(self.rfg("verify", "--format", "json"))
        self.assertTrue(ver["ok"], ver)
        self.assertIn("fib-ok", ver["data"].get("output") or "")

    def test_manual_apply_when_dirty(self):
        self.git_go()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "m1",
            "--engine",
            "manual",
            "--path",
            "user.go",
            "--from",
            "UserID",
            "--to",
            "UID",
        )
        Path(self.td, "extra.txt").write_text("x\n")
        out = json.loads(self.rfg("apply", "--format", "json"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"]["step"], "m1")
        self.assertTrue(out["data"]["manual"])
        st = json.loads(self.rfg("status", "--format", "json"))
        step = next(s for s in st["data"]["steps"] if s["id"] == "m1")
        self.assertEqual(step["status"], "applied")

    def test_replace_apply_still_dirty(self):
        self.git_go()
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        Path(self.td, "extra.txt").write_text("x\n")
        code, out, err = self.rfg_raw("apply", "--format", "json")
        self.assertEqual(code, 0, out + err)

    def test_apply_followup_manual_on_string_skip(self):
        Path(self.td, "mod.py").write_text('NAME = "Foo"\nFoo = 1\n')
        Path(self.td, "go.mod").write_text("module m\n")
        self.git()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "s1",
            "--from",
            "Foo",
            "--to",
            "Bar",
            "--path",
            "mod.py",
            "--verify",
            "test -n ok",
        )
        out = json.loads(self.rfg("apply", "--format", "json"))
        self.assertEqual(out["data"].get("followup"), "manual")
        skipped = out["data"].get("skipped") or []
        self.assertTrue(any(s.get("reason") == "string_literal" for s in skipped), skipped)

    def test_tick_context_from_worktree(self):
        self.git_go()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "s1",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--verify",
            "test -n ok",
        )
        tick = json.loads(self.rfg("tick", "--format", "json"))
        self.assertEqual(tick["data"]["action"], "applied")
        blob = json.dumps(tick["data"].get("context") or {})
        self.assertIn("UID", blob)
        self.assertNotIn("type UserID", blob)

    def test_init_hypothesis_blank(self):
        Path(self.td, "go.mod").write_text("module m\n")
        self.rfg("init")
        yaml = Path(self.td, ".rfg", "roadmap.yaml").read_text()
        self.assertNotIn("UserID", yaml)
        st = json.loads(self.rfg("status", "--format", "json"))
        self.assertNotIn("UserID", st["data"].get("hypothesis") or "")

    def test_replace_identifier_boundary(self):
        Path(self.td, "list.c").write_text(
            "void test_list_node_new() {\n  list_node_new(x);\n}\n"
        )
        Path(self.td, "go.mod").write_text("module m\n")
        self.git()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "s1",
            "--from",
            "list_node_new",
            "--to",
            "list_node_create",
            "--path",
            "list.c",
            "--verify",
            "test -n ok",
        )
        self.rfg("apply")
        text = (Path(self.td) / ".rfg" / "worktree" / "list.c").read_text()
        self.assertIn("void test_list_node_new()", text)
        self.assertIn("list_node_create(x);", text)
        self.assertNotIn("test_list_node_create", text)

    def test_nested_default_verify(self):
        nested = Path(self.td) / "src" / "01-dog" / "go"
        nested.mkdir(parents=True)
        (nested / "go.mod").write_text("module dog\n")
        self.rfg("init")
        yaml = Path(self.td, ".rfg", "roadmap.yaml").read_text()
        self.assertIn("go test ./...", yaml)
        self.assertIn("src/01-dog/go", yaml)
        self.assertIn("cd ", yaml)

    def test_init_default_verify(self):
        Path(self.td, "go.mod").write_text("module m\n")
        self.git()
        self.rfg("init")
        yaml = Path(self.td, ".rfg", "roadmap.yaml").read_text()
        self.assertIn("go test ./...", yaml)
        doc = json.loads(self.rfg("doctor", "--format", "json"))
        self.assertEqual(doc["data"]["checks"]["verify"]["detail"], "go test ./...")

        td2 = tempfile.mkdtemp(prefix="rfg-py-")
        self.addCleanup(shutil.rmtree, td2, ignore_errors=True)
        (Path(td2) / "tests").mkdir()
        (Path(td2) / "tests" / "test_a.py").write_text("import unittest\n")
        (Path(td2) / "pkg.py").write_text("x = 1\n")
        r = subprocess.run(
            RFG + ["--root", td2, "init", "--format", "json"],
            cwd=td2,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        yaml2 = Path(td2, ".rfg", "roadmap.yaml").read_text()
        self.assertTrue("pytest" in yaml2 or "unittest" in yaml2, yaml2)

    def test_impact_nested_workspace(self):
        nested = Path(self.td) / "src" / "01-dog" / "go"
        nested.mkdir(parents=True)
        (nested / "go.mod").write_text("module dog\n")
        (nested / "dog.go").write_text("package main\nfunc calculate_dog_age() {}\n")
        ts = Path(self.td) / "src" / "01-dog" / "typescript"
        ts.mkdir(parents=True)
        (ts / "package.json").write_text("{}\n")
        (ts / "main.ts").write_text("function calculate_dog_age() {}\n")
        self.git()
        self.rfg("init")
        out = json.loads(self.rfg("impact", "--symbol", "calculate_dog_age", "--files", "--format", "json"))
        self.assertTrue(out["ok"], out)
        langs = out["data"]["languages"]
        self.assertIn("go", langs)
        self.assertIn("typescript", langs)
        files = [f["path"] for f in out["data"].get("files") or []]
        self.assertTrue(any(p.endswith("dog.go") for p in files), files)
        self.assertTrue(any(p.endswith("main.ts") for p in files), files)

    def test_plan_from_impact(self):
        self.git_go()
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--from-impact")
        nxt = json.loads(self.rfg("next", "--format", "json"))
        self.assertIn("user.go", nxt["data"]["path"])
        self.assertLessEqual(len(nxt["data"]["path"]), 8)

    def test_context_cousin_modules(self):
        go = Path(self.td) / "src" / "07-fibonacci" / "go"
        go.mkdir(parents=True)
        (go / "go.mod").write_text("module fib\n")
        (go / "fibonacci.go").write_text("package main\nfunc fibonacci(n uint) {}\n")
        py = Path(self.td) / "src" / "07-fibonacci" / "python"
        py.mkdir(parents=True)
        self.git()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "port",
            "--engine",
            "manual",
            "--path",
            "src/07-fibonacci/python/fibonacci.py",
        )
        ctx = json.loads(self.rfg("context", "--sources", "--format", "json"))["data"]
        paths = [s["path"] for s in ctx["snippets"]]
        self.assertIn("src/07-fibonacci/python/fibonacci.py", paths)
        self.assertTrue(any(p.endswith("fibonacci.go") for p in paths), ctx["snippets"])
        srcs = ctx.get("sources") or []
        self.assertTrue(any(p.endswith("fibonacci.go") for p in srcs), srcs)

    def test_context_missing_related(self):
        cxx = Path(self.td) / "cxx"
        cxx.mkdir()
        (cxx / "Makefile").write_text("all:\n\ttrue\n")
        (cxx / "main.cc").write_text("int main() { return 0; }\n")
        self.git()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "layout",
            "--engine",
            "manual",
            "--path",
            "cxx/new.cc",
        )
        ctx = json.loads(self.rfg("context", "--format", "json"))["data"]
        self.assertIn("cxx/new.cc", ctx["missing"])
        self.assertTrue(ctx.get("missing_ok"))
        self.assertFalse(any(s.get("error") == "missing" for s in ctx["snippets"]))
        sourced = json.loads(self.rfg("context", "--sources", "--format", "json"))["data"]
        related = [s["path"] for s in sourced["snippets"] if s.get("lines")]
        self.assertTrue(
            any(p.endswith("Makefile") or p.endswith("main.cc") for p in related),
            sourced["snippets"],
        )

    def test_mcp_rfg_home(self):
        from rfg.home import find_rfg_home

        self.env_home = os.environ.get("RFG_HOME")
        os.environ["RFG_HOME"] = "/tmp/rfg-home-test"
        self.addCleanup(self._restore_home)
        self.assertEqual(find_rfg_home(), Path("/tmp/rfg-home-test").resolve())
        mcp = json.loads((ROOT / "plugin" / "rfg" / ".mcp.json").read_text())
        args = mcp["mcpServers"]["rfg"]["args"]
        self.assertEqual(args, ["-m", "rfg", "mcp"])
        env = mcp["mcpServers"]["rfg"].get("env") or {}
        self.assertIn("RFG_HOME", env.get("PYTHONPATH", ""))
        self.assertTrue((ROOT / "scripts" / "rfg-mcp.py").is_file())
        self.assertTrue((ROOT / "plugin" / "rfg" / "mcp-launch.py").is_file())

    def _restore_home(self):
        if self.env_home is None:
            os.environ.pop("RFG_HOME", None)
        else:
            os.environ["RFG_HOME"] = self.env_home


if __name__ == "__main__":
    unittest.main()
