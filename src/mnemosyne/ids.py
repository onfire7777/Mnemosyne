"""Stable identifiers and content addressing."""

from __future__ import annotations

import hashlib
import json
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
) -> str:
    """Content address evidence without making sensitive content a shared oracle."""

    metadata: dict[str, Any] = {
        "tenant_id": tenant_id,
        "source_type": source_type,
        "content_pointer": content_pointer,
        "modality": modality,
    }
    if int(sensitivity) >= 2 or _contains_detected_pii(content):
        metadata["subject_scope"] = "user"
        metadata["user_id"] = user_id
    return content_cid(content, metadata)


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
