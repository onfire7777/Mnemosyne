"""Opt-in change-aware polling preserves scope, cooldowns, and publication fences."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

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


class Reader:
    disclosure = {"query_decomposer": {"model": "fixture"}, "grounded_reader": {"model": "fixture"}}

    def __init__(self):
        self.calls = 0
        self.callback = None
        self.fail = False

    def decompose(self, payload):
        return ExtractiveQueryDecomposer().decompose(payload)

    def read(self, payload):
        self.calls += 1
        if self.callback:
            self.callback()
        if self.fail:
            raise RuntimeError("fixture failure must not escape")
        for day in ("Tuesday", "Friday"):
            for row in payload["evidence"]:
                if day in row["content"]:
                    return {"claims": [{"spans": [{"cid": row["cid"], "quote": day}]}], "unresolved": False}
        return {"claims": [], "unresolved": True}


def append(engine, text="Project Zephyr launches Friday.", *, context=CTX, sensitivity=0):
    return engine.append_evidence(Evidence(
        tenant_id=context.tenant_id, user_id=context.user_id, branch=context.branch,
        actor="user", source_type="chat", content=text, sensitivity=sensitivity,
        metadata={"revision_note": "original"},
        access_policy={"tenant": context.tenant_id, "allow_principals": [context.user_id]},
    ), branch=context.branch)


def create(service, name="Zephyr", context=CTX):
    return service.create(context, name, "When does Project Zephyr launch?")["model_id"]


@pytest.fixture(params=["local", "sqlite"])
def setup(request, tmp_path, monkeypatch):
    engine = LocalMemoryEngine(tmp_path / "store.json") if request.param == "local" else SqliteEngine(tmp_path / "store")
    now = [datetime.now(UTC)]
    monkeypatch.setattr(scheduling, "utc_now", lambda: now[0])
    reader = Reader()
    service = MentalModelService(engine, lambda: reader)
    cid = append(engine)
    model = create(service)
    service.schedule(CTX, model, interval_seconds=3600)
    assert MentalModelRefreshWorker(service, CTX).run_once()["refreshed"] == 1
    yield engine, service, reader, model, cid, now
    engine.close()


def test_change_checks_are_opt_in_and_refresh_before_interval(setup):
    engine, service, reader, model, _, now = setup
    append(engine, "Correction: Project Zephyr launches Tuesday.")
    now[0] += timedelta(seconds=61)
    assert service.get(CTX, model)["stale"]
    assert MentalModelRefreshWorker(service, CTX).run_once()["processed"] == 0
    report = MentalModelRefreshWorker(service, CTX, check_changes=True).run_once()
    assert report["refreshed"] == 1 and reader.calls == 2
    assert service.get(CTX, model)["answer"] == "Tuesday"
    assert report["change_check_failed"] == 0


def test_clean_poll_shares_one_snapshot_and_never_loads_provider(setup, monkeypatch):
    _, service, _, _, _, now = setup
    for name in ("Second", "Third"):
        model = create(service, name)
        service.schedule(CTX, model, interval_seconds=3600)
    assert MentalModelRefreshWorker(service, CTX).run_once()["refreshed"] == 2
    now[0] += timedelta(seconds=61)
    real_snapshot, calls = service._snapshot, []

    def snapshot(context):
        calls.append(context)
        return real_snapshot(context)

    monkeypatch.setattr(service, "_snapshot", snapshot)
    service.provider_factory = lambda: pytest.fail("clean poll loaded a provider")
    assert MentalModelRefreshWorker(service, CTX, check_changes=True).run_once()["processed"] == 0
    assert calls == [CTX]


def test_reverted_source_after_detection_skips_provider(setup, monkeypatch):
    engine, service, reader, _, cid, now = setup
    engine.update_evidence_metadata(CTX.tenant_id, cid, {"revision_note": "changed"})
    now[0] += timedelta(seconds=61)
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True)
    real_claim = worker._claim

    def revert_then_claim(model_id, *, changed_version=None):
        assert changed_version is not None
        engine.update_evidence_metadata(CTX.tenant_id, cid, {"revision_note": "original"})
        return real_claim(model_id, changed_version=changed_version)

    monkeypatch.setattr(worker, "_claim", revert_then_claim)
    service.provider_factory = lambda: pytest.fail("reverted source loaded a provider")
    assert worker.run_once()["unchanged"] == 1
    assert reader.calls == 1


def test_continuous_changes_wait_sixty_seconds_after_attempt_finishes(setup):
    engine, service, reader, _, _, now = setup
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True)
    append(engine, "Correction: Project Zephyr launches Tuesday.")
    now[0] += timedelta(seconds=59)
    assert worker.run_once()["processed"] == 0
    now[0] += timedelta(seconds=1)
    reader.callback = lambda: now.__setitem__(0, now[0] + timedelta(seconds=40))
    assert worker.run_once()["refreshed"] == 1
    reader.callback = None
    append(engine, "Project Zephyr launch coordinator is Alice.")
    now[0] += timedelta(seconds=59)
    assert worker.run_once()["processed"] == 0
    now[0] += timedelta(seconds=1)
    assert worker.run_once()["refreshed"] == 1
    assert reader.calls == 3


def test_failed_early_attempt_keeps_durable_backoff_after_restart(setup):
    engine, service, reader, model, _, now = setup
    append(engine, "Correction: Project Zephyr launches Tuesday.")
    now[0] += timedelta(seconds=61)
    reader.fail = True
    assert MentalModelRefreshWorker(service, CTX, check_changes=True).run_once()["retry"] == 1
    reader.fail = False
    append(engine, "Another Project Zephyr correction arrived.")
    now[0] += timedelta(seconds=61)
    worker = MentalModelRefreshWorker(MentalModelService(engine, lambda: reader), CTX, check_changes=True)
    assert worker.run_once()["processed"] == 0
    assert reader.calls == 2
    now[0] = datetime.fromisoformat(service.get(CTX, model)["refresh_schedule"]["next_run_at"])
    assert worker.run_once()["refreshed"] == 1


@pytest.mark.parametrize("context", [replace(CTX, user_id="other"), replace(CTX, tenant_id="other"),
                                      replace(CTX, branch="other"), replace(CTX, role="operator"),
                                      replace(CTX, max_sensitivity=1)])
def test_other_scope_never_scans_or_refreshes_owner_models(setup, monkeypatch, context):
    engine, service, reader, _, _, now = setup
    append(engine, "Correction: Project Zephyr launches Tuesday.")
    now[0] += timedelta(seconds=61)
    monkeypatch.setattr(service, "_snapshot", lambda _: pytest.fail("unrelated owner/scope was scanned"))
    assert MentalModelRefreshWorker(service, context, check_changes=True).run_once()["processed"] == 0
    assert reader.calls == 1


@pytest.mark.parametrize("context,sensitivity", [(replace(CTX, user_id="other"), 0),
                                                (replace(CTX, tenant_id="other"), 0),
                                                (replace(CTX, branch="other"), 0), (CTX, 3)])
def test_inaccessible_source_changes_do_not_trigger_provider(setup, context, sensitivity):
    engine, service, reader, _, _, now = setup
    if context.branch != CTX.branch:
        engine.branch(context.branch, tenant_id=context.tenant_id)
    append(engine, "Private correction: Project Zephyr launches Tuesday.", context=context, sensitivity=sensitivity)
    now[0] += timedelta(seconds=61)
    service.provider_factory = lambda: pytest.fail("inaccessible source triggered provider")
    assert MentalModelRefreshWorker(service, CTX, check_changes=True).run_once()["processed"] == 0
    assert reader.calls == 1


def test_erased_source_refreshes_invalidated_model_without_returning_old_answer(setup):
    engine, service, _, model, cid, now = setup
    assert engine.forget(CTX.tenant_id, cid)["erased"]
    now[0] += timedelta(seconds=61)
    report = MentalModelRefreshWorker(service, CTX, check_changes=True).run_once()
    assert report["abstained"] == 1
    assert service.get(CTX, model)["answer"] == ""


@pytest.mark.parametrize("mutation", ["disable", "rename", "question", "delete"])
def test_model_change_after_detection_prevents_stale_claim(setup, monkeypatch, mutation):
    engine, service, reader, model, _, now = setup
    append(engine, "Correction: Project Zephyr launches Tuesday.")
    now[0] += timedelta(seconds=61)
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True)
    real_claim = worker._claim

    def claim(model_id, *, changed_version=None):
        assert changed_version is not None
        if mutation == "disable":
            service.schedule(CTX, model, enabled=False)
        elif mutation == "rename":
            service.update(CTX, model, name="Renamed")
        elif mutation == "question":
            service.update(CTX, model, question="Who coordinates Project Zephyr?")
        else:
            service.delete(CTX, model)
        return real_claim(model_id, changed_version=changed_version)

    monkeypatch.setattr(worker, "_claim", claim)
    assert worker.run_once()["processed"] == 0
    assert reader.calls == 1


def test_competing_early_claim_and_disabled_model_never_run(setup):
    engine, service, reader, model, _, now = setup
    append(engine, "Correction: Project Zephyr launches Tuesday.")
    now[0] += timedelta(seconds=61)
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True)
    version = service.get(CTX, model)["version"]
    assert worker._claim(model, changed_version=version)
    assert worker._claim(model, changed_version=version) is None
    assert worker.run_once()["processed"] == 0
    service.schedule(CTX, model, enabled=False)
    assert worker.run_once()["processed"] == 0
    assert reader.calls == 1


def test_snapshot_failure_skips_early_candidates_but_runs_ordinary_due_work(setup, monkeypatch):
    engine, service, reader, _, _, now = setup
    append(engine, "Correction: Project Zephyr launches Tuesday.")
    now[0] += timedelta(seconds=61)
    due = create(service, "Due")
    service.schedule(CTX, due, interval_seconds=3600)
    real_snapshot, calls = service._snapshot, []

    def snapshot(context):
        calls.append(context)
        if len(calls) == 1:
            raise RuntimeError("private snapshot diagnostic")
        return real_snapshot(context)

    monkeypatch.setattr(service, "_snapshot", snapshot)
    report = MentalModelRefreshWorker(service, CTX, check_changes=True).run_once()
    assert report["change_check_failed"] == 1 and report["refreshed"] == 1
    assert report["models"] == [{"model_id": due, "outcome": "refreshed"}]
    assert "private" not in str(report) and reader.calls == 2


def test_due_jobs_run_before_change_candidates_and_batch_does_not_starve(setup):
    engine, service, _, early, _, now = setup
    second = create(service, "Second early")
    service.schedule(CTX, second, interval_seconds=3600)
    assert MentalModelRefreshWorker(service, CTX).run_once()["refreshed"] == 1
    append(engine, "Correction: Project Zephyr launches Tuesday.")
    now[0] += timedelta(seconds=61)
    due = create(service, "Already due")
    service.schedule(CTX, due, interval_seconds=3600)
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True, max_batch=1)
    reports = [worker.run_once() for _ in range(3)]
    assert all(report["refreshed"] == 1 for report in reports)
    assert reports[0]["models"][0]["model_id"] == due
    assert {report["models"][0]["model_id"] for report in reports[1:]} == {early, second}


def test_early_provider_runs_without_engine_lock_and_source_drift_cannot_publish(setup):
    engine, service, reader, model, _, now = setup
    append(engine, "Correction: Project Zephyr launches Tuesday.")
    now[0] += timedelta(seconds=61)

    def mutate_from_other_thread():
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(append, engine, "Project Zephyr source changed during reading.").result(timeout=2)

    reader.callback = mutate_from_other_thread
    worker = MentalModelRefreshWorker(service, CTX, check_changes=True)
    assert worker.run_once()["retry"] == 1
    view = service.get(CTX, model)
    assert view["answer"] == "" and view["refresh_error"] == "source_changed_during_refresh"
    now[0] += timedelta(seconds=61)
    assert worker.run_once()["processed"] == 0


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_check_changes_requires_boolean(value):
    with pytest.raises(ValueError, match="check_changes must be a boolean"):
        MentalModelRefreshWorker(None, CTX, check_changes=value)
