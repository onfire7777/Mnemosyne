"""Stable identifiers and content addressing."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any


def new_id() -> str:
    return str(uuid.uuid4())


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_cid(content: str, metadata: dict[str, Any] | None = None) -> str:
    payload = {
        "content": content,
        "metadata": metadata or {},
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def evidence_cid(
    content: str,
    *,
    tenant_id: str,
    user_id: str,
    source_type: str,
    content_pointer: str | None,
    modality: str,
    sensitivity: int,
    document_segment_id: str | None = None,
) -> str:
    """Content address evidence without making sensitive content a shared oracle."""

    metadata: dict[str, Any] = {
        "tenant_id": tenant_id,
        "source_type": source_type,
        "content_pointer": content_pointer,
        "modality": modality,
    }
    segment_id = validate_document_segment_id(document_segment_id)
    if segment_id is not None:
        # Optional and versioned: legacy evidence retains its exact hash payload.
        # Document segments must never share custody across different owners.
        metadata["document_segment"] = {"version": 1, "id": segment_id}
    if segment_id is not None or int(sensitivity) >= 2 or _contains_detected_pii(content):
        metadata["subject_scope"] = "user"
        metadata["user_id"] = user_id
    return content_cid(content, metadata)


def validate_document_segment_id(value: str | None) -> str | None:
    """Validate an opaque, immutable segment-generation identifier.

    This is a storage identity, not a document path or user-facing title. Keeping
    it bounded and unambiguous also prevents accidentally embedding source text.
    """
    if value is not None and (
        type(value) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}", value) is None
    ):
        raise ValueError("document_segment_id must be 1-256 ASCII identifier characters")
    return value


def evidence_unscoped_cid(
    content: str,
    *,
    tenant_id: str,
    source_type: str,
    content_pointer: str | None,
    modality: str,
) -> str:
    """Legacy evidence CID without subject scoping, for replay collision checks."""

    return content_cid(
        content,
        {
            "tenant_id": tenant_id,
            "source_type": source_type,
            "content_pointer": content_pointer,
            "modality": modality,
        },
    )


def bytes_cid(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _contains_detected_pii(content: str) -> bool:
    # Local import keeps the generic ID helpers usable by privacy.py itself.
    from mnemosyne.privacy import detect_pii_tags

    return bool(detect_pii_tags(content))
