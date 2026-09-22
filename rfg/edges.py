"""Explicit cross-language edges: cgo, pyo3, napi. Never inferred as complete FFI."""

from __future__ import annotations

import json
import re
from pathlib import Path

SKIP = {".git", ".rfg", "node_modules", "target", "vendor", "__pycache__", ".venv", "build"}

CGO_RE = re.compile(r'import\s+"C"|^\s*//export\s+|^\s*#include\s+"', re.M)
PYO3_RE = re.compile(r"\bpyo3\b|#\[pyfunction\]|#\[pymodule\]|#\[pyclass\]")
NAPI_RE = re.compile(r"#\[napi\]|\bnapi[-_]?rs\b|\bnapi\.h\b|require\(['\"]bindings['\"]\)")


def scan(root: str | Path) -> list[dict]:
    root = Path(root)
    found: list[dict] = []
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        if any("napi" in k or k == "bindings" or k == "node-addon-api" for k in deps):
            found.append(
                {
                    "type": "napi",
                    "from": "typescript",
                    "to": "native",
                    "path": "package.json",
                    "complete": False,
                }
            )
    for p in root.rglob("*"):
        if p.is_dir() or any(part in SKIP for part in p.parts):
            continue
        ext = p.suffix.lower()
        if ext not in {".go", ".rs", ".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".py", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".c"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(root).as_posix()
        if ext == ".go" and CGO_RE.search(text):
            found.append({"type": "cgo", "from": "go", "to": "c", "path": rel, "complete": False})
        if PYO3_RE.search(text):
            found.append({"type": "pyo3", "from": "rust", "to": "python", "path": rel, "complete": False})
        if NAPI_RE.search(text):
            found.append({"type": "napi", "from": "rust", "to": "typescript", "path": rel, "complete": False})
        if ext in {".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".c"} and ("extern \"C\"" in text or 'extern "C"' in text):
            found.append({"type": "cxx-ffi", "from": "cpp", "to": "other", "path": rel, "complete": False})
    # de-dupe by type+path
    uniq = {}
    for e in found:
        uniq[(e["type"], e["path"])] = e
    return list(uniq.values())
