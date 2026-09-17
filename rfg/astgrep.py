from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from rfg.types import Step


def available() -> bool:
    return shutil.which("ast-grep") is not None or shutil.which("sg") is not None


def binary() -> str | None:
    return shutil.which("ast-grep") or shutil.which("sg")


def run(root: str | Path, step: Step, *, dry: bool) -> tuple[str, int]:
    exe = binary()
    if not exe:
        raise FileNotFoundError("ast-grep not installed")
    if step.replace is None or not step.replace.from_pat:
        raise ValueError("ast-grep step needs replace.from as pattern")
    args = [exe, "run", "-p", step.replace.from_pat, "--json=compact"]
    if step.replace.to:
        args.extend(["-r", step.replace.to])
    if dry:
        # preview only
        pass
    else:
        args.append("--update-all")
    r = subprocess.run(args, cwd=root, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise RuntimeError(out.strip() or "ast-grep failed")
    hits = out.count("file") if out else 0
    return out, hits
