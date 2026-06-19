from __future__ import annotations

import tomllib
from io import StringIO
from pathlib import Path

from mnemosyne.mcp_server import MnemosyneMcpServer
from mnemosyne.models import Hit
from mnemosyne.postgres_engine import PostgresEngine, _bytes_to_cid, _cid_to_bytes, _stable_uuid, _uuid_or_none
from mnemosyne.retrieval import LocalSimilarityReranker, semantic_entropy


TENANT = "tenant-runtime"
USER = "user-runtime"


def test_semantic_entropy_distinguishes_identical_and_divergent_answers() -> None:
    assert semantic_entropy(["Postgres is the store", "Postgres is the store"]) == 0.0
    assert semantic_entropy(["Postgres is the store", "SQLite is the store"]) > 0.5


def test_local_similarity_reranker_prefers_query_relevant_hits() -> None:
    reranker = LocalSimilarityReranker()
    hits = [
        Hit(
            id="unrelated",
            kind="evidence",
            tenant_id=TENANT,
            branch="main",
            text="The UI color palette should avoid one-note gradients.",
            score=0.1,
            channel="candidate",
        ),
        Hit(
            id="postgres",
            kind="evidence",
            tenant_id=TENANT,
            branch="main",
            text="The memory system stores durable evidence in local-first Postgres.",
            score=0.1,
            channel="candidate",
        ),
    ]

    ranked = reranker.rerank("Postgres durable evidence store", hits, k=2)

    assert [hit.id for hit in ranked] == ["postgres", "unrelated"]
    assert ranked[0].metadata["reranker"] == "local-similarity"


def test_mcp_server_initializes_lists_tools_and_calls_capture_search(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")
    init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    capture = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "capture",
                "arguments": {
                    "tenant_id": TENANT,
                    "user_id": USER,
                    "actor": "user",
                    "source_type": "chat",
                    "content": "Runtime MCP captures memory evidence.",
                    "trust_tier": 3,
                },
            },
        }
    )
    search = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {"tenant_id": TENANT, "query": "MCP memory evidence"},
            },
        }
    )

    assert init["result"]["serverInfo"]["name"] == "mnemosyne-memory"
    assert {tool["name"] for tool in listed["result"]["tools"]} >= {
        "capture",
        "ingest",
        "assert_fact",
        "relation",
        "preference",
        "search",
        "branch",
        "prefetch",
        "profile_add",
        "profile_context",
        "forget",
        "export",
    }
    assert capture["result"]["isError"] is False
    assert search["result"]["isError"] is False
    capture_content = capture["result"]["structuredContent"]
    search_content = search["result"]["structuredContent"]
    assert capture_content["cid"]
    assert search_content["hits"]
    assert search_content["hits"][0]["provenance"] == [capture_content["cid"]]


def test_mcp_server_suppresses_initialized_notification_and_frames_stdio(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")
    incoming = StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"missing","arguments":{}}}\n'
    )
    outgoing = StringIO()

    server.serve(incoming, outgoing)
    lines = [line for line in outgoing.getvalue().splitlines() if line.strip()]

    assert len(lines) == 2
    assert '"id":1' in lines[0]
    assert '"id":2' in lines[1]
    assert '"isError":true' in lines[1]


def test_pyproject_exposes_mcp_script_and_postgres_extra() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"]["mneme-mcp"] == "mnemosyne.mcp_server:main"
    assert "psycopg[binary]>=3.2" in project["project"]["optional-dependencies"]["postgres"]


def test_postgres_cid_helpers_and_audit_uuid_guard() -> None:
    cid = "28e581ee79af77abbdfc97e1d9c9c65a7970bbb7bc06858280303c01c70847de"

    assert _bytes_to_cid(_cid_to_bytes(cid)) == cid
    assert _uuid_or_none("019ee1ba-9d93-7ca1-bde5-0afa93e73e98") == "019ee1ba-9d93-7ca1-bde5-0afa93e73e98"
    assert _uuid_or_none(cid) is None
    assert _stable_uuid("tenant", "tenant-a") == _stable_uuid("tenant", "tenant-a")
    assert _stable_uuid("tenant", "tenant-a") != _stable_uuid("tenant", "tenant-b")


def test_postgres_engine_exposes_memory_tools_runtime_surface() -> None:
    required = {
        "retrieve",
        "deep_search",
        "explain",
        "correct",
        "forget",
        "export_tenant",
        "branch",
        "merge",
        "discard",
    }

    assert required <= set(dir(PostgresEngine))
