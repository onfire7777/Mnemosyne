"""`mneme mcp-serve` starts the MCP server from the release CLI executable.

The server has always been reachable through the separate `mneme-mcp` console
script. These tests pin the two launch paths that do not depend on it: the
`mcp-serve` subcommand on `mneme`, and `python -m mnemosyne` for environments
with no console scripts at all.
"""

from __future__ import annotations

import json
import subprocess
import sys

import mnemosyne.cli as cli

_BASE = ["--backend", "local", "--store", "store.json", "mcp-serve", "--print-command"]


def _argv_for(capsys, *extra: str) -> list[str]:
    assert cli.main([*_BASE, *extra]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["prog"] == "mneme-mcp"
    argv = payload["argv"]
    assert argv[:4] == ["--backend", "local", "--store", "store.json"]
    return argv


def test_default_transport_is_plain_stdio(capsys) -> None:
    argv = _argv_for(capsys)
    assert "--sdk" not in argv
    assert not [flag for flag in argv if flag.startswith(("--http", "--sdk-streamable"))]


def test_sdk_stdio_transport(capsys) -> None:
    assert "--sdk" in _argv_for(capsys, "--transport", "sdk-stdio")


def test_streamable_http_transport_defaults_to_localhost(capsys) -> None:
    argv = _argv_for(capsys, "--transport", "streamable-http")
    assert "--sdk-streamable-http" in argv
    assert argv[argv.index("--http-host") + 1] == "127.0.0.1"
    assert argv[argv.index("--http-port") + 1] == "8765"
    assert argv[argv.index("--sdk-streamable-http-path") + 1] == "/mcp"
    assert argv[argv.index("--sdk-streamable-health-path") + 1] == "/healthz"
    assert "--sdk-streamable-stateful" not in argv


def test_streamable_http_stateful_and_passthrough(capsys) -> None:
    argv = _argv_for(
        capsys,
        "--transport",
        "streamable-http",
        "--port",
        "9001",
        "--stateful-sessions",
        "--mcp-arg=--queue-tenant",
        "--mcp-arg=tenant-a",
    )
    assert argv[argv.index("--http-port") + 1] == "9001"
    assert "--sdk-streamable-stateful" in argv
    assert argv[-2:] == ["--queue-tenant", "tenant-a"]


def test_hosted_http_transport_maps_paths(capsys) -> None:
    argv = _argv_for(capsys, "--transport", "http", "--path", "/rpc", "--health-path", "/live")
    assert "--http" in argv
    assert argv[argv.index("--http-rpc-path") + 1] == "/rpc"
    assert argv[argv.index("--http-health-path") + 1] == "/live"


def test_auth_flags_are_only_forwarded_when_given(capsys) -> None:
    assert "--auth-token" not in _argv_for(capsys)
    argv = _argv_for(capsys, "--auth-token", "secret", "--require-session")
    assert argv[argv.index("--auth-token") + 1] == "secret"
    assert "--require-session" in argv


def test_serve_invokes_the_server_entry_point(monkeypatch) -> None:
    import mnemosyne.mcp_server as mcp_server

    captured: list[list[str]] = []
    monkeypatch.setattr(mcp_server, "main", lambda argv=None: captured.append(list(argv or [])))
    assert cli.main(["--backend", "local", "--store", "store.json", "mcp-serve", "--self-test"]) == 0
    assert captured, "mcp-serve did not reach mcp_server.main"
    assert "--self-test" in captured[0]


def test_streamable_http_preflight_names_the_missing_extra(monkeypatch) -> None:
    import importlib.util

    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **k: None if name in {"mcp", "uvicorn"} else real_find_spec(name, *a, **k),
    )
    try:
        cli.main(["--backend", "local", "--store", "store.json", "mcp-serve", "--transport", "streamable-http"])
    except SystemExit as exc:
        assert "python -m pip install '.[mcp]'" in str(exc)
        assert "repository root" in str(exc)
        assert "mnemosyne-memory[mcp]" not in str(exc)
    else:  # pragma: no cover - the preflight must refuse
        raise AssertionError("expected mcp-serve to refuse without the mcp extra")


def test_module_entry_point_works_without_console_scripts() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mnemosyne", *_BASE],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["prog"] == "mneme-mcp"


def test_cli_and_mcp_server_read_a_store_in_its_stored_vector_width(tmp_path, monkeypatch) -> None:
    from mnemosyne.mcp_server import MnemosyneMcpServer
    from mnemosyne.retrieval import HashingEmbeddingProvider

    monkeypatch.delenv("MNEMOSYNE_EMBEDDING_DIMS", raising=False)
    monkeypatch.delenv("MNEMOSYNE_EMBEDDING_PROVIDER", raising=False)
    text = "The deploy server is hosted in Frankfurt."
    filt = {"tenant_id": "t", "branch": "main"}

    def cli_engine(store, *flags):
        return cli.load_engine(cli.build_parser().parse_args(["--backend", "sqlite", "--store", str(store), *flags, "search", "--tenant", "t", "--query", "x"]))

    for store, width in ((tmp_path / "old", 256), (tmp_path / "new", None)):
        server = MnemosyneMcpServer(backend="sqlite", store_path=store)
        cid = server.call_tool("capture", {"tenant_id": "t", "user_id": "u", "actor": "user", "source_type": "chat", "content": text})["cid"]
        if width:  # what an older MCP server's embedder pass stored
            server.engine.set_evidence_embedding("t", cid, HashingEmbeddingProvider(dims=width).embed(text))
        server.close()
        server, engine = MnemosyneMcpServer(backend="sqlite", store_path=store), cli_engine(store)
        expected = width or 1024
        assert server.engine.adapters.embedding.dims == engine.adapters.embedding.dims == expected
        assert [hit.id for hit in server.engine.vector_search("deploy server", 5, filt)] == [cid]
        assert [hit.id for hit in engine.vector_search("deploy server", 5, filt)] == [cid]
        server.close()
        engine.close()
    # An explicit width re-hashes the stored 256-dim row instead of dropping it.
    engine = cli_engine(tmp_path / "old", "--embedding-dims", "1024")
    assert engine.adapters.embedding.dims == 1024
    assert len(engine.vector_search("deploy server", 5, filt)) == 1
    engine.close()
