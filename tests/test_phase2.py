import io
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
PYFIX = ROOT / "testdata" / "pyfix"
SCIP = ROOT / "testdata" / "scip-sample.json"
GOFIX = ROOT / "testdata" / "fixture"


class Phase2Test(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="rfg2-")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(ROOT)

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

    def test_python_impact_and_index_incremental(self):
        for p in PYFIX.iterdir():
            shutil.copy(p, Path(self.td) / p.name)
        out = json.loads(self.rfg("impact", "--symbol", "UserID", "--format", "json"))
        self.assertGreater(out["data"]["hits"], 0)
        self.assertTrue(out["data"]["files"])
        self.assertIn("python", out["data"]["languages"])

        # impact already populated .rfg/index.json; rebuild must reuse hashes
        a = json.loads(self.rfg("index", "--format", "json"))
        self.assertGreaterEqual(a["data"]["reused"], 1)
        self.assertEqual(a["data"]["scanned"], 0)
        Path(self.td, "users.py").write_text(
            Path(self.td, "users.py").read_text() + "\nX = UserID\n"
        )
        b = json.loads(self.rfg("index", "--format", "json"))
        self.assertGreaterEqual(b["data"]["scanned"], 1)

    def test_scip_import_symbol(self):
        for p in GOFIX.iterdir():
            shutil.copy(p, Path(self.td) / p.name)
        self.rfg("init", "--format", "json")
        imp = json.loads(
            self.rfg("import-scip", str(SCIP), "--format", "json")
        )
        self.assertGreaterEqual(imp["data"]["occurrences"], 1)
        hit = json.loads(
            self.rfg("impact", "--symbol", "example.com/users/UserID#", "--format", "json")
        )
        self.assertGreater(hit["data"]["hits"], 0)
        self.assertEqual(hit["data"]["source"], "scip")
        self.assertEqual(hit["data"]["files"][0]["path"], "user.go")

    def test_astgrep_unsupported_without_binary(self):
        for p in GOFIX.iterdir():
            shutil.copy(p, Path(self.td) / p.name)
        env = self.env.copy()
        env["PATH"] = "/usr/bin"  # likely no ast-grep
        self.rfg("init")
        self.rfg(
            "plan",
            "--step",
            "sg",
            "--engine",
            "ast-grep",
            "--from",
            "UserID",
            "--to",
            "UID",
        )
        r = subprocess.run(
            RFG + ["--root", self.td, "apply", "--dry-run", "--format", "json"],
            cwd=self.td,
            env=env,
            capture_output=True,
            text=True,
        )
        from rfg import astgrep

        if not astgrep.available():
            self.assertEqual(r.returncode, 4, r.stdout + r.stderr)

    def test_mcp_tools_and_status(self):
        for p in GOFIX.iterdir():
            shutil.copy(p, Path(self.td) / p.name)
        subprocess.run(
            RFG + ["--root", self.td, "init"],
            cwd=self.td,
            env=self.env,
            check=True,
            capture_output=True,
        )
        from rfg.mcp import handle

        init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, self.td)
        self.assertEqual(init["result"]["serverInfo"]["name"], "rfg")
        listed = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, self.td)
        names = {t["name"] for t in listed["result"]["tools"]}
        for n in ("status", "next", "apply", "verify", "rollback", "impact"):
            self.assertIn(n, names)
        called = handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "status", "arguments": {}},
            },
            self.td,
        )
        text = called["result"]["content"][0]["text"]
        payload = json.loads(text)
        self.assertEqual(payload["command"], "status")
        self.assertEqual(payload["data"]["roadmap_id"], "roadmap-1")
        self.assertFalse(called["result"]["isError"])

    def test_mcp_lsp_framing(self):
        from io import BytesIO
        from rfg.mcp import _read_lsp, _write

        class Out:
            def __init__(self):
                self.buffer = BytesIO()

            def flush(self):
                pass

        out = Out()
        _write(out, {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}, framing="lsp")
        raw = out.buffer.getvalue()
        self.assertTrue(raw.startswith(b"Content-Length:"))
        msg = _read_lsp(BytesIO(raw))
        self.assertEqual(msg["id"], 1)
        self.assertTrue(msg["result"]["ok"])

    def test_github_action_mentions_status_json(self):
        yml = (ROOT / ".github" / "workflows" / "rfg.yml").read_text()
        self.assertIn("rfg.py status --format json", yml)


if __name__ == "__main__":
    unittest.main()
