"""Run the CLI from the same installed release as the local MCP host."""
import sys

# Importing runtime selects active-release.json before any package imports.
from runtime import ROOT
from retrieval_config import configure_environment

configure_environment()
from mnemosyne.cli import main  # noqa: E402 - runtime selects the installed package first

raise SystemExit(main([
    "--backend", "sqlite", "--store", str(ROOT / "codex-memory"), *sys.argv[1:]
]))
