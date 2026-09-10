"""Telemetry is opt-in and local-only. Never opens a network socket."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def enabled() -> bool:
    v = os.environ.get("RFG_TELEMETRY", "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def offline() -> bool:
    v = os.environ.get("RFG_OFFLINE", "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def record(root: str | Path, event: str, payload: dict | None = None) -> None:
    if not enabled() or offline():
        return
    path = Path(root) / ".rfg" / "telemetry.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "payload": payload or {},
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
