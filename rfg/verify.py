from __future__ import annotations

import subprocess
from pathlib import Path


def run(dir: str | Path, command: str) -> tuple[int, str]:
    if not command.strip():
        return 0, ""
    r = subprocess.run(
        command,
        cwd=dir,
        shell=True,
        capture_output=True,
        text=True,
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out
