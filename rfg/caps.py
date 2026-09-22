from __future__ import annotations

from pathlib import Path

from rfg import lsp


def has_compile_commands(root: str | Path) -> bool:
    root = Path(root)
    return (
        (root / "compile_commands.json").is_file()
        or (root / "build" / "compile_commands.json").is_file()
        or (root / "cxx" / "compile_commands.json").is_file()
    )


def rust_has_macros(text: str) -> bool:
    return "macro_rules!" in text or "proc_macro" in text or "#[macro_export]" in text


def looks_like_macro_use(pattern: str) -> bool:
    return pattern.endswith("!") or "!(" in pattern


def cpp_paths(paths: list[str]) -> bool:
    cpp_ext = {".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".c"}
    return any(Path(p).suffix.lower() in cpp_ext for p in paths)


def rust_paths(paths: list[str]) -> bool:
    return any(Path(p).suffix.lower() == ".rs" for p in paths)


def rust_analyzer_ok() -> bool:
    return lsp.server_for("rust") is not None


def clangd_ok() -> bool:
    return lsp.server_for("cpp") is not None
