#!/usr/bin/env python3
"""Start rfg MCP. Resolves the package via RFG_HOME, then this checkout, then cwd."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _home() -> Path:
    try:
        from rfg.home import resolve_home

        return resolve_home(here=Path(__file__), depths=(2, 1))
    except Exception:
        pass
    # bootstrap fallback: package not importable yet, same table, local check
    env = os.environ.get("RFG_HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    for cand in (here.parent.parent, here.parent, Path.cwd()):
        if (cand / "rfg" / "__main__.py").is_file() or (cand / "rfg.py").is_file():
            return cand
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        if (p / "rfg" / "__main__.py").is_file():
            return p
    return cwd


def main() -> int:
    home = _home()
    os.environ.setdefault("RFG_HOME", str(home))
    os.environ.setdefault("RFG_AGENT", "agent")
    if str(home) not in sys.path:
        sys.path.insert(0, str(home))
    from rfg.mcp import serve

    serve(root=os.environ.get("RFG_ROOT") or os.getcwd())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
