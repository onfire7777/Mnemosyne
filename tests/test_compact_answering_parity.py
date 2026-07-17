from __future__ import annotations

import json
from copy import deepcopy

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
