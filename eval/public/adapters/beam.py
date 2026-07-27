"""Source-only BEAM reader disclosure envelope."""

from __future__ import annotations

import re
from copy import deepcopy
from collections.abc import Mapping

from eval.public.runner import validate_candidate_manifest

_SCHEMA_VERSION = "beam-reader-disclosure-v1"
_REVISION = re.compile(r"[0-9a-f]{40}")


class BeamDisclosureError(ValueError):
    """The BEAM disclosure is not canonical."""


def build_disclosure(
    candidate_manifest: object,
    *,
    dataset_revision: object,
    protocol_id: object,
) -> dict[str, object]:
    """Build the canonical source-only BEAM reader disclosure."""
    if not isinstance(dataset_revision, str) or _REVISION.fullmatch(dataset_revision) is None:
        raise BeamDisclosureError("dataset revision must be exact lowercase 40-hex")
    if (
        not isinstance(protocol_id, str)
        or not protocol_id
        or protocol_id != protocol_id.strip()
    ):
        raise BeamDisclosureError("protocol identifier must be non-empty and canonical")
    if not isinstance(candidate_manifest, Mapping):
        raise BeamDisclosureError("candidate manifest must be a mapping")

    try:
        manifest = deepcopy(dict(candidate_manifest))
        validate_candidate_manifest(manifest)
        manifest = dict(sorted(manifest.items()))
    except Exception as exc:
        raise BeamDisclosureError("candidate manifest is invalid") from exc

    return {
        "schema_version": _SCHEMA_VERSION,
        "dataset_revision": dataset_revision,
        "protocol_id": protocol_id,
        "candidate_manifest": manifest,
    }
