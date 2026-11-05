"""Redacted, data-only reproductions for learning guard failures."""

from __future__ import annotations

import copy
from types import SimpleNamespace

from .guards import LearningGuardError, validate
from .receipts import digest

TEXT_FIELDS = {
    "content",
    "user_text",
    "query",
    "goal",
    "text",
    "evidence",
    "explanation",
    "quote",
}


def _redact(value, field=""):
    if isinstance(value, dict):
        return {
            key: _redact(item, key)
            for key, item in value.items()
            if key != "audit_keys"
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, field) for item in value]
    if isinstance(value, str) and field in TEXT_FIELDS:
        return "[redacted-" + digest(value)[:16] + "]"
    return copy.deepcopy(value)


def export(defect: dict, engine) -> dict:
    before = _redact(defect.get("before", {}))
    attempted = _redact(defect.get("attempted", {}))
    sources = {}
    for state in (before, attempted):
        for artifact in state.get("artifacts", {}).values():
            for quote in artifact.get("source_quotes", []):
                sources.setdefault(
                    quote["cid"], {"content": "", "erased": False, "actor": "tool"}
                )["content"] += quote["quote"] + "\n"
    return {
        "schema": "mnemosyne.learning-defect.v1",
        "engine": type(engine).__name__,
        "defect_id": defect["id"],
        "class": defect["class"],
        "operation": defect["operation"],
        "reproduction_seed": defect["reproduction_seed"],
        "before": before,
        "attempted": attempted,
        "sources": sources,
    }


def replay(bundle: dict) -> dict:
    if bundle.get("schema") != "mnemosyne.learning-defect.v1":
        raise ValueError("unsupported defect fixture schema")
    if not bundle.get("before") or not bundle.get("attempted"):
        raise ValueError("defect predates replayable state capture")
    sources = bundle.get("sources", {})
    try:
        validate(
            bundle["before"],
            bundle["attempted"],
            bundle["operation"],
            source_lookup=lambda cid: (
                SimpleNamespace(**sources[cid]) if cid in sources else None
            ),
        )
    except LearningGuardError as error:
        return {"passed": error.code == bundle["class"], "detected_class": error.code}
    return {"passed": False, "detected_class": None}
