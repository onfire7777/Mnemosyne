"""
Phase 3: Mechanical audit blockers (Definitive System Feedback v2, Section K).

Deterministic checks on nodes, edges, and definitive markdown. Results are stored on the framework
row and surfaced consistently in the UI and in DOCX export (banner + Quality panel).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from .field_completion_policy import (
    definition_fields_satisfy_policy,
    step_action_done_when_satisfy_policy,
    warning_symptoms_satisfy_policy,
)

log = logging.getLogger(__name__)

# v2 §K / Rule 6: near-duplicate source quotes (token-set Jaccard above this => failure).
SOURCE_QUOTE_DUPLICATE_JACCARD_THRESHOLD = 0.50

# Governs field phrases that reference the whole method (no per-step title required).
_GOVERNS_GLOBAL_PHRASES = re.compile(
    r"\ball\s+steps\b|\bevery\s+step\b|\bthe\s+framework\b|\bentire\s+framework\b|"
    r"\bwhole\s+method\b|\ball\s+step\b",
    re.IGNORECASE,
)

# Patterns that indicate forbidden meta-commentary about framework structure (Rule 8).
_STRUCTURAL_DISCLAIMER_PATTERNS = re.compile(
    r"this framework has|categorization issues|structural issues with (this |the )?framework|"
    r"framework\'?s? own structural|quality of (this |the )?extraction",
    re.IGNORECASE,
)


def _norm_ws(s: str) -> str:
    return " ".join((s or "").split()).strip().lower()


def _token_set(s: str) -> Set[str]:
    return {t for t in re.findall(r"[a-z0-9']+", _norm_ws(s)) if len(t) > 1}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _parse_page_number(page_ref: Any) -> Optional[int]:
    if page_ref is None:
        return None
    s = str(page_ref).strip()
    if not s:
        return None
    m = re.search(r"\b(\d{1,4})\b", s)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _node_type(n: Dict[str, Any]) -> str:
    return (n.get("node_type") or n.get("type") or "").strip().lower()


def _get_source_quote(n: Dict[str, Any]) -> Tuple[str, str]:
    df = n.get("definitive_fields")
    if not isinstance(df, dict):
        return "", ""
    sq = df.get("Source Quote")
    if not isinstance(sq, dict):
        return "", ""
    q = (sq.get("Quote") or "").strip()
    pr = (n.get("page_ref") or "").strip()
    return q, pr


def _failure(check_id: str, message: str, detail: str = "") -> Dict[str, Any]:
    return {"check_id": check_id, "message": message, "detail": detail or ""}


def _warning(check_id: str, message: str, detail: str = "") -> Dict[str, Any]:
    """Non-blocking audit item (does not set passed=False)."""
    return {"check_id": check_id, "message": message, "detail": detail or "", "severity": "info"}


def _shared_passage_duplicate_definitions(n1: Dict[str, Any], n2: Dict[str, Any]) -> bool:
    """
    Case B: distinct definitions on the same page often share one excerpt (co-mentioned terms).
    These are reported as warnings, not failures, so they do not block Phase 4 re-extract.
    """
    if _node_type(n1) != "definition" or _node_type(n2) != "definition":
        return False
    p1 = _parse_page_number(n1.get("page_ref"))
    p2 = _parse_page_number(n2.get("page_ref"))
    if p1 is None or p2 is None or p1 != p2:
        return False
    return True


def _strip_type_prefixes(title: str) -> str:
    s = (title or "").strip()
    s = re.sub(r"^step\s*\d+\s*:\s*", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"^(warning|constraint|principle)\s*:\s*", "", s, flags=re.IGNORECASE).strip()
    return s


def _strip_balance_outer_parens(s: str) -> str:
    """Strip wrapping parentheses e.g. '(Pivot)' -> 'Pivot' for cross-ref matching."""
    t = (s or "").strip()
    while len(t) >= 2 and t.startswith("(") and t.endswith(")"):
        inner = t[1:-1].strip()
        if not inner:
            break
        t = inner
    return t


def _norm_title_key(title: str) -> str:
    return _norm_ws(_strip_type_prefixes(title))


def _node_titles_index(nodes: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    """Map normalized title keys to node ids (multiple ids allowed for rare collisions)."""
    out: Dict[str, List[int]] = {}
    for n in nodes or []:
        nid = n.get("id")
        if nid is None:
            continue
        try:
            nid_i = int(nid)
        except (TypeError, ValueError):
            continue
        raw = (n.get("title") or "").strip()
        for key in {_norm_title_key(raw), _norm_ws(raw)}:
            if len(key) < 2:
                continue
            out.setdefault(key, []).append(nid_i)
    return out


def _short_reference_exact_match(text: str, title_index: Dict[str, List[int]]) -> bool:
    """
    Match short cross-reference fragments (e.g. 'Pivot', '(Pivot)') to indexed node titles
    using the same normalization as node titles. Avoids false negatives from min-length gates.
    """
    raw = _strip_balance_outer_parens((text or "").strip())
    if len(raw) < 1:
        return False
    keys = {
        _norm_title_key(raw),
        _norm_ws(raw),
        _norm_ws(_strip_type_prefixes(raw)),
    }
    for k in keys:
        if len(k) >= 2 and k in title_index:
            return True
    return False


def _text_matches_any_node_title(text: str, title_index: Dict[str, List[int]], min_len: int = 10) -> bool:
    if _short_reference_exact_match(text, title_index):
        return True
    t = (text or "").strip()
    if len(t) < min_len:
        return False
    keys = {_norm_title_key(t), _norm_ws(t), _norm_ws(_strip_type_prefixes(t))}
    for k in keys:
        if len(k) >= min_len and k in title_index:
            return True
    # Containment: longest node title key contained in text
    tlow = _norm_ws(t)
    for nk, ids in title_index.items():
        if len(nk) >= min_len and nk in tlow:
            return True
    return False


def _step_depends_on_resolves(
    dep: str,
    full_title_index: Dict[str, List[int]],
    definition_title_index: Dict[str, List[int]],
) -> bool:
    """
    Step 'Depends on' usually references a definition (short term like 'Pivot').
    Try definition titles first with exact short match, then full graph match + fuzzy rules.
    """
    if _short_reference_exact_match(dep, definition_title_index):
        return True
    return _text_matches_any_node_title(dep, full_title_index, min_len=8)


def _split_reference_fragments(s: str) -> List[str]:
    """Split 'Step 1: A, Step 2: B' or 'A; B' into candidate title fragments."""
    if not (s or "").strip():
        return []
    parts = re.split(r"[,;]|\band\b", s, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) >= 6]


def _check_cross_reference_fields(
    nodes: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
) -> None:
    """v2 §K / Rule 7: structured cross-refs should name real nodes (best-effort fuzzy match)."""
    nodes_list = nodes or []
    title_index = _node_titles_index(nodes_list)
    definition_title_index = _node_titles_index(
        [n for n in nodes_list if _node_type(n) == "definition"]
    )
    for n in nodes_list:
        nt = _node_type(n)
        df = n.get("definitive_fields")
        if not isinstance(df, dict):
            continue
        title_short = (n.get("title") or "")[:70]

        if nt == "warning":
            hr = (df.get("Highest risk at") or "").strip()
            if hr and "does not specify" not in hr.lower() and not _text_matches_any_node_title(
                hr, title_index, min_len=8
            ):
                failures.append(
                    _failure(
                        "cross_reference_fields",
                        f'Warning "{title_short}" Highest risk at does not match a known node title.',
                        hr[:120],
                    )
                )
        elif nt == "constraint":
            aff = (df.get("Affects") or "").strip()
            if aff and "not specified" not in aff.lower() and not _text_matches_any_node_title(
                aff, title_index, min_len=8
            ):
                failures.append(
                    _failure(
                        "cross_reference_fields",
                        f'Constraint "{title_short}" Affects does not match a known node title.',
                        aff[:120],
                    )
                )
        elif nt == "principle":
            gov = (df.get("Governs") or "").strip()
            if not gov or _GOVERNS_GLOBAL_PHRASES.search(gov):
                continue
            # Only strict-check when Governs looks like it cites numbered steps (ambiguous short phrases skipped).
            if not re.search(r"\bstep\s*\d+\b", gov, re.IGNORECASE):
                continue
            ok = False
            for frag in _split_reference_fragments(gov):
                if _text_matches_any_node_title(frag, title_index, min_len=6):
                    ok = True
                    break
            if not ok:
                failures.append(
                    _failure(
                        "cross_reference_fields",
                        f'Principle "{title_short}" Governs cites steps that do not match known node titles.',
                        gov[:120],
                    )
                )
        elif nt == "step":
            dep = (df.get("Depends on") or "").strip()
            if not dep or "does not specify" in dep.lower():
                continue
            if not _step_depends_on_resolves(dep, title_index, definition_title_index):
                failures.append(
                    _failure(
                        "cross_reference_fields",
                        f'Step "{title_short}" Depends on does not match a known node title.',
                        dep[:120],
                    )
                )


def _nonempty_str(v: Any, min_len: int = 1) -> bool:
    return isinstance(v, str) and len(v.strip()) >= min_len


def _check_required_definitive_fields(
    nodes: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
) -> None:
    """v2 §F / §E: required keys present (Symptoms, Mitigation, Done When, etc.)."""
    for n in nodes or []:
        nt = _node_type(n)
        df = n.get("definitive_fields")
        if not isinstance(df, dict):
            df = {}
        tid = (n.get("title") or "")[:70]

        if nt == "warning":
            if not warning_symptoms_satisfy_policy(df):
                failures.append(
                    _failure(
                        "required_definitive_fields",
                        f'Warning "{tid}" must include Symptoms: 2–4 observable strings, or one acknowledged-gap '
                        f"string per FIELD_COMPLETION_POLICY / field_completion_policy.py (v2 Rule 21).",
                        "",
                    )
                )
            if not _nonempty_str(df.get("Highest risk at"), 5):
                failures.append(
                    _failure(
                        "required_definitive_fields",
                        f'Warning "{tid}" must include Highest risk at.',
                        "",
                    )
                )
        elif nt == "constraint":
            mit = df.get("Mitigation")
            if not _nonempty_str(mit, 8):
                failures.append(
                    _failure(
                        "required_definitive_fields",
                        f'Constraint "{tid}" must include Mitigation (or the book-does-not-provide phrase).',
                        "",
                    )
                )
            if not _nonempty_str(df.get("Affects"), 5):
                failures.append(
                    _failure(
                        "required_definitive_fields",
                        f'Constraint "{tid}" must include Affects.',
                        "",
                    )
                )
        elif nt == "step":
            if not step_action_done_when_satisfy_policy(df):
                failures.append(
                    _failure(
                        "required_definitive_fields",
                        f'Step "{tid}" must include Action and Done When (≥8 chars or canonical gap per Rules 17–19).',
                        "",
                    )
                )
        elif nt == "definition":
            if not definition_fields_satisfy_policy(df):
                failures.append(
                    _failure(
                        "required_definitive_fields",
                        f'Definition "{tid}" must include Definition Source and Operational Test (Rules 14–16 / field_completion_policy).',
                        "",
                    )
                )


def _check_definition_requires_order(
    nodes: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
) -> None:
    """Rule 2: Requires[] should name definitions that appear earlier in render order."""
    defs = sorted(
        [n for n in (nodes or []) if _node_type(n) == "definition"],
        key=lambda x: (x.get("sort_order", 0), x.get("id", 0)),
    )
    pos_by_key: Dict[str, int] = {}
    for i, d in enumerate(defs):
        k = _norm_title_key(d.get("title") or "")
        if len(k) >= 2:
            pos_by_key[k] = i

    for i, d in enumerate(defs):
        df = d.get("definitive_fields")
        if not isinstance(df, dict):
            continue
        req = df.get("Requires")
        if not isinstance(req, list):
            continue
        dt = (d.get("title") or "")[:60]
        for r in req:
            if not _nonempty_str(r, 2):
                continue
            rk = _norm_title_key(str(r))
            if rk in ("none", "n/a", ""):
                continue
            pi = pos_by_key.get(rk)
            if pi is None:
                failures.append(
                    _failure(
                        "definition_requires_order",
                        f'Definition "{dt}" Requires unknown term "{str(r)[:50]}".',
                        "",
                    )
                )
            elif pi > i:
                failures.append(
                    _failure(
                        "definition_requires_order",
                        f'Definition "{dt}" Requires "{str(r)[:50]}" but that definition appears later (Rule 2).',
                        "",
                    )
                )


def _check_entry_field_consistency(
    nodes: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
) -> None:
    """
    v2 Rule 28 (light): if any node of a type carries an optional key, peers should too —
    only flag keys that appear on >= 50% of that type's nodes but are missing on others.
    """
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for n in nodes or []:
        nt = _node_type(n)
        if nt in ("section", "case", "example"):
            continue
        by_type.setdefault(nt, []).append(n)

    for nt, group in by_type.items():
        if len(group) < 2:
            continue
        key_counts: Dict[str, int] = {}
        for n in group:
            df = n.get("definitive_fields")
            if not isinstance(df, dict):
                continue
            for k in df.keys():
                key_counts[k] = key_counts.get(k, 0) + 1
        threshold = max(2, (len(group) + 1) // 2)
        # Only epistemic / evidence keys — optional template keys (e.g. In Practice) vary by content.
        peer_keys = {"ES", "EC", "CT", "CN", "Tag justifications", "Source Quote"}
        common = {k for k, c in key_counts.items() if c >= threshold and k in peer_keys}
        if not common:
            continue
        offenders: List[str] = []
        for n in group:
            df = n.get("definitive_fields")
            if not isinstance(df, dict):
                df = {}
            missing = sorted(common - set(df.keys()))
            if missing:
                offenders.append(f'"{(n.get("title") or "")[:50]}": {", ".join(missing[:6])}')
        if offenders:
            failures.append(
                _failure(
                    "entry_field_consistency",
                    f'{nt} node(s) missing fields that most {nt} nodes have (Rule 28).',
                    "; ".join(offenders[:12]) + ("…" if len(offenders) > 12 else ""),
                )
            )


def _build_page_text_index(chunks: List[Dict[str, Any]]) -> Dict[int, str]:
    by_page: Dict[int, List[str]] = {}
    for ch in chunks:
        try:
            p = int(ch.get("page_number") or 0)
        except (TypeError, ValueError):
            continue
        txt = (ch.get("chunk_text") or "").strip()
        if not txt:
            continue
        by_page.setdefault(p, []).append(txt)
    return {p: "\n".join(parts) for p, parts in by_page.items()}


def _quote_found_in_page_text(quote: str, page_text: str) -> bool:
    if not quote or not page_text:
        return False
    qn = _norm_ws(quote)
    if len(qn) < 12:
        return True  # too short to verify strictly
    pn = _norm_ws(page_text)
    if qn in pn:
        return True
    qt_tokens = [t for t in re.findall(r"[a-z0-9']+", qn) if len(t) > 2]
    if qt_tokens:
        hits = sum(1 for t in qt_tokens if t in pn)
        if hits / len(qt_tokens) >= 0.58:
            return True
    qt = _token_set(quote)
    pt = _token_set(page_text)
    if len(qt) >= 6 and _jaccard(qt, pt) >= 0.62:
        return True
    prefix = qn[: min(60, len(qn))]
    if len(prefix) >= 20 and prefix in pn:
        return True
    return False


def _check_overview_defined_terms_before_section3(
    doc: str, nodes: List[Dict[str, Any]], failures: List[Dict[str, Any]]
) -> None:
    """
    v2 Rule 1: Overview must not analytically use defined terms before Section 3.
    Conservative check: multi-word definition titles (≥3 tokens, normalized length ≥18) matched as
    whole phrases in Section 2 prose (markdown tables excluded).
    """
    m = re.search(
        r"##\s*2\.?\s+Overview\s*(.*?)(?=^##\s*3\.?\s+Definitions\b)",
        doc,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return
    block = m.group(1)
    prose_lines: List[str] = []
    for line in block.splitlines():
        if line.strip().startswith("|"):
            continue
        prose_lines.append(line)
    prose = "\n".join(prose_lines).strip()
    if len(prose) < 12:
        return

    for n in nodes or []:
        if _node_type(n) != "definition":
            continue
        raw_title = (n.get("title") or "").strip()
        raw_title = re.sub(r"\s*\([^)]*\)\s*$", "", raw_title).strip()
        if not raw_title:
            continue
        words = raw_title.split()
        if len(words) < 3:
            continue
        key_norm = _norm_ws(raw_title)
        if len(key_norm) < 18:
            continue
        try:
            pat = re.compile(
                r"\b" + r"\s+".join(re.escape(w) for w in words) + r"\b",
                re.IGNORECASE,
            )
        except re.error:
            continue
        if pat.search(prose):
            failures.append(
                _failure(
                    "overview_defined_term_before_definitions",
                    "Overview (Section 2) appears to use a defined term before definitions (v2 Rule 1).",
                    f'Matched definition title: "{raw_title[:120]}"',
                )
            )


def _overview_scope_row_issues(row_label: str, cell_text: str) -> List[str]:
    """Detect cut-off claimed scope or mid-sentence evidenced scope in §2 table cells."""
    t = " ".join((cell_text or "").split()).strip()
    if len(t) < 8:
        return []
    low = row_label.lower()
    issues: List[str] = []
    placeholder = bool(re.search(r"\bnot\s+stated\b", t, re.IGNORECASE))
    if "claimed" in low and "scope" in low:
        if len(t) >= 12 and re.search(r"[-–—]\s*$", t):
            issues.append("claimed_ends_with_trailing_hyphen")
        if (
            len(t) >= 24
            and not placeholder
            and not re.search(r"(?:[.!?]|…)\s*$", t)
        ):
            issues.append("claimed_missing_sentence_end")
    if "evidenced" in low and "scope" in low:
        if placeholder:
            return issues
        if len(t) < 16:
            return issues
        ts = t.lstrip()
        if ts and ts[0] in ",;'\"(":
            issues.append("evidenced_opens_with_leading_punctuation")
        if re.match(r"^(ing|ed)\s+", ts, re.IGNORECASE):
            issues.append("evidenced_mid_sentence_fragment_open")
        if re.match(r"^\$[\d,]", ts) or re.match(r"^\d{1,2},\d{3}\b", ts):
            issues.append("evidenced_numeric_fragment_open")
    return issues


def _check_overview_scope_quality(doc: str, failures: List[Dict[str, Any]]) -> None:
    """§2 Overview: Claimed / Evidenced scope cells must read as complete prose (no hyphen tail, no ing/ed opens)."""
    m = re.search(
        r"##\s*2\.?\s+Overview\s*(.*?)(?=^##\s*3\.?\s+Definitions\b)",
        doc,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return
    for line in m.group(1).splitlines():
        raw = line.strip()
        if not raw.startswith("|"):
            continue
        parts = [p.strip() for p in raw.split("|")]
        parts = [p for p in parts if p]
        if len(parts) < 2:
            continue
        label, cell = parts[0], parts[1]
        if re.match(r"^-{3,}$", label):
            continue
        for code in _overview_scope_row_issues(label, cell):
            failures.append(
                _failure(
                    "overview_scope_quality",
                    "Overview scope table cell fails prose-quality checks (complete claimed sentence; evidenced not mid-sentence).",
                    f"{code}: {label[:40]} → {cell[:160]}",
                )
            )


def run_mechanical_audit(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    definitive_document: Optional[str] = None,
    book_id: Optional[int] = None,
    db: Any = None,
) -> Dict[str, Any]:
    """
    Run all implemented mechanical checks.

    Returns:
      {
        "passed": bool,
        "checked_at": ISO8601 Z,
        "failures": [ { "check_id", "message", "detail" }, ... ],
        "warnings": [ { "check_id", "message", "detail", "severity": "info" }, ... ],
        "checks_run": [str, ...],
      }
    """
    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    checks_run: List[str] = []

    node_by_id: Dict[int, Dict[str, Any]] = {}
    for n in nodes or []:
        nid = n.get("id")
        if nid is not None:
            try:
                node_by_id[int(nid)] = n
            except (TypeError, ValueError):
                pass

    node_ids = set(node_by_id.keys())

    # --- edges_reference_valid_nodes ---
    checks_run.append("edges_reference_valid_nodes")
    for e in edges or []:
        try:
            a, b = int(e.get("from_node_id")), int(e.get("to_node_id"))
        except (TypeError, ValueError):
            failures.append(
                _failure(
                    "edges_reference_valid_nodes",
                    "Invalid edge endpoint IDs.",
                    str(e),
                )
            )
            continue
        if a not in node_ids or b not in node_ids:
            failures.append(
                _failure(
                    "edges_reference_valid_nodes",
                    f"Edge references missing node: {a} -> {b} ({e.get('edge_type')}).",
                    "",
                )
            )

    # --- warning_links_step ---
    checks_run.append("warning_links_step")
    for n in nodes or []:
        if _node_type(n) != "warning":
            continue
        nid = n.get("id")
        if nid is None:
            continue
        try:
            nid = int(nid)
        except (TypeError, ValueError):
            continue
        dep = n.get("depends_on_node_id")
        dep_step = False
        if dep is not None:
            try:
                dep = int(dep)
                dep_node = node_by_id.get(dep)
                if dep_node and _node_type(dep_node) == "step":
                    dep_step = True
            except (TypeError, ValueError):
                pass
        has_warns_edge = False
        for e in edges or []:
            try:
                a, b = int(e.get("from_node_id")), int(e.get("to_node_id"))
            except (TypeError, ValueError):
                continue
            et = (e.get("edge_type") or "").strip().lower()
            if et == "warns" and a == nid and b in node_ids:
                to_n = node_by_id.get(b)
                if to_n and _node_type(to_n) == "step":
                    has_warns_edge = True
                    break
        if not dep_step and not has_warns_edge:
            title = (n.get("title") or "")[:80]
            failures.append(
                _failure(
                    "warning_links_step",
                    f'Warning "{title}" must link to a step (depends_on step or warns → step edge).',
                    "",
                )
            )

    # --- constraint_links_step ---
    checks_run.append("constraint_links_step")
    for n in nodes or []:
        if _node_type(n) != "constraint":
            continue
        nid = n.get("id")
        if nid is None:
            continue
        try:
            nid = int(nid)
        except (TypeError, ValueError):
            continue
        dep = n.get("depends_on_node_id")
        dep_step = False
        if dep is not None:
            try:
                dep = int(dep)
                dep_node = node_by_id.get(dep)
                if dep_node and _node_type(dep_node) == "step":
                    dep_step = True
            except (TypeError, ValueError):
                pass
        has_constrains = False
        for e in edges or []:
            try:
                a, b = int(e.get("from_node_id")), int(e.get("to_node_id"))
            except (TypeError, ValueError):
                continue
            et = (e.get("edge_type") or "").strip().lower()
            if et == "constrains" and a == nid and b in node_ids:
                to_n = node_by_id.get(b)
                if to_n and _node_type(to_n) == "step":
                    has_constrains = True
                    break
        if not dep_step and not has_constrains:
            title = (n.get("title") or "")[:80]
            failures.append(
                _failure(
                    "constraint_links_step",
                    f'Constraint "{title}" must link to a step (depends_on step or constrains → step edge).',
                    "",
                )
            )

    # --- operational_principle_governs ---
    checks_run.append("operational_principle_governs")
    for n in nodes or []:
        if _node_type(n) != "principle":
            continue
        df = n.get("definitive_fields")
        if not isinstance(df, dict):
            continue
        tier = (df.get("Tier") or "").strip().lower()
        if "govern" in tier:
            continue
        if "operational" not in tier:
            continue
        governs = (df.get("Governs") or "").strip()
        if not governs or len(governs) < 3:
            title = (n.get("title") or "")[:80]
            failures.append(
                _failure(
                    "operational_principle_governs",
                    f'Operational principle "{title}" should name which steps it governs (Governs field).',
                    "",
                )
            )

    # --- source_quote_uniqueness ---
    checks_run.append("source_quote_uniqueness")
    quotes: List[Tuple[str, str, int]] = []  # (quote, label, node_id)
    for n in nodes or []:
        q, _pr = _get_source_quote(n)
        if len(q) < 24:
            continue
        nid = n.get("id")
        try:
            nid_i = int(nid) if nid is not None else 0
        except (TypeError, ValueError):
            nid_i = 0
        label = f"{_node_type(n)}:{(n.get('title') or '')[:60]}"
        quotes.append((q, label, nid_i))
    seen_pairs: List[Tuple[Set[str], str, int]] = []
    for q, label, nid in quotes:
        ts = _token_set(q)
        if len(ts) < 6:
            continue
        for ts2, label2, nid2 in seen_pairs:
            if _jaccard(ts, ts2) > SOURCE_QUOTE_DUPLICATE_JACCARD_THRESHOLD:
                n1 = node_by_id.get(nid)
                n2 = node_by_id.get(nid2)
                det = f"{label} (id {nid}) vs {label2} (id {nid2})"
                msg = (
                    "Source quotes are near-duplicates (>"
                    f"{int(SOURCE_QUOTE_DUPLICATE_JACCARD_THRESHOLD * 100)}% token-set overlap) for distinct nodes."
                )
                if n1 and n2 and _shared_passage_duplicate_definitions(n1, n2):
                    warnings.append(
                        _warning(
                            "source_quote_uniqueness",
                            msg
                            + " (informational: same-page definitions often share one excerpt in the source)",
                            det,
                        )
                    )
                else:
                    failures.append(_failure("source_quote_uniqueness", msg, det))
                break
        seen_pairs.append((ts, label, nid))

    # --- source_quote_verified_on_page ---
    checks_run.append("source_quote_verified_on_page")
    page_index: Optional[Dict[int, str]] = None
    if book_id is not None and db is not None and hasattr(db, "get_chunks_by_book_id"):
        try:
            chunks = db.get_chunks_by_book_id(int(book_id))
            page_index = _build_page_text_index(chunks)
        except Exception as ex:
            log.warning("mechanical_audit: could not load chunks for book %s: %s", book_id, ex)
            page_index = None

    if page_index:
        for n in nodes or []:
            q, _ = _get_source_quote(n)
            if len(q) < 20:
                continue
            pnum = _parse_page_number(n.get("page_ref"))
            if pnum is None:
                failures.append(
                    _failure(
                        "source_quote_verified_on_page",
                        "Could not parse page_ref for a node with a Source Quote.",
                        (n.get("title") or "")[:80],
                    )
                )
                continue
            parts_pg: List[str] = []
            for delta in (0, -1, 1, -2, 2):
                x = pnum + delta
                if x >= 1 and page_index.get(x):
                    parts_pg.append(page_index[x])
            combined = "\n".join(parts_pg)
            if not combined:
                failures.append(
                    _failure(
                        "source_quote_verified_on_page",
                        f"No source text found for cited page {pnum}.",
                        (n.get("title") or "")[:80],
                    )
                )
                continue
            if not _quote_found_in_page_text(q, combined):
                failures.append(
                    _failure(
                        "source_quote_verified_on_page",
                        "Source Quote could not be matched to text on the cited page (fuzzy check).",
                        f'{(n.get("title") or "")[:80]} (p. {pnum})',
                    )
                )
    else:
        log.info("mechanical_audit: skipping quote-on-page verification (no chunk index).")

    # --- definitive_document_sections ---
    doc = (definitive_document or "").strip()
    if doc:
        checks_run.append("definitive_document_sections")
        required_markers = (
            ("## 1. Metadata", "## 1 Metadata"),
            ("## 2. Overview", "## 2 Overview"),
            ("## 3. Definitions", "## 3 Definitions"),
            ("## 4. Principles", "## 4 Principles"),
            ("## 5. Steps", "## 5 Steps"),
            ("## 6. Warnings", "## 6 Warnings"),
            ("## 7. Constraints", "## 7 Constraints"),
            ("## 8. Dependency Map", "## 8 Dependency Map"),
            ("## 9. Scope and Limits", "## 9 Scope and Limits"),
        )
        missing = [new for new, old in required_markers if new not in doc and old not in doc]
        if missing:
            failures.append(
                _failure(
                    "definitive_document_sections",
                    "Definitive document is missing expected section heading(s).",
                    ", ".join(missing[:6]) + ("…" if len(missing) > 6 else ""),
                )
            )

        checks_run.append("overview_defined_term_before_definitions")
        _check_overview_defined_terms_before_section3(doc, nodes, failures)

        checks_run.append("overview_scope_quality")
        _check_overview_scope_quality(doc, failures)

    # --- no_structural_disclaimer_meta ---
    checks_run.append("no_structural_disclaimer_meta")
    scan_texts: List[str] = [doc] if doc else []
    for n in nodes or []:
        scan_texts.append(n.get("content") or "")
        scan_texts.append(n.get("title") or "")
        df = n.get("definitive_fields")
        if isinstance(df, dict):
            scan_texts.append(json.dumps(df, ensure_ascii=False))
    blob = "\n".join(scan_texts)
    if _STRUCTURAL_DISCLAIMER_PATTERNS.search(blob):
        failures.append(
            _failure(
                "no_structural_disclaimer_meta",
                "Structural meta-disclaimer phrasing detected (not allowed except via Section 9C gaps).",
                "",
            )
        )

    # --- cross_reference_fields (v2 §K / Rule 7) ---
    checks_run.append("cross_reference_fields")
    _check_cross_reference_fields(nodes, failures)

    # --- required_definitive_fields (v2 §F / §E) ---
    checks_run.append("required_definitive_fields")
    _check_required_definitive_fields(nodes, failures)

    # --- definition_requires_order (v2 Rule 2) ---
    checks_run.append("definition_requires_order")
    _check_definition_requires_order(nodes, failures)

    # --- entry_field_consistency (v2 Rule 28 light) ---
    checks_run.append("entry_field_consistency")
    _check_entry_field_consistency(nodes, failures)

    passed = len(failures) == 0
    out = {
        "passed": passed,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "failures": failures,
        "warnings": warnings,
        "checks_run": checks_run,
    }
    log.info(
        "mechanical_audit: passed=%s failure_count=%s warning_count=%s",
        passed,
        len(failures),
        len(warnings),
    )
    return out


def mechanical_audit_markdown_banner(audit: Dict[str, Any]) -> str:
    """Top-of-document markdown notice (same text used for DOCX structure prepend)."""
    if audit.get("passed"):
        return ""
    failures = audit.get("failures") or []
    lines = [
        "> **Mechanical audit (Phase 3): not all checks passed.**",
        f"> Generated checks: {', '.join(audit.get('checks_run') or [])}",
        f"> At: `{audit.get('checked_at', '')}`",
        "",
    ]
    for i, f in enumerate(failures[:25], 1):
        msg = (f.get("message") or "").replace("\n", " ")
        det = (f.get("detail") or "").replace("\n", " ")
        cid = f.get("check_id") or "check"
        line = f"> {i}. **{cid}**: {msg}"
        if det:
            line += f" — _{det}_"
        lines.append(line)
    if len(failures) > 25:
        lines.append(f"> … and {len(failures) - 25} more.")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def definitive_document_for_export(framework: Dict[str, Any]) -> str:
    """
    Definitive markdown for UI HTML and DOCX — same body as stored (no mechanical-audit preamble).

    Mechanical audit results stay in ``framework['mechanical_audit_result']`` and are shown in the
    Quality / audit UI only (Definitive_Framework_Template_Fina.md: no §0 audit block).
    """
    base = (framework.get("definitive_document") or "").strip()
    return base
