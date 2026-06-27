"""Shared byte limits for local and multimodal ingestion paths."""

from __future__ import annotations

import os


DEFAULT_MAX_INGEST_BYTES = 32 * 1024 * 1024


def validate_byte_limit(value: int, *, name: str = "max bytes") -> int:
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def enforce_byte_limit(payload: bytes, *, limit: int = DEFAULT_MAX_INGEST_BYTES, label: str = "payload") -> None:
    validate_byte_limit(limit, name=f"{label} limit")
    if len(payload) > limit:
        raise ValueError(f"{label} exceeds byte limit ({len(payload)} > {limit})")


def ensure_file_within_limit(path: str, *, limit: int = DEFAULT_MAX_INGEST_BYTES, label: str = "file") -> None:
    validate_byte_limit(limit, name=f"{label} limit")
    size = os.stat(path).st_size
    if size > limit:
        raise ValueError(f"{label} exceeds byte limit ({size} > {limit})")
