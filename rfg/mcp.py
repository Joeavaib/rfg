"""Minimal MCP stdio server exposing the same operations as the CLI."""

from __future__ import annotations

import json
import sys
from typing import Any

from rfg.cli import CLI, OK

TOOLS = [
    {"name": "init", "description": "Create .rfg roadmap"},
    {"name": "status", "description": "Roadmap DAG status"},
    {"name": "plan", "description": "Add or update a step"},
    {"name": "next", "description": "Next free step"},
    {"name": "apply", "description": "Apply a step (dry_run optional)"},
    {"name": "verify", "description": "Run verify command"},
    {"name": "rollback", "description": "Rollback last checkpoint"},
    {"name": "why", "description": "Why a step is ready or blocked"},
    {"name": "impact", "description": "Symbol/file hit counts"},
    {"name": "index", "description": "Rebuild incremental index"},
    {"name": "edges", "description": "Cross-language edges (cgo, pyo3, napi)"},
    {"name": "doctor", "description": "Environment and schema checks"},
    {"name": "migrate", "description": "Migrate roadmap schema"},
]


def _cli(root: str) -> CLI:
    return CLI(root, json_out=True, dry=False)


def call_tool(name: str, arguments: dict[str, Any], root: str) -> tuple[int, dict]:
    c = _cli(root)
    args = []
    if name == "init":
        return c.cmd_init([]), {}
    if name == "status":
        return c.cmd_status(), {}
    if name == "next":
        return c.cmd_next(), {}
    if name == "plan":
        for k, flag in (
            ("step", "--step"),
            ("title", "--title"),
            ("frm", "--from"),
            ("from", "--from"),
            ("to", "--to"),
            ("depends", "--depends"),
            ("verify", "--verify"),
            ("hypothesis", "--hypothesis"),
            ("symbol", "--symbol"),
            ("path", "--path"),
        ):
            if arguments.get(k):
                args.extend([flag, str(arguments[k])])
        return c.cmd_plan(args), {}
    if name == "apply":
        c.dry = bool(arguments.get("dry_run"))
        if arguments.get("step"):
            args.append(str(arguments["step"]))
        return c.cmd_apply(args), {}
    if name == "verify":
        if arguments.get("step"):
            args.append(str(arguments["step"]))
        return c.cmd_verify(args), {}
    if name == "rollback":
        return c.cmd_rollback(["last"]), {}
    if name == "why":
        if arguments.get("step"):
            args.append(str(arguments["step"]))
        return c.cmd_why(args), {}
    if name == "impact":
        if arguments.get("symbol"):
            args.extend(["--symbol", str(arguments["symbol"])])
        return c.cmd_impact(args), {}
    if name == "index":
        return c.cmd_index([]), {}
    if name == "edges":
        return c.cmd_edges([]), {}
    if name == "doctor":
        return c.cmd_doctor([]), {}
    if name == "migrate":
        return c.cmd_migrate([]), {}
    return 1, {"error": "unknown tool"}


def handle(msg: dict, root: str) -> dict:
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "rfg", "version": "1.0.0"},
            },
        }
    if method == "tools/list":
        tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": {"type": "object"},
            }
            for t in TOOLS
        ]
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        # capture stdout from CLI emit
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code, _ = call_tool(name, arguments, root)
        text = buf.getvalue()
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": code != OK,
                "exitCode": code,
            },
        }
    if method == "notifications/initialized" or method is None:
        return {}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": str(method)}}


def _write(stdout, obj: dict, *, framing: str) -> None:
    raw = json.dumps(obj)
    if framing == "lsp":
        body = raw.encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        buf = stdout.buffer if hasattr(stdout, "buffer") else stdout
        buf.write(header + body)
        if hasattr(buf, "flush"):
            buf.flush()
        return
    stdout.write(raw + "\n")
    stdout.flush()


def _read_lsp(buf) -> dict | None:
    headers = {}
    while True:
        line = buf.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        if b":" in line:
            k, v = line.decode("ascii", errors="replace").split(":", 1)
            headers[k.strip().lower()] = v.strip()
    n = int(headers.get("content-length") or "0")
    if n <= 0:
        return None
    body = buf.read(n)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def serve(stdin=None, stdout=None, root: str | None = None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    root = root or "."
    buf = stdin.buffer if hasattr(stdin, "buffer") else stdin
    sample = b""
    if hasattr(buf, "peek"):
        try:
            sample = buf.peek(32) or b""
        except Exception:
            sample = b""
    ndjson = sample.lstrip().startswith(b"{")
    if ndjson:
        for line in stdin:
            line = line.strip() if isinstance(line, str) else line.decode("utf-8").strip()
            if not line:
                continue
            resp = handle(json.loads(line), root)
            if resp:
                _write(stdout, resp, framing="ndjson")
        return
    while True:
        msg = _read_lsp(buf)
        if msg is None:
            break
        resp = handle(msg, root)
        if resp:
            _write(stdout, resp, framing="lsp")


if __name__ == "__main__":
    serve()
