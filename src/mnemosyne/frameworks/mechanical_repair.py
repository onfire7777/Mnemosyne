"""
Deterministic repairs for mechanical audit failures (PRE_PHASE4 Workstream A).

Mutates node dicts and edge lists in memory; caller persists via DB sync.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from . import mechanical_audit as _ma
from .edge_taxonomy import validate_and_remap_edges

log = logging.getLogger(__name__)

_REPAIRABLE_CHECKS = frozenset(
    {
        "warning_links_step",
        "constraint_links_step",
    }
)


def _nt(n: Dict[str, Any]) -> str:
    return (n.get("node_type") or n.get("type") or "").strip().lower()


def _steps(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = [n for n in nodes if _nt(n) == "step" and n.get("id") is not None]
    return sorted(out, key=lambda x: (x.get("sort_order", 0), x.get("id", 0)))


def _default_step_id(steps: List[Dict[str, Any]]) -> Any:
    return steps[0].get("id") if steps else None


def _hint_to_step_id(hint: str, steps: List[Dict[str, Any]]) -> Any:
    h = _ma._norm_ws(hint)
    if len(h) < 8 or "does not specify" in hint.lower() or "not specified" in hint.lower():
        return None
    for s in steps:
        raw = (s.get("title") or "").strip()
        variants = [
            _ma._norm_ws(raw),
            _ma._norm_ws(_ma._strip_type_prefixes(raw)),
        ]
        for v in variants:
            if len(v) >= 10 and (v in h or h in v):
                return s.get("id")
    return None


def _has_warns_or_constrains_edge(
    edges: List[Dict[str, Any]],
    wc_id: int,
    step_id: int,
    want: str,
) -> bool:
    for e in edges or []:
        try:
            a, b = int(e.get("from_node_id")), int(e.get("to_node_id"))
        except (TypeError, ValueError):
            continue
        if (e.get("edge_type") or "").strip().lower() != want:
            continue
        if a == wc_id and b == step_id:
            return True
    return False


def repair_warning_constraint_links(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> bool:
    """Set depends_on_node_id and add warns/constrains edges (warning|constraint -> step)."""
    steps = _steps(nodes)
    if not steps:
        return False
    changed = False

    for n in nodes:
        typ = _nt(n)
        if typ not in ("warning", "constraint"):
            continue
        nid = n.get("id")
        if nid is None:
            continue
        try:
            nid_i = int(nid)
        except (TypeError, ValueError):
            continue

        dep = n.get("depends_on_node_id")
        dep_step_ok = False
        if dep is not None:
            try:
                dep_i = int(dep)
            except (TypeError, ValueError):
                dep_i = None
            if dep_i is not None:
                dep_node = next((x for x in nodes if x.get("id") == dep_i), None)
                if dep_node and _nt(dep_node) == "step":
                    dep_step_ok = True

        etype = "warns" if typ == "warning" else "constrains"
        has_edge = False
        for e in edges:
            try:
                a = int(e.get("from_node_id"))
                b = int(e.get("to_node_id"))
            except (TypeError, ValueError):
                continue
            if a == nid_i and (e.get("edge_type") or "").strip().lower() == etype:
                to_n = next((x for x in nodes if x.get("id") == b), None)
                if to_n and _nt(to_n) == "step":
                    has_edge = True
                    break

        if dep_step_ok and has_edge:
            continue

        sid_i: Any = None
        if has_edge and not dep_step_ok:
            for e in edges:
                try:
                    a, b = int(e.get("from_node_id")), int(e.get("to_node_id"))
                except (TypeError, ValueError):
                    continue
                if a == nid_i and (e.get("edge_type") or "").strip().lower() == etype:
                    to_n = next((x for x in nodes if x.get("id") == b), None)
                    if to_n and _nt(to_n) == "step":
                        sid_i = b
                        break
        if sid_i is None:
            df = n.get("definitive_fields") if isinstance(n.get("definitive_fields"), dict) else {}
            hint = (df.get("Highest risk at") if typ == "warning" else df.get("Affects")) or ""
            sid = _hint_to_step_id(hint, steps) or _default_step_id(steps)
            if sid is None:
                continue
            try:
                sid_i = int(sid)
            except (TypeError, ValueError):
                continue

        n["depends_on_node_id"] = sid_i
        changed = True
        if not _has_warns_or_constrains_edge(edges, nid_i, sid_i, etype):
            edges.append(
                {
                    "from_node_id": nid_i,
                    "to_node_id": sid_i,
                    "edge_type": etype,
                    "why": "mechanical_repair:auto_link_step",
                }
            )
            changed = True

    return changed


def apply_mechanical_repairs_for_audit(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    audit: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """
    Apply repairs for failure check_ids we know how to fix. Re-run validate_and_remap_edges after edge edits.
    Returns (nodes, edges, changed).
    """
    failures = audit.get("failures") or []
    if not failures:
        return nodes, edges, False
    need = {f.get("check_id") for f in failures} & _REPAIRABLE_CHECKS
    if not need:
        return nodes, edges, False

    changed = False
    if need & {"warning_links_step", "constraint_links_step"}:
        changed = repair_warning_constraint_links(nodes, edges) or changed

    if changed:
        edges[:] = validate_and_remap_edges(nodes, list(edges))

    return nodes, edges, changed
