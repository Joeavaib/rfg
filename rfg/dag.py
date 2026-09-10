from __future__ import annotations

from rfg.types import Roadmap, State, Step


def compute(rm: Roadmap, st: State) -> dict:
    applied = set(st.applied)
    verified = set(st.verified)
    failed = set(st.failed)
    done = applied | verified
    steps = []
    nxt = None
    for s in rm.steps:
        blocked = any(d not in done for d in s.depends_on)
        if s.id in failed:
            status = "failed"
        elif s.id in verified:
            status = "verified"
        elif s.id in applied:
            status = "applied"
        elif blocked:
            status = "blocked"
        else:
            status = "ready"
            if nxt is None:
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


def next_id(rm: Roadmap, st: State) -> str:
    n = compute(rm, st)["next"]
    return n or ""


def step_by_id(rm: Roadmap, sid: str) -> Step | None:
    for s in rm.steps:
        if s.id == sid:
            return s
    return None


def mark_applied(st: State, sid: str) -> None:
    if sid not in st.applied:
        st.applied.append(sid)
    st.failed = [x for x in st.failed if x != sid]
