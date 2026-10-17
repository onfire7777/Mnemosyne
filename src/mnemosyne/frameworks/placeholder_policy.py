"""
Placeholder and gap-text normalization for definitive framework export (template + Feedback v2).

- Reference / link fields: omit visible lines when value is trivial or book-gap filler prose.
- Requires: show template **None** when no real prerequisite terms remain after filtering.
- Done When / Mitigation: use canonical acknowledged-gap sentences when missing or filler.
"""

from __future__ import annotations

import re
from typing import Any, List

from .field_completion_policy import (
    CONSTRAINT_MITIGATION_GAP_CANONICAL,
    DEFINITION_SOURCE_GAP_CANONICAL,
    OPERATIONAL_TEST_GAP_CANONICAL,
    STEP_DONE_WHEN_GAP_CANONICAL,
    is_template_acknowledged_gap_sentence,
)


def _ws(s: str) -> str:
    return " ".join((s or "").split()).strip()


def is_trivial_placeholder(s: str) -> bool:
    """Em dash, hyphen, n/a, empty — not valid content for template fields."""
    k = _ws(s).lower()
    if not k:
        return True
    if k in ("—", "-", "–", "n/a", "na", "tbd", "...", ".", "…", "none"):
        return True
    return False


def is_book_gap_filler_for_reference(s: str) -> bool:
    """
    Prose that must not appear in cross-reference fields (Highest risk at, Affects, Requires items, etc.).

    Canonical acknowledged-gap sentences (Done When, Mitigation, …) are excluded — they belong in prose fields only.
    """
    if is_template_acknowledged_gap_sentence(s):
        return False
    raw = _ws(s)
    if not raw:
        return True
    low = raw.lower()
    if low.startswith("the book does not"):
        return True
    if re.search(
        r"does not specify|not specified in (the )?(source|excerpt)|no .*provided excerpt",
        low,
    ):
        return True
    return False


def filter_reference_list_items(values: Any) -> List[str]:
    """List fields (Governed by, Watch for, …): drop trivial / gap filler strings."""
    if values is None:
        return []
    if isinstance(values, str):
        parts = [p.strip() for p in re.split(r"[;,]", values) if p.strip()]
        seq = parts if parts else ([values.strip()] if values.strip() else [])
    elif isinstance(values, list):
        seq = [str(x).strip() for x in values if str(x).strip()]
    else:
        seq = [str(values).strip()] if str(values).strip() else []
    out: List[str] = []
    for x in seq:
        if is_trivial_placeholder(x) or is_book_gap_filler_for_reference(x):
            continue
        out.append(x)
    return out


def format_requires_display(requires_raw: Any) -> str:
    """
    Template **Requires:** value: comma-separated terms, or literal None.
    """
    if requires_raw is None:
        return "None"
    if isinstance(requires_raw, list):
        terms = [str(x).strip() for x in requires_raw if str(x).strip()]
    elif isinstance(requires_raw, str):
        terms = [p.strip() for p in re.split(r"[;,]", requires_raw) if p.strip()]
        if not terms and requires_raw.strip():
            terms = [requires_raw.strip()]
    else:
        terms = [str(requires_raw).strip()] if str(requires_raw).strip() else []
    kept = [t for t in terms if not is_trivial_placeholder(t) and not is_book_gap_filler_for_reference(t)]
    return ", ".join(kept) if kept else "None"


def format_depends_on_display(raw: str, *, derived_step_label: str = "") -> str:
    """Template **Depends on:** None or Step N: …; strip gap filler; prefer graph-derived step label."""
    t = (raw or "").strip()
    if t and not is_trivial_placeholder(t) and not is_book_gap_filler_for_reference(t):
        return "None" if t.lower() == "none" else t
    d = (derived_step_label or "").strip()
    if d:
        return d
    return "None"


def effective_done_when(raw: str) -> str:
    if is_template_acknowledged_gap_sentence(raw):
        return _ws(str(raw))
    t = _ws(str(raw or ""))
    if not t or is_trivial_placeholder(t) or is_book_gap_filler_for_reference(t):
        return STEP_DONE_WHEN_GAP_CANONICAL
    return t


def effective_mitigation(raw: str) -> str:
    if is_template_acknowledged_gap_sentence(raw):
        return _ws(str(raw))
    t = _ws(str(raw or ""))
    if not t or is_trivial_placeholder(t) or is_book_gap_filler_for_reference(t):
        return CONSTRAINT_MITIGATION_GAP_CANONICAL
    return t


def effective_definition_source(raw: str) -> str:
    if is_template_acknowledged_gap_sentence(raw):
        return _ws(str(raw))
    t = _ws(str(raw or ""))
    if not t or is_trivial_placeholder(t):
        return DEFINITION_SOURCE_GAP_CANONICAL
    return t


def effective_operational_test(raw: str) -> str:
    if is_template_acknowledged_gap_sentence(raw):
        return _ws(str(raw))
    t = _ws(str(raw or ""))
    if not t or is_trivial_placeholder(t):
        return OPERATIONAL_TEST_GAP_CANONICAL
    return t


def should_omit_optional_prose_block(raw: str) -> bool:
    """Boundary, Argument Chain, Consequence, etc.: omit subsection when empty or filler-only."""
    t = _ws(str(raw or ""))
    if not t:
        return True
    if is_trivial_placeholder(t):
        return True
    if is_book_gap_filler_for_reference(t):
        return True
    return False


def should_omit_highest_risk_or_affects(raw: str) -> bool:
    t = _ws(str(raw or ""))
    if not t:
        return True
    if is_trivial_placeholder(t):
        return True
    if is_book_gap_filler_for_reference(t):
        return True
    return False


def in_practice_has_substance(ip: Any) -> bool:
    """Template: omit entire In Practice block if no case."""
    if not isinstance(ip, dict):
        return False
    keys = ("Case", "Context", "Action", "Outcome", "Lesson", "Tag")
    for k in keys:
        v = str(ip.get(k) or "").strip()
        if v and not is_trivial_placeholder(v):
            return True
    return False
