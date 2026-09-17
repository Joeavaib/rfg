from __future__ import annotations

from rfg.types import Roadmap, State, Step, is_implement


def step_by_id(rm: Roadmap, sid: str) -> Step | None:
    for s in rm.steps:
        if s.id == sid:
            return s
    return None


def _dep_done(rm: Roadmap, st: State, dep_id: str) -> bool:
    dep = step_by_id(rm, dep_id)
    if dep is not None and is_implement(dep.engine):
        return dep_id in set(st.verified)
    return dep_id in set(st.applied) | set(st.verified)


def step_status(rm: Roadmap, st: State, s: Step) -> str:
    applied = set(st.applied)
    verified = set(st.verified)
    failed = set(st.failed)
    if s.id in failed:
        return "failed"
    if s.id in verified:
        return "verified"
    if s.id in applied:
        return "implemented" if is_implement(s.engine) else "applied"
    if any(not _dep_done(rm, st, d) for d in s.depends_on):
        return "blocked"
    if st.claim_step == s.id:
        if s.id in set(st.started):
            return "in_progress"
        return "claimed"
    return "ready"


def compute(rm: Roadmap, st: State) -> dict:
    steps = []
    nxt = None
    for s in rm.steps:
        status = step_status(rm, st, s)
        if status in ("ready", "claimed", "in_progress") and nxt is None:
            nxt = s.id
        item = {
            "id": s.id,
            "title": s.title,
            "status": status,
            "depends_on": s.depends_on,
        }
        if s.engine:
            item["engine"] = s.engine
        if s.edge:
            item["edge"] = s.edge
        if s.diff_budget:
            item["diff_budget"] = s.diff_budget
        if s.goal:
            item["goal"] = s.goal
        steps.append(item)
    last = st.last_checkpoint.id if st.last_checkpoint else None
    return {
        "roadmap_id": rm.id,
        "hypothesis": rm.hypothesis.statement,
        "next": nxt,
        "dirty": False,
        "worktree": st.worktree,
        "last_checkpoint": last,
        "steps": steps,
    }


def slim_plan(rm: Roadmap, st: State) -> dict:
    """plan payload: next + id/status/engine, not titles or goals."""
    snap = compute(rm, st)
    return {
        "next": snap["next"],
        "steps": [
            {k: s[k] for k in ("id", "status", "engine") if k in s and s[k]}
            for s in snap["steps"]
        ],
    }


def blocked_reason(rm: Roadmap, st: State) -> str:
    s = compute(rm, st)
    if s["next"]:
        return ""
    if st.failed:
        return "verify failed: " + ",".join(st.failed)
    if not rm.steps:
        return "no free step"
    leftover = [x for x in s["steps"] if x["status"] == "blocked"]
    if leftover:
        deps = leftover[0].get("depends_on") or []
        return "waiting on: " + ", ".join(deps)
    return "no free step"


def next_id(rm: Roadmap, st: State) -> str:
    n = compute(rm, st)["next"]
    return n or ""


def ready_ids(rm: Roadmap, st: State) -> list[str]:
    return [s["id"] for s in compute(rm, st)["steps"] if s["status"] in ("ready", "claimed", "in_progress")]


def _downstream_count(rm: Roadmap, sid: str) -> int:
    """Transitive dependents — critical-path weight, not just direct children."""
    seen: set[str] = set()
    stack = [sid]
    count = 0
    children: dict[str, list[str]] = {}
    for x in rm.steps:
        for d in x.depends_on:
            children.setdefault(d, []).append(x.id)
    visited: set[str] = set([sid])
    queue = list(children.get(sid, []))
    while queue:
        cur = queue.pop(0)
        if cur in visited:
            continue
        visited.add(cur)
        count += 1
        queue.extend(children.get(cur, []))
    return count


def recommend(rm: Roadmap, st: State) -> tuple[str, str]:
    ids = ready_ids(rm, st)
    if not ids:
        return "", ""
    if st.claim_step and st.claim_step in ids:
        return st.claim_step, "claimed"
    best = ids[0]
    best_score: tuple[int, int] | None = None
    for sid in ids:
        s = step_by_id(rm, sid)
        unlocks = _downstream_count(rm, sid)
        vlen = len((s.verify if s else "") or "")
        score = (-unlocks, vlen)
        if best_score is None or score < best_score:
            best, best_score = sid, score
    s = step_by_id(rm, best)
    unlocks = _downstream_count(rm, best)
    reason = "critical path" if unlocks else "smallest verify"
    return best, reason


def mark_applied(st: State, sid: str) -> None:
    if sid not in st.applied:
        st.applied.append(sid)
    st.failed = [x for x in st.failed if x != sid]
