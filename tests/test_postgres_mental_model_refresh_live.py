"""Real PostgreSQL sessions against a disposable database with roles.sql applied.

MNEMOSYNE_POSTGRES_DSN uses the consolidator login. App/readonly permission
probes additionally use MNEMOSYNE_POSTGRES_APP_DSN/MNEMOSYNE_POSTGRES_READONLY_DSN.
The caller destroys the disposable database after the suite; rows are retained
for diagnostics. Provider replies are deterministic fixtures, not model calls.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import os
from threading import Event
import time
from uuid import uuid4

import pytest

import mnemosyne.mental_model_refresh as scheduling
from mnemosyne.answering import AnswerReadContext
from mnemosyne.mental_model_refresh import MentalModelRefreshWorker
from mnemosyne.mental_models import MentalModelService
from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import PostgresEngine, _cid_to_bytes, _stable_uuid
from mnemosyne.providers.extractive_decomposer import ExtractiveQueryDecomposer

psycopg = pytest.importorskip("psycopg")


class Provider:
    disclosure = {"query_decomposer": {"model": "fixture"}, "grounded_reader": {"model": "fixture"}}

    def __init__(self, callback=None):
        self.callback, self.calls = callback, 0

    def decompose(self, payload):
        return ExtractiveQueryDecomposer().decompose(payload)

    def read(self, payload):
        self.calls += 1
        if self.callback:
            self.callback()
        for day in ("Tuesday", "Friday"):
            for row in payload["evidence"]:
                if day in row["content"]:
                    return {"claims": [{"spans": [{"cid": row["cid"], "quote": day}]}], "unresolved": False}
        return {"claims": [], "unresolved": True}


@pytest.fixture
def live():
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    engine, other = PostgresEngine(dsn, require_safe_role=True), PostgresEngine(dsn, require_safe_role=True)
    context = AnswerReadContext(tenant_id=f"model-live-{uuid4().hex}", user_id="owner", role="agent", max_sensitivity=0)
    provider = Provider()
    service = MentalModelService(engine, lambda: provider)
    cid = engine.append_evidence(Evidence(tenant_id=context.tenant_id, user_id="owner", actor="user",
        source_type="chat", content="Project Zephyr launches Friday.", access_policy={"tenant": context.tenant_id}))
    mid = service.create(context, "Zephyr", "When does Project Zephyr launch?")["model_id"]
    yield engine, other, service, provider, context, mid, cid
    engine.close_connections()
    other.close_connections()


def test_live_scheduled_refresh_reuses_clean_answer_and_refreshes_new_source(live, monkeypatch):
    engine, _, service, provider, context, mid, _ = live
    now = [datetime.now(UTC)]
    monkeypatch.setattr(scheduling, "utc_now", lambda: now[0])
    service.schedule(context, mid, interval_seconds=60)
    worker = MentalModelRefreshWorker(service, context)
    assert worker.run_once()["refreshed"] == 1
    assert service.get(context, mid)["answer"] == "Friday"
    now[0] += timedelta(seconds=61)
    assert worker.run_once()["unchanged"] == 1
    assert provider.calls == 1
    engine.append_evidence(Evidence(tenant_id=context.tenant_id, user_id="owner", actor="user", source_type="chat",
        content="Correction: Project Zephyr launches Tuesday.", access_policy={"tenant": context.tenant_id}))
    now[0] += timedelta(seconds=61)
    assert worker.run_once()["refreshed"] == 1
    assert service.get(context, mid)["answer"] == "Tuesday"


@pytest.mark.parametrize("operation", ["privacy", "erase", "correction"])
def test_live_source_changes_during_generation_are_withheld(live, operation):
    _, other, service, provider, context, mid, cid = live
    def change():
        if operation == "privacy":
            other.backfill_evidence_privacy(context.tenant_id, cid, ["secret"])
        elif operation == "erase":
            other.forget(context.tenant_id, cid)
        else:
            other.append_evidence(Evidence(tenant_id=context.tenant_id, user_id="owner", actor="user", source_type="chat",
                content="Correction: Project Zephyr launches Tuesday.", access_policy={"tenant": context.tenant_id}))
    provider.callback = change
    service.schedule(context, mid, interval_seconds=60)
    report = MentalModelRefreshWorker(service, context).run_once()
    assert report["retry"] + report["lost"] == 1
    assert service.get(context, mid)["answer"] == ""


@pytest.mark.parametrize("operation", ["privacy", "erase", "insert"])
def test_live_publication_guard_blocks_another_session_source_write(live, operation):
    engine, other, service, _, context, mid, cid = live
    started = Event()
    def mutate():
        started.set()
        if operation == "privacy":
            return other.backfill_evidence_privacy(context.tenant_id, cid, ["secret"])
        if operation == "erase":
            return other.forget(context.tenant_id, cid)
        return other.append_evidence(Evidence(tenant_id=context.tenant_id, user_id="owner", actor="user", source_type="chat",
            content="Another source", access_policy={"tenant": context.tenant_id}))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with engine.mental_model_guard(context.tenant_id):
            before = service._snapshot(context)
            future = pool.submit(mutate)
            assert started.wait(3)
            time.sleep(0.2)
            assert not future.done()
            row = engine.get_mental_model_record(context.tenant_id, mid)
            saved = engine.save_mental_model_record(context.tenant_id, mid, row, expected_version=row["version"])
            assert saved["version"] == row["version"] + 1
            assert service._snapshot(context) == before
        future.result(timeout=10)
    assert service._snapshot(context) != before


def test_live_lease_takeover_fences_original_worker(live, monkeypatch):
    engine, other, service, provider, context, mid, _ = live
    now = [datetime.now(UTC)]
    monkeypatch.setattr(scheduling, "utc_now", lambda: now[0])
    service.schedule(context, mid, interval_seconds=60)
    entered, release = Event(), Event()
    provider.callback = lambda: (entered.set(), release.wait(10))
    second = MentalModelService(other, Provider)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(MentalModelRefreshWorker(service, context, lease_seconds=30).run_once)
            assert entered.wait(5)
            assert MentalModelRefreshWorker(second, context, lease_seconds=30).run_once()["processed"] == 0
            now[0] += timedelta(seconds=31)
            assert MentalModelRefreshWorker(second, context, lease_seconds=30).run_once()["refreshed"] == 1
            version = engine.get_mental_model_record(context.tenant_id, mid)["version"]
            release.set()
            assert first.result(timeout=10)["lost"] == 1
        assert engine.get_mental_model_record(context.tenant_id, mid)["version"] == version
        assert service.get(context, mid)["answer"] == "Friday"
    finally:
        release.set()


def test_live_lease_expiry_without_takeover_cannot_publish(live, monkeypatch):
    _, _, service, provider, context, mid, _ = live
    now = [datetime.now(UTC)]
    monkeypatch.setattr(scheduling, "utc_now", lambda: now[0])
    service.schedule(context, mid)
    provider.callback = lambda: now.__setitem__(0, now[0] + timedelta(seconds=31))
    assert MentalModelRefreshWorker(service, context, lease_seconds=30).run_once()["lost"] == 1
    assert service.get(context, mid)["answer"] == ""


@pytest.mark.parametrize("operation", ["save", "delete"])
def test_live_guard_rolls_back_model_write(live, operation):
    engine, other, _, _, context, mid, _ = live
    before = other.get_mental_model_record(context.tenant_id, mid)
    with pytest.raises(RuntimeError, match="validation failed"):
        with engine.mental_model_guard(context.tenant_id):
            if operation == "delete":
                engine.delete_mental_model_record(context.tenant_id, mid, expected_version=before["version"])
            else:
                engine.save_mental_model_record(context.tenant_id, mid, before, expected_version=before["version"])
            raise RuntimeError("validation failed")
    assert other.get_mental_model_record(context.tenant_id, mid) == before


def test_live_rls_owner_and_pooled_tenant_isolation(live):
    engine, _, service, _, context, mid, _ = live
    with pytest.raises(LookupError):
        service.get(replace(context, user_id="another-owner"), mid)
    with engine.mental_model_guard(context.tenant_id):
        assert engine.get_mental_model_record(context.tenant_id, mid)
    other_tenant = f"other-{uuid4().hex}"
    assert engine.get_mental_model_record(other_tenant, mid) is None
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM mental_models")
            assert cur.fetchone()[0] == 0


def test_live_lock_wait_times_out_and_next_transaction_recovers(live):
    engine, _, _, _, context, mid, cid = live
    with psycopg.connect(engine.dsn) as blocking:
        with blocking.cursor() as cur:
            cur.execute("SELECT set_config('mnemosyne.tenant_id', %s, true)", (str(_stable_uuid("tenant", context.tenant_id)),))
            cur.execute("UPDATE evidence SET sensitivity=sensitivity WHERE tenant_id=%s AND cid=%s",
                        (_stable_uuid("tenant", context.tenant_id), _cid_to_bytes(cid)))
            started = time.monotonic()
            with pytest.raises(psycopg.errors.LockNotAvailable):
                with engine.mental_model_guard(context.tenant_id):
                    pytest.fail("entered guard while source writer held conflicting lock")
            assert 4.5 <= time.monotonic() - started < 9
    with engine.mental_model_guard(context.tenant_id):
        assert engine.get_mental_model_record(context.tenant_id, mid)


def test_live_app_role_model_delete_keeps_owner_and_evidence_boundaries(live):
    engine, _, _, _, context, mid, _ = live
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_APP_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_APP_DSN is not set")
    app = PostgresEngine(dsn, require_safe_role=True)
    try:
        service = MentalModelService(app)
        with pytest.raises(LookupError):
            service.delete(replace(context, user_id="wrong-owner"), mid)
        assert app.get_mental_model_record(context.tenant_id, mid) is not None
        assert service.delete(context, mid)["deleted"]
        with app.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT has_table_privilege(current_user, 'mental_models', 'DELETE'), "
                            "has_table_privilege(current_user, 'evidence', 'DELETE'), "
                            "has_table_privilege(current_user, 'audit_log', 'DELETE')")
                assert cur.fetchone() == (True, False, False)
    finally:
        app.close_connections()


def test_live_branch_discard_with_models_uses_restricted_owner_cascade(live):
    engine, _, service, _, context, _, _ = live
    engine.branch("scratch", tenant_id=context.tenant_id)
    branch_context = replace(context, branch="scratch")
    mid = service.create(branch_context, "Scratch", "What is the plan?")["model_id"]
    engine.discard("scratch", tenant_id=context.tenant_id)
    assert engine.get_mental_model_record(context.tenant_id, mid, "scratch") is None


def test_live_readonly_role_cannot_publish_or_delete_models(live):
    _, _, _, _, context, mid, _ = live
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_READONLY_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_READONLY_DSN is not set")
    reader = PostgresEngine(dsn, require_safe_role=True)
    try:
        row = reader.get_mental_model_record(context.tenant_id, mid)
        assert row is not None
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with reader.mental_model_guard(context.tenant_id):
                pytest.fail("readonly role acquired publication lock")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.delete_mental_model_record(context.tenant_id, mid, expected_version=row["version"])
        assert reader.get_mental_model_record(context.tenant_id, mid) == row
    finally:
        reader.close_connections()


def test_live_changed_source_refreshes_early_only_when_opted_in_and_spacing_elapsed(live, monkeypatch):
    engine, other, service, provider, context, mid, _ = live
    now = [datetime.now(UTC)]
    monkeypatch.setattr(scheduling, "utc_now", lambda: now[0])
    service.schedule(context, mid, interval_seconds=3600)
    assert MentalModelRefreshWorker(service, context).run_once()["refreshed"] == 1
    before = engine.get_mental_model_record(context.tenant_id, mid)
    other.append_evidence(Evidence(tenant_id=context.tenant_id, user_id="owner", actor="user", source_type="chat",
        content="Correction: Project Zephyr launches Tuesday.", access_policy={"tenant": context.tenant_id}))
    worker = MentalModelRefreshWorker(service, context, check_changes=True)
    now[0] += timedelta(seconds=59)
    assert worker.run_once()["processed"] == 0
    now[0] += timedelta(seconds=1)
    assert MentalModelRefreshWorker(service, context).run_once()["processed"] == 0
    assert engine.get_mental_model_record(context.tenant_id, mid) == before
    assert provider.calls == 1
    assert scheduling.timestamp(before["refresh_schedule"]["next_run_at"]) > now[0]
    assert worker.run_once()["refreshed"] == 1
    assert provider.calls == 2
    assert service.get(context, mid)["answer"] == "Tuesday"


def test_live_clean_change_scan_shares_snapshot_without_provider_or_model_write(live, monkeypatch):
    engine, _, service, provider, context, mid, _ = live
    now = [datetime.now(UTC)]
    monkeypatch.setattr(scheduling, "utc_now", lambda: now[0])
    second = service.create(context, "Zephyr second", "What day does Project Zephyr launch?")["model_id"]
    for model_id in (mid, second):
        service.schedule(context, model_id, interval_seconds=3600)
    assert MentalModelRefreshWorker(service, context).run_once()["refreshed"] == 2
    assert provider.calls == 2
    before = engine.list_mental_model_records(context.tenant_id)
    snapshots = []
    original = service._snapshot

    def capture_snapshot(scope):
        snapshots.append(scope)
        return original(scope)

    monkeypatch.setattr(service, "_snapshot", capture_snapshot)
    monkeypatch.setattr(service, "provider_factory", lambda: pytest.fail("clean scan constructed a provider"))
    now[0] += timedelta(seconds=61)
    report = MentalModelRefreshWorker(service, context, check_changes=True).run_once()
    assert report["processed"] == report["change_check_failed"] == 0
    assert snapshots == [context]
    assert engine.list_mental_model_records(context.tenant_id) == before


def test_live_change_scan_version_is_fenced_when_other_session_refreshes_first(live, monkeypatch):
    engine, other, service, provider, context, mid, _ = live
    now = [datetime.now(UTC)]
    monkeypatch.setattr(scheduling, "utc_now", lambda: now[0])
    service.schedule(context, mid, interval_seconds=3600)
    assert MentalModelRefreshWorker(service, context).run_once()["refreshed"] == 1
    other.append_evidence(Evidence(tenant_id=context.tenant_id, user_id="owner", actor="user", source_type="chat",
        content="Correction: Project Zephyr launches Tuesday.", access_policy={"tenant": context.tenant_id}))
    now[0] += timedelta(seconds=61)
    scanned, release = Event(), Event()
    original = service._snapshot

    def pause_after_snapshot(scope):
        result = original(scope)
        scanned.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(service, "_snapshot", pause_after_snapshot)
    competitor_provider = Provider()
    competitor = MentalModelService(other, lambda: competitor_provider)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(MentalModelRefreshWorker(service, context, check_changes=True).run_once)
        try:
            assert scanned.wait(5)
            assert MentalModelRefreshWorker(competitor, context, check_changes=True).run_once()["refreshed"] == 1
            saved = other.get_mental_model_record(context.tenant_id, mid)
        finally:
            release.set()
        assert first.result(timeout=10)["processed"] == 0
    assert provider.calls == competitor_provider.calls == 1
    assert engine.get_mental_model_record(context.tenant_id, mid) == saved
    assert competitor.get(context, mid)["answer"] == "Tuesday"


def test_live_source_changes_do_not_bypass_failed_refresh_backoff(live, monkeypatch):
    engine, other, service, provider, context, mid, _ = live
    now = [datetime.now(UTC)]
    monkeypatch.setattr(scheduling, "utc_now", lambda: now[0])
    service.schedule(context, mid, interval_seconds=3600)
    worker = MentalModelRefreshWorker(service, context, check_changes=True)
    assert worker.run_once()["refreshed"] == 1
    other.append_evidence(Evidence(tenant_id=context.tenant_id, user_id="owner", actor="user", source_type="chat",
        content="Correction: Project Zephyr launches Tuesday.", access_policy={"tenant": context.tenant_id}))

    def fail_provider():
        raise RuntimeError("fixture provider failure")

    provider.callback = fail_provider
    now[0] += timedelta(seconds=61)
    assert worker.run_once()["retry"] == 1
    before = engine.get_mental_model_record(context.tenant_id, mid)
    assert before["refresh_schedule"]["consecutive_failures"] == 1
    other.append_evidence(Evidence(tenant_id=context.tenant_id, user_id="owner", actor="user", source_type="chat",
        content="The Project Zephyr launch announcement is final.", access_policy={"tenant": context.tenant_id}))
    now[0] += timedelta(seconds=61)
    monkeypatch.setattr(service, "_snapshot", lambda scope: pytest.fail("backoff should skip change scans"))
    assert worker.run_once()["processed"] == 0
    assert provider.calls == 2
    assert engine.get_mental_model_record(context.tenant_id, mid) == before
