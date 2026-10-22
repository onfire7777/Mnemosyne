"""Mental-model transport binding, permissions and complete CLI routes."""

from __future__ import annotations

import json
from typing import Any

import pytest

from mnemosyne import cli
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_server import MnemosyneMcpServer, _to_mcp_tool_spec
from mnemosyne.mcp_tools import TOOL_SPEC, MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.providers.extractive_decomposer import ExtractiveQueryDecomposer
from mnemosyne.security import SessionIdentity, SessionTokenVerifier
from mnemosyne.sqlite_engine import SqliteEngine


OPERATIONS = [
    ("create", {"name": "Launch", "question": "When is launch?"}),
    ("get", {"model_id": "model-1", "refresh_if_stale": False}),
    ("list", {}),
    ("refresh", {"model_id": "model-1", "force": True}),
    ("update", {"model_id": "model-1", "name": "New launch", "question": "When?", "expected_version": 2}),
    ("delete", {"model_id": "model-1", "expected_version": 2}),
    ("history", {"model_id": "model-1"}),
]


class Recorder:
    def __init__(self):
        self.calls: list[tuple[str, Any, tuple, dict]] = []

    def __getattr__(self, operation):
        def call(context, *args, **kwargs):
            self.calls.append((operation, context, args, kwargs))
            return [] if operation in {"list", "history"} else {"model_id": "model-1"}
        return call


@pytest.fixture
def recorded_tools(monkeypatch):
    service = Recorder()
    tools = MemoryTools(LocalMemoryEngine())
    monkeypatch.setattr(tools, "_mental_model_service", lambda: service)
    return tools, service


@pytest.mark.parametrize(("operation", "options"), OPERATIONS)
def test_every_operation_forwards_complete_immutable_scope(recorded_tools, operation, options):
    tools, service = recorded_tools
    getattr(tools, "mental_model_" + operation)(
        tenant_id="tenant-a", user_id="user-a", branch="main", role="agent",
        source_trust_tier=1, max_trust_tier=2, max_sensitivity=2,
        capability_tags=["memory"], purpose=["assist"], residency="us",
        region="us-west", lawful_basis=["consent"], as_of="2026-10-22T12:00:00Z",
        **options,
    )
    called, context, args, kwargs = service.calls[0]
    assert called == operation
    assert context.tenant_id == "tenant-a" and context.user_id == "user-a"
    assert context.role == "agent" and context.branch == "main"
    assert context.to_filter()["max_trust_tier"] == 1
    assert context.max_sensitivity == 2 and context.capability_tags == ("memory",)
    assert context.purpose == ("assist",) and context.lawful_basis == ("consent",)
    assert context.residency == "us" and context.region == "us-west"
    assert context.as_of.isoformat() == "2026-10-22T12:00:00+00:00"
    expected = dict(options)
    model_id = expected.pop("model_id", None)
    assert args == (() if model_id is None else (model_id,))
    assert kwargs == expected


@pytest.mark.parametrize(("operation", "options"), [
    *[row for row in OPERATIONS if row[0] in {"create", "refresh", "update", "delete"}],
    ("get", {"model_id": "model-1", "refresh_if_stale": True}),
])
@pytest.mark.parametrize("authority", [{"role": "reader"}, {"source_trust_tier": 5}])
def test_writes_require_authority_before_service(recorded_tools, operation, options, authority):
    tools, service = recorded_tools
    with pytest.raises(PermissionError):
        getattr(tools, "mental_model_" + operation)(
            tenant_id="tenant-a", user_id="user-a", **options, **authority,
        )
    assert not service.calls


@pytest.mark.parametrize(("operation", "options"), [row for row in OPERATIONS if row[0] in {"get", "list", "history"}])
def test_read_operations_do_not_request_write_authority(recorded_tools, monkeypatch, operation, options):
    tools, service = recorded_tools

    def forbidden(*args, **kwargs):
        pytest.fail("a read must not authorize or audit a write")

    monkeypatch.setattr(tools, "_authorize", forbidden)
    getattr(tools, "mental_model_" + operation)(
        tenant_id="tenant-a", user_id="user-a", role="reader", **options,
    )
    assert len(service.calls) == 1


@pytest.mark.parametrize("changes", [
    {"tenant_id": " "}, {"user_id": ""}, {"branch": " "},
    {"break_glass": True}, {"break_glass": "false"}, {"source_trust_tier": True},
    {"max_sensitivity": 4}, {"as_of": "2026-10-22"}, {"role": "administrator"},
])
def test_invalid_read_scope_fails_before_service(recorded_tools, changes):
    tools, service = recorded_tools
    with pytest.raises(ValueError):
        tools.mental_model_get(**{"tenant_id": "tenant-a", "user_id": "user-a", "model_id": "model-1", **changes})
    assert not service.calls


@pytest.mark.parametrize(("operation", "options"), [
    ("get", {"model_id": "model-1", "refresh_if_stale": "yes"}),
    ("refresh", {"model_id": "model-1", "force": 1}),
    ("update", {"model_id": "model-1", "expected_version": True}),
    ("delete", {"model_id": "model-1", "expected_version": -1}),
])
def test_operation_controls_are_validated_before_service(recorded_tools, operation, options):
    tools, service = recorded_tools
    with pytest.raises(ValueError):
        getattr(tools, "mental_model_" + operation)(tenant_id="tenant-a", user_id="user-a", **options)
    assert not service.calls


@pytest.mark.parametrize(("operation", "options"), OPERATIONS)
def test_tool_schema_keeps_authority_top_level_and_configuration_private(operation, options):
    spec = next(row for row in TOOL_SPEC if row["name"] == "mental_model_" + operation)
    schema = _to_mcp_tool_spec(spec)["inputSchema"]
    assert schema["additionalProperties"] is False
    assert {"tenant_id", "user_id"} <= set(schema["required"])
    assert {"branch", "role", "source_trust_tier", "max_sensitivity"} <= set(schema["properties"])
    assert not {"context", "provider", "command", "model", "max_hops", "session_id", "source_identity"} & set(schema["properties"])


def _call(server, name, arguments):
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "mental_model_" + name, "arguments": arguments,
    }})
    return response["result"]


def test_signed_mcp_binds_tenant_user_role_and_trust_before_service(tmp_path, monkeypatch):
    secret = "mental-model-session-key"
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json", session_secret=secret,
        require_session=True, object_store=str(tmp_path / "objects"),
    )
    service = Recorder()
    monkeypatch.setattr(server.tools, "_mental_model_service", lambda: service)
    token = SessionTokenVerifier(secret).sign(SessionIdentity(
        tenant_id="tenant-a", user_id="user-a", role="agent", source_trust_tier=1,
        session_id="current-session",
    ))
    try:
        for operation, options in OPERATIONS:
            result = _call(server, operation, {
                "session_token": token, "role": "operator", "source_trust_tier": 0, **options,
            })
            assert not result.get("isError"), result
            _, context, _, _ = service.calls[-1]
            assert (context.tenant_id, context.user_id, context.role, context.source_trust_tier) == (
                "tenant-a", "user-a", "agent", 1,
            )
            assert context.source_identity is None
        count = len(service.calls)
        for forgery in ({"tenant_id": "other"}, {"user_id": "other"}, {"context": {}},
                        {"command": "external-command"}, {"break_glass": True}):
            assert _call(server, "get", {"session_token": token, "model_id": "model-1", **forgery})["isError"]
        assert _call(server, "get", {"model_id": "model-1"})["isError"]
        assert len(service.calls) == count
        reader_token = SessionTokenVerifier(secret).sign(SessionIdentity(
            tenant_id="tenant-a", user_id="user-a", role="reader", source_trust_tier=0,
        ))
        assert _call(server, "refresh", {"session_token": reader_token, "model_id": "model-1", "role": "operator"})["isError"]
        assert len(service.calls) == count
    finally:
        server.close()


@pytest.mark.parametrize(("operation", "options"), OPERATIONS)
@pytest.mark.parametrize("grouped", [False, True])
def test_cli_routes_forward_every_option(monkeypatch, capsys, operation, options, grouped):
    class Facade:
        def __getattr__(self, method):
            return lambda **kwargs: {"method": method, "arguments": kwargs}

    monkeypatch.setattr(cli, "load_tools", lambda args: Facade())
    command = ["mental-model", operation] if grouped else ["mental-model-" + operation]
    flags = [
        "--tenant", "tenant-a", "--user", "user-a", "--branch", "topic",
        "--role", "agent", "--source-trust-tier", "1", "--max-trust-tier", "2",
        "--max-sensitivity", "2", "--capability-tag", "memory", "--purpose", "assist",
        "--residency", "us", "--region", "us-west", "--lawful-basis", "consent",
        "--as-of", "2026-10-22T12:00:00Z",
    ]
    for key, value in options.items():
        if isinstance(value, bool):
            if value:
                flags.append("--" + key.replace("_", "-"))
        else:
            flags.extend(["--" + key.replace("_", "-"), str(value)])
    assert cli.main([*command, *flags]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["method"] == "mental_model_" + operation
    assert output["arguments"] == {
        "tenant_id": "tenant-a", "user_id": "user-a", "branch": "topic", "role": "agent",
        "source_trust_tier": 1, "max_trust_tier": 2, "max_sensitivity": 2,
        "capability_tags": ["memory"], "purpose": ["assist"], "residency": "us",
        "region": "us-west", "lawful_basis": ["consent"], "break_glass": False,
        "as_of": "2026-10-22T12:00:00Z", **options,
    }


class FixtureProvider:
    disclosure = {"query_decomposer": {"model": "fixture"}, "grounded_reader": {"model": "fixture"}}

    def decompose(self, payload):
        return ExtractiveQueryDecomposer().decompose(payload)

    def read(self, payload):
        for row in payload["evidence"]:
            if "Friday" in row["content"]:
                return {"claims": [{"spans": [{"cid": row["cid"], "quote": "Friday"}]}], "unresolved": False}
        return {"claims": [], "unresolved": True}


def _seed(engine):
    return engine.append_evidence(Evidence(
        tenant_id="tenant-a", user_id="user-a", actor="user", source_type="chat",
        content="Project Zephyr launches Friday.",
        access_policy={"tenant": "tenant-a", "allow_principals": ["user-a"]},
    ))


@pytest.fixture(params=["local", "sqlite"])
def stored_tools(request, tmp_path):
    engine = (LocalMemoryEngine(tmp_path / "store.json") if request.param == "local"
              else SqliteEngine(tmp_path / "sqlite"))
    _seed(engine)
    calls = []

    def factory():
        calls.append(True)
        return FixtureProvider()

    yield MemoryTools(engine, grounded_provider_factory=factory), calls
    engine.close()


def test_real_service_create_read_and_history_do_not_invoke_provider(stored_tools, monkeypatch):
    tools, calls = stored_tools
    scope = {"tenant_id": "tenant-a", "user_id": "user-a"}
    created = tools.mental_model_create(**scope, name="Launch", question="When does Project Zephyr launch?")
    model_id = created["model_id"]
    assert created["status"] == "pending" and not calls
    assert tools.mental_model_get(**scope, model_id=model_id)["answer"] == ""
    assert not calls
    refreshed = tools.mental_model_refresh(**scope, model_id=model_id)
    assert refreshed["status"] == "ready" and refreshed["answer"] == "Friday"
    assert len(calls) == 1

    def forbidden(*args, **kwargs):
        pytest.fail("a clean saved answer must not run retrieval or an embedding provider")

    monkeypatch.setattr(tools.engine, "retrieve", forbidden)
    assert tools.mental_model_get(**scope, model_id=model_id)["answer"] == "Friday"
    assert tools.mental_model_refresh(**scope, model_id=model_id)["answer"] == "Friday"
    assert tools.mental_model_list(**scope)[0]["model_id"] == model_id
    history = tools.mental_model_history(**scope, model_id=model_id)
    assert history and "Friday" not in json.dumps(history)
    assert len(calls) == 1


def test_real_service_rejects_other_owner_tenant_branch_and_changed_read_scope(stored_tools):
    tools, calls = stored_tools
    scope = {"tenant_id": "tenant-a", "user_id": "user-a"}
    model_id = tools.mental_model_create(**scope, name="Launch", question="When does Project Zephyr launch?")["model_id"]
    for changes in ({"tenant_id": "tenant-b"}, {"user_id": "user-b"}, {"branch": "other"}):
        with pytest.raises(LookupError, match="not found"):
            tools.mental_model_get(**{**scope, **changes}, model_id=model_id)
        assert tools.mental_model_list(**{**scope, **changes}) == []
    for changes in ({"role": "operator"}, {"purpose": ["new-purpose"]}, {"max_sensitivity": 1}):
        with pytest.raises(PermissionError, match="scope differs"):
            tools.mental_model_get(**{**scope, **changes}, model_id=model_id)
    assert not calls


def test_real_service_update_and_delete_require_current_version(stored_tools):
    tools, calls = stored_tools
    scope = {"tenant_id": "tenant-a", "user_id": "user-a"}
    created = tools.mental_model_create(**scope, name="Launch", question="When does Project Zephyr launch?")
    model_id = created["model_id"]
    with pytest.raises(ValueError, match="version conflict"):
        tools.mental_model_update(**scope, model_id=model_id, name="Wrong", expected_version=created["version"] + 1)
    updated = tools.mental_model_update(**scope, model_id=model_id, name="Release", expected_version=created["version"])
    assert updated["name"] == "Release" and updated["version"] > created["version"]
    with pytest.raises(ValueError, match="version conflict"):
        tools.mental_model_delete(**scope, model_id=model_id, expected_version=created["version"])
    assert tools.mental_model_delete(**scope, model_id=model_id, expected_version=updated["version"])["deleted"]
    with pytest.raises(LookupError):
        tools.mental_model_get(**scope, model_id=model_id)
    assert not calls


def test_signed_mcp_real_service_owns_models_and_keeps_clean_reads_provider_free(tmp_path):
    secret = "mental-model-real-session-key"
    server = MnemosyneMcpServer(
        store_path=tmp_path / "store.json", session_secret=secret,
        require_session=True, object_store=str(tmp_path / "objects"),
    )
    _seed(server.engine)
    calls = []

    def factory():
        calls.append(True)
        return FixtureProvider()

    server.tools = MemoryTools(server.engine, grounded_provider_factory=factory)
    signer = SessionTokenVerifier(secret)
    token = signer.sign(SessionIdentity(tenant_id="tenant-a", user_id="user-a", role="agent", source_trust_tier=0))
    try:
        created = _call(server, "create", {"session_token": token, "name": "Launch", "question": "When does Project Zephyr launch?"})
        assert not created.get("isError"), created
        model_id = created["structuredContent"]["model_id"]
        assert not calls
        refreshed = _call(server, "refresh", {"session_token": token, "model_id": model_id})
        assert refreshed["structuredContent"]["answer"] == "Friday"
        for changes in ({}, {"role": "operator", "source_trust_tier": 5}):
            got = _call(server, "get", {"session_token": token, "model_id": model_id, **changes})
            assert got["structuredContent"]["answer"] == "Friday"
        for tenant, user in (("tenant-b", "user-a"), ("tenant-a", "user-b")):
            other = signer.sign(SessionIdentity(tenant_id=tenant, user_id=user, role="agent", source_trust_tier=0))
            denied = _call(server, "get", {"session_token": other, "model_id": model_id})
            assert denied["isError"] and "Friday" not in json.dumps(denied)
        assert len(calls) == 1
    finally:
        server.close()


def test_grouped_cli_uses_persistent_service(tmp_path, monkeypatch, capsys):
    from mnemosyne.providers.grounded_reader import CommandGroundedProvider

    path = tmp_path / "memory.json"
    engine = LocalMemoryEngine(path)
    _seed(engine)
    engine.close()
    calls = []

    def factory(cls):
        calls.append(True)
        return FixtureProvider()

    monkeypatch.setattr(CommandGroundedProvider, "from_environment", classmethod(factory))

    def run(operation, *args):
        assert cli.main(["--store", str(path), "mental-model", operation,
                         "--tenant", "tenant-a", "--user", "user-a", *args]) == 0
        return json.loads(capsys.readouterr().out)

    created = run("create", "--name", "Launch", "--question", "When does Project Zephyr launch?")
    model_id = created["model_id"]
    assert not calls
    assert run("get", "--model-id", model_id)["status"] == "pending"
    assert run("refresh", "--model-id", model_id)["answer"] == "Friday"
    assert run("get", "--model-id", model_id)["answer"] == "Friday"
    assert len(calls) == 1
    assert run("delete", "--model-id", model_id)["deleted"]
