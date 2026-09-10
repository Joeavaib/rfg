from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Replace:
    frm: str
    to: str
    paths: list[str] = field(default_factory=list)


@dataclass
class Step:
    id: str
    title: str = ""
    depends_on: list[str] = field(default_factory=list)
    replace: Replace | None = None
    verify: str = ""
    engine: str = ""
    diff_budget: int = 0
    edge: str = ""


@dataclass
class Hypothesis:
    id: str = "h1"
    statement: str = ""
    symbol: str = ""
    frm: str = ""
    to: str = ""


@dataclass
class Roadmap:
    version: int = 0
    id: str = "roadmap-1"
    hypothesis: Hypothesis = field(default_factory=Hypothesis)
    verify: str = ""
    steps: list[Step] = field(default_factory=list)


@dataclass
class Checkpoint:
    id: str
    step_id: str
    commit: str
    worktree: str = ""
    created_at: str = ""


@dataclass
class State:
    applied: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    worktree: str = ""
    last_checkpoint: Checkpoint | None = None
    checkpoints: list[Checkpoint] = field(default_factory=list)


def checkpoint_from_dict(d: dict | None) -> Checkpoint | None:
    if not d:
        return None
    return Checkpoint(
        id=d.get("id", ""),
        step_id=d.get("step_id", ""),
        commit=d.get("commit", ""),
        worktree=d.get("worktree", ""),
        created_at=d.get("created_at", ""),
    )


def state_from_dict(d: dict) -> State:
    cps = [checkpoint_from_dict(x) for x in d.get("checkpoints") or []]
    return State(
        applied=list(d.get("applied") or []),
        verified=list(d.get("verified") or []),
        failed=list(d.get("failed") or []),
        worktree=d.get("worktree") or "",
        last_checkpoint=checkpoint_from_dict(d.get("last_checkpoint")),
        checkpoints=[c for c in cps if c],
    )


def checkpoint_to_dict(c: Checkpoint) -> dict[str, Any]:
    return asdict(c)


def state_to_dict(s: State) -> dict[str, Any]:
    return {
        "applied": s.applied,
        "verified": s.verified,
        "failed": s.failed,
        "worktree": s.worktree,
        "last_checkpoint": checkpoint_to_dict(s.last_checkpoint) if s.last_checkpoint else None,
        "checkpoints": [checkpoint_to_dict(c) for c in s.checkpoints],
    }
