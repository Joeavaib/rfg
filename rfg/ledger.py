"""Test ledger (R4): append-only events, derived counters, map view.

Buchführung statt Ignorieren (SCOUT-D): verify/test-added events land
append-only in `.rfg/ledger-events.jsonl` (ignoriert, deriviert). Counter
(passes/fails) werden ausschließlich aus verify-Events abgeleitet —
Agent-Input landet nur in `note` und nie in Schwellen. Tombstone/Drop
ist geparkt (I3): stale_functions bleiben warn-only (progress.exceptions
+ doctor.ledger_stale) bis ein `test-dropped`/`tombstone`-Event die Map
bereinigt. Nichts löscht jsonl-Zeilen.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LEDGER_NAME = "ledger-events.jsonl"


def ledger_path(root: str | Path) -> Path:
    return Path(root) / ".rfg" / LEDGER_NAME


def _append(root: str | Path, row: dict) -> None:
    p = ledger_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now(timezone.utc).isoformat(), **row}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def record_test_added(root: str | Path, function: str, test_id: str, step: str, verify_cmd: str) -> None:
    """A test now covers `function`. Only fixed fields are stored."""
    _append(
        root,
        {
            "kind": "test-added",
            "function": str(function or ""),
            "test": str(test_id or ""),
            "step": str(step or ""),
            "verify_cmd": str(verify_cmd or ""),
        },
    )


def record_verify_event(
    root: str | Path,
    test_id: str,
    step: str,
    code: int,
    log: str,
    elapsed_ms: float | None = None,
    **ignored,
) -> None:
    """A verify ran for `test_id`. Extra kwargs (e.g. passes=999 from an
    agent) are dropped on purpose: counters are derived, never written.
    `elapsed_ms` (D4) is informational only, never used for decisions."""
    row: dict = {
        "kind": "verify",
        "test": str(test_id or ""),
        "step": str(step or ""),
        "exit": int(code),
        "log": str(log or ""),
    }
    if elapsed_ms is not None:
        try:
            row["elapsed_ms"] = float(elapsed_ms)
        except (TypeError, ValueError):
            pass
    _append(root, row)


def read_events(root: str | Path) -> list[dict]:
    p = ledger_path(root)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("kind") in ("test-added", "verify"):
            rows.append(row)
    return rows


def counters(root: str | Path) -> dict[str, dict[str, int]]:
    """Derived {test_id: {passes, fails}} from verify events only."""
    out: dict[str, dict[str, int]] = {}
    for row in read_events(root):
        if row.get("kind") != "verify" or not row.get("test"):
            continue
        entry = out.setdefault(str(row["test"]), {"passes": 0, "fails": 0})
        if int(row.get("exit", 1)) == 0:
            entry["passes"] += 1
        else:
            entry["fails"] += 1
    return out


def map_view(root: str | Path) -> dict[str, list[str]]:
    """{function: [test_ids]} from test-added events."""
    view: dict[str, list[str]] = {}
    for row in read_events(root):
        if row.get("kind") != "test-added" or not row.get("function") or not row.get("test"):
            continue
        tests = view.setdefault(str(row["function"]), [])
        if str(row["test"]) not in tests:
            tests.append(str(row["test"]))
    return view


def new_test_overlaps(root: str | Path, function: str, test_id: str) -> bool:
    """T1 trigger: True when `function` already has a *different* test."""
    known = map_view(root).get(str(function or ""), [])
    return bool(known) and str(test_id or "") not in known


def stale_functions(root: str | Path) -> list[str]:
    """Functions with >1 test needing human compare (review trigger).

    Tombstone design (parked I3): a later test-dropped event would remove
    a test from map_view so the function leaves this list. Until then
    stale is warn-only (progress.exceptions, doctor.ledger_stale).
    """
    return sorted(f for f, tests in map_view(root).items() if len(tests) > 1)
