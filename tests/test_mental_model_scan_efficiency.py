"""Bound advisory scan work without caching source authority or returned prose."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

import mnemosyne.mental_model_refresh as scheduling
from mnemosyne.answering import AnswerReadContext
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mental_model_refresh import MentalModelRefreshWorker, new_schedule
from mnemosyne.mental_models import MentalModelService
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine

CTX = AnswerReadContext(tenant_id="t", user_id="u", role="agent", max_sensitivity=0)


@pytest.fixture(params=["local", "sqlite"])
def setup(request, tmp_path, monkeypatch):
    engine = LocalMemoryEngine(tmp_path / "store.json") if request.param == "local" else SqliteEngine(tmp_path / "store")
    wall, ticks = [datetime.now(UTC)], [100.0]
    monkeypatch.setattr(scheduling, "utc_now", lambda: wall[0])
    monkeypatch.setattr(scheduling, "monotonic", lambda: ticks[0])
    def forbidden():
        raise AssertionError("this test must never construct a provider")
    service = MentalModelService(engine, forbidden)
    cids = [engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="chat",
        content="Project Zephyr launches Friday." if i == 0 else f"Source {i}.",
        metadata={"revision_note": "original"}, access_policy={"tenant": "t", "allow_principals": ["u"]}))
        for i in range(8)]
    yield engine, service, wall, ticks, cids
    engine.close()


def saved(service, wall, *, ready=False):
    mid = service.create(CTX, "Saved model", "When does Project Zephyr launch?")["model_id"]
    row = service._load(CTX, mid)
    fingerprint, evidence = service._snapshot(CTX)
    row.update(status="abstained", corpus_fingerprint=fingerprint, time_fingerprint=None)
    if ready:
        cid, source = next((cid, ev["content"]) for cid, ev in evidence.items() if "Friday" in ev["content"])
        start = source.index("Friday")
        row.update(status="ready", source_evidence_cids=[cid], answer={
            "answer": "Friday", "abstained": False, "reader": {}, "claims": [{
                "text": "Friday", "spans": [{"cid": cid, "start": start, "end": start + 6,
                                              "slice_sha256": hashlib.sha256(b"Friday").hexdigest()}],
                "evidence_cids": [cid], "derivation": {"schema_version": "mnemosyne.claim-derivation/v1",
                                                       "kind": "quotation", "operation": None}}]})
    schedule = new_schedule(True, 3600)
    schedule.update(next_run_at=(wall[0] + timedelta(hours=1)).isoformat(),
                    last_started_at=(wall[0] - timedelta(minutes=2)).isoformat(),
                    last_finished_at=(wall[0] - timedelta(minutes=2)).isoformat(), last_outcome="abstained")
    row["refresh_schedule"] = schedule
    service.engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
    return mid


def count_scans(engine, monkeypatch):
    counts = {"exports": 0, "point_reads": 0}
    original_export, original_get = engine.export_tenant_filtered, engine.get_evidence
    def export(*args, **kwargs):
        counts["exports"] += 1
        return original_export(*args, **kwargs)
    def get(*args, **kwargs):
        counts["point_reads"] += 1
        return original_get(*args, **kwargs)
    monkeypatch.setattr(engine, "export_tenant_filtered", export)
    monkeypatch.setattr(engine, "get_evidence", get)
    return counts


def test_pending_and_error_views_need_no_source_scan(setup, monkeypatch):
    engine, service, _, _, _ = setup
    counts = count_scans(engine, monkeypatch)
    mid = service.create(CTX, "Pending", "What is known?")["model_id"]
    assert service.get(CTX, mid)["status"] == "pending"
    row = service._load(CTX, mid)
    row.update(status="error", answer={"answer": "NEVER RETURN THIS"}, source_evidence_cids=["hidden"])
    engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
    for view in (service.get(CTX, mid), service.list(CTX)[0]):
        assert view["status"] == "error" and not view["stale"]
        assert view["answer"] == "" and view["claims"] == [] and view["source_evidence_cids"] == []
    assert counts == {"exports": 0, "point_reads": 0}


def test_empty_and_other_owner_lists_skip_snapshot(setup, monkeypatch):
    engine, service, wall, _, _ = setup
    saved(service, wall, ready=True)
    counts = count_scans(engine, monkeypatch)
    assert service.list(replace(CTX, user_id="other")) == []
    assert service.list(replace(CTX, branch="other")) == []
    assert counts == {"exports": 0, "point_reads": 0}


def test_clean_polls_share_one_scan_until_monotonic_deadline(setup, monkeypatch):
    engine, service, wall, ticks, _ = setup
    for _ in range(3):
        saved(service, wall)
    counts = count_scans(engine, monkeypatch)
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True)
    assert worker.run_once()["processed"] == 0
    ticks[0] += 4.999
    wall[0] += timedelta(minutes=1)  # Wall-clock changes cannot bypass the monotonic interval.
    assert worker.run_once()["processed"] == 0
    assert counts == {"exports": 1, "point_reads": 8}
    ticks[0] = 105.0
    assert worker.run_once()["processed"] == 0
    assert counts == {"exports": 2, "point_reads": 16}
    assert worker._change_hints == {}


def test_every_poll_checks_authority_even_without_scan(setup, monkeypatch):
    engine, service, wall, _, _ = setup
    saved(service, wall)
    allowed, calls = [True], []
    def authority():
        calls.append(1)
        if not allowed[0]:
            raise PermissionError("revoked")
    counts = count_scans(engine, monkeypatch)
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True, validate_authority=authority)
    worker.run_once()
    worker.run_once()
    allowed[0] = False
    with pytest.raises(PermissionError, match="revoked"):
        worker.run_once()
    assert len(calls) == 3 and counts["exports"] == 1


def test_due_work_runs_during_advisory_scan_cooldown(setup, monkeypatch):
    engine, service, wall, _, _ = setup
    mid = saved(service, wall)
    counts = count_scans(engine, monkeypatch)
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True)
    worker.run_once()
    row = service._load(CTX, mid)
    row["refresh_schedule"]["next_run_at"] = (wall[0] - timedelta(seconds=1)).isoformat()
    engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
    assert worker.run_once()["unchanged"] == 1
    assert counts["exports"] == 2  # Advisory scan plus the independent due refresh preflight.


@pytest.mark.parametrize("mutation", ["erasure", "privacy"])
def test_ready_get_and_list_reauthorize_inside_scan_cooldown(setup, monkeypatch, mutation):
    engine, service, wall, _, cids = setup
    mid = saved(service, wall, ready=True)
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True)
    worker.run_once()
    assert service.get(CTX, mid)["answer"] == "Friday"
    if mutation == "erasure":
        engine.forget("t", cids[0])
    else:
        engine.backfill_evidence_privacy("t", cids[0], ["secret"])
    counts = count_scans(engine, monkeypatch)
    for view in (service.get(CTX, mid), service.list(CTX)[0]):
        assert view["stale"] and view["answer"] == "" and view["claims"] == []
    assert counts["exports"] == 2


def test_new_worker_scans_immediately_even_with_reset_clock_origin(setup, monkeypatch):
    engine, service, wall, ticks, _ = setup
    saved(service, wall)
    counts = count_scans(engine, monkeypatch)
    old = MentalModelRefreshWorker(service, CTX, check_changes=True)
    old.run_once()
    ticks[0] = -100.0
    MentalModelRefreshWorker(service, CTX, check_changes=True).run_once()
    assert counts["exports"] == 2


def test_failed_advisory_scans_are_bounded_but_due_work_and_retry_survive(setup, monkeypatch):
    _, service, wall, ticks, _ = setup
    mid = saved(service, wall)
    original, scans = service._snapshot, []
    def fail_once(context):
        scans.append(1)
        if len(scans) == 1:
            raise RuntimeError("private diagnostic")
        return original(context)
    monkeypatch.setattr(service, "_snapshot", fail_once)
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True)
    assert worker.run_once()["change_check_failed"] == 1
    assert worker.run_once()["change_check_failed"] == 0
    assert len(scans) == 1
    row = service._load(CTX, mid)
    row["refresh_schedule"]["next_run_at"] = (wall[0] - timedelta(seconds=1)).isoformat()
    service.engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
    assert worker.run_once()["unchanged"] == 1 and len(scans) == 2
    ticks[0] += 5
    wall[0] += timedelta(seconds=61)
    assert worker.run_once()["processed"] == 0 and len(scans) == 3


def stale_hints_without_provider(setup, monkeypatch, count=3):
    engine, service, wall, _, cids = setup
    mids = [saved(service, wall) for _ in range(count)]
    engine.update_evidence_metadata("t", cids[0], {"revision_note": "changed"})
    original, calls = service._snapshot, []
    def snapshot(context):
        result = original(context)
        calls.append(1)
        if len(calls) == 1:
            # Detection saw a change, but preflight must independently see its reversal.
            engine.update_evidence_metadata("t", cids[0], {"revision_note": "original"})
        return result
    monkeypatch.setattr(service, "_snapshot", snapshot)
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True, max_batch=1)
    assert worker.run_once()["unchanged"] == 1
    return worker, mids, calls


def test_versioned_stale_backlog_drains_without_repeat_advisory_scan(setup, monkeypatch):
    worker, _, calls = stale_hints_without_provider(setup, monkeypatch)
    assert len(worker._change_hints) == 2
    assert all(type(mid) is str and type(version) is int for mid, version in worker._change_hints.items())
    assert worker.run_once()["unchanged"] == 1
    assert worker.run_once()["unchanged"] == 1
    assert calls == [1] * 4  # One detection snapshot plus three independent refresh preflights.
    assert worker._change_hints == {}


@pytest.mark.parametrize("mutation", ["delete", "disable", "reschedule", "context_owner", "scope"])
def test_pending_hint_never_revives_a_changed_record(setup, monkeypatch, mutation):
    _, service, _, _, _ = setup
    worker, _, _ = stale_hints_without_provider(setup, monkeypatch, count=2)
    mid = next(iter(worker._change_hints))
    if mutation == "delete":
        service.delete(CTX, mid)
    elif mutation in {"disable", "reschedule"}:
        service.schedule(CTX, mid, enabled=mutation != "disable")
        if mutation == "reschedule":
            row = service._load(CTX, mid)
            row["refresh_schedule"]["next_run_at"] = "2099-01-01T00:00:00+00:00"
            service.engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
    elif mutation == "context_owner":
        worker.context = replace(CTX, user_id="other")
    else:
        row = service._load(CTX, mid)
        row["scope"] = {**row["scope"], "max_sensitivity": 3}
        service.engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
    assert worker.run_once()["processed"] == 0
    assert mid not in worker._change_hints
