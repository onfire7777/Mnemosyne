from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

import eval.public.runner as runner
from eval.public.adapters.beam import BeamDisclosureError, build_disclosure
from eval.public.runner import build_candidate_manifest

_REVISION = "0123456789abcdef0123456789abcdef01234567"
_PROTOCOL_ID = "beam-reader-v1"


def _manifest() -> dict[str, object]:
    return build_candidate_manifest(
        model_content_sha256=(
            "500a1f067a9f782620b40bee6f7b0c89e"
            "17ae61f686b92c24933e4ca4b2b8b41"
        ),
        git_sha="a" * 40,
        created_at_utc="2026-07-11T00:00:00Z",
    )


def _build(candidate_manifest: object) -> dict[str, object]:
    return build_disclosure(
        candidate_manifest,
        dataset_revision=_REVISION,
        protocol_id=_PROTOCOL_ID,
    )


def test_build_disclosure_emits_the_canonical_envelope() -> None:
    manifest = _manifest()

    disclosure = _build(manifest)

    assert disclosure == {
        "schema_version": "beam-reader-disclosure-v1",
        "dataset_revision": _REVISION,
        "protocol_id": _PROTOCOL_ID,
        "candidate_manifest": dict(sorted(manifest.items())),
    }
    assert list(disclosure) == [
        "schema_version",
        "dataset_revision",
        "protocol_id",
        "candidate_manifest",
    ]
    assert list(disclosure["candidate_manifest"]) == sorted(manifest)


def test_build_disclosure_is_deterministic_for_equivalent_candidate_mappings() -> None:
    manifest = _manifest()
    reversed_manifest = MappingProxyType(dict(reversed(manifest.items())))

    assert _build(manifest) == _build(reversed_manifest)


def test_build_disclosure_does_not_load_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    monkeypatch.setattr(runner, "ROOT", Path("/registry-must-not-be-read"))

    assert _build(manifest)["candidate_manifest"] == dict(sorted(manifest.items()))


def test_candidate_validation_rejects_an_explicit_empty_protocol() -> None:
    with pytest.raises(ValueError, match="frozen QA protocol"):
        runner.validate_candidate_manifest(_manifest(), {})


def test_canonical_protocol_returns_detached_nested_values() -> None:
    protocol = runner.canonical_qa_protocol()
    baseline = protocol["retrieval_baselines"]["hipporag-2wiki"]  # type: ignore[index]
    original = baseline["recall_at_2"]  # type: ignore[index]

    try:
        baseline["recall_at_2"] = 999  # type: ignore[index]
        assert (
            runner.canonical_qa_protocol()["retrieval_baselines"]["hipporag-2wiki"][
                "recall_at_2"
            ]
            == original
        )
        with pytest.raises(ValueError, match="retrieval baselines"):
            runner.validate_qa_protocol(protocol)
    finally:
        baseline["recall_at_2"] = original  # type: ignore[index]


def test_build_disclosure_detaches_nested_candidate_values() -> None:
    manifest = _manifest()
    disclosure = _build(manifest)

    manifest["evidence_budget"]["max_records"] = 0  # type: ignore[index]
    manifest["abstention"]["claims"].append("mutated")  # type: ignore[index,union-attr]

    assert disclosure["candidate_manifest"]["evidence_budget"]["max_records"] == 20  # type: ignore[index]
    assert disclosure["candidate_manifest"]["abstention"]["claims"] == []  # type: ignore[index]


def test_build_disclosure_validates_the_detached_candidate() -> None:
    class MutatingCopy(list[object]):
        def __deepcopy__(self, memo: dict[int, object]) -> list[object]:
            return ["mutated"]

    manifest = _manifest()
    manifest["abstention"]["claims"] = MutatingCopy()  # type: ignore[index]

    with pytest.raises(BeamDisclosureError):
        _build(manifest)


def test_build_disclosure_wraps_mapping_conversion_errors() -> None:
    class BrokenMapping(Mapping[str, object]):
        def __getitem__(self, key: str) -> object:
            raise RuntimeError("broken mapping")

        def __iter__(self) -> Iterator[str]:
            return iter(("candidate_version",))

        def __len__(self) -> int:
            return 1

    with pytest.raises(BeamDisclosureError):
        _build(BrokenMapping())


@pytest.mark.parametrize(
    ("dataset_revision", "protocol_id"),
    [
        ("0" * 39, _PROTOCOL_ID),
        ("0" * 41, _PROTOCOL_ID),
        ("A" * 40, _PROTOCOL_ID),
        (True, _PROTOCOL_ID),
        (_REVISION, ""),
        (_REVISION, f" {_PROTOCOL_ID}"),
        (_REVISION, f"{_PROTOCOL_ID} "),
        (_REVISION, True),
    ],
)
def test_build_disclosure_rejects_non_canonical_metadata(
    dataset_revision: object,
    protocol_id: object,
) -> None:
    with pytest.raises(BeamDisclosureError):
        build_disclosure(
            _manifest(),
            dataset_revision=dataset_revision,
            protocol_id=protocol_id,
        )


@pytest.mark.parametrize(
    "candidate_manifest",
    [
        None,
        [],
        {**_manifest(), "transport_retries": True},
        {**_manifest(), "transport_retries": math.nan},
        {key: value for key, value in _manifest().items() if key != "git_sha"},
        {**_manifest(), "extra": "not canonical"},
    ],
)
def test_build_disclosure_fails_closed_for_invalid_candidate_manifest(
    candidate_manifest: object,
) -> None:
    with pytest.raises(BeamDisclosureError):
        _build(candidate_manifest)
