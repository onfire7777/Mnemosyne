"""Derived prose requires every live source, before ranking or provider access."""

from typing import Any
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, Hit
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite"])
def engine(request: Any, tmp_path: Any, monkeypatch: Any):
    monkeypatch.setenv("MNEMOSYNE_RETRIEVAL_RESULT_CACHE_SIZE", "16")
    value = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "store")
    yield value
    close = getattr(value, "close", None)
    if close:
        close()


CONTEXT = {"tenant_id": "t", "user_id": "outsider", "role": "reader", "max_trust_tier": 5}


def _source(engine: Any, text: str = "The launch code is amber.", **kwargs: Any) -> str:
    return engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="episode", content=text, **kwargs,
    ))


def _derived(engine: Any, sources: list[str], *, proposal: bool = False, **kwargs: Any) -> str:
    metadata = ({"provider_proposal": {"input_cids": sources}} if proposal else
                {"summary": {"source_evidence_cids": sources, "raptor_level": 1}})
    content = kwargs.pop("content", "The derived launch code is amber. " + hashlib.sha256(repr(sources).encode()).hexdigest()[:8])
    return engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="assistant",
        source_type="provider-proposal" if proposal else "consolidation-summary",
        content=content, metadata=metadata, **kwargs,
    ))


def _read_ids(engine: Any, route: str) -> set[str]:
    if route == "export":
        return {row["cid"] for row in engine.export_tenant_filtered("t", CONTEXT)["evidence"]}
    if route == "candidates":
        if isinstance(engine, LocalMemoryEngine):
            return {hit.id for hit in engine._candidate_hits(CONTEXT)}
        oracle = engine._scan_oracle(CONTEXT, with_blobs=False)
        return {hit.id for hit in oracle._candidate_hits(CONTEXT)}
    if route in {"lexical", "vector"}:
        return {hit.id for hit in getattr(engine, route + "_search")("launch code amber", 50, CONTEXT)}
    result = engine.retrieve("launch code amber", tenant_id="t", filt=CONTEXT, record_access=False)
    return {hit.id for hit in result.hits}


@pytest.mark.parametrize("proposal", [False, True])
@pytest.mark.parametrize("route", ["export", "candidates", "lexical", "vector", "retrieve"])
def test_warm_read_cannot_disclose_after_source_privacy_tightens(engine: Any, route: str, proposal: bool):
    source = _source(engine)
    derived = _derived(engine, [source], proposal=proposal)
    assert derived in _read_ids(engine, route)
    engine.backfill_evidence_privacy("t", source, ["secret"])
    assert derived not in _read_ids(engine, route)


@pytest.mark.parametrize("proposal", [False, True])
def test_every_source_required_even_after_one_is_erased(engine: Any, proposal: bool):
    first = _source(engine)
    second = _source(engine, "Additional source.")
    derived = _derived(engine, [first, second], proposal=proposal)
    assert derived in _read_ids(engine, "retrieve")
    engine.forget("t", first)
    assert derived not in _read_ids(engine, "retrieve")
    assert derived not in _read_ids(engine, "export")


def test_nested_summary_denies_restricted_grandparent(engine: Any):
    source = _source(engine)
    child = _derived(engine, [source])
    parent = _derived(engine, [child])
    assert parent != child
    assert parent in _read_ids(engine, "lexical")
    engine.backfill_evidence_privacy("t", source, ["secret"])
    assert not {child, parent} & _read_ids(engine, "lexical")


def test_direct_authorized_read_is_detached_and_checks_lineage(engine: Any):
    source = _source(engine)
    derived = _derived(engine, [source])
    row = engine.get_evidence_for_read("t", derived, access_context=CONTEXT)
    assert row is not None
    row.content = "mutated"
    row.metadata["summary"]["source_evidence_cids"].clear()
    assert engine.get_evidence("t", derived).content != "mutated"
    engine.backfill_evidence_privacy("t", source, ["secret"])
    assert engine.get_evidence_for_read("t", derived, access_context=CONTEXT) is None
    assert engine.get_evidence_for_read("other", derived, access_context=CONTEXT) is None


@pytest.mark.parametrize("sources", [[], ["missing"], [42], "not-a-list"])
def test_summary_missing_or_malformed_lineage_is_withheld(engine: Any, sources: Any):
    derived = _derived(engine, sources)
    assert derived not in _read_ids(engine, "lexical")


def test_input_free_proposal_remains_readable(engine: Any):
    derived = _derived(engine, [], proposal=True)
    assert derived in _read_ids(engine, "lexical")


def test_shared_ancestor_dag_is_not_a_cycle(engine: Any):
    source = _source(engine)
    left = _derived(engine, [source])
    right = _derived(engine, [source], content="A second derived launch code is amber.")
    parent = _derived(engine, [left, right])
    assert parent in _read_ids(engine, "lexical")


def test_cycle_is_withheld(engine: Any):
    source = _source(engine)
    child = _derived(engine, [source])
    parent = _derived(engine, [child])
    engine.update_evidence_metadata("t", child, {"summary": {"source_evidence_cids": [parent]}})
    assert not {child, parent} & _read_ids(engine, "lexical")


def test_partial_source_redaction_withholds_entire_summary(engine: Any):
    source = _source(engine, access_policy={"redact_fields": ["code"], "min_role_for_raw": "operator"})
    derived = _derived(engine, [source])
    assert derived not in _read_ids(engine, "lexical")


def test_legacy_top_level_summary_is_withheld_after_partial_forget(engine: Any):
    first, second = _source(engine), _source(engine, "Other origin.")
    derived = engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="system", source_type="consolidation-summary",
        content="The launch code is amber.", metadata={"source_evidence_cids": [first, second]},
    ))
    assert derived in _read_ids(engine, "retrieve")
    engine.forget("t", first)
    assert engine.get_evidence("t", derived).metadata["derived_source_custody"] == "incomplete"
    assert derived not in _read_ids(engine, "retrieve")


@pytest.mark.parametrize("proposal", [False, True])
def test_sequential_source_deletions_remove_derived_record(engine: Any, proposal: bool):
    first, second = _source(engine), _source(engine, "Other origin.")
    derived = _derived(engine, [first, second], proposal=proposal)
    engine.forget("t", first)
    assert engine.get_evidence_for_read("t", derived, access_context=CONTEXT) is None
    engine.forget("t", second)
    assert engine.get_evidence("t", derived) is None


class _Adapter:
    name = "test-lexical"

    def __init__(self, cid: str):
        self.cid = cid

    def search(self, *args: Any, **kwargs: Any):
        return [Hit(id=self.cid, kind="evidence", tenant_id="t", branch="main",
                    text="OLD PRIVATE TEXT", score=0.71, channel="external-lexical",
                    provenance=["fabricated"], trust_tier=0, sensitivity=0,
                    metadata={"confidence": 1.0, "reality_class": "grounded"})]


def test_adapter_cannot_resurrect_deleted_or_fabricated_evidence(engine: Any):
    source = _source(engine)
    derived = _derived(engine, [source])
    engine.adapters = replace(engine.adapters, lexical_retriever=_Adapter(derived))
    assert engine.lexical_search("launch", 5, CONTEXT)[0].text == engine.get_evidence("t", derived).content
    engine.forget("t", source)
    assert engine.lexical_search("launch", 5, CONTEXT) == []
    engine.adapters = replace(engine.adapters, lexical_retriever=_Adapter("unknown"))
    assert engine.lexical_search("launch", 5, CONTEXT) == []


def test_adapter_rank_uses_current_content_and_controls(engine: Any):
    source = _source(engine, "Current authorized text.", trust_tier=2)
    engine.adapters = replace(engine.adapters, lexical_retriever=_Adapter(source))
    hit, = engine.lexical_search("launch", 5, CONTEXT)
    assert hit.text == "Current authorized text."
    assert hit.provenance == [source] and hit.trust_tier == 2
    assert hit.score == 0.71 and hit.channel == "external-lexical"
    assert "confidence" not in hit.metadata
    engine.backfill_evidence_privacy("t", source, ["secret"])
    assert engine.lexical_search("launch", 5, CONTEXT) == []


def test_adapter_cannot_supply_unredacted_text(engine: Any):
    source = _source(engine, access_policy={"redact_fields": ["code"], "min_role_for_raw": "operator"})
    engine.adapters = replace(engine.adapters, lexical_retriever=_Adapter(source))
    assert engine.lexical_search("launch", 5, CONTEXT) == []


def test_rejected_summary_never_reaches_embedding_provider(engine: Any):
    from mnemosyne.text import hashing_embedding

    class Recorder:
        name = "recording-provider"
        dims = 256
        texts: list[str] = []

        def embed(self, text: str):
            self.texts.append(text)
            return hashing_embedding(text)

    source = _source(engine)
    derived = _derived(engine, [source])
    text = engine.get_evidence("t", derived).content
    engine.backfill_evidence_privacy("t", source, ["secret"])
    provider = Recorder()
    engine.adapters = replace(engine.adapters, embedding=provider)
    assert derived not in {hit.id for hit in engine.vector_search("launch", 5, CONTEXT)}
    assert text not in provider.texts


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_incomplete_marker_survives_replay_and_restart(tmp_path: Any, backend: str):
    location = tmp_path / ("store.json" if backend == "local" else "store")
    factory = LocalMemoryEngine if backend == "local" else SqliteEngine
    engine = factory(location)
    first, second = _source(engine), _source(engine, "Other origin.")
    derived = _derived(engine, [first, second])
    content = engine.get_evidence("t", derived).content
    engine.forget("t", first)
    assert _derived(engine, [second], content=content) == derived  # content-CID replay cannot replace custody
    engine.close()
    reopened = factory(location)
    try:
        assert reopened.get_evidence("t", derived).metadata["derived_source_custody"] == "incomplete"
        assert reopened.get_evidence_for_read("t", derived, access_context=CONTEXT) is None
    finally:
        reopened.close()


def test_expiring_ancestor_invalidates_warm_result_cache(engine: Any, monkeypatch: Any):
    import mnemosyne.access_policy as access_policy
    import mnemosyne.engine as engine_module

    current = datetime.now(UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None):
            return current if tz is not None else current.replace(tzinfo=None)

    monkeypatch.setattr(access_policy, "datetime", Clock)
    monkeypatch.setattr(engine_module, "utc_now", lambda: current)
    source = _source(engine, access_policy={"expires_at": (current + timedelta(minutes=1)).isoformat()})
    derived = _derived(engine, [source])
    assert derived in _read_ids(engine, "retrieve")
    assert derived in _read_ids(engine, "retrieve")
    current += timedelta(minutes=2)
    assert derived not in _read_ids(engine, "retrieve")
