"""Locate the rfg package (install vs checkout)."""

from __future__ import annotations

import os
from pathlib import Path


def find_rfg_home() -> Path:
    env = os.environ.get("RFG_HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    import rfg

    return Path(rfg.__file__).resolve().parent.parent


def _looks_like_home(cand: Path) -> bool:
    return (cand / "rfg" / "__main__.py").is_file() or (cand / "rfg.py").is_file()


def resolve_home(here: Path | None = None, depths: tuple[int, ...] = (2, 1)) -> Path:
    """Single home-resolution logic for all MCP launchers (V0.2).

    `RFG_HOME` wins; otherwise walk `depths` parents up from the
    launcher file (`here`), then walk up from cwd. Launchers delegate
    here whenever the package is importable and keep only a dumb
    bootstrap fallback for first import.
    """
    env = os.environ.get("RFG_HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if here is not None:
        base = Path(here).resolve()
        for d in depths:
            cand = base
            for _ in range(d):
                cand = cand.parent
            if _looks_like_home(cand):
                return cand
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        if (p / "rfg" / "__main__.py").is_file():
            return p
    return cwd
