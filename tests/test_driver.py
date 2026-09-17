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
CXX = ROOT / "examples" / "cxx"


class DriverTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-drv-")
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

    def test_apply_json_omits_diff(self):
        self.git_go()
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        out = json.loads(self.rfg("apply", "--format", "json"))
        self.assertNotIn("diff", out)
        self.assertNotIn("diff", out["data"])
        self.assertIn("files", out["data"])
        self.assertGreater(out["data"]["hits"], 0)

    def test_next_includes_claim_budget(self):
        self.git_go()
        self.rfg("init")
        self.rfg("plan", "--budget", "4")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        env = self.env.copy()
        env["RFG_AGENT"] = "grok"
        subprocess.run(
            RFG + ["--root", self.td, "claim", "--agent", "grok", "--format", "json"],
            cwd=self.td,
            env=env,
            check=True,
            capture_output=True,
        )
        nxt = json.loads(self.rfg("next", "--format", "json"))
        d = nxt["data"]
        self.assertEqual(d["claim_agent"], "grok")
        self.assertEqual(d["claim_step"], "s1")
        self.assertEqual(d["budget"]["max_applies"], 4)
        self.assertIn("applies_used", d)

    def test_context_bounded_to_paths(self):
        self.git_go()
        self.rfg("init")
        self.rfg("plan", "--step", "s1", "--from", "UserID", "--to", "UID", "--path", "user.go")
        ctx = json.loads(self.rfg("context", "--format", "json"))["data"]
        self.assertEqual(ctx["path"], ["user.go"])
        self.assertTrue(ctx["snippets"])
        self.assertEqual(ctx["snippets"][0]["path"], "user.go")
        self.assertLessEqual(len(ctx["snippets"][0]["lines"]), 40)
        self.assertEqual(ctx["tick"], "apply")

    def test_tick_manual_stop(self):
        self.git_go()
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "m1",
            "--from",
            "UserID",
            "--to",
            "UID",
            "--path",
            "user.go",
            "--engine",
            "manual",
        )
        out = json.loads(self.rfg("tick", "--format", "json"))
        self.assertEqual(out["data"]["action"], "stop")
        self.assertEqual(out["data"]["reason"], "manual")
        self.assertEqual(out["data"]["context"]["tick"], "stop")

    def test_tick_replace_applies(self):
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
        out = json.loads(self.rfg("tick", "--format", "json"))
        self.assertEqual(out["data"]["action"], "applied")
        self.assertEqual(out["data"]["code"], 0)
        text = (Path(self.td) / ".rfg" / "worktree" / "user.go").read_text()
        self.assertIn("type UID", text)

    def test_cxx_compile_cmd_from_db(self):
        from rfg.cxxcompile import command, should_default

        cmd = command(CXX, ["user_id.cc"])
        self.assertIn("user_id.cc", cmd)
        self.assertTrue(should_default(CXX, ["user_id.cc"]))
        self.assertFalse(should_default(self.td, ["user.go"]))

    def test_recipe_placeholders(self):
        Path(self.td, "go.mod").write_text("module m\n")
        self.rfg("init")
        self.rfg("recipe", "apply", "rename", "--from", "UserID", "--to", "UID")
        nxt = json.loads(self.rfg("next", "--format", "json"))
        self.assertEqual(nxt["data"]["from"], "UserID")
        self.assertEqual(nxt["data"]["to"], "UID")

    def test_mcp_core_tools(self):
        from rfg.mcp import CORE_TOOLS, handle

        listed = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, self.td)
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertEqual(names, set(CORE_TOOLS))
        self.assertNotIn("sbom", names)
        self.assertIn("plan", names)
        self.assertIn("init", names)
        self.assertIn("doctor", names)
        self.assertIn("recipe", names)
        self.assertIn("why", names)
        self.assertIn("impact", names)

    def test_plugin_layout(self):
        self.assertTrue((ROOT / ".grok-plugin" / "marketplace.json").is_file())
        self.assertTrue((ROOT / "plugin" / "rfg" / "plugin.json").is_file())
        self.assertTrue((ROOT / "plugin" / "rfg" / "hooks" / "hooks.json").is_file())
        self.assertTrue((ROOT / "scripts" / "rfg-hook-pretool.py").is_file())
        self.assertTrue((ROOT / "scripts" / "rfg-hook-stop.py").is_file())
        self.assertTrue((ROOT / ".grok" / "hooks" / "rfg.json").is_file())
        self.assertTrue((ROOT / "plugin" / "rfg" / "mcp-launch.py").is_file())
        self.assertTrue((ROOT / "scripts" / "rfg-mcp.py").is_file())


if __name__ == "__main__":
    unittest.main()
