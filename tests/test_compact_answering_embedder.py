"""Focused tests for the versioned, model-free embedder ABI."""

from __future__ import annotations

import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from eval.compact_answering.embedder_dev import (
    ABI_VERSION,
    NATIVE_DIMENSIONS,
    EmbedderIdentity,
    EmbedderSelectionValidationError,
    EmbedderValidationError,
    cosine_similarity,
    fixture_digest,
    load_selection_fixture,
    pad_native_to_1024,
    rank_by_cosine,
    select_synthetic_embedder,
    validate_bakeoff_receipt,
    validate_request,
    validate_response,
    validate_selection_fixture,
)

ROOT = Path(__file__).parents[1]
RUST_MODULE = ROOT / "services/answering-ort/src/embed.rs"


@pytest.fixture
def identity() -> EmbedderIdentity:
    return EmbedderIdentity(
        artifact="granite-r2@dev",
        tokenizer="tokenizer@dev",
        preprocessing="unicode-nfkc-lower-v1",
        model_space="native-768-zero-pad-1024-v1",
    )


def vector(first: float, second: float = 0.0) -> list[float]:
    values = [0.0] * NATIVE_DIMENSIONS
    values[0] = first
    values[1] = second
    return values


def request(identity: EmbedderIdentity) -> dict[str, object]:
    return {
        "abi_version": ABI_VERSION,
        "identity": identity.as_mapping(),
        "inputs": ["query"],
        "space": "native_768",
    }


def response(identity: EmbedderIdentity, values: list[list[float]]) -> dict[str, object]:
    return {
        "abi_version": ABI_VERSION,
        "identity": identity.as_mapping(),
        "vectors": values,
        "space": "native_768",
    }


def test_request_and_response_require_exact_custody(identity: EmbedderIdentity) -> None:
    parsed_request = validate_request(request(identity), identity)
    parsed_response = validate_response(response(identity, [vector(1.0)]), parsed_request, identity)
    assert parsed_response.vectors[0][0] == 1.0

    malformed = request(identity)
    malformed["unknown"] = True
    with pytest.raises(EmbedderValidationError):
        validate_request(malformed, identity)

    drifted = identity.as_mapping()
    drifted["tokenizer"] = "tokenizer@other"
    mismatched = request(identity)
    mismatched["identity"] = drifted
    with pytest.raises(EmbedderValidationError, match="tokenizer"):
        validate_request(mismatched, identity)


def test_vectors_reject_nonfinite_zero_and_bad_padding(identity: EmbedderIdentity) -> None:
    parsed_request = validate_request(request(identity), identity)
    with pytest.raises(EmbedderValidationError):
        validate_response(response(identity, [[0.0] * NATIVE_DIMENSIONS]), parsed_request, identity)

    nonfinite = vector(1.0)
    nonfinite[4] = float("inf")
    with pytest.raises(EmbedderValidationError):
        validate_response(response(identity, [nonfinite]), parsed_request, identity)

    padded_request = request(identity)
    padded_request["space"] = "padded_1024"
    parsed_padded_request = validate_request(padded_request, identity)
    padded = list(pad_native_to_1024(vector(1.0)))
    padded[-1] = 1.0
    padded_response = response(identity, [padded])
    padded_response["space"] = "padded_1024"
    with pytest.raises(EmbedderValidationError):
        validate_response(padded_response, parsed_padded_request, identity)


def test_native_and_padded_spaces_have_cosine_and_ranking_parity() -> None:
    query = vector(1.0, 2.0)
    candidate = vector(2.0, 1.0)
    padded_query = pad_native_to_1024(query)
    padded_candidate = pad_native_to_1024(candidate)
    assert cosine_similarity(query, candidate) == cosine_similarity(padded_query, padded_candidate)
    assert rank_by_cosine(query, [("b", candidate), ("a", candidate)]) == ["a", "b"]


def test_rust_module_unit_tests_pass_without_model_artifacts(tmp_path: Path) -> None:
    binary = tmp_path / "embed-tests"
    subprocess.run(
        ["rustc", "--edition=2021", "--test", str(RUST_MODULE), "-o", str(binary)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], cwd=ROOT, check=True, capture_output=True, text=True)


def _selection_fixture() -> dict[str, object]:
    return deepcopy(load_selection_fixture())


def test_synthetic_train_fixture_validates_and_selects_without_artifacts() -> None:
    fixture = load_selection_fixture()

    assert fixture["split"] == "TRAIN"
    assert fixture["fixture_status"] == "synthetic-unmeasured"
    assert select_synthetic_embedder(fixture) == "synthetic-anchor-a"
    assert fixture["selection"] == {
        "method": "mean_cosine_then_id_v1",
        "expected_candidate_id": "synthetic-anchor-a",
    }


def test_synthetic_fixture_rejects_malformed_top_level() -> None:
    fixture = _selection_fixture()
    del fixture["source"]

    with pytest.raises(EmbedderSelectionValidationError, match="fields must be exact"):
        validate_selection_fixture(fixture)


def test_synthetic_fixture_rejects_identity_mismatch() -> None:
    fixture = _selection_fixture()
    candidate = fixture["candidates"][0]
    receipt = candidate["receipt"]
    drifted = deepcopy(receipt["identity"])
    drifted["tokenizer"] = "synthetic-tokenizer-drifted-v1"
    receipt["identity"] = drifted

    with pytest.raises(EmbedderSelectionValidationError, match="identity mismatch"):
        validate_bakeoff_receipt(
            receipt,
            expected_candidate_id=candidate["id"],
            expected_identity=EmbedderIdentity.from_mapping(candidate["identity"]),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("coordinates", [[0, float("nan")]], "non-finite"),
        ("coordinates", [[0, 0.0]], "zero"),
    ],
)
def test_synthetic_fixture_rejects_nonfinite_and_zero_vectors(
    field: str, value: object, message: str
) -> None:
    fixture = _selection_fixture()
    query = fixture["probes"][0]["query"]["native_768"]
    query[field] = value

    with pytest.raises(EmbedderSelectionValidationError, match=message):
        validate_selection_fixture(fixture)


def test_synthetic_fixture_rejects_receipt_digest_mutation() -> None:
    fixture = _selection_fixture()
    receipt = fixture["candidates"][0]["receipt"]
    receipt["parity"]["ranking"] = False

    with pytest.raises(EmbedderSelectionValidationError, match="receipt parity"):
        validate_selection_fixture(fixture)


def test_synthetic_fixture_rejects_top_level_receipt_or_vector_drift() -> None:
    fixture = _selection_fixture()
    fixture["fixture_sha256"] = "0" * 64

    with pytest.raises(EmbedderSelectionValidationError, match="fixture digest"):
        validate_selection_fixture(fixture)


def test_synthetic_fixture_tie_break_is_candidate_id_deterministic() -> None:
    fixture = _selection_fixture()
    fixture["candidates"] = [
        fixture["candidates"][1],
        fixture["candidates"][0],
        fixture["candidates"][2],
    ]
    fixture["fixture_sha256"] = fixture_digest(fixture)

    validate_selection_fixture(fixture)
    assert select_synthetic_embedder(fixture) == "synthetic-anchor-a"
