"""Strict custody manifests for compact-answering parity evidence."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

SCHEMA = "mnemosyne.compact-answering-custody.v1"
IDENTITY_KINDS = frozenset({"code", "artifact", "configuration", "provider"})
_DIGEST = re.compile(r"[0-9a-f]{64}", re.ASCII)


class ManifestValidationError(ValueError):
    """The manifest is not the exact supported custody schema."""


class ManifestExistsError(FileExistsError):
    """An identical immutable manifest already exists at the target path."""


class ManifestDriftError(ManifestExistsError):
    """Existing custody differs from the requested or expected manifest."""


def validate_manifest(document: object) -> dict[str, Any]:
    """Validate and return a manifest using only the exact v1 schema."""
    if not isinstance(document, dict):
        raise ManifestValidationError("manifest must be a JSON object")
    if set(document) != {"schema", "identities"}:
        raise ManifestValidationError("manifest must contain only schema and identities")
    if document["schema"] != SCHEMA:
        raise ManifestValidationError(f"unsupported manifest schema: {document['schema']!r}")

    identities = document["identities"]
    if not isinstance(identities, dict):
        raise ManifestValidationError("identities must be a JSON object")
    if set(identities) != IDENTITY_KINDS:
        missing = sorted(IDENTITY_KINDS - set(identities))
        unsupported = sorted(set(identities) - IDENTITY_KINDS)
        raise ManifestValidationError(
            f"identity kinds must be exact; missing={missing}, unsupported={unsupported}"
        )

    for kind in sorted(IDENTITY_KINDS):
        identity = identities[kind]
        if not isinstance(identity, dict) or set(identity) != {"identity", "sha256"}:
            raise ManifestValidationError(
                f"{kind} identity must contain only identity and sha256"
            )
        name = identity["identity"]
        if not isinstance(name, str) or not name or name != name.strip():
            raise ManifestValidationError(f"{kind} identity must be a non-empty exact string")
        digest = identity["sha256"]
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise ManifestValidationError(f"{kind} sha256 must be 64 lowercase hex characters")

    return document


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_manifest(path: str | Path, *, expected: object | None = None) -> dict[str, Any]:
    """Load validated custody, optionally failing if it drifted from expected."""
    manifest_path = Path(path)
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestValidationError(f"cannot read valid manifest {manifest_path}") from exc
    validated = validate_manifest(document)
    if expected is not None:
        validated_expected = validate_manifest(expected)
        if _canonical_bytes(validated) != _canonical_bytes(validated_expected):
            raise ManifestDriftError(f"manifest drift detected at {manifest_path}")
    return validated


def create_manifest(path: str | Path, document: object) -> None:
    """Create immutable custody once; never replace an existing path."""
    validated = validate_manifest(document)
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_bytes(validated)

    try:
        descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        try:
            load_manifest(manifest_path, expected=validated)
        except ManifestDriftError:
            raise
        except ManifestValidationError as invalid:
            raise ManifestDriftError(
                f"existing manifest is invalid at {manifest_path}"
            ) from invalid
        raise ManifestExistsError(f"manifest already exists at {manifest_path}") from exc

    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        manifest_path.unlink(missing_ok=True)
        raise
