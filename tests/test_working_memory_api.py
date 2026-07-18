from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mnemosyne.cli import build_parser
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_server import MnemosyneMcpServer, _to_mcp_tool_spec
from mnemosyne.mcp_tools import TOOL_SPEC, MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.security import SessionIdentity


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
SCOPE = {
    "tenant_id": "tenant-a",
    "session_id": "session-a",
    "user_id": "user-a",
    "agent_id": "agent-a",
    "task_id": "task-a",
    "branch": "main",
}


def seeded_tools() -> tuple[MemoryTools, str]:
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id="tenant-a", user_id="user-a", actor="user",
            source_type="episode", content="Finish the scoped task",
            session_id="session-a", trust_tier=1, access_policy={"tenant": "tenant-a"},
        )
    )
    return MemoryTools(engine), cid


def seed(tools: MemoryTools, cid: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        **SCOPE, "kind": "active_goal", "content": "Finish the scoped task",
        "evidence_ids": [cid], "ttl_seconds": 30, "created_at": NOW,
        "role": "agent", "source_trust_tier": 1, "item_id": "working-a",
    }
    values.update(overrides)
    return tools.working_seed(**values)  # type: ignore[arg-type]


def test_tool_spec_and_cli_expose_all_working_operations() -> None:
    names = {item["name"] for item in TOOL_SPEC}
    assert {"working_seed", "working_query", "working_promote", "working_expire"} <= names
    schemas = {item["name"]: _to_mcp_tool_spec(item)["inputSchema"] for item in TOOL_SPEC}
    assert "session_id" in schemas["working_seed"]["required"]
    parser = build_parser()
    for command in ("working-seed", "working-query", "working-promote", "working-expire"):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args([command])
        assert exc.value.code == 2


def test_seed_query_ttl_scope_and_provenance_fail_closed() -> None:
    tools, cid = seeded_tools()
    result = seed(tools, cid)
    assert result["item"]["created_at"] == NOW.isoformat()  # type: ignore[index]
    assert result["item"]["expires_at"] == "2026-07-18T12:00:30+00:00"  # type: ignore[index]
    assert len(tools.working_query(**SCOPE, as_of=NOW)["items"]) == 1
    assert tools.working_query(**{**SCOPE, "tenant_id": "tenant-b"}, as_of=NOW)["items"] == []
    assert tools.working_query(**{**SCOPE, "user_id": "user-b"}, as_of=NOW)["items"] == []
    assert tools.working_query(**SCOPE, as_of="2026-07-18T12:00:30Z")["items"] == []

    for ttl in (0, -1, 86401, True):
        with pytest.raises(ValueError):
            seed(*seeded_tools(), ttl_seconds=ttl)
    with pytest.raises(ValueError):
        seed(*seeded_tools(), evidence_ids=["missing-cid"])

    foreign, foreign_cid = seeded_tools()
    with pytest.raises(ValueError):
        seed(foreign, foreign_cid, tenant_id="tenant-b")
    foreign.engine.forget("tenant-a", foreign_cid)
    with pytest.raises(ValueError):
        seed(foreign, foreign_cid, item_id="after-erasure")


def test_promote_requires_scope_evidence_and_regression_gate() -> None:
    tools, cid = seeded_tools()
    item_id = seed(tools, cid)["item"]["item_id"]  # type: ignore[index]
    with pytest.raises(PermissionError):
        tools.working_promote(
            **SCOPE, item_id=item_id, as_of=NOW, cases=[], role="agent", source_trust_tier=1
        )
    with pytest.raises(ValueError, match="explicit regression"):
        tools.working_promote(
            **SCOPE, item_id=item_id, as_of=NOW, cases=[], role="operator", source_trust_tier=0
        )
    with pytest.raises(KeyError):
        tools.working_promote(
            **{**SCOPE, "task_id": "task-b"}, item_id=item_id, as_of=NOW,
            cases=[{"id": "case", "signature": "task", "query": "task", "expected_substring": "task"}],
            role="operator", source_trust_tier=0,
        )

    denied = tools.working_promote(
        **SCOPE, item_id=item_id, as_of=NOW,
        cases=[{"id": "deny", "signature": "task-a", "query": "task-a", "expected_substring": "never-present", "protected": True}],
        role="operator", source_trust_tier=0,
    )
    assert denied["gate"]["promoted"] is False
    assert tools.engine.export_tenant("tenant-a")["assertions"] == []
    assert len(tools.working_query(**SCOPE, as_of=NOW)["items"]) == 1

    promoted = tools.working_promote(
        **SCOPE, item_id=item_id, as_of=NOW,
        cases=[{"id": "pass", "signature": "task-a", "query": "Finish", "expected_substring": "Finish"}],
        role="operator", source_trust_tier=0,
    )
    assert promoted["gate"]["promoted"] is True
    assertions = tools.engine.export_tenant("tenant-a")["assertions"]
    assert all(
        (item["subject"], item["predicate"], item["object"])
        == ("task-a", "active_goal", "Finish the scoped task")
        for item in assertions
    )


def test_expire_is_authorized_deterministic_and_session_bound() -> None:
    tools, cid = seeded_tools()
    seed(tools, cid)
    with pytest.raises(PermissionError):
        tools.working_expire(
            **SCOPE, expired_at="2026-07-18T12:00:30Z", role="agent", source_trust_tier=1
        )
    result = tools.working_expire(
        **SCOPE, expired_at="2026-07-18T12:00:30Z", role="operator", source_trust_tier=0
    )
    assert [item["item_id"] for item in result["items"]] == ["working-a"]

    server = object.__new__(MnemosyneMcpServer)
    identity = SessionIdentity("tenant-a", "user-a", "operator", 1, session_id="session-a")
    prepared = server._bind_session_identity(
        "working_expire", {**SCOPE, "role": "reader", "source_trust_tier": 5}, identity
    )
    assert prepared["role"] == "operator"
    assert prepared["source_trust_tier"] == 1
    with pytest.raises(PermissionError, match="session mismatch"):
        server._bind_session_identity("working_query", {**SCOPE, "session_id": "session-b"}, identity)


def test_expire_cannot_cross_authenticated_subject_scope() -> None:
    tools, cid = seeded_tools()
    seed(tools, cid)
    other_scope = {
        **SCOPE,
        "user_id": "user-b",
        "agent_id": "agent-b",
        "task_id": "task-b",
    }
    other_cid = tools.engine.append_evidence(
        Evidence(
            tenant_id="tenant-a", user_id="user-b", actor="user",
            source_type="episode", content="Preserve the other scoped task",
            session_id="session-a", trust_tier=1, access_policy={"tenant": "tenant-a"},
        )
    )
    seed(
        tools,
        other_cid,
        **other_scope,
        item_id="working-b",
        content="Preserve the other scoped task",
    )

    result = tools.working_expire(
        **SCOPE, expired_at="2026-07-18T12:00:30Z", role="operator", source_trust_tier=0
    )

    assert [item["item_id"] for item in result["items"]] == ["working-a"]
    assert tools.working_query(**SCOPE, as_of=NOW)["items"] == []
    assert [item["item_id"] for item in tools.working_query(**other_scope, as_of=NOW)["items"]] == [
        "working-b"
    ]
    assert tools.working_expire(
        **SCOPE, expired_at="2026-07-18T12:00:30Z", role="operator", source_trust_tier=0
    )["items"] == []
