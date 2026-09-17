"""Goal acceptance items that are real shell commands (not prose)."""

from __future__ import annotations

from rfg.types import Roadmap
from rfg.verify import is_trivial, run

_FIRST = {
    "test",
    "make",
    "python",
    "python3",
    "pytest",
    "node",
    "npm",
    "npx",
    "go",
    "cargo",
    "g++",
    "gcc",
    "c++",
    "cmake",
    "sh",
    "bash",
}


def is_command(item: str) -> bool:
    s = (item or "").strip()
    if not s or is_trivial(s):
        return False
    first = s.split()[0]
    base = first.rsplit("/", 1)[-1]
    # Paths only: ./foo, /usr/bin/x, ../x — not prose like "Register/Login".
    if first.startswith(("./", "/", "../")):
        return True
    return base in _FIRST


def commands(rm: Roadmap) -> list[str]:
    return [a.strip() for a in (rm.goal.acceptance or []) if is_command(a)]


def prose(rm: Roadmap) -> list[str]:
    """Acceptance items that are prose, not executable commands.

    These never gate progress/land; they are listed as `acceptance_prose`
    with a not-executed hint so campaign prose cannot rot silently
    (Meridian: 'Baseline mit Pricing-Engine (TS), ...' was never built).
    """
    return [a.strip() for a in (rm.goal.acceptance or []) if a and a.strip() and not is_command(a)]


def run_all(root: str, rm: Roadmap) -> tuple[int, str, list[dict]]:
    rows: list[dict] = []
    for cmd in commands(rm):
        code, out = run(root, cmd)
        rows.append({"command": cmd, "code": code, "ok": code == 0})
        if code != 0:
            return code, (out or "") + f" acceptance failed: {cmd}", rows
    return 0, "", rows
