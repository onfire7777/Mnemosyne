"""Schedule transport authorization and the bounded standalone worker lifecycle."""

from __future__ import annotations

import json
import signal
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from mnemosyne import cli
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_server import MnemosyneMcpServer, _to_mcp_tool_spec
from mnemosyne.mcp_tools import TOOL_SPEC, MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.providers.extractive_decomposer import ExtractiveQueryDecomposer
from mnemosyne.security import SessionIdentity, SessionTokenVerifier
from mnemosyne.sqlite_engine import SqliteEngine


SCOPE = {"tenant_id": "tenant-a", "user_id": "user-a"}


@pytest.fixture
def recorded_tools(monkeypatch):
    calls = []
    tools = MemoryTools(LocalMemoryEngine())

    def schedule(context, model_id, **options):
        calls.append((context, model_id, options))
        return {"model_id": model_id}

    monkeypatch.setattr(tools, "_mental_model_service", lambda: SimpleNamespace(schedule=schedule))
    return tools, calls


def test_schedule_forwards_complete_scope_and_options(recorded_tools):
    tools, calls = recorded_tools
    tools.mental_model_schedule(
        **SCOPE, model_id="model", interval_seconds=600, enabled=False, expected_version=3,
        role="agent", source_trust_tier=1, max_trust_tier=2, max_sensitivity=2,
        capability_tags=["memory"], purpose=["assist"], residency="us", region="us-west",
        lawful_basis=["consent"], as_of="2026-10-22T12:00:00Z",
    )
    context, model_id, options = calls[0]
    assert model_id == "model" and options == {
        "interval_seconds": 600, "enabled": False, "expected_version": 3,
    }
    assert context.tenant_id == "tenant-a" and context.user_id == "user-a"
    assert context.to_filter()["max_trust_tier"] == 1
    assert context.max_sensitivity == 2 and context.capability_tags == ("memory",)
    assert context.purpose == ("assist",) and context.lawful_basis == ("consent",)
    assert context.residency == "us" and context.region == "us-west"
    assert context.as_of.isoformat() == "2026-10-22T12:00:00+00:00"


@pytest.mark.parametrize("changes", [
    {"interval_seconds": 59}, {"interval_seconds": 604801}, {"interval_seconds": True},
    {"interval_seconds": 60.0}, {"enabled": 1}, {"enabled": "false"},
    {"expected_version": True}, {"expected_version": -1}, {"break_glass": True},
])
def test_schedule_rejects_invalid_controls_before_service(recorded_tools, changes):
    tools, calls = recorded_tools
    with pytest.raises(ValueError):
        tools.mental_model_schedule(**SCOPE, model_id="model", **changes)
    assert calls == []


@pytest.mark.parametrize("changes", [{"role": "reader"}, {"source_trust_tier": 5}])
def test_schedule_requires_write_authority(recorded_tools, changes):
    tools, calls = recorded_tools
    with pytest.raises(PermissionError):
        tools.mental_model_schedule(**SCOPE, model_id="model", **changes)
    assert calls == []


def _call(server, arguments):
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "mental_model_schedule", "arguments": arguments,
    }})
    return response["result"]


def test_signed_schedule_binds_identity_and_rejects_forgery(tmp_path, recorded_tools):
    secret = "schedule-test-signing-key"
    tools, calls = recorded_tools
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json", session_secret=secret,
                               require_session=True, object_store=str(tmp_path / "objects"))
    server.tools = tools
    signer = SessionTokenVerifier(secret)
    token = signer.sign(SessionIdentity(**SCOPE, role="agent", source_trust_tier=1))
    try:
        result = _call(server, {"session_token": token, "model_id": "model",
                                "role": "operator", "source_trust_tier": 0})
        assert not result.get("isError"), result
        context = calls[0][0]
        assert (context.tenant_id, context.user_id, context.role, context.source_trust_tier) == (
            "tenant-a", "user-a", "agent", 1,
        )
        for forgery in ({"tenant_id": "other"}, {"user_id": "other"},
                        {"context": {}}, {"command": "untrusted"}, {"break_glass": True}):
            assert _call(server, {"session_token": token, "model_id": "model", **forgery})["isError"]
        reader = signer.sign(SessionIdentity(**SCOPE, role="reader", source_trust_tier=0))
        assert _call(server, {"session_token": reader, "model_id": "model", "role": "operator"})["isError"]
        assert len(calls) == 1
    finally:
        server.close()


def test_schedule_schema_has_scope_but_no_provider_controls():
    item = next(item for item in TOOL_SPEC if item["name"] == "mental_model_schedule")
    schema = _to_mcp_tool_spec(item)["inputSchema"]
    assert set(schema["required"]) == {"tenant_id", "user_id", "model_id"}
    assert {"enabled", "interval_seconds", "expected_version", "role", "source_trust_tier"} <= set(schema["properties"])
    assert not {"command", "provider", "model", "context"} & set(schema["properties"])


@pytest.mark.parametrize("grouped", [True, False])
def test_cli_schedule_routes_forward_every_option(monkeypatch, capsys, grouped):
    class Facade:
        def mental_model_schedule(self, **kwargs):
            return kwargs

    monkeypatch.setattr(cli, "load_tools", lambda args: Facade())
    command = ["mental-model", "schedule"] if grouped else ["mental-model-schedule"]
    assert cli.main([*command, "--tenant", "tenant-a", "--user", "user-a", "--model-id", "model",
                     "--interval-seconds", "900", "--disable", "--expected-version", "4",
                     "--max-sensitivity", "1", "--purpose", "assist"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["interval_seconds"] == 900 and output["enabled"] is False
    assert output["expected_version"] == 4 and output["model_id"] == "model"
    assert output["max_sensitivity"] == 1 and output["purpose"] == ["assist"]
    assert output["tenant_id"] == "tenant-a" and output["user_id"] == "user-a"


def _worker_args(*extra):
    return ["--backend", "sqlite", "mental-model-worker", "--tenant", "tenant-a",
            "--user", "user-a", *extra]


@pytest.fixture
def worker_runtime(tmp_path, monkeypatch):
    engine = SqliteEngine(tmp_path / "sqlite")
    closed = []
    real_close = engine.close

    def close():
        closed.append(True)
        real_close()

    monkeypatch.setattr(engine, "close", close)
    monkeypatch.setattr(cli, "load_engine", lambda args: engine)
    return engine, closed


def _stub_worker(monkeypatch, callback):
    import mnemosyne.mental_model_refresh as module

    class Worker:
        def __init__(self, service, context, **kwargs):
            self.service, self.context, self.options = service, context, kwargs

        def run_once(self):
            return callback(self)

    monkeypatch.setattr(module, "MentalModelRefreshWorker", Worker)


@pytest.mark.parametrize("check_changes", [False, True])
def test_worker_once_forwards_bounds_emits_aggregate_and_closes(worker_runtime, monkeypatch, capsys, check_changes):
    engine, closed = worker_runtime
    calls = []

    def run(worker):
        worker.options["authorize"]()
        worker.options["validate_authority"]()
        calls.append(worker)
        return {"processed": 0, "models": []}

    _stub_worker(monkeypatch, run)
    options = ["--once", "--limit", "3", "--lease-seconds", "90"]
    if check_changes:
        options.append("--check-changes")
    assert cli.main(_worker_args(*options)) == 0
    assert json.loads(capsys.readouterr().out) == {"processed": 0, "models": []}
    assert len(calls) == 1 and calls[0].service.engine is engine
    assert calls[0].options["max_batch"] == 3 and calls[0].options["lease_seconds"] == 90
    assert calls[0].options["check_changes"] is check_changes
    assert calls[0].context.tenant_id == "tenant-a" and calls[0].context.user_id == "user-a"
    assert closed == [True]


@pytest.mark.parametrize("options", [
    ["--limit", "0"], ["--limit", "101"], ["--lease-seconds", "29"], ["--lease-seconds", "3601"],
    ["--poll-interval", "0"], ["--poll-interval", "301"], ["--poll-interval", "nan"],
    ["--max-cycles", "-1"],
])
def test_worker_invalid_bounds_do_not_open_store(monkeypatch, options):
    monkeypatch.setattr(cli, "load_engine", lambda args: pytest.fail("invalid worker opened a store"))
    with pytest.raises(SystemExit):
        cli.main(_worker_args(*options))


def test_worker_rejects_local_json_before_open(monkeypatch):
    monkeypatch.setattr(cli, "load_engine", lambda args: pytest.fail("local JSON worker opened a store"))
    with pytest.raises(SystemExit, match="sqlite or postgres"):
        cli.main(["--backend", "local", "mental-model-worker", "--tenant", "tenant-a", "--user", "user-a", "--once"])


def test_worker_checks_actual_backend_and_closes_rejected_engine(monkeypatch):
    engine = LocalMemoryEngine()
    closed = []
    monkeypatch.setattr(engine, "close", lambda: closed.append(True))
    monkeypatch.setattr(cli, "load_engine", lambda args: engine)
    with pytest.raises(SystemExit, match="SQLite or Postgres"):
        cli.main(_worker_args("--once"))
    assert closed == [True]


def test_worker_wait_is_interruptible_and_does_not_accumulate_reports(worker_runtime, monkeypatch, capsys):
    _, closed = worker_runtime
    waits = []

    class StopAfterWait:
        stopped = False

        def is_set(self):
            return self.stopped

        def set(self):
            self.stopped = True

        def wait(self, seconds):
            waits.append(seconds)
            return True

    monkeypatch.setattr(threading, "Event", StopAfterWait)
    _stub_worker(monkeypatch, lambda worker: {"processed": 0})
    assert cli.main(_worker_args("--poll-interval", "7")) == 0
    assert json.loads(capsys.readouterr().out) == {"processed": 0}
    assert waits == [7] and closed == [True]


@pytest.mark.parametrize("failure", [KeyboardInterrupt, RuntimeError])
def test_worker_restores_signal_and_closes_on_failure(worker_runtime, monkeypatch, failure):
    _, closed = worker_runtime
    before = signal.getsignal(signal.SIGTERM)

    def run(worker):
        raise failure("stopping")

    _stub_worker(monkeypatch, run)
    if failure is KeyboardInterrupt:
        assert cli.main(_worker_args("--once")) == 0
    else:
        with pytest.raises(RuntimeError, match="stopping"):
            cli.main(_worker_args("--once"))
    assert closed == [True] and signal.getsignal(signal.SIGTERM) == before


def test_signed_worker_expiry_before_publication_stops_without_publishing(worker_runtime, monkeypatch):
    import mnemosyne.security as security

    _, closed = worker_runtime
    now = [1000]
    monkeypatch.setattr(security.time, "time", lambda: now[0])
    secret = "worker-test-signing-key"
    token = SessionTokenVerifier(secret).sign(SessionIdentity(
        **SCOPE, role="agent", source_trust_tier=1, expires_at=1500,
    ))
    published = []

    def run(worker):
        assert worker.context.role == "agent" and worker.context.source_trust_tier == 1
        worker.options["authorize"]()  # Start of attempt.
        now[0] = 1501
        worker.options["validate_authority"]()  # Final publication after source snapshot.
        published.append(True)
        return {"processed": 1}

    _stub_worker(monkeypatch, run)
    with pytest.raises(SystemExit, match="expired"):
        cli.main(["--session-secret", secret, "--session-token", token,
                  *_worker_args("--once", "--role", "operator", "--source-trust-tier", "0")])
    assert not published and closed == [True]


def test_worker_publication_validation_does_not_audit_or_end_transaction(worker_runtime, monkeypatch):
    engine, closed = worker_runtime
    checked = []

    def run(worker):
        worker.options["authorize"]()
        with engine.mental_model_guard("tenant-a"):
            connection = engine._connect("tenant-a")
            before = connection.total_changes
            with monkeypatch.context() as scoped:
                scoped.setattr(engine, "record_audit_event", lambda *args, **kwargs: pytest.fail("validation wrote an audit event"))
                worker.options["validate_authority"]()
            assert connection.in_transaction and connection.total_changes == before
            checked.append(True)
        return {"processed": 0}

    _stub_worker(monkeypatch, run)
    assert cli.main(_worker_args("--once")) == 0
    assert checked == [True] and closed == [True]


def test_worker_rechecks_authority_each_cycle(worker_runtime, monkeypatch):
    _, closed = worker_runtime
    checks = []
    real_apply = cli.apply_session_identity

    def apply(args):
        real_apply(args)
        checks.append(True)
        if len(checks) == 4:  # main, setup, first cycle, then second cycle.
            args.role = "reader"

    monkeypatch.setattr(cli, "apply_session_identity", apply)
    monkeypatch.setattr(threading.Event, "wait", lambda self, seconds: False)
    runs = []
    _stub_worker(monkeypatch, lambda worker: runs.append(True) or {"processed": 0})
    with pytest.raises(PermissionError, match="scope changed"):
        cli.main(_worker_args("--max-cycles", "2"))
    assert runs == [True] and closed == [True]


def test_worker_sigterm_stops_after_current_cycle_and_restores_handler(worker_runtime, monkeypatch, capsys):
    _, closed = worker_runtime
    before = signal.getsignal(signal.SIGTERM)

    def run(worker):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return {"processed": 0}

    _stub_worker(monkeypatch, run)
    assert cli.main(_worker_args()) == 0
    assert json.loads(capsys.readouterr().out) == {"processed": 0}
    assert closed == [True] and signal.getsignal(signal.SIGTERM) == before


def test_worker_emits_each_bounded_cycle_without_combining_reports(worker_runtime, monkeypatch):
    _, closed = worker_runtime
    reports, waits = [], []
    monkeypatch.setattr(cli, "emit", reports.append)
    monkeypatch.setattr(threading.Event, "wait", lambda self, seconds: waits.append(seconds) or False)
    _stub_worker(monkeypatch, lambda worker: {"processed": 0})
    assert cli.main(_worker_args("--max-cycles", "3", "--poll-interval", "2")) == 0
    assert reports == [{"processed": 0}] * 3 and waits == [2, 2]
    assert closed == [True]


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_schedule_real_service_preserves_owner_scope_and_version_without_provider(tmp_path, backend):
    engine = LocalMemoryEngine(tmp_path / "store.json") if backend == "local" else SqliteEngine(tmp_path / "sqlite")
    tools = MemoryTools(engine, grounded_provider_factory=lambda: pytest.fail("scheduling invoked provider"))
    try:
        created = tools.mental_model_create(**SCOPE, name="Launch", question="When is the launch?")
        model_id = created["model_id"]
        scheduled = tools.mental_model_schedule(**SCOPE, model_id=model_id, interval_seconds=60,
                                               expected_version=created["version"])
        assert scheduled["refresh_schedule"]["enabled"] is True
        assert scheduled["refresh_schedule"]["interval_seconds"] == 60
        assert scheduled["answer"] == ""
        for changes in ({"user_id": "other"}, {"tenant_id": "other"}, {"branch": "other"}):
            with pytest.raises(LookupError, match="not found"):
                tools.mental_model_schedule(**{**SCOPE, **changes}, model_id=model_id)
        with pytest.raises(PermissionError, match="scope differs"):
            tools.mental_model_schedule(**SCOPE, model_id=model_id, max_sensitivity=2)
        with pytest.raises(ValueError, match="version conflict"):
            tools.mental_model_schedule(**SCOPE, model_id=model_id, enabled=False,
                                        expected_version=created["version"])
        disabled = tools.mental_model_schedule(**SCOPE, model_id=model_id, enabled=False,
                                              expected_version=scheduled["version"])
        assert disabled["refresh_schedule"]["enabled"] is False
    finally:
        engine.close()


def test_sqlite_cli_schedule_worker_and_clean_repeat_are_persistent(tmp_path, monkeypatch, capsys):
    import mnemosyne.mental_model_refresh as refresh_module
    from mnemosyne.providers.grounded_reader import CommandGroundedProvider

    now = [datetime.now(UTC)]
    monkeypatch.setattr(refresh_module, "utc_now", lambda: now[0])
    path = tmp_path / "sqlite"
    engine = SqliteEngine(path)
    engine.append_evidence(Evidence(**SCOPE, actor="user", source_type="chat",
                                    content="Project Zephyr launches Friday.",
                                    access_policy={"tenant": "tenant-a", "allow_principals": ["user-a"]}))
    tools = MemoryTools(engine)
    model_id = tools.mental_model_create(**SCOPE, name="Launch", question="When does Project Zephyr launch?")["model_id"]
    engine.close()
    calls = []

    class Provider:
        disclosure = {"query_decomposer": {"model": "fixture"}, "grounded_reader": {"model": "fixture"}}

        def decompose(self, payload):
            return ExtractiveQueryDecomposer().decompose(payload)

        def read(self, payload):
            row = next(row for row in payload["evidence"] if "Friday" in row["content"])
            return {"claims": [{"spans": [{"cid": row["cid"], "quote": "Friday"}]}], "unresolved": False}

    def factory(cls):
        calls.append(True)
        return Provider()

    monkeypatch.setattr(CommandGroundedProvider, "from_environment", classmethod(factory))
    base = ["--backend", "sqlite", "--store", str(path), "--object-store", str(tmp_path / "objects")]
    scope = ["--tenant", "tenant-a", "--user", "user-a"]
    assert cli.main([*base, "mental-model", "schedule", *scope, "--model-id", model_id,
                     "--interval-seconds", "600"]) == 0
    assert json.loads(capsys.readouterr().out)["refresh_schedule"]["enabled"]
    assert not calls
    assert cli.main([*base, "mental-model-worker", *scope, "--once"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["refreshed"] == 1 and "Friday" not in json.dumps(report)
    assert len(calls) == 1
    now[0] += timedelta(seconds=601)
    assert cli.main([*base, "mental-model-worker", *scope, "--once"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["unchanged"] == 1 and len(calls) == 1
    reopened = SqliteEngine(path)
    try:
        view = MemoryTools(reopened).mental_model_get(**SCOPE, model_id=model_id)
        assert view["answer"] == "Friday" and view["refresh_schedule"]["last_outcome"] == "unchanged"
    finally:
        reopened.close()
