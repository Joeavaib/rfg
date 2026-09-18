"""Epic scope helpers (GS1).

Reine String-Praefix-Helfer, stdlib-only (nur ``re``), warn-first:
unbekannte Epics liefern leere Listen plus Warntext, nie hartes Gate,
kein Schema-Feld, kein Prozessabbruch, kein Netz/Daemon, kein
LLM/tree-sitter/clangd im Kern.

Schnittregel: Das Epic einer Step-ID ist der fuehrende Grossbuchstaben-
Praefix (``GS1-epic-scope`` -> ``GS``, ``KD-1`` -> ``KD``, ``XB-01`` ->
``XB``). Kein Roadmap-Schema-Feld noetig.
"""

from __future__ import annotations

import re

__all__ = ["epic_of", "filter_by_epic", "list_epics", "unknown_epic_warning", "epic_warning"]

_EPIC_RE = re.compile(r"^([A-Z]+)")


def epic_of(step_id: str | None) -> str:
    """Epic aus Step-ID-Praefix ableiten (fuehrende Grossbuchstaben)."""
    if not step_id:
        return ""
    m = _EPIC_RE.match(str(step_id))
    return m.group(1) if m else ""


def _step_id(step) -> str:
    """ID aus Step-Objekt (``.id``), Dict (``['id']``) oder String lesen."""
    if isinstance(step, str):
        return step
    if isinstance(step, dict):
        return str(step.get("id") or "")
    return str(getattr(step, "id", "") or "")


def filter_by_epic(steps, epic: str | None):
    """Steps auf ein Epic filtern (reiner Praefix-Vergleich).

    Leerer/fehlender Epic-Filter gibt alle Steps zurueck. Unbekanntes
    Epic -> ``[]`` (Warntext via :func:`unknown_epic_warning`); die
    Funktion bricht nie ab und aendert keine Exit-Semantik.
    """
    items = list(steps or [])
    if not epic:
        return items
    want = str(epic)
    return [s for s in items if epic_of(_step_id(s)) == want]


def list_epics(steps) -> list[str]:
    """Sortierte, eindeutige Epics ueber Step-IDs (reine Praefixe)."""
    seen: set[str] = set()
    for s in steps or []:
        e = epic_of(_step_id(s))
        if e:
            seen.add(e)
    return sorted(seen)


def unknown_epic_warning(steps, epic: str | None) -> str:
    """Warntext fuer unbekanntes Epic, ``""`` wenn bekannt oder leer.

    Rein warnend (warn-first): nennt das unbekannte Epic plus bekannte
    Epics, gatet nie.
    """
    if not epic:
        return ""
    known = set(list_epics(steps))
    if str(epic) in known:
        return ""
    hint = ", ".join(sorted(known)) if known else "none"
    return f"unknown epic {epic!r} (known: {hint}); warn-first, no gate"


epic_warning = unknown_epic_warning
