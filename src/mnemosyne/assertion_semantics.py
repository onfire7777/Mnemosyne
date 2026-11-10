"""Cardinality and explicit replacement shared by assertion writers."""

from collections.abc import Mapping, Collection
import re
from typing import Any


# These describe members or events rather than a single current attribute.
# Other predicates retain the existing exclusive-attribute revision contract.
ADDITIVE_PREDICATES = frozenset({
    "is_a", "has_pet", "has_family", "has_child", "has_sibling", "education",
    "milestone", "expense", "likes", "dislikes", "prefers", "owns",
    "has_hobby", "has_interest", "speaks", "speaks_language", "knows",
    "allergic_to", "has_allergy", "like", "dislike", "prefer", "own",
    "speak", "know", "use", "uses",
    "has_project", "has_server", "has_repository", "has_service", "has_app",
    "has_application", "depends_on", "hosts", "supports", "requires",
    "plan_to", "intend_to", "committed_to", "promised_to", "decided_to",
    "believes",
})


# Predicate spellings are retained on the assertion; this key is only for
# semantic comparison. Negation belongs to a value, not an entire member set.
_PREDICATE_ALIASES = {
    "likes": "like", "prefers": "prefer", "owns": "own", "uses": "use",
    "speaks": "speak", "knows": "know", "live_in": "residence",
    "lives_in": "residence", "reside_in": "residence", "resides_in": "residence",
    "works_at": "work_at", "employed_by": "work_at", "works_for": "work_for",
    "has_allergy": "allergic_to",
}
_NEGATION = re.compile(
    r"^(?:(?:do|does|did|am|is|are|was|were)_)?"
    r"(?:not|never|no_longer)_"
)


def assertion_predicate_key(predicate: str) -> tuple[str, bool]:
    """Return the semantic attribute and explicit negative polarity."""
    normalized = re.sub(r"\s+", "_", predicate.strip().casefold())
    negative = bool(_NEGATION.match(normalized))
    normalized = _NEGATION.sub("", normalized)
    return _PREDICATE_ALIASES.get(normalized, normalized), negative


def assertion_is_additive(predicate: str) -> bool:
    normalized, negative = assertion_predicate_key(predicate)
    return negative or normalized in ADDITIVE_PREDICATES


def _field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, Mapping) else getattr(item, name)


def assertions_share_interval(left: Any, right: Any) -> bool:
    from mnemosyne.models import parse_dt

    for first, second in ((left, right), (right, left)):
        end = parse_dt(_field(first, "valid_to"))
        start = parse_dt(_field(second, "valid_from"))
        if end is not None and start is not None and end <= start:
            return False
    return True


def assertions_same_value(left: Any, right: Any) -> bool:
    return (
        assertion_predicate_key(_field(left, "predicate"))
        == assertion_predicate_key(_field(right, "predicate"))
        and _field(left, "object") == _field(right, "object")
        and assertions_share_interval(left, right)
    )


def assertions_conflict(left: Any, right: Any) -> bool:
    """Compare owned/same-scope peers without erasing unrelated values."""
    left_key, left_negative = assertion_predicate_key(_field(left, "predicate"))
    right_key, right_negative = assertion_predicate_key(_field(right, "predicate"))
    if left_key != right_key or not assertions_share_interval(left, right):
        return False
    same_object = _field(left, "object") == _field(right, "object")
    if left_negative != right_negative:
        return same_object
    return (
        not same_object and not left_negative
        and not assertion_is_additive(_field(left, "predicate"))
    )


def assertion_replacement_id(
    calibration: Mapping[str, Any], peer_ids: Collection[str],
    *, replayed_calibration: Mapping[str, Any] | None = None,
) -> str | None:
    """Validate an explicit replacement against the caller's owned peer group."""
    target = calibration.get("replaces_assertion_id")
    if target is None:
        return None
    if replayed_calibration is not None and replayed_calibration.get("replaces_assertion_id") == target:
        return None
    if not isinstance(target, str) or not target or target not in peer_ids:
        raise ValueError("replacement target must be an active assertion in the same owner and scope")
    return target
