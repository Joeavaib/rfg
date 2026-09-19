"""Diff presence gate (stdlib-only): every changed function in rfg/ must be
referenced by at least one test file.

This is honestly a *symbol* heuristic, not line coverage (no coverage lib
vendored on purpose). A test counts as reference only when it really *uses*
the name (AST: Name load, attribute access, import) — a bare word in a
comment or string is decoration, not coverage (QG-03). It pairs with
mutation sampling (scripts/mutation_sample.py): presence forces the agent
to touch changed code in tests, mutation checks the tests actually assert.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path


def changed_added_lines(root: str | Path, rev: str = "HEAD") -> dict[str, list[int]]:
    """Added line numbers per file from `git diff -U0 rev -- rfg/`."""
    root = Path(root)
    r = subprocess.run(
        ["git", "diff", "-U0", rev, "--", "rfg/"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    out: dict[str, list[int]] = {}
    cur: str | None = None
    new_line = 0
    for line in (r.stdout or "").splitlines():
        if line.startswith("+++ b/"):
            cur = line[len("+++ b/") :]
            out.setdefault(cur, [])
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                new_line = int(m.group(1))
        elif cur is not None:
            if line.startswith("+") and not line.startswith("+++"):
                out[cur].append(new_line)
                new_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                pass
            else:
                new_line += 1
    return {k: v for k, v in out.items() if v}


def def_spans(src: str) -> list[tuple[str, int, int]]:
    """(name, firstlineno, endlineno) for top-level and method defs."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return []
    spans: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            spans.append((node.name, node.lineno, getattr(node, "end_lineno", node.lineno) or node.lineno))
    return spans


def changed_functions(root: str | Path, rev: str = "HEAD") -> dict[str, list[str]]:
    """Changed function names per rfg/ file (added lines hitting a def span)."""
    root = Path(root)
    result: dict[str, list[str]] = {}
    for rel, lines in changed_added_lines(root, rev).items():
        try:
            src = (root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        names: list[str] = []
        for name, first, last in def_spans(src):
            if any(first <= n <= last for n in lines):
                names.append(name)
        if names:
            result[rel] = sorted(set(names))
    return result


def test_references(root: str | Path) -> dict[str, set[str]]:
    """Map test file -> set of symbol names it really uses (AST).

    Counts Name loads, attribute accesses in load position, and imported
    names. Bare words in comments/strings never count: mentioning a
    function in prose does not test it.
    """
    root = Path(root)
    refs: dict[str, set[str]] = {}
    for t in sorted((root / "tests").glob("test_*.py")):
        try:
            tree = ast.parse(t.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    names.add(node.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.ctx, ast.Load):
                    names.add(node.attr)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    names.add((a.asname or a.name).split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name != "*":
                        names.add(a.asname or a.name)
        refs[t.name] = names
    return refs


def check(root: str | Path, rev: str = "HEAD") -> tuple[int, str]:
    """Returns (exit_code, report). 0 when every changed function is referenced."""
    root = Path(root)
    changed = changed_functions(root, rev)
    if not changed:
        return 0, "no changed functions in rfg/ (nothing to gate)"
    refs = test_references(root)
    all_words: set[str] = set()
    for w in refs.values():
        all_words |= w
    missing: list[str] = []
    for rel, names in sorted(changed.items()):
        for n in names:
            if n not in all_words:
                missing.append(f"{rel}:{n}")
    if missing:
        return 2, "unreferenced changed functions (add tests touching them): " + ", ".join(missing)
    detail = "; ".join(f"{k}={','.join(v)}" for k, v in sorted(changed.items()))
    return 0, f"all changed functions referenced: {detail}"


def main(argv: list[str]) -> int:
    rev = "HEAD"
    root = Path.cwd()
    i = 0
    while i < len(argv):
        if argv[i] == "--rev" and i + 1 < len(argv):
            rev = argv[i + 1]
            i += 2
        elif argv[i] == "--root" and i + 1 < len(argv):
            root = Path(argv[i + 1])
            i += 2
        else:
            i += 1
    code, report = check(root, rev)
    print(report)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
