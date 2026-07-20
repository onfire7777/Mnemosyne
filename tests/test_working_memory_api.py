from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest

from mnemosyne import cli
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


def identity(*, role: str = "agent", trust: int = 1, scope: dict[str, str] = SCOPE) -> SessionIdentity:
    return SessionIdentity(
        scope["tenant_id"], scope["user_id"], role, trust,
        agent_id=scope["agent_id"], session_id=scope["session_id"],
    )


def seed(tools: MemoryTools, cid: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        **SCOPE, "kind": "active_goal", "content": "Finish the scoped task",
        "evidence_ids": [cid], "ttl_seconds": 30, "created_at": NOW,
        "role": "agent", "source_trust_tier": 1, "item_id": "working-a",
        "session_identity": identity(),
    }
    values.update(overrides)
    return tools.working_seed(**values)  # type: ignore[arg-type]


def test_tool_spec_and_cli_expose_all_working_operations() -> None:
    names = {item["name"] for item in TOOL_SPEC}
    assert {"working_seed", "working_query", "working_promote", "working_expire"} <= names
    schemas = {item["name"]: _to_mcp_tool_spec(item)["inputSchema"] for item in TOOL_SPEC}
    assert "session_id" in schemas["working_seed"]["required"]
    parser = build_parser()
    common = [
        "--tenant", "tenant-a", "--session-id", "session-a", "--user", "user-a",
        "--agent-id", "agent-a", "--task-id", "task-a", "--branch", "main",
    ]
    commands = {
        "working-seed": (
            [*common, "--kind", "active_goal", "--content", "Finish", "--evidence-cid", "cid-a",
             "--ttl-seconds", "30", "--created-at", NOW.isoformat(), "--source-trust-tier", "1"],
            cli.cmd_working_seed,
        ),
        "working-query": ([*common, "--as-of", NOW.isoformat()], cli.cmd_working_query),
        "working-promote": (
            [*common, "--item-id", "working-a", "--as-of", NOW.isoformat(),
             "--regression-case", '{"id":"case-a"}', "--role", "operator",
             "--source-trust-tier", "0"],
            cli.cmd_working_promote,
        ),
        "working-expire": (
            [*common, "--expired-at", NOW.isoformat(), "--role", "operator",
             "--source-trust-tier", "0"],
            cli.cmd_working_expire,
        ),
    }
    for command, (arguments, handler) in commands.items():
        parsed = parser.parse_args([command, *arguments])
        assert parsed.func is handler
        assert cli._working_scope(parsed) == SCOPE

    promote = parser.parse_args(["working-promote", *commands["working-promote"][0]])
    promote.regression_case = ["[]"]
    with pytest.raises(ValueError, match="JSON object"):
        promote.func(promote)
    promote.regression_case = ["not-json"]
    with pytest.raises(ValueError):
        promote.func(promote)


@pytest.mark.parametrize(
    "command",
    ["working-seed", "working-query", "working-promote", "working-expire"],
)
def test_cli_working_operations_require_verified_session_token(command: str) -> None:
    with pytest.raises(SystemExit, match="requires --session-token"):
        cli._require_authorization_context(argparse.Namespace(command=command))


def test_seed_query_ttl_scope_and_provenance_fail_closed() -> None:
    tools, cid = seeded_tools()
    result = seed(tools, cid)
    assert result["item"]["created_at"] == NOW.isoformat()  # type: ignore[index]
    assert result["item"]["expires_at"] == "2026-07-18T12:00:30+00:00"  # type: ignore[index]
    assert len(tools.working_query(**SCOPE, as_of=NOW, session_identity=identity())["items"]) == 1
    for claim in ("tenant_id", "user_id", "agent_id", "session_id"):
        forged = {**SCOPE, claim: f"{claim}-b"}
        with pytest.raises(PermissionError):
            tools.working_query(**forged, as_of=NOW, session_identity=identity())
    assert tools.working_query(
        **SCOPE, as_of="2026-07-18T12:00:30Z", session_identity=identity()
    )["items"] == []

    for ttl in (0, -1, 86401, True):
        with pytest.raises(ValueError):
            seed(*seeded_tools(), ttl_seconds=ttl)
    with pytest.raises(ValueError):
        seed(*seeded_tools(), evidence_ids=["missing-cid"])

    foreign, foreign_cid = seeded_tools()
    with pytest.raises(PermissionError):
        seed(foreign, foreign_cid, tenant_id="tenant-b")
    foreign.engine.forget("tenant-a", foreign_cid)
    with pytest.raises(ValueError):
        seed(foreign, foreign_cid, item_id="after-erasure")


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("working_seed", {
            **SCOPE, "kind": "active_goal", "content": "Finish",
            "evidence_ids": ["cid"], "ttl_seconds": 30, "created_at": NOW,
        }),
        ("working_query", {**SCOPE, "as_of": NOW}),
        ("working_promote", {
            **SCOPE, "item_id": "working-a", "as_of": NOW, "cases": [{"id": "case"}],
            "role": "operator", "source_trust_tier": 0,
        }),
        ("working_expire", {
            **SCOPE, "expired_at": NOW, "role": "operator", "source_trust_tier": 0,
        }),
    ],
)
def test_working_operations_require_identity_before_engine_access(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    arguments: dict[str, object],
) -> None:
    tools, _ = seeded_tools()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("engine accessed before authentication")

    for method in ("put_working", "list_working", "get_working", "expire_working"):
        monkeypatch.setattr(tools.engine, method, forbidden)
    with pytest.raises(PermissionError):
        getattr(tools, operation)(**arguments)


def test_promote_requires_scope_evidence_and_regression_gate() -> None:
    tools, cid = seeded_tools()
    item_id = seed(tools, cid)["item"]["item_id"]  # type: ignore[index]
    with pytest.raises(PermissionError):
        tools.working_promote(
            **SCOPE, item_id=item_id, as_of=NOW, cases=[], role="operator", source_trust_tier=0,
            session_identity=identity(),
        )
    with pytest.raises(ValueError, match="explicit regression"):
        tools.working_promote(
            **SCOPE, item_id=item_id, as_of=NOW, cases=[], role="operator", source_trust_tier=0,
            session_identity=identity(role="operator", trust=0),
        )
    with pytest.raises(KeyError):
        tools.working_promote(
            **{**SCOPE, "task_id": "task-b"}, item_id=item_id, as_of=NOW,
            cases=[{"id": "case", "signature": "task", "query": "task", "expected_substring": "task"}],
            role="operator", source_trust_tier=0,
            session_identity=identity(role="operator", trust=0),
        )

    denied = tools.working_promote(
        **SCOPE, item_id=item_id, as_of=NOW,
        cases=[{"id": "deny", "signature": "task-a", "query": "task-a", "expected_substring": "never-present", "protected": True}],
        role="operator", source_trust_tier=0,
        session_identity=identity(role="operator", trust=0),
    )
    assert denied["gate"]["promoted"] is False
    assert tools.engine.export_tenant("tenant-a")["assertions"] == []
    assert len(tools.working_query(**SCOPE, as_of=NOW, session_identity=identity())["items"]) == 1

    promoted = tools.working_promote(
        **SCOPE, item_id=item_id, as_of=NOW,
        cases=[{"id": "pass", "signature": "task-a", "query": "Finish", "expected_substring": "Finish"}],
        role="operator", source_trust_tier=0,
        session_identity=identity(role="operator", trust=0),
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
            **SCOPE, expired_at="2026-07-18T12:00:30Z", role="agent", source_trust_tier=1,
            session_identity=identity(),
        )
    result = tools.working_expire(
        **SCOPE, expired_at="2026-07-18T12:00:30Z", role="operator", source_trust_tier=0,
        session_identity=identity(role="operator", trust=0),
    )
    assert [item["item_id"] for item in result["items"]] == ["working-a"]

    server = object.__new__(MnemosyneMcpServer)
    session = SessionIdentity("tenant-a", "user-a", "operator", 1, session_id="session-a")
    prepared = server._bind_session_identity(
        "working_expire", {**SCOPE, "role": "reader", "source_trust_tier": 5}, session
    )
    assert prepared["role"] == "operator"
    assert prepared["source_trust_tier"] == 1
    with pytest.raises(PermissionError, match="session mismatch"):
        server._bind_session_identity("working_query", {**SCOPE, "session_id": "session-b"}, session)


@pytest.mark.parametrize("selector", ["user_id", "agent_id", "task_id", "branch"])
def test_expire_cannot_cross_authenticated_subject_scope(selector: str) -> None:
    tools, cid = seeded_tools()
    seed(tools, cid)
    other_scope = {**SCOPE, selector: f"{selector}-b"}
    other_cid = tools.engine.append_evidence(
        Evidence(
            tenant_id="tenant-a", user_id=other_scope["user_id"], actor="user",
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
        session_identity=identity(scope=other_scope),
    )

    result = tools.working_expire(
        **SCOPE, expired_at="2026-07-18T12:00:30Z", role="operator", source_trust_tier=0,
        session_identity=identity(role="operator", trust=0),
    )

    assert [item["item_id"] for item in result["items"]] == ["working-a"]
    assert tools.working_query(**SCOPE, as_of=NOW, session_identity=identity())["items"] == []
    assert [item["item_id"] for item in tools.working_query(
        **other_scope, as_of=NOW, session_identity=identity(scope=other_scope)
    )["items"]] == [
        "working-b"
    ]
    assert tools.working_expire(
        **SCOPE, expired_at="2026-07-18T12:00:30Z", role="operator", source_trust_tier=0,
        session_identity=identity(role="operator", trust=0),
    )["items"] == []
