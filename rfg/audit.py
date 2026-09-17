from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

NAME = "audit.jsonl"


def path(root: str | Path) -> Path:
    return Path(root) / ".rfg" / NAME


def record(root: str | Path, event: str, **fields) -> None:
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read(root: str | Path, limit: int = 50) -> list[dict]:
    p = path(root)
    if not p.is_file():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
