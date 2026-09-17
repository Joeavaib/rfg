#!/usr/bin/env python3
"""Stop: if a step is applied but not verified, keep the agent on verify."""
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
    if ev.get("stopHookActive"):
        print(json.dumps({"decision": "allow"}))
        return 0
    if not (ROOT / ".rfg" / "roadmap.yaml").is_file():
        print(json.dumps({"decision": "allow"}))
        return 0
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from rfg.store import Store
    except Exception:
        print(json.dumps({"decision": "allow"}))
        return 0
    try:
        st = Store(str(ROOT))
        state = st.load_state()
    except Exception:
        print(json.dumps({"decision": "allow"}))
        return 0
    pending = [s for s in state.applied if s not in state.verified and s not in state.failed]
    if not pending:
        print(json.dumps({"decision": "allow"}))
        return 0
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": f"rfg: applied {pending[-1]} is not verified — run rfg verify or rfg tick",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
