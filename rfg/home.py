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
