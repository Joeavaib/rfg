from __future__ import annotations

import subprocess
from pathlib import Path


def _run(dir: str | Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=dir,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
        raise RuntimeError(f"git {' '.join(args)}: {msg}")
    return (r.stdout or "").rstrip("\n")


def is_repo(dir: str | Path) -> bool:
    try:
        _run(dir, "rev-parse", "--is-inside-work-tree")
        return True
    except RuntimeError:
        return False


def dirty_tracked(dir: str | Path) -> bool:
    """True if tracked files (not untracked, not .rfg) differ at this toplevel."""
    dir = Path(dir).resolve()
    try:
        top = Path(_run(dir, "rev-parse", "--show-toplevel")).resolve()
        if top != dir:
            return False
    except RuntimeError:
        return False
    for st, path in _porcelain(dir):
        if st.strip() == "??":
            continue
        if path:
            return True
    return False


def dirty(dir: str | Path) -> bool:
    """True if this git toplevel has tracked/untracked files outside .rfg/."""
    dir = Path(dir).resolve()
    try:
        top = Path(_run(dir, "rev-parse", "--show-toplevel")).resolve()
        out = _run(dir, "status", "--porcelain")
    except RuntimeError:
        return False
    if top != dir:
        return False
    for line in out.splitlines():
        path = line[3:] if len(line) > 3 else line
        path = path.strip().strip('"')
        if path.startswith(".rfg/") or path == ".rfg":
            continue
        if path:
            return True
    return False


def head(dir: str | Path) -> str:
    return _run(dir, "rev-parse", "HEAD")


def has_head(dir: str | Path) -> bool:
    try:
        head(dir)
        return True
    except RuntimeError:
        return False


def git_ignored(dir: str | Path, rel: str) -> bool:
    r = subprocess.run(
        ["git", "check-ignore", "-q", "--", rel],
        cwd=dir,
        capture_output=True,
        text=True,
    )
    return r.returncode == 0


def worktree_path(root: str | Path) -> Path:
    return Path(root) / ".rfg" / "worktree"


def ensure_worktree(root: str | Path) -> Path:
    wt = worktree_path(root)
    if (wt / ".git").exists() or wt.is_dir() and (wt / "HEAD").exists():
        # git worktree uses .git file
        gitf = wt / ".git"
        if gitf.exists():
            return wt
    if wt.exists():
        try:
            _run(root, "worktree", "remove", "--force", str(wt))
        except RuntimeError:
            pass
        import shutil

        shutil.rmtree(wt, ignore_errors=True)
    try:
        _run(root, "worktree", "add", "--detach", str(wt), "HEAD")
    except RuntimeError as e:
        msg = str(e)
        if "already" in msg.lower() or "registered" in msg.lower() or "exists" in msg.lower():
            try:
                _run(root, "worktree", "prune")
            except RuntimeError:
                pass
            try:
                _run(root, "worktree", "add", "--detach", str(wt), "HEAD")
            except RuntimeError:
                raise RuntimeError(
                    f"{msg} (hint: git worktree prune in {root} if .rfg/worktree was removed manually)"
                )
            return wt
        raise
    return wt


def reset_hard(dir: str | Path, commit: str) -> None:
    _run(dir, "reset", "--hard", commit)


def snapshot(dir: str | Path, msg: str) -> str:
    _run(dir, "add", "-A")
    _run(dir, "commit", "-m", msg, "--allow-empty")
    return head(dir)


def _porcelain(dir: str | Path) -> list[tuple[str, str]]:
    try:
        out = _run(dir, "status", "--porcelain", "-uall")
    except RuntimeError:
        return []
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[-1]
        if path.startswith(".rfg/") or path in (".rfg", ".git"):
            continue
        rows.append((line[:2], path))
    return rows


def untracked_rels(dir: str | Path) -> list[str]:
    """Untracked (??) paths that reset --hard would destroy, excluding .rfg."""
    return [path for st, path in _porcelain(dir) if st.strip() == "??" and path]


def backup_untracked(dir: str | Path, backup_root: str | Path) -> list[str]:
    """Copy untracked files aside before a destructive reset. Returns backed-up rels."""
    import shutil

    dir_p = Path(dir)
    bkp = Path(backup_root)
    saved: list[str] = []
    for rel in untracked_rels(dir_p):
        src = dir_p / rel
        if not src.is_file():
            continue
        dst = bkp / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            saved.append(rel)
        except OSError:
            continue
    return saved


def _land_kinds(root: Path, wt: Path) -> dict[str, str]:
    """rel -> copy|delete, including commits on the worktree since root HEAD."""
    kinds: dict[str, str] = {}
    try:
        base = head(root)
        out = _run(wt, "diff", "--name-status", base)
    except RuntimeError:
        out = ""
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, rel = parts[0], parts[-1].strip()
        if not rel or rel.startswith(".rfg") or rel.startswith("/") or ".." in Path(rel).parts:
            continue
        kinds[rel] = "delete" if status.startswith("D") else "copy"
    for st, rel in _porcelain(wt):
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            continue
        if st.strip() == "D":
            kinds[rel] = "delete"
        else:
            kinds[rel] = "copy"
    return kinds


def land(root: str | Path, worktree: str | Path) -> dict:
    """Copy worktree changes onto the main checkout. backups is for revert_land."""
    import shutil

    root = Path(root).resolve()
    wt = Path(worktree).resolve()
    if not wt.is_dir() or root == wt:
        return {"files": [], "deleted": [], "noop": True, "backups": []}
    kinds = _land_kinds(root, wt)
    if not kinds:
        return {"files": [], "deleted": [], "noop": True, "backups": []}
    backups: list[tuple[str, bytes | None, str]] = []
    for rel, kind in sorted(kinds.items()):
        src = wt / rel
        dst = root / rel
        if kind == "delete" or not src.exists():
            old = dst.read_bytes() if dst.is_file() else None
            backups.append((rel, old, "delete"))
            continue
        if src.is_file():
            old = dst.read_bytes() if dst.is_file() else None
            backups.append((rel, old, "copy"))
    files: list[str] = []
    deleted: list[str] = []
    for rel, _old, kind in backups:
        src = wt / rel
        dst = root / rel
        if kind == "delete":
            if dst.is_file():
                dst.unlink()
                deleted.append(rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        files.append(rel)
    return {"files": files, "deleted": deleted, "noop": False, "backups": backups}


def revert_land(root: str | Path, backups: list[tuple[str, bytes | None, str]]) -> None:
    root = Path(root)
    for rel, old, _kind in backups:
        dst = root / rel
        if old is None:
            if dst.is_file():
                dst.unlink()
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(old)


EXTRA_EMIT_CAP = 24
_SKIP_PARTS = {"__pycache__", "node_modules", ".venv", "dist", "build", "target", ".git"}
_SKIP_SUF = {".pyc", ".pyo", ".so", ".dylib", ".o"}


def is_campaign_edit(rel: str, root: str | Path | None = None) -> bool:
    """True for source-like paths; skip bytecode, vendor dirs, and gitignore."""
    if not rel:
        return False
    parts = Path(rel).parts
    if any(p in _SKIP_PARTS for p in parts):
        return False
    if Path(rel).suffix.lower() in _SKIP_SUF:
        return False
    if root is not None and git_ignored(root, rel):
        return False
    return True


def changed_rels(dir: str | Path) -> list[str]:
    """Tracked or untracked paths at this toplevel, excluding .rfg."""
    return [path for _st, path in _porcelain(dir) if path]


def stage_paths(
    src_root: str | Path, dst_root: str | Path, paths: list[str], *, overwrite: bool = False
) -> list[str]:
    """Copy checkout files into the apply worktree (implement/manual edits live on root)."""
    import shutil

    src_root = Path(src_root).resolve()
    dst_root = Path(dst_root).resolve()
    if src_root == dst_root:
        return []
    copied: list[str] = []
    for rel in paths:
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            continue
        src = src_root / rel
        dst = dst_root / rel
        if not src.is_file():
            continue
        if dst.is_file() and not overwrite:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    return copied
