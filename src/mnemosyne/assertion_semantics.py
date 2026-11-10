"""Cardinality and explicit replacement shared by assertion writers."""

from collections.abc import Mapping, Collection
import re
from typing import Any


# These describe members or events rather than a single current attribute.
# Other predicates retain the existing exclusive-attribute revision contract.
ADDITIVE_PREDICATES = frozenset({
    "has_pet", "has_family", "has_child", "has_sibling", "education",
    "milestone", "expense", "likes", "dislikes", "prefers", "owns",
    "has_hobby", "has_interest", "speaks", "speaks_language", "knows",
    "allergic_to", "has_allergy", "like", "dislike", "prefer", "own",
    "speak", "know", "use", "uses",
})


def assertion_is_additive(predicate: str) -> bool:
    normalized = predicate.strip().casefold().replace(" ", "_")
    normalized = re.sub(
        r"^(?:(?:do|does|did|can|could|will|would|should|must|have|has|had)_)?(?:not|never)_",
        "", normalized,
    )
    return normalized in ADDITIVE_PREDICATES


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
