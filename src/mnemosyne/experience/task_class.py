"""Stable task identities without presenting lexical hashes as semantic clustering."""

import unicodedata
import re

from .receipts import digest

METHOD = "explicit-or-full-request-with-bounded-equivalence-v4"

_ACTION_FORMS = (
    ("list", r"(?:list|enumerate|(?:give|show)(?: me)? a list of)"),
    ("summarize", r"(?:summari[sz]e|(?:give|provide)(?: me)? a summary of)"),
    ("show", r"(?:show(?: me)?|display)"),
    ("find", r"(?:find|locate)"),
    ("fix", r"(?:fix|repair)"),
    ("run", r"(?:run|execute)"),
)


def _request_contract(query: str) -> tuple[str, str] | None:
    """Normalize bounded request forms while preserving the complete subject.

    Similarity alone does not establish interchangeable work. These forms only
    remove polite wrappers and replace an explicitly equivalent action phrase.
    Subject case, entities, quoted code, negation and constraints remain literal.
    """
    request = unicodedata.normalize("NFC", query).strip()
    request = re.sub(r"^(?:(?:please|(?:can|could|would) you)\s+){1,2}", "", request,
                     flags=re.IGNORECASE)
    for action, pattern in _ACTION_FORMS:
        match = re.match(pattern + r"\s+(.+)$", request, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return action, match.group(1)
    return None


def scope_query(episode: dict) -> str:
    return episode.get("task_scope_query") or episode.get("user_text", "")


def resolve_task(query, tools, task_type, *, tenant_id, user_id, risk_level,
                 state, source_is_live):
    """Reuse a proven owner-scoped task identity for a bounded paraphrase.

    Stored identities and outcomes stay intact. Each alias retains the prior
    exact scope and the observed episode that justifies its interpretation.
    """
    task = classify(query, tools, task_type)
    contract = _request_contract(query)
    if task_type or contract is None:
        return task, query, None
    candidates = []
    for episode in state["episodes"].values():
        if (
            episode.get("tenant_id") != tenant_id or episode.get("user_id") != user_id
            or episode.get("status") not in {"open", "resolved"}
            or episode.get("feedback_for_episode_id")
            or not episode.get("task_class", "").startswith("lexical:v3:")
            or _request_contract(episode.get("user_text", "")) != contract
            or _request_contract(scope_query(episode)) != contract
        ):
            continue
        receipts = [state["receipts"][key] for key in episode.get("receipt_ids", [])
                    if key in state["receipts"]]
        if not any(
            set(receipt.get("available_tools", [])) == set(tools)
            and receipt.get("risk_level", "normal") == (risk_level or "normal")
            for receipt in receipts
        ) or not source_is_live(episode.get("source_cids", [])):
            continue
        candidates.append(episode)
    if not candidates:
        return task, query, None
    prior = min(candidates, key=lambda row: (
        row["user_text"] != scope_query(row), row["user_text"] != query,
        row["created_at"], row["id"],
    ))
    if prior["user_text"] == query and scope_query(prior) == query:
        return prior["task_class"], query, None
    return prior["task_class"], scope_query(prior), {
        "method": "bounded_request_equivalence:v1", "matched_episode_id": prior["id"],
        "source_cids": list(prior["source_cids"]),
    }


def validated_scope_query(receipt: dict, state: dict) -> str | None:
    """Validate retained equivalence evidence before using a canonical scope."""
    query = receipt.get("query", "")
    canonical = receipt.get("task_scope_query", query)
    proof = receipt.get("task_match")
    if not proof:
        return query if canonical == query else None
    prior = state["episodes"].get(proof.get("matched_episode_id"), {})
    contract = _request_contract(query)
    if (
        proof.get("method") != "bounded_request_equivalence:v1"
        or prior.get("status") not in {"open", "resolved"}
        or prior.get("tenant_id") != receipt.get("tenant_id")
        or prior.get("user_id") != receipt.get("user_id")
        or prior.get("task_class") != receipt.get("task_class")
        or canonical != scope_query(prior)
        or contract is None or _request_contract(canonical) != contract
        or not set(prior.get("source_cids", [])) <= set(receipt.get("source_cids", []))
    ):
        return None
    old_receipts = [state["receipts"][key] for key in prior.get("receipt_ids", [])
                    if key in state["receipts"]]
    if not any(
        set(old.get("available_tools", [])) == set(receipt.get("available_tools", []))
        and old.get("risk_level", "normal") == receipt.get("risk_level", "normal")
        for old in old_receipts
    ):
        return None
    return canonical


def classify(query: str, tools: list[str], task_type: str | None = None) -> str:
    """Group formatting-equivalent requests or honor an explicit shared class.

    Automatic matching normalizes Unicode and trims outer whitespace. Case,
    internal whitespace, words, numbers and punctuation retain their identity. Reusing a
    class across semantic paraphrases requires a caller-supplied ``task_type``.
    The versioned namespace keeps new requests separate from persisted classes
    made by the former two-word hash, whose members may be unrelated.
    """
    if task_type:
        return str(task_type)
    request = unicodedata.normalize("NFC", query).strip()
    return "lexical:v3:" + digest([request, sorted(set(tools))])[:32]
