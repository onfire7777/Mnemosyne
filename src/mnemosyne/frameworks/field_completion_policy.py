"""
Field completion policy (v2 + Definitive Framework Template): required vs omitted vs acknowledged-gap.

Shared by mechanical_audit and run_definitive_fields_pass — single source of truth (Rules 14–17, 21, quotes).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# --- Rule 21 (warnings) ---
WARNING_SYMPTOMS_GAP_CANONICAL = (
    "The book does not provide enough detail in the excerpt to list 2–4 observable symptoms for this warning; "
    "use the error description, consequence, and linked step for recognition."
)

# --- Rules 14–15 (definitions) ---
DEFINITION_SOURCE_GAP_CANONICAL = (
    "The book does not specify whether this term is author-defined or framework-derived in the provided excerpt."
)
OPERATIONAL_TEST_GAP_CANONICAL = (
    "The book does not specify an operational test in the excerpt by which two readers could agree whether a case meets this definition."
)

# --- Rules 17, 19 (steps) ---
STEP_ACTION_GAP_CANONICAL = (
    "The book does not specify an imperative action for this step in the provided excerpt."
)
# Definitive_System_Feedback_v2 Rule 17 (exact prescribed sentence).
STEP_DONE_WHEN_GAP_CANONICAL = (
    "The book does not specify completion criteria for this step."
)

# --- Rule 22 (constraints) — prescribed when the book offers no mitigation ---
CONSTRAINT_MITIGATION_GAP_CANONICAL = (
    "The book does not provide a mitigation for this condition."
)

# --- Rule 26 (quotes): max words in Source Quote.Quote for export/mechanical alignment ---
SOURCE_QUOTE_MAX_WORDS = 60


def _norm_ws(s: str) -> str:
    return " ".join((s or "").split()).strip()


# Legacy strings from earlier prompts (treat as satisfied gap prose for policy + rendering).
_STEP_DONE_WHEN_GAP_LEGACY = (
    "The book does not specify observable completion criteria for this step in the provided excerpt."
)


def is_template_acknowledged_gap_sentence(text: Optional[str]) -> bool:
    """
    True if text is an allowed, reader-facing acknowledged-gap sentence (Rules 14–17, 21–22).

    These must NOT be classified as empty placeholders for §9C aggregation or reference-field stripping.
    """
    n = _norm_ws(str(text or ""))
    if len(n) < 24:
        return False
    canon = (
        _norm_ws(DEFINITION_SOURCE_GAP_CANONICAL),
        _norm_ws(OPERATIONAL_TEST_GAP_CANONICAL),
        _norm_ws(STEP_ACTION_GAP_CANONICAL),
        _norm_ws(STEP_DONE_WHEN_GAP_CANONICAL),
        _norm_ws(_STEP_DONE_WHEN_GAP_LEGACY),
        _norm_ws(WARNING_SYMPTOMS_GAP_CANONICAL),
        _norm_ws(CONSTRAINT_MITIGATION_GAP_CANONICAL),
    )
    if n in canon:
        return True
    low = n.lower()
    if low.startswith("the book does not provide a mitigation"):
        return True
    if low.startswith("the book does not specify completion criteria"):
        return True
    if low.startswith("the book does not specify observable completion criteria"):
        return True
    if low.startswith("the book does not specify an imperative action"):
        return True
    if low.startswith("the book does not specify whether this term is author-defined"):
        return True
    if low.startswith("the book does not specify an operational test"):
        return True
    return False


def is_symptoms_acknowledged_gap(text: str) -> bool:
    """True if Symptoms is satisfied by the explicit gap path (one string), allowing minor whitespace drift."""
    n = _norm_ws(text)
    if not n:
        return False
    if _norm_ws(WARNING_SYMPTOMS_GAP_CANONICAL) == n:
        return True
    low = n.lower()
    if n.startswith("The book does not") and "symptom" in low and len(n) >= 48:
        return True
    return False


def _trivial_symptom_string(s: str) -> bool:
    t = (s or "").strip()
    if len(t) < 3:
        return True
    low = t.lower()
    if low in ("n/a", "none", "-", "—", "tbd"):
        return True
    return False


def substantive_symptom_count(symptoms: Any) -> int:
    """Count plausible observable symptom strings (min length, not trivial)."""
    if not isinstance(symptoms, list):
        return 0
    n = 0
    for x in symptoms:
        t = (str(x) if x is not None else "").strip()
        if _trivial_symptom_string(t):
            continue
        if is_symptoms_acknowledged_gap(t):
            continue
        n += 1
    return n


def warning_symptoms_satisfy_policy(definitive_fields: Dict[str, Any]) -> bool:
    """
    Rule 21: either ≥2 substantive symptom strings, OR a single acknowledged-gap entry (canonical or equivalent).
    """
    df = definitive_fields if isinstance(definitive_fields, dict) else {}
    sym = df.get("Symptoms")
    if not isinstance(sym, list):
        return False
    texts = [str(x).strip() for x in sym if str(x).strip()]
    if not texts:
        return False
    if len(texts) == 1 and is_symptoms_acknowledged_gap(texts[0]):
        return True
    return substantive_symptom_count(sym) >= 2


# --- Rules 14–16: definition fields ---


def definition_source_satisfies_policy(text: Optional[str]) -> bool:
    """Rule 15: Author-defined / Framework-derived, or explicit book-gap wording."""
    t = _norm_ws(str(text or ""))
    if len(t) < 3:
        return False
    low = t.lower()
    if "author-defined" in low or "framework-derived" in low:
        return True
    if t == _norm_ws(DEFINITION_SOURCE_GAP_CANONICAL):
        return True
    if t.startswith("The book does not") and len(t) >= 24:
        return True
    return False


def operational_test_satisfies_policy(text: Optional[str]) -> bool:
    """Rule 16: substantive test OR explicit gap (≥8 chars)."""
    t = _norm_ws(str(text or ""))
    return len(t) >= 8


def definition_fields_satisfy_policy(definitive_fields: Dict[str, Any]) -> bool:
    df = definitive_fields if isinstance(definitive_fields, dict) else {}
    return definition_source_satisfies_policy(df.get("Definition Source")) and operational_test_satisfies_policy(
        df.get("Operational Test")
    )


# --- Rules 17, 19: step fields ---


def step_action_satisfies_policy(text: Optional[str]) -> bool:
    t = _norm_ws(str(text or ""))
    return len(t) >= 8


def step_done_when_satisfies_policy(text: Optional[str]) -> bool:
    t = _norm_ws(str(text or ""))
    return len(t) >= 8


def step_action_done_when_satisfy_policy(definitive_fields: Dict[str, Any]) -> bool:
    df = definitive_fields if isinstance(definitive_fields, dict) else {}
    return step_action_satisfies_policy(df.get("Action")) and step_done_when_satisfies_policy(df.get("Done When"))


# --- Rule 26: quote word limit ---


def _truncate_quote_to_words(quote: str, max_words: int = SOURCE_QUOTE_MAX_WORDS) -> str:
    words = (quote or "").split()
    if len(words) <= max_words:
        return (quote or "").strip()
    cut = " ".join(words[:max_words]).rstrip(".,;:")
    return cut + "…"


def enforce_source_quote_word_limit(nodes: List[Dict[str, Any]], max_words: int = SOURCE_QUOTE_MAX_WORDS) -> int:
    """
    Trim Source Quote.Quote to max_words (Rule 26). Keeps Core Sentence inside Quote when possible.

    Returns number of nodes updated.
    """
    changed = 0
    for n in nodes or []:
        df = n.get("definitive_fields")
        if not isinstance(df, dict):
            continue
        sq = df.get("Source Quote")
        if not isinstance(sq, dict):
            continue
        q = (sq.get("Quote") or "").strip()
        if not q:
            continue
        words = q.split()
        if len(words) <= max_words:
            continue
        new_q = _truncate_quote_to_words(q, max_words)
        sq["Quote"] = new_q
        cs = (sq.get("Core Sentence") or "").strip()
        if not cs or cs not in new_q:
            # Preserve one evidential sentence from the trimmed quote
            first_sent = new_q.split(". ")[0].strip()
            if len(first_sent) >= 12:
                sq["Core Sentence"] = first_sent + ("." if not first_sent.endswith(".") else "")
            else:
                sq["Core Sentence"] = new_q[: min(240, len(new_q))]
        changed += 1
    return changed


# --- ensure* passes (after definitive LLM batches) ---


def ensure_warning_symptoms_or_gap(nodes: List[Dict[str, Any]]) -> int:
    """Any warning failing Rule 21 gets canonical gap Symptoms."""
    changed = 0
    for n in nodes or []:
        if (n.get("node_type") or "").strip().lower() != "warning":
            continue
        df = n.get("definitive_fields")
        if not isinstance(df, dict):
            df = {}
            n["definitive_fields"] = df
        if warning_symptoms_satisfy_policy(df):
            continue
        df["Symptoms"] = [WARNING_SYMPTOMS_GAP_CANONICAL]
        changed += 1
    return changed


def ensure_definition_fields_or_gap(nodes: List[Dict[str, Any]]) -> int:
    """Rules 14–16: Definition Source + Operational Test filled or canonical gap strings."""
    changed = 0
    for n in nodes or []:
        if (n.get("node_type") or "").strip().lower() != "definition":
            continue
        df = n.get("definitive_fields")
        if not isinstance(df, dict):
            df = {}
            n["definitive_fields"] = df
        touched = False
        if not definition_source_satisfies_policy(str(df.get("Definition Source") or "")):
            df["Definition Source"] = DEFINITION_SOURCE_GAP_CANONICAL
            touched = True
        if not operational_test_satisfies_policy(str(df.get("Operational Test") or "")):
            df["Operational Test"] = OPERATIONAL_TEST_GAP_CANONICAL
            touched = True
        if touched:
            changed += 1
    return changed


def ensure_step_action_done_when_or_gap(nodes: List[Dict[str, Any]]) -> int:
    """Rules 17, 19: Action + Done When filled or canonical gap strings."""
    changed = 0
    for n in nodes or []:
        if (n.get("node_type") or "").strip().lower() != "step":
            continue
        df = n.get("definitive_fields")
        if not isinstance(df, dict):
            df = {}
            n["definitive_fields"] = df
        touched = False
        if not step_action_satisfies_policy(df.get("Action")):
            df["Action"] = STEP_ACTION_GAP_CANONICAL
            touched = True
        if not step_done_when_satisfies_policy(df.get("Done When")):
            df["Done When"] = STEP_DONE_WHEN_GAP_CANONICAL
            touched = True
        if touched:
            changed += 1
    return changed


def ensure_constraint_mitigation_or_gap(nodes: List[Dict[str, Any]]) -> int:
    """Rule 22: every constraint has Mitigation text or the canonical gap sentence."""
    changed = 0
    for n in nodes or []:
        if (n.get("node_type") or "").strip().lower() != "constraint":
            continue
        df = n.get("definitive_fields")
        if not isinstance(df, dict):
            df = {}
            n["definitive_fields"] = df
        mit = str(df.get("Mitigation") or "").strip()
        if len(mit) >= 8:
            continue
        df["Mitigation"] = CONSTRAINT_MITIGATION_GAP_CANONICAL
        changed += 1
    return changed
