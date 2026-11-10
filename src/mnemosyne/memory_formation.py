"""Form owned semantic memory from direct, current user statements."""

from __future__ import annotations

import json
import re
from uuid import NAMESPACE_URL, uuid5

from mnemosyne.access_policy import evidence_expiry_deadline, merge_access_policies
from mnemosyne.episodic_facts import extract_episodic_facts, _strip_temporal_affixes
from mnemosyne.assertion_semantics import assertion_predicate_key
from mnemosyne.models import utc_now
from mnemosyne.retrieval import projection_sources_readable
from mnemosyne.security import is_write_tainted


_USER_SOURCE_TYPES = {"chat", "learning_turn", "correction", "conversation", "message", "note", "user"}
_FIRST_PERSON = re.compile(r"^(?:I\b|I['’](?:m|ve|ll|d)\b|We\b|We['’](?:re|ve|ll|d)\b|My\b|Our\b)", re.I)
_DIRECTIVE = re.compile(
    r"^(?:please\s+(?:use|keep|respond)\b|from\s+now\s+on\b|(?:use|write|respond)\b.+\binstead\b)", re.I,
)
_HYPOTHETICAL = re.compile(
    r"\b(?:if|suppose|imagine|hypothetically|assuming|maybe|perhaps|might|possibly|probably)\b"
    r"|\b(?:I|we|he|she|they|it)\s+may\b|\bmay\s+(?:not\s+)?(?:be|have|live|move|work|prefer|like|need)\b"
    r"|\b(?:think|guess|suspect|uncertain|unsure|not sure)\b|\bwould\s+(?!prefer\b|like\b)", re.I,
)
_QUOTED_BLOCK = re.compile(r"(?:^|\b)(?:example|quote|quoted|instructions?|prompt|transcript|code|logs?)\s*:\s*$", re.I)
_CONTRACTIONS = {
    "don't": "do not", "doesn't": "does not", "didn't": "did not",
    "can't": "can not", "couldn't": "could not", "won't": "will not",
    "wouldn't": "would not", "shouldn't": "should not", "haven't": "have not",
    "hasn't": "has not", "isn't": "is not", "aren't": "are not", "wasn't": "was not", "i'm": "I am", "i've": "I have", "we're": "We are",
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
                (_FIRST_PERSON.match(_strip_temporal_affixes(clause)) or include_directives and _DIRECTIVE.match(clause))
                and not clause.endswith("?")
                and not _HYPOTHETICAL.search(clause)
                and not re.search(r"\b(?:says|said|told|claims|believes|according to)\b", clause, re.I)
                and not re.match(r"I\s+(?:said|wrote|quoted|read|asked|ran|clicked|opened|mean|meant|want\s+you|need\s+you)\b", clause, re.I)
                and not re.search(r'["“”`]|(?:^|\s)[\'‘].+?[\'’](?:\s|$)', clause)
            ):
                clauses.append(clause)
    return list(dict.fromkeys(clauses))


_DURABLE_PREDICATES = frozenset({
    "residence", "has_pet", "has_family", "breed", "count", "expense", "education",
    "milestone", "like", "dislike", "love", "hate", "prefer", "own", "use", "speak",
    "know", "allergic_to", "has_allergy", "has_hobby", "has_interest", "is_a", "name",
    "work_at", "work_for", "work_as", "study_at", "study", "studies", "studied",
    "decided_to", "plan_to", "intend_to", "committed_to", "promised_to",
    "timezone", "time_zone", "occupation", "profession", "job", "birthday",
    "first_name", "last_name", "pronouns", "preferred_language", "native_language",
    "favorite_color", "favourite_colour", "favorite_editor", "preferred_editor",
})


def _durable_direct_fact(fact) -> bool:
    """Require a personal attribute, relationship, preference, or commitment.

    The open-domain extractor intentionally accepts operational SVO for other
    uses; automatic durable user memory has a narrower evidence contract.
    """
    return assertion_predicate_key(fact.predicate)[0] in _DURABLE_PREDICATES



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
        facts.assertions = [fact for fact in facts.assertions if _durable_direct_fact(fact)]
        supported_entities = {(fact.subject, fact.object) for fact in facts.assertions}
        facts.relations = [relation for relation in facts.relations
                           if (relation.source, relation.target) in supported_entities
                           or any(fact.predicate == "has_pet" and relation.source == fact.object
                                  for fact in facts.assertions)]
        for fact in facts.assertions:
            identity = ["direct-user-assertion", tenant_id, source.user_id, branch, cid,
                        fact.subject, fact.predicate, fact.object, fact.scope]
            fact.id = str(uuid5(NAMESPACE_URL, json.dumps(identity, sort_keys=True)))
            fact.calibration["source_quote"] = clause
            fact.calibration["projection_kind"] = "direct_user"
            fact.calibration["projection_version"] = 2
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
        stored_assertions = engine.export_tenant(tenant_id)["assertions"]
        for relation in facts.relations:
            supporting_rows = [row for row in stored_assertions
                               if row["id"] in result["assertion_ids"]
                               and row["subject"] == relation.source and row["object"] == relation.target]
            if supporting_rows and all(row["status"] not in {"active", "contested"} for row in supporting_rows):
                from mnemosyne.models import parse_dt
                ends = [parse_dt(row.get("valid_to")) for row in supporting_rows]
                if any(end is None for end in ends):
                    continue
                relation.valid_to = max(ends)
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


def preview_direct_user_memory(engine, tenant_id: str, cid: str, branch: str = "main") -> dict:
    """Plan a source-preserving repair without writing to the supplied engine.

    Only single-source, deterministically identified direct-user projections
    are proposed for retirement. Shared claims and manual replacements require
    review and are never silently relabeled as automatic projections.
    """
    from copy import deepcopy
    from mnemosyne.engine import LocalMemoryEngine

    report = {"source_cid": cid, "reason": "ineligible_source", "assertions": [],
              "relations": [], "obsolete_assertion_ids": [], "obsolete_relation_ids": []}
    source = engine.get_evidence(tenant_id, cid, branch=branch)
    if source is None or not _eligible_user_source(source):
        return report
    if not projection_sources_readable(
        engine, [cid], tenant_id=tenant_id, branch=branch,
        filt={"tenant_id": tenant_id, "user_id": source.user_id, "principal": source.user_id},
        policy=engine.policy,
    ):
        return report
    scratch = LocalMemoryEngine()
    if branch != "main":
        scratch.branches[branch] = {"from": "main", "kind": "repair_preview"}
    scratch.evidence[scratch._evidence_key(tenant_id, branch, cid)] = deepcopy(source)
    projected = project_direct_user_memory(scratch, tenant_id, cid, branch)
    expected = scratch.export_tenant(tenant_id)
    for row in expected["assertions"]:
        row.pop("transaction_time", None)  # assigned by the eventual writer, not part of the plan
    report.update(reason=projected["reason"], assertions=expected["assertions"], relations=expected["relations"])
    retained = engine.export_tenant(tenant_id)
    expected_ids = {row["id"] for row in expected["assertions"] + expected["relations"]}
    for kind in ("assertions", "relations"):
        for row in retained[kind]:
            if row.get("branch", "main") != branch or row.get("source_evidence_cids") != [cid]:
                continue
            if kind == "assertions":
                if row.get("user_id") != source.user_id or not row.get("calibration", {}).get("source_quote"):
                    continue
                identity = ["direct-user-assertion", tenant_id, source.user_id, branch, cid,
                            row["subject"], row["predicate"], row["object"], row.get("scope", {})]
                identifier = str(uuid5(NAMESPACE_URL, json.dumps(identity, sort_keys=True)))
            else:
                identity = ["direct-user-relation", tenant_id, source.user_id, branch, cid,
                            row["source"], row["predicate"], row["target"]]
                identifier = str(uuid5(NAMESPACE_URL, json.dumps(identity)))
            if row["id"] == identifier and identifier not in expected_ids:
                report["obsolete_assertion_ids" if kind == "assertions" else "obsolete_relation_ids"].append(identifier)
    for key in ("obsolete_assertion_ids", "obsolete_relation_ids"):
        report[key].sort()
    return report
