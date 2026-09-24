from __future__ import annotations

"""One-call session resume (RES-A).

Single source for `rfg resume`, `rfg status --resume`, the MCP `resume`
verb and the `.rfg/last-stand.md` handoff (RES-B reuses the payload).
"""

from datetime import datetime, timezone
from pathlib import Path


def _short(sha: str) -> str:
    return (sha or "")[:7]


def _verify_time(root: str | Path, step_id: str) -> str:
    if not step_id:
        return ""
    for name in (f"{step_id}.log",):
        p = Path(root) / ".rfg" / "verify" / name
        try:
            if p.is_file():
                ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                return ts.isoformat()
        except OSError:
            continue
    return ""


def _git_head(root: str | Path) -> str:
    try:
        from rfg import gitops as _g

        if not _g.is_repo(root):
            return ""
        return _short(_g.head(root))
    except Exception:
        return ""


def _git_dirty(root: str | Path) -> list[str]:
    try:
        from rfg import gitops as _g

        return sorted(_g.dirty_tracked_files(root))
    except Exception:
        return []


def _worktree_drift(root: str | Path, state) -> dict:
    """Root vs worktree drift (RES-A wording: worktree-drift, not git-dirty).

    git-dirty = uncommitted tracked files at root.
    worktree-drift = root content differs from .rfg/worktree content.
    """
    from rfg import gitops as _g

    raw = (getattr(state, "worktree", "") or "").strip()
    if raw:
        wt = Path(raw)
        if not wt.is_dir():
            return {"drift": False, "files": []}
    else:
        try:
            wt = _g.worktree_path(root)
        except Exception:
            return {"drift": False, "files": []}
        if not wt.is_dir():
            return {"drift": False, "files": []}
    try:
        root_p = Path(root).resolve()
        wt_p = Path(wt).resolve()
        if root_p == wt_p:
            return {"drift": False, "files": []}
        root_dirty = set(_g.changed_rels(root_p))
        wt_dirty = set(_g.changed_rels(wt_p))
        files: set[str] = set(root_dirty) | set(wt_dirty)
        # content comparison for files present on both sides (cheap, bounded)
        candidates = sorted(files)[:50]
        for rel in list(candidates):
            try:
                a = root_p / rel
                b = wt_p / rel
                if a.is_file() and b.is_file() and a.read_bytes() == b.read_bytes():
                    files.discard(rel)
            except OSError:
                continue
        # worktree HEAD vs root HEAD also counts as drift
        try:
            if _g.is_repo(root_p) and _g.is_repo(wt_p):
                if _g.has_head(root_p) and _g.has_head(wt_p):
                    if _g.head(root_p) != _g.head(wt_p):
                        files.add(".rfg/worktree@HEAD")
        except Exception:
            pass
        return {"drift": bool(files), "files": sorted(files)[:20]}
    except Exception:
        return {"drift": False, "files": []}


def report(root: str | Path, rm, state) -> dict:
    from rfg import dag as _dag
    from rfg.types import step_paths as _paths
    from rfg.types import step_want as _want
    from rfg.types import step_observation as _obs

    snap = _dag.compute(rm, state)
    steps = snap.get("steps") or []
    total = len(steps)
    verified_ids = [s.get("id") for s in steps if s.get("status") == "verified"]
    ready_ids = [s.get("id") for s in steps if s.get("status") in ("ready", "claimed", "in_progress")]
    last_verified = verified_ids[-1] if verified_ids else ""
    # state.verified order is the source of truth when snap order differs
    try:
        if getattr(state, "verified", None):
            last_verified = list(state.verified)[-1]
    except Exception:
        pass
    nxt = snap.get("next") or ""
    nxt_step = _dag.step_by_id(rm, nxt) if nxt else None
    if nxt_step is not None:
        next_block: dict = {
            "id": nxt_step.id,
            "want": _want(nxt_step),
            "verify": _obs(nxt_step, rm.verify),
            "path": _paths(nxt_step),
        }
    else:
        next_block = {"id": None, "want": "", "verify": rm.verify if getattr(rm, "verify", "") else "", "path": []}
    cp = getattr(state, "last_checkpoint", None)
    if cp is not None:
        checkpoint = {
            "step": getattr(cp, "step_id", ""),
            "commit": _short(getattr(cp, "commit", "") or ""),
            "time": getattr(cp, "created_at", "") or "",
        }
    else:
        checkpoint = {"step": "", "commit": "", "time": ""}
    drift = _worktree_drift(root, state)
    dirty = _git_dirty(root)
    try:
        from rfg import progress as _progress

        pending = _progress.pending_land(root, rm, state)
    except Exception:
        pending = {"steps": [], "dirty": dirty}
    return {
        "goal": (getattr(getattr(rm, "goal", None), "statement", "") or "")[:300],
        "counts": {"total": total, "verified": len(verified_ids), "ready": len(ready_ids)},
        "last_verified": {"step": last_verified, "verify_time": _verify_time(root, last_verified)},
        "next": next_block,
        "ready": ready_ids[:8],
        "git": {"head": _git_head(root), "dirty": dirty},
        "git_dirty": dirty,
        "worktree": drift,
        "worktree_drift": drift.get("drift", False),
        "worktree_files": drift.get("files", []),
        "checkpoint": checkpoint,
        "pending_land": pending,
        "resume_command": "python3 rfg.py resume --format json",
    }


def render_text(rep: dict) -> str:
    lines = [
        f"goal: {rep.get('goal', '')}",
        f"counts: total={(rep.get('counts') or {}).get('total', 0)} "
        f"verified={(rep.get('counts') or {}).get('verified', 0)} "
        f"ready={(rep.get('counts') or {}).get('ready', 0)}",
        f"last_verified: {(rep.get('last_verified') or {}).get('step', '')} "
        f"@ {(rep.get('last_verified') or {}).get('verify_time', '')}",
        f"next: {(rep.get('next') or {}).get('id', '')} | {(rep.get('next') or {}).get('want', '')[:120]}",
        f"git: head={(rep.get('git') or {}).get('head', '')} dirty={','.join((rep.get('git') or {}).get('dirty', [])[:10]) or 'clean'}",
        f"worktree_drift: {rep.get('worktree_drift')} files={','.join((rep.get('worktree_files') or [])[:10])}",
        f"checkpoint: {(rep.get('checkpoint') or {}).get('step', '')} "
        f"{(rep.get('checkpoint') or {}).get('commit', '')} {(rep.get('checkpoint') or {}).get('time', '')}",
        f"resume: {rep.get('resume_command', '')}",
    ]
    return "\n".join(lines) + "\n"


def write_last_stand(root: str | Path, rm=None, state=None) -> dict:
    """Write `.rfg/last-stand.md` (RES-B): <30 lines, human-readable.

    Best-effort, never raises: a missing handoff must not break verify/land.
    Returns {"path": str, "lines": int} or {} when the store is absent.
    """
    try:
        from rfg.store import Store as _Store

        st = _Store(root)
        if rm is None or state is None:
            try:
                rm = st.load_roadmap()
                state = st.load_state()
            except FileNotFoundError:
                return {}
        rep = report(root, rm, state)
        now = datetime.now(timezone.utc).isoformat()
        last_v = rep.get("last_verified") or {}
        nxt = rep.get("next") or {}
        git = rep.get("git") or {}
        cp = rep.get("checkpoint") or {}
        dirty = ",".join((git.get("dirty") or [])[:10]) or "clean"
        lines = [
            "# rfg last stand (auto-generated, do not hand-edit)",
            f"date: {now}",
            f"goal: {rep.get('goal', '')}",
            f"counts: total={rep['counts']['total']} verified={rep['counts']['verified']} ready={rep['counts']['ready']}",
            f"last_green: {last_v.get('step', '')} @ {last_v.get('verify_time', '')}",
            f"next: {nxt.get('id', '')}",
            f"next_want: {(nxt.get('want', '') or '')[:160]}",
            f"next_verify: {nxt.get('verify', '')}",
            f"git_head: {git.get('head', '')}",
            f"git_dirty: {dirty}",
            f"worktree_drift: {rep.get('worktree_drift')} ({','.join((rep.get('worktree_files') or [])[:8])})",
            f"checkpoint: {cp.get('step', '')} {cp.get('commit', '')} {cp.get('time', '')}",
            f"resume: {rep.get('resume_command', '')}",
        ]
        # hard cap: <30 lines by construction (13 here)
        text = "\n".join(lines[:29]) + "\n"
        p = Path(root) / ".rfg" / "last-stand.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return {"path": str(p), "lines": len(lines)}
    except Exception:
        return {}
