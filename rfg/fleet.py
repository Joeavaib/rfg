"""Local multi-repo fleet. No cloud, no paid estate scheduler."""

from __future__ import annotations

from pathlib import Path

from rfg import dag
from rfg.progress import report
from rfg.store import Store
from rfg.yamlio import _split_kv, _unquote

OPEN_PACKS = (
    "loop",
    "oracles",
    "fleet-status",
    "batch-export",
    "sbom",
)
PAID_PACKS = (
    "estate-scheduler",
    "org-policy",
    "audit-saas",
    "read-dashboard",
)


def load_fleet(root: str | Path) -> list[dict]:
    root = Path(root)
    for cand in (root / ".rfg" / "fleet.yaml", root / "fleet.yaml"):
        if cand.is_file():
            return _parse_fleet(cand, root)
    return [{"name": root.name or "root", "path": str(root.resolve())}]


def _parse_fleet(path: Path, root: Path) -> list[dict]:
    repos: list[dict] = []
    in_repos = False
    cur: dict | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        trim = line.strip()
        if indent == 0 and trim.startswith("repos"):
            in_repos = True
            continue
        if not in_repos:
            continue
        if indent == 2 and trim.startswith("- "):
            if cur:
                repos.append(cur)
            cur = {"name": "", "path": ""}
            rest = trim[2:]
            kv = _split_kv(rest)
            if kv:
                cur[kv[0]] = _unquote(kv[1])
            continue
        if cur is None:
            continue
        kv = _split_kv(trim)
        if not kv:
            continue
        cur[kv[0]] = _unquote(kv[1])
    if cur:
        repos.append(cur)
    out = []
    for r in repos:
        p = Path(r.get("path") or "")
        if not p.is_absolute():
            p = (root / p).resolve()
        else:
            p = p.resolve()
        out.append({"name": r.get("name") or p.name, "path": str(p)})
    return out


def collect(root: str | Path) -> dict:
    rows = []
    exceptions = []
    for repo in load_fleet(root):
        p = repo["path"]
        st = Store(p)
        item = {"name": repo["name"], "path": p, "ok": False, "error": None, "progress": None}
        try:
            rm = st.load_roadmap()
            state = st.load_state()
            prog = report(p, rm, state)
            item["progress"] = prog
            item["ok"] = bool(prog.get("ok"))
            for ex in prog.get("exceptions") or []:
                exceptions.append({"repo": repo["name"], **ex})
        except FileNotFoundError as e:
            item["error"] = str(e)
            exceptions.append({"repo": repo["name"], "kind": "missing", "step": "", "detail": str(e)})
        rows.append(item)
    return {"repos": rows, "exceptions": exceptions, "ok": not exceptions}


def summary(root: str | Path) -> dict:
    """One compact row per repo: name/ok/next/verified/total/failed/ready.

    Read-only overview, no scheduler. Full progress dumps stay behind --full.
    """
    rows = []
    exceptions = []
    for repo in load_fleet(root):
        p = repo["path"]
        st = Store(p)
        row = {"name": repo["name"], "path": p, "ok": False, "next": None,
               "verified": 0, "total": 0, "failed": 0, "ready": 0, "error": None}
        try:
            rm = st.load_roadmap()
            state = st.load_state()
            snap = dag.compute(rm, state)
            counts = {}
            for s in snap.get("steps") or []:
                counts[s.get("status")] = counts.get(s.get("status"), 0) + 1
            row.update({
                "ok": not [s for s in (snap.get("steps") or []) if s.get("status") == "failed"],
                "next": snap.get("next"),
                "verified": counts.get("verified", 0),
                "total": len(snap.get("steps") or []),
                "failed": counts.get("failed", 0),
                "ready": counts.get("ready", 0) + counts.get("claimed", 0) + counts.get("in_progress", 0),
            })
        except FileNotFoundError as e:
            row["error"] = str(e)
            exceptions.append({"repo": repo["name"], "kind": "missing", "step": "", "detail": str(e)})
        rows.append(row)
    ok = not exceptions and all(r["ok"] for r in rows)
    return {"repos": rows, "exceptions": exceptions, "ok": ok,
            "totals": {"repos": len(rows),
                       "verified": sum(r["verified"] for r in rows),
                       "failed": sum(r["failed"] for r in rows),
                       "ready": sum(r["ready"] for r in rows)}}


def next_step(root: str | Path) -> dict:
    """First free step across fleet.yaml. One JSON {repo, step}."""
    for repo in load_fleet(root):
        p = repo["path"]
        st = Store(p)
        try:
            rm = st.load_roadmap()
            state = st.load_state()
        except FileNotFoundError:
            continue
        sid = dag.next_id(rm, state)
        if sid:
            return {"repo": repo["name"], "path": p, "step": sid}
    return {"repo": None, "path": "", "step": None}


def export_batch(root: str | Path) -> tuple[Path, str]:
    st = Store(root)
    rm = st.load_roadmap()
    lines = [
        f"name: rfg-{rm.id}",
        "description: exported from rfg (offline; not a live Sourcegraph campaign)",
        "changesetTemplate:",
        f"  title: {rm.goal.statement or rm.hypothesis.statement or rm.id}",
        "  branch: rfg/" + rm.id,
        "steps:",
    ]
    for s in rm.steps:
        run = "python3 rfg.py apply --format json"
        if s.id:
            run += " " + s.id
        lines.append(f"  - id: {s.id}")
        lines.append(f"    run: {run}")
        if s.verify:
            lines.append(f"    verify: {s.verify}")
    text = "\n".join(lines) + "\n"
    p = Path(root) / ".rfg" / "batch-changes.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p, text


def pack_info(name: str) -> tuple[str, bool]:
    n = (name or "").strip()
    if n in OPEN_PACKS:
        return "open", True
    if n in PAID_PACKS:
        return "paid", False
    return "unknown", False
