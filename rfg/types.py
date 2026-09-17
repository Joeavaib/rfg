from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any


def coerce_path_list(value: Any) -> list[str]:
    """Hosts often stringify JSON arrays as one path; split those into files."""
    if value is None or value is False:
        return []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for v in value:
            out.extend(coerce_path_list(v))
        return [p for p in out if p]
    s = str(value).strip()
    if not s:
        return []
    if s[0] in "\"'" and len(s) >= 2 and s[-1] == s[0]:
        inner = s[1:-1]
        if inner.startswith("["):
            s = inner
    if s.startswith("["):
        parsed = None
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            try:
                import ast

                parsed = ast.literal_eval(s)
            except (ValueError, SyntaxError):
                parsed = None
        if isinstance(parsed, list):
            return coerce_path_list(parsed)
        # unparseable bracket string (e.g. "[A, B]"): strip outer brackets so
        # no broken "[A" / "B]" entries survive; fall through to comma split.
        if s.endswith("]"):
            s = s[1:-1].strip()
            if not s:
                return []
    if "," in s:
        parts = [p.strip().strip("[]").strip('"').strip("'").strip() for p in s.split(",") if p.strip().strip("[]\"' ")]
        if len(parts) > 1 and not any(p.startswith("[") for p in parts):
            return parts
        if len(parts) == 1:
            return parts
    if s.startswith("[") or s.endswith("]") or '"' in s or "'" in s:
        cleaned = s.strip().strip("[]").strip('"').strip("'").strip()
        return [cleaned] if cleaned else []
    return [s]


def coerce_depends_list(value: Any) -> list[str]:
    """Depends IDs coerce like paths: JSON-array strings, lists, comma strings.

    Hosts (MCP/JSON) often stringify arrays to '["G02", "G03"]'; without
    coercion that becomes one broken dep '["G02"' instead of two deps.
    """
    return coerce_path_list(value)


def expand_dir_paths(root: str | Any, paths: list[str] | None) -> list[str]:
    """Expand directory entries in path[] to contained source files (mapping steps)."""
    from pathlib import Path

    root_p = Path(root)
    out: list[str] = []
    for p in paths or []:
        if not p or p.startswith("/") or ".." in Path(p).parts:
            continue
        full = root_p / p
        if full.is_dir():
            for f in sorted(full.rglob("*")):
                if not f.is_file():
                    continue
                rel = f.relative_to(root_p).as_posix()
                parts = Path(rel).parts
                if any(x in {".git", ".rfg", "__pycache__", "node_modules", ".venv", "target", "build", "dist"} for x in parts):
                    continue
                if f.suffix.lower() in {".pyc", ".pyo", ".o", ".so"}:
                    continue
                out.append(rel)
        else:
            out.append(p)
    # dedup preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


@dataclass
class Replace:
    from_pat: str
    to: str
    paths: list[str] = field(default_factory=list)


ORACLE_KINDS = ("test", "perf", "debug", "security")
PROFILES = ("refactor", "feature", "perf", "debug", "security")
STOP_ENGINES = ("manual", "implement", "survey")
CONTRACT_ENGINES = ("manual", "implement", "scaffold", "survey")
MECHANICAL_ENGINES = ("replace", "", "ast-grep", "scaffold")
BARE_SUITE = ("pytest", "pytest -q", "go test ./...", "make", "npm test", "cargo test", "python3 -m unittest")


def default_engine(engine: str, *, from_pat: str = "") -> str:
    """Empty engine is implement unless a replace from-pattern exists."""
    e = engine or ""
    if e == "notes":
        return "survey"
    if e:
        return e
    return "replace" if from_pat else "implement"


def is_implement(engine: str) -> bool:
    return (engine or "") == "implement"


def is_stop_engine(engine: str) -> bool:
    return (engine or "") in STOP_ENGINES


def is_contract(engine: str) -> bool:
    return (engine or "") in CONTRACT_ENGINES


def is_mechanical(engine: str) -> bool:
    return (engine or "replace") in MECHANICAL_ENGINES


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
    oracle: str = "test"
    goal: str = ""
    want: str = ""
    paths: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)


def step_paths(step: Step) -> list[str]:
    if step.paths:
        return list(step.paths)
    if step.replace:
        return list(step.replace.paths)
    return []


def step_allowed_paths(step: Step) -> list[str]:
    """Declared paths plus explicit extras (e.g. rfgfeedback.md).

    path[] is the code scope; extras is the allowlist for side artefacts
    that should be staged without polluting path[].
    """
    out = list(step_paths(step))
    for p in list(step.extras or []):
        if p and p not in out:
            out.append(p)
    return out


def step_want(step: Step) -> str:
    return step.want or step.goal or step.title


def step_observation(step: Step, fallback: str = "") -> str:
    """Per-step oracle. Contract engines do not inherit the roadmap suite."""
    if step.verify:
        return step.verify
    if is_contract(step.engine):
        return ""
    return fallback


@dataclass
class Hypothesis:
    id: str = "h1"
    statement: str = ""
    symbol: str = ""
    from_pat: str = ""
    to: str = ""


@dataclass
class Goal:
    id: str = "g1"
    statement: str = ""
    profile: str = "refactor"
    acceptance: list[str] = field(default_factory=list)


@dataclass
class Oracle:
    kind: str = "test"
    command: str = ""
    max_ms: float = 0.0
    max_ratio: float = 0.0


@dataclass
class Budget:
    max_applies: int = 0  # 0 = unlimited


@dataclass
class Roadmap:
    version: int = 0
    id: str = "roadmap-1"
    hypothesis: Hypothesis = field(default_factory=Hypothesis)
    goal: Goal = field(default_factory=Goal)
    verify: str = ""
    oracles: list[Oracle] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
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
    claim_step: str = ""
    claim_agent: str = ""
    applies_used: int = 0
    started: list[str] = field(default_factory=list)


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
        claim_step=d.get("claim_step") or "",
        claim_agent=d.get("claim_agent") or "",
        applies_used=int(d.get("applies_used") or 0),
        started=list(d.get("started") or []),
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
        "claim_step": s.claim_step,
        "claim_agent": s.claim_agent,
        "applies_used": s.applies_used,
        "started": s.started,
    }
