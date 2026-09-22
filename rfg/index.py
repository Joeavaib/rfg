from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

SKIP_DIRS = {".git", ".rfg", "node_modules", "vendor", "__pycache__", ".venv", "dist", "build"}
GO_EXT = {".go"}
TS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"}
PY_EXT = {".py"}
RS_EXT = {".rs"}
CXX_EXT = {".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".c"}

LANG_EXTS = {
    "go": GO_EXT,
    "typescript": TS_EXT,
    "python": PY_EXT,
    "rust": RS_EXT,
    "cpp": CXX_EXT,
}

IMPORT_RE = {
    "go": re.compile(r'^\s*import\s+(?:\(|")', re.M),
    "typescript": re.compile(r"^\s*import\s+", re.M),
    "python": re.compile(r"^\s*(?:import|from)\s+", re.M),
    "rust": re.compile(r"^\s*(?:use\s+|mod\s+)", re.M),
    "cpp": re.compile(r"^\s*#\s*include\s+", re.M),
}
EXPORT_RE = {
    "go": re.compile(r"^func\s+[A-Z]\w*|^type\s+[A-Z]\w*|^var\s+[A-Z]\w*", re.M),
    "typescript": re.compile(r"^\s*export\s+", re.M),
    "python": re.compile(r"^\s*(?:class|def)\s+\w+", re.M),
    "rust": re.compile(r"^\s*pub\s+(?:fn|struct|enum|mod|type|trait|const|static)", re.M),
    "cpp": re.compile(r"^\s*(?:export\s+|class\s+\w+|struct\s+\w+)", re.M),
}


def discover(root: str | Path) -> str:
    langs = discover_all(root)
    if not langs:
        return "unknown"
    if "go" in langs:
        return "go"
    if "typescript" in langs:
        return "typescript"
    return langs[0]


def discover_all(root: str | Path) -> list[str]:
    """Languages present at root or nested (polyglot layouts with src/<mod>/<lang>/)."""
    root = Path(root)
    found: set[str] = set()
    scanned = 0
    for p in root.rglob("*"):
        scanned += 1
        if scanned > 4000:
            break
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file():
            continue
        name = p.name
        if name == "go.mod":
            found.add("go")
        elif name == "package.json":
            found.add("typescript")
        elif name in ("pyproject.toml", "setup.py", "requirements.txt"):
            found.add("python")
        elif name == "Cargo.toml":
            found.add("rust")
        elif name in ("compile_commands.json", "CMakeLists.txt"):
            found.add("cpp")
        ext = p.suffix.lower()
        if ext in GO_EXT:
            found.add("go")
        elif ext in TS_EXT:
            found.add("typescript")
        elif ext in PY_EXT:
            found.add("python")
        elif ext in RS_EXT:
            found.add("rust")
        elif ext in CXX_EXT:
            found.add("cpp")
        if len(found) >= 5:
            break
    order = ("go", "typescript", "python", "rust", "cpp")
    return [x for x in order if x in found]


def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _iter_source(root: Path, langs: list[str] | None = None):
    langs = langs or discover_all(root) or ["go", "typescript", "python", "rust", "cpp"]
    exts: set[str] = set()
    for lang in langs:
        exts |= LANG_EXTS.get(lang, set())
    if not exts:
        exts = GO_EXT | TS_EXT | PY_EXT
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in exts:
            continue
        yield p


def _lang_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in GO_EXT:
        return "go"
    if ext in TS_EXT:
        return "typescript"
    if ext in PY_EXT:
        return "python"
    if ext in RS_EXT:
        return "rust"
    if ext in CXX_EXT:
        return "cpp"
    return "unknown"


def _symbols_python(text: str) -> list[str]:
    names: list[str] = []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return names
    except Exception:
        return names
    try:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.append(t.id)
    except (ValueError, AttributeError, RecursionError):
        return names
    except Exception:
        return names
    return names


DEF_RE = {
    "go": [
        re.compile(r"(?m)^func\s+(?:\([^)]*\)\s*)?(\w+)"),
        re.compile(r"(?m)^type\s+(\w+)"),
    ],
    "typescript": [
        re.compile(r"(?m)^\s*(?:export\s+)?(?:function|class|interface|enum)\s+(\w+)"),
        re.compile(r"(?m)^\s*export\s+type\s+(\w+)"),
    ],
    "rust": [
        re.compile(r"(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?fn\s+(\w+)"),
        re.compile(r"(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|mod|type)\s+(\w+)"),
    ],
    "cpp": [
        re.compile(r"(?m)^\s*(?:class|struct)\s+(\w+)"),
        re.compile(r"(?m)^\s*(?:[\w:<>*&]+\s+)+(\w+)\s*\("),
    ],
}


def _symbols_generic(text: str, lang: str) -> list[str]:
    if lang == "python":
        return _symbols_python(text)
    found: list[str] = []
    for rx in DEF_RE.get(lang) or []:
        for m in rx.finditer(text):
            found.append(m.group(1))
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9_]+)\b", text):
        found.append(m.group(1))
    return list(dict.fromkeys(found))


def _file_record(rel: str, text: str, lang: str, digest: str) -> dict:
    kind = "source"
    if EXPORT_RE.get(lang) and EXPORT_RE[lang].search(text):
        kind = "export"
    elif IMPORT_RE.get(lang) and IMPORT_RE[lang].search(text):
        kind = "import"
    return {
        "path": rel,
        "hash": digest,
        "lang": lang,
        "kind": kind,
        "symbols": _symbols_generic(text, lang),
    }


def index_path(root: str | Path) -> Path:
    return Path(root) / ".rfg" / "index.json"


def load_index(root: str | Path) -> dict:
    p = index_path(root)
    if not p.is_file():
        return {"files": {}, "scip": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_index(root: str | Path, data: dict) -> None:
    p = index_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")


def build_index(root: str | Path) -> dict:
    """Incremental: reuse records whose sha256 still matches. Unparseable files are skipped."""
    root = Path(root)
    prev = load_index(root)
    old_files = prev.get("files") or {}
    files: dict[str, dict] = {}
    skipped: list[dict] = []
    scanned = 0
    reused = 0
    for p in _iter_source(root):
        rel = p.relative_to(root).as_posix()
        try:
            raw = p.read_bytes()
        except OSError as e:
            skipped.append({"path": rel, "reason": f"unreadable: {e.strerror or e}"[:200]})
            continue
        digest = _hash_bytes(raw)
        old = old_files.get(rel)
        if old and old.get("hash") == digest:
            files[rel] = old
            reused += 1
            continue
        scanned += 1
        try:
            text = raw.decode("utf-8", errors="replace")
            files[rel] = _file_record(rel, text, _lang_for(p), digest)
        except Exception as e:
            skipped.append({"path": rel, "reason": f"{type(e).__name__}: {e}"[:200]})
            continue
    data = {
        "files": files,
        "scip": prev.get("scip") or [],
        "stats": {"scanned": scanned, "reused": reused, "files": len(files), "skipped": len(skipped)},
        "skipped": skipped[:50],
        "skipped_omitted": max(0, len(skipped) - 50),
    }
    save_index(root, data)
    return data


IMPACT_HIT_WARN = 500
IMPACT_FILE_CAP = 24


def _cap_impact(rep: dict) -> dict:
    files = sorted(rep.get("files") or [], key=lambda x: -int(x.get("hits") or 0))
    hits = int(rep.get("hits") or 0)
    if hits > IMPACT_HIT_WARN or len(files) > IMPACT_FILE_CAP:
        rep["warning"] = "too broad, use qualified symbol or SCIP"
        rep["files"] = files[:IMPACT_FILE_CAP]
        rep["files_omitted"] = max(0, len(files) - IMPACT_FILE_CAP)
    else:
        rep["files"] = files
    return rep


def impact(root: str | Path, query: str, *, use_index: bool = True) -> dict:
    root = Path(root)
    files_out: list[dict] = []
    hits = 0
    if not query:
        return {"query": query, "hits": 0, "files": files_out, "source": "empty"}
    scip_hits = impact_from_scip(root, query)
    if scip_hits["hits"]:
        return _cap_impact(scip_hits)
    idx = load_index(root) if use_index else {"files": {}}
    if use_index and not idx.get("files"):
        idx = build_index(root)
    source = "index"
    if idx.get("files"):
        needle = query.split(".")[-1]
        for rec in idx["files"].values():
            n = 0
            if needle in (rec.get("symbols") or []) or query in (rec.get("symbols") or []):
                n = 1
            path = rec["path"]
            try:
                text = (root / path).read_text(encoding="utf-8")
            except OSError:
                continue
            n = text.count(needle)
            if n == 0:
                continue
            files_out.append({"path": path, "hits": n, "kind": rec.get("kind", "source")})
            hits += n
        return _cap_impact({"query": query, "hits": hits, "files": files_out, "source": source})

    langs = discover_all(root)
    for p in _iter_source(root, langs or None):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        n = text.count(query.split(".")[-1])
        if n == 0:
            continue
        rel = p.relative_to(root).as_posix()
        files_out.append({"path": rel, "hits": n, "kind": "source"})
        hits += n
    return _cap_impact({"query": query, "hits": hits, "files": files_out, "source": "scan"})


def merge_scip(root: str | Path, scip: dict) -> dict:
    idx = load_index(root)
    occs = []
    for doc in scip.get("documents") or []:
        rel = doc.get("relative_path") or doc.get("relativePath") or ""
        for occ in doc.get("occurrences") or []:
            occs.append(
                {
                    "path": rel,
                    "symbol": occ.get("symbol") or "",
                    "range": occ.get("range") or [],
                }
            )
    idx["scip"] = occs
    save_index(root, idx)
    return idx


def impact_from_scip(root: str | Path, query: str) -> dict:
    idx = load_index(root)
    files: dict[str, int] = {}
    needle = query
    for occ in idx.get("scip") or []:
        sym = occ.get("symbol") or ""
        qualified = needle == sym or sym.endswith(needle) or needle in sym.split(" ")
        broad = len(needle) >= 8 and needle in sym
        if qualified or broad:
            p = occ.get("path") or ""
            files[p] = files.get(p, 0) + 1
    out = [{"path": p, "hits": n, "kind": "scip"} for p, n in files.items() if p]
    hits = sum(f["hits"] for f in out)
    raw = {"query": query, "hits": hits, "files": out, "source": "scip"} if hits else {"query": query, "hits": 0, "files": [], "source": "scip"}
    return _cap_impact(raw) if hits else raw
