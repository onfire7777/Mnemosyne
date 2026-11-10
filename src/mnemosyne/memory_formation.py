"""Form owned semantic memory from direct, current user statements."""

from __future__ import annotations

import json
import re
from uuid import NAMESPACE_URL, uuid5

from mnemosyne.access_policy import evidence_expiry_deadline, merge_access_policies
from mnemosyne.episodic_facts import extract_episodic_facts
from mnemosyne.models import utc_now
from mnemosyne.retrieval import projection_sources_readable
from mnemosyne.security import is_write_tainted


_USER_SOURCE_TYPES = {"chat", "learning_turn", "correction", "conversation", "message", "note", "user"}
_FIRST_PERSON = re.compile(r"^(?:I\b|I['’](?:m|ve|ll|d)\b|We\b|We['’](?:re|ve|ll|d)\b|My\b|Our\b)", re.I)
_DIRECTIVE = re.compile(
    r"^(?:please\s+(?:use|keep|respond)\b|from\s+now\s+on\b|(?:use|write|respond)\b.+\binstead\b)", re.I,
)
_HYPOTHETICAL = re.compile(
    r"\b(?:if|suppose|imagine|hypothetically|assuming|maybe|perhaps|may|might|possibly|probably)\b"
    r"|\b(?:think|guess|suspect|uncertain|unsure|not sure)\b|\bwould\s+(?!prefer\b|like\b)", re.I,
)
_QUOTED_BLOCK = re.compile(r"(?:^|\b)(?:example|quote|quoted|instructions?|prompt|transcript|code|logs?)\s*:\s*$", re.I)
_CONTRACTIONS = {
    "don't": "do not", "doesn't": "does not", "didn't": "did not",
    "can't": "can not", "couldn't": "could not", "won't": "will not",
    "wouldn't": "would not", "shouldn't": "should not", "haven't": "have not",
    "hasn't": "has not", "i'm": "I am", "i've": "I have", "we're": "We are",
    "we've": "We have",
}
_CONTRACTION_PATTERN = re.compile(r"\b(?:" + "|".join(re.escape(key) for key in _CONTRACTIONS) + r")\b", re.I)


def _eligible_user_source(source) -> bool:
    metadata = source.metadata
    provenance = metadata.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    deadline = evidence_expiry_deadline(source.access_policy, metadata)
    return (
        source.actor == "user" and source.source_type in _USER_SOURCE_TYPES
        and isinstance(source.trust_tier, int) and not isinstance(source.trust_tier, bool)
        and source.trust_tier in {0, 1} and bool(source.user_id)
        and not source.erased and source.retired_at is None
        and not is_write_tainted(source.capability_tags)
        and not any(metadata.get(key) or provenance.get(key)
                    for key in ("imported_from", "imported", "historical", "synthetic", "data_only", "source_origin"))
        and metadata.get("origin") not in {"imported", "external", "synthetic"}
        and provenance.get("origin") not in {"imported", "external", "synthetic"}
        and not metadata.get("quarantine_reason")
        and metadata.get("reality_class") not in {"self_generated", "simulated", "externally_suggested"}
        and (deadline is None or deadline > utc_now())
    )


def direct_user_clauses(source_or_text, *, include_directives: bool = False) -> list[str]:
    """Return original declarative clauses, omitting quoted or uncertain prose."""
    if isinstance(source_or_text, str):
        text = source_or_text
    else:
        if not _eligible_user_source(source_or_text):
            return []
        text = source_or_text.content
    if re.search(r"<(?:instructions?|system|developer|environment_context)\b|^\s*#\s*AGENTS\.md\b", text, re.I | re.M):
        return []
    quoted_lines = set()
    for match in re.finditer(r'''"[^"]*"|“[^”]*”|(?<!\w)'(?:[^']|'(?=\w))*'(?!\w)|‘[^’]*’''', text, re.S):
        quoted_lines.update(range(text.count("\n", 0, match.start()), text.count("\n", 0, match.end()) + 1))
    clauses = []
    fenced = False
    quoted_block = False
    for line_number, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if not stripped:
            quoted_block = False
            continue
        if fenced or quoted_block or line_number in quoted_lines or stripped.startswith((">", "#")):
            continue
        if _QUOTED_BLOCK.search(stripped):
            quoted_block = True
            continue
        stripped = re.sub(r"^(?:[-*]\s+|\d+[.)]\s+)", "", stripped)
        for clause in re.split(r"(?<=[.!?])\s+|;\s*|\s+and\s+(?=(?:I|We|My|Our)\b)", stripped):
            clause = clause.strip()
            if (
                (_FIRST_PERSON.match(clause) or include_directives and _DIRECTIVE.match(clause))
                and not clause.endswith("?")
                and not _HYPOTHETICAL.search(clause)
                and not re.search(r"\b(?:says|said|told|claims|believes|according to)\b", clause, re.I)
                and not re.match(r"I\s+(?:said|wrote|quoted|read|asked|ran|clicked|opened)\b", clause, re.I)
                and not re.search(r'["“”`]|(?:^|\s)[\'‘].+?[\'’](?:\s|$)', clause)
            ):
                clauses.append(clause)
    return list(dict.fromkeys(clauses))


def project_direct_user_memory(engine, tenant_id: str, cid: str, branch: str = "main") -> dict:
    """Project trusted user evidence through the existing episodic extractor."""
    result = {"source_cid": cid, "assertion_ids": [], "relation_ids": [], "count": 0,
              "created_count": 0, "reason": "ineligible_source"}
    source = engine.get_evidence(tenant_id, cid, branch=branch)
    if (
        source is None or not _eligible_user_source(source)
        or not projection_sources_readable(
            engine, [cid], tenant_id=tenant_id, branch=branch,
            filt={"tenant_id": tenant_id, "user_id": source.user_id, "principal": source.user_id},
            policy=engine.policy,
        )
    ):
        return result
    policy = merge_access_policies([
        source.access_policy, {"tenant": tenant_id, "allow_principals": [source.user_id]},
    ], tenant_id=tenant_id)
    deadline = evidence_expiry_deadline(source.access_policy, source.metadata)
    if deadline is not None:
        policy["expires_at"] = deadline.isoformat()
    clauses = direct_user_clauses(source)
    if not clauses:
        result["reason"] = "no_supported_direct_claim"
        return result
    snapshot = engine.export_tenant(tenant_id)
    retained_assertions = [row for row in snapshot["assertions"] if row.get("branch", "main") == branch]
    retained_relations = {row["id"] for row in snapshot["relations"] if row.get("branch", "main") == branch}
    for clause in clauses:
        parser_text = _CONTRACTION_PATTERN.sub(
            lambda match: _CONTRACTIONS[match.group().lower()], clause.replace("’", "'"),
        )
        facts = extract_episodic_facts(
            parser_text, tenant_id=tenant_id, user_id=source.user_id, branch=branch,
            source_evidence_cids=[cid], created_at=source.created_at,
            trust_tier=source.trust_tier, access_policy=policy, speaker_role="user",
        )
        for fact in facts.assertions:
            identity = ["direct-user-assertion", tenant_id, source.user_id, branch, cid,
                        fact.subject, fact.predicate, fact.object, fact.scope]
            fact.id = str(uuid5(NAMESPACE_URL, json.dumps(identity, sort_keys=True)))
            fact.calibration["source_quote"] = clause
            retained = next((row for row in retained_assertions if row["id"] == fact.id or (
                cid in row.get("source_evidence_cids", []) and row.get("user_id") == source.user_id
                and row["subject"] == fact.subject and row["predicate"] == fact.predicate
                and row["object"] == fact.object and row.get("scope", {}) == fact.scope
            )), None)
            if retained is None:
                identifier = engine.upsert_assertion(fact, branch=branch)
                result["created_count"] += int(identifier == fact.id)
            else:
                identifier = retained["id"]
            if identifier not in result["assertion_ids"]:
                result["assertion_ids"].append(identifier)
        for relation in facts.relations:
            identity = ["direct-user-relation", tenant_id, source.user_id, branch, cid,
                        relation.source, relation.predicate, relation.target]
            relation.id = str(uuid5(NAMESPACE_URL, json.dumps(identity)))
            identifier = relation.id
            if identifier not in retained_relations:
                engine.add_relation(relation, branch=branch)
                result["created_count"] += 1
                retained_relations.add(identifier)
            if identifier not in result["relation_ids"]:
                result["relation_ids"].append(identifier)
    result["count"] = len(result["assertion_ids"]) + len(result["relation_ids"])
    result["reason"] = "projected" if result["count"] else "no_supported_direct_claim"
    return result
