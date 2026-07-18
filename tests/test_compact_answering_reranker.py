from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

from eval.compact_answering.reranker_dev import (
    MAX_RANK_WIDTH,
    RerankCandidate,
    RerankIdentity,
    RerankScore,
    RerankerValidationError,
    RerankerSelectionValidationError,
    RerankerTimeoutError,
    fixture_digest,
    identity_digest,
    load_selection_fixture,
    parse_selection_fixture,
    rank_scores,
    run_synthetic_bakeoff,
    validate_bakeoff_receipt,
    validate_selection_fixture,
)

ROOT = Path(__file__).parents[1]
FIXTURE_PATH = ROOT / "eval" / "compact_answering" / "fixtures" / "reranker-train-dev.json"


@pytest.fixture
def fixture() -> dict[str, object]:
    return copy.deepcopy(load_selection_fixture())


def test_source_owned_fixture_is_train_only_and_deterministic() -> None:
    document = load_selection_fixture()

    assert document["split"] == "TRAIN"
    assert document["source"] == "source-owned"
    assert document["fixture_status"] == "synthetic-unmeasured"
    assert run_synthetic_bakeoff(document) == "synthetic-anchor-a"
    assert document["fixture_sha256"] == fixture_digest(document)

    candidates = document["candidates"]
    assert [candidate["evidence_id"] for candidate in candidates] == [
        "evidence-b",
        "evidence-a",
        "evidence-c",
    ]
    assert document["rank_width"] == 3


def test_receipts_bind_model_artifact_and_preprocessing_identity(fixture) -> None:
    for variant in fixture["variants"]:
        identity = variant["identity"]
        receipt = variant["receipt"]
        assert receipt["identity"] == identity
        assert receipt["identity_sha256"] == identity_digest(identity)
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
            expected_rank_width=fixture["rank_width"],
        )


def test_duplicate_unknown_and_nonfinite_payloads_fail_closed(fixture) -> None:
    payload = json.dumps(fixture)
    duplicate = payload.replace(
        '"schema": "mnemosyne.reranker-selection-fixture.v1"',
        '"schema": "mnemosyne.reranker-selection-fixture.v1", '
        '"schema": "mnemosyne.reranker-selection-fixture.v1"',
        1,
    )
    with pytest.raises(RerankerSelectionValidationError, match="duplicate"):
        parse_selection_fixture(duplicate)

    nonfinite = copy.deepcopy(fixture)
    nonfinite["variants"][0]["scores"][0]["score"] = float("nan")
    with pytest.raises(RerankerSelectionValidationError, match="finite|digest"):
        validate_selection_fixture(nonfinite)

    with pytest.raises(RerankerSelectionValidationError, match="unknown"):
        rank_scores(
            [RerankCandidate("evidence-a", "a")],
            [RerankScore("unknown", 1.0)],
            1,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("split", "validation", "TRAIN-only"),
        ("fixture_status", "measured", "unmeasured"),
        ("fixture_sha256", "0" * 64, "digest"),
    ],
)
def test_fixture_drift_and_unsupported_split_are_rejected(fixture, field, value, message) -> None:
    fixture[field] = value
    with pytest.raises(RerankerSelectionValidationError, match=message):
        validate_selection_fixture(fixture)


def test_identity_drift_and_receipt_digest_are_rejected(fixture) -> None:
    variant = fixture["variants"][0]
    drifted = copy.deepcopy(variant["identity"])
    drifted["preprocessing_id"] = "preprocess:other-v1"
    with pytest.raises(RerankerValidationError, match="identity mismatch"):
        validate_bakeoff_receipt(
            variant["receipt"], expected_identity=RerankIdentity.from_mapping(drifted)
        )

    tampered_receipt = copy.deepcopy(variant["receipt"])
    tampered_receipt["rank_width"] = 1
    with pytest.raises(RerankerSelectionValidationError, match="digest|rank width"):
        validate_bakeoff_receipt(tampered_receipt)


def test_ordering_duplicate_scores_and_rank_width_are_strict() -> None:
    candidates = [
        RerankCandidate("evidence-b", "b"),
        RerankCandidate("evidence-a", "a"),
        RerankCandidate("evidence-c", "c"),
    ]
    scores = [
        RerankScore("evidence-b", 0.5),
        RerankScore("evidence-c", 0.9),
        RerankScore("evidence-a", 0.5),
    ]
    assert [row.evidence_id for row in rank_scores(candidates, scores, 2)] == [
        "evidence-c",
        "evidence-a",
    ]

    with pytest.raises(RerankerSelectionValidationError, match="between"):
        rank_scores(candidates, scores, 0)
    with pytest.raises(RerankerSelectionValidationError, match="between"):
        rank_scores(candidates, scores, MAX_RANK_WIDTH + 1)
    with pytest.raises(RerankerSelectionValidationError, match="unique"):
        rank_scores(candidates, [scores[0], scores[0], scores[2]], 2)
    with pytest.raises(RerankerSelectionValidationError, match="finite"):
        rank_scores(candidates, [RerankScore("evidence-b", float("inf")), *scores[1:]], 2)


def test_timeout_is_fail_closed_without_model_execution(fixture) -> None:
    with pytest.raises(RerankerTimeoutError, match="timed out"):
        run_synthetic_bakeoff(fixture, deadline=time.monotonic() - 1)
    with pytest.raises(RerankerTimeoutError, match="positive"):
        run_synthetic_bakeoff(fixture, timeout_ms=0)
