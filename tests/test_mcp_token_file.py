"""The hosted MCP bearer token resolves from a file secret, not just env."""

from __future__ import annotations

from pathlib import Path

import pytest

from mnemosyne.mcp_server import _env_or_file_secret


def test_env_or_file_secret_prefers_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "mcp_bearer_token"
    secret.write_text("file-token-value\n", encoding="utf-8")
    monkeypatch.setenv("MNEMOSYNE_MCP_TOKEN", "env-token-value")
    monkeypatch.setenv("MNEMOSYNE_MCP_TOKEN_FILE", str(secret))
    assert _env_or_file_secret("MNEMOSYNE_MCP_TOKEN") == "file-token-value"


def test_env_or_file_secret_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_MCP_TOKEN_FILE", raising=False)
    monkeypatch.setenv("MNEMOSYNE_MCP_TOKEN", "env-token-value")
    assert _env_or_file_secret("MNEMOSYNE_MCP_TOKEN") == "env-token-value"


def test_env_or_file_secret_blank_file_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "blank"
    secret.write_text("   \n", encoding="utf-8")
    monkeypatch.delenv("MNEMOSYNE_MCP_TOKEN", raising=False)
    monkeypatch.setenv("MNEMOSYNE_MCP_TOKEN_FILE", str(secret))
    assert _env_or_file_secret("MNEMOSYNE_MCP_TOKEN") is None


def test_env_or_file_secret_absent_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_MCP_TOKEN", raising=False)
    monkeypatch.delenv("MNEMOSYNE_MCP_TOKEN_FILE", raising=False)
    assert _env_or_file_secret("MNEMOSYNE_MCP_TOKEN") is None
