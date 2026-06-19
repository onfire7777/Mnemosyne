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


def bytes_cid(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

