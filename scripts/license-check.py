#!/usr/bin/env python3
"""Fail if vendored parsers/grammars appear. rfg must not ship third-party tree-sitter grammars."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_DIR_NAMES = {
    "tree-sitter-go",
    "tree-sitter-javascript",
    "tree-sitter-typescript",
    "tree-sitter-python",
    "tree-sitter-rust",
    "tree-sitter-cpp",
}
FORBIDDEN_FILES = {"grammar.js", "parser.c"}


def main() -> int:
    hits = []
    for p in ROOT.rglob("*"):
        if ".git" in p.parts or p.parts[-1] == "__pycache__":
            continue
        if p.is_dir() and p.name in FORBIDDEN_DIR_NAMES:
            hits.append(str(p.relative_to(ROOT)))
        if p.is_file() and p.name in FORBIDDEN_FILES and "node_modules" not in p.parts:
            # only flag if under a tree-sitter-ish path
            if "tree-sitter" in str(p) or "grammar" in p.parent.name:
                hits.append(str(p.relative_to(ROOT)))
    if hits:
        print("vendored grammars not allowed:", *hits, sep="\n  ")
        return 1
    print("ok: no vendored grammars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
