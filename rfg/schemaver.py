from __future__ import annotations

from rfg import SCHEMA_VERSION
from rfg.types import Oracle, Roadmap


def needs_migrate(rm: Roadmap) -> bool:
    return rm.version < SCHEMA_VERSION


def migrate_roadmap(rm: Roadmap) -> Roadmap:
    """v0→v1 engine fields; v1→v2 goal contract + oracle stubs."""
    if rm.version < 1:
        rm.version = 1
    if rm.version < 2:
        if not rm.goal.statement:
            rm.goal.statement = rm.hypothesis.statement
            rm.goal.id = rm.hypothesis.id or "g1"
        kinds = {o.kind for o in rm.oracles}
        for k in ("test", "perf", "debug", "security"):
            if k not in kinds:
                cmd = rm.verify if k == "test" else ""
                rm.oracles.append(Oracle(kind=k, command=cmd))
        rm.version = 2
    if rm.version < 3:
        rm.version = 3
    rm.version = max(rm.version, SCHEMA_VERSION)
    return rm
