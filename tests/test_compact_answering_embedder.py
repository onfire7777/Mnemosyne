"""Focused tests for the versioned, model-free embedder ABI."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from eval.compact_answering.embedder_dev import (
    ABI_VERSION,
    NATIVE_DIMENSIONS,
    EmbedderIdentity,
    EmbedderValidationError,
    cosine_similarity,
    pad_native_to_1024,
    rank_by_cosine,
    validate_request,
    validate_response,
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
