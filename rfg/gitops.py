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
    return (r.stdout or "").strip()


def is_repo(dir: str | Path) -> bool:
    try:
        _run(dir, "rev-parse", "--is-inside-work-tree")
        return True
    except RuntimeError:
        return False


def dirty(dir: str | Path) -> bool:
    """True if tracked/untracked files exist outside .rfg/."""
    try:
        out = _run(dir, "status", "--porcelain")
    except RuntimeError:
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
    _run(root, "worktree", "add", "--detach", str(wt), "HEAD")
    return wt


def reset_hard(dir: str | Path, commit: str) -> None:
    _run(dir, "reset", "--hard", commit)


def snapshot(dir: str | Path, msg: str) -> str:
    _run(dir, "add", "-A")
    _run(dir, "commit", "-m", msg, "--allow-empty")
    return head(dir)
