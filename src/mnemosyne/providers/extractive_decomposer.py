"""Deterministic, source-bound hop-zero query decomposition."""

from __future__ import annotations

from typing import Mapping, Sequence

from mnemosyne.answering import (
    _ANCHOR_TOKEN,
    _FALLBACK_DENY_TERMS,
    _anchor_tokens,
    _contains_control_label,
    _control_ranges,
    _entity_spans,
    _substantive,
)


_IDENTIFIER_MARKERS = {
    "account", "archive", "campaign", "case", "cluster", "initiative",
    "order", "program", "project", "repository", "service", "team",
    "ticket", "workspace",
}
_INTENT_TERMS = {
    "approve", "approved", "belong", "belongs", "did", "does", "find",
    "launch", "launched", "located", "open", "opened", "responsible",
    "ship", "shipped", "store", "stored", "when", "where", "which", "who",
}


def extract_hop_zero_anchor(question: str) -> tuple[str, ...]:
    """Return at most one exact question span suitable for initial retrieval."""
    if (
        not question
        or _contains_control_label(question)
        or _FALLBACK_DENY_TERMS.intersection(_anchor_tokens(question))
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
            and token not in _FALLBACK_DENY_TERMS
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
        if not isinstance(question, str) or not isinstance(evidence, Sequence) or isinstance(evidence, str):
            raise ValueError("extractive decomposer payload is invalid")
        if evidence:
            return {"queries": []}
        return {"queries": list(extract_hop_zero_anchor(question))}
