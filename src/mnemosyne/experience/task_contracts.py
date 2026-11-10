"""Validate provider-proposed task roles against exact request spans.

The proposer locates roles in paraphrased sentences. It cannot rename entities,
discard constraints, invent capabilities, or declare an unknown action safe.
"""

from __future__ import annotations

import re

_INTENTS = {
    "fix": {"fix", "fixing", "repair", "repairing", "resolve", "resolving", "sort out"},
    "find": {"find", "finding", "locate", "locating", "search for"},
    "show": {"show", "showing", "display", "displaying"},
    "summarize": {"summarize", "summarizing", "summarise", "summarising", "give a summary of"},
    "run": {"run", "running", "execute", "executing"},
    "list": {"list", "listing", "enumerate", "enumerating"},
}
_WRAPPER = frozenset("i we me us you please can could would help need needs want wants to the a an is are it".split())


def grounded_contract(text, proposal, tools, risk):
    """Reject any content word not explicitly assigned to a retained role."""
    if not isinstance(proposal, dict) or proposal.get("version") != 1:
        return None
    intent = proposal.get("intent")
    if intent not in _INTENTS or proposal.get("risk", risk or "normal") != (risk or "normal"):
        return None
    required_tools = proposal.get("required_tools", [])
    if not isinstance(required_tools, list) or not all(isinstance(tool, str) for tool in required_tools) or not set(required_tools) <= set(tools):
        return None
    spans = []
    def extract(value):
        if not isinstance(value, dict):
            raise ValueError("missing role span")
        start, end = value.get("start"), value.get("end")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            raise ValueError("invalid role span")
        if any(start < right and end > left for left, right in spans):
            raise ValueError("overlapping role spans")
        quote = text[start:end]
        if quote != value.get("quote") or not quote.strip():
            raise ValueError("role quote mismatch")
        spans.append((start, end))
        return quote
    try:
        action = extract(proposal.get("action"))
        if action.casefold() not in _INTENTS[intent]:
            return None
        entity = extract(proposal.get("entity"))
        constraints = [extract(span) for span in proposal.get("constraints", [])]
    except (ValueError, TypeError):
        return None
    uncovered = "".join(" " if any(start <= i < end for start, end in spans) else char for i, char in enumerate(text))
    if any(word.casefold() not in _WRAPPER for word in re.findall(r"[\w'-]+", uncovered)):
        return None
    if re.search(r"[^\w\s,.!?'-]", uncovered):
        return None
    # Reuse the deterministic entity normalization; neither model-supplied
    # canonical names nor fabricated input/output labels enter the contract.
    from .task_class import semantic_contract
    base = semantic_contract(f"{intent} {entity}", tools, risk)
    if base is None:
        return None
    if base["constraints"]:  # constraints must not be hidden inside entity text
        return None
    base["constraints"] = constraints
    return base


def proposed_match(query, tools, risk, candidates, proposer):
    if not callable(proposer) or not candidates:
        return None
    choices = sorted(candidates, key=lambda row: (row.get("created_at", ""), row["id"]), reverse=True)[:16]
    try:
        value = proposer(query=query, candidates=[{"id": row["id"], "query": row.get("task_scope_query") or row["user_text"]} for row in choices],
                         available_tools=list(tools), risk_level=risk or "normal")
    except Exception:
        return None
    if not isinstance(value, dict):
        return None
    prior = next((row for row in choices if row["id"] == value.get("matched_episode_id")), None)
    if prior is None:
        return None
    proof = {"method": "grounded_semantic_applicability:v1", "matched_episode_id": prior["id"],
             "query_roles": value.get("query_roles"), "reference_roles": value.get("reference_roles"),
             "source_cids": list(prior.get("source_cids", []))}
    current = grounded_contract(query, proof["query_roles"], tools, risk)
    reference = grounded_contract(prior.get("task_scope_query") or prior["user_text"], proof["reference_roles"], tools, risk)
    if current is None or current != reference:
        return None
    proof["contract"] = current
    return prior, proof
