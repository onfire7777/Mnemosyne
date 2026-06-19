from __future__ import annotations

import inspect
import json
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path

from mnemosyne.mcp_server import MnemosyneMcpServer
from mnemosyne.models import Hit
from mnemosyne.postgres_engine import PostgresEngine, _bytes_to_cid, _cid_to_bytes, _stable_uuid, _uuid_or_none, _vector_literal
from mnemosyne.retrieval import HttpEmbeddingProvider, HttpReranker, LocalSimilarityReranker, semantic_entropy


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


def test_http_embedding_and_reranker_adapters_use_json_provider_contract() -> None:
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name.
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append({"path": self.path, "payload": payload, "auth": self.headers.get("Authorization")})
            if self.path == "/embed":
                body = {"data": [{"embedding": [3.0, 4.0, 0.0, 99.0]}]}
            else:
                body = {"results": [{"index": 1, "relevance_score": 0.91}, {"index": 0, "relevance_score": 0.2}]}
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature.
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        embedding = HttpEmbeddingProvider(f"{base}/embed", model="embed-model", api_key="secret", dims=3)
        vector = embedding.embed("hello")
        reranker = HttpReranker(f"{base}/rerank", model="rank-model")
        ranked = reranker.rerank(
            "query",
            [
                Hit("a", "evidence", TENANT, "main", "first", 0.1, "candidate"),
                Hit("b", "evidence", TENANT, "main", "second", 0.1, "candidate"),
            ],
            k=2,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert vector == [0.6, 0.8, 0.0]
    assert [hit.id for hit in ranked] == ["b", "a"]
    assert requests[0]["auth"] == "Bearer secret"
    assert requests[0]["payload"] == {"input": "hello", "model": "embed-model"}
    assert requests[1]["payload"]["model"] == "rank-model"


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
        "graph_neighbors",
        "trajectory_log",
        "lesson_induce",
        "procedure_induce",
        "lesson_promote",
        "procedure_validate",
        "parametric_propose",
        "parametric_evaluate",
        "forget",
        "export",
    }
    tools_by_name = {tool["name"]: tool for tool in listed["result"]["tools"]}
    capture_schema = tools_by_name["capture"]["inputSchema"]
    assert capture_schema["properties"]["trust_tier"]["type"] == "integer"
    assert "trust_tier" not in capture_schema["required"]
    assert capture_schema["additionalProperties"] is False
    graph_schema = tools_by_name["graph_query"]["inputSchema"]
    assert graph_schema["properties"]["seeds"] == {"type": "array", "items": {"type": "string"}}
    assert graph_schema["properties"]["hops"]["type"] == "integer"
    assert "hops" not in graph_schema["required"]
    supersede_schema = tools_by_name["supersede"]["inputSchema"]
    assert supersede_schema["properties"]["new"]["type"] == "object"
    assert "branch" not in supersede_schema["required"]
    assert capture["result"]["isError"] is False
    assert search["result"]["isError"] is False
    capture_content = capture["result"]["structuredContent"]
    search_content = search["result"]["structuredContent"]
    assert capture_content["cid"]
    assert search_content["hits"]
    assert search_content["hits"][0]["provenance"] == [capture_content["cid"]]


def test_mcp_server_requires_configured_auth_token_for_tool_calls(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json", auth_token="secret-token")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "capture",
            "arguments": {
                "tenant_id": TENANT,
                "user_id": USER,
                "actor": "user",
                "source_type": "chat",
                "content": "Authenticated MCP writes are accepted.",
            },
        },
    }

    denied = server.handle(request)
    request["params"]["_meta"] = {"auth_token": "secret-token"}
    allowed = server.handle(request)

    assert denied["result"]["isError"] is True
    assert "auth token required" in denied["result"]["content"][0]["text"]
    assert allowed["result"]["isError"] is False
    assert allowed["result"]["structuredContent"]["cid"]


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
    assert _vector_literal([0.25, -0.5, 1.0]) == "[0.25,-0.5,1]"


def test_postgres_adapter_uses_sql_retrieval_backends() -> None:
    source = inspect.getsource(PostgresEngine)

    assert "plainto_tsquery('english'" in source
    assert "embedding <=> %s::vector" in source
    assert "postgres_graph_ppr" in source
    assert "return []" not in inspect.getsource(PostgresEngine.vector_search)
    assert "del seeds" not in inspect.getsource(PostgresEngine.graph_ppr)
    assert "FROM relations" in inspect.getsource(PostgresEngine.graph_ppr)


def test_postgres_adapter_sets_rls_tenant_context() -> None:
    source = inspect.getsource(PostgresEngine)

    assert "set_config('mnemosyne.tenant_id'" in source
    assert "PostgresEngine.branch requires tenant_id" in source
    assert "PostgresEngine.merge requires tenant_id" in source
    assert "PostgresEngine.discard requires tenant_id" in source


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
