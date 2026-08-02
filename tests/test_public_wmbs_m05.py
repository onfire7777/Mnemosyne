"""Contract tests for the standalone M05 development core."""

from __future__ import annotations

import importlib
import importlib.util
import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from eval.public import runner

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "eval/public/fixtures/wmbs-m05-provenance-development.json"


def _module():
    spec = importlib.util.find_spec("eval.public.wmbs_m05")
    assert spec is not None, "M05 module must exist"
    return importlib.import_module("eval.public.wmbs_m05")


def _traces(fixture):
    traces = []
    for slice_ in fixture["slices"]:
        for case in slice_["cases"]:
            if not case["scored"]:
                continue
            handles = case["gold_source_cids"]
            abstained = slice_["slice_id"] in {
                "tampered-lineage",
                "unsupported-claim",
            }
            traces.append(
                {
                    "case_id": case["case_id"],
                    "answer_envelope": {
                        "abstained": abstained,
                        "answer_text": None if abstained else case["claim"],
                        "evidence_handles": []
                        if abstained
                        else list(reversed(handles)),
                        "action_handles": [],
                        "adapter_metadata": {"mode": "deterministic"},
                    },
                    "explanation": {
                        "source_evidence_cids": handles,
                        "stages": case.get("retrieval_stages", ["lexical"]),
                    },
                    "provenance_status": "verified",
                }
            )
    return traces


def _rehash(m05, fixture) -> None:
    payload = dict(fixture)
    payload.pop("dataset_sha256", None)
    fixture["dataset_sha256"] = m05.canonical_sha256(payload)


def test_claim_source_completeness_is_a_hard_rail() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    result = m05.score(fixture, _traces(fixture))
    assert result["metrics"]["M-PROV-COMPLETE"] == 1.0
    assert result["metrics"]["M-EXPLAIN-COV"] == 1.0
    assert result["passed"] is True


@pytest.mark.parametrize("stages", [None, ["unknown-stage"]])
def test_explanation_contract_requires_complete_retrieval_stages(stages) -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    target = next(
        trace for trace in traces if "protected-grounding" in trace["case_id"]
    )
    if stages is None:
        del target["explanation"]["stages"]
    else:
        target["explanation"]["stages"] = stages
    with pytest.raises(m05.WmbsM05Error, match="stages"):
        m05.score(fixture, traces)


def test_fixture_declares_frozen_retrieval_stages() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    assert all(
        case["retrieval_stages"] == ["lexical"]
        for slice_ in fixture["slices"]
        for case in slice_["cases"]
    )


def test_citation_set_metrics_are_order_invariant_diagnostics() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    first = m05.score(fixture, traces)
    for trace in traces:
        trace["answer_envelope"]["evidence_handles"].reverse()
    second = m05.score(fixture, traces)
    assert first["metrics"]["citation_precision"] == 1.0
    assert first["metrics"]["citation_recall"] == 1.0
    assert first["metrics"] == second["metrics"]


def test_non_abstained_claim_without_valid_source_is_unsupported() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    target = next(trace for trace in traces if "unsupported-claim" in trace["case_id"])
    target["answer_envelope"]["evidence_handles"] = []
    target["answer_envelope"]["abstained"] = False
    target["answer_envelope"]["answer_text"] = "unsupported answer"
    target["explanation"]["source_evidence_cids"] = []
    result = m05.score(fixture, traces)
    assert result["metrics"]["unsupported_claim_rate"] > 0
    assert result["passed"] is False


def test_unsupported_cases_use_non_supporting_sources_that_cannot_become_gold() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    unsupported = fixture["slices"][3]["cases"]
    assert all(
        "supports claim" not in case["source_events"][0]["content"].lower()
        for case in unsupported
    )

    traces = _traces(fixture)
    target_case = unsupported[0]
    target_trace = next(
        trace for trace in traces if trace["case_id"] == target_case["case_id"]
    )
    supplied_cid = m05.recompute_source_cids(fixture)[
        target_case["source_events"][0]["event_id"]
    ]
    assert supplied_cid not in target_case["gold_source_cids"]
    target_trace["answer_envelope"]["abstained"] = False
    target_trace["answer_envelope"]["answer_text"] = target_case["claim"]
    target_trace["answer_envelope"]["evidence_handles"] = [supplied_cid]
    target_trace["explanation"]["source_evidence_cids"] = [supplied_cid]

    result = m05.score(fixture, traces)
    assert result["metrics"]["unsupported_claim_rate"] > 0.0
    assert result["passed"] is False


def test_tampered_lineage_is_rejected_despite_verified_self_declaration() -> None:
    m05 = _module()
    fixture = deepcopy(m05.generate_fixture(13))
    traces = _traces(fixture)
    assert all(trace["provenance_status"] == "verified" for trace in traces)
    result = m05.score(fixture, traces)
    assert result["metrics"]["lineage_tamper_rejection"] == 1.0
    assert result["passed"] is True


def test_committed_fixture_exists_and_matches_generator_bytes() -> None:
    m05 = _module()
    assert FIXTURE_PATH.is_file(), "M05 fixture must exist"
    assert FIXTURE_PATH.read_bytes() == m05.canonical_json(m05.generate_fixture(13))


def test_fixture_has_fixed_matrix_and_all_portable_event_keys() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    assert tuple(slice_["slice_id"] for slice_ in fixture["slices"]) == m05.SLICE_IDS
    assert sum(len(slice_["cases"]) for slice_ in fixture["slices"]) == 100
    required = {
        "event_id",
        "content",
        "actor_label",
        "event_time",
        "ingestion_time",
        "content_sha256",
        "public_metadata",
    }
    assert all(
        set(event) == required
        for slice_ in fixture["slices"]
        for case in slice_["cases"]
        for event in case["source_events"]
    )


@pytest.mark.parametrize(
    "label",
    sorted(
        {
            "admission_state",
            "comparability",
            "headline_eligible",
            "independent_reproduction",
            "module_id",
            "pbpp_headline_eligible",
            "publishable",
            "track",
            "upstream_comparable",
        }
    ),
)
def test_fixture_rejects_missing_or_permissive_custody_labels(label: str) -> None:
    m05 = _module()
    for mutation in ("missing", "permissive"):
        fixture = deepcopy(m05.generate_fixture(13))
        if mutation == "missing":
            del fixture[label]
        else:
            fixture[label] = True if fixture[label] is not True else "permissive"
        with pytest.raises(m05.WmbsM05Error):
            m05.validate_fixture(fixture)


@pytest.mark.parametrize("mutation", ["reduce", "reorder", "duplicate", "rename"])
def test_fixture_rejects_matrix_mutation(mutation: str) -> None:
    m05 = _module()
    fixture = deepcopy(m05.generate_fixture(13))
    if mutation == "reduce":
        fixture["slices"].pop()
    elif mutation == "reorder":
        fixture["slices"][0], fixture["slices"][1] = (
            fixture["slices"][1],
            fixture["slices"][0],
        )
    elif mutation == "duplicate":
        fixture["slices"][1] = deepcopy(fixture["slices"][0])
    else:
        fixture["slices"][0]["slice_id"] = "renamed"
    with pytest.raises(m05.WmbsM05Error):
        m05.validate_fixture(fixture)


def test_derived_claims_and_sensitivity_binding_remain_explicitly_deferred() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    assert fixture["sensitivity_binding"] == {
        "protected_slice_sensitivity": 2,
        "reason": "Q8",
    }
    derived = next(s for s in fixture["slices"] if s["slice_id"] == "derived-claims")
    assert all(
        case["scored"] is False and case["deferral_reason"] == "howprovenance-unwired"
        for case in derived["cases"]
    )


def test_fixture_digest_and_runner_canonicalizer_agree() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    without_digest = dict(fixture)
    digest = without_digest.pop("dataset_sha256")
    assert m05.canonical_json(fixture) == runner._canonical(fixture)
    assert digest == m05.canonical_sha256(without_digest)


def test_manifest_changes_when_fixture_content_changes() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    before = m05.source_manifest(fixture)
    mutated = deepcopy(fixture)
    event = mutated["slices"][1]["cases"][0]["source_events"][1]
    event["content"] += "x"
    event["content_sha256"] = hashlib.sha256(event["content"].encode()).hexdigest()
    check = dict(mutated)
    check.pop("dataset_sha256")
    mutated["dataset_sha256"] = m05.canonical_sha256(check)
    after = m05.source_manifest(mutated)
    assert before["fixture_sha256"] != after["fixture_sha256"]
    assert before["source_cids_sha256"] != after["source_cids_sha256"]


def test_abstained_envelope_with_citations_is_malformed() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    traces[0]["answer_envelope"]["abstained"] = True
    traces[0]["answer_envelope"]["answer_text"] = None
    with pytest.raises(m05.WmbsM05Error, match="evidence handles"):
        m05.score(fixture, traces)


def test_missing_protected_trace_fails_closed() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    traces.pop(0)
    with pytest.raises(m05.WmbsM05Error, match="missing scored case_id"):
        m05.score(fixture, traces)


def test_omitting_all_distractor_traces_fails_closed() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = [
        trace
        for trace in _traces(fixture)
        if "distractor-sources" not in trace["case_id"]
    ]
    with pytest.raises(m05.WmbsM05Error, match="missing scored case_id"):
        m05.score(fixture, traces)


def test_protected_non_abstained_claim_without_valid_source_is_unsupported() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    target = next(
        trace for trace in traces if "protected-grounding" in trace["case_id"]
    )
    target["answer_envelope"]["evidence_handles"] = []
    target["explanation"]["source_evidence_cids"] = []
    result = m05.score(fixture, traces)
    assert result["metrics"]["unsupported_claim_rate"] > 0
    assert result["passed"] is False


def test_fixture_carries_and_validates_disclosure_contracts() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    assert fixture["integration_dependencies"] == list(m05.INTEGRATION_DEPENDENCIES)
    assert fixture["disclosure"] == m05.FINITE_CORPUS_DISCLOSURE
    for field in ("integration_dependencies", "disclosure"):
        for mutation in ("missing", "tampered"):
            changed = deepcopy(fixture)
            if mutation == "missing":
                del changed[field]
            else:
                changed[field] = (
                    [] if field == "integration_dependencies" else "tampered"
                )
            _rehash(m05, changed)
            with pytest.raises(m05.WmbsM05Error):
                m05.validate_fixture(changed)


def test_distinct_source_contents_cannot_share_a_gold_evidence_handle() -> None:
    m05 = _module()
    fixture = deepcopy(m05.generate_fixture(13))
    protected = fixture["slices"][0]["cases"]
    assert (
        protected[0]["source_events"][0]["content"]
        != protected[1]["source_events"][0]["content"]
    )
    protected[1]["gold_source_cids"] = list(protected[0]["gold_source_cids"])
    _rehash(m05, fixture)
    with pytest.raises(m05.WmbsM05Error, match="evidence handle"):
        m05.score(fixture, _traces(fixture))


def test_cross_case_real_cid_cannot_ground_a_different_protected_claim() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    fixture_bytes = m05.canonical_json(fixture)
    traces = _traces(fixture)
    protected = [trace for trace in traces if "protected-grounding" in trace["case_id"]]
    foreign_cid = protected[0]["answer_envelope"]["evidence_handles"][0]
    protected[1]["answer_envelope"]["evidence_handles"] = [foreign_cid]
    protected[1]["explanation"]["source_evidence_cids"] = [foreign_cid]

    result = m05.score(fixture, traces)

    assert m05.canonical_json(fixture) == fixture_bytes
    assert result["metrics"]["M-PROV-COMPLETE"] < 1.0
    assert result["metrics"]["unsupported_claim_rate"] > 0.0
    assert result["passed"] is False


def test_trace_case_id_must_exist_in_fixture() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    unknown = deepcopy(traces[0])
    unknown["case_id"] = "m05-unknown-case"
    with pytest.raises(m05.WmbsM05Error, match="case_id"):
        m05.score(fixture, [*traces, unknown])


def test_replay_is_bound_to_fixture_and_generation_seed() -> None:
    m05 = _module()
    generated_13 = m05.generate_fixture(13)
    generated_29 = m05.generate_fixture(29)
    assert m05.canonical_json(generated_13) != m05.canonical_json(generated_29)
    assert (
        generated_13["slices"][0]["cases"][0]["source_events"][0]["content"]
        != generated_29["slices"][0]["cases"][0]["source_events"][0]["content"]
    )
    fixture = deepcopy(m05.generate_fixture(13))
    event = fixture["slices"][1]["cases"][0]["source_events"][1]
    event["content"] += " mutation"
    event["content_sha256"] = hashlib.sha256(event["content"].encode()).hexdigest()
    _rehash(m05, fixture)
    result = m05.score(fixture, _traces(fixture))
    assert result["metrics"]["five_seed_canonical_replay"] == 0.0


def test_clean_fixture_passes_five_seed_canonical_replay() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    result = m05.score(fixture, _traces(fixture))
    assert result["metrics"]["five_seed_canonical_replay"] == 1.0


def test_distractor_citations_degrade_diagnostic_without_failing_rails() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    cids = m05.recompute_source_cids(fixture)
    distractors = {
        case["case_id"]: cids[case["source_events"][1]["event_id"]]
        for case in fixture["slices"][1]["cases"]
    }
    for trace in traces:
        if trace["case_id"] in distractors:
            trace["answer_envelope"]["evidence_handles"] = [
                distractors[trace["case_id"]]
            ]
    result = m05.score(fixture, traces)
    assert result["metrics"]["citation_precision"] == 0.0
    assert result["passed"] is True


def test_fixture_rejects_fake_content_digest() -> None:
    m05 = _module()
    fixture = deepcopy(m05.generate_fixture(13))
    fixture["slices"][0]["cases"][0]["source_events"][0]["content_sha256"] = "0" * 64
    _rehash(m05, fixture)
    with pytest.raises(m05.WmbsM05Error, match="content_sha256"):
        m05.validate_fixture(fixture)


def test_tampered_lineage_gold_must_bind_to_original_content() -> None:
    m05 = _module()
    fixture = deepcopy(m05.generate_fixture(13))
    tampered = fixture["slices"][2]["cases"][0]
    tampered["gold_source_cids"] = ["f" * 64]
    _rehash(m05, fixture)
    with pytest.raises(m05.WmbsM05Error, match="tampered-lineage"):
        m05.validate_fixture(fixture)


def test_fixture_rejects_attacker_controlled_capture_metadata() -> None:
    m05 = _module()
    fixture = deepcopy(m05.generate_fixture(13))
    event = fixture["slices"][0]["cases"][0]["source_events"][0]
    event["public_metadata"]["tenant_id"] = "attacker-tenant"
    _rehash(m05, fixture)
    with pytest.raises(m05.WmbsM05Error, match="public_metadata"):
        m05.validate_fixture(fixture)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("license", "Proprietary"),
        ("source_manifest", {"signed": True, "reason": "attacker"}),
        ("seeds", [73, 59, 41, 29, 13]),
        ("generator_id", "attacker-generator"),
        ("generator_version", "9.9.9"),
    ],
)
def test_fixture_rejects_mutated_identity_and_custody_fields(field, value) -> None:
    m05 = _module()
    fixture = deepcopy(m05.generate_fixture(13))
    fixture[field] = value
    _rehash(m05, fixture)
    with pytest.raises(m05.WmbsM05Error, match=field):
        m05.validate_fixture(fixture)


@pytest.mark.parametrize("mutation", ["duplicate", "substitute"])
def test_fixture_rejects_incomplete_or_reused_case_identity_matrix(mutation) -> None:
    m05 = _module()
    fixture = deepcopy(m05.generate_fixture(13))
    cases = fixture["slices"][0]["cases"]
    if mutation == "duplicate":
        cases[1] = deepcopy(cases[0])
    else:
        cases[1]["case_id"] = "m05-substituted-case"
    _rehash(m05, fixture)
    with pytest.raises(m05.WmbsM05Error, match="case identity matrix"):
        m05.validate_fixture(fixture)


def test_replay_drift_is_a_hard_aggregate_failure() -> None:
    m05 = _module()
    fixture = deepcopy(m05.generate_fixture(13))
    event = fixture["slices"][1]["cases"][0]["source_events"][1]
    event["content"] += " replay drift"
    event["content_sha256"] = hashlib.sha256(event["content"].encode()).hexdigest()
    _rehash(m05, fixture)
    result = m05.score(fixture, _traces(fixture))
    assert result["metrics"]["five_seed_canonical_replay"] == 0.0
    assert result["passed"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("explanation", None),
        ("evidence_handles", "not-a-list"),
        ("evidence_handles", [7]),
        ("action_handles", "not-a-list"),
    ],
)
def test_trace_rejects_malformed_explanation_and_handles(field, value) -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    if field == "explanation":
        traces[0][field] = value
    else:
        traces[0]["answer_envelope"][field] = value
    with pytest.raises(m05.WmbsM05Error):
        m05.score(fixture, traces)


@pytest.mark.parametrize(
    "traces",
    ["not-a-trace-list", b"not-a-trace-list", {"case_id": "mapping-container"}],
)
def test_trace_container_rejects_strings_bytes_and_mappings(traces) -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    with pytest.raises(m05.WmbsM05Error, match="trace container"):
        m05.score(fixture, traces)


def test_trace_container_rejects_non_mapping_items() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    with pytest.raises(m05.WmbsM05Error, match="trace item"):
        m05.score(fixture, [None])


@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_trace_top_level_fields_are_closed(mutation) -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    if mutation == "unknown":
        traces[0]["unknown_field"] = "not allowed"
    else:
        del traces[0]["provenance_status"]
    with pytest.raises(m05.WmbsM05Error, match="trace fields"):
        m05.score(fixture, traces)


def test_trace_rejects_nonempty_action_handles() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    traces[0]["answer_envelope"]["action_handles"] = ["forbidden-action"]
    with pytest.raises(m05.WmbsM05Error, match="action_handles"):
        m05.score(fixture, traces)


def test_trace_rejects_duplicate_evidence_handles_before_set_scoring() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    handle = traces[0]["answer_envelope"]["evidence_handles"][0]
    traces[0]["answer_envelope"]["evidence_handles"] = [handle, handle]
    with pytest.raises(m05.WmbsM05Error, match="evidence_handles"):
        m05.score(fixture, traces)


@pytest.mark.parametrize(
    "handles",
    [
        [f"h{index}" for index in range(1001)],
        [""],
        ["a" * 129],
        ["invalid handle"],
    ],
)
def test_trace_enforces_frozen_evidence_handle_bounds(handles) -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    traces[0]["answer_envelope"]["evidence_handles"] = handles
    with pytest.raises(m05.WmbsM05Error, match="evidence_handles"):
        m05.score(fixture, traces)


@pytest.mark.parametrize(
    ("abstained", "answer_text", "missing"),
    [
        (False, None, True),
        (False, None, False),
        (False, "", False),
        (False, "   ", False),
        (False, "x" * 65537, False),
        (True, "contradictory answer", False),
    ],
)
def test_trace_rejects_missing_or_contradictory_answer_text(
    abstained, answer_text, missing
) -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    envelope = traces[0]["answer_envelope"]
    envelope["abstained"] = abstained
    if missing:
        del envelope["answer_text"]
    else:
        envelope["answer_text"] = answer_text
    with pytest.raises(m05.WmbsM05Error, match="answer_text"):
        m05.score(fixture, traces)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unknown_field", "not allowed"),
        ("confidence", "0.5"),
        ("confidence", -0.1),
        ("confidence", 1.1),
        ("adapter_metadata", {"unknown": "value"}),
        ("adapter_metadata", {"mode": ""}),
        ("adapter_metadata", {"mode": " "}),
        ("adapter_metadata", {"mode": "x" * 257}),
    ],
)
def test_trace_enforces_frozen_optional_answer_envelope_fields(field, value) -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    traces[0]["answer_envelope"][field] = value
    with pytest.raises(m05.WmbsM05Error):
        m05.score(fixture, traces)


@pytest.mark.parametrize("confidence", [None, 0, 1, 0.5])
def test_trace_accepts_valid_optional_confidence_bounds(confidence) -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    traces[0]["answer_envelope"]["confidence"] = confidence
    assert m05.score(fixture, traces)["passed"] is True


@pytest.mark.parametrize("metadata", [{}, {"mode": "deterministic"}])
def test_trace_accepts_adapter_metadata_with_absent_or_valid_mode(metadata) -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    traces[0]["answer_envelope"]["adapter_metadata"] = metadata
    assert m05.score(fixture, traces)["passed"] is True


def test_trace_accepts_absent_optional_confidence() -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    assert "confidence" not in traces[0]["answer_envelope"]
    assert m05.score(fixture, traces)["passed"] is True


@pytest.mark.parametrize(
    "stages",
    ["lexical", [], ["lexical", "lexical"], ["unknown-stage"]],
)
def test_trace_rejects_malformed_duplicate_or_unknown_stages(stages) -> None:
    m05 = _module()
    fixture = m05.generate_fixture(13)
    traces = _traces(fixture)
    traces[0]["explanation"]["stages"] = stages
    with pytest.raises(m05.WmbsM05Error, match="stages"):
        m05.score(fixture, traces)
