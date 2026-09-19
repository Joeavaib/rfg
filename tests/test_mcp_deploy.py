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

    def test_backup_id_allowlist(self):
        # QM-02: allowlist pins fail-stop ids; traversal never restores.
        from rfg import gitops

        for good in ("20260918T222247-8e47c7e1", "manual-retry", "a.b_c-d", "B01"):
            self.assertTrue(gitops._valid_backup_id(good), good)
        for bad in ("", "../x", "/abs", "a/b", ".hidden", "-dash", "sp ace",
                    "  ", "x" * 201, None, 123):
            self.assertFalse(gitops._valid_backup_id(bad), repr(bad))

    def test_restore_traversal_is_exit_4(self):
        # QM-02: ../-restore is refused (OSError -> exit 4), never guessed.
        import json

        from rfg import gitops, mcp

        with tempfile.TemporaryDirectory(prefix="rfg-mcp-trav-") as td:
            bad = mcp.handle(
                {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                 "params": {"name": "restore", "arguments": {"id": "../x"}}},
                td,
            )
            self.assertTrue(bad["result"]["isError"], bad)
            self.assertEqual(bad["result"]["exitCode"], 4, bad)
            with self.assertRaises(OSError):
                gitops.restore_roadmap_state(td, "/abs")
            with self.assertRaises(OSError):
                gitops.diff_roadmap_state(td, "a/b")

    def test_doctor_names_external_root(self):
        # QM-02: root outside cwd is named (warn-first, never a gate).
        from unittest import mock

        from rfg import doctor

        with tempfile.TemporaryDirectory(prefix="rfg-doc-root-") as td:
            with mock.patch.object(Path, "cwd", return_value=Path("/definitely/elsewhere")):
                rep = doctor.run(td)
            root_check = rep["checks"]["root"]
            self.assertTrue(root_check["ok"], root_check)
            self.assertIn("outside", root_check["detail"], root_check)
            with mock.patch.object(Path, "cwd", return_value=Path(td)):
                rep = doctor.run(td)
            self.assertIn("cwd", rep["checks"]["root"]["detail"])

    def test_qm05_external_root_guard_deferred(self):
        # QM-05: hard --allow-external-root waits for gotoharness flag
        # coordination. FAIL: Guard lands without coordinated flag.
        import json
        import subprocess
        import sys

        from rfg import cli as climod
        from rfg import mcp

        src_cli = Path(climod.__file__).read_text(encoding="utf-8")
        src_mcp = Path(mcp.__file__).read_text(encoding="utf-8")
        for src, label in ((src_cli, "cli"), (src_mcp, "mcp")):
            self.assertIn("allow-external-root", src, label)
            self.assertIn("gotoharness", src.lower(), label)
            self.assertIn("deferred", src.lower(), label)

        with tempfile.TemporaryDirectory(prefix="rfg-qm05-") as td:
            r = subprocess.run(
                [sys.executable, str(ROOT / "rfg.py"), "--root", td,
                 "--format", "json", "version"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            body = json.loads(r.stdout)
            self.assertTrue(body.get("ok"), body)
            # Uncoordinated hard guard would reject --root outside cwd (exit 4).
            self.assertNotEqual(r.returncode, 4)
            self.assertNotIn("allow-external-root", r.stdout)


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
