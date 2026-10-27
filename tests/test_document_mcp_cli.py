"""Comprehensive tests for document revision MCP tools and CLI commands.

Covers:
- MCP tool execution over MemoryTools and MnemosyneMcpServer (JSON-RPC)
- CLI command execution (both grouped `document <cmd>` and hyphenated `document-<cmd>`)
- Signed-session authorization, token binding and tenant isolation checks
- Segment-level change reuse and unchanged-segment deduplication
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

import mnemosyne.cli as cli
from mnemosyne.documents import DocumentConflict
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_server import MnemosyneMcpServer, _to_mcp_tool_spec
from mnemosyne.mcp_tools import TOOL_SPEC, MemoryTools
from mnemosyne.security import SessionIdentity, SessionTokenVerifier
from mnemosyne.sqlite_engine import SqliteEngine


SESSION_SECRET = "test-secret-document-key-12345"


def _make_token(
    tenant_id: str = "tenant-test",
    user_id: str = "owner-alice",
    role: str = "agent",
    trust_tier: int = 1,
    session_id: str = "session-1",
    secret: str = SESSION_SECRET,
) -> str:
    identity = SessionIdentity(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        source_trust_tier=trust_tier,
        session_id=session_id,
    )
    return SessionTokenVerifier(secret).sign(identity)


@pytest.fixture
def local_tools(tmp_path):
    engine = LocalMemoryEngine(tmp_path / "memory.json")
    return MemoryTools(engine)


@pytest.fixture
def sqlite_tools(tmp_path):
    engine = SqliteEngine(tmp_path / "sqlite")
    tools = MemoryTools(engine)
    yield tools
    engine.close()


@pytest.fixture
def mcp_server(tmp_path):
    store_file = tmp_path / "server_store.json"
    server = MnemosyneMcpServer(
        store_path=store_file,
        session_secret=SESSION_SECRET,
        require_session=True,
        object_store=str(tmp_path / "objects"),
    )
    yield server
    server.close()


# ---------------------------------------------------------------------------
# 1. Schema & Specifications
# ---------------------------------------------------------------------------


def test_document_tools_in_tool_spec():
    doc_tools = {tool["name"]: tool for tool in TOOL_SPEC if tool["name"].startswith("document_")}
    assert set(doc_tools.keys()) == {
        "document_create",
        "document_replace",
        "document_append",
        "document_get",
    }
    assert doc_tools["document_create"]["arguments"] == ["tenant_id", "user_id", "document_id", "content"]
    assert doc_tools["document_replace"]["arguments"] == ["tenant_id", "user_id", "document_id", "content", "expected_revision"]
    assert doc_tools["document_append"]["arguments"] == ["tenant_id", "user_id", "document_id", "suffix", "expected_revision"]
    assert doc_tools["document_get"]["arguments"] == ["tenant_id", "user_id", "document_id"]


def test_document_tool_mcp_schemas():
    for name in ("document_create", "document_replace", "document_append", "document_get"):
        spec = next(tool for tool in TOOL_SPEC if tool["name"] == name)
        schema = _to_mcp_tool_spec(spec)["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert "tenant_id" in schema["required"]
        assert "user_id" in schema["required"]
        assert "document_id" in schema["required"]
        if name in {"document_create", "document_replace"}:
            assert "content" in schema["required"]
        if name in {"document_replace", "document_append"}:
            assert "expected_revision" in schema["required"]
            assert schema["properties"]["expected_revision"].get("minimum") == 1
        if name == "document_append":
            assert "suffix" in schema["required"]
        if name == "document_create":
            assert schema["properties"]["chunk_chars"].get("minimum") == 64
            assert schema["properties"]["chunk_chars"].get("maximum") == 16384
            assert schema["properties"]["sensitivity"].get("minimum") == 0
            assert schema["properties"]["sensitivity"].get("maximum") == 3


# ---------------------------------------------------------------------------
# 2. Tool Execution over MemoryTools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tools_fixture", ["local_tools", "sqlite_tools"])
def test_document_lifecycle_create_replace_append_get(request, tools_fixture):
    tools = request.getfixturevalue(tools_fixture)
    tenant = f"tenant-{uuid4().hex[:8]}"
    user = "alice"
    doc_id = "sop-guide"

    # Step A: Get nonexistent document
    view = tools.document_get(tenant_id=tenant, user_id=user, document_id=doc_id)
    assert view == {"found": False, "document_id": doc_id}

    # Step B: Create document with 3 paragraphs (each paragraph ending with blank line)
    content_v1 = "Paragraph 1: Welcome to the team.\n\nParagraph 2: Friday is release day.\n\nParagraph 3: Contact support.\n\n"
    receipt_v1 = tools.document_create(
        tenant_id=tenant,
        user_id=user,
        document_id=doc_id,
        content=content_v1,
        operation_id="op-create-1",
    )
    assert receipt_v1["document_id"] == doc_id
    assert receipt_v1["operation_id"] == "op-create-1"
    assert receipt_v1["action"] == "create"
    assert receipt_v1["revision"] == 1
    assert receipt_v1["created"] == 3
    assert receipt_v1["reused"] == 0
    assert receipt_v1["retired"] == 0

    # Step C: Read back revision 1
    view_v1 = tools.document_get(tenant_id=tenant, user_id=user, document_id=doc_id)
    assert view_v1["found"] is True
    assert view_v1["document_id"] == doc_id
    assert view_v1["revision"] == 1
    assert view_v1["content"] == content_v1
    assert len(view_v1["segment_cids"]) == 3
    cids_v1 = list(view_v1["segment_cids"])

    # Step D: Replace paragraph 2 only (paragraphs 1 and 3 unchanged)
    content_v2 = "Paragraph 1: Welcome to the team.\n\nParagraph 2: Monday is release day.\n\nParagraph 3: Contact support.\n\n"
    receipt_v2 = tools.document_replace(
        tenant_id=tenant,
        user_id=user,
        document_id=doc_id,
        content=content_v2,
        expected_revision=1,
        operation_id="op-replace-2",
    )
    assert receipt_v2["revision"] == 2
    assert receipt_v2["created"] == 1
    assert receipt_v2["reused"] == 2
    assert receipt_v2["retired"] == 1

    view_v2 = tools.document_get(tenant_id=tenant, user_id=user, document_id=doc_id)
    assert view_v2["found"] is True
    assert view_v2["revision"] == 2
    assert view_v2["content"] == content_v2
    cids_v2 = list(view_v2["segment_cids"])
    # Segment 1 and 3 must keep exact CIDs without re-extraction
    assert cids_v2[0] == cids_v1[0]
    assert cids_v2[1] != cids_v1[1]
    assert cids_v2[2] == cids_v1[2]

    # Verify retired segment is retired in storage
    retired_ev = tools.engine.get_evidence(tenant, cids_v1[1])
    assert retired_ev is not None
    assert retired_ev.retired_at is not None

    # Step E: Append a new paragraph
    suffix = "Paragraph 4: Emergency phone numbers.\n\n"
    receipt_v3 = tools.document_append(
        tenant_id=tenant,
        user_id=user,
        document_id=doc_id,
        suffix=suffix,
        expected_revision=2,
        operation_id="op-append-3",
    )
    assert receipt_v3["revision"] == 3
    assert receipt_v3["reused"] == 3
    assert receipt_v3["created"] == 1
    assert receipt_v3["retired"] == 0

    view_v3 = tools.document_get(tenant_id=tenant, user_id=user, document_id=doc_id)
    assert view_v3["revision"] == 3
    assert view_v3["content"] == content_v2 + suffix
    cids_v3 = list(view_v3["segment_cids"])
    assert len(cids_v3) == 4
    assert cids_v3[:3] == cids_v2

    # Step F: CAS conflict detection
    with pytest.raises(DocumentConflict):
        tools.document_replace(
            tenant_id=tenant,
            user_id=user,
            document_id=doc_id,
            content="stale update",
            expected_revision=1,
            operation_id="op-conflict-1",
        )
    with pytest.raises(DocumentConflict):
        tools.document_append(
            tenant_id=tenant,
            user_id=user,
            document_id=doc_id,
            suffix="stale append",
            expected_revision=2,
            operation_id="op-conflict-2",
        )


def test_reader_role_cannot_modify_documents(local_tools):
    tools = local_tools
    tenant = "tenant-reader-test"
    user = "alice"

    with pytest.raises(PermissionError, match="reader role cannot modify documents|denied"):
        tools.document_create(
            tenant_id=tenant,
            user_id=user,
            document_id="doc-1",
            content="test",
            role="reader",
        )


# ---------------------------------------------------------------------------
# 3. MCP JSON-RPC Server Execution & Session Authorization
# ---------------------------------------------------------------------------


def _jsonrpc_call(server: MnemosyneMcpServer, tool_name: str, arguments: dict):
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }
    response = server.handle(request)
    assert response is not None
    assert "result" in response
    return response["result"]


def test_mcp_server_requires_session_token(mcp_server):
    result = _jsonrpc_call(
        mcp_server,
        "document_create",
        {
            "tenant_id": "tenant-a",
            "user_id": "alice",
            "document_id": "doc-1",
            "content": "No token provided",
        },
    )
    assert result.get("isError") is True
    assert "session token required" in result["content"][0]["text"]


def test_mcp_server_validates_tenant_isolation(mcp_server):
    # Session is signed for tenant-a / alice
    token = _make_token(tenant_id="tenant-a", user_id="alice", role="agent")

    # Mismatched tenant must be rejected
    mismatch_tenant = _jsonrpc_call(
        mcp_server,
        "document_create",
        {
            "session_token": token,
            "tenant_id": "tenant-b",
            "user_id": "alice",
            "document_id": "doc-1",
            "content": "Tenant attack",
        },
    )
    assert mismatch_tenant.get("isError") is True
    assert "tenant mismatch" in mismatch_tenant["content"][0]["text"]

    # Mismatched user must be rejected
    mismatch_user = _jsonrpc_call(
        mcp_server,
        "document_create",
        {
            "session_token": token,
            "tenant_id": "tenant-a",
            "user_id": "bob",
            "document_id": "doc-1",
            "content": "User attack",
        },
    )
    assert mismatch_user.get("isError") is True
    assert "user mismatch" in mismatch_user["content"][0]["text"]


def test_mcp_server_full_document_session_flow(mcp_server):
    token = _make_token(tenant_id="tenant-corp", user_id="alice", role="agent")

    # 1. Create document over JSON-RPC
    create_res = _jsonrpc_call(
        mcp_server,
        "document_create",
        {
            "session_token": token,
            "tenant_id": "tenant-corp",
            "user_id": "alice",
            "document_id": "policy-doc",
            "content": "Section 1: Data retention.\n\nSection 2: Erasure timeline.\n\n",
            "operation_id": "op-mcp-create",
        },
    )
    assert not create_res.get("isError"), create_res
    create_payload = json.loads(create_res["content"][0]["text"])
    assert create_payload["document_id"] == "policy-doc"
    assert create_payload["revision"] == 1
    assert create_payload["created"] == 2
    assert create_payload["reused"] == 0

    # 2. Read back over JSON-RPC
    get_res = _jsonrpc_call(
        mcp_server,
        "document_get",
        {
            "session_token": token,
            "tenant_id": "tenant-corp",
            "user_id": "alice",
            "document_id": "policy-doc",
        },
    )
    assert not get_res.get("isError")
    get_payload = json.loads(get_res["content"][0]["text"])
    assert get_payload["found"] is True
    assert get_payload["revision"] == 1
    assert len(get_payload["segment_cids"]) == 2

    # 3. Replace revision 1 with modified section 2
    replace_res = _jsonrpc_call(
        mcp_server,
        "document_replace",
        {
            "session_token": token,
            "tenant_id": "tenant-corp",
            "user_id": "alice",
            "document_id": "policy-doc",
            "content": "Section 1: Data retention.\n\nSection 2: Immediate erasure timeline.\n\n",
            "expected_revision": 1,
            "operation_id": "op-mcp-replace",
        },
    )
    assert not replace_res.get("isError")
    replace_payload = json.loads(replace_res["content"][0]["text"])
    assert replace_payload["revision"] == 2
    assert replace_payload["reused"] == 1
    assert replace_payload["created"] == 1
    assert replace_payload["retired"] == 1

    # 4. Append over JSON-RPC
    append_res = _jsonrpc_call(
        mcp_server,
        "document_append",
        {
            "session_token": token,
            "tenant_id": "tenant-corp",
            "user_id": "alice",
            "document_id": "policy-doc",
            "suffix": "Section 3: Incident response.\n\n",
            "expected_revision": 2,
            "operation_id": "op-mcp-append",
        },
    )
    assert not append_res.get("isError")
    append_payload = json.loads(append_res["content"][0]["text"])
    assert append_payload["revision"] == 3
    assert append_payload["reused"] == 2
    assert append_payload["created"] == 1

    # 5. Cross-user isolation: Bob cannot read Alice's document
    bob_token = _make_token(tenant_id="tenant-corp", user_id="bob", role="agent")
    bob_read = _jsonrpc_call(
        mcp_server,
        "document_get",
        {
            "session_token": bob_token,
            "tenant_id": "tenant-corp",
            "user_id": "bob",
            "document_id": "policy-doc",
        },
    )
    # Bob reading policy-doc in bob scope returns found=False
    bob_payload = json.loads(bob_read["content"][0]["text"])
    assert bob_payload["found"] is False


def test_mcp_server_reader_token_denied_write(mcp_server):
    reader_token = _make_token(tenant_id="tenant-corp", user_id="alice", role="reader")
    res = _jsonrpc_call(
        mcp_server,
        "document_create",
        {
            "session_token": reader_token,
            "tenant_id": "tenant-corp",
            "user_id": "alice",
            "document_id": "reader-doc",
            "content": "Content",
        },
    )
    assert res.get("isError") is True
    assert "reader role" in res["content"][0]["text"]


# ---------------------------------------------------------------------------
# 4. CLI Command Execution
# ---------------------------------------------------------------------------


def test_cli_document_grouped_and_hyphenated(tmp_path, capsys):
    db_file = tmp_path / "cli_test.json"
    tenant = "cli-tenant"
    user = "cli-user"
    doc_id = "runbook"

    # 1. `document create` (grouped)
    code = cli.main([
        "--backend", "local",
        "--store", str(db_file),
        "document", "create",
        "--tenant", tenant,
        "--user", user,
        "--document-id", doc_id,
        "--content", "Step 1: Check metrics.\n\nStep 2: Restart worker.\n\n",
        "--operation-id", "cli-op-1",
    ])
    assert code == 0
    out = capsys.readouterr().out
    receipt = json.loads(out)
    assert receipt["document_id"] == doc_id
    assert receipt["revision"] == 1
    assert receipt["created"] == 2

    # 2. `document get` (grouped)
    code = cli.main([
        "--backend", "local",
        "--store", str(db_file),
        "document", "get",
        "--tenant", tenant,
        "--user", user,
        "--document-id", doc_id,
    ])
    assert code == 0
    view = json.loads(capsys.readouterr().out)
    assert view["found"] is True
    assert view["revision"] == 1
    assert len(view["segment_cids"]) == 2

    # 3. `document-replace` (hyphenated alias)
    code = cli.main([
        "--backend", "local",
        "--store", str(db_file),
        "document-replace",
        "--tenant", tenant,
        "--user", user,
        "--document-id", doc_id,
        "--content", "Step 1: Check metrics.\n\nStep 2: Drain worker gracefully.\n\n",
        "--expected-revision", "1",
        "--operation-id", "cli-op-2",
    ])
    assert code == 0
    rep_receipt = json.loads(capsys.readouterr().out)
    assert rep_receipt["revision"] == 2
    assert rep_receipt["reused"] == 1
    assert rep_receipt["created"] == 1
    assert rep_receipt["retired"] == 1

    # 4. `document append` (grouped)
    code = cli.main([
        "--backend", "local",
        "--store", str(db_file),
        "document", "append",
        "--tenant", tenant,
        "--user", user,
        "--document-id", doc_id,
        "--suffix", "Step 3: Notify Slack.\n\n",
        "--expected-revision", "2",
        "--operation-id", "cli-op-3",
    ])
    assert code == 0
    app_receipt = json.loads(capsys.readouterr().out)
    assert app_receipt["revision"] == 3
    assert app_receipt["reused"] == 2
    assert app_receipt["created"] == 1

    # 5. `document-get` (hyphenated alias)
    code = cli.main([
        "--backend", "local",
        "--store", str(db_file),
        "document-get",
        "--tenant", tenant,
        "--user", user,
        "--document-id", doc_id,
    ])
    assert code == 0
    view3 = json.loads(capsys.readouterr().out)
    assert view3["revision"] == 3
    assert len(view3["segment_cids"]) == 3


def test_cli_signed_session_token_validation(tmp_path, capsys):
    db_file = tmp_path / "cli_session_test.json"
    tenant = "session-tenant"
    user = "session-user"
    secret = "cli-hmac-secret-xyz"

    token = _make_token(tenant_id=tenant, user_id=user, role="agent", secret=secret)

    # Valid token succeeds
    code = cli.main([
        "--backend", "local",
        "--store", str(db_file),
        "--session-token", token,
        "--session-secret", secret,
        "document", "create",
        "--tenant", tenant,
        "--user", user,
        "--document-id", "auth-doc",
        "--content", "Authorized content",
        "--operation-id", "op-cli-auth-1",
    ])
    assert code == 0
    res = json.loads(capsys.readouterr().out)
    assert res["revision"] == 1

    # Mismatched tenant with valid token fails
    with pytest.raises(SystemExit) as exc_info:
        cli.main([
            "--backend", "local",
            "--store", str(db_file),
            "--session-token", token,
            "--session-secret", secret,
            "document", "get",
            "--tenant", "other-tenant",
            "--user", user,
            "--document-id", "auth-doc",
        ])
    assert "session tenant mismatch" in str(exc_info.value)

    # Mismatched user with valid token fails
    with pytest.raises(SystemExit) as exc_info:
        cli.main([
            "--backend", "local",
            "--store", str(db_file),
            "--session-token", token,
            "--session-secret", secret,
            "document", "get",
            "--tenant", tenant,
            "--user", "other-user",
            "--document-id", "auth-doc",
        ])
    assert "session user mismatch" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 5. Unchanged-Segment Deduplication & Consolidation Reuse
# ---------------------------------------------------------------------------


def test_unchanged_segment_deduplication(local_tools):
    tools = local_tools
    tenant = "dedup-tenant"
    user = "alice"
    doc_id = "doc-dedup"

    # Multi-paragraph text
    p1 = "Paragraph 1: The architecture is event-driven.\n\n"
    p2 = "Paragraph 2: The database is PostgreSQL 16.\n\n"
    p3 = "Paragraph 3: Caching uses Redis 7.\n\n"
    p4 = "Paragraph 4: All services communicate over mTLS."

    original_text = p1 + p2 + p3 + p4
    receipt1 = tools.document_create(
        tenant_id=tenant, user_id=user, document_id=doc_id,
        content=original_text, operation_id="dedup-1",
    )
    assert receipt1["revision"] == 1
    assert receipt1["created"] == 4

    v1 = tools.document_get(tenant_id=tenant, user_id=user, document_id=doc_id)
    cids1 = v1["segment_cids"]
    assert len(cids1) == 4

    # Extract initial evidence objects
    ev1 = [tools.engine.get_evidence(tenant, cid) for cid in cids1]
    segment_ids1 = [ev.document_segment_id for ev in ev1]
    assert all(seg_id is not None for seg_id in segment_ids1)

    # Revise ONLY paragraph 2 (P1, P3, P4 are completely identical)
    p2_modified = "Paragraph 2: The database is PostgreSQL 17.\n\n"
    revised_text = p1 + p2_modified + p3 + p4

    receipt2 = tools.document_replace(
        tenant_id=tenant, user_id=user, document_id=doc_id,
        content=revised_text, expected_revision=1, operation_id="dedup-2",
    )
    assert receipt2["revision"] == 2
    assert receipt2["created"] == 1
    assert receipt2["reused"] == 3
    assert receipt2["retired"] == 1

    v2 = tools.document_get(tenant_id=tenant, user_id=user, document_id=doc_id)
    cids2 = v2["segment_cids"]
    assert len(cids2) == 4

    # Unchanged segments must retain EXACT segment IDs and CIDs
    ev2 = [tools.engine.get_evidence(tenant, cid) for cid in cids2]
    segment_ids2 = [ev.document_segment_id for ev in ev2]

    # Index 0 (P1): unchanged
    assert cids2[0] == cids1[0]
    assert segment_ids2[0] == segment_ids1[0]

    # Index 1 (P2): modified -> fresh CID and fresh segment_id
    assert cids2[1] != cids1[1]
    assert segment_ids2[1] != segment_ids1[1]

    # Index 2 (P3): unchanged
    assert cids2[2] == cids1[2]
    assert segment_ids2[2] == segment_ids1[2]

    # Index 3 (P4): unchanged
    assert cids2[3] == cids1[3]
    assert segment_ids2[3] == segment_ids1[3]

    # The old paragraph 2 must be marked retired
    old_p2_ev = tools.engine.get_evidence(tenant, cids1[1])
    assert old_p2_ev.retired_at is not None

    # The unchanged paragraphs must NOT be marked retired
    assert tools.engine.get_evidence(tenant, cids1[0]).retired_at is None
    assert tools.engine.get_evidence(tenant, cids1[2]).retired_at is None
    assert tools.engine.get_evidence(tenant, cids1[3]).retired_at is None


def test_document_operation_id_idempotency_and_conflict(local_tools):
    tools = local_tools
    tenant = "op-idempotent-tenant"
    user = "alice"
    doc_id = "doc-op-test"

    # Initial create with op-create-1
    content_v1 = "Section 1: Initial draft.\n\n"
    receipt1 = tools.document_create(
        tenant_id=tenant, user_id=user, document_id=doc_id,
        content=content_v1, operation_id="op-create-1",
    )
    assert receipt1["revision"] == 1

    # Exact idempotent retry of create with same op-id returns identical receipt
    retry_receipt = tools.document_create(
        tenant_id=tenant, user_id=user, document_id=doc_id,
        content=content_v1, operation_id="op-create-1",
    )
    assert retry_receipt == receipt1

    # Reusing op-create-1 with different content raises DocumentConflict
    with pytest.raises(DocumentConflict, match="operation ID was consumed"):
        tools.document_create(
            tenant_id=tenant, user_id=user, document_id=doc_id,
            content="Different content entirely.\n\n", operation_id="op-create-1",
        )

    # Replace with op-rep-1
    content_v2 = "Section 1: Second draft.\n\n"
    receipt2 = tools.document_replace(
        tenant_id=tenant, user_id=user, document_id=doc_id,
        content=content_v2, expected_revision=1, operation_id="op-rep-1",
    )
    assert receipt2["revision"] == 2

    # Idempotent retry of replace returns identical receipt
    retry_rep = tools.document_replace(
        tenant_id=tenant, user_id=user, document_id=doc_id,
        content=content_v2, expected_revision=1, operation_id="op-rep-1",
    )
    assert retry_rep == receipt2


def test_document_segment_reordering(local_tools):
    tools = local_tools
    tenant = "reorder-tenant"
    user = "alice"
    doc_id = "doc-reorder"

    p1 = "Paragraph Alpha: First section.\n\n"
    p2 = "Paragraph Beta: Second section.\n\n"

    # Create with P1 then P2
    tools.document_create(
        tenant_id=tenant, user_id=user, document_id=doc_id,
        content=p1 + p2, operation_id="reorder-1",
    )
    v1 = tools.document_get(tenant_id=tenant, user_id=user, document_id=doc_id)
    cids1 = v1["segment_cids"]
    assert len(cids1) == 2

    # Replace with P2 then P1 (reordered)
    receipt2 = tools.document_replace(
        tenant_id=tenant, user_id=user, document_id=doc_id,
        content=p2 + p1, expected_revision=1, operation_id="reorder-2",
    )
    assert receipt2["revision"] == 2
    assert receipt2["reused"] == 2
    assert receipt2["created"] == 0
    assert receipt2["retired"] == 0

    v2 = tools.document_get(tenant_id=tenant, user_id=user, document_id=doc_id)
    cids2 = v2["segment_cids"]
    assert cids2 == [cids1[1], cids1[0]]


def test_document_append_tail_merge_replaces_tail(local_tools):
    tools = local_tools
    tenant = "tail-merge-tenant"
    user = "alice"
    doc_id = "doc-tail-merge"

    p1 = "Paragraph 1: Standalone block.\n\n"
    p2 = "Paragraph 2: Incomplete thought"

    tools.document_create(
        tenant_id=tenant, user_id=user, document_id=doc_id,
        content=p1 + p2, operation_id="tail-1",
    )
    v1 = tools.document_get(tenant_id=tenant, user_id=user, document_id=doc_id)
    cids1 = v1["segment_cids"]
    assert len(cids1) == 2

    # Appending suffix extends P2 because P2 lacked a trailing paragraph separator
    receipt2 = tools.document_append(
        tenant_id=tenant, user_id=user, document_id=doc_id,
        suffix=" completed now.\n\n", expected_revision=1, operation_id="tail-2",
    )
    assert receipt2["revision"] == 2
    assert receipt2["reused"] == 1
    assert receipt2["created"] == 1
    assert receipt2["retired"] == 1

    v2 = tools.document_get(tenant_id=tenant, user_id=user, document_id=doc_id)
    cids2 = v2["segment_cids"]
    assert len(cids2) == 2
    # P1 is reused, P2 is replaced
    assert cids2[0] == cids1[0]
    assert cids2[1] != cids1[1]


def test_document_invalid_expected_revision_rejected(local_tools):
    tools = local_tools
    tenant = "invalid-rev-tenant"
    user = "alice"
    doc_id = "doc-rev-check"

    tools.document_create(
        tenant_id=tenant, user_id=user, document_id=doc_id,
        content="Initial content.\n\n", operation_id="rev-1",
    )

    with pytest.raises(ValueError, match="expected_revision must be a positive integer"):
        tools.document_replace(
            tenant_id=tenant, user_id=user, document_id=doc_id,
            content="New content.\n\n", expected_revision=0,
        )

    with pytest.raises(ValueError, match="expected_revision must be a positive integer"):
        tools.document_append(
            tenant_id=tenant, user_id=user, document_id=doc_id,
            suffix="Suffix.\n\n", expected_revision=-1,
        )

