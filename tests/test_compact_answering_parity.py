from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from eval.compact_answering.manifest import (
    SCHEMA,
    ManifestDriftError,
    ManifestExistsError,
    ManifestValidationError,
    create_manifest,
    load_manifest,
    validate_manifest,
)
from eval.compact_answering.parity import (
    ParityMismatchError,
    ParityValidationError,
    compare_parity_rows,
    parse_parity_row,
)

FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "eval"
    / "compact_answering"
    / "fixtures"
    / "synthetic-parity.json"
)


@pytest.fixture
def manifest() -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "identities": {
            kind: {"identity": f"{kind}:pinned-v1", "sha256": character * 64}
            for kind, character in zip(
                ("code", "artifact", "configuration", "provider"),
                "abcd",
                strict=True,
            )
        },
    }


def test_manifest_round_trip_is_canonical_and_private(tmp_path, manifest) -> None:
    path = tmp_path / "custody.json"

    create_manifest(path, manifest)

    assert load_manifest(path, expected=manifest) == manifest
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text(encoding="utf-8") == (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )


@pytest.mark.parametrize("missing", ["code", "artifact", "configuration", "provider"])
def test_manifest_rejects_missing_identity(manifest, missing) -> None:
    del manifest["identities"][missing]

    with pytest.raises(ManifestValidationError, match="missing"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    ("digest", "identity"),
    [
        ("a" * 63, "code:pinned-v1"),
        ("A" * 64, "code:pinned-v1"),
        ("g" * 64, "code:pinned-v1"),
        ("a" * 64, ""),
        ("a" * 64, " code:pinned-v1"),
    ],
)
def test_manifest_rejects_malformed_identity(manifest, digest, identity) -> None:
    manifest["identities"]["code"] = {"identity": identity, "sha256": digest}

    with pytest.raises(ManifestValidationError):
        validate_manifest(manifest)


def test_manifest_rejects_unsupported_schema_identity_and_fields(manifest) -> None:
    unsupported_schema = {**manifest, "schema": "mnemosyne.unknown.v1"}
    unsupported_identity = deepcopy(manifest)
    unsupported_identity["identities"]["runtime"] = {
        "identity": "runtime:v1",
        "sha256": "e" * 64,
    }
    unsupported_field = {**manifest, "created_at": "mutable"}

    for document in (unsupported_schema, unsupported_identity, unsupported_field):
        with pytest.raises(ManifestValidationError):
            validate_manifest(document)


def test_manifest_detects_expected_identity_drift(tmp_path, manifest) -> None:
    path = tmp_path / "custody.json"
    create_manifest(path, manifest)
    drifted = deepcopy(manifest)
    drifted["identities"]["provider"]["sha256"] = "e" * 64

    with pytest.raises(ManifestDriftError, match="drift"):
        load_manifest(path, expected=drifted)


def test_manifest_rejects_identical_overwrite(tmp_path, manifest) -> None:
    path = tmp_path / "custody.json"
    create_manifest(path, manifest)

    with pytest.raises(ManifestExistsError, match="already exists"):
        create_manifest(path, manifest)


def test_manifest_rejects_drifted_and_malformed_overwrite(tmp_path, manifest) -> None:
    path = tmp_path / "custody.json"
    create_manifest(path, manifest)
    drifted = deepcopy(manifest)
    drifted["identities"]["artifact"]["identity"] = "artifact:other"

    with pytest.raises(ManifestDriftError, match="drift"):
        create_manifest(path, drifted)

    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ManifestDriftError, match="invalid"):
        create_manifest(path, manifest)


def test_manifest_rejects_duplicate_json_keys(tmp_path, manifest) -> None:
    path = tmp_path / "custody.json"
    payload = json.dumps(manifest).replace(
        '"schema": "mnemosyne.compact-answering-custody.v1"',
        '"schema": "mnemosyne.compact-answering-custody.v1", '
        '"schema": "mnemosyne.compact-answering-custody.v1"',
        1,
    )
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ManifestValidationError, match="duplicate"):
        load_manifest(path)


def test_manifest_creation_is_exclusive_under_concurrency(tmp_path, manifest) -> None:
    path = tmp_path / "custody.json"
    barrier = threading.Barrier(2)

    def create_once() -> type[BaseException] | None:
        barrier.wait()
        try:
            create_manifest(path, manifest)
        except BaseException as exc:  # capture the losing creator for exact assertion
            return type(exc)
        return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create_once(), range(2)))

    assert sorted(result.__name__ if result else "success" for result in results) == [
        "ManifestExistsError",
        "success",
    ]
    assert load_manifest(path, expected=manifest) == manifest


def test_manifest_removes_partial_file_when_fsync_fails(tmp_path, manifest, monkeypatch) -> None:
    path = tmp_path / "custody.json"

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("injected fsync failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="injected"):
        create_manifest(path, manifest)

    assert not path.exists()


@pytest.fixture
def parity_row() -> dict[str, object]:
    return {
        "decoded_span_b64": "ZXhhY3Q=",
        "answer_type": "span",
        "supporting_facts": [
            {"source_id": "doc-a", "sentence_index": 1},
            {"source_id": "doc-b", "sentence_index": 0},
        ],
        "null_margin": -1.5,
        "abstained": False,
    }


def test_parity_row_decodes_exact_bytes_and_preserves_fact_order(parity_row) -> None:
    parsed = parse_parity_row(parity_row)

    assert parsed.decoded_span_bytes == b"exact"
    assert [(fact.source_id, fact.sentence_index) for fact in parsed.supporting_facts] == [
        ("doc-a", 1),
        ("doc-b", 0),
    ]
    compare_parity_rows(parity_row, deepcopy(parity_row))


@pytest.mark.parametrize(
    ("answer_type", "decoded_span_b64", "abstained"),
    [
        ("span", "ZXhhY3Q=", False),
        ("yes", "eWVz", False),
        ("no", "bm8=", False),
        ("span", "", True),
    ],
)
def test_parity_accepts_canonical_answer_states(
    parity_row, answer_type, decoded_span_b64, abstained
) -> None:
    parity_row.update(
        {
            "answer_type": answer_type,
            "decoded_span_b64": decoded_span_b64,
            "abstained": abstained,
        }
    )

    parse_parity_row(parity_row)


@pytest.mark.parametrize(
    ("field", "replacement", "error_field"),
    [
        ("decoded_span_b64", "RVhBQ1Q=", "decoded_span_bytes"),
        ("answer_type", "yes", "answer_type"),
        (
            "supporting_facts",
            [
                {"source_id": "doc-b", "sentence_index": 0},
                {"source_id": "doc-a", "sentence_index": 1},
            ],
            "supporting_facts",
        ),
        ("null_margin", -1.5000000000000002, "null_margin"),
        ("abstained", True, "abstained"),
    ],
)
def test_parity_rejects_every_mismatched_field(
    parity_row, field, replacement, error_field
) -> None:
    candidate = deepcopy(parity_row)
    candidate[field] = replacement
    if field == "answer_type":
        candidate["decoded_span_b64"] = "eWVz"
    elif field == "abstained":
        candidate["decoded_span_b64"] = ""

    with pytest.raises(ParityMismatchError, match=error_field):
        compare_parity_rows(parity_row, candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.pop("answer_type"),
        lambda row: row.update({"extra": "unsupported"}),
        lambda row: row.update({"decoded_span_b64": "not base64"}),
        lambda row: row.update({"answer_type": "free-form"}),
        lambda row: row.update({"supporting_facts": "doc-a:1"}),
        lambda row: row.update(
            {"supporting_facts": [{"source_id": "doc-a", "sentence_index": True}]}
        ),
        lambda row: row.update({"null_margin": 1}),
        lambda row: row.update({"null_margin": float("nan")}),
        lambda row: row.update({"abstained": 0}),
        lambda row: row.update({"answer_type": "null", "decoded_span_b64": ""}),
        lambda row: row.update({"abstained": True}),
        lambda row: row.update({"decoded_span_b64": ""}),
        lambda row: row.update({"answer_type": "yes"}),
        lambda row: row.update({"answer_type": "no"}),
    ],
)
def test_parity_fails_closed_on_malformed_rows(parity_row, mutation) -> None:
    malformed = deepcopy(parity_row)
    mutation(malformed)

    with pytest.raises(ParityValidationError):
        compare_parity_rows(parity_row, malformed)


def test_synthetic_fixture_covers_required_edges_and_mismatch() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["schema"] == "mnemosyne.compact-answering-parity-fixture.v1"
    cases = {case["id"]: case for case in fixture["cases"]}
    assert set(cases) == {
        "unicode",
        "repeated-answer",
        "null-answer",
        "window-boundary",
        "multi-window-reconstruction",
        "explicit-mismatch",
    }
    assert {case["input"]["token_length"] for case in cases.values()} == {
        64,
        128,
        384,
        512,
    }

    for case in cases.values():
        fixture_input = case["input"]
        source = fixture_input["source_utf8"].encode("utf-8")
        segments = fixture_input["answer_byte_segments"]
        windows = fixture_input["windows"]
        assert len(segments) == len(windows)
        reconstructed = b""
        for (start, end), (window_start, window_end) in zip(
            segments, windows, strict=True
        ):
            assert 0 <= window_start <= start <= end <= window_end <= len(source)
            reconstructed += source[start:end]

        reference = parse_parity_row(case["reference"])
        if reference.abstained:
            assert segments == []
            assert reference.decoded_span_bytes == b""
        else:
            assert reconstructed == reference.decoded_span_bytes

        if case["id"] == "repeated-answer":
            occurrence = fixture_input["selected_occurrence"]
            assert fixture_input["occurrences"][occurrence] == segments[0]
            assert len(fixture_input["occurrences"]) > 1
        elif case["id"] == "window-boundary":
            assert segments[0][1] == windows[0][1]
        elif case["id"] == "multi-window-reconstruction":
            assert len(segments) > 1

        if case["matches"]:
            compare_parity_rows(case["reference"], case["candidate"])
        else:
            with pytest.raises(ParityMismatchError):
                compare_parity_rows(case["reference"], case["candidate"])
