from __future__ import annotations

from pathlib import Path

from rfg.types import Step

EXTS = {".go", ".ts", ".tsx", ".js", ".jsx", ".mod", ".py", ".rs", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".c"}
SKIP = {".git", ".rfg", "node_modules", "__pycache__", ".venv", "target", "build"}


def _files(root: Path, step: Step) -> list[str]:
    if step.replace and step.replace.paths:
        return list(step.replace.paths)
    out = []
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP for part in p.parts):
            continue
        if p.suffix.lower() in EXTS or p.name == "go.mod":
            out.append(p.relative_to(root).as_posix())
    return out


def patch(root: str | Path, step: Step) -> tuple[str, int]:
    if step.replace is None:
        raise ValueError(f"step {step.id} has no replace")
    root = Path(root)
    frm, to = step.replace.frm, step.replace.to
    if not frm:
        raise ValueError("empty replace.from")
    parts: list[str] = []
    hits = 0
    for rel in _files(root, step):
        full = root / rel
        try:
            src = full.read_text(encoding="utf-8")
        except OSError:
            continue
        if frm not in src:
            continue
        n = src.count(frm)
        neu = src.replace(frm, to)
        hits += n
        parts.append(f"--- a/{rel}\n+++ b/{rel}")
        old_lines = src.split("\n")
        new_lines = neu.split("\n")
        m = max(len(old_lines), len(new_lines))
        for i in range(m):
            o = old_lines[i] if i < len(old_lines) else None
            nl = new_lines[i] if i < len(new_lines) else None
            if o != nl:
                if o is not None:
                    parts.append("-" + o)
                if nl is not None:
                    parts.append("+" + nl)
    return "\n".join(parts) + ("\n" if parts else ""), hits


def apply_step(root: str | Path, step: Step) -> int:
    if step.replace is None:
        raise ValueError(f"step {step.id} has no replace")
    root = Path(root)
    frm, to = step.replace.frm, step.replace.to
    hits = 0
    for rel in _files(root, step):
        full = root / rel
        try:
            src = full.read_text(encoding="utf-8")
        except OSError:
            continue
        if frm not in src:
            continue
        hits += src.count(frm)
        full.write_text(src.replace(frm, to), encoding="utf-8")
    return hits


def changed_rels(root: str | Path, step: Step) -> list[str]:
    if step.replace is None:
        return []
    root = Path(root)
    frm = step.replace.frm
    out = []
    for rel in _files(root, step):
        full = root / rel
        try:
            src = full.read_text(encoding="utf-8")
        except OSError:
            continue
        if frm and frm in src:
            out.append(rel)
    return out
