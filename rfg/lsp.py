"""LSP fallback for references. Missing servers stay unsupported — never fake types."""

from __future__ import annotations

import shutil

SERVERS = {
    "go": "gopls",
    "typescript": "typescript-language-server",
    "python": "pyright-langserver",
    "rust": "rust-analyzer",
    "cpp": "clangd",
}


def server_for(lang: str) -> str | None:
    exe = SERVERS.get(lang)
    if not exe:
        return None
    return shutil.which(exe) or shutil.which(exe.replace("-langserver", ""))


def references_available(lang: str) -> bool:
    return server_for(lang) is not None
