from __future__ import annotations

import asyncio
import base64
import inspect
import json
import shlex
import sys
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path

import pytest

from mnemosyne.mcp_server import MnemosyneMcpServer, build_sdk_server
from mnemosyne.mcp_tools import TOOL_SPEC
from mnemosyne.models import Hit
from mnemosyne.postgres_engine import PostgresEngine, _bytes_to_cid, _cid_to_bytes, _stable_uuid, _uuid_or_none, _vector_literal
from mnemosyne.retrieval import (
    CommandMediaEmbeddingProvider,
    HttpEmbeddingProvider,
    HttpReranker,
    LocalSimilarityReranker,
    semantic_entropy,
)
from mnemosyne.security import SessionIdentity, SessionTokenVerifier


TENANT = "tenant-runtime"
USER = "user-runtime"
PARAMETRIC_AUTH = {"role": "operator", "source_trust_tier": 0}
MCP_SESSION_SECRET = "mnemosyne-mcp-session-secret"


def mcp_call(server: MnemosyneMcpServer, name: str, arguments: dict[str, object]) -> dict:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert response["result"]["isError"] is False, response["result"]["content"][0]["text"]
    return response["result"]["structuredContent"]


def mcp_session_token(
    *,
    tenant_id: str = TENANT,
    user_id: str = USER,
    role: str = "operator",
    source_trust_tier: int = 0,
    session_id: str = "mcp-test-session",
) -> str:
    return SessionTokenVerifier(MCP_SESSION_SECRET).sign(
        SessionIdentity(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,  # type: ignore[arg-type]
            source_trust_tier=source_trust_tier,
            session_id=session_id,
        )
    )


def fake_kms_command(tmp_path: Path) -> tuple[str, Path]:
    state = tmp_path / "kms-state.json"
    script = tmp_path / "fake-kms.py"
    script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import base64, hashlib, json, sys",
                "from pathlib import Path",
                "state = Path(sys.argv[1])",
                "action = sys.argv[2]",
                "request = json.load(sys.stdin)",
                "data = json.loads(state.read_text()) if state.exists() else {'keys': {}}",
                "keys = data.setdefault('keys', {})",
                "key_id = request['key_id']",
                "def save(): state.write_text(json.dumps(data, sort_keys=True), encoding='utf-8')",
                "if action == 'get_or_create_key':",
                "    keys.setdefault(key_id, base64.urlsafe_b64encode(hashlib.sha256(key_id.encode()).digest()).decode('ascii'))",
                "    save()",
                "    print(json.dumps({'key': keys[key_id]}))",
                "elif action == 'get_key':",
                "    if key_id not in keys:",
                "        print('missing key', file=sys.stderr)",
                "        raise SystemExit(4)",
                "    print(json.dumps({'key': keys[key_id]}))",
                "elif action == 'has_key':",
                "    print(json.dumps({'exists': key_id in keys}))",
                "elif action == 'shred_key':",
                "    shredded = keys.pop(key_id, None) is not None",
                "    save()",
                "    print(json.dumps({'shredded': shredded}))",
                "else:",
                "    print('bad action', file=sys.stderr)",
                "    raise SystemExit(2)",
            ]
        ),
        encoding="utf-8",
    )
    command = " ".join(shlex.quote(item) for item in (sys.executable, str(script), str(state)))
    return command, state


def fake_parametric_command(tmp_path: Path) -> tuple[str, Path]:
    state = tmp_path / "parametric-state.json"
    script = tmp_path / "fake-parametric.py"
    script.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json, sys",
                "from pathlib import Path",
                "state = Path(sys.argv[1])",
                "action = sys.argv[2]",
                "request = json.load(sys.stdin)",
                "data = json.loads(state.read_text()) if state.exists() else {'calls': []}",
                "data.setdefault('calls', []).append({'action': action, 'tenant_id': request.get('tenant_id'), 'source_ids': request.get('source_ids')})",
                "state.write_text(json.dumps(data, sort_keys=True), encoding='utf-8')",
                "if action == 'propose':",
                "    print(json.dumps({'adapter_kind': 'test-time-command-adapter', 'artifact_ref': 'provider://' + request['tenant_id'] + '/adapter', 'metrics': {'source_count': len(request['source_ids']), 'rail_count': len(request['immutable_rails'])}, 'metadata': {'lesson_count': len(request['lessons']), 'procedure_count': len(request['procedures'])}}))",
                "elif action == 'rollback':",
                "    print(json.dumps({'rollback_ref': 'provider-rollback-' + request['artifact']['id'], 'metrics': {'provider_rolled_back': 1}}))",
                "else:",
                "    print('bad action', file=sys.stderr)",
                "    raise SystemExit(2)",
            ]
        ),
        encoding="utf-8",
    )
    command = " ".join(shlex.quote(item) for item in (sys.executable, str(script), str(state)))
    return command, state


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


def test_http_retrieval_adapters_fail_closed_on_malformed_provider_responses() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name.
            if self.path == "/embed-zero":
                body = {"embedding": [0.0, 0.0, 0.0]}
            elif self.path == "/rerank-empty":
                body = {"results": []}
            else:
                body = {"results": [{"index": 9, "score": 0.9}]}
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
        with pytest.raises(ValueError, match="non-zero vector"):
            HttpEmbeddingProvider(f"{base}/embed-zero", dims=3).embed("hello")
        with pytest.raises(ValueError, match="at least one scored result"):
            HttpReranker(f"{base}/rerank-empty").rerank(
                "query",
                [Hit("a", "evidence", TENANT, "main", "first", 0.1, "candidate")],
                k=1,
            )
        with pytest.raises(ValueError, match="out of range"):
            HttpReranker(f"{base}/rerank-oob").rerank(
                "query",
                [Hit("a", "evidence", TENANT, "main", "first", 0.1, "candidate")],
                k=1,
            )
        with pytest.raises(ValueError, match="absolute HTTP or HTTPS"):
            HttpEmbeddingProvider("file:///tmp/embed", dims=3).embed("hello")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_command_media_embedding_provider_validates_json_contract(tmp_path: Path) -> None:
    embedder = tmp_path / "embedder.py"
    embedder.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                "request = json.loads(sys.stdin.read())",
                "assert pathlib.Path(sys.argv[1]).read_bytes() == b'media-bytes'",
                "assert request['media_type'] == 'image/png'",
                "print(json.dumps({'embedding': [3.0, 4.0, 0.0, 99.0]}))",
            ]
        ),
        encoding="utf-8",
    )
    embedder.chmod(0o755)

    vector = CommandMediaEmbeddingProvider(str(embedder), dims=3).embed_media(
        b"media-bytes",
        media_type="image/png",
        modality="image",
        metadata={"source": "unit"},
    )

    assert vector == [0.6, 0.8, 0.0]


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
        "parametric_rollback",
        "forget",
        "export",
    }
    tools_by_name = {tool["name"]: tool for tool in listed["result"]["tools"]}
    assert set(tools_by_name) == {item["name"] for item in TOOL_SPEC}
    capture_schema = tools_by_name["capture"]["inputSchema"]
    assert capture_schema["properties"]["trust_tier"]["type"] == "integer"
    assert "trust_tier" not in capture_schema["required"]
    assert capture_schema["additionalProperties"] is False
    assert {"type": "null"} in tools_by_name["search"]["inputSchema"]["properties"]["max_sensitivity"]["anyOf"]
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


def test_official_mcp_sdk_adapter_lists_tools_and_calls_capture_search(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from mcp import types

    server = build_sdk_server(store_path=tmp_path / "sdk-store.json", auth_token="token")

    async def exercise() -> None:
        list_handler = server.request_handlers[types.ListToolsRequest]
        call_handler = server.request_handlers[types.CallToolRequest]
        listed = await list_handler(types.ListToolsRequest())
        tools_by_name = {tool.name: tool for tool in listed.root.tools}

        denied = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "Unauthorized SDK call should fail closed.",
                    },
                }
            )
        )
        invalid = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "auth_token": "token",
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "Invalid SDK call should fail schema validation.",
                        "unexpected": True,
                    },
                }
            )
        )
        captured = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "auth_token": "token",
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "Official MCP SDK captures Mnemosyne memory.",
                        "trust_tier": 3,
                    },
                }
            )
        )
        searched = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "search",
                    "arguments": {
                        "auth_token": "token",
                        "tenant_id": TENANT,
                        "query": "SDK Mnemosyne memory",
                    },
                }
            )
        )

        assert set(tools_by_name) == {item["name"] for item in TOOL_SPEC}
        assert tools_by_name["capture"].inputSchema["additionalProperties"] is False
        assert denied.root.isError is True
        assert "unauthorized" in denied.root.content[0].text
        assert invalid.root.isError is True
        assert "Input validation error" in invalid.root.content[0].text
        assert captured.root.isError is False
        assert captured.root.structuredContent["cid"]
        assert searched.root.isError is False
        assert searched.root.structuredContent["hits"]

    asyncio.run(exercise())


def test_mcp_server_honors_object_encryption_and_residency_config(tmp_path: Path) -> None:
    objects = tmp_path / "objects"
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        object_store=objects,
        object_store_encryption="aesgcm",
        object_key_store=tmp_path / "keys.json",
        allowed_residencies=("local", "eu"),
    )
    ingested = mcp_call(
        server,
        "ingest",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "mcp-upload",
            "data": base64.b64encode(b"mcp private payload bytes").decode("ascii"),
            "modality": "binary",
            "media_type": "application/octet-stream",
            "metadata": {"residency": "eu", "description": "MCP encrypted private payload."},
            "trust_tier": 0,
        },
    )
    raw_objects = [path.read_bytes() for path in objects.rglob("*") if path.is_file()]
    exported = mcp_call(server, "export", {"tenant_id": TENANT})
    evidence = next(item for item in exported["evidence"] if item["cid"] == ingested["cid"])
    rejected = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {
                "name": "ingest",
                "arguments": {
                    "tenant_id": TENANT,
                    "user_id": USER,
                    "actor": "user",
                    "source_type": "mcp-upload",
                    "content": "disallowed residency",
                    "metadata": {"residency": "us"},
                    "trust_tier": 0,
                },
            },
        }
    )
    forgotten = mcp_call(
        server,
        "forget",
        {"tenant_id": TENANT, "cid": ingested["cid"], "erasure_mode": "hard_delete_legal"},
    )

    assert raw_objects
    assert all(b"mcp private payload bytes" not in raw for raw in raw_objects)
    assert evidence["access_policy"]["residency"] == "eu"
    assert "residency:eu" in evidence["capability_tags"]
    assert rejected["result"]["isError"] is True
    assert "not allowed by this runtime" in rejected["result"]["content"][0]["text"]
    assert forgotten["object_shred"]["crypto_shredded"] is True


def test_mcp_server_enforces_cross_region_residency_transfers(tmp_path: Path) -> None:
    denied_server = MnemosyneMcpServer(
        store_path=tmp_path / "denied.json",
        allowed_residencies=("eu", "us"),
        runtime_residency="us",
    )
    denied = denied_server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ingest",
                "arguments": {
                    "tenant_id": TENANT,
                    "user_id": USER,
                    "actor": "user",
                    "source_type": "mcp-upload",
                    "content": "EU data cannot process in US without explicit transfer.",
                    "metadata": {"residency": "eu"},
                    "trust_tier": 0,
                },
            },
        }
    )
    allowed_server = MnemosyneMcpServer(
        store_path=tmp_path / "allowed.json",
        allowed_residencies=("eu", "us"),
        runtime_residency="us",
        allowed_residency_transfers=("eu->us",),
    )
    accepted = mcp_call(
        allowed_server,
        "ingest",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "mcp-upload",
            "content": "EU data can process in US with explicit transfer.",
            "metadata": {"residency": "eu"},
            "trust_tier": 0,
        },
    )
    exported = mcp_call(allowed_server, "export", {"tenant_id": TENANT})
    evidence = next(item for item in exported["evidence"] if item["cid"] == accepted["cid"])

    assert denied["result"]["isError"] is True
    assert "cross-region residency transfer" in denied["result"]["content"][0]["text"]
    assert evidence["access_policy"]["runtime_residency"] == "us"
    assert evidence["access_policy"]["cross_region_transfer"] is True


def test_mcp_server_requires_runtime_residency_when_configured(tmp_path: Path) -> None:
    denied_server = MnemosyneMcpServer(
        store_path=tmp_path / "denied.json",
        allowed_residencies=("eu",),
        require_runtime_residency=True,
    )
    denied = denied_server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ingest",
                "arguments": {
                    "tenant_id": TENANT,
                    "user_id": USER,
                    "actor": "user",
                    "source_type": "mcp-upload",
                    "content": "Runtime residency cannot be omitted in strict mode.",
                    "metadata": {"residency": "eu"},
                    "trust_tier": 0,
                },
            },
        }
    )
    allowed_server = MnemosyneMcpServer(
        store_path=tmp_path / "allowed.json",
        allowed_residencies=("eu",),
        runtime_residency="eu",
        require_runtime_residency=True,
    )
    accepted = mcp_call(
        allowed_server,
        "ingest",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "mcp-upload",
            "content": "Runtime residency is configured in strict mode.",
            "metadata": {"residency": "eu"},
            "trust_tier": 0,
        },
    )
    exported = mcp_call(allowed_server, "export", {"tenant_id": TENANT})
    evidence = next(item for item in exported["evidence"] if item["cid"] == accepted["cid"])

    assert denied["result"]["isError"] is True
    assert "runtime residency is required" in denied["result"]["content"][0]["text"]
    assert evidence["access_policy"]["runtime_residency"] == "eu"
    assert evidence["access_policy"]["cross_region_transfer"] is False


def test_mcp_server_reports_residency_policy(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        allowed_residencies=("eu", "us"),
        runtime_residency="us",
        allowed_residency_transfers=("eu->us",),
        require_runtime_residency=True,
    )
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    policy = mcp_call(server, "residency_policy", {})

    tool_names = {item["name"] for item in tools["result"]["tools"]}
    assert "residency_policy" in tool_names
    assert policy["allowed_residencies"] == ["eu", "us"]
    assert policy["runtime_residency"] == "us"
    assert policy["require_runtime_residency"] is True
    assert policy["allowed_residency_transfers"] == ["eu->us"]
    assert policy["warnings"] == []


def test_mcp_server_can_use_command_key_provider_for_encrypted_objects(tmp_path: Path) -> None:
    objects = tmp_path / "objects"
    command, kms_state = fake_kms_command(tmp_path)
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        object_store=objects,
        object_store_encryption="aesgcm",
        object_key_provider="command",
        object_key_command=command,
    )
    ingested = mcp_call(
        server,
        "ingest",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "mcp-upload",
            "data": base64.b64encode(b"mcp kms private payload").decode("ascii"),
            "modality": "binary",
            "media_type": "application/octet-stream",
            "metadata": {"description": "MCP command-KMS private payload."},
            "trust_tier": 0,
        },
    )
    raw_objects = [path.read_bytes() for path in objects.rglob("*") if path.is_file()]
    before_shred = json.loads(kms_state.read_text(encoding="utf-8"))
    forgotten = mcp_call(
        server,
        "forget",
        {"tenant_id": TENANT, "cid": ingested["cid"], "erasure_mode": "hard_delete_legal"},
    )
    after_shred = json.loads(kms_state.read_text(encoding="utf-8"))

    assert raw_objects
    assert all(b"mcp kms private payload" not in raw for raw in raw_objects)
    assert len(before_shred["keys"]) == 1
    assert after_shred["keys"] == {}
    assert not (objects / ".keys.json").exists()
    assert forgotten["object_shred"]["crypto_shredded"] is True


def test_mcp_server_rejects_non_object_tool_arguments(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search", "arguments": ["not", "an", "object"]},
        }
    )

    assert response["result"]["isError"] is True
    assert "Tool arguments must be a JSON object" in response["result"]["content"][0]["text"]


def test_mcp_server_rejects_schema_invalid_json_rpc_tool_arguments(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")

    invalid_type = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "tenant_id": TENANT,
                    "query": "schema invalid request",
                    "max_sensitivity": "high",
                },
            },
        }
    )
    unexpected_property = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "tenant_id": TENANT,
                    "query": "schema invalid request",
                    "unexpected": True,
                },
            },
        }
    )
    explicit_null = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "tenant_id": TENANT,
                    "query": "schema valid nullable request",
                    "max_sensitivity": None,
                },
            },
        }
    )

    assert invalid_type["result"]["isError"] is True
    assert "Input validation error" in invalid_type["result"]["content"][0]["text"]
    assert unexpected_property["result"]["isError"] is True
    assert "unexpected" in unexpected_property["result"]["content"][0]["text"]
    assert explicit_null["result"]["isError"] is False


def test_mcp_server_stateless_mode_reloads_durable_engine_and_runtime_state(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    writer = MnemosyneMcpServer(store_path=store, stateless=True)
    captured = mcp_call(
        writer,
        "capture",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "actor": "user",
            "source_type": "chat",
            "content": "Stateless MCP reloads durable evidence.",
            "trust_tier": 3,
        },
    )
    mcp_call(
        writer,
        "profile_add",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "kind": "explicit_preference",
            "statement": "Prefer stateless MCP calls backed by durable state.",
        },
    )
    reader = MnemosyneMcpServer(store_path=store, stateless=True)

    search = mcp_call(reader, "search", {"tenant_id": TENANT, "query": "stateless durable evidence"})
    profile = mcp_call(reader, "profile_context", {"tenant_id": TENANT, "user_id": USER})

    assert search["hits"][0]["provenance"] == [captured["cid"]]
    assert profile["authoritative"][0]["statement"] == "Prefer stateless MCP calls backed by durable state."


def test_mcp_server_persists_parametric_artifacts_and_rolls_back(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    server = MnemosyneMcpServer(store_path=store)
    trajectory = mcp_call(
        server,
        "trajectory_record",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "session_id": "session-mcp",
            "task": "MCP parametric rollback",
            "steps": [{"name": "train", "status": "failed", "error": "regression"}],
            "outcome": "failure",
            "reward": -1.0,
            "memory_version": "v1",
        },
    )
    lesson = mcp_call(server, "lesson_propose", {"trajectory_id": trajectory["id"]})
    procedure = mcp_call(server, "procedure_propose", {"lesson_id": lesson["id"]})
    mcp_call(server, "procedure_validate", {"procedure_id": procedure["id"]})
    mcp_call(
        server,
        "lesson_promote",
        {
            "lesson_id": lesson["id"],
            "cases": [
                    {
                        "id": "mcp-parametric-case",
                        "signature": "MCP parametric rollback",
                        "query": "regression verify tools durable memory",
                        "expected_substring": "verify with tools",
                        "protected": True,
                    }
            ],
        },
    )

    artifact = mcp_call(server, "parametric_propose", {"tenant_id": TENANT, **PARAMETRIC_AUTH})
    artifact_path = store.with_suffix(store.suffix + ".parametric") / TENANT / f"{artifact['id']}.json"
    proposal_record = json.loads(artifact_path.read_text(encoding="utf-8"))
    evaluated = mcp_call(
        server,
        "parametric_evaluate",
        {"artifact_uri": artifact["artifact_uri"], **PARAMETRIC_AUTH},
    )
    rolled_back = mcp_call(
        server,
        "parametric_rollback",
        {
            "artifact_uri": artifact["artifact_uri"],
            "reason": "protected regression after MCP proposal",
            **PARAMETRIC_AUTH,
        },
    )
    rollback_record = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert set(artifact["source_ids"]) == {lesson["id"], procedure["id"]}
    assert artifact["artifact_uri"].startswith("local-parametric://")
    assert proposal_record["payload"]["phase"] == "proposal"
    assert evaluated["artifact"]["id"] == artifact["id"]
    assert evaluated["promoted"] is True
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["rollback_ref"].startswith("rollback-")
    assert rollback_record["payload"]["phase"] == "rolled_back"


def test_mcp_server_parametric_tier_can_use_command_provider(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    command, provider_state = fake_parametric_command(tmp_path)
    server = MnemosyneMcpServer(
        store_path=store,
        parametric_provider="command",
        parametric_command=command,
        parametric_adapter_kind="test-time-command-adapter",
    )
    trajectory = mcp_call(
        server,
        "trajectory_record",
        {
            "tenant_id": TENANT,
            "user_id": USER,
            "session_id": "session-mcp-parametric-provider",
            "task": "MCP parametric provider",
            "steps": [{"name": "train", "status": "failed", "error": "provider"}],
            "outcome": "failure",
            "reward": -1.0,
            "memory_version": "v1",
        },
    )
    lesson = mcp_call(server, "lesson_propose", {"trajectory_id": trajectory["id"]})
    procedure = mcp_call(server, "procedure_propose", {"lesson_id": lesson["id"]})
    mcp_call(server, "procedure_validate", {"procedure_id": procedure["id"]})
    mcp_call(
        server,
        "lesson_promote",
        {
            "lesson_id": lesson["id"],
            "cases": [
                {
                    "id": "mcp-parametric-provider-case",
                    "signature": "MCP parametric provider",
                    "query": "provider regression",
                    "expected_substring": "verify with tools",
                    "protected": True,
                }
            ],
        },
    )

    artifact = mcp_call(server, "parametric_propose", {"tenant_id": TENANT, **PARAMETRIC_AUTH})
    artifact_path = store.with_suffix(store.suffix + ".parametric") / TENANT / f"{artifact['id']}.json"
    proposal_record = json.loads(artifact_path.read_text(encoding="utf-8"))
    rolled_back = mcp_call(
        server,
        "parametric_rollback",
        {"artifact_uri": artifact["artifact_uri"], "reason": "provider rollback smoke", **PARAMETRIC_AUTH},
    )
    rollback_record = json.loads(artifact_path.read_text(encoding="utf-8"))
    calls = json.loads(provider_state.read_text(encoding="utf-8"))["calls"]

    assert artifact["adapter_kind"] == "test-time-command-adapter"
    assert artifact["metrics"]["provider_invoked"] == 1.0
    assert artifact["metrics"]["source_count"] == 2.0
    assert proposal_record["payload"]["provider"]["artifact_ref"] == f"provider://{TENANT}/adapter"
    assert rolled_back["rollback_ref"] == f"provider-rollback-{artifact['id']}"
    assert rolled_back["metrics"]["provider_rolled_back"] == 1.0
    assert rollback_record["payload"]["provider"]["rollback_ref"] == f"provider-rollback-{artifact['id']}"
    assert [call["action"] for call in calls] == ["propose", "rollback"]


def test_mcp_parametric_provider_requires_operator_authority(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "mcp-store.json")

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "parametric_propose",
                "arguments": {"tenant_id": TENANT, "role": "agent", "source_trust_tier": 5},
            },
        }
    )

    assert response["result"]["isError"] is True
    assert "policy and safety rails require operator authority" in response["result"]["content"][0]["text"]


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


def test_mcp_server_requires_signed_session_when_configured(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )

    response = server.handle(
        {
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
                    "content": "Unsigned MCP writes must fail closed.",
                },
            },
        }
    )

    assert response["result"]["isError"] is True
    assert "session token required" in response["result"]["content"][0]["text"]


def test_mcp_server_binds_signed_session_and_rejects_tenant_mismatch(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )
    token = mcp_session_token(role="agent", source_trust_tier=3)

    mismatch = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "capture",
                "arguments": {
                    "session_token": token,
                    "tenant_id": "other-tenant",
                    "user_id": USER,
                    "actor": "user",
                    "source_type": "chat",
                    "content": "Tenant mismatch must not be accepted.",
                },
            },
        }
    )
    captured = mcp_call(
        server,
        "capture",
        {
            "session_token": token,
            "actor": "user",
            "source_type": "chat",
            "content": "Signed sessions bind tenant and user for capture.",
        },
    )
    searched = mcp_call(server, "search", {"session_token": token, "query": "bind tenant and user"})

    assert mismatch["result"]["isError"] is True
    assert "session tenant mismatch" in mismatch["result"]["content"][0]["text"]
    assert captured["cid"]
    assert searched["hits"][0]["provenance"] == [captured["cid"]]


def test_mcp_server_accepts_keyring_sessions_and_rejects_revoked_session_ids(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        session_keyring=json.dumps({"current": MCP_SESSION_SECRET}),
        session_key_id="current",
        session_revoked_ids="revoked-session",
        require_session=True,
    )
    allowed_token = SessionTokenVerifier({"current": MCP_SESSION_SECRET}, active_key_id="current").sign(
        SessionIdentity(
            tenant_id=TENANT,
            user_id=USER,
            role="operator",
            source_trust_tier=0,
            session_id="active-session",
        )
    )
    revoked_token = SessionTokenVerifier({"current": MCP_SESSION_SECRET}, active_key_id="current").sign(
        SessionIdentity(
            tenant_id=TENANT,
            user_id=USER,
            role="operator",
            source_trust_tier=0,
            session_id="revoked-session",
        )
    )

    allowed = mcp_call(
        server,
        "capture",
        {
            "session_token": allowed_token,
            "actor": "user",
            "source_type": "chat",
            "content": "Keyring MCP sessions authorize capture.",
        },
    )
    denied = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "capture",
                "arguments": {
                    "session_token": revoked_token,
                    "actor": "user",
                    "source_type": "chat",
                    "content": "Revoked MCP sessions must fail.",
                },
            },
        }
    )

    assert allowed["cid"]
    assert denied["result"]["isError"] is True
    assert "session id is revoked" in denied["result"]["content"][0]["text"]


def test_mcp_server_session_overrides_self_asserted_authority(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json",
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )
    token = mcp_session_token(role="agent", source_trust_tier=5)

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "parametric_propose",
                "arguments": {
                    "session_token": token,
                    "tenant_id": TENANT,
                    "role": "operator",
                    "source_trust_tier": 0,
                },
            },
        }
    )

    assert response["result"]["isError"] is True
    assert "policy and safety rails require operator authority" in response["result"]["content"][0]["text"]


def test_official_mcp_sdk_adapter_binds_signed_session_like_json_rpc(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from mcp import types

    server = build_sdk_server(
        store_path=tmp_path / "sdk-session-store.json",
        session_secret=MCP_SESSION_SECRET,
        require_session=True,
    )
    token = mcp_session_token(role="agent", source_trust_tier=3)

    async def exercise() -> None:
        call_handler = server.request_handlers[types.CallToolRequest]
        denied = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "Unsigned SDK session call must fail.",
                    },
                }
            )
        )
        mismatch = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "session_token": token,
                        "tenant_id": "other-tenant",
                        "user_id": USER,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "SDK tenant mismatch must fail.",
                    },
                }
            )
        )
        captured = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "session_token": token,
                        "actor": "user",
                        "source_type": "sdk",
                        "content": "SDK signed sessions bind Mnemosyne memory.",
                    },
                }
            )
        )
        searched = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "search",
                    "arguments": {
                        "session_token": token,
                        "query": "SDK signed sessions",
                    },
                }
            )
        )

        assert denied.root.isError is True
        assert "session token required" in denied.root.content[0].text
        assert mismatch.root.isError is True
        assert "session tenant mismatch" in mismatch.root.content[0].text
        assert captured.root.isError is False
        assert captured.root.structuredContent["cid"]
        assert searched.root.isError is False
        assert searched.root.structuredContent["hits"][0]["provenance"] == [captured.root.structuredContent["cid"]]

    asyncio.run(exercise())


def test_mcp_server_postgres_backend_requires_dsn(monkeypatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_POSTGRES_DSN", raising=False)

    try:
        MnemosyneMcpServer(backend="postgres")
    except ValueError as exc:
        assert "Postgres MCP backend requires" in str(exc)
    else:  # pragma: no cover - defensive assertion clarity.
        raise AssertionError("postgres MCP backend should require a DSN")


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
