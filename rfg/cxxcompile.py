"""Build a real C++ verify command from compile_commands.json or PATH."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from rfg.caps import has_compile_commands

CXX_SRC = {".cc", ".cpp", ".cxx", ".c"}


def compiler() -> str:
    for n in ("c++", "g++", "clang++"):
        if shutil.which(n):
            return n
    return "c++"


def load_db(root: Path) -> list[dict]:
    for cand in (root / "compile_commands.json", root / "build" / "compile_commands.json", root / "cxx" / "compile_commands.json"):
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return []
            if isinstance(data, list):
                return data
    return []


def command(root: str | Path, paths: list[str] | None = None) -> str:
    root = Path(root)
    db = load_db(root)
    want = {Path(p).as_posix() for p in (paths or [])}
    src = [p for p in (paths or []) if Path(p).suffix.lower() in CXX_SRC]
    if db:
        cmds = []
        for ent in db:
            f = Path(ent.get("file") or "").as_posix()
            if want and f not in want and Path(f).name not in {Path(p).name for p in want}:
                continue
            raw = (ent.get("command") or "").strip()
            if raw:
                cmds.append(raw)
            elif ent.get("arguments"):
                cmds.append(" ".join(str(a) for a in ent["arguments"]))
        if cmds:
            return " && ".join(cmds)
    files = src or [Path(e.get("file") or "").as_posix() for e in db if e.get("file")]
    files = [f for f in files if f]
    if not files:
        return compiler() + " -std=c++17 -fsyntax-only"
    return compiler() + " -std=c++17 -fsyntax-only " + " ".join(files)


def minimal_db(root: str | Path, paths: list[str] | None = None) -> list[dict]:
    """Generate a minimal compile_commands.json from path[] (g++ -fsyntax-only)."""
    root = Path(root).resolve()
    comp = compiler()
    src = [p for p in (paths or []) if Path(p).suffix.lower() in CXX_SRC]
    if not src:
        src = ["a.cpp"]
    entries: list[dict] = []
    for rel in src:
        entries.append(
            {
                "directory": str(root),
                "file": Path(rel).as_posix(),
                "command": f"{comp} -std=c++17 -fsyntax-only {Path(rel).as_posix()}",
            }
        )
    return entries


def missing_db_hint(root: str | Path, paths: list[str] | None = None) -> str:
    db = minimal_db(root, paths)
    sample = json.dumps(db[:2], indent=2)
    return (
        "unsupported: C++ apply without compile_commands.json "
        "(need compile DB for honest rename). "
        "Minimal template from path[] (write to compile_commands.json or build/compile_commands.json): "
        f"{sample} "
        f"Generator: python3 -c \"from rfg.cxxcompile import minimal_db; import json; "
        f"print(json.dumps(minimal_db('.', {paths or []}), indent=2))\" "
        f"or verify fallback: {command(root, paths)}"
    )


def should_default(root: str | Path, paths: list[str] | None) -> bool:
    paths = paths or []
    cppish = any(Path(p).suffix.lower() in CXX_SRC | {".h", ".hh", ".hpp"} for p in paths)
    if cppish:
        return True
    if paths:
        return False
    return has_compile_commands(root)
