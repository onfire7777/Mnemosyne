"""Privacy policy primitives: PII tags, residency, and erasure modes."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class ErasureMode(str, Enum):
    TOMBSTONE_RECOMPUTE = "tombstone_recompute"
    HARD_DELETE_LEGAL = "hard_delete_legal"


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b")
RESIDENCY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


@dataclass(slots=True)
class PrivacyClassification:
    pii_tags: list[str]
    residency: str
    erasure_mode: ErasureMode

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["erasure_mode"] = self.erasure_mode.value
        return data


def classify_privacy(text: str, residency: str = "local", legal_erasure: bool = False) -> PrivacyClassification:
    tags: list[str] = []
    if EMAIL_RE.search(text):
        tags.append("email")
    if PHONE_RE.search(text):
        tags.append("phone")
    return PrivacyClassification(
        pii_tags=tags,
        residency=residency,
        erasure_mode=ErasureMode.HARD_DELETE_LEGAL if legal_erasure else ErasureMode.TOMBSTONE_RECOMPUTE,
    )


def normalize_residency(value: str | None) -> str:
    if value is None:
        residency = "local"
    elif isinstance(value, str):
        residency = value.strip().lower()
    else:
        raise ValueError(f"invalid residency label: {value!r}")
    if not RESIDENCY_RE.fullmatch(residency):
        raise ValueError(f"invalid residency label: {value!r}")
    return residency


def enforce_residency(residency: str, allowed: tuple[str, ...]) -> None:
    normalized_allowed = tuple(normalize_residency(item) for item in allowed)
    if normalized_allowed and residency not in normalized_allowed:
        allowed_text = ", ".join(normalized_allowed)
        raise ValueError(f"residency {residency!r} is not allowed by this runtime; allowed: {allowed_text}")


def normalize_residency_transfer(value: str) -> tuple[str, str]:
    if "->" in value:
        source, target = value.split("->", 1)
    elif ":" in value:
        source, target = value.split(":", 1)
    else:
        raise ValueError(f"invalid residency transfer rule: {value!r}")
    return normalize_residency(source), normalize_residency(target)


def normalize_residency_transfers(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        f"{source}->{target}"
        for source, target in (normalize_residency_transfer(item) for item in values if item)
    )


def enforce_residency_transfer(
    source_residency: str,
    target_residency: str | None,
    allowed_transfers: tuple[str, ...],
) -> bool:
    if target_residency is None:
        return False
    source = normalize_residency(source_residency)
    target = normalize_residency(target_residency)
    if source == target:
        return False
    normalized_transfers = {normalize_residency_transfer(item) for item in allowed_transfers if item}
    if (source, target) not in normalized_transfers:
        allowed_text = ", ".join(f"{left}->{right}" for left, right in sorted(normalized_transfers)) or "none"
        raise ValueError(
            f"cross-region residency transfer {source!r}->{target!r} is not allowed by this runtime; "
            f"allowed transfers: {allowed_text}"
        )
    return True
