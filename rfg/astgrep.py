from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from rfg.types import Step


def available() -> bool:
    return shutil.which("ast-grep") is not None or shutil.which("sg") is not None


def binary() -> str | None:
    return shutil.which("ast-grep") or shutil.which("sg")


LANG_FOR_EXT = {
    ".go": "go",
    ".rs": "rust",
    ".py": "python",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".h": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
}


def lang_for(paths: list[str] | None) -> str | None:
    langs = {LANG_FOR_EXT.get(Path(p).suffix.lower()) for p in paths or [] if Path(p).suffix}
    langs.discard(None)
    if len(langs) == 1:
        return next(iter(langs))  # type: ignore[return-value]
    return None


def run(root: str | Path, step: Step, *, dry: bool) -> tuple[str, int]:
    exe = binary()
    if not exe:
        raise FileNotFoundError("ast-grep not installed")
    if step.replace is None or not step.replace.from_pat:
        raise ValueError("ast-grep step needs replace.from as pattern")
    args = [exe, "run", "-p", step.replace.from_pat, "--json=compact"]
    lang = lang_for(list(step.replace.paths or []))
    if lang:
        args.extend(["--lang", lang])
    if step.replace.to:
        args.extend(["-r", step.replace.to])
    paths = [p for p in (step.replace.paths or []) if p and ".." not in Path(p).parts]
    if dry:
        # preview only
        pass
    else:
        args.append("--update-all")
    args.extend(paths)
    r = subprocess.run(args, cwd=root, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise RuntimeError(out.strip() or "ast-grep failed")
    hits = out.count("file") if out else 0
    return out, hits
