#!/usr/bin/env python3
"""PreToolUse: deny writes outside the current rfg step.path (replace engine only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path.cwd()


def main() -> int:
    raw = sys.stdin.read()
    try:
        ev = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        print(json.dumps({"decision": "allow"}))
        return 0
    tool = str(ev.get("toolName") or ev.get("tool_name") or "")
    if tool not in {"Write", "StrReplace", "search_replace", "write"}:
        print(json.dumps({"decision": "allow"}))
        return 0
    rfg = ROOT / ".rfg" / "roadmap.yaml"
    if not rfg.is_file():
        print(json.dumps({"decision": "allow"}))
        return 0
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from rfg.store import Store
        from rfg import dag
        from rfg.types import step_paths
    except Exception:
        print(json.dumps({"decision": "allow"}))
        return 0
    try:
        st = Store(str(ROOT))
        rm = st.load_roadmap()
        state = st.load_state()
        sid = dag.next_id(rm, state)
        step = dag.step_by_id(rm, sid) if sid else None
    except Exception:
        print(json.dumps({"decision": "allow"}))
        return 0
    if step is None or (step.engine or "replace") == "manual":
        print(json.dumps({"decision": "allow"}))
        return 0
    paths = {p for p in step_paths(step)}
    if not paths:
        print(json.dumps({"decision": "allow"}))
        return 0
    inp = ev.get("toolInput") or ev.get("tool_input") or {}
    target = str(inp.get("path") or inp.get("file_path") or inp.get("target_file") or "")
    if not target:
        print(json.dumps({"decision": "allow"}))
        return 0
    rel = target
    try:
        rel = str(Path(target).resolve().relative_to(ROOT.resolve()).as_posix())
    except Exception:
        rel = Path(target).as_posix()
    if rel in paths or any(rel.endswith("/" + p) or rel.endswith(p) for p in paths):
        print(json.dumps({"decision": "allow"}))
        return 0
    print(
        json.dumps(
            {
                "decision": "deny",
                "reason": f"rfg step {step.id} only allows {sorted(paths)}; use rfg tick/context or engine manual",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
