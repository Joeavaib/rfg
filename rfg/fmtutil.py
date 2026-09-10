"""Format-after-apply. Missing formatters are skipped, never faked."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

TOOLS = {
    ".go": ["gofmt", "-w"],
    ".rs": ["rustfmt"],
    ".py": ["ruff", "format"],
    ".ts": ["prettier", "--write"],
    ".tsx": ["prettier", "--write"],
    ".js": ["prettier", "--write"],
    ".cc": ["clang-format", "-i"],
    ".cpp": ["clang-format", "-i"],
    ".cxx": ["clang-format", "-i"],
    ".h": ["clang-format", "-i"],
    ".hpp": ["clang-format", "-i"],
}


def format_paths(root: str | Path, rels: list[str]) -> list[dict]:
    root = Path(root)
    reports = []
    for rel in rels:
        ext = Path(rel).suffix.lower()
        spec = TOOLS.get(ext)
        if not spec:
            continue
        exe = shutil.which(spec[0])
        if not exe:
            reports.append({"path": rel, "tool": spec[0], "ran": False, "reason": "not on PATH"})
            continue
        r = subprocess.run(
            [exe, *spec[1:], str(root / rel)],
            cwd=root,
            capture_output=True,
            text=True,
        )
        reports.append(
            {
                "path": rel,
                "tool": spec[0],
                "ran": r.returncode == 0,
                "reason": "" if r.returncode == 0 else (r.stderr or r.stdout)[:200],
            }
        )
    return reports
