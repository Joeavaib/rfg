"""Guess a real verify command from repo layout so agents do not invent one."""

from __future__ import annotations

import json
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


def _has_npm_test_script(pkg: str | Path) -> bool:
    """True only if package.json declares a non-empty scripts.test.

    `npm test` without a test script errors out, so promising it
    is dishonest. Unparseable package.json counts as missing.
    """
    try:
        data = json.loads(Path(pkg).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    scripts = (data or {}).get("scripts") or {}
    return bool(str(scripts.get("test") or "").strip())


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
        if _has_npm_test_script(root / "package.json"):
            return "npm test"
        # no test script: fall through to nested search instead of
        # promising a command that errors out
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
        if ((root / rel / "tests").is_dir() or (root / rel / "test").is_dir())
        and _has_npm_test_script(root / rel / "package.json")
    ]
    if js:
        return _cd(js, "npm test")
    return ""
