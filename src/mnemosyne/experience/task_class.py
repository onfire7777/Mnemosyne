"""Stable task identities without presenting lexical hashes as semantic clustering."""

import unicodedata
import re

from .receipts import digest

METHOD = "explicit-or-full-request-with-grounded-abstract-transfer-v7"
CONTRACT_VERSION = 1

_ACTION_FORMS = (
    ("optimize", r"(?:optimi[sz]e|improve the performance of|speed up)"),
    ("diagnose", r"(?:diagnose|debug|investigate|troubleshoot)"),
    ("implement", r"(?:implement|build|develop)"),
    ("refactor", r"(?:refactor|restructure)"),
    ("verify", r"(?:verify|validate|check)"),
    ("explain", r"(?:explain|describe)"),
    ("compare", r"(?:compare|contrast)"),
    ("configure", r"(?:configure|set up)"),
    ("migrate", r"(?:migrate|upgrade)"),
    ("document", r"(?:document|write documentation for)"),
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
            subject = match.group(1)
            # Only grammatical prose gets article/terminal punctuation folding.
            # Code, paths, quoted strings, flags and decimal literals stay exact.
            prose = re.fullmatch(r"(?:the )?([A-Za-z][A-Za-z0-9 ]*\b(?:report|reports|bug|bugs|check|checks|test|tests|file|files|summary|summaries))[.!?]?", subject)
            if prose:
                subject = prose.group(1)
            return action, subject
    return None


def semantic_contract(query: str, tools=(), risk_level=None) -> dict | None:
    """A bounded, inspectable applicability contract, separate from task IDs.

    Only grammatical wrappers and a small domain vocabulary are normalized.
    Paths, quoted literals, flags, entities, numbers and constraints remain
    exact; unknown language declines transfer rather than guessing similarity.
    Available tools are recorded separately from demonstrated required tools.
    """
    text = unicodedata.normalize("NFC", query).strip()
    text = re.sub(r"^(?:(?:please|(?:can|could|would) you)\s+){1,2}", "", text, flags=re.I)
    text = re.sub(r"^help me\s+(?:to\s+)?", "", text, flags=re.I)
    text = re.sub(r"^resolve\s+", "fix ", text, flags=re.I)
    parsed = _request_contract(text)
    if parsed is None:
        return None
    action, subject = parsed
    # Split constraints before normalizing the domain vocabulary. A negated
    # condition, changed tool or changed side effect can never disappear.
    pieces = re.split(r"\s+(?=(?:without|with|using|only|unless|except|before|after|while|but|do not|never)\b)", subject, maxsplit=1)
    entity = pieces[0]
    constraints = pieces[1:]  # retained verbatim, including case and punctuation
    entity = re.sub(r"^the\s+", "", entity)
    if re.fullmatch(r"[a-z][a-z ]*[.!?]?", entity):
        entity = entity.rstrip(".!?")
        # These substitutions are confined to a repair intent, not arbitrary
        # names or descriptions. 'cache invalidation' remains a distinct entity.
        if action in {"fix", "diagnose"}:
            entity = re.sub(r"\bcaching\b", "cache", entity)
            entity = re.sub(r"\b(?:issue|problem|bug)\b$", "defect", entity)
    return {"version": CONTRACT_VERSION, "intent": action, "entity": entity,
            "inputs": [entity], "outputs": [action], "constraints": constraints,
            "risk": risk_level or "normal", "available_tools": sorted(set(tools))}


def _semantic_equal(left, right):
    return bool(left and right and {k: v for k, v in left.items() if k != "available_tools"}
                == {k: v for k, v in right.items() if k != "available_tools"})


def _required_tools(episode: dict, receipt: dict) -> set[str]:
    from .candidates import EXCLUDED_SOURCES, observed_action

    observed = {event["name"] for event in episode.get("tool_events", [])
                if event.get("source") not in EXCLUDED_SOURCES
                and event.get("name") != "benchmark_verifier"
                and observed_action(event) is not None}
    # Without an observed trace there is no basis to declare a tool incidental.
    return observed or set(receipt.get("available_tools", []))


def _compatible_tools(episode: dict, old: dict, tools: list[str]) -> bool:
    return _required_tools(episode, old) <= set(tools)


def scope_query(episode: dict) -> str:
    return episode.get("task_scope_query") or episode.get("user_text", "")


def resolve_task(query, tools, task_type, *, tenant_id, user_id, risk_level,
                 state, source_is_live, proposer=None):
    """Reuse a proven owner-scoped task identity for a bounded paraphrase.

    Stored identities and outcomes stay intact. Each alias retains the prior
    exact scope and the observed episode that justifies its interpretation.
    """
    task = classify(query, tools, task_type)
    contract = _request_contract(query)
    semantic = semantic_contract(query, tools, risk_level)
    if task_type:
        return task, query, None
    candidates = []
    proposal_candidates = []
    for episode in state["episodes"].values():
        if (
            episode.get("tenant_id") != tenant_id or episode.get("user_id") != user_id
            or episode.get("status") not in {"open", "resolved"}
            or episode.get("feedback_for_episode_id")
            or not episode.get("task_class", "").startswith("lexical:v3:")
        ):
            continue
        literal_match = bool(contract and _request_contract(episode.get("user_text", "")) == contract
                             and _request_contract(scope_query(episode)) == contract)
        semantic_match = bool(
            episode.get("status") == "resolved"
            and any(s.get("kind") in {"tests", "verifier"} for s in episode.get("signals", []))
            and _semantic_equal(semantic, semantic_contract(episode.get("user_text", ""), tools, risk_level))
            and _semantic_equal(semantic, semantic_contract(scope_query(episode), tools, risk_level))
        )
        receipts = [state["receipts"][key] for key in episode.get("receipt_ids", [])
                    if key in state["receipts"]]
        if not any(
            _compatible_tools(episode, receipt, tools)
            and receipt.get("risk_level", "normal") == (risk_level or "normal")
            for receipt in receipts
        ) or not source_is_live(episode.get("source_cids", [])):
            continue
        if episode.get("status") == "resolved" and any(s.get("kind") in {"tests", "verifier"} for s in episode.get("signals", [])):
            proposal_candidates.append(episode)
        if not literal_match and not semantic_match:
            continue
        candidates.append((episode, literal_match))
    if not candidates:
        from .task_contracts import proposed_match
        proposed = proposed_match(query, tools, risk_level, proposal_candidates, proposer)
        if proposed:
            prior, proof = proposed
            return prior["task_class"], scope_query(prior), proof
        return task, query, None
    prior, literal_match = min(candidates, key=lambda pair: (
        not pair[1],
        (row := pair[0])["user_text"] != scope_query(row), row["user_text"] != query,
        row["created_at"], row["id"],
    ))
    if prior["user_text"] == query and scope_query(prior) == query and prior["task_class"] == task:
        return prior["task_class"], query, None
    return prior["task_class"], scope_query(prior), {
        "method": "bounded_request_equivalence:v2" if literal_match else "semantic_applicability:v1",
        "matched_episode_id": prior["id"],
        "source_cids": list(prior["source_cids"]),
        **({"contract": semantic, "required_tools": sorted(_required_tools(
            prior, next(state["receipts"][key] for key in prior["receipt_ids"]
                        if key in state["receipts"]))) }
           if not literal_match else {}),
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
    grounded_match = proof.get("method") == "grounded_semantic_applicability:v1"
    semantic_match = proof.get("method") == "semantic_applicability:v1" or grounded_match
    if (
        proof.get("method") not in {"bounded_request_equivalence:v1", "bounded_request_equivalence:v2", "semantic_applicability:v1", "grounded_semantic_applicability:v1"}
        or prior.get("status") not in {"open", "resolved"}
        or prior.get("tenant_id") != receipt.get("tenant_id")
        or prior.get("user_id") != receipt.get("user_id")
        or prior.get("task_class") != receipt.get("task_class")
        or canonical != scope_query(prior)
        or (not semantic_match and (contract is None or _request_contract(canonical) != contract))
        or not set(prior.get("source_cids", [])) <= set(receipt.get("source_cids", []))
    ):
        return None
    if semantic_match:
        if grounded_match:
            from .task_contracts import grounded_contract
            expected = grounded_contract(query, proof.get("query_roles"), receipt.get("available_tools", []), receipt.get("risk_level"))
            reference = grounded_contract(canonical, proof.get("reference_roles"), receipt.get("available_tools", []), receipt.get("risk_level"))
        else:
            expected = semantic_contract(query, receipt.get("available_tools", []), receipt.get("risk_level"))
            reference = semantic_contract(canonical, (), receipt.get("risk_level"))
        if (proof.get("contract") != expected
                or prior.get("status") != "resolved"
                or not any(s.get("kind") in {"tests", "verifier"} for s in prior.get("signals", []))
                or not _semantic_equal(expected, reference)):
            return None
    old_receipts = [state["receipts"][key] for key in prior.get("receipt_ids", [])
                    if key in state["receipts"]]
    if not any(
        (_compatible_tools(prior, old, receipt.get("available_tools", []))
         if proof.get("method") in {"bounded_request_equivalence:v2", "semantic_applicability:v1", "grounded_semantic_applicability:v1"}
         else set(old.get("available_tools", [])) == set(receipt.get("available_tools", [])))
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
