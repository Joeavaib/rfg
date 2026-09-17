"""Mutation sampling (stdlib-only): targeted mutants must be killed by the suite.

Each mutant is a small string replacement in rfg/ source, applied to a temp
copy of the repo? No — applied in place with guaranteed restore, then the
killing test command runs. Exit 2 lists survivors (tests are decoration).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MUTANTS: list[dict] = [
    {
        "name": "cross-scope-empty",
        "file": "rfg/verify.py",
        "old": "    return out[:10]",
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
        "old": "        if isinstance(parsed, list):\n            return coerce_path_list(parsed)",
        "new": "        if isinstance(parsed, list):\n            return [s]  # mutant: no expansion",
        "kill": "python3 -m pytest tests/test_quality.py::QualityTest::test_property_coerce -q",
        "why": "JSON-array strings must expand to multiple deps",
    },
]


def run(root: str | Path, timeout: float = 120.0) -> tuple[int, str]:
    root = Path(root)
    killed: list[str] = []
    survived: list[str] = []
    for m in MUTANTS:
        f = root / m["file"]
        src = f.read_text(encoding="utf-8")
        if m["old"] not in src:
            survived.append(f"{m['name']}: anchor missing")
            continue
        f.write_text(src.replace(m["old"], m["new"], 1), encoding="utf-8")
        try:
            r = subprocess.run(
                m["kill"], shell=True, cwd=root,
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            r = None
        finally:
            f.write_text(src, encoding="utf-8")
        if r is not None and r.returncode != 0:
            killed.append(m["name"])
        else:
            survived.append(m["name"])
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
