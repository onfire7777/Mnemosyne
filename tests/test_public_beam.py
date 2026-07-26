from __future__ import annotations

import math

import pytest

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
    reversed_manifest = dict(reversed(manifest.items()))

    assert _build(manifest) == _build(reversed_manifest)


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
