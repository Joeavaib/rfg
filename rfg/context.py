"""Bounded step context so an agent does not read the tree."""

from __future__ import annotations

from pathlib import Path

from rfg import apply as applymod
from rfg import dag, edges, index
import re

from rfg.types import Roadmap, State, Step, default_engine, is_contract, is_stop_engine, step_observation, step_paths, step_want

MAX_FILES = 8
MAX_LINES = 24
MAX_HEAD = 12
MAX_CHARS = 8000
MAX_TOTAL_LINES = 80
_SKIP = {".git", ".rfg", "node_modules", "__pycache__", ".venv", "target", "build", "vendor"}
_LANG_DIRS = {
    "c",
    "cc",
    "cxx",
    "cpp",
    "go",
    "python",
    "py",
    "rust",
    "rs",
    "typescript",
    "ts",
    "js",
    "java",
    "haskell",
    "hs",
}
_SRC_EXT = {
    ".go",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mts",
    ".cts",
    ".py",
    ".rs",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".c",
    ".java",
    ".hs",
}


def _related_paths(root: Path, rel: str, already: set[str]) -> list[str]:
    full = root / rel
    parent = full.parent
    extras: list[str] = []

    def add(p: Path) -> None:
        if not p.is_file():
            return
        try:
            r = p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return
        if r not in already and r not in extras:
            extras.append(r)

    for base in (parent, root):
        for name in ("Makefile", "CMakeLists.txt", "compile_commands.json"):
            add(base / name)
    if parent.is_dir():
        stem = full.stem
        cpp = {".cc", ".cpp", ".cxx", ".c", ".h", ".hh", ".hpp"}
        for sib in sorted(parent.iterdir(), key=lambda p: p.name):
            if not sib.is_file() or sib.name.startswith("."):
                continue
            if sib.stem == stem or sib.suffix.lower() in cpp:
                add(sib)
    return extras


def _cousin_paths(root: Path, rel: str, already: set[str]) -> list[str]:
    """Sibling language dirs (src/mod/go vs src/mod/python) when the target is new."""
    parent = (root / rel).parent
    module = parent.parent if parent.name.lower() in _LANG_DIRS else parent
    if not module.is_dir():
        return []
    extras: list[str] = []
    try:
        root_res = root.resolve()
    except OSError:
        return []
    for p in sorted(module.rglob("*"), key=lambda x: x.as_posix()):
        if not p.is_file():
            continue
        if any(part in _SKIP or part.startswith(".") for part in p.parts):
            continue
        if p.suffix.lower() not in _SRC_EXT:
            continue
        try:
            r = p.resolve().relative_to(root_res).as_posix()
        except ValueError:
            continue
        if r in already or r in extras:
            continue
        extras.append(r)
        if len(extras) >= MAX_FILES:
            break
    return extras


def _expand_paths(root: Path, paths: list[str]) -> list[str]:
    already = set(paths)
    extra: list[str] = []
    for rel in paths:
        if not (root / rel).is_file():
            extra.extend(_related_paths(root, rel, already | set(extra)))
    ordered: list[str] = []
    seen: set[str] = set()
    for rel in list(paths) + extra:
        if rel in seen:
            continue
        seen.add(rel)
        ordered.append(rel)
        if len(ordered) >= MAX_FILES:
            break
    return ordered


def _impact_paths(root: Path, rm: Roadmap, step: Step) -> list[str]:
    q = ""
    if step.replace and step.replace.from_pat:
        q = step.replace.from_pat
    q = q or rm.hypothesis.symbol or rm.hypothesis.from_pat
    if not q:
        return []
    try:
        rep = index.impact(root, q)
    except (OSError, ValueError):
        return []
    files = sorted(rep.get("files") or [], key=lambda x: -int(x.get("hits") or 0))
    out = []
    for f in files:
        p = f.get("path") or ""
        if p and (root / p).is_file() and p not in out:
            out.append(p)
        if len(out) >= MAX_FILES:
            break
    return out


def path_split(root: str | Path, paths: list[str]) -> tuple[list[str], list[str]]:
    root = Path(root)
    missing = [p for p in paths if not (root / p).exists()]
    exists = [p for p in paths if (root / p).exists()]
    return exists, missing


_SIG = re.compile(
    r"^\s*(def |class |func |fn |pub fn |pub\(crate\) fn |pub enum |enum |impl |macro_rules!|#\[proc_macro|function |interface |struct |pub struct |type |export )",
    re.I,
)


def neighbors_and_sigs(root: Path, paths: list[str]) -> tuple[list[str], list[dict]]:
    neighbors: list[str] = []
    signatures: list[dict] = []
    seen: set[str] = set()
    root = Path(root)
    for rel in paths[:8]:
        parent = (root / rel).parent
        if not parent.is_dir():
            continue
        try:
            sibs = sorted(parent.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for sib in sibs:
            if not sib.is_file() or sib.name.startswith("."):
                continue
            if sib.suffix.lower() not in _SRC_EXT and sib.name not in ("Makefile", "CMakeLists.txt"):
                continue
            try:
                r = sib.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            if r in seen:
                continue
            seen.add(r)
            neighbors.append(r)
            if r == rel or len(signatures) >= 12:
                continue
            try:
                lines = sib.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            scan = lines[:200] if r.endswith(".rs") else lines[:80]
            for line in scan:
                if _SIG.match(line) or "macro_rules!" in line or "#[proc_macro" in line:
                    signatures.append({"path": r, "text": line.strip()[:120]})
                    break
            if len(neighbors) >= 12:
                return neighbors, signatures
    return neighbors[:12], signatures[:8]


def _snippet_paths(root: Path, rm: Roadmap, step: Step, *, sources: bool) -> tuple[list[str], list[str]]:
    targets = step_paths(step)
    if is_contract(step.engine) and not sources:
        return list(targets), []
    impact = _impact_paths(root, rm, step)
    missing = [p for p in targets if not (root / p).is_file()]
    want_src = sources and ((step.engine or "") == "manual" or bool(missing) or not targets)
    src_out: list[str] = list(impact)
    ordered: list[str] = list(targets)
    if want_src:
        for s in impact:
            if s not in ordered:
                ordered.append(s)
        for t in targets:
            for c in _cousin_paths(root, t, set(ordered)):
                if c not in ordered:
                    ordered.append(c)
                if c not in src_out:
                    src_out.append(c)
    return _expand_paths(root, ordered), src_out


def _snippets_ex(
    root: Path, rm: Roadmap, step: Step, *, sources: bool
) -> tuple[list[dict], list[str], dict]:
    """Snippets plus Kappungs-Metadaten (KD-3, warn-first, kein Gate).

    Meldet Kappung durch MAX_FILES / MAX_CHARS / MAX_TOTAL_LINES via
    ``truncated`` plus ``omitted``-Zaehler. Anzeige kappt, Disk-Dateien
    bleiben voll; --max-chars 0 = unlimited (K11-Regel, siehe rfg/tokens.py).
    """
    paths, src = _snippet_paths(root, rm, step, sources=sources)
    # MAX_FILES-Kappung: _snippet_paths/_expand_paths deckelt bereits auf
    # MAX_FILES; zusaetzlich rohe Target-Zahl pruefen (Impact/Cousins).
    full_targets = list(step_paths(step))
    truncated = False
    omitted_files = 0
    omitted_lines = 0
    if len(full_targets) > MAX_FILES:
        truncated = True
        omitted_files += len(full_targets) - MAX_FILES
    if len(paths) > MAX_FILES:
        truncated = True
        omitted_files += len(paths) - MAX_FILES
    frm = step.replace.from_pat if step.replace else ""
    out = []
    used = 0
    nlines = 0
    for idx, rel in enumerate(paths[:MAX_FILES]):
        full = root / rel
        if not full.is_file():
            if not sources:
                continue
            out.append({"path": rel, "error": "missing", "lines": []})
            continue
        try:
            text = full.read_text(encoding="utf-8")
        except OSError:
            out.append({"path": rel, "error": "unreadable", "lines": []})
            continue
        lines = text.splitlines()
        hits: list[int] = []
        needles = []
        if frm:
            needles.append(frm)
        to_pat = step.replace.to if step.replace else ""
        if to_pat and to_pat not in needles:
            needles.append(to_pat)
        for needle in needles:
            for i, line in enumerate(lines):
                if needle in line:
                    hits.append(i)
            if hits:
                break
        if hits:
            show = set()
            for i in hits[:8]:
                for j in range(max(0, i - 2), min(len(lines), i + 3)):
                    show.add(j)
            picked = sorted(show)[:MAX_LINES]
        else:
            picked = list(range(min(MAX_HEAD, len(lines))))
        if nlines + len(picked) > MAX_TOTAL_LINES:
            allowed = max(0, MAX_TOTAL_LINES - nlines)
            omitted_lines += len(picked) - allowed
            picked = picked[:allowed]
            truncated = True
        chunk = [{"n": n + 1, "text": lines[n][:200]} for n in picked]
        blob = "\n".join(c["text"] for c in chunk)
        if used + len(blob) > MAX_CHARS:
            truncated = True
            # Rest-Dateien plus Rest-Zeilen dieser Datei entfallen
            omitted_files += len(paths[:MAX_FILES]) - idx
            try:
                omitted_lines += max(0, len(lines) - len(chunk))
            except Exception:
                pass
            break
        used += len(blob)
        nlines += len(chunk)
        out.append({"path": rel, "lines": chunk})
        if nlines >= MAX_TOTAL_LINES:
            truncated = True
            omitted_files += max(0, len(paths[:MAX_FILES]) - (idx + 1))
            break
    if omitted_files or omitted_lines:
        truncated = True
    info = {
        "truncated": bool(truncated),
        "omitted": int(omitted_files),
        "omitted_files": int(omitted_files),
        "omitted_lines": int(omitted_lines),
    }
    return out, src, info


def _snippets(root: Path, rm: Roadmap, step: Step, *, sources: bool) -> tuple[list[dict], list[str]]:
    out, src, _info = _snippets_ex(root, rm, step, sources=sources)
    return out, src


def where_to_edit(root: str | Path, state: State, step: Step) -> dict:
    wt = state.worktree or ""
    stop = is_stop_engine(step.engine)
    return {
        "worktree": wt,
        "edit_root": True if stop else False,
        "after_edit": "apply" if stop else "verify",
    }


def packet(root: str | Path, rm: Roadmap, state: State, step: Step | None, *, sources: bool = False) -> dict:
    root = Path(root)
    if step is None:
        return {
            "id": None,
            "engine": "",
            "path": [],
            "snippets": [],
            "truncated": False,
            "omitted": 0,
            "edges": [],
            "tick": "done",
            "verify": rm.verify,
        }
    frm = step.replace.from_pat if step.replace else ""
    eng = default_engine(step.engine, from_pat=frm)
    paths = step_paths(step)
    exists, missing = path_split(root, paths)
    fat = bool(sources) or not is_contract(eng)
    snippets, src = ([], [])
    trunc_info: dict = {"truncated": False, "omitted": 0, "omitted_files": 0, "omitted_lines": 0}
    if fat:
        snippets, src, trunc_info = _snippets_ex(root, rm, step, sources=sources)
    else:
        # contract ohne snippets meldet MAX_FILES-Kappung trotzdem
        # (snippets leben auf context; Anzeige kappt, Disk voll).
        if len(paths) > MAX_FILES:
            trunc_info = {
                "truncated": True,
                "omitted": int(len(paths) - MAX_FILES),
                "omitted_files": int(len(paths) - MAX_FILES),
                "omitted_lines": 0,
            }
    preview = None
    if fat and step.replace and step.replace.from_pat and not is_stop_engine(eng):
        try:
            prev = applymod.preview(root, step)
            preview = applymod.compact_dry_run(prev)
        except (ValueError, OSError):
            preview = None
    step_edges = [e for e in edges.scan(root) if e.get("path") in set(paths)] if fat else []
    tick = "stop" if is_stop_engine(eng) else "apply"
    loc = where_to_edit(root, state, step)
    missing_ok = [{"path": p, "missing": True, "note": "file does not exist yet — that is ok"} for p in missing]
    neigh, sigs = ([], [])
    if sources and is_contract(eng):
        neigh, sigs = neighbors_and_sigs(root, paths)
    body = {
        "id": step.id,
        "title": step.title,
        "engine": eng,
        "want": step_want(step),
        "goal": step_want(step),
        "path": paths,
        "extras": list(step.extras or []),
        "exists": exists,
        "missing": missing,
        "missing_ok": missing_ok,
        "neighbors": neigh,
        "signatures": sigs,
        "depends": list(step.depends_on),
        "verify": step_observation(step, rm.verify),
        "oracle": step.oracle or "test",
        "edge": step.edge,
        "status": dag.step_status(rm, state, step),
        "snippets": snippets,
        "truncated": bool(trunc_info.get("truncated")),
        "omitted": int(trunc_info.get("omitted") or 0),
        "omitted_files": int(trunc_info.get("omitted_files") or 0),
        "omitted_lines": int(trunc_info.get("omitted_lines") or 0),
        "sources": src if sources else [],
        "preview": preview,
        "edges": step_edges,
        "tick": tick,
        "worktree": loc["worktree"],
        "edit_root": loc["edit_root"],
        "after_edit": loc["after_edit"],
        "claim_step": state.claim_step,
        "claim_agent": state.claim_agent,
        "applies_used": state.applies_used,
        "budget": {"max_applies": rm.budget.max_applies},
    }
    if step.replace and (step.replace.from_pat or step.replace.to):
        body["from"] = step.replace.from_pat
        body["to"] = step.replace.to
    gen: list[str] = []
    for rel in paths:
        full = root / rel
        if not full.is_file():
            continue
        try:
            head = full.read_text(encoding="utf-8")[:400].lower()
        except OSError:
            continue
        if "generated" in head or "do not edit" in head or "@generated" in head:
            gen.append(rel)
    if gen:
        body["warnings"] = [f"path looks generated: {','.join(gen[:4])}"]
    return body


def contract(root: str | Path, rm: Roadmap, state: State, step: Step | None) -> dict:
    """Tick-sized packet: no snippets/neighbors (those live on context)."""
    pkt = packet(root, rm, state, step, sources=False)
    for k in ("snippets", "neighbors", "signatures", "preview", "sources", "edges", "missing_ok"):
        pkt.pop(k, None)
    return pkt


_TICK_KEYS = (
    "id",
    "engine",
    "want",
    "path",
    "extras",
    "exists",
    "missing",
    "verify",
    "tick",
    "edit_root",
    "after_edit",
    "from",
    "to",
)


def tick_view(root: str | Path, rm: Roadmap, state: State, step: Step | None) -> dict:
    pkt = contract(root, rm, state, step)
    return {k: pkt[k] for k in _TICK_KEYS if k in pkt}
