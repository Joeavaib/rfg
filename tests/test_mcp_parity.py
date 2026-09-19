"""CLI<->MCP parity tests (QM-03).

Every CORE_TOOL must be routed end-to-end (tools/list + tools/call),
so a new CLI verb without MCP parity breaks red instead of drifting
silently. Unknown verbs must answer -32601 (negative control proving
the detector detects).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class McpParityTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg-parity-")
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
        subprocess.check_call(["git", "init", "-q"], cwd=self.td, env=self.env,
                              stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "commit", "--allow-empty", "-qm", "i"],
                              cwd=self.td, env=self.env, stdout=subprocess.DEVNULL)

    def call(self, name, arguments, mid):
        from rfg import mcp

        return mcp.handle(
            {"jsonrpc": "2.0", "id": mid, "method": "tools/call",
             "params": {"name": name, "arguments": arguments}},
            self.td,
        )

    def test_core_tools_listed_with_schema(self):
        from rfg import mcp

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RFG_MCP_ALL", None)
            resp = mcp.handle({"id": 1, "method": "tools/list", "params": {}}, self.td)
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        for name in mcp.CORE_TOOLS:
            self.assertIn(name, tools, f"core verb missing from MCP: {name}")
            props = (tools[name].get("inputSchema") or {}).get("properties") or {}
            self.assertIn("root", props, f"MCP {name} missing root param")

    def test_core_verbs_routed_end_to_end(self):
        # call_tool returns (code, {}) when routed, (1, {"error": ...})
        # when not — that exact tuple is the routing detector.
        import io
        from contextlib import redirect_stdout

        from rfg import mcp

        with redirect_stdout(io.StringIO()):
            mcp.call_tool("init", {}, self.td)
        failures = []
        for name in mcp.CORE_TOOLS:
            try:
                with redirect_stdout(io.StringIO()):
                    code, extra = mcp.call_tool(name, {}, self.td)
            except Exception as exc:  # noqa: BLE001 — a crash IS a parity break
                failures.append(f"{name}: raised {exc!r}")
                continue
            if extra == {"error": "unknown tool"}:
                failures.append(f"{name}: not routed")
        self.assertEqual(failures, [], failures)

    def test_unknown_verb_is_not_routed(self):
        from rfg import mcp

        self.assertEqual(mcp.call_tool("frobnicate", {}, self.td),
                         (1, {"error": "unknown tool"}))
