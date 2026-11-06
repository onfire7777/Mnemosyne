"""Source changes revalidate only their dependency closure, under current authority."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import os
from uuid import uuid4

import pytest

import mnemosyne.access_policy as access_policy
from mnemosyne.answering import AnswerReadContext
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mental_models import MentalModelService
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine
from tests.test_mental_model_watermark import SimpleProvider


@pytest.fixture(params=["local", "sqlite", "postgres"])
def setup(request, tmp_path):
    tenant = f"incremental-{uuid4().hex}"
    context = AnswerReadContext(tenant_id=tenant, user_id="u", role="agent", max_sensitivity=0)
    if request.param == "postgres":
        dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
        if not dsn:
            pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
        from mnemosyne.postgres_engine import PostgresEngine
        engine = PostgresEngine(dsn, require_safe_role=True)
    else:
        engine = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "store")
    service = MentalModelService(engine, SimpleProvider)
    yield engine, service, context
    if request.param == "postgres":
        engine.close_connections()
    else:
        engine.close()


def append(engine, context, text="Project Zephyr launches Friday.", **kwargs):
    return engine.append_evidence(Evidence(
        tenant_id=context.tenant_id, user_id=context.user_id, actor="user", source_type=kwargs.pop("source_type", "chat"),
        content=text, access_policy=kwargs.pop("access_policy", {"tenant": context.tenant_id, "allow_principals": [context.user_id]}),
        **kwargs,
    ), branch=context.branch)


def ready(engine, service, context):
    cid = append(engine, context)
    model = service.create(context, "Launch", "When does Project Zephyr launch?")["model_id"]
    # Isolate snapshot freshness from backend ranking/channel provenance. The
    # reader/refresh entry point is covered by the existing live-backend suite.
    fingerprint, evidence = service._snapshot(context)
    start = evidence[cid]["content"].index("Friday")
    record = engine.get_mental_model_record(context.tenant_id, model)
    record.update(status="ready", corpus_fingerprint=fingerprint, time_fingerprint=None,
                  source_evidence_cids=[cid], answer={
        "answer": "Friday", "abstained": False, "reader": {}, "claims": [{
            "text": "Friday", "evidence_cids": [cid],
            "derivation": {"schema_version": "mnemosyne.claim-derivation/v1", "kind": "quotation", "operation": None},
            "spans": [{"cid": cid, "start": start, "end": start + 6,
                       "slice_sha256": hashlib.sha256(b"Friday").hexdigest()}],
        }],
    })
    engine.save_mental_model_record(context.tenant_id, model, record, expected_version=record["version"])
    assert service.get(context, model)["answer"] == "Friday"
    return cid, model


def forbid_exports(engine, monkeypatch):
    monkeypatch.setattr(engine, "export_tenant", lambda *_: pytest.fail("incremental update scanned the tenant"))
    monkeypatch.setattr(engine, "export_tenant_filtered", lambda *_: pytest.fail("incremental update exported the tenant"))


def test_unrelated_and_new_relevant_evidence_use_changed_rows_only(setup, monkeypatch):
    engine, service, context = setup
    _, model = ready(engine, service, context)
    before = service._snapshot(context)[0]
    forbid_exports(engine, monkeypatch)
    calls, original = [], engine.mental_model_source_rows
    def changed_rows(tenant, changes):
        calls.extend(changes)
        return original(tenant, changes)
    monkeypatch.setattr(engine, "mental_model_source_rows", changed_rows)
    unrelated = append(engine, context, "The garden has a cherry tree.")
    after = service._snapshot(context)
    assert after[0] != before and unrelated in after[1]
    correction = append(engine, context, "Correction: Project Zephyr launches Tuesday.")
    assert service.get(context, model)["stale"]
    assert correction in service._snapshot(context)[1]
    assert {row[2] for row in calls} == {unrelated, correction}


def test_inaccessible_and_other_branch_writes_preserve_fresh_answer(setup, monkeypatch):
    engine, service, context = setup
    engine.branch("other", tenant_id=context.tenant_id)
    _, model = ready(engine, service, context)
    forbid_exports(engine, monkeypatch)
    append(engine, replace(context, user_id="private"), "Project Zephyr launches Tuesday.")
    append(engine, replace(context, branch="other"), "Other branch Project Zephyr launches Tuesday.")
    view = service.get(context, model)
    assert view["answer"] == "Friday" and not view["stale"]


def test_metadata_change_rechecks_transitive_summary_custody(setup, monkeypatch):
    engine, service, context = setup
    cid = append(engine, context)
    summary = append(engine, context, "Summary of Project Zephyr.", source_type="consolidation-summary",
                     metadata={"summary": {"source_evidence_cids": [cid]}})
    assert summary in service._snapshot(context)[1]
    forbid_exports(engine, monkeypatch)
    engine.update_evidence_metadata(context.tenant_id, cid, {"quarantine_reason": "review required"})
    evidence = service._snapshot(context)[1]
    assert cid not in evidence and summary not in evidence


@pytest.mark.parametrize("naive", [False, True])
@pytest.mark.parametrize("historical", [False, True])
def test_expiry_rechecks_sources_without_a_storage_write(setup, monkeypatch, naive, historical):
    engine, service, context = setup
    clock = [datetime.now(UTC)]
    if historical:
        context = replace(context, as_of=clock[0] - timedelta(days=1))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)
    monkeypatch.setattr(access_policy, "datetime", Clock)
    deadline = clock[0] + timedelta(minutes=1)
    if naive:
        deadline = deadline.replace(tzinfo=None)
    cid = append(engine, context, created_at=clock[0] - timedelta(days=2), access_policy={"tenant": context.tenant_id,
        "expires_at": deadline.isoformat()})
    assert cid in service._snapshot(context)[1]
    forbid_exports(engine, monkeypatch)
    clock[0] += timedelta(minutes=2)
    assert cid not in service._snapshot(context)[1]


def test_legacy_saved_fingerprint_stays_readable_after_cold_cache(setup):
    engine, service, context = setup
    _, model = ready(engine, service, context)
    state = next(iter(engine._mental_model_source_cache.values()))
    record = engine.get_mental_model_record(context.tenant_id, model)
    record["corpus_fingerprint"] = state.legacy_fingerprint
    engine.save_mental_model_record(context.tenant_id, model, record, expected_version=record["version"])
    service.clear_watermark_cache()
    assert service.get(context, model)["answer"] == "Friday"


def direct_metadata_write(engine, context, cid, *, rollback=False):
    if isinstance(engine, LocalMemoryEngine):
        row = engine.evidence[engine._evidence_key(context.tenant_id, context.branch, cid)]
        row.metadata = {**row.metadata, "quarantine_reason": "private review"}
        return
    if isinstance(engine, SqliteEngine):
        conn = engine._connect(context.tenant_id)
        conn.execute("BEGIN")
        conn.execute("UPDATE evidence SET metadata = json_set(metadata, '$.quarantine_reason', 'private review') WHERE cid = ?", (cid,))
        conn.rollback() if rollback else conn.commit()
        return
    from mnemosyne.postgres_engine import _cid_to_bytes, _stable_uuid
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, _stable_uuid("tenant", context.tenant_id))
            cur.execute("UPDATE evidence SET metadata = metadata || %s::jsonb WHERE tenant_id = %s AND cid = %s",
                        ('{"quarantine_reason":"private review"}', _stable_uuid("tenant", context.tenant_id), _cid_to_bytes(cid)))
        if rollback:
            conn.rollback()


def test_direct_source_edit_invalidates_even_without_an_audit_event(setup):
    engine, service, context = setup
    cid, model = ready(engine, service, context)
    direct_metadata_write(engine, context, cid)
    view = service.get(context, model)
    assert view["stale"] and view["answer"] == ""


def test_rolled_back_database_edit_does_not_advance_source_revision(setup, monkeypatch):
    engine, service, context = setup
    if isinstance(engine, LocalMemoryEngine):
        pytest.skip("database transaction probe")
    cid, model = ready(engine, service, context)
    before = engine.mental_model_source_revision(context.tenant_id)
    direct_metadata_write(engine, context, cid, rollback=True)
    assert engine.mental_model_source_revision(context.tenant_id) == before
    forbid_exports(engine, monkeypatch)
    assert service.get(context, model)["answer"] == "Friday"


def test_direct_acl_update_withholds_answer(setup):
    engine, service, context = setup
    cid, model = ready(engine, service, context)
    policy = {"tenant": context.tenant_id, "allow_principals": ["someone-else"]}
    if isinstance(engine, LocalMemoryEngine):
        engine.evidence[engine._evidence_key(context.tenant_id, context.branch, cid)].access_policy = policy
    elif isinstance(engine, SqliteEngine):
        import json
        conn = engine._connect(context.tenant_id)
        with conn:
            conn.execute("UPDATE evidence SET access_policy = ? WHERE cid = ?", (json.dumps(policy), cid))
    else:
        from mnemosyne.postgres_engine import _cid_to_bytes, _stable_uuid
        with engine.connect() as conn:
            with conn.cursor() as cur:
                engine._set_tenant(cur, _stable_uuid("tenant", context.tenant_id))
                cur.execute("UPDATE evidence SET access_policy = %s WHERE tenant_id = %s AND cid = %s",
                            (engine._jsonb(policy), _stable_uuid("tenant", context.tenant_id), _cid_to_bytes(cid)))
    assert service.get(context, model)["answer"] == ""


def test_hard_delete_resets_snapshot_and_scrubs_change_identifiers(setup):
    engine, service, context = setup
    cid, model = ready(engine, service, context)
    assert engine.forget(context.tenant_id, cid, requested_by="legal", erasure_mode="hard_delete_legal")["erased"]
    assert cid not in service._snapshot(context)[1]
    assert service.get(context, model)["answer"] == ""
    if isinstance(engine, LocalMemoryEngine):
        assert cid not in str(engine._source_change_events)
    elif isinstance(engine, SqliteEngine):
        assert not engine._connect(context.tenant_id).execute(
            "SELECT 1 FROM memory_source_changes WHERE item_id = ?", (cid,)).fetchone()
    else:
        from mnemosyne.postgres_engine import _stable_uuid
        with engine.connect() as conn:
            with conn.cursor() as cur:
                engine._set_tenant(cur, _stable_uuid("tenant", context.tenant_id))
                cur.execute("SELECT 1 FROM memory_source_changes WHERE item_id = %s", (cid,))
                assert cur.fetchone() is None


def test_unknown_change_record_fails_closed(setup):
    engine, service, context = setup
    cid, model = ready(engine, service, context)
    if isinstance(engine, LocalMemoryEngine):
        engine._source_change_revision += 1
        engine._source_change_events.append((engine._source_change_revision, context.tenant_id, "unknown", "main", cid))
    elif isinstance(engine, SqliteEngine):
        conn = engine._connect(context.tenant_id)
        with conn:
            conn.execute("UPDATE memory_source_revisions SET revision = revision + 1 WHERE tenant_id = ?", (context.tenant_id,))
            conn.execute("INSERT INTO memory_source_changes SELECT tenant_id, revision, 'unknown', 'main', ? FROM memory_source_revisions WHERE tenant_id = ?", (cid, context.tenant_id))
    else:
        from mnemosyne.postgres_engine import _stable_uuid
        with engine.connect() as conn:
            with conn.cursor() as cur:
                tenant = _stable_uuid("tenant", context.tenant_id)
                engine._set_tenant(cur, tenant)
                cur.execute("UPDATE memory_source_revisions SET revision = revision + 1 WHERE tenant_id = %s RETURNING revision", (tenant,))
                revision = cur.fetchone()[0]
                cur.execute("INSERT INTO memory_source_changes VALUES (%s, %s, 'unknown', 'main', %s)", (tenant, revision, cid))
    view = service.get(context, model)
    assert view["stale"] and view["answer"] == ""


def test_other_tenant_changes_do_not_rescan_model(setup, monkeypatch):
    engine, service, context = setup
    _, model = ready(engine, service, context)
    forbid_exports(engine, monkeypatch)
    append(engine, replace(context, tenant_id=context.tenant_id + "-other"), "Other tenant evidence.")
    assert service.get(context, model)["answer"] == "Friday"


def test_missing_database_change_record_rebuilds_safely(setup):
    engine, service, context = setup
    if isinstance(engine, LocalMemoryEngine):
        pytest.skip("database change stream corruption probe")
    cid, model = ready(engine, service, context)
    before = engine.mental_model_source_revision(context.tenant_id)
    direct_metadata_write(engine, context, cid)
    if isinstance(engine, SqliteEngine):
        conn = engine._connect(context.tenant_id)
        with conn:
            conn.execute("DELETE FROM memory_source_changes WHERE revision > ?", (before,))
    else:
        from mnemosyne.postgres_engine import _stable_uuid
        with engine.connect() as conn:
            with conn.cursor() as cur:
                engine._set_tenant(cur, _stable_uuid("tenant", context.tenant_id))
                cur.execute("DELETE FROM memory_source_changes WHERE revision > %s", (before,))
    assert service.get(context, model)["answer"] == ""


def test_postgres_change_revision_cannot_skip_an_uncommitted_writer(setup):
    engine, service, context = setup
    if isinstance(engine, (LocalMemoryEngine, SqliteEngine)):
        pytest.skip("PostgreSQL transaction ordering probe")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from mnemosyne.postgres_engine import _cid_to_bytes, _stable_uuid
    first = append(engine, context)
    second = append(engine, context, "A second independent source.")
    service._snapshot(context)
    baseline = engine.mental_model_source_revision(context.tenant_id)
    tenant = _stable_uuid("tenant", context.tenant_id)
    started = Event()
    def later_writer():
        with engine.connect() as conn:
            with conn.cursor() as cur:
                engine._set_tenant(cur, tenant)
                started.set()
                cur.execute("UPDATE evidence SET metadata = metadata || '{\"second\":true}'::jsonb WHERE tenant_id = %s AND cid = %s", (tenant, _cid_to_bytes(second)))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with engine.connect() as first_conn:
            with first_conn.cursor() as cur:
                engine._set_tenant(cur, tenant)
                cur.execute("UPDATE evidence SET metadata = metadata || '{\"first\":true}'::jsonb WHERE tenant_id = %s AND cid = %s", (tenant, _cid_to_bytes(first)))
            later = pool.submit(later_writer)
            assert started.wait(5)
            # The other writer cannot publish a later revision before this one.
            assert engine.mental_model_source_revision(context.tenant_id) == baseline
            assert not later.done()
        later.result(timeout=10)
    changes = engine.mental_model_source_changes(context.tenant_id, context.branch, baseline)
    assert {change[2] for change in changes} == {first, second}
    snapshot = service._snapshot(context)[1]
    assert snapshot[first]["metadata"]["first"] is True
    assert snapshot[second]["metadata"]["second"] is True


def test_unavailable_tracking_uses_fresh_legacy_snapshots(setup, monkeypatch):
    engine, service, context = setup
    _, model = ready(engine, service, context)
    state = next(iter(engine._mental_model_source_cache.values()))
    row = engine.get_mental_model_record(context.tenant_id, model)
    row["corpus_fingerprint"] = state.legacy_fingerprint
    engine.save_mental_model_record(context.tenant_id, model, row, expected_version=row["version"])
    service.clear_watermark_cache()
    monkeypatch.setattr(engine, "mental_model_source_revision", lambda _: None)
    calls, original = [], engine.export_tenant_filtered
    def export(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(engine, "export_tenant_filtered", export)
    assert service.get(context, model)["answer"] == "Friday"
    assert service.get(context, model)["answer"] == "Friday"
    append(engine, context, "Correction: Project Zephyr launches Tuesday.")
    view = service.get(context, model)
    assert view["stale"] and view["answer"] == ""
    assert len(calls) == 3


@pytest.mark.parametrize("operation", ["privacy", "erasure"])
def test_sensitive_writes_immediately_purge_cached_plaintext_across_live_engines(setup, operation):
    engine, service, context = setup
    cid, _ = ready(engine, service, context)
    other = None
    if isinstance(engine, SqliteEngine):
        other = SqliteEngine(engine.root_dir)
    elif not isinstance(engine, LocalMemoryEngine):
        from mnemosyne.postgres_engine import PostgresEngine
        other = PostgresEngine(engine.dsn, require_safe_role=True)
    if other:
        MentalModelService(other)._snapshot(context)
    engines = [engine, *([other] if other else [])]
    states = [state for item in engines for state in item._mental_model_source_cache.values()]
    assert states and all(state.raw and state.filtered and state.evidence for state in states)
    try:
        if operation == "privacy":
            assert engine.backfill_evidence_privacy(context.tenant_id, cid, ["secret"])
        else:
            assert engine.forget(context.tenant_id, cid, requested_by="legal", erasure_mode="hard_delete_legal")["erased"]
        # No model read or fresh snapshot may be needed to discard the old data.
        for state in states:
            assert state.raw == state.filtered == state.evidence == {}
        for item in engines:
            assert item._mental_model_source_cache == {}
            assert item._mental_model_snapshot_cache == {}
    finally:
        if other:
            other.close() if isinstance(other, SqliteEngine) else other.close_connections()


@pytest.mark.parametrize("rollback", [False, True])
def test_nested_erasure_cache_purge_follows_outer_commit(setup, rollback):
    engine, service, context = setup
    cid, model = ready(engine, service, context)
    state = next(iter(engine._mental_model_source_cache.values()))
    class Abort(Exception):
        pass
    try:
        with engine.source_transaction(context.tenant_id):
            engine.forget(context.tenant_id, cid)
            assert state.raw  # The outer transaction still owns the mutation.
            if rollback:
                raise Abort
    except Abort:
        pass
    if rollback:
        assert state.raw
        assert service.get(context, model)["answer"] == "Friday"
    else:
        assert state.raw == state.filtered == state.evidence == {}
        assert service.get(context, model)["answer"] == ""


def test_native_nonpersisted_projection_write_invalidates_snapshot(setup):
    engine, service, context = setup
    if not isinstance(engine, LocalMemoryEngine):
        pytest.skip("native nonpersisted projection batching")
    from mnemosyne.models import Assertion
    cid = append(engine, context)
    before = service._snapshot(context)[0]
    engine._upsert_assertion_core(Assertion(
        tenant_id=context.tenant_id, user_id=context.user_id, subject="Zephyr", predicate="launches",
        object="Friday", source_evidence_cids=[cid], status="active", access_policy={"tenant": context.tenant_id},
    ), persist=False)
    assert service._snapshot(context)[0] != before


def test_cached_list_preserves_independently_cited_models(setup):
    engine, service, context = setup
    _, first = ready(engine, service, context)
    cid = append(engine, context, "Project Atlas launches Monday.")
    second = service.create(context, "Atlas", "When does Project Atlas launch?")["model_id"]
    fingerprint, evidence = service._snapshot(context)
    first_record = engine.get_mental_model_record(context.tenant_id, first)
    first_record["corpus_fingerprint"] = fingerprint
    engine.save_mental_model_record(context.tenant_id, first, first_record, expected_version=first_record["version"])
    record = engine.get_mental_model_record(context.tenant_id, second)
    start = evidence[cid]["content"].index("Monday")
    record.update(status="ready", corpus_fingerprint=fingerprint, time_fingerprint=None,
                  source_evidence_cids=[cid], answer={
        "answer": "Monday", "abstained": False, "reader": {}, "claims": [{
            "text": "Monday", "evidence_cids": [cid],
            "derivation": {"schema_version": "mnemosyne.claim-derivation/v1", "kind": "quotation", "operation": None},
            "spans": [{"cid": cid, "start": start, "end": start + 6,
                       "slice_sha256": hashlib.sha256(b"Monday").hexdigest()}],
        }],
    })
    engine.save_mental_model_record(context.tenant_id, second, record, expected_version=record["version"])
    assert service.get(context, first)["answer"] == "Friday"
    assert service.get(context, second)["answer"] == "Monday"
    views = {view["model_id"]: view for view in service.list(context)}
    assert views[first]["answer"] == "Friday"
    assert views[second]["answer"] == "Monday"


def test_committed_erasure_waits_for_inflight_snapshot_publication(setup, monkeypatch):
    engine, service, context = setup
    if isinstance(engine, LocalMemoryEngine):
        pytest.skip("independent database connections")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import mnemosyne.mental_model_sources as sources
    cid = append(engine, context)
    if isinstance(engine, SqliteEngine):
        writer = SqliteEngine(engine.root_dir)
    else:
        from mnemosyne.postgres_engine import PostgresEngine
        writer = PostgresEngine(engine.dsn, require_safe_role=True)
    blocked, release, committed, purge_returned = Event(), Event(), Event(), Event()
    original_result, original_purge = sources.SourceSnapshot.result, sources.purge_source_snapshot_caches
    calls = 0
    def pause_publication(state):
        nonlocal calls
        result = original_result(state)
        if state.engine is engine:
            calls += 1
            if calls == 2:  # load() computes the baseline before the publication check.
                blocked.set()
                assert release.wait(10)
        return result
    def observe_purge(*args):
        committed.set()
        original_purge(*args)
        purge_returned.set()
    monkeypatch.setattr(sources.SourceSnapshot, "result", pause_publication)
    monkeypatch.setattr(sources, "purge_source_snapshot_caches", observe_purge)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            read = pool.submit(service._snapshot, context)
            assert blocked.wait(10)
            erase = pool.submit(writer.forget, context.tenant_id, cid)
            try:
                assert committed.wait(10)
                assert not purge_returned.wait(0.2)
            finally:
                release.set()
            read.result(timeout=10)
            assert erase.result(timeout=10)["erased"]
        assert engine._mental_model_source_cache == {}
        assert engine._mental_model_snapshot_cache == {}
    finally:
        release.set()
        writer.close() if isinstance(writer, SqliteEngine) else writer.close_connections()
