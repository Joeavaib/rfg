from __future__ import annotations

from pathlib import Path

def text() -> str:
    here = Path(__file__).resolve().parent.parent / "docs" / "rfg.1"
    if here.is_file():
        return here.read_text(encoding="utf-8")
    return ".TH RFG 1\n.SH NAME\nrfg\n"
