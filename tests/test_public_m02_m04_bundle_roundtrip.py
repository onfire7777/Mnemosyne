"""Unit-generated oracle traces exercise custody, never benchmark performance."""

from copy import deepcopy

import pytest

from eval.public import wmbs_m02 as m02, wmbs_m04 as m04
from eval.public.bundle import BundleError, verify_bundle, write_bundle
from eval.public.runner import load_registry
from eval.public.scoring import score_profile


def _case(module):
    if module == "M02":
        fixture = m02.load_fixture()
        traces = [
            {
                "case_id": q["question_id"],
                "question_id": q["question_id"],
                "ranked_hits": [
                    {"rank": i, "stable_item_id": value}
                    for i, value in enumerate(q["gold_doc_ids"], 1)
                ],
                "answer": q["answers"][0] if q["answers"] else None,
                "abstained": not bool(q["answers"]),
            }
            for q in fixture["questions"]
        ]
        suite = "wmbs-m02-retrieval-development"
    else:
        fixture = m04.load_fixture()
        traces = []
        for case in fixture["cases"]:
            gold = case["gold"]
            for permutation in m04.PERMUTATIONS:
                traces.append(
                    {
                        "case_id": case["case_id"],
                        "permutation": permutation,
                        "current": {
                            "objects": gold["current_objects"],
                            "as_of": gold["current_as_of"],
                        },
                        "historical": {
                            "objects": gold["historical_objects"],
                            "as_of": gold["historical_as_of"],
                        },
                        "answer": {
                            "answer_text": None
                            if gold["unresolved"]
                            else gold["current_objects"][0],
                            "abstained": gold["unresolved"],
                            "evidence_handles": [],
                            "action_handles": [],
                            "adapter_metadata": {"mode": "normal"},
                        },
                        "monotonic_violation": False,
                    }
                )
                for source, objects in gold["ablation_objects"].items():
                    traces.append(
                        {
                            "case_id": case["case_id"],
                            "permutation": permutation,
                            "source_id": source,
                            "current": {
                                "objects": objects,
                                "as_of": gold["current_as_of"],
                            },
                        }
                    )
        suite = "wmbs-m04-development"
    metadata = {**load_registry()[suite], "suite": suite, "backend": "unit-oracle"}
    return fixture, traces, metadata


@pytest.mark.parametrize("module", ["M02", "M04"])
def test_canonical_fixture_roundtrip_recomputes_metrics(tmp_path, module):
    fixture, raw, metadata = _case(module)
    profile = metadata["scoring_profile"]
    measured = score_profile(profile, [{"fixture": fixture}], raw)
    traces = [{**row, "scoring_family": metadata["family"]} for row in raw]
    destination = tmp_path / module
    write_bundle(
        destination,
        benchmark=fixture,
        metadata=metadata,
        metrics=measured,
        traces=traces,
    )
    assert verify_bundle(destination) == {
        "family": metadata["family"],
        "suite": metadata["suite"],
        "valid": True,
    }


@pytest.mark.parametrize("module", ["M02", "M04"])
def test_transport_family_does_not_weaken_closed_trace_schema(module):
    fixture, raw, metadata = _case(module)
    traces = [{**row, "scoring_family": metadata["family"]} for row in raw]
    expected = score_profile(metadata["scoring_profile"], [{"fixture": fixture}], raw)
    assert (
        score_profile(metadata["scoring_profile"], [{"fixture": fixture}], traces)
        == expected
    )
    poisoned = deepcopy(traces)
    poisoned[0]["invented_metric"] = 1.0
    with pytest.raises(ValueError):
        score_profile(metadata["scoring_profile"], [{"fixture": fixture}], poisoned)
    poisoned = deepcopy(traces)
    poisoned[0]["scoring_family"] = "qa"
    with pytest.raises(ValueError):
        score_profile(metadata["scoring_profile"], [{"fixture": fixture}], poisoned)


@pytest.mark.parametrize("module", ["M02", "M04"])
def test_bundle_rejects_duplicate_observation(tmp_path, module):
    fixture, raw, metadata = _case(module)
    measured = score_profile(metadata["scoring_profile"], [{"fixture": fixture}], raw)
    traces = [{**row, "scoring_family": metadata["family"]} for row in raw]
    traces.append(deepcopy(traces[0]))
    destination = tmp_path / module
    write_bundle(
        destination,
        benchmark=fixture,
        metadata=metadata,
        metrics=measured,
        traces=traces,
    )
    with pytest.raises(BundleError, match="duplicate trace"):
        verify_bundle(destination)


def test_m04_bundle_rejects_missing_observation_even_with_adjusted_counts(tmp_path):
    fixture, raw, metadata = _case("M04")
    measured = score_profile(metadata["scoring_profile"], [{"fixture": fixture}], raw)
    traces = [{**row, "scoring_family": metadata["family"]} for row in raw[1:]]
    measured["total"] -= 1
    measured["trace_count"] -= 1
    destination = tmp_path / "missing"
    write_bundle(
        destination,
        benchmark=fixture,
        metadata=metadata,
        metrics=measured,
        traces=traces,
    )
    with pytest.raises(BundleError, match="trace/metric count drift"):
        verify_bundle(destination)


@pytest.mark.parametrize("module", ["M02", "M04"])
def test_bundle_rejects_forged_metrics_with_valid_manifest(tmp_path, module):
    fixture, raw, metadata = _case(module)
    measured = score_profile(metadata["scoring_profile"], [{"fixture": fixture}], raw)
    measured["passed"] = not measured["passed"]
    traces = [{**row, "scoring_family": metadata["family"]} for row in raw]
    destination = tmp_path / module
    write_bundle(
        destination,
        benchmark=fixture,
        metadata=metadata,
        metrics=measured,
        traces=traces,
    )
    with pytest.raises(BundleError, match="metrics do not recompute"):
        verify_bundle(destination)


def test_adapters_emit_family_tags_for_both_m04_row_types(monkeypatch):
    from types import SimpleNamespace
    from eval.public.adapters import whole_memory_reference as adapter

    fixture = m04.load_fixture()
    monkeypatch.setattr(adapter, "_m04_ingest", lambda *args: None)
    monkeypatch.setattr(adapter, "_m04_as_of", lambda *args: [])
    cli = SimpleNamespace(backend="unit", answer=lambda *args: {"abstained": True})
    traces, _ = adapter.run_m04_conflict_development(fixture, cli)
    assert any("source_id" in row for row in traces)
    assert any("source_id" not in row for row in traces)
    assert all(row["scoring_family"] == "whole-memory-development" for row in traces)
    score_profile("wmbs-m04-v1", [{"fixture": fixture}], traces)
    assert (
        adapter._m02_trace_from_cli("q", [], {"abstained": True})["scoring_family"]
        == "whole-memory-development"
    )
