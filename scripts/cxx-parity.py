#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CXX = ROOT / "cxx" / "rfg"

# Honest boundary: cxx/rfg is the rename core, not feature parity.
# Covered verbs behave identically; python-only features stay exit-4-free
# by simply not existing in cxx (no silent divergence).
BOUNDARY = {
    "covered": ["init", "plan", "next", "context", "tick", "apply", "verify-basic", "land-basic", "progress", "claim", "rollback"],
    "python_only": [
        "land-gate (rm.verify suite gate before copy)",
        "cross-verify (dependents + path overlap on verify)",
        "output budgets (--max-chars/--show-risk, token_estimate)",
        "scan --parse/SARIF findings",
        "fleet summary compact JSON",
        "perf delta in progress",
    ],
}


def py(*args):
    r = subprocess.run(
        [sys.executable, str(ROOT / "rfg.py"), "--root", str(ROOT), "--format", "json", *args],
        capture_output=True,
        text=True,
    )
    return json.loads(r.stdout)


def cxx(*args):
    r = subprocess.run(
        [str(CXX), "--root", str(ROOT), "--format", "json", *args],
        capture_output=True,
        text=True,
    )
    if not r.stdout.strip():
        raise SystemExit(r.stderr or "cxx empty stdout")
    return json.loads(r.stdout)


def main() -> int:
    if "--boundary" in sys.argv:
        print(json.dumps(BOUNDARY, indent=2))
        return 0
    if not CXX.is_file():
        print("missing cxx/rfg", file=sys.stderr)
        return 2
    pn, cn = py("next")["data"], cxx("next")["data"]
    if pn.get("next") != cn.get("next") or pn.get("id") != cn.get("id"):
        print(f"next mismatch python={pn.get('id')!r} cxx={cn.get('id')!r}", file=sys.stderr)
        return 2
    pp, cp = py("progress")["data"], cxx("progress")["data"]
    if pp.get("next") != cp.get("next"):
        print(f"progress next mismatch python={pp.get('next')!r} cxx={cp.get('next')!r}", file=sys.stderr)
        return 2
    pc, cc = py("context")["data"], cxx("context")["data"]
    if pc.get("id") != cc.get("id"):
        print(f"context id mismatch python={pc.get('id')!r} cxx={cc.get('id')!r}", file=sys.stderr)
        return 2
    if pc.get("tick") != cc.get("tick"):
        print(f"tick mismatch python={pc.get('tick')!r} cxx={cc.get('tick')!r}", file=sys.stderr)
        return 2
    print(f"ok next={pn.get('id')!r} tick={pc.get('tick')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
