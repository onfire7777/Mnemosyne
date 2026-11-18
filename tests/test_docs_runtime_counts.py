"""Architecture doc surface counts must match the runtime, not a regex over source."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from mnemosyne.cli import build_parser
from mnemosyne.mcp_server import MnemosyneMcpServer

_DOC = Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE-OVERVIEW.md"


def test_architecture_overview_counts_match_runtime(tmp_path: Path) -> None:
    subcommands = sum(
        len(action.choices)
        for action in build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    tools = len(MnemosyneMcpServer(store_path=tmp_path / "store.json").tool_specs)
    text = _DOC.read_text(encoding="utf-8")

    cli_claims = {int(n) for n in re.findall(r"(\d+) (?:CLI )?(?:subcommands|cmds)", text)}
    mcp_claims = {int(n) for n in re.findall(r"(\d+) (?:MCP )?tools", text)}
    assert cli_claims == {subcommands}
    assert mcp_claims == {tools}
