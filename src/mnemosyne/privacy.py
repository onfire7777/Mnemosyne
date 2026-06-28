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
SSN_RE = re.compile(r"\b(?!000|666|9\d{2})\d{3}[- ](?!00)\d{2}[- ](?!0000)\d{4}\b")
PAYMENT_CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
DOB_RE = re.compile(
    r"\b(?:dob|date of birth|birthdate)\s*[:#-]?\s*"
    r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)
PASSPORT_RE = re.compile(r"\bpassport(?:\s+(?:no\.?|number|id))?\s*[:#-]?\s*[A-Z0-9]{6,9}\b", re.I)
STREET_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9][A-Za-z0-9 .'-]{1,60}\s+"
    r"(?:street|st\.?|avenue|ave\.?|road|rd\.?|boulevard|blvd\.?|lane|ln\.?|"
    r"drive|dr\.?|court|ct\.?|circle|cir\.?|way|parkway|pkwy\.?)\b",
    re.I,
)
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
    return PrivacyClassification(
        pii_tags=detect_pii_tags(text),
        residency=residency,
        erasure_mode=ErasureMode.HARD_DELETE_LEGAL if legal_erasure else ErasureMode.TOMBSTONE_RECOMPUTE,
    )


def detect_pii_tags(text: str) -> list[str]:
    tags: list[str] = []
    if EMAIL_RE.search(text):
        tags.append("email")
    if SSN_RE.search(text):
        tags.append("ssn")
    if PHONE_RE.search(text):
        tags.append("phone")
    if _contains_payment_card(text):
        tags.append("payment-card")
    if _contains_ipv4(text):
        tags.append("ip-address")
    if DOB_RE.search(text):
        tags.append("date-of-birth")
    if PASSPORT_RE.search(text):
        tags.append("passport")
    if STREET_ADDRESS_RE.search(text):
        tags.append("street-address")
    return tags


def redact_pii_text(text: str) -> str:
    redacted = EMAIL_RE.sub("[REDACTED:email]", text)
    redacted = SSN_RE.sub("[REDACTED:ssn]", redacted)
    redacted = _redact_payment_cards(redacted)
    redacted = PHONE_RE.sub("[REDACTED:phone]", redacted)
    redacted = _redact_ipv4(redacted)
    redacted = DOB_RE.sub("[REDACTED:date-of-birth]", redacted)
    redacted = PASSPORT_RE.sub("[REDACTED:passport]", redacted)
    redacted = STREET_ADDRESS_RE.sub("[REDACTED:street-address]", redacted)
    return redacted


def _contains_payment_card(text: str) -> bool:
    return any(_valid_payment_card(_digits(match.group(0))) for match in PAYMENT_CARD_CANDIDATE_RE.finditer(text))


def _redact_payment_cards(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        digits = _digits(match.group(0))
        if _valid_payment_card(digits):
            return "[REDACTED:payment-card]"
        return match.group(0)

    return PAYMENT_CARD_CANDIDATE_RE.sub(replace, text)


def _valid_payment_card(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    if len(set(digits)) < 2:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        value = int(char)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        checksum += value
    return checksum % 10 == 0


def _contains_ipv4(text: str) -> bool:
    return any(_valid_ipv4(match.group(0)) for match in IPV4_RE.finditer(text))


def _redact_ipv4(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        if _valid_ipv4(value):
            return "[REDACTED:ip-address]"
        return value

    return IPV4_RE.sub(replace, text)


def _valid_ipv4(value: str) -> bool:
    try:
        return all(0 <= int(part) <= 255 for part in value.split("."))
    except ValueError:
        return False


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


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
