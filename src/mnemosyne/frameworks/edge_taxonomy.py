"""
Edge taxonomy and validator for framework mindmap relations.

- Core relation types: canonical semantics for allowed types.
- Forbidden patterns: (from_type, to_type, edge_type) that get remapped (not dropped).
- Other relations: kept as-is so valid but unlisted relations are preserved.
"""

import logging
from typing import Any, Dict, List, Tuple

log = logging.getLogger(__name__)

# Core relation types used in prompts and validator. Other types from LLM are kept as-is.
# Rule 24 (v2): tension / opposes — opposing failure modes; undirected semantically (canonicalize in normalize_tension_edges).
CORE_RELATION_TYPES = (
    "supports",
    "implemented_by",
    "leads_to",
    "uses_definition",
    "constrains",
    "warns",
    "feeds_back_to",
    "refined_into",
    "exposes_problem_in",
    "drives_step",
    "tension",
    "tension_pair",
    "opposes",
)

TENSION_EDGE_TYPES = frozenset({"tension", "tension_pair", "opposes"})

# Forbidden patterns: (from_type, to_type, edge_type) -> (new_edge_type, flip_direction).
# flip_direction True means swap from_node_id and to_node_id.
FORBIDDEN_REMAP: Dict[Tuple[str, str, str], Tuple[str, bool]] = {
    # step -> step with implemented_by is sequential, not "implements"
    ("step", "step", "implemented_by"): ("leads_to", False),
    # warning/constraint -> step with supports: constraint limits step
    ("warning", "step", "supports"): ("constrains", False),
    ("constraint", "step", "supports"): ("constrains", False),
    # step -> warning/constraint with supports: wrong direction; constraint limits step
    ("step", "warning", "supports"): ("constrains", True),
    ("step", "constraint", "supports"): ("constrains", True),
    # definition -> step uses_definition: wrong direction; step uses definition
    ("definition", "step", "uses_definition"): ("uses_definition", True),
    # step -> constraint/warning with constrains: wrong direction; constraint/warning constrains step
    ("step", "constraint", "constrains"): ("constrains", True),
    ("step", "warning", "constrains"): ("warns", True),
    # Dependency builder historically emitted step -> warning/constraint; audit expects warning/constraint -> step
    ("step", "warning", "warns"): ("warns", True),
    # step -> case/example with supports: wrong direction; case/evidence supports step
    ("step", "case", "supports"): ("supports", True),
    ("step", "example", "supports"): ("supports", True),
    # principle/constraint -> case/example with supports: wrong direction; case supports claim
    ("principle", "case", "supports"): ("supports", True),
    ("principle", "example", "supports"): ("supports", True),
    ("constraint", "case", "supports"): ("supports", True),
    ("constraint", "example", "supports"): ("supports", True),
}


def _node_type(n: Dict[str, Any]) -> str:
    """Return normalized node type for taxonomy lookup."""
    t = (n.get("node_type") or n.get("type") or "section").strip().lower()
    return t if t else "section"


def validate_and_remap_edges(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Remap forbidden edge patterns; keep all other edges unchanged.

    Returns a new list of edges (may reuse same dicts with updated fields).
    """
    if not nodes:
        return list(edges)
    id_to_node: Dict[int, Dict[str, Any]] = {}
    for n in nodes:
        nid = n.get("id")
        if nid is not None:
            id_to_node[int(nid)] = n

    result: List[Dict[str, Any]] = []
    remapped_count = 0
    for e in edges:
        from_id = e.get("from_node_id")
        to_id = e.get("to_node_id")
        if from_id is None or to_id is None:
            continue
        try:
            from_id = int(from_id)
            to_id = int(to_id)
        except (TypeError, ValueError):
            continue
        from_node = id_to_node.get(from_id)
        to_node = id_to_node.get(to_id)
        if not from_node or not to_node:
            result.append(dict(e))
            continue
        from_type = _node_type(from_node)
        to_type = _node_type(to_node)
        edge_type = (e.get("edge_type") or "").strip().lower()
        key = (from_type, to_type, edge_type)
        action = FORBIDDEN_REMAP.get(key)
        if action:
            new_type, flip = action
            remapped_count += 1
            if flip:
                result.append({
                    "from_node_id": to_id,
                    "to_node_id": from_id,
                    "edge_type": new_type,
                    "why": e.get("why"),
                })
            else:
                result.append({
                    "from_node_id": from_id,
                    "to_node_id": to_id,
                    "edge_type": new_type,
                    "why": e.get("why"),
                })
        else:
            result.append(dict(e))

    if remapped_count:
        log.info("Edge taxonomy: remapped %s forbidden edge(s).", remapped_count)

    return result


def normalize_tension_edges(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rule 24: Tension is semantically undirected. Collapse A↔B duplicates to a single edge
    from min(id)→max(id) and merge `why` when both exist.
    Non-tension edges are preserved in order.
    """
    if not edges:
        return []
    tension_buckets: Dict[Tuple[int, int], Dict[str, Any]] = {}
    out: List[Dict[str, Any]] = []
    for e in edges:
        et = (e.get("edge_type") or "").strip().lower()
        if et not in TENSION_EDGE_TYPES:
            out.append(dict(e))
            continue
        try:
            a = int(e.get("from_node_id"))
            b = int(e.get("to_node_id"))
        except (TypeError, ValueError):
            out.append(dict(e))
            continue
        lo, hi = (a, b) if a <= b else (b, a)
        key = (lo, hi)
        why = (e.get("why") or "").strip()
        if key not in tension_buckets:
            ne = dict(e)
            ne["from_node_id"] = lo
            ne["to_node_id"] = hi
            ne["edge_type"] = "tension"
            ne["why"] = why[:500] if why else None
            tension_buckets[key] = ne
        else:
            w0 = (tension_buckets[key].get("why") or "").strip()
            if why and why not in w0:
                merged = f"{w0}; {why}".strip("; ") if w0 else why
                tension_buckets[key]["why"] = merged[:500]
    out.extend(tension_buckets.values())
    return out
