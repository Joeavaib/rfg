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


def prune_worktrees(dir: str | Path) -> str:
    """Drop stale worktree registrations (paths gone). Never touches files."""
    return _run(dir, "worktree", "prune")


def _worktree_usable(wt: Path) -> bool:
    """True when wt answers as a git dir (V0.1: heals broken gitdir pointers).

    A `.git` file pointing at a missing `gitdir:` (e.g. stale absolute
    path after a move) previously passed `ensure_worktree` unchecked and
    failed later with "Kein Git-Repository". Now it counts as unusable so
    the caller prunes and recreates instead.
    """
    gitf = wt / ".git"
    if gitf.is_file():
        try:
            target = gitf.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if target.startswith("gitdir:"):
            target = target[len("gitdir:") :].strip()
            if target and not Path(target).exists():
                return False
        try:
            _run(wt, "rev-parse", "--is-inside-work-tree")
        except RuntimeError:
            return False
        return True
    if gitf.is_dir():
        try:
            _run(wt, "rev-parse", "--is-inside-work-tree")
        except RuntimeError:
            return False
        return True
    return False


def _gitdir_owned_by_root(wt: Path, root: str | Path) -> bool:
    """True when wt/.git gitdir resolves under root/.git/worktrees/.

    A `.git` file pointing at an *existing but foreign* gitdir (stale
    absolute path after a manual clone, state.worktree from another
    checkout) answers `rev-parse` fine but belongs to another repo, so
    `_worktree_usable` alone accepts it. Only linked worktrees of THIS
    root are usable; anything else is pruned and recreated. Non-linked
    layouts (no `.git` file) are left to `_worktree_usable`.
    """
    gitf = wt / ".git"
    if not gitf.is_file():
        return True
    try:
        target = gitf.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not target.startswith("gitdir:"):
        return False
    target = target[len("gitdir:") :].strip()
    if not target:
        return False
    gdir = Path(target)
    if not gdir.is_absolute():
        gdir = wt / gdir
    try:
        owned = Path(root).resolve() / ".git" / "worktrees"
        gdir.resolve().relative_to(owned)
        return True
    except (OSError, ValueError):
        return False


def ensure_worktree(root: str | Path) -> Path:
    wt = worktree_path(root)
    if _worktree_usable(wt) and _gitdir_owned_by_root(wt, root):
        return wt
    if wt.exists():
        try:
            _run(root, "worktree", "remove", "--force", str(wt))
        except RuntimeError:
            pass
        import shutil

        shutil.rmtree(wt, ignore_errors=True)
    try:
        _run(root, "worktree", "prune")
    except RuntimeError:
        pass
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


def commit_all(dir: str | Path, msg: str) -> str:
    """Stage everything except `.rfg/` and commit locally. Never pushes.

    `.rfg/` (worktree, logs, state) is unstaged again after `add -A`
    (plain `add` with an explicit `:!.rfg` pathspec errors out on some
    git versions when `.rfg` is gitignored). Returns the new sha, or ""
    when the tree was clean (nothing to commit). Raises RuntimeError
    on failure (e.g. missing identity) so callers can warn instead of
    failing their own operation.
    """
    _run(dir, "add", "-A")
    if has_head(dir):
        try:
            _run(dir, "reset", "-q", "--", ".rfg")
        except RuntimeError:
            pass
    if not _porcelain(dir):
        return ""
    _run(dir, "commit", "-m", msg)
    return head(dir)


LAND_BACKUP_DIR = "land-backups"
LAND_BACKUP_KEEP = 10


def backup_roadmap_state(root: str | Path, backup_id: str | None = None) -> dict:
    """Copy `.rfg/roadmap.yaml` + `.rfg/state.json` aside for harness recovery.

    `.rfg/` is gitignored, so without this copy a lost worktree means a lost
    campaign: recovery purely via the harness would be impossible. Backups
    live in `.rfg/land-backups/<backup_id>/` with `<backup_id>` defaulting
    to `<UTC-timestamp>-<sha1(content)[:8]>` (sortable, idempotent for
    identical content within the same second). Manual recovery path: copy
    both files back into `.rfg/` (see `restore_roadmap_state`). Raises
    OSError when the source files are missing/unreadable so callers can
    warn instead of failing their own operation.
    """
    import hashlib
    from datetime import datetime, timezone

    rfg = Path(root) / ".rfg"
    rm_b = (rfg / "roadmap.yaml").read_bytes()
    st_b = (rfg / "state.json").read_bytes()
    if not backup_id:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        digest = hashlib.sha1(rm_b + b"\x00" + st_b).hexdigest()[:8]
        backup_id = f"{ts}-{digest}"
    if not backup_id or backup_id.startswith("/") or ".." in Path(backup_id).parts:
        raise OSError(f"invalid backup id: {backup_id!r}")
    dest = rfg / LAND_BACKUP_DIR / backup_id
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "roadmap.yaml").write_bytes(rm_b)
    (dest / "state.json").write_bytes(st_b)
    _prune_land_backups(rfg / LAND_BACKUP_DIR)
    return {"dir": backup_id, "files": ["roadmap.yaml", "state.json"]}


def restore_roadmap_state(root: str | Path, backup_id: str) -> dict:
    """Restore `.rfg/roadmap.yaml` + `.rfg/state.json` from a land backup.

    Recovery path when the harness store is lost (`.rfg/` is gitignored):
    pick a backup id from `.rfg/land-backups/` (newest sorts last) and call
    this helper — or manually copy both files back into `.rfg/`. Existing
    files are overwritten. Raises OSError for unknown backup ids or
    unreadable backups.
    """
    import shutil

    if not backup_id or backup_id.startswith("/") or ".." in Path(backup_id).parts:
        raise OSError(f"invalid backup id: {backup_id!r}")
    src = Path(root) / ".rfg" / LAND_BACKUP_DIR / backup_id
    if not src.is_dir():
        raise OSError(f"unknown backup: {backup_id!r}")
    rfg = Path(root) / ".rfg"
    restored: list[str] = []
    for name in ("roadmap.yaml", "state.json"):
        blob = src / name
        if not blob.is_file():
            raise OSError(f"backup {backup_id!r} misses {name}")
        shutil.copy2(blob, rfg / name)
        restored.append(name)
    return {"dir": backup_id, "files": restored}


def _prune_land_backups(backup_root: Path, keep: int = LAND_BACKUP_KEEP) -> None:
    """Best-effort cap: keep the newest `keep` backup dirs (name-sorted).

    Backup ids start with a UTC timestamp so lexicographic order is
    chronological. Only directories are removed, errors are swallowed:
    pruning is hygiene, it must never fail a land.
    """
    import shutil

    try:
        names = sorted(p.name for p in backup_root.iterdir() if p.is_dir())
    except OSError:
        return
    for name in names[: max(0, len(names) - keep)]:
        try:
            shutil.rmtree(backup_root / name)
        except OSError:
            continue


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
