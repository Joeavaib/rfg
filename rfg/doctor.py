from __future__ import annotations

import shutil
import sys
from pathlib import Path

from rfg import SCHEMA_VERSION, __version__
from rfg import caps, gitops, index, telemetry
from rfg.fmtutil import TOOLS
from rfg.store import Store


def run(root: str | Path) -> dict:
    root = Path(root)
    langs = index.discover_all(root)
    st = Store(root)
    schema = None
    schema_ok = True
    if st.exists():
        try:
            rm = st.load_roadmap()
            schema = rm.version
            schema_ok = rm.version >= SCHEMA_VERSION
        except Exception as e:
            schema_ok = False
            schema = str(e)
    tools = {}
    for spec in TOOLS.values():
        name = spec[0]
        tools[name] = shutil.which(name) is not None
    checks = {
        "python": {"ok": sys.version_info >= (3, 10), "detail": sys.version.split()[0]},
        "git": {"ok": shutil.which("git") is not None, "detail": shutil.which("git") or ""},
        "repo": {"ok": gitops.is_repo(root), "detail": str(root)},
        "roadmap": {"ok": st.exists(), "detail": str(st.roadmap_path) if st.exists() else "missing"},
        "schema": {"ok": schema_ok, "detail": schema},
        "languages": {"ok": bool(langs), "detail": langs},
        "compile_commands": {"ok": True, "detail": caps.has_compile_commands(root)},
        "rust_analyzer": {"ok": True, "detail": caps.rust_analyzer_ok()},
        "clangd": {"ok": True, "detail": caps.clangd_ok()},
        "offline": {"ok": True, "detail": telemetry.offline()},
        "telemetry": {"ok": not telemetry.enabled(), "detail": "opt-in" if telemetry.enabled() else "off"},
        "network": {"ok": True, "detail": "unused"},
        "vendored_grammars": {"ok": True, "detail": "none (stdlib parsers only)"},
        "formatters": {"ok": True, "detail": tools},
    }
    # compile db missing is not a doctor failure; it's informational
    failed = [k for k, v in checks.items() if not v["ok"] and k in {"python", "git"}]
    return {
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "ok": not failed,
        "failed": failed,
        "checks": checks,
    }
