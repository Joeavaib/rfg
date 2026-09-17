"""Guess a real verify command from repo layout so agents do not invent one."""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path

FALLBACK_VERIFY = "test -n ok"
_SKIP = {".git", ".rfg", "node_modules", "vendor", "__pycache__", ".venv", "dist", "build", "target"}


def _nested_dirs(root: Path, name: str, *, limit: int = 4) -> list[str]:
    hits: list[str] = []
    for p in root.rglob(name):
        if any(part in _SKIP for part in p.parts):
            continue
        if not p.is_file():
            continue
        rel = p.parent.relative_to(root).as_posix()
        if rel == ".":
            continue
        hits.append(rel)
        if len(hits) >= limit:
            break
    return hits


def _cd(dirs: list[str], inner: str) -> str:
    return " && ".join(f"(cd {shlex.quote(d)} && {inner})" for d in dirs)


def default_verify(root: str | Path) -> str:
    root = Path(root)
    if (root / "go.mod").is_file():
        return "go test ./..."
    if (
        (root / "pyproject.toml").is_file()
        or (root / "setup.py").is_file()
        or (root / "requirements.txt").is_file()
        or (root / "tests").is_dir()
        or any(root.glob("test_*.py"))
    ):
        if shutil.which("pytest") is not None:
            return "pytest"
        if (root / "tests").is_dir():
            return "python3 -m unittest discover -s tests"
        return "python3 -m unittest"
    if (root / "Cargo.toml").is_file():
        return "cargo test"
    if (root / "Makefile").is_file():
        return "make"
    if (root / "package.json").is_file():
        return "npm test"
    if (root / "compile_commands.json").is_file() or (root / "CMakeLists.txt").is_file():
        return "make"
    go = _nested_dirs(root, "go.mod")
    if go:
        return _cd(go, "go test ./...")
    py = [
        rel
        for rel in (_nested_dirs(root, "pyproject.toml") or _nested_dirs(root, "setup.py"))
        if (root / rel / "tests").is_dir() or (root / rel / "test").is_dir()
    ]
    if py:
        inner = "pytest" if shutil.which("pytest") is not None else "python3 -m unittest"
        return _cd(py, inner)
    rs = _nested_dirs(root, "Cargo.toml")
    if rs:
        return _cd(rs, "cargo test")
    js = [
        rel
        for rel in _nested_dirs(root, "package.json")
        if (root / rel / "tests").is_dir() or (root / rel / "test").is_dir()
    ]
    if js:
        return _cd(js, "npm test")
    return ""
