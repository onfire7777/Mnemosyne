from __future__ import annotations

import gc
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mnemosyne import cli
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_server import MnemosyneMcpServer
from mnemosyne.mcp_tools import TOOL_SPEC, MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.security import (
    OidcAuthorizationPolicy,
    PROSPECTIVE_SCHEDULER_CAPABILITY,
    SessionIdentity,
    SessionTokenVerifier,
    TrustTier,
    WriteRole,
)

TENANT = "tenant-a"
USER = "user-a"
AGENT = "agent-a"
SESSION_SECRET = "prospective-memory-session-secret"
ACTION = {"kind": "notify", "message": "Call the customer; data only"}
OPERATING_POINT = {
    "operating_point_id": "api-op-v1",
    "threshold": 0.8,
    "measured_precision": 0.95,
    "measured_recall": 0.9,
    "measurement_cid": "cid-api-op-v1",
}
EMPTY_CONTEXT = {"infrastructure_available": True, "events": [], "conditions": {}}


def _identity(
    *,
    user_id: str = USER,
    role: WriteRole = "agent",
    capabilities: tuple[str, ...] = (),
) -> SessionIdentity:
    return SessionIdentity(
        tenant_id=TENANT,
        user_id=user_id,
        role=role,
        source_trust_tier=int(TrustTier.NORMAL),
        capabilities=capabilities,
    )


def _token(**kwargs: Any) -> str:
    return SessionTokenVerifier(SESSION_SECRET).sign(_identity(**kwargs))


def _seed_evidence(
    engine: LocalMemoryEngine,
    *,
    user_id: str = USER,
    content: str = "Call the customer",
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=user_id,
            actor="user",
            source_type="episode",
            content=content,
            trust_tier=1,
            access_policy={"tenant": TENANT},
        )
    )


def _server(tmp_path: Path, *, stateless: bool = False) -> MnemosyneMcpServer:
    return MnemosyneMcpServer(
        store_path=tmp_path / "mcp-store.json",
        auth_token="",
        session_secret=SESSION_SECRET,
        require_session=True,
        stateless=stateless,
    )


def _mcp_call(
    server: MnemosyneMcpServer,
    name: str,
    arguments: dict[str, Any],
    *,
    token: str | None = None,
) -> dict[str, Any]:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
                "session_token": token or _token(),
            },
        }
    )
    assert response is not None
    return response["result"]


def _schedule_arguments(
    evidence_id: str,
    due_at: str,
    *,
    user_id: str = USER,
    trigger_type: str = "exact_time",
    trigger_expression: dict[str, Any] | None = None,
    dependencies: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "tenant_id": TENANT,
        "user_id": user_id,
        "agent_id": AGENT,
        "trigger_type": trigger_type,
        "trigger_expression": trigger_expression or {"at": due_at},
        "action": ACTION,
        "due_at": due_at,
        "evidence_ids": [evidence_id],
        "dependencies": dependencies or [],
    }


def _evaluate_arguments(evaluated_at: str) -> dict[str, Any]:
    return {
        "tenant_id": TENANT,
        "evaluated_at": evaluated_at,
        "trigger_context": EMPTY_CONTEXT,
        "operating_point": OPERATING_POINT,
    }


def _cli_auth(token: str) -> list[str]:
    return ["--session-token", token, "--session-secret", SESSION_SECRET]


def _run_cli(
    capsys: pytest.CaptureFixture[str], store: Path, token: str, *arguments: str
) -> dict[str, Any]:
    assert cli.main(["--store", str(store), *_cli_auth(token), *arguments]) == 0
    return json.loads(capsys.readouterr().out)


def _cli_schedule(evidence_id: str, due_at: str) -> list[str]:
    return [
        "intention-schedule",
        "--tenant",
        TENANT,
        "--user",
        USER,
        "--agent",
        AGENT,
        "--trigger-expression",
        json.dumps({"at": due_at}),
        "--action",
        json.dumps(ACTION),
        "--due-at",
        due_at,
        "--evidence-cid",
        evidence_id,
    ]


def test_cli_requires_signed_identity_and_preserves_timezone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "cli-store.json"
    evidence_id = _seed_evidence(LocalMemoryEngine(store))
    due_at = (datetime.now(UTC) + timedelta(hours=1)).astimezone().isoformat()
    with pytest.raises(SystemExit, match="requires --session-token"):
        cli.main(["--store", str(store), *_cli_schedule(evidence_id, due_at)])

    scheduled = _run_cli(capsys, store, _token(), *_cli_schedule(evidence_id, due_at))
    listed = _run_cli(
        capsys, store, _token(role="reader"), "intention-list", "--tenant", TENANT
    )
    assert datetime.fromisoformat(scheduled["due_at"]) == datetime.fromisoformat(due_at)
    assert listed["intentions"] == [scheduled]


def test_cli_evaluate_requires_scheduler_and_explicit_context(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "cli-store.json"
    evidence_id = _seed_evidence(LocalMemoryEngine(store))
    due_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    _run_cli(capsys, store, _token(), *_cli_schedule(evidence_id, due_at))
    evaluated_at = datetime.now(UTC).isoformat()
    evaluate = [
        "intention-evaluate",
        "--tenant",
        TENANT,
        "--evaluated-at",
        evaluated_at,
        "--trigger-context",
        json.dumps(EMPTY_CONTEXT),
        "--operating-point",
        json.dumps(OPERATING_POINT),
    ]
    with pytest.raises(PermissionError, match="scheduler capability"):
        cli.main(["--store", str(store), *_cli_auth(_token()), *evaluate])
    fired = _run_cli(
        capsys,
        store,
        _token(role="operator", capabilities=(PROSPECTIVE_SCHEDULER_CAPABILITY,)),
        *evaluate,
    )
    assert [item["status"] for item in fired["intentions"]] == ["fired"]


def test_direct_api_denies_unsigned_and_reader_mutation(tmp_path: Path) -> None:
    engine = LocalMemoryEngine(tmp_path / "store.json")
    evidence_id = _seed_evidence(engine)
    tools = MemoryTools(engine)
    due_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    arguments = _schedule_arguments(evidence_id, due_at)
    with pytest.raises(PermissionError, match="verified session identity"):
        tools.schedule_intention(**arguments)
    with pytest.raises(PermissionError, match="reader role"):
        tools.schedule_intention(**arguments, session_identity=_identity(role="reader"))
    assert engine.list_intentions(TENANT) == []


def test_mcp_rejects_body_authority_and_binds_claims(tmp_path: Path) -> None:
    server = _server(tmp_path)
    evidence_id = _seed_evidence(server.engine)
    due_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    arguments = _schedule_arguments(evidence_id, due_at)
    assert _mcp_call(server, "schedule_intention", {**arguments, "role": "operator"})[
        "isError"
    ] is True
    assert _mcp_call(
        server, "schedule_intention", {**arguments, "capabilities": [PROSPECTIVE_SCHEDULER_CAPABILITY]}
    )["isError"] is True
    mismatch = _mcp_call(server, "schedule_intention", {**arguments, "user_id": "user-b"})
    assert mismatch["isError"] is True
    assert "session user mismatch" in mismatch["content"][0]["text"]


def test_all_five_trigger_types_round_trip(tmp_path: Path) -> None:
    server = _server(tmp_path)
    evidence_id = _seed_evidence(server.engine)
    due = datetime.now(UTC) + timedelta(hours=1)
    cases = [
        ("exact_time", {"at": due.isoformat()}, []),
        (
            "time_window",
            {"start": due.isoformat(), "end": (due + timedelta(hours=1)).isoformat()},
            [],
        ),
        ("event", {"event_type": "report.ready", "match": {"kind": "final"}}, []),
        ("condition", {"condition_id": "quota", "operator": "gte", "value": 10}, []),
    ]
    scheduled: list[dict[str, Any]] = []
    for trigger_type, expression, dependencies in cases:
        result = _mcp_call(
            server,
            "schedule_intention",
            _schedule_arguments(
                evidence_id,
                due.isoformat(),
                trigger_type=trigger_type,
                trigger_expression=expression,
                dependencies=dependencies,
            ),
        )
        assert result["isError"] is False
        scheduled.append(result["structuredContent"])
    dependency = _mcp_call(
        server,
        "schedule_intention",
        _schedule_arguments(
            evidence_id,
            due.isoformat(),
            trigger_type="dependency_completion",
            trigger_expression={"require": "all"},
            dependencies=[scheduled[0]["intention_id"]],
        ),
    )
    assert dependency["isError"] is False
    assert {item["trigger_type"] for item in [*scheduled, dependency["structuredContent"]]} == {
        "exact_time",
        "time_window",
        "event",
        "condition",
        "dependency_completion",
    }


def test_scheduler_only_evaluate_and_fail_closed_context(tmp_path: Path) -> None:
    server = _server(tmp_path)
    evidence_id = _seed_evidence(server.engine)
    due_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    scheduled = _mcp_call(server, "schedule_intention", _schedule_arguments(evidence_id, due_at))
    assert scheduled["isError"] is False
    denied = _mcp_call(server, "evaluate_intentions", _evaluate_arguments(datetime.now(UTC).isoformat()))
    assert denied["isError"] is True
    unavailable = _evaluate_arguments(datetime.now(UTC).isoformat())
    unavailable["trigger_context"] = {**EMPTY_CONTEXT, "infrastructure_available": False}
    scheduler = _token(role="operator", capabilities=(PROSPECTIVE_SCHEDULER_CAPABILITY,))
    failed = _mcp_call(server, "evaluate_intentions", unavailable, token=scheduler)
    assert failed["isError"] is True
    listed = _mcp_call(server, "list_intentions", {"tenant_id": TENANT})
    assert listed["structuredContent"]["intentions"][0]["status"] == "scheduled"


def test_evaluate_serializes_context_and_operating_point_for_event(tmp_path: Path) -> None:
    server = _server(tmp_path)
    evidence_id = _seed_evidence(server.engine)
    due = datetime.now(UTC) - timedelta(minutes=1)
    scheduled = _mcp_call(
        server,
        "schedule_intention",
        _schedule_arguments(
            evidence_id,
            due.isoformat(),
            trigger_type="event",
            trigger_expression={"event_type": "report.ready", "match": {"kind": "final"}},
        ),
    )
    assert scheduled["isError"] is False
    arguments = _evaluate_arguments(datetime.now(UTC).isoformat())
    arguments["trigger_context"] = {
        "infrastructure_available": True,
        "events": [
            {
                "event_id": "evt-1",
                "event_type": "report.ready",
                "occurred_at": due.isoformat(),
                "payload": {"kind": "final"},
                "confidence": 0.9,
            }
        ],
        "conditions": {},
    }
    result = _mcp_call(
        server,
        "evaluate_intentions",
        arguments,
        token=_token(role="operator", capabilities=(PROSPECTIVE_SCHEDULER_CAPABILITY,)),
    )
    assert result["structuredContent"]["intentions"][0]["status"] == "fired"
    audit = [item for item in server.engine.audit_log if item["op"] == "fire_intention"][-1]
    assert audit["diff"]["operating_point"] == OPERATING_POINT


def test_list_is_subject_scoped(tmp_path: Path) -> None:
    server = _server(tmp_path)
    first = _seed_evidence(server.engine)
    second = _seed_evidence(server.engine, user_id="user-b", content="Second reminder")
    due_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert _mcp_call(server, "schedule_intention", _schedule_arguments(first, due_at))["isError"] is False
    assert _mcp_call(
        server,
        "schedule_intention",
        _schedule_arguments(second, due_at, user_id="user-b"),
        token=_token(user_id="user-b"),
    )["isError"] is False
    own = _mcp_call(server, "list_intentions", {"tenant_id": TENANT})
    other = _mcp_call(
        server,
        "list_intentions",
        {"tenant_id": TENANT},
        token=_token(user_id="user-b", role="reader"),
    )
    assert [item["user_id"] for item in own["structuredContent"]["intentions"]] == [USER]
    assert [item["user_id"] for item in other["structuredContent"]["intentions"]] == ["user-b"]


def test_signed_cancellation_principal_is_bound(tmp_path: Path) -> None:
    server = _server(tmp_path)
    evidence_id = _seed_evidence(server.engine)
    due_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    scheduled = _mcp_call(server, "schedule_intention", _schedule_arguments(evidence_id, due_at))[
        "structuredContent"
    ]
    mismatch = _mcp_call(
        server,
        "cancel_intention",
        {"tenant_id": TENANT, "intention_id": scheduled["intention_id"], "cancelled_by": "user-b"},
    )
    assert mismatch["isError"] is True
    cancelled = _mcp_call(
        server, "cancel_intention", {"tenant_id": TENANT, "intention_id": scheduled["intention_id"]}
    )
    assert cancelled["structuredContent"]["cancellation_state"] == {"cancelled_by": USER}


def test_stateless_local_writes_are_serialized_and_subject_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "mcp-store.json"
    seed_engine = LocalMemoryEngine(store)
    evidence_ids = {
        user_id: _seed_evidence(seed_engine, user_id=user_id, content=user_id)
        for user_id in (USER, "user-b")
    }
    del seed_engine
    gc.collect()
    server = _server(tmp_path, stateless=True)
    due_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    barrier = threading.Barrier(2)
    guard = threading.Lock()
    active = 0
    maximum = 0
    original = LocalMemoryEngine._persist

    def monitored(engine: LocalMemoryEngine) -> None:
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(0.03)
            original(engine)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(LocalMemoryEngine, "_persist", monitored)

    def schedule(user_id: str) -> dict[str, Any]:
        barrier.wait()
        return server.call_tool(
            "schedule_intention",
            {
                **_schedule_arguments(evidence_ids[user_id], due_at, user_id=user_id),
                "session_identity": _identity(user_id=user_id),
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(schedule, (USER, "user-b")))
    assert [item["status"] for item in results] == ["scheduled", "scheduled"]
    assert maximum == 1
    own = server.call_tool(
        "list_intentions", {"tenant_id": TENANT, "session_identity": _identity()}
    )
    assert [item["user_id"] for item in own["intentions"]] == [USER]


def test_policy_rollout_detects_capability_only_grant_and_revoke() -> None:
    base = {
        "allowed_client_ids": ["client-a"],
        "rules": [
            {
                "claim_equals": {"group": "scheduler"},
                "required_acr": "urn:mnemosyne:mfa",
                "required_amr": "mfa",
                "max_auth_age_seconds": 300,
                "role": "agent",
                "source_trust_tier": int(TrustTier.NORMAL),
            }
        ],
    }
    granted = json.loads(json.dumps(base))
    granted["rules"][0]["capabilities"] = [PROSPECTIVE_SCHEDULER_CAPABILITY]
    simulation = {
        "payload": {
            "azp": "client-a",
            "group": "scheduler",
            "acr": "urn:mnemosyne:mfa",
            "amr": ["pwd", "mfa"],
            "auth_time": 1_900_000_000,
        },
        "tenant_id": TENANT,
        "user_id": USER,
        "now": 1_900_000_100,
    }
    current = cli._policy_authorization_outcome(OidcAuthorizationPolicy.from_mapping(base), simulation)
    candidate = cli._policy_authorization_outcome(
        OidcAuthorizationPolicy.from_mapping(granted), simulation
    )
    assert current["capabilities"] == []
    assert candidate["capabilities"] == [PROSPECTIVE_SCHEDULER_CAPABILITY]
    assert current != candidate
    assert cli._policy_authorization_outcome(
        OidcAuthorizationPolicy.from_mapping(base), simulation
    ) == current


def test_timezone_and_malformed_evaluation_fail_closed(tmp_path: Path) -> None:
    server = _server(tmp_path)
    evidence_id = _seed_evidence(server.engine)
    due = datetime.now(UTC) - timedelta(minutes=1)
    assert _mcp_call(server, "schedule_intention", _schedule_arguments(evidence_id, due.isoformat()))[
        "isError"
    ] is False
    scheduler = _token(role="operator", capabilities=(PROSPECTIVE_SCHEDULER_CAPABILITY,))
    naive = _evaluate_arguments(datetime.now().replace(microsecond=0).isoformat())
    assert _mcp_call(server, "evaluate_intentions", naive, token=scheduler)["isError"] is True
    malformed = _evaluate_arguments(datetime.now(UTC).isoformat())
    malformed["operating_point"] = {**OPERATING_POINT, "threshold": 2.0}
    assert _mcp_call(server, "evaluate_intentions", malformed, token=scheduler)["isError"] is True
    listed = _mcp_call(server, "list_intentions", {"tenant_id": TENANT})
    assert listed["structuredContent"]["intentions"][0]["status"] == "scheduled"


def test_prospective_tool_schemas_exclude_transport_identity(tmp_path: Path) -> None:
    expected = {"schedule_intention", "cancel_intention", "evaluate_intentions", "list_intentions"}
    assert expected <= {entry["name"] for entry in TOOL_SPEC}
    response = _server(tmp_path).handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )
    assert response is not None
    tools = {entry["name"]: entry for entry in response["result"]["tools"]}
    assert expected <= set(tools)
    assert all("session_identity" not in tools[name]["inputSchema"]["properties"] for name in expected)
