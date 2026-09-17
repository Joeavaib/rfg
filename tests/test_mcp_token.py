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
SKILL = ROOT / ".grok" / "skills" / "rfg" / "SKILL.md"


class McpTokenTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-tok-")
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

    def git_go(self):
        for p in GO.iterdir():
            if p.is_file():
                shutil.copy(p, Path(self.td) / p.name)
        subprocess.check_call(["git", "init"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@t.test"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.td, env=self.env)
        subprocess.check_call(["git", "add", "-A"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "-m", "i"], cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)

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

    def test_progress_exit_0_when_dirty(self):
        self.git_go()
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        Path(self.td, "extra.txt").write_text("x\n")
        out = json.loads(self.rfg("progress", "--format", "json", code=0))
        self.assertTrue(out["ok"], out)
        kinds = {e["kind"] for e in out["data"]["exceptions"]}
        self.assertNotIn("dirty", kinds)

    def test_context_includes_impact_sources(self):
        self.git_go()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "port",
            "--engine",
            "manual",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "cxx/new.cc",
        )
        ctx = json.loads(self.rfg("context", "--sources", "--format", "json"))["data"]
        self.assertIn("user.go", ctx.get("sources") or [])
        paths = [s["path"] for s in ctx["snippets"]]
        self.assertTrue(any(p == "user.go" or p.endswith("user.go") for p in paths), ctx["snippets"])
        for s in ctx["snippets"]:
            self.assertLessEqual(len(s.get("lines") or []), 24)

    def test_mcp_core_and_schemas(self):
        from rfg.mcp import CORE_TOOLS, handle

        listed = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, self.td)
        tools = {t["name"]: t for t in listed["result"]["tools"]}
        self.assertEqual(set(tools), set(CORE_TOOLS))
        for name in ("init", "plan", "next", "context", "tick", "apply", "verify", "land", "rollback", "claim", "release", "progress", "doctor", "recipe", "why", "impact"):
            self.assertIn(name, tools)
        self.assertIn("step", tools["tick"]["inputSchema"]["properties"])
        apply_props = tools["apply"]["inputSchema"]["properties"]
        self.assertIn("step", apply_props)
        self.assertIn("dry_run", apply_props)
        self.assertIn("root", tools["land"]["inputSchema"]["properties"])
        plan_props = tools["plan"]["inputSchema"]["properties"]
        self.assertIn("from_impact", plan_props)
        self.assertIn("engine", plan_props)
        claim_props = tools["claim"]["inputSchema"]["properties"]
        self.assertIn("step", claim_props)

        self.git_go()
        handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "init", "arguments": {}}}, self.td)
        call = handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "plan",
                    "arguments": {
                        "step": "s1",
                        "from": "UserID",
                        "to": "UID",
                        "from_impact": True,
                    },
                },
            },
            self.td,
        )
        self.assertFalse(call["result"]["isError"], call)
        body = json.loads(call["result"]["content"][0]["text"])
        self.assertEqual(body["command"], "plan")
        nxt = handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "next", "arguments": {}}}, self.td)
        text = nxt["result"]["content"][0]["text"]
        self.assertNotIn("\n  ", text)
        data = json.loads(text)["data"]
        self.assertEqual(data["id"], "s1")
        self.assertIn("user.go", data["path"])

        Path(self.td, "extra.txt").write_text("x\n")
        prog = handle(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "progress", "arguments": {}}},
            self.td,
        )
        self.assertFalse(prog["result"]["isError"], prog)
        self.assertEqual(prog["result"]["exitCode"], 0)

    def test_mcp_root_argument(self):
        from rfg.mcp import handle

        listed = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "/tmp/not-the-repo")
        tools = {t["name"]: t for t in listed["result"]["tools"]}
        self.assertIn("root", tools["init"]["inputSchema"]["properties"])
        self.assertIn("root", tools["plan"]["inputSchema"]["properties"])
        self.git_go()
        other = "/tmp/not-the-repo"
        init = handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "init", "arguments": {"root": self.td}},
            },
            other,
        )
        self.assertFalse(init["result"]["isError"], init)
        self.assertTrue((Path(self.td) / ".rfg" / "roadmap.yaml").is_file())
        old = os.environ.get("RFG_ROOT")
        os.environ["RFG_ROOT"] = self.td
        self.addCleanup(lambda: os.environ.pop("RFG_ROOT", None) if old is None else os.environ.__setitem__("RFG_ROOT", old))
        nxt = handle(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "next", "arguments": {}}},
            other,
        )
        self.assertFalse(nxt["result"]["isError"], nxt)
        body = json.loads(nxt["result"]["content"][0]["text"])
        self.assertEqual(body["command"], "next")

    def test_mcp_tick_implement_is_stop_not_unsupported(self):
        from rfg.mcp import handle

        self.git_go()
        handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "init", "arguments": {}}}, self.td)
        plan = handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "plan",
                    "arguments": {
                        "step": "W01",
                        "engine": "implement",
                        "path": "db.py",
                        "want": "schema",
                        "verify": "test -f db.py",
                    },
                },
            },
            self.td,
        )
        self.assertFalse(plan["result"]["isError"], plan)
        tick = handle(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "tick", "arguments": {}}},
            self.td,
        )
        self.assertEqual(tick["result"]["exitCode"], 0, tick)
        self.assertFalse(tick["result"]["isError"], tick)
        body = json.loads(tick["result"]["content"][0]["text"])
        self.assertEqual(body["data"]["action"], "stop")
        self.assertEqual(body["data"]["reason"], "implement")
        Path(self.td, "db.py").write_text("ok\n")
        applied = handle(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "apply", "arguments": {}}},
            self.td,
        )
        self.assertEqual(applied["result"]["exitCode"], 0, applied)
        self.assertFalse(applied["result"]["isError"], applied)

    def test_skill_mentions_mcp_plan(self):
        text = SKILL.read_text()
        self.assertIn("`plan`", text)
        self.assertIn("MCP", text)
        self.assertIn("RFG_ROOT", text)
        self.assertIn("`land`", text)
        self.assertNotIn("plan is CLI", text.lower())
        self.assertLess(len(text.encode()), 1800)
        plugin = (ROOT / "plugin" / "rfg" / "skills" / "rfg" / "SKILL.md").read_text()
        self.assertIn("MCP", plugin)
        self.assertIn("RFG_ROOT", plugin)
        self.assertLess(len(plugin.encode()), 800)


if __name__ == "__main__":
    unittest.main()
