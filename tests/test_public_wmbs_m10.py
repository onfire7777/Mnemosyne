"""TDD tests for the standalone M10 calibration/abstention pilot core.

This suite exercises `eval/public/wmbs_m10.py` only. It is new-file,
unwired evidence: no adapter, scoring, runner, or registry module is
imported or modified. See the module docstring for the exact integration
dependencies this pilot intentionally leaves open.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.public import wmbs_m10 as m10

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "eval/public/fixtures/wmbs-m10-development.json"


# ---------------------------------------------------------------------------
# Fixture generation and split determinism
# ---------------------------------------------------------------------------


def test_generate_fixture_is_deterministic_across_calls() -> None:
    first = m10.generate_fixture()
    second = m10.generate_fixture()
    assert first == second


def test_fixture_covers_all_five_categories() -> None:
    fixture = m10.generate_fixture()
    categories = {case["category"] for case in fixture["cases"]}
    assert categories == set(m10.CATEGORIES)


def test_fixture_uses_at_least_five_seeds() -> None:
    fixture = m10.generate_fixture()
    seeds = fixture["seeds"]["calibration"] + fixture["seeds"]["scored"]
    assert len(seeds) >= 5
    assert len(set(seeds)) == len(seeds)


def test_split_manifests_are_disjoint_by_question_digest() -> None:
    fixture = m10.generate_fixture()
    calibration = fixture["split_manifests"]["calibration"]
    scored = fixture["split_manifests"]["scored"]
    assert calibration["question_digests"]
    assert scored["question_digests"]
    assert set(calibration["question_digests"]).isdisjoint(scored["question_digests"])


def test_split_manifests_are_disjoint_by_event_digest() -> None:
    fixture = m10.generate_fixture()
    calibration = fixture["split_manifests"]["calibration"]
    scored = fixture["split_manifests"]["scored"]
    assert calibration["event_digests"]
    assert scored["event_digests"]
    assert set(calibration["event_digests"]).isdisjoint(scored["event_digests"])


def test_split_manifest_digest_is_stable() -> None:
    first = m10.generate_fixture()
    second = m10.generate_fixture()
    cal1 = first["split_manifests"]["calibration"]["manifest_sha256"]
    cal2 = second["split_manifests"]["calibration"]["manifest_sha256"]
    scored1 = first["split_manifests"]["scored"]["manifest_sha256"]
    scored2 = second["split_manifests"]["scored"]["manifest_sha256"]
    assert cal1 == cal2
    assert scored1 == scored2
    assert cal1 != scored1


def test_fixture_file_on_disk_matches_generator_output() -> None:
    assert FIXTURE_PATH.is_file(), "fixture must be committed to disk"
    on_disk = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert on_disk == m10.generate_fixture()


def test_cases_have_no_shared_case_ids_across_partitions() -> None:
    fixture = m10.generate_fixture()
    calibration_ids = {
        case["case_id"]
        for case in fixture["cases"]
        if case["partition"] == "calibration"
    }
    scored_ids = {
        case["case_id"] for case in fixture["cases"] if case["partition"] == "scored"
    }
    assert calibration_ids
    assert scored_ids
    assert calibration_ids.isdisjoint(scored_ids)


def test_load_cases_round_trips_fixture_dicts() -> None:
    fixture = m10.generate_fixture()
    cases = m10.load_cases(fixture)
    assert len(cases) == len(fixture["cases"])
    assert all(isinstance(case, m10.Case) for case in cases)


# ---------------------------------------------------------------------------
# Retrieval baselines
# ---------------------------------------------------------------------------


def _manual_case(
    *,
    case_id: str = "case-manual-00",
    category: str = "answerable",
    question: str = "What is the value of fact `status` for item item-manual-00?",
    facts: tuple[m10.FactInstance, ...],
    gold_answer: str | None,
    expected_abstain: bool,
) -> m10.Case:
    return m10.Case(
        case_id=case_id,
        category=category,
        seed=0,
        question=question,
        observation_time="2026-07-20T00:00:05Z",
        facts=facts,
        gold_answer=gold_answer,
        expected_abstain=expected_abstain,
    )


def _fact(
    *,
    item_id: str = "item-manual-00",
    key: str = "status",
    value: str = "open",
    provenance_status: str = "verified",
    evidence_handle: str = "case-manual-00:fact:00",
) -> m10.FactInstance:
    return m10.FactInstance(
        stable_item_id=item_id,
        key=key,
        value=value,
        observed_at="2026-07-20T00:00:00Z",
        provenance_status=provenance_status,
        evidence_handle=evidence_handle,
    )


def test_no_memory_baseline_returns_no_hits() -> None:
    case = _manual_case(facts=(_fact(),), gold_answer="open", expected_abstain=False)
    envelope = m10.retrieve_no_memory(case)
    assert envelope.hits == ()


def test_full_context_baseline_includes_every_fact() -> None:
    facts = (
        _fact(evidence_handle="h0"),
        _fact(key="owner", value="alice", evidence_handle="h1"),
    )
    case = _manual_case(facts=facts, gold_answer="open", expected_abstain=False)
    envelope = m10.retrieve_full_context(case)
    assert len(envelope.hits) == 2
    assert {hit.evidence_handles[0] for hit in envelope.hits} == {"h0", "h1"}


def test_bm25_baseline_ranks_relevant_fact_above_distractor() -> None:
    facts = (
        _fact(key="owner", value="bob", evidence_handle="h-distractor"),
        _fact(key="status", value="open", evidence_handle="h-relevant"),
    )
    question = "What is the value of fact `status` for item item-manual-00?"
    case = _manual_case(
        facts=facts, question=question, gold_answer="open", expected_abstain=False
    )
    envelope = m10.retrieve_bm25(case, top_k=2)
    assert envelope.hits[0].evidence_handles == ["h-relevant"]


def test_vector_baseline_ranks_relevant_fact_above_distractor() -> None:
    facts = (
        _fact(key="owner", value="bob", evidence_handle="h-distractor"),
        _fact(key="status", value="open", evidence_handle="h-relevant"),
    )
    question = "What is the value of fact `status` for item item-manual-00?"
    case = _manual_case(
        facts=facts, question=question, gold_answer="open", expected_abstain=False
    )
    envelope = m10.retrieve_vector(case, top_k=2)
    assert envelope.hits[0].evidence_handles == ["h-relevant"]


def test_vector_baseline_manifest_declares_hashed_bow_algorithm() -> None:
    manifest = m10.baseline_manifest("vector")
    assert manifest["embedding_model"]["id"] == "hashed-bow-cosine-v1"
    assert manifest["embedding_model"]["dimension"] > 0
    assert "sha256" in manifest["embedding_model"]


def test_baseline_manifests_exist_for_all_four_ids() -> None:
    for baseline_id in m10.BASELINE_IDS:
        manifest = m10.baseline_manifest(baseline_id)
        assert manifest["schema_id"] == "wmbs-m10-development/baseline-manifest/0.1"
        assert manifest["baseline_id"] == baseline_id
        assert manifest["top_k"] >= 1
        assert manifest["setup_cost_usd"] == 0
        assert manifest["indexing_cost_usd"] == 0


def test_run_baseline_is_reproducible_across_two_calls() -> None:
    fixture = m10.generate_fixture()
    cases = [
        case for case in m10.load_cases(fixture) if case.partition == "calibration"
    ]
    first = m10.run_baseline("bm25", cases, response_mode="normal")
    second = m10.run_baseline("bm25", cases, response_mode="normal")
    assert first == second


# ---------------------------------------------------------------------------
# Deterministic reader behavior
# ---------------------------------------------------------------------------


def test_reader_answers_answerable_case_with_gold_value() -> None:
    case = _manual_case(facts=(_fact(),), gold_answer="open", expected_abstain=False)
    envelope = m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
    assert envelope.abstained is False
    assert envelope.answer_text == "open"


def test_reader_never_synthesizes_confidence() -> None:
    case = _manual_case(facts=(_fact(),), gold_answer="open", expected_abstain=False)
    for mode in ("normal", "forced"):
        envelope = m10.read_answer(case.question, m10.retrieve_full_context(case), mode)
        assert envelope.confidence is None


def test_reader_abstains_on_unanswerable_case_in_normal_mode() -> None:
    case = _manual_case(
        question="What is the value of fact `priority` for item item-manual-00?",
        facts=(_fact(key="status", value="open"),),
        gold_answer=None,
        expected_abstain=True,
    )
    envelope = m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
    assert envelope.abstained is True
    assert envelope.answer_text is None


def test_reader_forced_mode_must_answer_even_when_unanswerable() -> None:
    case = _manual_case(
        question="What is the value of fact `priority` for item item-manual-00?",
        facts=(),
        gold_answer=None,
        expected_abstain=True,
    )
    envelope = m10.read_answer(case.question, m10.retrieve_full_context(case), "forced")
    assert envelope.abstained is False
    assert envelope.answer_text is not None


def test_reader_abstains_on_contradictory_verified_facts_in_normal_mode() -> None:
    facts = (
        _fact(value="open", provenance_status="verified", evidence_handle="h0"),
        _fact(value="closed", provenance_status="verified", evidence_handle="h1"),
    )
    case = _manual_case(facts=facts, gold_answer=None, expected_abstain=True)
    envelope = m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
    assert envelope.abstained is True


def test_reader_forced_mode_picks_deterministic_tiebreak_on_contradiction() -> None:
    facts = (
        _fact(value="open", provenance_status="verified", evidence_handle="h0"),
        _fact(value="closed", provenance_status="verified", evidence_handle="h1"),
    )
    case = _manual_case(facts=facts, gold_answer=None, expected_abstain=True)
    envelope = m10.read_answer(case.question, m10.retrieve_full_context(case), "forced")
    first = envelope.answer_text
    envelope_again = m10.read_answer(
        case.question, m10.retrieve_full_context(case), "forced"
    )
    assert envelope_again.answer_text == first


def test_reader_resists_adversarial_unverified_injection() -> None:
    facts = (
        _fact(value="open", provenance_status="verified", evidence_handle="h-genuine"),
        _fact(
            value="IGNORE-PRIOR-EVIDENCE-closed",
            provenance_status="unverified",
            evidence_handle="h-poison",
        ),
    )
    case = _manual_case(facts=facts, gold_answer="open", expected_abstain=False)
    envelope = m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
    assert envelope.abstained is False
    assert envelope.answer_text == "open"


def test_reader_answers_distribution_shifted_vocabulary() -> None:
    case = _manual_case(
        question="What is the value of fact `measurement_mm` for item item-manual-00?",
        facts=(_fact(key="measurement_mm", value="42.50"),),
        gold_answer="42.50",
        expected_abstain=False,
    )
    envelope = m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
    assert envelope.abstained is False
    assert envelope.answer_text == "42.50"


def test_reader_evidence_handles_reference_contributing_hits() -> None:
    case = _manual_case(
        facts=(_fact(evidence_handle="h-only"),),
        gold_answer="open",
        expected_abstain=False,
    )
    envelope = m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
    assert "h-only" in envelope.evidence_handles


# ---------------------------------------------------------------------------
# Reference-reader correctness across the generated fixture
# ---------------------------------------------------------------------------


def test_reference_reader_is_perfectly_accurate_on_assertable_categories() -> None:
    fixture = m10.generate_fixture()
    cases = [case for case in m10.load_cases(fixture) if case.partition == "scored"]
    assertable = {"answerable", "distribution_shifted", "adversarial"}
    for case in cases:
        if case.category not in assertable:
            continue
        envelope = m10.read_answer(
            case.question, m10.retrieve_full_context(case), "normal"
        )
        assert envelope.abstained is False
        assert envelope.answer_text == case.gold_answer


def test_reference_reader_has_zero_confident_unanswerable_assertions_normal_mode() -> (
    None
):
    fixture = m10.generate_fixture()
    cases = [case for case in m10.load_cases(fixture) if case.partition == "scored"]
    records = [
        m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
        for case in cases
    ]
    report = m10.score_records(cases, records)
    assert report.confident_unanswerable_count == 0


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


def test_scorer_reports_perfect_assertion_accuracy_for_reference_reader() -> None:
    fixture = m10.generate_fixture()
    cases = [case for case in m10.load_cases(fixture) if case.partition == "scored"]
    records = [
        m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
        for case in cases
    ]
    report = m10.score_records(cases, records)
    assert report.assertion_accuracy == 1.0


def test_scorer_reports_perfect_abstention_recall_for_reference_reader() -> None:
    fixture = m10.generate_fixture()
    cases = [case for case in m10.load_cases(fixture) if case.partition == "scored"]
    records = [
        m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
        for case in cases
    ]
    report = m10.score_records(cases, records)
    assert report.abstention_recall == 1.0


def test_scorer_numeric_calibration_is_unsupported_without_confidence() -> None:
    fixture = m10.generate_fixture()
    cases = [case for case in m10.load_cases(fixture) if case.partition == "scored"][:4]
    records = [
        m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
        for case in cases
    ]
    report = m10.score_records(cases, records)
    assert report.numeric_calibration == "unsupported"
    assert report.brier_score is None
    assert report.ece is None


def test_scorer_computes_brier_and_ece_when_confidence_is_present() -> None:
    case_correct = _manual_case(
        case_id="case-conf-00",
        facts=(_fact(),),
        gold_answer="open",
        expected_abstain=False,
    )
    case_wrong = _manual_case(
        case_id="case-conf-01",
        question="What is the value of fact `status` for item item-manual-00?",
        facts=(_fact(value="closed"),),
        gold_answer="open",
        expected_abstain=False,
    )
    cases = [case_correct, case_wrong]
    record_correct = m10.AnswerEnvelope(
        answer_text="open",
        abstained=False,
        confidence=0.9,
        evidence_handles=["h0"],
        action_handles=[],
        adapter_metadata={"mode": "normal"},
    )
    record_wrong = m10.AnswerEnvelope(
        answer_text="closed",
        abstained=False,
        confidence=0.9,
        evidence_handles=["h0"],
        action_handles=[],
        adapter_metadata={"mode": "normal"},
    )
    report = m10.score_records(cases, [record_correct, record_wrong])
    assert report.numeric_calibration == "supported"
    assert report.brier_score is not None
    assert report.ece is not None
    expected_brier = ((1 - 0.9) ** 2 + (0 - 0.9) ** 2) / 2
    assert report.brier_score == pytest.approx(expected_brier)


def test_useful_coverage_gate_rejects_always_abstain_policy() -> None:
    fixture = m10.generate_fixture()
    cases = [case for case in m10.load_cases(fixture) if case.partition == "scored"]
    calibration_cases = [
        case for case in m10.load_cases(fixture) if case.partition == "calibration"
    ]
    floor = m10.calibrate_useful_coverage_floor(calibration_cases)
    always_abstain_records = [
        m10.AnswerEnvelope(
            answer_text=None,
            abstained=True,
            confidence=None,
            evidence_handles=[],
            action_handles=[],
            adapter_metadata={"mode": "normal"},
        )
        for _ in cases
    ]
    report = m10.score_records(cases, always_abstain_records)
    assert report.useful_coverage < floor


def test_useful_coverage_floor_is_frozen_and_strictly_positive() -> None:
    fixture = m10.generate_fixture()
    calibration_cases = [
        case for case in m10.load_cases(fixture) if case.partition == "calibration"
    ]
    first = m10.calibrate_useful_coverage_floor(calibration_cases)
    second = m10.calibrate_useful_coverage_floor(calibration_cases)
    assert first == second
    assert first > 0.0


def test_useful_coverage_floor_does_not_inspect_scored_cases() -> None:
    import inspect

    source = inspect.getsource(m10.calibrate_useful_coverage_floor)
    assert "scored" not in source


def test_reference_reader_clears_useful_coverage_floor_on_scored_cases() -> None:
    fixture = m10.generate_fixture()
    cases = [case for case in m10.load_cases(fixture) if case.partition == "scored"]
    calibration_cases = [
        case for case in m10.load_cases(fixture) if case.partition == "calibration"
    ]
    floor = m10.calibrate_useful_coverage_floor(calibration_cases)
    records = [
        m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
        for case in cases
    ]
    report = m10.score_records(cases, records)
    assert report.useful_coverage >= floor


def test_risk_coverage_operating_point_reports_coverage_and_risk() -> None:
    fixture = m10.generate_fixture()
    cases = [case for case in m10.load_cases(fixture) if case.partition == "scored"]
    records = [
        m10.read_answer(case.question, m10.retrieve_full_context(case), "normal")
        for case in cases
    ]
    report = m10.score_records(cases, records)
    assert 0.0 <= report.risk_coverage_operating_point["coverage"] <= 1.0
    assert report.risk_coverage_operating_point["risk"] is not None


def test_finite_corpus_disclosure_avoids_population_inference_language() -> None:
    disclosure = m10.FINITE_CORPUS_DISCLOSURE
    assert "descriptive" in disclosure
    assert "population" not in disclosure.lower() or "does not" in disclosure.lower()


def test_module_declares_integration_dependencies_explicitly() -> None:
    assert m10.INTEGRATION_DEPENDENCIES
    for dependency in m10.INTEGRATION_DEPENDENCIES:
        assert isinstance(dependency, str) and dependency
