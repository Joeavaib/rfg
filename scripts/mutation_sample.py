"""Mutation sampling (stdlib-only): targeted mutants must be killed by the suite.

Each mutant is applied in an isolated temp *copy* of the repo, never in
place: a SIGKILL or a parallel mutation run cannot leave a mutant behind
in the real tree (QB-01). Copies ignore .git/.rfg/caches and are removed
best-effort; leftovers are harmless (outside the repo).
Exit 2 lists survivors (tests are decoration).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MUTANTS: list[dict] = [
    {
        "name": "cross-scope-empty",
        "file": "rfg/verify.py",
        "old": "    return deduped[: _related_cap()]",
        "new": "    return []",
        "kill": "python3 -m pytest tests/test_stress_feedback.py::StressFeedbackTest::test_cross_verify -q",
        "why": "empty cross scope must miss the overlap regression",
    },
    {
        "name": "cross-no-applied-filter",
        "file": "rfg/cli.py",
        "old": "            if rid not in state.applied and rid not in state.verified:\n                continue",
        "new": "            pass  # mutant: no applied filter",
        "kill": "python3 -m pytest tests/test_implement.py::ImplementLoopTest::test_implement_dep_waits_for_verify -q",
        "why": "pending dependents must not block verify",
    },
    {
        "name": "gate-always-runnable",
        "file": "rfg/cli.py",
        "old": "    return shutil.which(first) is not None",
        "new": "    return True  # mutant",
        "kill": "python3 -m pytest tests/test_gaps.py::GapsTest::test_land_copies_and_verify_root -q",
        "why": "missing toolchain must skip the land gate, not fail it",
    },
    {
        "name": "coerce-no-json-expand",
        "file": "rfg/types.py",
        "old": "        if isinstance(parsed, list):\n            return _coerce_path_list(parsed)",
        "new": "        if isinstance(parsed, list):\n            return [s]  # mutant: no expansion",
        "kill": "python3 -m pytest tests/test_quality.py::QualityTest::test_property_coerce -q",
        "why": "JSON-array strings must expand to multiple deps",
    },
]

_COPY_SKIP = (".git", ".rfg", "__pycache__", ".pytest_cache", ".mypy_cache")


def copy_repo(root: str | Path) -> Path:
    """Isolated repo copy for one mutant run (caller removes best-effort).

    Skips .git/.rfg/caches: kill commands run pytest on tests/ in tmp-git
    repos or in-process and never need the real store or history.
    """
    root = Path(root)
    dst = Path(tempfile.mkdtemp(prefix="rfg-mutant-"))
    for item in root.iterdir():
        if item.name in _COPY_SKIP:
            continue
        target = dst / item.name
        try:
            if item.is_dir() and not item.is_symlink():
                shutil.copytree(item, target, ignore=shutil.ignore_patterns(*_COPY_SKIP))
            elif item.is_file() or item.is_symlink():
                shutil.copy2(item, target, follow_symlinks=False)
        except OSError:
            continue
    return dst


def run(root: str | Path, timeout: float = 120.0) -> tuple[int, str]:
    root = Path(root)
    killed: list[str] = []
    survived: list[str] = []
    for m in MUTANTS:
        try:
            work = copy_repo(root)
        except OSError as exc:
            survived.append(f"{m['name']}: copy failed ({exc})")
            continue
        try:
            f = work / m["file"]
            try:
                src = f.read_text(encoding="utf-8")
            except OSError:
                survived.append(f"{m['name']}: anchor missing")
                continue
            if m["old"] not in src:
                survived.append(f"{m['name']}: anchor missing")
                continue
            f.write_text(src.replace(m["old"], m["new"], 1), encoding="utf-8")
            try:
                r = subprocess.run(
                    m["kill"], shell=True, cwd=work,
                    capture_output=True, text=True, timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                r = None
            if r is not None and r.returncode != 0:
                killed.append(m["name"])
            else:
                survived.append(m["name"])
        finally:
            shutil.rmtree(work, ignore_errors=True)
    report = f"killed {len(killed)}/{len(MUTANTS)}: {','.join(killed)}"
    if survived:
        return 2, report + f" | SURVIVED: {','.join(survived)}"
    return 0, report


def main(argv: list[str]) -> int:
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else Path.cwd()
    code, report = run(root)
    print(report)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
