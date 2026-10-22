"""A provider cannot publish a summary from sources changed during synthesis."""

from collections.abc import Callable
import json
from threading import Thread
from typing import Any

import pytest

from mnemosyne.consolidation import ConsolidationWorker
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


def _source(engine: Any, content: str = "The launch code is amber.") -> str:
    return engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="episode", content=content,
        access_policy={"tenant": "t"},
    ))


class _Summarizer:
    strategy = "custody-test"

    def __init__(self, callback: Callable[[], None] = lambda: None):
        self.callback = callback
        self.calls = 0

    def summarize(self, tenant_id: str, evidence: list[Evidence]) -> dict[str, Any]:
        self.calls += 1
        self.callback()
        return {"strategy": self.strategy, "summary": "The launch code is amber.",
                "source_cids": [item.cid for item in evidence]}


def _run(engine: Any, cids: list[str], summarizer: _Summarizer, **options: Any):
    return ConsolidationWorker(
        engine, gate_cases=[], summarizer=summarizer, consolidation_min_steps=0,
    ).run_queue_payload({
        "tenant_id": "t", "source_evidence_cids": cids, "passes": ["summarizer"], **options,
    })


def _summaries(engine: Any) -> list[dict[str, Any]]:
    return [row for row in engine.export_tenant("t")["evidence"]
            if row["source_type"] == "consolidation-summary" and not row.get("erased")]


def _details(result: Any) -> dict[str, Any]:
    return next(row["details"] for row in result.pass_results if row["name"] == "summarizer")


@pytest.mark.parametrize("mutation", ["delete", "privacy", "correction", "retag", "content"])
def test_source_change_during_summary_is_rejected(engine: Any, mutation: str) -> None:
    cid = _source(engine)
    if mutation == "correction":
        engine.upsert_assertion(Assertion(
            tenant_id="t", user_id="u", subject="launch", predicate="code", object="amber",
            source_evidence_cids=[cid], status="active", confidence=0.9,
        ))

    def change() -> None:
        if mutation == "delete":
            engine.forget("t", cid)
        elif mutation == "privacy":
            engine.backfill_evidence_privacy("t", cid, ["secret"])
        elif mutation == "correction":
            engine.correct("t", "u", "launch", "code", "violet", "The launch code is now violet.")
        elif isinstance(engine, LocalMemoryEngine):
            # Simulate an in-flight storage edit; these columns have no generic
            # public update API. Public privacy/correction APIs are covered above.
            row = engine.evidence[engine._evidence_key("t", "main", cid)]
            if mutation == "retag":
                row.capability_tags = ["data-only"]
            else:
                row.content = "The launch code is violet."
        else:
            conn = engine._connect("t")
            column = "capability_tags" if mutation == "retag" else "content"
            value = json.dumps(["data-only"]) if mutation == "retag" else "The launch code is violet."
            with conn:
                conn.execute(f"UPDATE evidence SET {column} = ? WHERE cid = ?", (value, cid))

    result = _run(engine, [cid], _Summarizer(change))

    assert _summaries(engine) == []
    assert _details(result)["materialized"] is False
    assert _details(result)["reason"] == "source_changed"
    assert not [row for row in engine.export_tenant("t")["relations"]
                if row["predicate"] == "summary-derived-gist"]


def test_unchanged_sources_materialize_and_replay_without_duplicate_proof(engine: Any) -> None:
    cid = _source(engine)
    first = _run(engine, [cid], _Summarizer())
    second = _run(engine, [cid], _Summarizer())

    assert _details(first)["materialized"] is True
    assert _details(second)["summary_cid"] == _details(first)["summary_cid"]
    assert len(_summaries(engine)) == 1
    relations = [row for row in engine.export_tenant("t")["relations"]
                 if row["predicate"] == "summary-derived-gist"]
    assert len(relations) == 1


def test_transitive_source_change_during_parent_summary_is_rejected(engine: Any) -> None:
    raw = _source(engine)
    child = _details(_run(engine, [raw], _Summarizer()))["summary_cid"]
    result = _run(engine, [child], _Summarizer(
        lambda: engine.backfill_evidence_privacy("t", raw, ["secret"]),
    ))

    assert [row["cid"] for row in _summaries(engine)] == [child]
    assert _details(result)["materialized"] is False
    assert _details(result)["reason"] == "source_changed"


@pytest.mark.parametrize("lineage", ["missing", "cycle"])
def test_invalid_lineage_is_rejected_before_calling_provider(engine: Any, lineage: str) -> None:
    first, second = _source(engine), _source(engine, "Another source.")
    engine.update_evidence_metadata("t", first, {"source_evidence_cids": ["missing" if lineage == "missing" else second]})
    if lineage == "cycle":
        engine.update_evidence_metadata("t", second, {"source_evidence_cids": [first]})
    summarizer = _Summarizer()

    result = _run(engine, [first], summarizer)

    assert _summaries(engine) == []
    assert summarizer.calls == 0
    assert _details(result)["reason"] == "source_changed"


@pytest.mark.parametrize("field", ["source_cids", "relation_source_cids", "source_summary_cids"])
def test_provider_cannot_add_uncaptured_sources(engine: Any, field: str) -> None:
    source, unrelated = _source(engine), _source(engine, "Unrelated evidence.")

    class ForgedSources(_Summarizer):
        def summarize(self, tenant_id: str, evidence: list[Evidence]) -> dict[str, Any]:
            return super().summarize(tenant_id, evidence) | {field: [unrelated]}

    result = _run(engine, [source], ForgedSources())

    assert _summaries(engine) == []
    assert _details(result)["reason"] == "source_changed"


def test_provider_input_mutation_cannot_weaken_written_summary(engine: Any) -> None:
    source = _source(engine)
    engine.backfill_evidence_privacy("t", source, ["secret"])

    class MutatingInputs(_Summarizer):
        def summarize(self, tenant_id: str, evidence: list[Evidence]) -> dict[str, Any]:
            result = super().summarize(tenant_id, evidence)
            evidence[0].sensitivity = 0
            evidence[0].access_policy = {"tenant": "t"}
            evidence.clear()
            return result

    result = _run(engine, [source], MutatingInputs())

    assert _details(result)["materialized"] is True
    assert _summaries(engine)[0]["sensitivity"] == 3
    assert _summaries(engine)[0]["access_policy"] == engine.get_evidence("t", source).access_policy


def test_provider_runs_without_holding_engine_lock(engine: Any) -> None:
    source = _source(engine)
    completed: list[bool] = []

    def concurrent_change() -> None:
        def tighten() -> None:
            engine.backfill_evidence_privacy("t", source, ["secret"])
            completed.append(True)

        thread = Thread(target=tighten)
        thread.start()
        thread.join(timeout=2)
        assert completed, "provider execution must not block another engine writer"

    result = _run(engine, [source], _Summarizer(concurrent_change))

    assert _details(result)["materialized"] is False
    assert _summaries(engine) == []


def test_read_telemetry_during_synthesis_does_not_invalidate_source(engine: Any) -> None:
    source = _source(engine)
    result = _run(engine, [source], _Summarizer(
        lambda: engine.retrieve("launch code amber", tenant_id="t"),
    ))

    assert _details(result)["materialized"] is True
    assert len(_summaries(engine)) == 1


def test_preexisting_child_with_weaker_ancestor_policy_is_not_disclosed(engine: Any) -> None:
    source = _source(engine)
    child = _details(_run(engine, [source], _Summarizer()))["summary_cid"]
    engine.backfill_evidence_privacy("t", source, ["secret"])
    summarizer = _Summarizer()

    result = _run(engine, [child], summarizer)

    assert summarizer.calls == 0
    assert _details(result)["materialized"] is False
    assert [row["cid"] for row in _summaries(engine)] == [child]


def test_hierarchy_cannot_cite_unsupplied_sibling_cluster(engine: Any) -> None:
    sources = [_source(engine, f"Source number {index}.") for index in range(5)]

    class SiblingCitation(_Summarizer):
        def summarize(self, tenant_id: str, evidence: list[Evidence]) -> dict[str, Any]:
            result = super().summarize(tenant_id, evidence)
            unsupplied = set(sources) - {item.cid for item in evidence}
            assert unsupplied
            return result | {"source_cids": [sorted(unsupplied)[0]]}

    result = _run(engine, sources, SiblingCitation(), raptor_cluster_size=2, raptor_max_levels=2)

    assert _details(result)["materialized"] is False
    assert _summaries(engine) == []
