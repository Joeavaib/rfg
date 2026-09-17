from __future__ import annotations

from rfg.types import Step


def diff_line_count(diff: str) -> int:
    return sum(1 for line in diff.splitlines() if line.startswith("+") or line.startswith("-"))


def score(step: Step, *, hits: int, diff_lines: int, edges: list[dict], macros: bool, cpp_no_db: bool) -> dict:
    """0–100. Higher is riskier. Never claims semantic safety."""
    s = 10
    s += min(40, hits * 2)
    s += min(20, diff_lines // 4)
    if edges:
        s += 15
    if macros:
        s += 25
    if cpp_no_db:
        s += 20
    if step.engine in ("manual", "implement"):
        s += 10
    s = min(100, s)
    band = "low" if s < 30 else "medium" if s < 60 else "high"
    return {
        "score": s,
        "band": band,
        "hits": hits,
        "diff_lines": diff_lines,
        "edges": len(edges),
        "macros": macros,
        "cpp_no_compile_db": cpp_no_db,
    }


def over_budget(step: Step, diff_lines: int) -> bool:
    if step.diff_budget and step.diff_budget > 0:
        return diff_lines > step.diff_budget
    return False
