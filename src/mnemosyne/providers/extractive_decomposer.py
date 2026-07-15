"""Deterministic, source-bound hop-zero query decomposition."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Mapping

_ANCHOR_TOKEN = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*", re.UNICODE)
_CONTROL_LABELS = (
    re.compile(r"tenant(?:[\s_-]*ids?)\b", re.IGNORECASE),
    re.compile(r"user(?:[\s_-]*ids?)\b", re.IGNORECASE),
    re.compile(r"source(?:[\s_-]*identit(?:y|ies))\b", re.IGNORECASE),
    re.compile(r"auth(?:orization)?(?:[\s_-]*fields?)\b", re.IGNORECASE),
    re.compile(r"filter(?:[\s_-]*fields?)\b", re.IGNORECASE),
    re.compile(r"policy(?:[\s_-]*fields?)\b", re.IGNORECASE),
)
_DENY_TERMS = {
    "command", "commands", "ignore", "instruction", "instructions", "policy",
}
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does",
    "for", "from", "had", "has", "have", "how", "in", "is", "it", "of",
    "on", "or", "that", "the", "this", "to", "was", "were", "what", "when",
    "where", "which", "who", "why", "with",
}
_IDENTIFIER_MARKERS = {
    "account", "archive", "campaign", "case", "cluster", "initiative",
    "order", "program", "project", "repository", "service", "team",
    "ticket", "workspace",
}
_INTENT_TERMS = {
    "approve", "approved", "belong", "belongs", "did", "does", "find",
    "launch", "launched", "located", "open", "opened", "own", "owns", "responsible",
    "ship", "shipped", "store", "stored", "when", "where", "which", "who",
}
SELECTOR = "mnemosyne-extractive-hop0-v1"
SPEC = {
    "selector": SELECTOR,
    "scope": "hop-zero-only",
    "output": "at-most-one-exact-question-substring",
    "later_hops": "empty-provider-proposal; orchestrator-authorized-evidence-traversal",
    "identifier_markers": sorted(_IDENTIFIER_MARKERS),
    "intent_terms": sorted(_INTENT_TERMS),
    "deny_terms": sorted(_DENY_TERMS),
    "control_labels": "tenant/user/source-identity/auth/filter/policy fields",
    "normalization": "NFKC-casefold-for-comparison; raw-source-output",
}
SPEC_SHA256 = hashlib.sha256(
    json.dumps(SPEC, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


def implementation_sha256() -> str:
    """Bind the disclosed provider identity to the exact installed source bytes."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


CONTENT_SHA256 = implementation_sha256()
SERIALIZER_SPEC = {
    "encoding": "utf-8",
    "input_keys": ["evidence", "question"],
    "evidence_behavior": "nonempty-means-empty-query-list",
}
DECODING_SPEC = {"kind": "deterministic-extractive", "sampling": False}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def disclosure() -> dict[str, object]:
    """Return the legacy-shaped role disclosure with deterministic semantics."""
    return {
        "role": "query_decomposer",
        "model": SELECTOR,
        "model_content_digest": CONTENT_SHA256,
        "prompt_sha256": SPEC_SHA256,
        "serializer_sha256": _digest(SERIALIZER_SPEC),
        "decoding_options": DECODING_SPEC,
        "decoding_sha256": _digest(DECODING_SPEC),
    }


def _comparison(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _anchor_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        _comparison(re.sub(r"(?:['’]s)$", "", match.group(0), flags=re.IGNORECASE))
        for match in _ANCHOR_TOKEN.finditer(value)
    )


def _contains_control_label(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    return any(pattern.search(normalized) for pattern in _CONTROL_LABELS)


def _control_ranges(source: str) -> tuple[tuple[int, int], ...]:
    ranges = []
    for pattern in _CONTROL_LABELS:
        for match in pattern.finditer(source):
            value = _ANCHOR_TOKEN.search(source, match.end())
            ranges.append((match.start(), value.end() if value else match.end()))
    return tuple(ranges)


def _substantive(value: str) -> bool:
    return any(len(token) > 2 and token not in _STOPWORDS for token in _anchor_tokens(value))


def _entity_spans(source: str) -> tuple[str, ...]:
    if _contains_control_label(source):
        return ()
    words = list(_ANCHOR_TOKEN.finditer(source))
    control_ranges = _control_ranges(source)
    spans: list[str] = []
    start: int | None = None
    end = 0
    for match in words:
        raw = match.group(0)
        base = re.sub(r"(?:['’]s)$", "", raw, flags=re.IGNORECASE)
        letters = "".join(character for character in base if character.isalpha())
        terms = _anchor_tokens(base)
        entity_like = bool(letters) and any(
            len(term) > 2 and term not in _STOPWORDS for term in terms
        ) and (
            base[0].isupper()
            or letters.isupper()
            or (
                any(character.isupper() for character in letters[1:])
                and any(character.islower() for character in letters)
            )
            or (any(character.isdigit() for character in base) and any(character.isalpha() for character in base))
        )
        adjacent = start is not None and not source[end : match.start()].strip()
        if not entity_like or (start is not None and not adjacent):
            if start is not None and not any(
                left < end and start < right for left, right in control_ranges
            ):
                spans.append(source[start:end])
            start = None
        if entity_like:
            if start is None:
                start = match.start()
            end = match.end() - (len(raw) - len(base))
    if start is not None and not any(
        left < end and start < right for left, right in control_ranges
    ):
        spans.append(source[start:end])
    return tuple(anchor.strip() for anchor in spans if anchor.strip() and _substantive(anchor))


def extract_hop_zero_anchor(question: str) -> tuple[str, ...]:
    """Return at most one exact question span suitable for initial retrieval."""
    if (
        not question
        or _contains_control_label(question)
        or _DENY_TERMS.intersection(_anchor_tokens(question))
    ):
        return ()
    entities = _entity_spans(question)
    if entities:
        return (entities[0],)
    words = list(_ANCHOR_TOKEN.finditer(question))
    control_ranges = _control_ranges(question)

    def eligible(index: int) -> bool:
        match = words[index]
        token = _anchor_tokens(match.group(0))[0]
        return (
            _substantive(match.group(0))
            and token not in _DENY_TERMS
            and token not in _INTENT_TERMS
            and not any(
                left < match.end() and match.start() < right
                for left, right in control_ranges
            )
        )

    for index, match in enumerate(words[:-1]):
        if (
            _anchor_tokens(match.group(0))[0] in _IDENTIFIER_MARKERS
            and eligible(index)
            and eligible(index + 1)
        ):
            return (question[match.start() : words[index + 1].end()],)
    candidates = [
        words[index].group(0)
        for index in range(len(words))
        if eligible(index)
        and _anchor_tokens(words[index].group(0))[0] not in _IDENTIFIER_MARKERS
    ]
    if not candidates:
        return ()
    return (min(candidates, key=lambda value: (-len(value), question.index(value))),)


class ExtractiveQueryDecomposer:
    """Provider-shaped adapter; authorized evidence traversal stays in the orchestrator."""

    def decompose(self, payload: Mapping[str, object]) -> dict[str, list[str]]:
        if set(payload) != {"question", "evidence"}:
            raise ValueError("extractive decomposer payload is invalid")
        question = payload["question"]
        evidence = payload["evidence"]
        if not isinstance(question, str) or not isinstance(evidence, list):
            raise ValueError("extractive decomposer payload is invalid")
        if any(
            not isinstance(row, dict)
            or set(row) != {"cid", "content"}
            or not isinstance(row["cid"], str)
            or not row["cid"]
            or len(row["cid"]) > 512
            or not isinstance(row["content"], str)
            or not row["content"]
            for row in evidence
        ):
            raise ValueError("extractive decomposer payload is invalid")
        if evidence:
            return {"queries": []}
        return {"queries": list(extract_hop_zero_anchor(question))}
