from __future__ import annotations

import copy
import subprocess
import sys

import pytest

from eval.public import wmbs_m04 as m04


def _perfect(
    fixture: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    observations: list[dict[str, object]] = []
    ablations: list[dict[str, object]] = []
    for case in fixture["cases"]:  # type: ignore[index]
        gold = case["gold"]
        for permutation in m04.PERMUTATIONS:
            unresolved = gold["unresolved"]
            observations.append(
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
                        if unresolved
                        else gold["current_objects"][0],
                        "abstained": unresolved,
                        "evidence_handles": [],
                        "action_handles": [],
                        "adapter_metadata": {"mode": "normal"},
                    },
                    "monotonic_violation": False,
                }
            )
            for source_id, objects in gold["ablation_objects"].items():
                ablations.append(
                    {
                        "case_id": case["case_id"],
                        "permutation": permutation,
                        "source_id": source_id,
                        "current": {"objects": objects, "as_of": gold["current_as_of"]},
                    }
                )
    return observations, ablations


def _redigest(fixture: dict[str, object]) -> None:
    unsigned = dict(fixture)
    unsigned.pop("fixture_sha256")
    fixture["fixture_sha256"] = m04.canonical_sha256(unsigned)


def test_fixture_schema_is_label_neutral() -> None:
    fixture = m04.generate_fixture()
    m04.validate_fixture(fixture)
    for forbidden in (
        "trust_tier",
        "source_trust_tier",
        "status",
        "superseded_by",
        "contested",
        "confidence",
    ):
        poisoned = copy.deepcopy(fixture)
        poisoned["cases"][0]["events_by_permutation"]["as_authored"][0][forbidden] = "x"
        with pytest.raises(m04.WmbsM04Error):
            m04.validate_fixture(poisoned)


def test_fixture_covers_seven_source_classes_five_seeds_three_permutations() -> None:
    fixture = m04.generate_fixture()
    assert len(fixture["cases"]) == 7 * 4 * 5
    assert tuple(fixture["seeds"]) == m04.SEEDS == (11, 23, 37, 53, 71)
    assert (
        tuple(fixture["permutations"])
        == m04.PERMUTATIONS
        == ("as_authored", "reversed", "interleaved")
    )
    reduced = copy.deepcopy(fixture)
    reduced["cases"].pop()
    with pytest.raises(m04.WmbsM04Error):
        m04.validate_fixture(reduced)


def test_fixture_rejects_resigned_full_duplicate_case_before_indexing() -> None:
    fixture = m04.generate_fixture()
    fixture["cases"][4] = copy.deepcopy(fixture["cases"][0])
    _redigest(fixture)

    with pytest.raises(m04.WmbsM04Error, match="canonical and unique"):
        m04.validate_fixture(fixture)


@pytest.mark.parametrize(
    "invalid_objects",
    [[], "not-a-list", ["duplicate", "duplicate"]],
)
def test_fixture_and_scorer_reject_invalid_resolved_gold_objects(
    invalid_objects: object,
) -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    resolved = next(case for case in fixture["cases"] if not case["gold"]["unresolved"])
    resolved["gold"]["current_objects"] = invalid_objects
    _redigest(fixture)

    with pytest.raises(m04.WmbsM04Error, match="gold.current_objects"):
        m04.validate_fixture(fixture)
    with pytest.raises(m04.WmbsM04Error, match="gold.current_objects"):
        m04.score_current_answer(fixture, observations)


@pytest.mark.parametrize("object_count", [0, 1])
def test_fixture_rejects_resigned_unresolved_gold_below_two_objects(
    object_count: int,
) -> None:
    fixture = m04.generate_fixture()
    unresolved = next(case for case in fixture["cases"] if case["gold"]["unresolved"])
    unresolved["gold"]["current_objects"] = unresolved["gold"]["current_objects"][
        :object_count
    ]
    _redigest(fixture)

    with pytest.raises(m04.WmbsM04Error, match="at least two unique strings"):
        m04.validate_fixture(fixture)


@pytest.mark.parametrize(
    ("field", "drifted"),
    [
        ("generator_id", "other.generate_fixture"),
        ("generator_version", "1.0.1"),
    ],
)
def test_fixture_and_standalone_scorer_reject_resigned_generator_drift(
    field: str, drifted: str
) -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    fixture[field] = drifted
    _redigest(fixture)

    with pytest.raises(m04.WmbsM04Error, match="generator identity mismatch"):
        m04.validate_fixture(fixture)
    with pytest.raises(m04.WmbsM04Error, match="generator identity mismatch"):
        m04.score_current_answer(fixture, observations)


def test_every_case_has_three_pairwise_distinct_source_orders() -> None:
    for case in m04.generate_fixture()["cases"]:
        orders = {
            tuple(event["event_id"] for event in case["events_by_permutation"][name])
            for name in m04.PERMUTATIONS
        }
        assert len(orders) == len(m04.PERMUTATIONS), case["case_id"]


def test_independent_events_are_distinct_resolved_assertions() -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    independent = [
        case for case in fixture["cases"] if case["source_class"] == "independent"
    ]
    for case in independent:
        events = case["events_by_permutation"]["as_authored"]
        fields = [
            dict(part.split("=", 1) for part in event["content"].split() if "=" in part)
            for event in events
        ]
        identities = {
            (field.get("subject"), field.get("predicate")) for field in fields
        }
        assert len(identities) == len(events) == 3
        assert case["gold"]["unresolved"] is False
    independent_ids = {case["case_id"] for case in independent}
    assert all(
        not row["answer"]["abstained"]
        for row in observations
        if row["case_id"] in independent_ids
    )
    assert m04.score_current_answer(fixture, observations)["passed"] is True
    assert m04.score_unresolved_calibration(fixture, observations)["passed"] is True


def test_generate_fixture_is_byte_reproducible() -> None:
    raw = m04.FIXTURE_PATH.read_bytes()
    fixture = m04.generate_fixture()
    assert m04.canonical_json(fixture) == raw
    unsigned = dict(fixture)
    digest = unsigned.pop("fixture_sha256")
    assert digest == m04.canonical_sha256(unsigned)
    assert m04.load_fixture() == fixture
    assert m04.normalize_fixture(fixture) == fixture


def test_historical_preservation_gate_is_exact() -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    assert m04.score_historical_preservation(fixture, observations)["passed"] is True
    target = next(row for row in observations if row["historical"]["objects"])
    target["historical"]["objects"] = []
    result = m04.score_historical_preservation(fixture, observations)
    assert result["rate"] < 1.0
    assert result["passed"] is False


def test_historical_preservation_rejects_wrong_as_of() -> None:
    fixture = m04.generate_fixture()
    observations, ablations = _perfect(fixture)
    target = next(row for row in observations if row["historical"]["objects"])
    target["historical"]["as_of"] = "2026-07-19T00:00:00Z"

    metric = m04.score_historical_preservation(fixture, observations)
    assert metric["passed"] is False
    assert m04.score_conflict(fixture, observations, ablations)["passed"] is False


def test_current_answer_rejects_wrong_as_of_and_fails_aggregate() -> None:
    fixture = m04.generate_fixture()
    observations, ablations = _perfect(fixture)
    for row in observations:
        row["current"]["as_of"] = "2026-07-19T00:00:00Z"

    metric = m04.score_current_answer(fixture, observations)
    assert metric["correct_count"] == 0
    assert m04.score_conflict(fixture, observations, ablations)["passed"] is False


def test_current_answer_rejects_wrong_resolved_text_for_ordered_projection() -> None:
    fixture = m04.generate_fixture()
    observations, ablations = _perfect(fixture)
    target = next(
        row
        for row in observations
        if row["case_id"].split("-")[2] == "independent"
        and row["permutation"] == m04.PERMUTATIONS[0]
    )
    assert len(target["current"]["objects"]) > 1
    assert target["answer"]["answer_text"] == target["current"]["objects"][0]
    target["answer"]["answer_text"] = "wrong-but-nonempty"

    metric = m04.score_current_answer(fixture, observations)
    assert metric["correct_count"] == metric["total_count"] - 1
    assert metric["passed"] is False
    assert m04.score_conflict(fixture, observations, ablations)["passed"] is False


def test_unresolved_state_is_scored_by_multiplicity_not_by_status() -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    assert m04.score_unresolved_calibration(fixture, observations)["passed"] is True
    poisoned = copy.deepcopy(observations)
    poisoned[0]["current"]["status"] = "contested"
    with pytest.raises(m04.WmbsM04Error):
        m04.score_unresolved_calibration(fixture, poisoned)


@pytest.mark.parametrize("drift", ["objects", "as_of"])
def test_unresolved_calibration_rejects_fabricated_gold_projection(
    drift: str,
) -> None:
    fixture = m04.generate_fixture()
    observations, ablations = _perfect(fixture)
    target = next(row for row in observations if row["answer"]["abstained"])
    if drift == "objects":
        target["current"]["objects"] = ["fabricated-alpha", "fabricated-beta"]
    else:
        target["current"]["as_of"] = "2026-07-19T00:00:00Z"

    metric = m04.score_unresolved_calibration(fixture, observations)
    assert metric["correct_count"] == metric["total_count"] - 1
    assert metric["passed"] is False
    assert m04.score_conflict(fixture, observations, ablations)["passed"] is False


def test_wrong_confidences_do_not_claim_calibration_support() -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    for row in observations:
        row["answer"]["confidence"] = 0.0

    metric = m04.score_unresolved_calibration(fixture, observations)
    assert metric["passed"] is True
    assert metric["confidence_calibration"] == "unsupported"


def test_unresolved_projection_rejects_duplicate_current_objects() -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    unresolved = next(row for row in observations if row["answer"]["abstained"])
    alpha = unresolved["current"]["objects"][0]
    unresolved["current"]["objects"] = [alpha, alpha]

    with pytest.raises(m04.WmbsM04Error, match="objects must be unique strings"):
        m04.score_unresolved_calibration(fixture, observations)


def test_unresolved_calibration_rejects_false_positive_on_resolved_case() -> None:
    fixture = m04.generate_fixture()
    observations, ablations = _perfect(fixture)
    resolved = next(
        row
        for row in observations
        if not next(
            case for case in fixture["cases"] if case["case_id"] == row["case_id"]
        )["gold"]["unresolved"]
        and len(row["current"]["objects"]) == 1
    )
    resolved["current"]["objects"] = [
        *resolved["current"]["objects"],
        "spurious-conflict",
    ]
    resolved["answer"].update(answer_text=None, abstained=True)

    metric = m04.score_unresolved_calibration(fixture, observations)
    assert metric["total_count"] == 420
    assert metric["passed"] is False
    assert m04.score_conflict(fixture, observations, ablations)["passed"] is False


def test_answer_envelope_matches_closed_schema_contract() -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    nullable_confidence = copy.deepcopy(observations)
    nullable_confidence[0]["answer"]["confidence"] = None
    nullable_confidence[0]["answer"]["adapter_metadata"]["mode"] = "deterministic"
    m04.score_unresolved_calibration(fixture, nullable_confidence)
    for missing in (
        "answer_text",
        "abstained",
        "evidence_handles",
        "action_handles",
        "adapter_metadata",
    ):
        invalid = copy.deepcopy(observations)
        invalid[0]["answer"].pop(missing)
        with pytest.raises(m04.WmbsM04Error):
            m04.score_unresolved_calibration(fixture, invalid)
    invalid = copy.deepcopy(observations)
    invalid[0]["answer"]["action_handles"] = ["not-supported"]
    with pytest.raises(m04.WmbsM04Error):
        m04.score_unresolved_calibration(fixture, invalid)
    invalid = copy.deepcopy(observations)
    invalid[0]["answer"]["adapter_metadata"]["extra"] = "x"
    with pytest.raises(m04.WmbsM04Error):
        m04.score_unresolved_calibration(fixture, invalid)
    invalid = copy.deepcopy(observations)
    invalid[0]["answer"]["evidence_handles"] = ["duplicate", "duplicate"]
    with pytest.raises(m04.WmbsM04Error):
        m04.score_unresolved_calibration(fixture, invalid)


def test_adapter_metadata_allows_optional_mode() -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    observations[0]["answer"]["adapter_metadata"] = {}
    observations[1]["answer"]["adapter_metadata"] = {"mode": "x" * 256}

    m04.score_unresolved_calibration(fixture, observations)


@pytest.mark.parametrize("invalid_mode", [" \t", "x" * 257])
def test_adapter_metadata_mode_enforces_frozen_short_string(
    invalid_mode: str,
) -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    observations[0]["answer"]["adapter_metadata"] = {"mode": invalid_mode}

    with pytest.raises(m04.WmbsM04Error, match="short_string"):
        m04.score_unresolved_calibration(fixture, observations)


@pytest.mark.parametrize(
    "invalid_handle",
    ["contains space", "a" * 129, "-invalid-start", "_invalid-start"],
)
def test_evidence_handles_enforce_frozen_identifier_items(
    invalid_handle: str,
) -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    observations[0]["answer"]["evidence_handles"] = ["A.valid_1:/-handle"]
    m04.score_unresolved_calibration(fixture, observations)
    observations[0]["answer"]["evidence_handles"] = [invalid_handle]

    with pytest.raises(m04.WmbsM04Error, match="identifier schema"):
        m04.score_unresolved_calibration(fixture, observations)


def test_false_resolution_and_monotonic_violations_fail_closed() -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    unresolved = next(row for row in observations if row["answer"]["abstained"])
    unresolved["answer"].update(answer_text="guessed", abstained=False, confidence=0.99)
    unresolved["current"]["objects"] = ["guessed"]
    result = m04.score_false_supersession(fixture, observations)
    assert result["false_resolution_count"] == 1
    assert result["passed"] is False
    observations, _ = _perfect(fixture)
    observations[0]["monotonic_violation"] = True
    assert m04.score_false_supersession(fixture, observations)["passed"] is False


def test_permutation_invariance_and_clean_process_replay_equality() -> None:
    fixture = m04.generate_fixture()
    observations, _ = _perfect(fixture)
    result = m04.score_permutation_invariance(fixture, observations)
    assert result["rate"] == 1.0
    assert result["passed"] is True
    code = "from eval.public import wmbs_m04 as m; import sys; sys.stdout.buffer.write(m.canonical_json(m.generate_fixture()))"
    replay = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True
    ).stdout
    assert replay == m04.canonical_json(fixture)


def test_source_ablation_sensitivity_matches_gold() -> None:
    fixture = m04.generate_fixture()
    observations, ablations = _perfect(fixture)
    assert (
        m04.score_source_ablation_sensitivity(fixture, observations, ablations)[
            "passed"
        ]
        is True
    )
    ablations[0]["current"]["objects"] = ["wrong"]
    assert (
        m04.score_source_ablation_sensitivity(fixture, observations, ablations)[
            "passed"
        ]
        is False
    )


def test_source_ablation_sensitivity_rejects_wrong_current_as_of() -> None:
    fixture = m04.generate_fixture()
    observations, ablations = _perfect(fixture)
    ablations[0]["current"]["as_of"] = "2026-07-19T00:00:00Z"

    metric = m04.score_source_ablation_sensitivity(fixture, observations, ablations)
    assert metric["correct_count"] == metric["total_count"] - 1
    assert metric["passed"] is False


def test_unresolved_ablation_recomputes_remaining_source_support() -> None:
    fixture = m04.generate_fixture()
    observations, ablations = _perfect(fixture)
    case = next(
        case for case in fixture["cases"] if case["source_class"] == "unresolved"
    )
    alpha, beta = case["gold"]["current_objects"]
    expected = {
        "source-a": [beta],
        "source-b": [beta],
        "source-c": [alpha],
        "source-d": [alpha],
    }
    assert case["gold"]["ablation_objects"] == expected

    for row in ablations:
        if row["case_id"] == case["case_id"]:
            row["current"]["objects"] = expected[row["source_id"]]
    assert (
        m04.score_source_ablation_sensitivity(fixture, observations, ablations)[
            "passed"
        ]
        is True
    )

    ignored = next(
        row
        for row in ablations
        if row["case_id"] == case["case_id"] and row["source_id"] == "source-a"
    )
    ignored["current"]["objects"] = [alpha, beta]
    assert (
        m04.score_source_ablation_sensitivity(fixture, observations, ablations)[
            "passed"
        ]
        is False
    )


def test_scorer_emits_no_publication_or_measurement_claim() -> None:
    fixture = m04.generate_fixture()
    observations, ablations = _perfect(fixture)
    result = m04.score_conflict(fixture, observations, ablations)
    assert result["admission_state"] == "PROPOSED"
    assert result["evidence_level"] == "IMPLEMENTED"
    for key in (
        "publishable",
        "pbpp_headline_eligible",
        "headline_eligible",
        "independent_external_reproduction",
        "upstream_comparable",
    ):
        assert result[key] is False
    assert result["interval"] == {"method": "descriptive"}
    assert result["metrics"]["replay_equality"] == {
        "metric_id": "M04-REPLAY-EQ",
        "equal_count": 1,
        "total_count": 1,
        "rate": 1.0,
        "passed": True,
    }
    assert result["metrics"]["monotonic"] == {
        "metric_id": "M04-MONOTONIC",
        "violation_count": 0,
        "total_count": 420,
        "passed": True,
    }


def test_replay_equality_rejects_validation_legal_fixture_drift() -> None:
    fixture = m04.generate_fixture()
    fixture["cases"].reverse()
    _redigest(fixture)
    m04.validate_fixture(fixture)
    observations, ablations = _perfect(fixture)
    replay = m04.score_conflict(fixture, observations, ablations)["metrics"][
        "replay_equality"
    ]
    assert replay["equal_count"] == 0
    assert replay["rate"] == 0.0
    assert replay["passed"] is False


@pytest.mark.parametrize(
    "zero_denominator",
    ["unresolved", "non_unresolved", "historical", "ablations"],
)
def test_zero_denominator_gold_fails_closed(zero_denominator: str) -> None:
    fixture = m04.generate_fixture()
    for case in fixture["cases"]:
        if zero_denominator == "unresolved":
            case["gold"]["unresolved"] = False
        elif zero_denominator == "non_unresolved":
            case["gold"]["unresolved"] = True
            if len(case["gold"]["current_objects"]) == 1:
                case["gold"]["current_objects"].append(
                    f"{case['case_id']}-second-unresolved-object"
                )
        elif zero_denominator == "historical":
            case["gold"]["historical_objects"] = []
        else:
            case["gold"]["ablation_objects"] = {}
    _redigest(fixture)
    with pytest.raises(m04.WmbsM04Error, match="zero denominator"):
        m04.validate_fixture(fixture)


def test_branch_merge_and_transaction_time_are_declared_unsupported() -> None:
    fixture = m04.generate_fixture()
    assert fixture["disclosures"] == {
        "branch_merge": "UNSUPPORTED-BY-SYSTEM",
        "transaction_time": "unsupported",
        "update_hook": "emulated",
        "backends": {
            "local_json": "supported",
            "sqlite": "DEFERRED",
            "postgresql": "DEFERRED",
        },
    }
    invalid = copy.deepcopy(fixture)
    invalid["disclosures"]["transaction_time"] = "supported"
    with pytest.raises(m04.WmbsM04Error):
        m04.validate_fixture(invalid)
