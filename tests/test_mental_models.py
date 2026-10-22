"""Saved-answer lifecycle: reuse, drift, isolation, and race regressions."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

from mnemosyne.answering import AnswerReadContext
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mental_models import MentalModelService
from mnemosyne.models import Evidence
from mnemosyne.providers.extractive_decomposer import ExtractiveQueryDecomposer
from mnemosyne.sqlite_engine import SqliteEngine


CTX = AnswerReadContext(tenant_id="t", user_id="u", role="agent", max_sensitivity=0)


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    value = (LocalMemoryEngine(tmp_path / "store.json") if request.param == "local"
             else SqliteEngine(tmp_path / "store"))
    yield value
    value.close()


def source(engine, text="Project Zephyr launches Friday.", **kwargs):
    return engine.append_evidence(Evidence(
        tenant_id=kwargs.pop("tenant_id", "t"), user_id="u", actor="user", source_type="chat",
        content=text, access_policy=kwargs.pop("access_policy", {"tenant": "t", "allow_principals": ["u"]}),
        **kwargs,
    ))


class Provider:
    def __init__(self, callback=None, response=None):
        self.calls = 0
        self.callback = callback
        self.response = response
        self.disclosure = {"query_decomposer": {"model": "fixture"}, "grounded_reader": {"model": "fixture"}}

    def decompose(self, payload):
        return ExtractiveQueryDecomposer().decompose(payload)

    def read(self, payload):
        self.calls += 1
        if self.callback:
            self.callback()
        if isinstance(self.response, Exception):
            raise self.response
        if self.response is not None:
            return self.response
        for day in ("Tuesday", "Friday"):
            for row in payload["evidence"]:
                if day in row["content"]:
                    return {"claims": [{"spans": [{"cid": row["cid"], "quote": day}]}], "unresolved": False}
        return {"claims": [], "unresolved": True}


def create(service):
    return service.create(CTX, "Zephyr launch", "When does Project Zephyr launch?")["model_id"]


def ready(engine):
    cid = source(engine)
    provider = Provider()
    service = MentalModelService(engine, lambda: provider)
    mid = create(service)
    result = service.refresh(CTX, mid)
    assert result["status"] == "ready", result
    assert result["answer"] == "Friday"
    return service, provider, mid, cid


def test_create_and_clean_reads_never_call_provider_or_retrieval(engine, monkeypatch):
    service, provider, mid, _ = ready(engine)
    assert provider.calls == 1
    service.provider_factory = lambda: pytest.fail("clean read loaded provider")
    monkeypatch.setattr(engine, "retrieve", lambda *a, **kw: pytest.fail("clean read retrieved"))
    assert service.get(CTX, mid)["answer"] == "Friday"
    assert service.get(CTX, mid, refresh_if_stale=True)["answer"] == "Friday"
    assert service.refresh(CTX, mid)["answer"] == "Friday"
    assert service.list(CTX)[0]["status"] == "ready"
    assert service.history(CTX, mid)[0]["event"] == "refresh"


def test_added_evidence_marks_get_and_list_stale_then_refreshes(engine):
    service, provider, mid, _ = ready(engine)
    source(engine, "Correction: Project Zephyr launches Tuesday.")
    for view in (service.get(CTX, mid), service.list(CTX)[0]):
        assert view["status"] == "stale"
        assert view["answer"] == "" and view["claims"] == [] and view["reader"] == {}
    assert provider.calls == 1
    assert service.get(CTX, mid, refresh_if_stale=True)["answer"] == "Tuesday"
    assert provider.calls == 2


def test_read_telemetry_and_other_tenants_do_not_invalidate(engine):
    service, _, mid, _ = ready(engine)
    engine.retrieve("Project Zephyr", "t")
    assert service.get(CTX, mid)["status"] == "ready"
    source(engine, "Unrelated", tenant_id="elsewhere", access_policy={"tenant": "elsewhere"})
    assert service.get(CTX, mid)["status"] == "ready"


def test_private_new_sources_do_not_change_readable_corpus(engine):
    service, _, mid, _ = ready(engine)
    source(engine, "Secret correction", sensitivity=3)
    assert service.get(CTX, mid)["status"] == "ready"


def test_privacy_change_hides_answer_in_get_list_and_history(engine):
    service, _, mid, cid = ready(engine)
    engine.backfill_evidence_privacy("t", cid, ["secret"])
    assert service.get(CTX, mid)["status"] == "stale"
    assert service.list(CTX)[0]["answer"] == ""
    assert "Friday" not in str(service.history(CTX, mid))


def test_forget_erases_stored_answer_not_only_public_view(engine):
    service, _, mid, cid = ready(engine)
    engine.forget("t", cid)
    assert service.get(CTX, mid)["answer"] == ""
    assert "Friday" not in str(engine.get_mental_model_record("t", mid))


def test_source_expiry_alone_invalidates(engine, monkeypatch):
    import mnemosyne.access_policy as access_policy

    now = datetime.now(UTC)
    source(engine, access_policy={"tenant": "t", "expires_at": (now + timedelta(hours=1)).isoformat()})
    service = MentalModelService(engine, Provider)
    mid = create(service)
    assert service.refresh(CTX, mid)["answer"] == "Friday"

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now + timedelta(hours=2)

    monkeypatch.setattr(access_policy, "datetime", Clock)
    assert service.get(CTX, mid)["status"] == "stale"
    assert service.list(CTX)[0]["answer"] == ""


@pytest.mark.parametrize("response", [RuntimeError("private failure"), {"claims": [], "unresolved": True},
                                     {"claims": [{"spans": [{"cid": "forged", "quote": "Tuesday"}]}], "unresolved": False}])
def test_failed_forced_refresh_preserves_still_valid_good_answer(engine, response):
    service, _, mid, _ = ready(engine)
    service.provider_factory = lambda: Provider(response=response)
    result = service.refresh(CTX, mid, force=True)
    assert result["status"] == "ready" and result["answer"] == "Friday"
    assert result["refresh_error"]
    assert "private failure" not in str(result)


def test_failed_refresh_cannot_preserve_stale_answer(engine):
    service, _, mid, _ = ready(engine)
    source(engine, "Project Zephyr is cancelled.")
    service.provider_factory = lambda: Provider(response=RuntimeError("private failure"))
    assert service.refresh(CTX, mid)["answer"] == ""
    assert "Friday" not in str(engine.get_mental_model_record("t", mid)["answer"])


@pytest.mark.parametrize("change", ["source", "definition", "delete"])
def test_inflight_refresh_cannot_publish_after_mutation(engine, change):
    service, _, mid, cid = ready(engine)

    def callback():
        if change == "source":
            engine.backfill_evidence_privacy("t", cid, ["secret"])
        elif change == "definition":
            service.update(CTX, mid, question="What is Project Zephyr?")
        else:
            service.delete(CTX, mid)

    service.provider_factory = lambda: Provider(callback=callback)
    if change == "source":
        result = service.refresh(CTX, mid, force=True)
        assert result["status"] == "stale" and result["answer"] == ""
    else:
        with pytest.raises((ValueError, LookupError)):
            service.refresh(CTX, mid, force=True)
        if change == "delete":
            assert engine.get_mental_model_record("t", mid) is None
        else:
            assert service.get(CTX, mid)["answer"] == ""


def test_scope_owner_and_tenant_isolation(engine):
    service, _, mid, _ = ready(engine)
    for context in (replace(CTX, tenant_id="other"), replace(CTX, user_id="other"), replace(CTX, branch="other")):
        assert service.list(context) == []
        for method in (service.get, service.history, service.refresh, service.delete):
            with pytest.raises(LookupError):
                method(context, mid)
    with pytest.raises(PermissionError):
        service.get(replace(CTX, max_sensitivity=3), mid)
    with pytest.raises(ValueError, match="break-glass"):
        service.get(replace(CTX, break_glass=True), mid)


def test_definition_update_and_stale_client_version(engine):
    service, _, mid, _ = ready(engine)
    version = service.get(CTX, mid)["version"]
    updated = service.update(CTX, mid, question="What is Project Zephyr?", expected_version=version)
    assert updated["status"] == "pending" and updated["answer"] == ""
    with pytest.raises(ValueError, match="version"):
        service.update(CTX, mid, name="stale edit", expected_version=version)
    with pytest.raises(ValueError, match="version"):
        service.delete(CTX, mid, expected_version=version)


def test_model_outputs_and_history_are_detached_and_not_evidence(engine):
    before = copy.deepcopy(engine.export_tenant("t")["evidence"])
    service = MentalModelService(engine, Provider)
    mid = create(service)
    assert engine.export_tenant("t")["evidence"] == before
    assert not engine.retrieve("Zephyr launch", "t").hits
    source(engine)
    result = service.refresh(CTX, mid)
    result["claims"][0]["text"] = "corrupt"
    history = service.history(CTX, mid)
    history[0]["status"] = "corrupt"
    assert service.get(CTX, mid)["answer"] == "Friday"
    assert service.history(CTX, mid)[0]["status"] == "ready"
    assert "mental_models" not in engine.export_tenant_filtered("t", CTX.to_filter())


@pytest.mark.parametrize("kind", ["local", "sqlite"])
def test_ready_model_survives_restart_without_provider(kind, tmp_path):
    path = tmp_path / ("data.json" if kind == "local" else "data")
    factory = LocalMemoryEngine if kind == "local" else SqliteEngine
    engine = factory(path)
    _, _, mid, _ = ready(engine)
    engine.close()
    reopened = factory(path)
    try:
        service = MentalModelService(reopened, lambda: pytest.fail("restart read loaded provider"))
        assert service.get(CTX, mid)["answer"] == "Friday"
    finally:
        reopened.close()


def test_cached_claim_tampering_is_withheld(engine):
    service, _, mid, _ = ready(engine)
    row = engine.get_mental_model_record("t", mid)
    row["answer"]["answer"] = "Invented answer"
    engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
    assert service.get(CTX, mid)["status"] == "stale"
    assert service.get(CTX, mid)["answer"] == ""


@pytest.mark.parametrize("sources", [[], ["private-or-nonexistent-source"]])
def test_unverified_record_source_ids_are_withheld(engine, sources):
    service, _, mid, _ = ready(engine)
    row = engine.get_mental_model_record("t", mid)
    row["source_evidence_cids"] = sources
    engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
    view = service.get(CTX, mid)
    assert view["status"] == "stale"
    assert view["source_evidence_cids"] == []


def test_imported_cache_cannot_cite_evidence_after_historical_cutoff(engine):
    from mnemosyne.mental_models import _scope

    service, _, mid, _ = ready(engine)
    historical = replace(CTX, as_of="2020-01-01T00:00:00+00:00")
    row = engine.get_mental_model_record("t", mid)
    row["scope"] = _scope(historical)
    row["corpus_fingerprint"] = service._snapshot(historical)[0]
    engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
    assert service.get(historical, mid)["status"] == "stale"
    assert service.get(historical, mid)["answer"] == ""


@pytest.mark.parametrize("tamper", ["extra_claim", "bad_operation", "old_history"])
def test_malformed_imports_cannot_extend_public_claims_or_history(engine, tamper):
    service, _, mid, cid = ready(engine)
    row = engine.get_mental_model_record("t", mid)
    if tamper == "extra_claim":
        row["answer"]["claims"][0]["unsupported"] = "secret stale value"
    elif tamper == "bad_operation":
        row["answer"]["claims"][0]["derivation"]["operation"] = "invented"
    else:
        row["revisions"][0]["old_answer"] = "secret stale value"
    engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
    assert "secret stale value" not in str(service.get(CTX, mid))
    if tamper != "old_history":
        assert service.get(CTX, mid)["answer"] == ""
    engine.backfill_evidence_privacy("t", cid, ["secret"])
    assert "secret stale value" not in str(service.history(CTX, mid))


def test_day_boundary_invalidates_relative_question_without_writes(engine, monkeypatch):
    import mnemosyne.mental_models as module

    current = datetime(2026, 10, 22, 12, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current

    monkeypatch.setattr(module, "datetime", Clock)
    source(engine)
    service = MentalModelService(engine, Provider)
    mid = service.create(CTX, "Today's answer", "What is the Project Zephyr launch day today?")["model_id"]
    result = service.refresh(CTX, mid)
    assert result["status"] == "ready"
    current += timedelta(days=1)
    assert service.get(CTX, mid)["status"] == "stale"


def test_continuously_moving_question_requires_fixed_clock(engine):
    service = MentalModelService(engine, Provider)
    with pytest.raises(ValueError, match="explicit as_of"):
        service.create(CTX, "Rolling", "What did I say about Zephyr this week?")
    scoped = replace(CTX, as_of="2026-10-22T12:00:00+00:00")
    assert service.create(scoped, "Fixed", "What did I say about Zephyr this week?")["status"] == "pending"


def test_malformed_history_and_error_metadata_are_ignored(engine):
    service, _, mid, _ = ready(engine)
    row = engine.get_mental_model_record("t", mid)
    valid = copy.deepcopy(row["revisions"][0])
    row["revisions"].extend([{**valid, "status": []}, {**valid, "event": {}}])
    row["refresh_error"] = ["untrusted error"]
    engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
    assert service.history(CTX, mid) == [valid]
    assert service.get(CTX, mid)["refresh_error"] is None


def test_two_concurrent_refreshes_cannot_overwrite_new_revision(engine):
    service, _, mid, _ = ready(engine)
    barrier = Barrier(2)
    service.provider_factory = lambda: Provider(callback=lambda: barrier.wait(timeout=5))

    def refresh():
        try:
            return service.refresh(CTX, mid, force=True)
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: refresh(), range(2)))
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert sum(outcome == "mental model changed during refresh" for outcome in outcomes) == 1
    assert service.get(CTX, mid)["version"] == 3


def test_clock_rollover_during_save_withholds_old_day_answer(engine, monkeypatch):
    import mnemosyne.mental_models as module

    current = datetime(2026, 10, 22, 12, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current

    monkeypatch.setattr(module, "datetime", Clock)
    source(engine)
    service = MentalModelService(engine, Provider)
    mid = service.create(CTX, "Today", "What is the Project Zephyr launch day today?")["model_id"]
    original = engine.save_mental_model_record

    def save(*args, **kwargs):
        nonlocal current
        result = original(*args, **kwargs)
        current += timedelta(days=1)
        return result

    monkeypatch.setattr(engine, "save_mental_model_record", save)
    result = service.refresh(CTX, mid)
    assert result["status"] == "stale"
    assert result["answer"] == ""
