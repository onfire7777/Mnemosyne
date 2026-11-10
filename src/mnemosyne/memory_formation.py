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
from mnemosyne.semantic_memory import build_semantic_projection, semantic_metadata, source_spans, is_owned_entity_clause
from mnemosyne.commitment_memory import commitment_changes, project_commitment_memory


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
        and metadata.get("reality_class") not in {"self_generated", "simulated", "externally_suggested", "external"}
        and (deadline is None or deadline > utc_now())
    )


def memory_source_clauses(source_or_text) -> list[str]:
    """Return original unquoted clauses; interpretation applies its own gates."""
    if isinstance(source_or_text, str):
        text = source_or_text
    else:
        if not _eligible_user_source(source_or_text):
            return []
        text = source_or_text.content
    if re.search(r"<(?:instructions?|system|developer|environment_context)\b|^\s*#\s*AGENTS\.md\b", text, re.I | re.M):
        return []
    quoted_lines = set()
    quote_pattern = r'''"[^"]*"|“[^”]*”|(?<!\w)'(?:[^']|'(?=\w))*'(?!\w)|‘[^’]*’'''
    for match in re.finditer(quote_pattern, text, re.S):
        # Preserve short, inline quoted names/labels. Complete quoted claims,
        # multiline quotations and reported speech are never user facts.
        inner = match[0][1:-1]
        prefix = text[text.rfind("\n", 0, match.start()) + 1:match.start()]
        is_label = (bool(prefix.strip()) and "\n" not in inner and len(inner) <= 80
                    and not re.search(r"[.!?;:]|\b(?:I|we|you|he|she|they|it|is|are|am|was|were|will|must|should|please|ignore)\b", inner, re.I)
                    and not re.search(r"\b(?:said|says|wrote|reads?|quote|example|prompt|instructions?|according)\b", prefix, re.I))
        if not is_label:
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
            if clause and not clause.endswith("?") and "`" not in clause:
                clauses.append(clause)
    return list(dict.fromkeys(clauses))



def direct_user_clauses(source_or_text, *, include_directives: bool = False) -> list[str]:
    """Return original declarative clauses, omitting quoted or uncertain prose."""
    return [clause for clause in memory_source_clauses(source_or_text) if (
        (_FIRST_PERSON.match(_strip_temporal_affixes(clause)) or include_directives and _DIRECTIVE.match(clause))
        and not _HYPOTHETICAL.search(clause)
        and not re.search(r"\b(?:says|said|told|claims|believes|according to)\b", clause, re.I)
        and not re.match(r"I\s+(?:said|wrote|quoted|read|asked|ran|clicked|opened|mean|meant|want\s+you|need\s+you)\b", clause, re.I)
    )]


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


def _semantic_context(engine, source, snapshot) -> dict:
    from mnemosyne.entity_context import build_entity_context
    return build_entity_context(engine, source, snapshot, eligible=_eligible_user_source)



def project_direct_user_memory(
    engine, tenant_id: str, cid: str, branch: str = "main", *,
    semantic_proposer=None, semantic_reviewer=None, timezone: str | None = None, agent_id: str = "codex",
    session_id: str | None = None,
) -> dict:
    """Project trusted user evidence through the existing episodic extractor."""
    result = {"source_cid": cid, "assertion_ids": [], "relation_ids": [], "count": 0,
              "created_count": 0, "reason": "ineligible_source", "intention_ids": [],
              "unresolved": [], "rejected_proposals": [], "pending_reviews": []}
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
    all_clauses = memory_source_clauses(source)
    if not all_clauses:
        result["reason"] = "no_supported_direct_claim"
        return result
    snapshot = engine.export_tenant(tenant_id)
    retained_assertions = [row for row in snapshot["assertions"] if row.get("branch", "main") == branch]
    retained_relations = {row["id"] for row in snapshot["relations"] if row.get("branch", "main") == branch}
    batches = []
    timezone = timezone or source.metadata.get("timezone") or source.metadata.get("time_zone")
    commitments = commitment_changes(source, all_clauses, timezone)
    commitment_quotes = {item["span"].quote for item in commitments}
    for clause in clauses:
        if is_owned_entity_clause(clause):
            continue  # The entity projector owns canonical identity and project scope.
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
        if clause in commitment_quotes:
            for fact in facts.assertions:
                if assertion_predicate_key(fact.predicate)[0] in {"plan_to", "intend_to", "committed_to", "promised_to", "decided_to"}:
                    # Preserve the historical decision independently from the
                    # mutable current commitment. No invented completion time.
                    fact.status = "superseded"
                    fact.calibration.setdefault("qualifiers", {}).update({
                        "current_state": "represented_by_commitment", "end_known": False,
                    })
            facts.relations = []
        batches.append((clause, facts))
    semantic = build_semantic_projection(source, policy, all_clauses, proposer=semantic_proposer, reviewer=semantic_reviewer,
        supported_clauses={clause for clause, facts in batches if facts.assertions},
        context=_semantic_context(engine, source, snapshot))
    result["rejected_proposals"] = semantic.rejected
    # Recovery needs the review outcome even when the proposal itself was
    # retained in quarantine. Otherwise a transient provider failure would
    # look like a completed projection and never be retried.
    result["pending_reviews"] = [
        {key: verdict[key] for key in ("reason", "method", "error_type") if key in verdict}
        for fact in semantic.assertions
        if (verdict := fact.calibration.get("entailment_review"))
        and not verdict.get("entailed")
    ]
    # Each proposal already carries its exact original span.
    for fact in semantic.assertions:
        from mnemosyne.episodic_facts import ExtractedFacts
        relations = [rel for rel in semantic.relations if rel.source == fact.subject
                     and rel.predicate == fact.predicate and rel.target == fact.object]
        batches.append((fact.calibration["source_quote"], ExtractedFacts([fact], relations)))
    for clause, facts in batches:
        for fact in facts.assertions:
            identity = ["direct-user-assertion", tenant_id, source.user_id, branch, cid,
                        fact.subject, fact.predicate, fact.object, fact.scope]
            fact.id = str(uuid5(NAMESPACE_URL, json.dumps(identity, sort_keys=True)))
            span = source_spans(source, [clause])[0]
            metadata = semantic_metadata(source, span)
            metadata.update(fact.calibration)
            qualifiers = metadata.get("qualifiers", {})
            if qualifiers.get("occurrence_start"):
                metadata["event_time"] = {
                    "status": "resolved", "precision": qualifiers.get("temporal_precision", "unknown"),
                    "start": str(qualifiers["occurrence_start"]),
                    "end": str(qualifiers.get("occurrence_end") or ""), "wording": clause,
                }
            fact.calibration = metadata
            fact.calibration["projection_version"] = 3
            retained = next((row for row in retained_assertions if row["id"] == fact.id or (
                cid in row.get("source_evidence_cids", []) and row.get("user_id") == source.user_id
                and row["subject"] == fact.subject and row["predicate"] == fact.predicate
                and row["object"] == fact.object and row.get("scope", {}) == fact.scope
            )), None)
            if retained is None or retained.get("calibration", {}).get("reprojection_pending") == 3:
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
    prospective = project_commitment_memory(engine, source, policy, all_clauses,
        timezone=timezone, agent_id=agent_id, session_id=session_id)
    result["assertion_ids"].extend(identifier for identifier in prospective["assertion_ids"] if identifier not in result["assertion_ids"])
    result["intention_ids"] = prospective["intention_ids"]
    result["created_count"] += prospective["created_count"]
    result["unresolved"] = prospective["unresolved"]
    result["count"] = len(result["assertion_ids"]) + len(result["relation_ids"]) + len(result["intention_ids"])
    result["reason"] = "projected" if result["count"] else "no_supported_direct_claim"
    return result


def preview_direct_user_memory(
    engine, tenant_id: str, cid: str, branch: str = "main", *,
    semantic_proposer=None, semantic_reviewer=None, timezone: str | None = None, agent_id: str = "codex", session_id: str | None = None,
) -> dict:
    """Plan a source-preserving repair without writing to the supplied engine.

    Only single-source, deterministically identified direct-user projections
    are proposed for retirement. Shared claims and manual replacements require
    review and are never silently relabeled as automatic projections.
    """
    from copy import deepcopy
    from mnemosyne.engine import LocalMemoryEngine, Intention
    from mnemosyne.models import Assertion, parse_dt

    report = {"source_cid": cid, "reason": "ineligible_source", "assertions": [],
              "relations": [], "intentions": [], "cancelled_intention_ids": [], "unresolved": [],
              "obsolete_assertion_ids": [], "obsolete_relation_ids": []}
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
    retained = engine.export_tenant(tenant_id)
    context = _semantic_context(engine, source, retained)
    # Discourse boundaries are evidence too: dropping an intervening unrelated
    # turn from a preview would incorrectly resurrect a stale pronoun focus.
    for row in retained["evidence"]:
        if (row.get("user_id") == source.user_id and row.get("branch", "main") == branch
                and row.get("actor") == "user" and row.get("cid") != cid
                and parse_dt(row.get("created_at")) is not None
                and parse_dt(row["created_at"]) < source.created_at):
            prior_source = engine.get_evidence(tenant_id, row["cid"], branch=branch)
            if prior_source is not None:
                scratch.evidence[scratch._evidence_key(tenant_id, branch, row["cid"])] = deepcopy(prior_source)
    context_cids = {span.cid for spans in context.get("dependencies", {}).values() for span in spans}
    for dependency in context_cids:
        evidence = engine.get_evidence(tenant_id, dependency, branch=branch)
        if evidence is not None:
            scratch.evidence[scratch._evidence_key(tenant_id, branch, dependency)] = deepcopy(evidence)
    for row in retained["assertions"]:
        if (row.get("user_id") == source.user_id and row.get("branch", "main") == branch
                and row.get("source_evidence_cids") and set(row["source_evidence_cids"]) <= context_cids):
            scratch.assertions[scratch._branch_key(tenant_id, branch, row["id"])] = Assertion.from_dict(deepcopy(row))
    previous_ids = {row.get("calibration", {}).get("previous_assertion_id") for row in retained["assertions"]
                    if row.get("source_evidence_cids") == [cid] and row.get("user_id") == source.user_id}
    copied_intentions = set()
    if branch == "main":
        # Replay a lifecycle transition against its pre-transition state, in
        # the sandbox only. This makes cancellation/reschedule previews useful
        # both before their first application and after an interrupted replay.
        for row in retained["assertions"]:
            if row.get("user_id") != source.user_id or row.get("branch", "main") != branch or row["predicate"] != "commitment_state":
                continue
            if row.get("source_evidence_cids") == [cid] or row.get("calibration", {}).get("commitment_state") != "pending":
                continue
            if row["status"] != "active" and row["id"] not in previous_ids:
                continue
            if parse_dt(row.get("valid_from")) > source.created_at:
                continue
            dependencies = row.get("source_evidence_cids", [])
            if not projection_sources_readable(engine, dependencies, tenant_id=tenant_id, branch=branch,
                    filt={"tenant_id": tenant_id, "user_id": source.user_id, "principal": source.user_id}, policy=engine.policy):
                continue
            for dependency in dependencies:
                evidence = engine.get_evidence(tenant_id, dependency, branch=branch)
                if evidence is not None:
                    scratch.evidence[scratch._evidence_key(tenant_id, branch, dependency)] = deepcopy(evidence)
            copied = deepcopy(row)
            if row["id"] in previous_ids:
                copied.update(status="active", valid_to=None, superseded_by=None)
            scratch.assertions[scratch._branch_key(tenant_id, branch, row["id"])] = Assertion.from_dict(copied)
            intention_id = row.get("calibration", {}).get("intention_id")
            for item in engine.list_intentions(tenant_id):
                if item.intention_id != intention_id:
                    continue
                intention = item.to_dict()
                if row["id"] in previous_ids and item.status == "cancelled":
                    intention.update(status="scheduled", cancellation_state=None)
                scratch.intentions[(tenant_id, item.intention_id)] = Intention.from_dict(intention)
                copied_intentions.add(item.intention_id)
    projected = project_direct_user_memory(scratch, tenant_id, cid, branch, semantic_proposer=semantic_proposer, semantic_reviewer=semantic_reviewer,
        timezone=timezone, agent_id=agent_id, session_id=session_id)
    expected = scratch.export_tenant(tenant_id)
    expected["assertions"] = [row for row in expected["assertions"] if row["id"] in projected["assertion_ids"]]
    expected["relations"] = [row for row in expected["relations"] if row["id"] in projected["relation_ids"]]
    for row in expected["assertions"]:
        row.pop("transaction_time", None)  # assigned by the eventual writer, not part of the plan
    report.update(reason=projected["reason"], assertions=expected["assertions"], relations=expected["relations"],
                  intentions=[item.to_dict() for item in scratch.list_intentions(tenant_id) if item.intention_id in projected["intention_ids"]],
                  cancelled_intention_ids=[item.intention_id for item in scratch.list_intentions(tenant_id)
                                           if item.intention_id in copied_intentions and item.status == "cancelled"],
                  unresolved=projected["unresolved"])
    expected_ids = {row["id"] for row in expected["assertions"] + expected["relations"]}
    for kind in ("assertions", "relations"):
        for row in retained[kind]:
            if row.get("branch", "main") != branch or cid not in row.get("source_evidence_cids", []):
                continue
            if kind == "assertions":
                if row.get("user_id") != source.user_id or not row.get("calibration", {}).get("source_quote"):
                    continue
                if row.get("source_evidence_cids") != [cid] and not row.get("calibration", {}).get("coreference"):
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


def reproject_direct_user_memory(engine, tenant_id: str, cid: str, branch: str = "main", **options) -> dict:
    """Apply a versioned preview, retiring only this source's automatic outputs.

    Manual/shared assertions and already superseded user corrections are never
    revived. A durable pending marker permits retries after interruption between
    invalidation and regeneration. Raw evidence is not modified.
    """
    from copy import deepcopy
    from mnemosyne.models import Assertion, Relation

    for option, method in (("semantic_proposer", "propose_memory"), ("semantic_reviewer", "review_memory_entailment")):
        provider = options.get(option)
        if provider is None:
            continue
        def cached(payload, _provider=provider, _method=method, _responses=None, _failures=None):
            key = json.dumps(payload, sort_keys=True)
            if key in _failures:
                raise _failures[key]
            if key not in _responses:
                try:
                    call = getattr(_provider, _method, _provider)
                    _responses[key] = call(payload)
                except Exception as error:
                    _failures[key] = error
                    raise
            return deepcopy(_responses[key])
        from functools import partial
        options[option] = partial(cached, _responses={}, _failures={})
    preview = preview_direct_user_memory(engine, tenant_id, cid, branch, **options)
    if preview["reason"] == "ineligible_source":
        return {"preview": preview, "applied": False, "retired_assertion_ids": [], "retired_relation_ids": []}
    retained = engine.export_tenant(tenant_id)
    expected = {row["id"]: row for row in preview["assertions"]}
    changed = set(preview["obsolete_assertion_ids"])
    retired = []
    for row in retained["assertions"]:
        if cid not in row.get("source_evidence_cids", []) or row.get("branch", "main") != branch:
            continue
        if row.get("source_evidence_cids") != [cid] and not row.get("calibration", {}).get("coreference"):
            continue
        replacement = expected.get(row["id"])
        # The UUID contract makes this distinction independent of mutable
        # labels. A manual assertion with the same text remains manual.
        identity = ["direct-user-assertion", tenant_id, row.get("user_id"), branch, cid,
                    row["subject"], row["predicate"], row["object"], row.get("scope", {})]
        if row["id"] != str(uuid5(NAMESPACE_URL, json.dumps(identity, sort_keys=True))):
            continue
        automatic = row.get("calibration", {}).get("projection_kind") in {None, "direct_user"} and row.get("calibration", {}).get("source_quote")
        if not automatic:
            continue
        pending = row.get("calibration", {}).get("reprojection_pending") == 3
        if replacement and (row["status"] in {"active", "contested"} or pending) and (
            row.get("calibration", {}).get("projection_version", 0) < 3 or row["status"] != replacement["status"] or pending
            or row.get("calibration", {}).get("derivation_version") != replacement.get("calibration", {}).get("derivation_version")
            or row.get("source_evidence_cids") != replacement.get("source_evidence_cids")
        ):
            changed.add(row["id"])
        if row["id"] not in changed:
            continue
        tombstone = deepcopy(row)
        tombstone["status"] = "retracted"
        tombstone["expired_at"] = utc_now().isoformat()
        tombstone.setdefault("calibration", {})["reprojection_pending"] = 3 if replacement else None
        tombstone["calibration"]["reprojection_reason"] = "source_projection_v3"
        engine.upsert_assertion(Assertion.from_dict(tombstone), branch=branch)
        retired.append(row["id"])
    retired_relations = []
    expected_relations = {row["id"]: row for row in preview["relations"]}
    changed_pairs = {(row["subject"], row["object"]) for row in retained["assertions"] if row["id"] in changed}
    for row in retained["relations"]:
        if cid not in row.get("source_evidence_cids", []) or row.get("branch", "main") != branch:
            continue
        if row["id"] not in preview["obsolete_relation_ids"] and (row["source"], row["target"]) not in changed_pairs:
            continue
        identity = ["direct-user-relation", tenant_id, engine.get_evidence(tenant_id, cid, branch=branch).user_id,
                    branch, cid, row["source"], row["predicate"], row["target"]]
        if row["id"] != str(uuid5(NAMESPACE_URL, json.dumps(identity))):
            continue
        tombstone = deepcopy(row)
        # Serving expiry is a repair timestamp, not an invented world-time end.
        tombstone.setdefault("access_policy", {})["expires_at"] = utc_now().isoformat()
        engine.add_relation(Relation.from_dict(tombstone), branch=branch)
        retired_relations.append(row["id"])
    applied = project_direct_user_memory(engine, tenant_id, cid, branch, **options)
    current = engine.export_tenant(tenant_id)["assertions"]
    for identifier in retired_relations:
        replacement = expected_relations.get(identifier)
        if replacement and any(row["status"] in {"active", "contested"} and row["subject"] == replacement["source"]
                               and row["object"] == replacement["target"] and cid in row.get("source_evidence_cids", []) for row in current):
            engine.add_relation(Relation.from_dict(replacement), branch=branch)
    return {"preview": preview, "applied": True, "projection": applied,
            "retired_assertion_ids": retired, "retired_relation_ids": retired_relations}
