from __future__ import annotations

import re
from pathlib import Path

from rfg.index import LANG_EXTS
from rfg.types import Step

# Single-source: alle indexierten Exts sind ersetzbar. .mod ist
# apply-only (go.mod-Nachbar), kein index-EXT – bewusste Ausnahme.
EXTS = set().union(*LANG_EXTS.values()) | {".mod"}
SKIP = {".git", ".rfg", "node_modules", "__pycache__", ".venv", "target", "build"}
SKIP_REASONS = ("string_literal", "comment", "unsupported")


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


def _skip_spans(src: str, suffix: str) -> list[tuple[str, int, int]]:
    """Byte/char spans that are comments or string literals. Inclusive start, exclusive end."""
    n = len(src)
    i = 0
    spans: list[tuple[str, int, int]] = []
    py = suffix == ".py"
    ticks = suffix in {".go", ".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"}
    cxx = suffix in {".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".c"}
    include_re = re.compile(r"#\s*include\s*<[^>\n]*>")
    while i < n:
        if cxx and src[i] == "#":
            eol = src.find("\n", i)
            if eol < 0:
                eol = n
            line = src[i:eol]
            m = include_re.match(line)
            if m:
                a = i + m.group(0).find("<")
                b = i + m.group(0).find(">") + 1
                spans.append(("string_literal", a, b))
                i += 1
                continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            spans.append(("comment", i, j))
            i = j
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            spans.append(("comment", i, j))
            i = j
            continue
        if py and src[i] == "#":
            j = src.find("\n", i)
            j = n if j < 0 else j
            spans.append(("comment", i, j))
            i = j
            continue
        if py and (src.startswith('"""', i) or src.startswith("'''", i)):
            q = src[i : i + 3]
            j = src.find(q, i + 3)
            j = n if j < 0 else j + 3
            spans.append(("string_literal", i, j))
            i = j
            continue
        if src[i] in "\"'":
            q = src[i]
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == q:
                    j += 1
                    break
                j += 1
            spans.append(("string_literal", i, j))
            i = j
            continue
        if ticks and src[i] == "`":
            j = src.find("`", i + 1)
            j = n if j < 0 else j + 1
            spans.append(("string_literal", i, j))
            i = j
            continue
        i += 1
    return spans


def _kind_at(pos: int, spans: list[tuple[str, int, int]]) -> str | None:
    for kind, a, b in spans:
        if a <= pos < b:
            return kind
    return None


def _ident_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def replace_preserving(src: str, frm: str, to: str, suffix: str) -> tuple[str, int, list[dict], list[str]]:
    """Replace whole identifiers in code only. Returns (new, hits, skipped, example_new_lines)."""
    if not frm:
        return src, 0, [], []
    spans = _skip_spans(src, suffix)
    out: list[str] = []
    skipped: list[dict] = []
    examples: list[str] = []
    hits = 0
    i = 0
    n = len(src)
    flen = len(frm)
    while i < n:
        j = src.find(frm, i)
        if j < 0:
            out.append(src[i:])
            break
        out.append(src[i:j])
        kind = _kind_at(j, spans)
        if kind in ("string_literal", "comment"):
            line = src[:j].count("\n") + 1
            snippet = src.splitlines()[line - 1] if src.splitlines() else frm
            skipped.append({"path": "", "reason": kind, "line": line, "example": snippet[:200]})
            out.append(frm)
            i = j + flen
            continue
        prev = src[j - 1] if j else ""
        nxt = src[j + flen] if j + flen < n else ""
        if (prev and _ident_char(prev)) or (nxt and _ident_char(nxt)):
            out.append(frm)
            i = j + flen
            continue
        hits += 1
        out.append(to)
        line_start = src.rfind("\n", 0, j) + 1
        line_end = src.find("\n", j)
        if line_end < 0:
            line_end = n
        old_line = src[line_start:line_end]
        examples.append((old_line.replace(frm, to, 1))[:200])
        i = j + flen
    return "".join(out), hits, skipped, examples[:3]


def preview(root: str | Path, step: Step) -> dict:
    """Shared dry-run/apply scan. hits are identifier (code) replacements only."""
    if step.replace is None:
        raise ValueError(f"step {step.id} has no replace")
    root = Path(root)
    frm, to = step.replace.from_pat, step.replace.to
    if not frm:
        return {"files": [], "skipped": [], "hits": 0, "diff": "", "new_by_rel": {}, "zero_hits": []}
    files: list[dict] = []
    skipped: list[dict] = []
    hits = 0
    parts: list[str] = []
    new_by_rel: dict[str, str] = {}
    for rel in _files(root, step):
        full = root / rel
        try:
            src = full.read_text(encoding="utf-8")
        except OSError:
            skipped.append({"path": rel, "reason": "unsupported", "line": 0, "example": ""})
            continue
        if frm not in src:
            continue
        suffix = Path(rel).suffix.lower()
        neu, n, sk, examples = replace_preserving(src, frm, to, suffix)
        for s in sk:
            s["path"] = rel
            skipped.append(s)
        if n:
            hits += n
            files.append({"path": rel, "hits": n, "examples": examples[:3]})
            new_by_rel[rel] = neu
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
    hit_paths = {f["path"] for f in files}
    zero_hits = [rel for rel in _files(root, step) if rel not in hit_paths]
    return {
        "files": files,
        "skipped": skipped,
        "hits": hits,
        "diff": "\n".join(parts) + ("\n" if parts else ""),
        "new_by_rel": new_by_rel,
        "zero_hits": zero_hits,
    }


def patch(root: str | Path, step: Step) -> tuple[str, int]:
    p = preview(root, step)
    return p["diff"], p["hits"]


def apply_step(root: str | Path, step: Step) -> int:
    p = preview(root, step)
    root = Path(root)
    for rel, neu in p["new_by_rel"].items():
        dst = root / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        dst.write_text(neu, encoding="utf-8")
    return p["hits"]


def zero_hit_paths(root: str | Path, step: Step) -> list[str]:
    """Paths in scope with 0 identifier hits — scope errors stay visible."""
    try:
        p = preview(root, step)
    except (ValueError, OSError):
        return list(step.replace.paths) if step.replace else []
    return list(p.get("zero_hits") or [])


def changed_rels(root: str | Path, step: Step) -> list[str]:
    if step.replace is None:
        return []
    p = preview(root, step)
    return [f["path"] for f in p["files"]]


def compact_dry_run(preview_data: dict) -> dict:
    return {
        "files": preview_data["files"],
        "skipped": [
            {"path": s["path"], "reason": s["reason"], "line": s.get("line", 0), "example": s.get("example", "")}
            for s in preview_data["skipped"]
        ],
        "hits": preview_data["hits"],
        "zero_hits": list(preview_data.get("zero_hits") or []),
    }
