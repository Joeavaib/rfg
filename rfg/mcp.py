"""Minimal MCP stdio server exposing the same operations as the CLI.

QM-05: MCP `root` outside cwd is allowed (warn-first). A hard
`--allow-external-root` guard (exit 4) is deferred until gotoharness
clients can send that flag; otherwise foreign campaigns break.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from pathlib import Path

from rfg import __version__
from rfg.cli import CLI, OK
from rfg.types import coerce_depends_list, coerce_path_list

# Same verbs as the CLI driver loop. Catalog stays behind RFG_MCP_ALL=1.
CORE_TOOLS = (
    "init",
    "plan",
    "next",
    "context",
    "tick",
    "apply",
    "verify",
    "land",
    "rollback",
    "claim",
    "release",
    "progress",
    "resume",
    "doctor",
    "recipe",
    "why",
    "impact",
    "harvest",
    "harvest_stat",
)

_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_ROOT = {"type": "string", "description": "Repo root (same as CLI --root; else RFG_ROOT or server cwd)"}
SCHEMAS = {
    "init": {"type": "object", "properties": {"root": _ROOT}},
    "plan": {
        "type": "object",
        "properties": {
            "root": _ROOT,
            "step": _STR,
            "title": _STR,
            "from": _STR,
            "to": _STR,
            "path": {"oneOf": [_STR, {"type": "array", "items": _STR}]},
            "extras": {"oneOf": [_STR, {"type": "array", "items": _STR}]},
            "list": _BOOL,
            "engine": _STR,
            "verify": _STR,
            "depends": {"oneOf": [_STR, {"type": "array", "items": _STR}]},
            "symbol": _STR,
            "goal": _STR,
            "want": _STR,
            "hypothesis": _STR,
            "profile": _STR,
            "acceptance": _STR,
            "from_impact": _BOOL,
            "diff_budget": _STR,
            "oracle": _STR,
            "edge": _STR,
            "budget": _STR,
            "check": _BOOL,
        },
    },
    "next": {"type": "object", "properties": {"root": _ROOT}},
    "context": {"type": "object", "properties": {"root": _ROOT, "step": _STR, "sources": _BOOL}},
    "tick": {"type": "object", "properties": {"root": _ROOT, "step": _STR}},
    "apply": {
        "type": "object",
        "properties": {
            "root": _ROOT,
            "step": _STR,
            "dry_run": _BOOL,
            "force": _BOOL,
            "agent": _STR,
        },
    },
    "release": {"type": "object", "properties": {"root": _ROOT}},
    "backup": {"type": "object", "properties": {"root": _ROOT}},
    "restore": {"type": "object", "properties": {"root": _ROOT, "id": _STR}},
    "verify": {"type": "object", "properties": {"root": _ROOT, "step": _STR}},
    "land": {"type": "object", "properties": {"root": _ROOT, "commit": _BOOL}},
    "rollback": {"type": "object", "properties": {"root": _ROOT}},
    "claim": {"type": "object", "properties": {"root": _ROOT, "step": _STR, "agent": _STR}},
    "progress": {"type": "object", "properties": {"root": _ROOT}},
    "resume": {"type": "object", "properties": {"root": _ROOT}},
    "doctor": {"type": "object", "properties": {"root": _ROOT, "verbose": _BOOL}},
    "recipe": {
        "type": "object",
        "properties": {
            "root": _ROOT,
            "action": _STR,
            "id": _STR,
            "path": _STR,
            "verify": _STR,
            "from": _STR,
            "to": _STR,
            "goal": _STR,
            "profile": _STR,
            "depends": _STR,
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": _STR,
                        "path": {"oneOf": [_STR, {"type": "array", "items": _STR}]},
                        "verify": _STR,
                        "depends": {"oneOf": [_STR, {"type": "array", "items": _STR}]},
                        "want": _STR,
                        "engine": _STR,
                    },
                },
            },
        },
    },
    "why": {"type": "object", "properties": {"root": _ROOT, "step": _STR}},
    "impact": {"type": "object", "properties": {"root": _ROOT, "symbol": _STR, "files": _BOOL}},
    "harvest": {
        "type": "object",
        "properties": {
            "root": _ROOT,
            "out": {
                "type": "string",
                "description": "Farm directory (else RFG_FARM). External rfg-farm, not .rfg/",
            },
        },
    },
    "harvest_stat": {
        "type": "object",
        "properties": {
            "out": {
                "type": "string",
                "description": "Farm directory (else RFG_FARM)",
            },
        },
    },
}

TOOLS = [
    {"name": "init", "description": "Create .rfg store"},
    {"name": "status", "description": "Roadmap DAG status"},
    {"name": "plan", "description": "Campaign goal without step; step want/path/verify with --step. Does not overwrite the product goal."},
    {"name": "next", "description": "Next step plus ready[] and a recommend (critical path / smallest verify)"},
    {"name": "context", "description": "Step contract (want, path, missing, verify). Cousins only with sources=true."},
    {"name": "tick", "description": "Replace: apply+verify. implement/manual: claim in_progress + contract. Optional step= overrides next/recommend."},
    {"name": "apply", "description": "Apply a step. No agent = same client as the claim. implement/manual: copy path[] and extra root edits into the worktree."},
    {"name": "verify", "description": "Run verify"},
    {"name": "land", "description": "Copy worktree onto root and re-verify"},
    {"name": "rollback", "description": "Restore last checkpoint"},
    {"name": "backup", "description": "List roadmap/state backups (recovery; needs RFG_MCP_ALL=1)"},
    {"name": "restore", "description": "Restore roadmap/state from a backup id (recovery; needs RFG_MCP_ALL=1)"},
    {"name": "claim", "description": "Lock a step"},
    {"name": "release", "description": "Drop the current step claim"},
    {"name": "audit", "description": "Recent audit.jsonl events"},
    {"name": "baseline", "description": "Capture perf oracle baseline"},
    {"name": "repro", "description": "Run debug oracle / write repro.log"},
    {"name": "progress", "description": "Goal, counts, exceptions"},
    {"name": "resume", "description": "One-call session resume (goal, counts, last/next, git, drift, checkpoint)"},
    {"name": "digest", "description": "Write .rfg/digest.json nightly handoff"},
    {"name": "why", "description": "Why a step is ready or blocked"},
    {"name": "impact", "description": "Hit counts. files=true to list paths."},
    {"name": "index", "description": "Rebuild incremental index"},
    {"name": "edges", "description": "Cross-language edges (cgo, pyo3, napi)"},
    {"name": "scan", "description": "Security scan command or scanner presence (no exploits)"},
    {"name": "fuzz", "description": "Fuzzer presence or configured fuzz command"},
    {"name": "sbom", "description": "Write CycloneDX-lite inventory to .rfg/sbom.json"},
    {"name": "boundaries", "description": "FFI trust boundaries"},
    {"name": "fleet", "description": "Progress across local fleet.yaml repos"},
    {"name": "export", "description": "Write offline batch-changes.yaml or static dashboard.html"},
    {"name": "recipe", "description": "List/show/apply bundled roadmap recipes"},
    {"name": "packs", "description": "List packs; paid enable is unsupported"},
    {"name": "harvest", "description": "Copy implement packets (want/path[]/diff) into RFG_FARM. External farmer, not rfg store. Pass root= for the campaign repo."},
    {"name": "harvest_stat", "description": "Counts of harvested packets (with_contract vs diff-only)"},
    {"name": "doctor", "description": "Environment and schema checks. Extra verbs (status, audit, …) need RFG_MCP_ALL=1"},
    {"name": "migrate", "description": "Migrate roadmap schema"},
]


def _cli(root: str) -> CLI:
    return CLI(root, json_out=True, dry=False, compact=True)


def _tool_root(arguments: dict[str, Any], default: str) -> str:
    """Repo root precedence (QM-01, single source — no silent drift).

    1. arguments["root"] (explicit per call, wins over everything)
    2. RFG_ROOT env (server-wide default)
    3. default (server cwd at serve time)
    Empty/blank values fall through to the next level (a blank root
    must never silently become the effective root).
    """
    arg = ""
    if isinstance(arguments, dict):
        arg = str(arguments.get("root") or "").strip()
    if arg:
        return arg
    env = str(os.environ.get("RFG_ROOT") or "").strip()
    if env:
        return env
    return str(default)


def _harvest_py() -> Path | None:
    """Where harvest.py lives. Never the packet `out` directory.

    Subagents pass out=farm_01 (empty packet dir). That must not be
    required to contain harvest.py — look at RFG_FARM, RFG_HOME sibling,
    then the checkout next to this package (works when subagent MCP
    inherits neither env).
    """
    env = str(os.environ.get("RFG_FARM") or "").strip()
    if env:
        p = Path(env)
        if p.is_file() and p.name == "harvest.py":
            return p
        cand = p / "harvest.py"
        if cand.is_file():
            return cand
    home = str(os.environ.get("RFG_HOME") or "").strip()
    if home:
        cand = Path(home).resolve().parent / "rfg-farm" / "harvest.py"
        if cand.is_file():
            return cand
    here = Path(__file__).resolve().parents[1]  # repo that contains rfg/
    cand = here.parent / "rfg-farm" / "harvest.py"
    if cand.is_file():
        return cand
    return None


def _packet_out(arguments: dict[str, Any] | None, harvest_py: Path) -> Path:
    arg = ""
    if isinstance(arguments, dict):
        arg = str(arguments.get("out") or "").strip()
    if arg:
        return Path(arg)
    env = str(os.environ.get("RFG_FARM") or "").strip()
    if env:
        p = Path(env)
        return p.parent if p.is_file() else p
    return harvest_py.parent


def _call_farm(action: str, arguments: dict[str, Any], root: str) -> tuple[int, dict]:
    script = _harvest_py()
    if script is None:
        print(json.dumps({
            "ok": False,
            "error": "unsupported: harvest.py not found (set RFG_FARM or keep rfg-farm next to the rfg checkout)",
        }))
        return 4, {}
    import importlib.util

    spec = importlib.util.spec_from_file_location("rfg_farm_harvest", script)
    if spec is None or spec.loader is None:
        print(json.dumps({"ok": False, "error": "unsupported: harvest.py not loadable"}))
        return 4, {}
    farm_harvest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(farm_harvest)

    out = _packet_out(arguments, script)
    if action == "stat":
        rows = farm_harvest.load_index(out)
        known = sum(1 for r in rows if r.get("contract_known"))
        payload = {
            "ok": True,
            "packets": len(rows),
            "with_contract": known,
            "without_contract": len(rows) - known,
            "out": str(out),
        }
        print(json.dumps(payload))
        return OK, {}
    info = farm_harvest.harvest(Path(root), out)
    info["ok"] = True
    print(json.dumps(info))
    return OK, {}


def call_tool(name: str, arguments: dict[str, Any], root: str) -> tuple[int, dict]:
    root = _tool_root(arguments, root)
    c = _cli(root)
    args = []
    if name == "init":
        return c.cmd_init([]), {}
    if name == "status":
        return c.cmd_status(), {}
    if name == "resume":
        return c.cmd_resume(), {}
    if name == "next":
        return c.cmd_next(), {}
    if name == "context":
        if arguments.get("step"):
            args.append(str(arguments["step"]))
        if arguments.get("sources"):
            args.append("--sources")
        return c.cmd_context(args), {}
    if name == "tick":
        if arguments.get("step"):
            args.append(str(arguments["step"]))
        if arguments.get("agent"):
            args.extend(["--agent", str(arguments["agent"])])
        return c.cmd_tick(args), {}
    if name == "plan":
        for k, flag in (
            ("step", "--step"),
            ("title", "--title"),
            ("from_pat", "--from"),
            ("from", "--from"),
            ("to", "--to"),
            ("verify", "--verify"),
            ("hypothesis", "--hypothesis"),
            ("symbol", "--symbol"),
            ("engine", "--engine"),
            ("goal", "--goal"),
            ("want", "--want"),
            ("profile", "--profile"),
            ("acceptance", "--acceptance"),
            ("diff_budget", "--diff-budget"),
            ("oracle", "--oracle"),
            ("edge", "--edge"),
            ("budget", "--budget"),
        ):
            if arguments.get(k):
                args.extend([flag, str(arguments[k])])
        dep = arguments.get("depends")
        deps = coerce_depends_list(dep)
        if deps:
            args.extend(["--depends", ",".join(deps)])
        for p in coerce_path_list(arguments.get("path")):
            args.extend(["--path", p])
        for p in coerce_path_list(arguments.get("extras")):
            args.extend(["--extras", p])
        if arguments.get("list"):
            args.append("--list")
        if arguments.get("check"):
            args.append("--check")
        if arguments.get("from_impact") or arguments.get("from-impact"):
            args.append("--from-impact")
        return c.cmd_plan(args), {}
    if name == "apply":
        c.dry = bool(arguments.get("dry_run"))
        if arguments.get("step"):
            args.append(str(arguments["step"]))
        if arguments.get("force"):
            args.append("--force")
        if arguments.get("agent"):
            args.extend(["--agent", str(arguments["agent"])])
        return c.cmd_apply(args), {}
    if name == "verify":
        if arguments.get("step"):
            args.append(str(arguments["step"]))
        return c.cmd_verify(args), {}
    if name == "land":
        if arguments.get("commit"):
            return c.cmd_land(["--commit"]), {}
        return c.cmd_land([]), {}
    if name == "rollback":
        return c.cmd_rollback(["last"]), {}
    if name == "backup":
        return c.cmd_backup([]), {}
    if name == "restore":
        bid = str(arguments.get("id") or "")
        return c.cmd_restore([bid] if bid else []), {}
    if name == "claim":
        if arguments.get("agent"):
            args.extend(["--agent", str(arguments["agent"])])
        if arguments.get("step"):
            args.append(str(arguments["step"]))
        return c.cmd_claim(args), {}
    if name == "release":
        return c.cmd_release([]), {}
    if name == "audit":
        return c.cmd_audit([]), {}
    if name == "baseline":
        return c.cmd_baseline([]), {}
    if name == "repro":
        return c.cmd_repro([]), {}
    if name == "progress":
        return c.cmd_progress([]), {}
    if name == "digest":
        return c.cmd_digest([]), {}
    if name == "why":
        if arguments.get("step"):
            args.append(str(arguments["step"]))
        return c.cmd_why(args), {}
    if name == "impact":
        if arguments.get("symbol"):
            args.extend(["--symbol", str(arguments["symbol"])])
        if arguments.get("files"):
            args.append("--files")
        return c.cmd_impact(args), {}
    if name == "index":
        return c.cmd_index([]), {}
    if name == "edges":
        return c.cmd_edges([]), {}
    if name == "scan":
        return c.cmd_scan([]), {}
    if name == "fuzz":
        return c.cmd_fuzz([]), {}
    if name == "sbom":
        return c.cmd_sbom([]), {}
    if name == "boundaries":
        return c.cmd_boundaries([]), {}
    if name == "fleet":
        act = []
        if arguments.get("action"):
            act.append(str(arguments["action"]))
        return c.cmd_fleet(act), {}
    if name == "export":
        return c.cmd_export([str(arguments.get("kind") or "batch")]), {}
    if name == "recipe":
        act = [str(arguments.get("action") or "list")]
        if arguments.get("id"):
            act.append(str(arguments["id"]))
        for k, flag in (
            ("verify", "--verify"),
            ("from", "--from"),
            ("to", "--to"),
            ("goal", "--goal"),
            ("profile", "--profile"),
        ):
            if arguments.get(k):
                act.extend([flag, str(arguments[k])])
        for p in coerce_path_list(arguments.get("path")):
            act.extend(["--path", p])
        steps = arguments.get("steps")
        if isinstance(steps, list) and str(arguments.get("id") or "") == "feature-campaign":
            for row in steps:
                if not isinstance(row, dict):
                    continue
                sid = str(row.get("id") or "")
                path = ",".join(coerce_path_list(row.get("path")))
                ver = str(row.get("verify") or "")
                act.extend(["--step", f"{sid}:{path}:{ver}"])
                deps = coerce_depends_list(row.get("depends"))
                for d in deps:
                    act.extend(["--depends", f"{sid}:{d}"])
                if row.get("want"):
                    act.extend(["--want", str(row["want"])])
        elif arguments.get("depends"):
            deps = coerce_depends_list(arguments["depends"])
            if deps:
                act.extend(["--depends", ",".join(deps)])
        return c.cmd_recipe(act), {}
    if name == "packs":
        return c.cmd_packs([]), {}
    if name == "harvest":
        return _call_farm("harvest", arguments, root)
    if name == "harvest_stat":
        return _call_farm("stat", arguments, root)
    if name == "doctor":
        return c.cmd_doctor(["--verbose"] if arguments.get("verbose") else []), {}
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
                "serverInfo": {
                    "name": "rfg",
                    "version": __version__,
                    "home": str(Path(__file__).resolve().parent.parent),
                },
            },
        }
    if method == "tools/list":
        listed = TOOLS if os.environ.get("RFG_MCP_ALL") == "1" else [t for t in TOOLS if t["name"] in CORE_TOOLS]
        tools = []
        for t in listed:
            schema = SCHEMAS.get(t["name"]) or {"type": "object", "properties": {}}
            props = dict(schema.get("properties") or {})
            if "root" not in props:
                props = {"root": _ROOT, **props}
            tools.append(
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": {**schema, "type": "object", "properties": props},
                }
            )
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools, "server": {"name": "rfg", "version": __version__}, "serverVersion": __version__}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        # capture stdout from CLI emit
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        os.environ.setdefault("RFG_AGENT", "agent")
        try:
            with redirect_stdout(buf):
                code, _ = call_tool(name, arguments, root)
            text = buf.getvalue()
        except ValueError as e:
            msg = str(e)
            if "traversal" not in msg.lower() and not msg.startswith("unsupported"):
                raise
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": msg}],
                    "isError": True,
                    "exitCode": 4,
                },
            }
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
    os.environ.setdefault("RFG_AGENT", "agent")
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
