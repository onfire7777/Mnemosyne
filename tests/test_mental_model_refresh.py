"""Durable scheduled refresh: retries, leases, isolation, and cancellation."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

import mnemosyne.mental_model_refresh as scheduling
from mnemosyne.answering import AnswerReadContext
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mental_model_refresh import MentalModelRefreshWorker
from mnemosyne.mental_models import MentalModelService
from mnemosyne.models import Evidence
from mnemosyne.providers.extractive_decomposer import ExtractiveQueryDecomposer
from mnemosyne.sqlite_engine import SqliteEngine

CTX = AnswerReadContext(tenant_id="t", user_id="u", role="agent", max_sensitivity=0)


class Provider:
    disclosure = {"query_decomposer": {"model": "fixture"}, "grounded_reader": {"model": "fixture"}}

    def __init__(self, callback=None, fail=False, unresolved=False):
        self.callback, self.fail, self.unresolved, self.calls = callback, fail, unresolved, 0

    def decompose(self, payload):
        return ExtractiveQueryDecomposer().decompose(payload)

    def read(self, payload):
        self.calls += 1
        if self.callback:
            self.callback()
        if self.fail:
            raise RuntimeError("secret provider failure")
        if not self.unresolved:
            for day in ("Tuesday", "Friday"):
                for row in payload["evidence"]:
                    if day in row["content"]:
                        return {"claims": [{"spans": [{"cid": row["cid"], "quote": day}]}], "unresolved": False}
        return {"claims": [], "unresolved": True}


@pytest.fixture(params=["local", "sqlite"])
def setup(request, tmp_path, monkeypatch):
    engine = LocalMemoryEngine(tmp_path / "store.json") if request.param == "local" else SqliteEngine(tmp_path / "store")
    now = [datetime.now(UTC)]
    monkeypatch.setattr(scheduling, "utc_now", lambda: now[0])
    provider = Provider()
    service = MentalModelService(engine, lambda: provider)
    cid = add_source(engine)
    mid = service.create(CTX, "Zephyr", "When does Project Zephyr launch?")["model_id"]
    yield engine, service, provider, mid, cid, now
    engine.close()


def add_source(engine, text="Project Zephyr launches Friday."):
    return engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="chat",
                                           content=text, access_policy={"tenant": "t", "allow_principals": ["u"]}))


def schedule(service, mid):
    return service.schedule(CTX, mid, interval_seconds=60)


def test_disabled_models_never_run_then_refresh_and_skip_clean_model(setup):
    engine, service, provider, mid, _, now = setup
    worker = MentalModelRefreshWorker(service, CTX)
    assert worker.run_once()["processed"] == 0
    schedule(service, mid)
    assert worker.run_once()["refreshed"] == 1
    assert service.get(CTX, mid)["answer"] == "Friday"
    assert provider.calls == 1
    assert worker.run_once()["processed"] == 0
    now[0] += timedelta(seconds=61)
    service.provider_factory = lambda: pytest.fail("clean model loaded a provider")
    assert worker.run_once()["unchanged"] == 1
    add_source(engine, "Correction: Project Zephyr launches Tuesday.")
    now[0] += timedelta(seconds=61)
    service.provider_factory = lambda: provider
    assert worker.run_once()["refreshed"] == 1
    assert service.get(CTX, mid)["answer"] == "Tuesday"


def test_transient_failure_retries_after_restart_and_recovers(setup):
    engine, service, provider, mid, _, now = setup
    provider.fail = True
    schedule(service, mid)
    worker = MentalModelRefreshWorker(service, CTX)
    report = worker.run_once()
    assert report["retry"] == 1 and "secret" not in str(report)
    view = service.get(CTX, mid)
    assert view["status"] == "error"
    assert view["refresh_schedule"]["consecutive_failures"] == 1
    assert not view["refresh_schedule"]["running"]
    worker = MentalModelRefreshWorker(MentalModelService(engine, lambda: provider), CTX)
    assert worker.run_once()["processed"] == 0
    provider.fail = False
    now[0] += timedelta(seconds=61)
    assert worker.run_once()["refreshed"] == 1
    assert service.get(CTX, mid)["refresh_schedule"]["consecutive_failures"] == 0


def test_retry_backoff_is_capped_and_persisted(setup):
    _, service, provider, mid, _, now = setup
    provider.fail = True
    schedule(service, mid)
    for attempt in range(1, 10):
        worker = MentalModelRefreshWorker(service, CTX)
        assert worker.run_once()["retry"] == 1
        view = service.get(CTX, mid)["refresh_schedule"]
        assert view["consecutive_failures"] == attempt
        due = datetime.fromisoformat(view["next_run_at"])
        assert (due - now[0]).total_seconds() == min(3600, 60 * 2 ** min(attempt - 1, 6))
        now[0] = due


def test_legitimate_abstention_is_not_a_retry(setup):
    _, service, provider, mid, _, now = setup
    provider.unresolved = True
    schedule(service, mid)
    worker = MentalModelRefreshWorker(service, CTX)
    assert worker.run_once()["abstained"] == 1
    now[0] += timedelta(seconds=61)
    assert worker.run_once()["unchanged"] == 1
    assert provider.calls == 1


@pytest.mark.parametrize("context", [replace(CTX, user_id="other"), replace(CTX, tenant_id="other"),
                                      replace(CTX, role="operator"), replace(CTX, max_sensitivity=1),
                                      replace(CTX, branch="other")])
def test_worker_never_reconstructs_authority_from_stored_scope(setup, context):
    _, service, provider, mid, _, _ = setup
    schedule(service, mid)
    assert MentalModelRefreshWorker(service, context).run_once()["processed"] == 0
    assert provider.calls == 0


@pytest.mark.parametrize("context", [replace(CTX, role="reader"), replace(CTX, source_trust_tier=5)])
def test_worker_rejects_untrusted_write_context(setup, context):
    _, service, _, mid, _, _ = setup
    schedule(service, mid)
    with pytest.raises(PermissionError):
        MentalModelRefreshWorker(service, context).run_once()


def test_lease_expiry_without_takeover_prevents_publication_and_is_recovered(setup):
    _, service, provider, mid, _, now = setup
    schedule(service, mid)
    provider.callback = lambda: now.__setitem__(0, now[0] + timedelta(seconds=31))
    worker = MentalModelRefreshWorker(service, CTX, lease_seconds=30)
    assert worker.run_once()["lost"] == 1
    assert service.get(CTX, mid)["answer"] == ""
    provider.callback = None
    assert worker.run_once()["refreshed"] == 1


def test_expired_worker_cannot_overwrite_or_clear_successors_lease(setup):
    _, service, provider, mid, _, now = setup
    schedule(service, mid)
    worker = MentalModelRefreshWorker(service, CTX, lease_seconds=30)

    def takeover():
        provider.callback = None
        now[0] += timedelta(seconds=31)
        assert worker.run_once()["refreshed"] == 1

    provider.callback = takeover
    assert worker.run_once()["lost"] == 1
    view = service.get(CTX, mid)
    assert view["answer"] == "Friday"
    assert view["refresh_schedule"]["last_outcome"] == "refreshed"


@pytest.mark.parametrize("change", ["disable", "edit", "rename", "delete", "manual"])
def test_user_changes_cancel_inflight_scheduled_refresh(setup, change):
    _, service, provider, mid, _, _ = setup
    schedule(service, mid)

    def mutate():
        provider.callback = None
        if change == "disable":
            service.schedule(CTX, mid, enabled=False)
        elif change == "edit":
            service.update(CTX, mid, question="Who owns Zephyr?")
        elif change == "rename":
            service.update(CTX, mid, name="New label")
        elif change == "delete":
            service.delete(CTX, mid)
        else:
            assert service.refresh(CTX, mid)["answer"] == "Friday"

    provider.callback = mutate
    assert MentalModelRefreshWorker(service, CTX).run_once()["lost"] == 1
    if change != "delete":
        assert service.get(CTX, mid)["answer"] == ("Friday" if change == "manual" else "")


def test_authority_is_revalidated_after_provider_work(setup):
    _, service, provider, mid, _, _ = setup
    schedule(service, mid)
    allowed = [True]

    def authorize():
        if not allowed[0]:
            raise PermissionError("expired session")

    provider.callback = lambda: allowed.__setitem__(0, False)
    with pytest.raises(PermissionError):
        MentalModelRefreshWorker(service, CTX, authorize=authorize, validate_authority=authorize).run_once()
    assert service.get(CTX, mid)["answer"] == ""


@pytest.mark.parametrize("expiry", ["authority", "lease"])
def test_slow_source_preparation_cannot_outlive_authority_or_lease(setup, monkeypatch, expiry):
    _, service, provider, mid, _, now = setup
    schedule(service, mid)
    allowed = [True]

    def authorize():
        if not allowed[0]:
            raise PermissionError("expired session")

    original = service._snapshot

    def snapshot(context):
        result = original(context)
        if expiry == "authority":
            allowed[0] = False
        else:
            now[0] += timedelta(seconds=31)
        return result

    monkeypatch.setattr(service, "_snapshot", snapshot)
    worker = MentalModelRefreshWorker(service, CTX, lease_seconds=30, authorize=authorize, validate_authority=authorize)
    if expiry == "authority":
        with pytest.raises(PermissionError):
            worker.run_once()
    else:
        assert worker.run_once()["lost"] == 1
    assert provider.calls == 0


def test_authority_expiry_during_final_snapshot_blocks_publication(setup, monkeypatch):
    engine, service, provider, mid, _, _ = setup
    schedule(service, mid)
    allowed, snapshots = [True], [0]

    def validate():
        if not allowed[0]:
            raise PermissionError("expired session")

    original = service._snapshot

    def snapshot(context):
        result = original(context)
        snapshots[0] += 1
        if snapshots[0] == 2:
            allowed[0] = False
        return result

    monkeypatch.setattr(service, "_snapshot", snapshot)
    worker = MentalModelRefreshWorker(service, CTX, authorize=validate, validate_authority=validate)
    with pytest.raises(PermissionError):
        worker.run_once()
    assert provider.calls == 1
    assert engine.get_mental_model_record("t", mid)["answer"] is None


def test_private_source_change_during_background_work_is_withheld(setup):
    engine, service, provider, mid, cid, _ = setup
    schedule(service, mid)
    provider.callback = lambda: engine.backfill_evidence_privacy("t", cid, ["secret"])
    assert MentalModelRefreshWorker(service, CTX).run_once()["retry"] == 1
    assert service.get(CTX, mid)["answer"] == ""


def test_invalid_schedules_do_not_starve_valid_due_models(setup):
    engine, service, _, mid, _, _ = setup
    bad = service.create(CTX, "Malformed", "When does Project Zephyr launch?")["model_id"]
    row = engine.get_mental_model_record("t", bad)
    row["refresh_schedule"] = {"enabled": True, "next_run_at": []}
    engine.save_mental_model_record("t", bad, row, expected_version=row["version"])
    schedule(service, mid)
    report = MentalModelRefreshWorker(service, CTX, max_batch=1).run_once()
    assert report["invalid"] == 1 and report["refreshed"] == 1
    assert service.get(CTX, bad)["refresh_schedule"] == {"enabled": False, "invalid": True}


@pytest.mark.parametrize("value", [True, 0, 59, 604801, 60.0, "60"])
def test_interval_validation(setup, value):
    _, service, _, mid, _, _ = setup
    with pytest.raises(ValueError):
        service.schedule(CTX, mid, interval_seconds=value)


def test_two_sqlite_workers_do_not_generate_the_same_due_model(tmp_path):
    first, second = SqliteEngine(tmp_path), SqliteEngine(tmp_path)
    entered, release = Event(), Event()
    provider = Provider(callback=lambda: (entered.set(), release.wait(5)))
    service = MentalModelService(first, lambda: provider)
    other = MentalModelService(second, lambda: pytest.fail("duplicate provider call"))
    add_source(first)
    mid = service.create(CTX, "Zephyr", "When does Project Zephyr launch?")["model_id"]
    schedule(service, mid)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(MentalModelRefreshWorker(service, CTX).run_once)
            assert entered.wait(5)
            assert MentalModelRefreshWorker(other, CTX).run_once()["processed"] == 0
            release.set()
            assert pending.result(timeout=5)["refreshed"] == 1
        assert provider.calls == 1
    finally:
        release.set()
        first.close()
        second.close()


@pytest.mark.parametrize("factory", [LocalMemoryEngine, SqliteEngine])
def test_crashed_lease_survives_engine_restart_and_recovers(factory, tmp_path, monkeypatch):
    path = tmp_path / "store"
    now = [datetime.now(UTC)]
    monkeypatch.setattr(scheduling, "utc_now", lambda: now[0])
    engine = factory(path)
    service = MentalModelService(engine, Provider)
    add_source(engine)
    mid = service.create(CTX, "Zephyr", "When does Project Zephyr launch?")["model_id"]
    schedule(service, mid)
    assert MentalModelRefreshWorker(service, CTX, lease_seconds=30)._claim(mid)
    engine.close()
    reopened = factory(path)
    try:
        service = MentalModelService(reopened, Provider)
        worker = MentalModelRefreshWorker(service, CTX, lease_seconds=30)
        assert worker.run_once()["processed"] == 0
        now[0] += timedelta(seconds=31)
        assert worker.run_once()["refreshed"] == 1
        assert service.get(CTX, mid)["answer"] == "Friday"
    finally:
        reopened.close()


def test_due_batch_limit_does_not_starve_remaining_models(setup):
    _, service, _, mid, _, _ = setup
    other = service.create(CTX, "Another", "When does Project Zephyr launch?")["model_id"]
    schedule(service, mid)
    schedule(service, other)
    worker = MentalModelRefreshWorker(service, CTX, max_batch=1)
    first, second = worker.run_once(), worker.run_once()
    assert first["refreshed"] == second["refreshed"] == 1
    assert first["models"][0]["model_id"] != second["models"][0]["model_id"]
