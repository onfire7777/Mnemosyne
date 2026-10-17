"""
Phase 0 (PHASE4_TARGETED_REPAIR_PLAN): graph metrics and stable hashes for debugging
the Phase 4 judgment / re-extract loop without changing pipeline behavior.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from .placeholder_policy import format_requires_display

log = logging.getLogger(__name__)


def _node_type(n: Dict[str, Any]) -> str:
    return (n.get("node_type") or n.get("type") or "section").strip().lower()


def definition_requires_display_is_empty(def_node: Dict[str, Any]) -> bool:
    """True when **Requires** would render as template literal `None`."""
    df = def_node.get("definitive_fields")
    if not isinstance(df, dict):
        return True
    return format_requires_display(df.get("Requires")) == "None"


def compute_graph_metrics(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Counts by node type, constraint total, definitions with empty Requires
    (for Phase 4 instrumentation).
    """
    by_type: Dict[str, int] = {}
    for n in nodes or []:
        t = _node_type(n)
        by_type[t] = by_type.get(t, 0) + 1

    definitions = [n for n in nodes or [] if _node_type(n) == "definition"]
    empty_req = sum(1 for n in definitions if definition_requires_display_is_empty(n))

    return {
        "node_total": len(nodes or []),
        "by_type": dict(sorted(by_type.items())),
        "constraint_count": by_type.get("constraint", 0),
        "definition_count": len(definitions),
        "definitions_empty_requires": empty_req,
    }


def hash_framework_snapshot(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> str:
    """
    Stable SHA-256 over minimal node/edge identity (ids, types, titles, sort_order, edge triples).
    For comparing passes before/after targeted repair (Phase 1+).
    """

    def norm_node(n: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": n.get("id"),
            "type": _node_type(n),
            "title": (n.get("title") or "").strip(),
            "sort_order": n.get("sort_order", 0),
        }

    def norm_edge(e: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "from": e.get("from_node_id"),
            "to": e.get("to_node_id"),
            "type": (e.get("edge_type") or "").strip().lower(),
        }

    sn = sorted(
        [norm_node(n) for n in nodes or []],
        key=lambda x: (x["id"] is None, x["id"] if x["id"] is not None else 0, x["sort_order"]),
    )
    se = sorted(
        [norm_edge(e) for e in edges or []],
        key=lambda x: (x["from"], x["to"], x["type"]),
    )
    payload = {"nodes": sn, "edges": se}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def summarize_judgment_notes(judgment: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """Counts per judgment note bucket (for log lines)."""
    if not judgment:
        return {}
    j = judgment
    keys = (
        "findings",
        "coverage_notes",
        "proportionality_notes",
        "epistemic_notes",
        "redundancy_notes",
        "self_test_notes",
    )
    out: Dict[str, int] = {}
    for k in keys:
        v = j.get(k)
        if isinstance(v, list):
            out[k] = len(v)
        else:
            out[k] = 0
    return out


def log_phase4_iteration_metrics(
    framework_id: int,
    iteration_index: int,
    max_iterations: int,
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    judgment: Optional[Dict[str, Any]] = None,
    *,
    tag: str = "",
) -> None:
    """
    Single INFO line + structured detail for debugging Phase 4 loops.
    """
    m = compute_graph_metrics(nodes)
    h = hash_framework_snapshot(nodes, edges)
    jn = summarize_judgment_notes(judgment)
    suffix = f" {tag}" if tag else ""

    log.info(
        "Phase 4 metrics [pass %s/%s] framework_id=%s graph_sha256_prefix=%s%s",
        iteration_index + 1,
        max_iterations,
        framework_id,
        h[:16],
        suffix,
    )
    log.info(
        "Phase 4 metrics detail: graph_sha256=%s nodes_by_type=%s constraint_count=%s definition_count=%s "
        "definitions_empty_requires=%s edge_count=%s judgment_note_counts=%s warrants_reextract=%s",
        h,
        m["by_type"],
        m["constraint_count"],
        m["definition_count"],
        m["definitions_empty_requires"],
        len(edges or []),
        jn,
        (judgment or {}).get("warrants_reextract"),
    )
