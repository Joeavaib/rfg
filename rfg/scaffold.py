"""Create empty (or templated) files. No LLM."""

from __future__ import annotations

from pathlib import Path

from rfg.types import is_traversal_path

TPL = Path(__file__).resolve().parent / "data" / "scaffold"


def _paths(paths: list[str]) -> list[str]:
    out: list[str] = []
    for rel in paths or []:
        rel = (rel or "").strip().lstrip("/")
        if not rel or is_traversal_path(rel):
            continue
        out.append(rel)
    return out


def plan(root: str | Path, paths: list[str]) -> list[str]:
    root = Path(root)
    return [rel for rel in _paths(paths) if not (root / rel).is_file()]


def apply(root: str | Path, paths: list[str]) -> list[str]:
    root = Path(root)
    created: list[str] = []
    for rel in _paths(paths):
        dest = root / rel
        if dest.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        ext = dest.suffix.lower()
        tpl = TPL / f"empty{ext}"
        body = tpl.read_text(encoding="utf-8") if tpl.is_file() else ""
        dest.write_text(body, encoding="utf-8")
        created.append(rel)
    return created
