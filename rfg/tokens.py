"""Token budgets for agent-facing output (stdlib-only).

Default 2000 chars, hard cap 8000: no command emits more than the cap without
an explicit --max-chars request, and capped payloads say so (truncated=true).
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_MAX = 2000
HARD_CAP = 8000

# list fields to shrink (essential ids like steps come last;
# exceptions are NEVER shrunk: safety info must survive every budget)
SHRINK_ORDER = ("files", "events", "components", "neighbors", "snippets", "signatures", "examples", "diff", "steps", "text")


def parse_max_chars(args: list[str], default: int = DEFAULT_MAX) -> int | None:
    """--max-chars N from argv, clamped to [1, HARD_CAP].

    N <= 0 means unlimited (None): an explicit human override for debugging.
    The clamp only ever applies to positive requests and is documented in HELP.
    """
    n = default
    for i, a in enumerate(args):
        if a == "--max-chars" and i + 1 < len(args):
            try:
                n = int(args[i + 1])
            except (ValueError, TypeError):
                n = default
    if n <= 0:
        return None
    return max(1, min(n, HARD_CAP))


def estimate_tokens(chars: int) -> int:
    """Rough token estimate (~4 chars per token)."""
    return max(0, int(chars) // 4)


def _size(data: dict) -> int:
    try:
        return len(json.dumps(data, ensure_ascii=False))
    except (TypeError, ValueError):
        return len(str(data))


def cap_data(data: dict[str, Any], max_chars: int | None) -> dict[str, Any]:
    """Shrink list fields until the JSON fits; always reports budget fields.

    max_chars=None means unlimited: annotate only, never shrink. On-disk
    artifacts (digest.json, batch file, sarif, logs) are always complete;
    only emitted JSON is budgeted.
    """
    data = dict(data)
    if max_chars is None:
        data["truncated"] = False
        data["chars"] = _size(data)
        data["token_estimate"] = estimate_tokens(data["chars"])
        data["max_chars"] = None
        return data
    if _size(data) <= max_chars:
        data["truncated"] = False
        data["chars"] = _size(data)
        data["token_estimate"] = estimate_tokens(data["chars"])
        data["max_chars"] = max_chars
        return data
    # free-text blobs first: they duplicate structured ids, clip them early
    if isinstance(data.get("text"), str) and _size(data) > max_chars:
        keep = max(0, max_chars - 200 - (_size(data) - len(data["text"])))
        data["text"] = data["text"][:keep] + "…[truncated]"
        data["text_omitted"] = True
    for key in SHRINK_ORDER:
        while isinstance(data.get(key), list) and len(data[key]) > 1 and _size(data) > max_chars:
            items = data[key]
            keep = max(1, len(items) // 2)
            data[key] = items[:keep]
            data[key + "_omitted"] = len(items) - keep
        if _size(data) <= max_chars:
            break
    data["truncated"] = _size(data) > max_chars or any(k.endswith("_omitted") for k in data)
    data["chars"] = _size(data)
    data["token_estimate"] = estimate_tokens(data["chars"])
    data["max_chars"] = max_chars
    return data
