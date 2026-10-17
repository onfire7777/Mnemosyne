"""
Sentinel lines embedded in definitive markdown for UI + DOCX styling.

Parsed by ui_frameworks._format_markdown_to_html and docx_export._append_structure_to_docx.
Do not change strings without updating both consumers.
"""

from __future__ import annotations

import re

RE_FW_BLOCK_OPEN = re.compile(r"^\[\[FW:BLOCK:(\w+)\]\]\s*$")
RE_FW_HEADING = re.compile(r"^\[\[FW:HEADING:(\w+)\]\]\s*$")

FW_EPISTEMIC_BEGIN = "[[FW:EPISTEMIC]]"
FW_EPISTEMIC_END = "[[/FW:EPISTEMIC]]"
FW_BLOCK_END = "[[/FW:BLOCK]]"


def fw_block_open(kind: str) -> str:
    return f"[[FW:BLOCK:{kind}]]"


def fw_heading_marker(kind: str) -> str:
    return f"[[FW:HEADING:{kind}]]"


def wrap_fw_block(kind: str, body: str) -> str:
    return f"{fw_block_open(kind)}\n{body.strip()}\n{FW_BLOCK_END}"
