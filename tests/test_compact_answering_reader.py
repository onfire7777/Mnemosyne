from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

from eval.compact_answering.reader_dev import (
    ABI_SCHEMA,
    MAX_REQUEST_BYTES,
    MAX_SUPPORTING_FACTS,
    ReaderIdentity,
    ReaderLogits,
    ReaderOffsetError,
    ReaderPrediction,
    ReaderRequest,
    ReaderTimeoutError,
    ReaderUnsupportedAnswerError,
    ReaderValidationError,
    build_windows,
    decode_prediction,
    decode_logits,
    fixture_digest,
    identity_digest,
    load_selection_fixture,
    parse_selection_fixture,
    parse_request,
    run_synthetic_bakeoff,
    validate_bakeoff_receipt,
    validate_prediction,
    validate_selection_fixture,
)

ROOT = Path(__file__).parents[1]
FIXTURE_PATH = ROOT / "eval" / "compact_answering" / "fixtures" / "reader-train-dev.json"
DIGEST = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def identity() -> ReaderIdentity:
    return ReaderIdentity(
        model_id="model:test-reader-v1",
        artifact_id="artifact:test-reader",
        artifact_sha256=DIGEST,
        preprocessing_id="preprocess:unicode-whitespace-v1",
        preprocessing_sha256=DIGEST,
    )


def request_for(context: str, query: str = "what is the answer?") -> ReaderRequest:
    windows = build_windows(context)
    encoded = context.encode("utf-8")
    return ReaderRequest.from_mapping(
        {
            "schema": ABI_SCHEMA,
            "identity": identity().as_mapping(),
            "query": query,
            "context": context,
            "facts": [
                {
                    "fact_id": "fact-1",
                    "raw_start": 0,
                    "raw_end": len(encoded),
                    "text": context,
                }
            ],
            "windows": [window.as_mapping() for window in windows],
            "null_threshold": 0.5,
        }
    )


def prediction_for(
    request: ReaderRequest,
    *,
    answer_type: str,
    window_index: int = 0,
    start_token: int | None = None,
    end_token: int | None = None,
    null_margin: float = 0.0,
    score: float = 1.0,
) -> ReaderPrediction:
    window = request.windows[window_index]
    raw_start = raw_end = None
    if answer_type == "span":
        assert start_token is not None and end_token is not None
        raw_start = window.tokens[start_token].raw_start
        raw_end = window.tokens[end_token - 1].raw_end
    return ReaderPrediction(
        schema=ABI_SCHEMA,
        identity=request.identity,
        window_id=window.window_id,
        answer_type=answer_type,
        start_token=start_token,
        end_token=end_token,
        raw_start=raw_start,
        raw_end=raw_end,
        supporting_facts=("fact-1",),
        null_margin=null_margin,
        score=score,
    )


@pytest.fixture
def fixture() -> dict[str, object]:
    return copy.deepcopy(load_selection_fixture())


def test_source_owned_fixture_is_train_only_and_deterministic() -> None:
    document = load_selection_fixture()

    assert document["split"] == "TRAIN"
    assert document["source"] == "source-owned"
    assert document["fixture_status"] == "synthetic-unmeasured"
    assert document["artifact_custody"] == "synthetic-fixture-no-model-artifact"
    assert run_synthetic_bakeoff(document) == "reader-dev-challenger"
    assert document["fixture_sha256"] == fixture_digest(document)
    assert len(document["cases"]) == 7
    assert document["cases"][0]["context"] == "The café is open today."
    assert document["cases"][5]["window_count"] == 2
    assert document["cases"][6]["window_count"] == 2


def test_receipts_bind_identity_and_leave_measurements_unclaimed(fixture) -> None:
    fixture_identity = fixture["identity"]
    assert fixture["identity_sha256"] == identity_digest(fixture_identity)
    for variant in fixture["variants"]:
        identity_value = ReaderIdentity.from_mapping(variant["identity"])
        receipt = variant["receipt"]
        assert receipt["identity"] == variant["identity"]
        assert receipt["identity_sha256"] == identity_digest(identity_value)
        assert receipt["status"] == "unmeasured"
        assert receipt["unmeasured"] == [
            "artifact_bytes",
            "quality",
            "latency_ms",
            "peak_memory_mib",
            "resource_envelope",
        ]
        validate_bakeoff_receipt(
            receipt,
            expected_candidate_id=variant["id"],
            expected_identity=identity_value,
        )


def test_unicode_repeated_and_window_boundary_spans_reconstruct_exact_text(fixture) -> None:
    unicode_request = request_for("The café is open today.")
    unicode_prediction = prediction_for(
        unicode_request, answer_type="span", start_token=1, end_token=2
    )
    unicode_answer = decode_prediction(unicode_request, unicode_prediction)
    assert unicode_answer.answer == "café"
    assert unicode_answer.raw_start == len("The ".encode())
    assert unicode_answer.raw_end == len("The café".encode())

    repeated_request = request_for("The token appears and the token appears again.")
    repeated_prediction = prediction_for(
        repeated_request, answer_type="span", start_token=5, end_token=6
    )
    assert decode_prediction(repeated_request, repeated_prediction).answer == "token"

    boundary_context = " ".join(
        "edge" if index == 511 else f"t{index:03d}" for index in range(513)
    )
    boundary_request = request_for(boundary_context)
    assert len(boundary_request.windows) == 2
    boundary_prediction = prediction_for(
        boundary_request,
        answer_type="span",
        window_index=1,
        start_token=510,
        end_token=511,
    )
    assert decode_prediction(boundary_request, boundary_prediction).answer == "edge"


@pytest.mark.parametrize("answer_type", ["yes", "no"])
def test_yes_no_answers_have_no_span_offsets(answer_type: str) -> None:
    request = request_for("The launch is enabled.")
    prediction = prediction_for(request, answer_type=answer_type)
    answer = decode_prediction(request, prediction)
    assert answer.answer == answer_type
    assert answer.raw_start is None
    assert answer.raw_end is None


def test_null_margin_abstains_and_rejects_disagreement() -> None:
    request = request_for("No document confirms the answer.")
    null_prediction = prediction_for(request, answer_type="null", null_margin=0.75)
    assert decode_prediction(request, null_prediction).abstained is True

    disagreeing = copy.copy(null_prediction)
    disagreeing = ReaderPrediction(**{**disagreeing.__dict__, "null_margin": 0.25})
    with pytest.raises(ReaderValidationError, match="null margin"):
        validate_prediction(request, disagreeing)


def test_duplicate_nonfinite_and_unsupported_payloads_fail_closed(fixture) -> None:
    payload = FIXTURE_PATH.read_text()
    duplicate = payload.replace(
        '"schema": "mnemosyne.reader-selection-fixture.v1"',
        '"schema": "mnemosyne.reader-selection-fixture.v1", "schema": "mnemosyne.reader-selection-fixture.v1"',
        1,
    )
    with pytest.raises(ReaderValidationError, match="duplicate"):
        parse_selection_fixture(duplicate)

    nonfinite = copy.deepcopy(fixture)
    nonfinite["variants"][0]["case_scores"][0] = float("nan")
    with pytest.raises(ReaderValidationError, match="finite|digest"):
        validate_selection_fixture(nonfinite)

    unsupported = prediction_for(
        request_for("A source sentence."), answer_type="span", start_token=0, end_token=1
    )
    unsupported = ReaderPrediction(**{**unsupported.__dict__, "answer_type": "long_form"})
    with pytest.raises(ReaderUnsupportedAnswerError, match="unsupported"):
        validate_prediction(request_for("A source sentence."), unsupported)


def test_drifted_split_identity_offsets_and_digests_are_rejected(fixture) -> None:
    drifted = copy.deepcopy(fixture)
    drifted["split"] = "VALIDATION"
    with pytest.raises(ReaderValidationError, match="TRAIN-only"):
        validate_selection_fixture(drifted)

    receipt = copy.deepcopy(fixture["variants"][0]["receipt"])
    receipt["identity"]["preprocessing_id"] = "preprocess:drifted"
    with pytest.raises(ReaderValidationError, match="identity digest|identity mismatch"):
        validate_bakeoff_receipt(receipt)

    tampered = copy.deepcopy(fixture)
    tampered["fixture_sha256"] = "0" * 64
    with pytest.raises(ReaderValidationError, match="digest"):
        validate_selection_fixture(tampered)

    request = request_for("The café is open.")
    prediction = prediction_for(request, answer_type="span", start_token=1, end_token=2)
    bad_offsets = ReaderPrediction(**{**prediction.__dict__, "raw_start": prediction.raw_start + 1})
    with pytest.raises(ReaderOffsetError, match="raw offsets"):
        validate_prediction(request, bad_offsets)


def test_timeout_is_fail_closed_before_fixture_admission(fixture) -> None:
    with pytest.raises(ReaderTimeoutError, match="timed out"):
        run_synthetic_bakeoff(fixture, deadline=time.monotonic() - 1)
    with pytest.raises(ReaderTimeoutError, match="positive finite"):
        run_synthetic_bakeoff(fixture, timeout_ms=0)
    with pytest.raises(ReaderTimeoutError, match="finite"):
        run_synthetic_bakeoff(fixture, deadline=float("nan"))


def test_logits_shape_and_finiteness_are_checked() -> None:
    request = request_for("The answer is Paris.")
    window = request.windows[0]
    logits = {
        "schema": ABI_SCHEMA,
        "identity": request.identity.as_mapping(),
        "window_id": window.window_id,
        "start_logits": [0.0, 0.0, 0.0, 2.0],
        "end_logits": [0.0, 0.0, 0.0, 2.0],
        "answer_type_logits": {"span": 2.0, "yes": 0.0, "no": 0.0},
        "supporting_fact_logits": [1.0],
        "null_logit": -1.0,
    }
    answer = decode_logits(request, ReaderLogits.from_mapping(logits))
    assert answer.answer_type == "span"
    assert decode_prediction(request, answer).answer == "Paris."

    malformed = copy.deepcopy(logits)
    malformed["start_logits"] = [0.0]
    with pytest.raises(ReaderValidationError, match="shape"):
        decode_logits(request, ReaderLogits.from_mapping(malformed))


def test_reader_parser_enforces_request_byte_limit() -> None:
    request = request_for("The answer is Paris.")
    parsed = parse_request(json.dumps(request.as_mapping()).encode())
    assert parsed.query == request.query
    with pytest.raises(ReaderValidationError, match="byte limit"):
        parse_request(b" " * (MAX_REQUEST_BYTES + 1))


def test_logits_ties_are_stable_and_derived_nonfinite_scores_fail_closed() -> None:
    request = request_for("The answer is Paris.")
    window = request.windows[0]
    tied = {
        "schema": ABI_SCHEMA,
        "identity": request.identity.as_mapping(),
        "window_id": window.window_id,
        "start_logits": [0.0] * len(window.tokens),
        "end_logits": [0.0] * len(window.tokens),
        "answer_type_logits": {"span": 0.0, "yes": 0.0, "no": 0.0},
        "supporting_fact_logits": [0.0],
        "null_logit": -1.0,
    }
    assert decode_logits(request, ReaderLogits.from_mapping(tied)).answer_type == "span"

    overflowing = copy.deepcopy(tied)
    overflowing["start_logits"] = [3.4e38] * len(window.tokens)
    overflowing["end_logits"] = [3.4e38] * len(window.tokens)
    with pytest.raises(ReaderValidationError, match="finite|fit in f32"):
        decode_logits(request, ReaderLogits.from_mapping(overflowing))


def test_direct_prediction_validation_rejects_malformed_types_and_controls() -> None:
    request = request_for("The answer is Paris.")
    prediction = prediction_for(request, answer_type="yes")
    for field, value in (("window_id", []), ("answer_type", []), ("score", float("nan"))):
        malformed = ReaderPrediction(**{**prediction.__dict__, field: value})
        with pytest.raises(ReaderValidationError):
            validate_prediction(request, malformed)

    with pytest.raises(ReaderValidationError, match="query"):
        request_for("The answer is Paris.", query="what\u0085is it?")


def test_decode_logits_rejects_too_many_supporting_facts() -> None:
    context = "x"
    request_mapping = request_for(context).as_mapping()
    request_mapping["facts"] = [
        {"fact_id": f"fact-{index}", "raw_start": 0, "raw_end": 1, "text": context}
        for index in range(MAX_SUPPORTING_FACTS + 1)
    ]
    request = ReaderRequest.from_mapping(request_mapping)
    window = request.windows[0]
    logits = ReaderLogits.from_mapping(
        {
            "schema": ABI_SCHEMA,
            "identity": request.identity.as_mapping(),
            "window_id": window.window_id,
            "start_logits": [0.0],
            "end_logits": [0.0],
            "answer_type_logits": {"span": 0.0, "yes": 0.0, "no": 0.0},
            "supporting_fact_logits": [1.0] * len(request.facts),
            "null_logit": -1.0,
        }
    )
    with pytest.raises(ReaderValidationError, match="supporting_facts"):
        decode_logits(request, logits)
