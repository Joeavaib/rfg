"""MCP deploy resolution tests (V0.2, test-first).

McpDeployTest pins the missing shared resolver (RED until V0.2-impl);
McpDeploySmokeTest locks launcher agreement + tools/list surface.
"""

import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load_launcher(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class McpDeployTest(unittest.TestCase):
    def test_shared_resolver_env_wins(self):
        from rfg.home import resolve_home

        with tempfile.TemporaryDirectory(prefix="rfg-home-") as td:
            with mock.patch.dict(os.environ, {"RFG_HOME": td}, clear=False):
                self.assertEqual(resolve_home(), Path(td).resolve())

    def test_shared_resolver_walks_from_file(self):
        from rfg.home import resolve_home

        with tempfile.TemporaryDirectory(prefix="rfg-home-") as td:
            fake = Path(td)
            (fake / "rfg").mkdir()
            (fake / "rfg" / "__main__.py").write_text("# marker\n")
            deep = fake / "scripts"
            deep.mkdir()
            with mock.patch.dict(os.environ, {}, clear=False):
                with mock.patch.dict(os.environ, {"RFG_HOME": ""}, clear=False):
                    got = resolve_home(here=deep / "rfg-mcp.py", depths=(2, 1))
            self.assertEqual(got, fake)

    def test_tools_list_is_core_by_default(self):
        from rfg import mcp

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RFG_MCP_ALL", None)
            resp = mcp.handle({"id": 1, "method": "tools/list", "params": {}}, str(ROOT))
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertEqual(names, set(mcp.CORE_TOOLS))

    def test_backup_restore_behind_flag_with_schema(self):
        from rfg import mcp

        with mock.patch.dict(os.environ, {"RFG_MCP_ALL": "1"}, clear=False):
            resp = mcp.handle({"id": 1, "method": "tools/list", "params": {}}, str(ROOT))
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        for name in ("backup", "restore"):
            self.assertIn(name, tools)
            self.assertIn("root", tools[name]["inputSchema"]["properties"])
        self.assertIn("id", tools["restore"]["inputSchema"]["properties"])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RFG_MCP_ALL", None)
            resp = mcp.handle({"id": 1, "method": "tools/list", "params": {}}, str(ROOT))
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertNotIn("backup", names)
        self.assertNotIn("restore", names)

    def test_backup_restore_call_roundtrip(self):
        import json
        import subprocess

        from rfg import mcp

        with tempfile.TemporaryDirectory(prefix="rfg-mcp-bak-") as td:
            env = dict(os.environ, PYTHONPATH=str(ROOT))
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            call = mcp.handle(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "init", "arguments": {}}},
                td,
            )
            self.assertFalse(call["result"]["isError"], call)
            bak = mcp.handle(
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "backup", "arguments": {}}},
                td,
            )
            self.assertFalse(bak["result"]["isError"], bak)
            body = json.loads(bak["result"]["content"][0]["text"])
            self.assertEqual(body["command"], "backup")
            bad = mcp.handle(
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "restore", "arguments": {"id": "no-such-backup"}}},
                td,
            )
            self.assertTrue(bad["result"]["isError"], bad)
            self.assertEqual(bad["result"]["exitCode"], 4, bad)


class McpDeploySmokeTest(unittest.TestCase):
    def test_both_launchers_agree_with_canonical(self):
        from rfg.home import resolve_home

        scripts_mod = _load_launcher(ROOT / "scripts" / "rfg-mcp.py", "rfg_mcp_a")
        plugin_mod = _load_launcher(ROOT / "plugin" / "rfg" / "mcp-launch.py", "rfg_mcp_b")
        with tempfile.TemporaryDirectory(prefix="rfg-home-") as td:
            fake = Path(td)
            (fake / "rfg").mkdir()
            (fake / "rfg" / "__main__.py").write_text("# marker\n")
            with mock.patch.dict(os.environ, {"RFG_HOME": ""}, clear=False):
                for mod, fake_here, depths in (
                    (scripts_mod, fake / "scripts" / "rfg-mcp.py", (2, 1)),
                    (plugin_mod, fake / "plugin" / "rfg" / "mcp-launch.py", (3, 2, 1)),
                ):
                    with mock.patch.object(mod, "__file__", str(fake_here)):
                        with mock.patch.object(Path, "cwd", return_value=fake):
                            got = mod._home()
                    want = resolve_home(here=fake_here, depths=depths)
                    self.assertEqual(got, fake, mod.__name__)
                    self.assertEqual(got, want, mod.__name__)


if __name__ == "__main__":
    unittest.main()
