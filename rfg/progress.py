from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rfg import accept, dag, gitops
from rfg.types import Roadmap, State, is_implement, is_mechanical


def apply_dirty(root: str, rm: Roadmap, state: State) -> bool:
    """True only when a mechanical apply is in flight and tracked files differ.

    Untracked files (greenfield init/plan/implement) are not dirty.
    """
    pending = False
    verified = set(state.verified)
    applied = set(state.applied)
    for s in rm.steps:
        if s.id in applied and s.id not in verified and is_mechanical(s.engine):
            pending = True
            break
    if not pending:
        return False
    return gitops.is_repo(root) and gitops.dirty_tracked(root)


def _by_epic_counts(rm: Roadmap, steps: list[dict]) -> dict:
    """Gruppierte Counts je Epic-Praefix (GS3, warn-first, kein Gate).

    Reine String-Praefixe via :mod:`rfg.scope` (kein Schema-Feld):
    ``{epic: {"total", "verified", "ready"}}``. Additiv — aendert keine
    Exit-Semantik.
    """
    from rfg.scope import epic_of as _epic_of

    status_by_id = {s.get("id"): s.get("status") for s in steps or []}
    out: dict[str, dict[str, int]] = {}
    for s in rm.steps or []:
        e = _epic_of(s.id)
        if not e:
            continue
        g = out.setdefault(e, {"total": 0, "verified": 0, "ready": 0})
        g["total"] += 1
        st = status_by_id.get(s.id, "")
        if st == "verified":
            g["verified"] += 1
        if st in ("ready", "claimed", "in_progress"):
            g["ready"] += 1
    return out


def report(root: str, rm: Roadmap, state: State) -> dict:
    snap = dag.compute(rm, state)
    snap["dirty"] = apply_dirty(root, rm, state)
    steps = snap["steps"]
    n = len(steps)
    verified = sum(1 for s in steps if s["status"] == "verified")
    failed = [s["id"] for s in steps if s["status"] == "failed"]
    blocked = [s["id"] for s in steps if s["status"] == "blocked"]
    ready = [s["id"] for s in steps if s["status"] == "ready"]
    in_progress = [s["id"] for s in steps if s["status"] == "in_progress"]
    claimed = [s["id"] for s in steps if s["status"] == "claimed"]
    pending = [s["id"] for s in steps if s["status"] == "implemented"]
    applied_ids = set(state.applied)
    implemented = [
        s.id
        for s in rm.steps
        if is_implement(s.engine) and s.id in applied_ids and s.id not in state.verified
    ]
    exceptions: list[dict] = []
    for sid in failed:
        exceptions.append({"kind": "failed", "step": sid, "detail": "verify failed"})
    if snap.get("dirty"):
        exceptions.append({"kind": "dirty", "step": "", "detail": "mechanical apply left tracked files dirty"})
    if rm.budget.max_applies and state.applies_used >= rm.budget.max_applies:
        exceptions.append(
            {
                "kind": "budget",
                "step": "",
                "detail": f"apply budget {rm.budget.max_applies} exhausted ({state.applies_used})",
            }
        )
    if state.claim_step:
        exceptions.append(
            {
                "kind": "claim",
                "step": state.claim_step,
                "detail": f"held by {state.claim_agent or 'unknown'}",
            }
        )
    acc_code, acc_out, _acc = accept.run_all(root, rm)
    if acc_code != 0:
        exceptions.append({"kind": "acceptance", "step": "", "detail": (acc_out or "acceptance failed").strip()[:300]})
    by_epic = _by_epic_counts(rm, steps)
    from rfg import oracles as _oracles

    try:
        perf = _oracles.perf_delta(root)
    except Exception:
        perf = {"recorded": False}
    return {
        "goal": {
            "id": rm.goal.id,
            "statement": rm.goal.statement,
            "hypothesis": rm.hypothesis.statement,
            "profile": rm.goal.profile,
            "acceptance": list(rm.goal.acceptance),
            "acceptance_set": bool(rm.goal.acceptance),
            "acceptance_prose": accept.prose(rm),
            "acceptance_prose_note": "prose items are not executed; commands gate via acceptance",
        },
        "counts": {
            "total": n,
            "verified": verified,
            "failed": len(failed),
            "blocked": len(blocked),
            "ready": len(ready),
            "claimed": len(claimed),
            "in_progress": len(in_progress),
            "implemented": len(implemented),
            "pending_verify": len(pending),
        },
        "next": snap["next"],
        "ready": [s["id"] for s in steps if s["status"] in ("ready", "claimed", "in_progress")][:8],
        "by_epic": by_epic,
        "exceptions": exceptions,
        "perf": perf,
        "ok": not failed and not snap.get("dirty") and acc_code == 0,
    }


def write_digest(root: str, rm: Roadmap, state: State) -> dict:
    body = report(root, rm, state)
    logs = Path(root) / ".rfg" / "verify"
    body["verify_logs"] = {p.stem: str(p) for p in sorted(logs.glob("*.log"))} if logs.is_dir() else {}
    body["generated_at"] = datetime.now(timezone.utc).isoformat()
    body["roadmap_id"] = rm.id
    p = Path(root) / ".rfg" / "digest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    import json

    p.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    body["path"] = str(p)
    return body


def write_dashboard(root: str, rm, state) -> dict:
    """Static HTML snapshot. Not a server, not the paid read-dashboard pack."""
    import html as htmlmod
    import json
    from pathlib import Path

    data = report(root, rm, state)
    rows = "".join(
        f"<tr><td>{htmlmod.escape(e.get('kind',''))}</td>"
        f"<td>{htmlmod.escape(str(e.get('step','')))}</td>"
        f"<td>{htmlmod.escape(str(e.get('detail','')))}</td></tr>"
        for e in data.get("exceptions") or []
    ) or "<tr><td colspan=3>none</td></tr>"
    g = data.get("goal") or {}
    c = data.get("counts") or {}
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>rfg {htmlmod.escape(str(g.get('id','')))}</title>
<style>body{{font-family:sans-serif;max-width:40rem;margin:2rem auto}} table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ccc;padding:.3rem;text-align:left}}</style>
</head><body>
<h1>rfg snapshot</h1>
<p><strong>goal</strong> {htmlmod.escape(str(g.get('statement','')))} ({htmlmod.escape(str(g.get('profile','')))})</p>
<p>verified {c.get('verified',0)}/{c.get('total',0)} next {htmlmod.escape(str(data.get('next')))}</p>
<h2>exceptions</h2>
<table><thead><tr><th>kind</th><th>step</th><th>detail</th></tr></thead><tbody>{rows}</tbody></table>
<pre>{htmlmod.escape(json.dumps(data.get('counts'), indent=2))}</pre>
</body></html>
"""
    p = Path(root) / ".rfg" / "dashboard.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(page, encoding="utf-8")
    data["path"] = str(p)
    data["kind"] = "html-snapshot"
    return data
