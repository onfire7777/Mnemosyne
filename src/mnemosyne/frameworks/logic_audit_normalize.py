"""
Single source of truth for Logic Auditor JSON shape (graph vs logic vs hybrid buckets).

graph_warnings are not used (always []); graph structure is reported only via graph_critical_issues.

Persisted audit_result dicts always include split lists and legacy critical_issues / warnings
(concatenation) so older code paths keep working.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _str_list(val: Any) -> List[str]:
    if not isinstance(val, list):
        return []
    out: List[str] = []
    for x in val:
        s = str(x).strip() if x is not None else ""
        if s:
            out.append(s[:4000])
    return out


def normalize_logic_audit_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize LLM or legacy payload into canonical audit_result.

    - New shape: graph_*, logic_*, hybrid_* issue lists.
    - Legacy: only critical_issues / warnings -> treated as logic-only (preserves old approval semantics).
    - approved: True only when there are no logic or hybrid *critical* issues (graph-only criticals
      do not block approval; they are addressed via graph repair when enabled).
    - approved_graph: True when no graph or hybrid critical issues.
    """
    if not isinstance(data, dict):
        data = {}

    gc = _str_list(data.get("graph_critical_issues"))
    lc = _str_list(data.get("logic_critical_issues"))
    lw = _str_list(data.get("logic_warnings"))
    hc = _str_list(data.get("hybrid_critical_issues"))
    hw = _str_list(data.get("hybrid_warnings"))
    # graph_warnings are not surfaced (UI/repair); ignore persisted values
    gw: List[str] = []

    legacy_critical = _str_list(data.get("critical_issues"))
    legacy_warnings = _str_list(data.get("warnings"))
    has_split = bool(gc or lc or lw or hc or hw)

    if not has_split and (legacy_critical or legacy_warnings):
        lc = legacy_critical
        lw = legacy_warnings
        legacy_mode = True
    else:
        legacy_mode = False

    approved_graph = len(gc) + len(hc) == 0
    if legacy_mode:
        approved_logic = bool(data.get("approved", False))
        approved = approved_logic
    else:
        approved_logic = len(lc) + len(hc) == 0
        approved = approved_logic

    critical_issues = gc + lc + hc
    warnings = lw + hw

    note = data.get("reasoning_quality_note")
    if note is not None and not isinstance(note, str):
        note = None

    out: Dict[str, Any] = {
        "graph_critical_issues": gc,
        "graph_warnings": gw,
        "logic_critical_issues": lc,
        "logic_warnings": lw,
        "hybrid_critical_issues": hc,
        "hybrid_warnings": hw,
        "approved": approved,
        "approved_logic": approved_logic,
        "approved_graph": approved_graph,
        "critical_issues": critical_issues,
        "warnings": warnings,
    }
    if note and str(note).strip():
        out["reasoning_quality_note"] = str(note).strip()[:2000]
    return out


def prepare_audit_result_for_ui(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize buckets for display; preserve phase4 and graph_repair attachments."""
    if not raw or not isinstance(raw, dict):
        return {}
    a = dict(raw)
    p4 = a.pop("phase4", None)
    gr = a.pop("graph_repair", None)
    out = normalize_logic_audit_result(a)
    if p4 is not None:
        out["phase4"] = p4
    if gr is not None:
        out["graph_repair"] = gr
    return out
