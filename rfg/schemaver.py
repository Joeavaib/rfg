from __future__ import annotations

from rfg import SCHEMA_VERSION
from rfg.types import Roadmap


def needs_migrate(rm: Roadmap) -> bool:
    return rm.version < SCHEMA_VERSION


def migrate_roadmap(rm: Roadmap) -> Roadmap:
    """v0 → v1: schema version bump; steps already have optional engine/budget/edge."""
    if rm.version < 1:
        rm.version = 1
    rm.version = max(rm.version, SCHEMA_VERSION)
    return rm
