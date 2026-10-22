"""Provider proposal replay is bound to every live input source."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from mnemosyne.consolidation import ProviderProposalLedger
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite"])
def engine(request: Any, tmp_path: Any):
    value = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "store")
    yield value
    close = getattr(value, "close", None)
    if close:
        close()


TEXT = "The launch destination is velvet canyon."


def _source(engine: Any, content: str = TEXT) -> str:
    return engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="episode", content=content,
        access_policy={"tenant": "t"},
    ))


def _request(cids: list[str]) -> dict[str, Any]:
    return {"evidence": [{"cid": cid, "sensitivity": 0, "access_policy": {"tenant": "t"}}
                         for cid in cids]}


def _call(engine: Any, request: dict[str, Any], run: Callable[[], dict[str, Any]]):
    return ProviderProposalLedger(engine).load_or_run(
        tenant_id="t", branch="main", role="evidence_summarizer", strategy="custody-test",
        request=request, run=run,
    )


def _records(engine: Any) -> list[dict[str, Any]]:
    return [row for row in engine.export_tenant("t")["evidence"]
            if row["source_type"] == "provider-proposal" and not row.get("erased")]


def _mutation(engine: Any, source: str, mutation: str) -> None:
    if mutation == "delete":
        engine.forget("t", source)
    elif mutation == "privacy":
        engine.backfill_evidence_privacy("t", source, ["secret"])
    else:
        engine.correct("t", "u", "launch", "destination", "coral bay", "The destination is now coral bay.")


@pytest.mark.parametrize("mutation", ["delete", "privacy", "correction"])
@pytest.mark.parametrize("cached", [False, True])
def test_stale_response_is_neither_returned_nor_recorded(engine: Any, mutation: str, cached: bool) -> None:
    source = _source(engine)
    engine.upsert_assertion(Assertion(
        tenant_id="t", user_id="u", subject="launch", predicate="destination", object="velvet canyon",
        source_evidence_cids=[source], status="active", confidence=0.9,
    ))
    request = _request([source])
    if cached:
        _call(engine, request, lambda: {"summary": TEXT})
        _mutation(engine, source, mutation)
        before = _records(engine)

        def run() -> dict[str, Any]:
            pytest.fail("stale replay must not call the provider")
    else:
        before = []

        def run() -> dict[str, Any]:
            _mutation(engine, source, mutation)
            return {"summary": TEXT}

    with pytest.raises(ValueError, match="source"):
        _call(engine, request, run)

    assert _records(engine) == before


def test_live_source_replay_and_read_telemetry_preserve_one_record(engine: Any) -> None:
    source = _source(engine)
    request = _request([source])
    first = _call(engine, request, lambda: {"summary": TEXT})
    engine.retrieve("velvet canyon", "t")
    second = _call(engine, request, lambda: pytest.fail("verified replay should be reused"))

    assert second["summary"] == TEXT
    assert second["_proposal_record"]["replayed"] is True
    assert first["_proposal_record"]["cid"] == second["_proposal_record"]["cid"]
    assert len(_records(engine)) == 1
    assert _records(engine)[0]["metadata"]["source_evidence_cids"] == [source]


def test_later_source_erasure_removes_single_source_proposal(engine: Any) -> None:
    source = _source(engine)
    result = _call(engine, _request([source]), lambda: {"summary": TEXT})
    proposal = result["_proposal_record"]["cid"]

    engine.forget("t", source)

    assert engine.get_evidence("t", proposal) is None
    assert _records(engine) == []


def test_input_free_proposal_retains_replay_behavior(engine: Any) -> None:
    first = _call(engine, {}, lambda: {"summary": "A source-free diagnostic."})
    second = _call(engine, {}, lambda: pytest.fail("input-free replay should be reused"))

    assert second["_proposal_record"]["replayed"] is True
    assert second["summary"] == first["summary"]


def test_legacy_cache_without_source_state_is_not_replayed(engine: Any) -> None:
    source = _source(engine)
    request = _request([source])
    result = _call(engine, request, lambda: {"summary": TEXT})
    row = _records(engine)[0]
    legacy = dict(row["metadata"]["provider_proposal"])
    legacy.pop("input_state_sha256")
    engine.update_evidence_metadata("t", result["_proposal_record"]["cid"], {"provider_proposal": legacy})

    with pytest.raises(ValueError, match="cached source"):
        _call(engine, request, lambda: pytest.fail("unverified legacy cache must not replay"))


def test_provider_cannot_downgrade_saved_request_controls(engine: Any) -> None:
    source = _source(engine)
    request = _request([source])
    request["evidence"][0]["sensitivity"] = 3

    def run() -> dict[str, Any]:
        request["evidence"][0]["sensitivity"] = 0
        return {"summary": TEXT}

    result = _call(engine, request, run)

    assert result["summary"].startswith("[sensitive-provider-output:")
    assert _records(engine)[0]["sensitivity"] == 3
    assert TEXT not in _records(engine)[0]["content"]


def test_stale_public_request_is_rejected_before_provider_disclosure(engine: Any) -> None:
    source = _source(engine)
    request = _request([source])
    engine.backfill_evidence_privacy("t", source, ["secret"])

    with pytest.raises(ValueError, match="stale source controls"):
        _call(engine, request, lambda: pytest.fail("private source must not be sent under public controls"))

    assert _records(engine) == []


def test_incomplete_source_custody_is_rejected_before_generation(engine: Any) -> None:
    source = _source(engine)
    engine.update_evidence_metadata("t", source, {"derived_source_custody": "incomplete"})

    with pytest.raises(ValueError, match="source changed or unavailable"):
        _call(engine, _request([source]), lambda: pytest.fail("incomplete source must not be reused"))

    assert _records(engine) == []


def test_partial_source_erasure_rejects_persisted_cache_replay(engine: Any) -> None:
    first_source = _source(engine)
    second_source = _source(engine, "The launch occurs on Friday.")
    request = _request([first_source, second_source])
    first = _call(engine, request, lambda: {"summary": TEXT})
    engine.forget("t", first_source)

    with pytest.raises(ValueError, match="source"):
        _call(engine, request, lambda: pytest.fail("partially erased source set must not replay"))

    proposal = engine.get_evidence("t", first["_proposal_record"]["cid"])
    assert proposal is not None
    assert proposal.metadata["derived_source_custody"] == "incomplete"


@pytest.mark.parametrize("change", ["privacy", "quarantine", "incomplete", "retired", "malformed"])
def test_cached_record_own_controls_are_rechecked(engine: Any, change: str) -> None:
    source = _source(engine)
    request = _request([source])
    result = _call(engine, request, lambda: {"summary": TEXT})
    cid = result["_proposal_record"]["cid"]
    if change == "privacy":
        engine.backfill_evidence_privacy("t", cid, ["secret"])
    else:
        patch = {
            "quarantine": {"quarantine_reason": "review required"},
            "incomplete": {"derived_source_custody": "incomplete"},
            "retired": {"summary": {"status": "retired", "source_evidence_cids": [source]}},
            "malformed": {"source_evidence_cids": "not-a-list"},
        }[change]
        engine.update_evidence_metadata("t", cid, patch)

    with pytest.raises(ValueError, match="cached"):
        _call(engine, request, lambda: pytest.fail("unreadable cache must not be silently regenerated"))


def test_stricter_request_controls_allow_valid_cache_replay(engine: Any) -> None:
    source = _source(engine)
    request = _request([source])
    request["evidence"][0].update(sensitivity=3, access_policy={"tenant": "t", "allow_principals": ["u"]})
    first = _call(engine, request, lambda: {"summary": TEXT})
    second = _call(engine, request, lambda: pytest.fail("valid stricter cache should replay"))

    assert second["_proposal_record"]["replayed"] is True
    assert second["summary"] == first["summary"]
    assert second["summary"].startswith("[sensitive-provider-output:")


def test_cache_expiry_is_rechecked_without_source_mutation(engine: Any, monkeypatch: Any) -> None:
    source = _source(engine)
    request = _request([source])
    request["evidence"][0]["access_policy"]["expires_at"] = "2040-01-01T00:00:00Z"
    _call(engine, request, lambda: {"summary": TEXT})
    monkeypatch.setattr("mnemosyne.consolidation.utc_now", lambda: datetime(2041, 1, 1, tzinfo=UTC))

    with pytest.raises(ValueError, match="cached record controls"):
        _call(engine, request, lambda: pytest.fail("expired cache must not replay"))
