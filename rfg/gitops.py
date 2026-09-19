from __future__ import annotations

import re
import subprocess
from pathlib import Path


_BACKUP_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _valid_backup_id(backup_id: object) -> bool:
    """Allowlist for backup ids (QM-02, fail-stop, never guess).

    Alnum start, then word chars/dots/dashes, max 200 chars. Rejects
    traversal (`../`), absolute paths, blanks, dot/dash-leading names.
    """
    if not isinstance(backup_id, str) or not backup_id or len(backup_id) > 200:
        return False
    if backup_id.startswith((".", "-", "/")):
        return False
    if ".." in Path(backup_id).parts:
        return False
    return _BACKUP_ID_RE.fullmatch(backup_id) is not None


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


def dirty_tracked_files(dir: str | Path) -> list[str]:
    """Tracked-dirty paths (same semantics as dirty_tracked, as a list).

    Used for --force diagnostics (QW-05): naming the files instead of a
    bare "dirty" so the agent can judge before forcing.
    """
    dir = Path(dir).resolve()
    try:
        top = Path(_run(dir, "rev-parse", "--show-toplevel")).resolve()
        if top != dir:
            return []
    except RuntimeError:
        return []
    out: list[str] = []
    for st, path in _porcelain(dir):
        if st.strip() == "??" or not path:
            continue
        if path not in out:
            out.append(path)
    return out


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


def worktree_diagnosis(root: str | Path) -> dict:
    """Classify `.rfg/worktree` without side effects (QW-06, single source).

    Status: usable | missing | broken-gitdir | foreign-gitdir. Uses the
    same predicates as ensure_worktree (`_worktree_usable`,
    `_gitdir_owned_by_root`) so doctor/progress name the exact reason
    the healer would act on — a heal without diagnosis is silent loss.
    """
    wt = worktree_path(root)
    if not wt.exists():
        return {
            "status": "missing",
            "detail": ".rfg/worktree absent (heals on next tick/apply)",
        }
    if not _worktree_usable(wt):
        return {
            "status": "broken-gitdir",
            "detail": "broken gitdir: .rfg/worktree/.git points nowhere usable (stale gitdir); "
            "ensure_worktree will prune and recreate it",
        }
    if not _gitdir_owned_by_root(wt, root):
        return {
            "status": "foreign-gitdir",
            "detail": f"foreign gitdir: .rfg/worktree/.git points outside {root}/.git/worktrees "
            "(stale absolute gitdir after manual clone); "
            "ensure_worktree will prune and recreate it",
        }
    return {"status": "usable", "detail": "ok"}


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


def _backup_complete(dest: Path, rm_b: bytes, st_b: bytes) -> bool:
    """True when dest holds exactly these bytes (torn dirs fail).

    A crash between two writes leaves a dir that *looks* like a backup;
    completeness (bytes + manifest hashes when present) is the only
    thing that counts as one.
    """
    import hashlib

    try:
        if not dest.is_dir():
            return False
        if (dest / "roadmap.yaml").read_bytes() != rm_b:
            return False
        if (dest / "state.json").read_bytes() != st_b:
            return False
        man = dest / "manifest.json"
        if man.is_file():
            try:
                import json

                files = (json.loads(man.read_text(encoding="utf-8")) or {}).get("files") or {}
            except (OSError, ValueError):
                return False
            if files.get("roadmap.yaml") != hashlib.sha256(rm_b).hexdigest():
                return False
            if files.get("state.json") != hashlib.sha256(st_b).hexdigest():
                return False
        return True
    except OSError:
        return False


def _clean_stale_tmp(backup_root: Path) -> None:
    """Remove crashed `.tmp-*` leftovers (best-effort, never fails).

    Rename is atomic, so any `.tmp-*` dir is crash litter by definition —
    it must never count toward the keep-cap or evict real backups.
    """
    import shutil

    try:
        litter = [p for p in backup_root.iterdir() if p.is_dir() and ".tmp-" in p.name]
    except OSError:
        return
    for p in litter:
        try:
            shutil.rmtree(p)
        except OSError:
            continue


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

    Atomicity (QW-01): files land in `<id>.tmp-*` first (data +
    `manifest.json` with sha256 per file) and appear as `<id>` via a
    single `os.rename` — a crash can leave tmp litter (cleaned
    best-effort) but never a torn backup dir. Same-id retries with
    identical bytes are idempotent.
    """
    import hashlib
    import json
    import os
    import shutil
    import tempfile
    from datetime import datetime, timezone

    rfg = Path(root) / ".rfg"
    rm_b = (rfg / "roadmap.yaml").read_bytes()
    st_b = (rfg / "state.json").read_bytes()
    if not backup_id:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        digest = hashlib.sha1(rm_b + b"\x00" + st_b).hexdigest()[:8]
        backup_id = f"{ts}-{digest}"
    if not _valid_backup_id(backup_id):
        raise OSError(f"invalid backup id: {backup_id!r}")
    backups = rfg / LAND_BACKUP_DIR
    backups.mkdir(parents=True, exist_ok=True)
    _clean_stale_tmp(backups)
    dest = backups / backup_id
    if _backup_complete(dest, rm_b, st_b):
        _prune_land_backups(backups)
        return {"dir": backup_id, "files": ["roadmap.yaml", "state.json"]}
    manifest = {
        "files": {
            "roadmap.yaml": hashlib.sha256(rm_b).hexdigest(),
            "state.json": hashlib.sha256(st_b).hexdigest(),
        }
    }
    tmp = Path(tempfile.mkdtemp(dir=str(backups), prefix=backup_id + ".tmp-"))
    try:
        (tmp / "roadmap.yaml").write_bytes(rm_b)
        (tmp / "state.json").write_bytes(st_b)
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        try:
            os.rename(tmp, dest)
        except OSError:
            if _backup_complete(dest, rm_b, st_b):
                pass  # idempotent retry lost the race; dest is already good
            else:
                raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _prune_land_backups(backups)
    return {"dir": backup_id, "files": ["roadmap.yaml", "state.json"]}


def _verify_backup_manifest(src: Path, backup_id: str) -> str:
    """Fail-stop manifest check shared by restore and dry-run (QW-02).

    Returns "ok" when a manifest is present and matches, "absent" for old
    manifest-less backups (accepted for backward compatibility). Raises
    OSError for unreadable/corrupt backups — before touching the live
    store, never after half a restore.
    """
    import hashlib
    import json

    man = src / "manifest.json"
    if not man.is_file():
        return "absent"
    try:
        files = (json.loads(man.read_text(encoding="utf-8")) or {}).get("files") or {}
    except (OSError, ValueError) as exc:
        raise OSError(f"backup {backup_id!r} has unreadable manifest") from exc
    for name in ("roadmap.yaml", "state.json"):
        blob = src / name
        try:
            digest = hashlib.sha256(blob.read_bytes()).hexdigest()
        except OSError as exc:
            raise OSError(f"backup {backup_id!r} misses {name}") from exc
        if files.get(name) != digest:
            raise OSError(f"backup {backup_id!r} corrupt: {name} hash mismatch")
    return "ok"


def diff_roadmap_state(root: str | Path, backup_id: str) -> dict:
    """Dry-run for restore: what *would* change, without writing anything.

    Same fail-stop rules as restore (unknown/corrupt -> OSError), but the
    live store is only read, never written. Payload carries per-file
    would_change plus byte sizes so callers can judge before restoring.
    """
    if not _valid_backup_id(backup_id):
        raise OSError(f"invalid backup id: {backup_id!r}")
    src = Path(root) / ".rfg" / LAND_BACKUP_DIR / backup_id
    if not src.is_dir():
        raise OSError(f"unknown backup: {backup_id!r}")
    manifest = _verify_backup_manifest(src, backup_id)
    rfg = Path(root) / ".rfg"
    diff: list[dict] = []
    for name in ("roadmap.yaml", "state.json"):
        blob = (src / name).read_bytes()
        live = rfg / name
        live_b = live.read_bytes() if live.is_file() else None
        diff.append(
            {
                "file": name,
                "would_change": live_b != blob,
                "backup_bytes": len(blob),
                "live_bytes": len(live_b) if live_b is not None else None,
            }
        )
    return {"dir": backup_id, "dry_run": True, "manifest": manifest,
            "files": ["roadmap.yaml", "state.json"], "diff": diff}


def restore_roadmap_state(root: str | Path, backup_id: str) -> dict:
    """Restore `.rfg/roadmap.yaml` + `.rfg/state.json` from a land backup.

    Recovery path when the harness store is lost (`.rfg/` is gitignored):
    pick a backup id from `.rfg/land-backups/` (newest sorts last) and call
    this helper — or manually copy both files back into `.rfg/`. Existing
    files are overwritten. Raises OSError for unknown backup ids or
    unreadable backups.
    """
    import shutil

    if not _valid_backup_id(backup_id):
        raise OSError(f"invalid backup id: {backup_id!r}")
    src = Path(root) / ".rfg" / LAND_BACKUP_DIR / backup_id
    if not src.is_dir():
        raise OSError(f"unknown backup: {backup_id!r}")
    rfg = Path(root) / ".rfg"
    # Fail-stop before touching the live store: a torn backup must refuse,
    # never half-restore (QW-01). Manifest-less dirs are old backups and
    # stay accepted for backward compatibility.
    _verify_backup_manifest(src, backup_id)
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
    pruning is hygiene, it must never fail a land. Crash litter
    (`*.tmp-*`, see backup_roadmap_state) never counts toward the cap.
    """
    import shutil

    try:
        names = sorted(
            p.name for p in backup_root.iterdir() if p.is_dir() and ".tmp-" not in p.name
        )
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
