"""Evidence-backed entity identity and discourse focus, reconstructed as of a source.

No name cache is authoritative. Every resolution rechecks owner, branch, source
spans, current privacy and the source-time boundary; a later turn cannot rewrite
an earlier turn during replay.
"""
from __future__ import annotations

import re

from mnemosyne.access_policy import evidence_expiry_deadline, may_read_item
from mnemosyne.models import parse_dt
from mnemosyne.retrieval import projection_sources_readable


_SCOPE_KEYS = ("entity_scope", "project_id", "workspace_id", "workspace", "project_root")
_NEUTRAL = re.compile(r"^(?:please\s+)?(?:continue|go on|carry on|proceed|keep going|okay|ok|thanks|thank you)[.!\s]*$", re.I)


def source_entity_scope(source) -> dict:
    """Use recorded scope, never current process settings or a transcript path."""
    metadata = source.metadata if hasattr(source, "metadata") else source.get("metadata", {})
    for key in _SCOPE_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return {key: value.strip()}
    return {}


def build_entity_context(engine, source, snapshot, *, eligible) -> dict:
    from mnemosyne.semantic_memory import SourceSpan

    scope = source_entity_scope(source)
    context = {"entities": {}, "aliases": {}, "roles": {}, "dependencies": {}, "policies": {},
               "trust_tiers": {}, "sensitivities": {}, "focus": [], "focus_dependencies": {}, "focus_policies": {},
               "focus_trust_tiers": {}, "focus_sensitivities": {}, "ambiguous_names": [], "scope": scope}
    read_context = {"tenant_id": source.tenant_id, "user_id": source.user_id, "principal": source.user_id}
    evidence_cache = {}

    def evidence(cid):
        if cid not in evidence_cache:
            evidence_cache[cid] = engine.get_evidence(source.tenant_id, cid, source.branch)
        return evidence_cache[cid]

    records, mentioned_by_source = [], {}
    for row in snapshot["assertions"]:
        meta = row.get("calibration", {})
        if (row.get("user_id") != source.user_id or row.get("branch", "main") != source.branch
                or row.get("status") not in {"active", "superseded"}
                or meta.get("epistemic_class") != "direct_user"
                or meta.get("reprojection_pending") or meta.get("temporal_context") == "historical"):
            continue
        end = parse_dt(row.get("valid_to"))
        if end is not None and end <= source.created_at:
            continue
        spans, policies, sources = [], [row.get("access_policy", {})], []
        cids = row.get("source_evidence_cids", [])
        if not cids or len(cids) > 32 or source.cid in cids:
            continue
        if not may_read_item(item_tenant_id=source.tenant_id, sensitivity=row.get("sensitivity", 0),
                access_policy=row.get("access_policy", {}), context=read_context,
                policy_max_sensitivity=engine.policy.max_sensitivity, status="active", erased=False).allowed:
            continue
        if not projection_sources_readable(engine, cids, tenant_id=source.tenant_id, branch=source.branch,
                filt=read_context, policy=engine.policy):
            continue
        for item in meta.get("source_spans", []):
            dependency = evidence(item.get("cid"))
            if (dependency is None or dependency.user_id != source.user_id or not eligible(dependency)
                    or dependency.created_at >= source.created_at or source_entity_scope(dependency) != scope
                    or type(item.get("start")) is not int or type(item.get("end")) is not int
                    or not 0 <= item["start"] < item["end"] <= len(dependency.content)
                    or dependency.content[item["start"]:item["end"]] != item.get("quote")):
                spans = []
                break
            spans.append(SourceSpan(item["cid"], item["start"], item["end"], item["quote"]))
            policies.append(dependency.access_policy)
            deadline = evidence_expiry_deadline(dependency.access_policy, dependency.metadata)
            if deadline is not None:
                policies.append({"expires_at": deadline.isoformat()})
            sources.append(dependency)
        if not spans or set(cids) - {span.cid for span in spans}:
            continue
        primary = sources[0]
        names = [name for name in meta.get("entity_mentions", []) if isinstance(name, str) and name not in {"user", "I", "We"}]
        mentioned_by_source.setdefault(primary.cid, set()).update(names)
        records.append((primary.created_at, row["id"], row, spans, policies, primary))

    # Prefer explicit introductions to dependent attribute statements. Each
    # name's identity needs its own original evidence, not an ever-growing
    # chain of every intervening attribute.
    records.sort(key=lambda item: (item[0], item[1]))
    alias_rows = []
    for _, _, row, spans, policies, primary in records:
        meta = row["calibration"]
        if row["predicate"] == "entity_alias":
            alias_rows.append((row, spans, policies))
            continue
        for name in meta.get("entity_mentions", []):
            if not isinstance(name, str) or not name or name in {"user", "I", "We"}:
                continue
            if name not in context["entities"]:
                context["entities"][name] = spans[0]
                context["dependencies"][name] = spans
                context["policies"][name] = policies
                context["trust_tiers"][name] = row.get("trust_tier", 1)
                context["sensitivities"][name] = row.get("sensitivity", 0)
                context["aliases"][name] = name
            if row["subject"] == "user" and row["object"] == name:
                role = row["predicate"].removeprefix("has_").replace("_", " ")
                context["roles"].setdefault(role, set()).add(name)
    # Alias evidence is independently retained and checked. A shared spelling
    # never silently unifies two entities.
    for row, spans, policies in alias_rows:
        canonical, alias = row["subject"], row["object"]
        if canonical not in context["entities"]:
            continue
        existing = context["aliases"].get(alias)
        if existing is not None and existing != canonical:
            context["ambiguous_names"].append(alias)
            context["aliases"].pop(alias, None)
            continue
        if alias in context["ambiguous_names"]:
            continue
        context["aliases"][alias] = canonical
        context["entities"][alias] = spans[0]
        context["dependencies"][alias] = list(dict.fromkeys([*context["dependencies"][canonical], *spans]))
        context["policies"][alias] = [*context["policies"][canonical], *policies]
        context["trust_tiers"][alias] = max(context["trust_tiers"][canonical], row.get("trust_tier", 1))
        context["sensitivities"][alias] = max(context["sensitivities"][canonical], row.get("sensitivity", 0))
    context["roles"] = {role: sorted(names) for role, names in context["roles"].items()}

    previous = [row for row in snapshot["evidence"] if row.get("cid") != source.cid
                and row.get("user_id") == source.user_id and row.get("actor") == "user"
                and row.get("branch", "main") == source.branch and source_entity_scope(row) == scope
                and parse_dt(row.get("created_at")) is not None and parse_dt(row["created_at"]) < source.created_at]
    in_session = [row for row in previous if row.get("session_id") == source.session_id]
    # Cross-session bare references need an explicitly recorded project scope.
    focus_sources = in_session or (previous if scope else [])
    for row in sorted(focus_sources, key=lambda item: (parse_dt(item["created_at"]), item["cid"]), reverse=True):
        if _NEUTRAL.fullmatch(row.get("content", "").strip()):
            continue
        names = mentioned_by_source.get(row["cid"], set())
        context["focus"] = sorted({context["aliases"].get(name, name) for name in names
                                    if name in context["entities"] and name not in context["ambiguous_names"]})
        for _, _, assertion, spans, policies, primary in records:
            if primary.cid != row["cid"]:
                continue
            meta = assertion["calibration"]
            # A pronoun bridge carries its prior focus proof forward without
            # requiring every intervening attribute statement forever.
            if re.match(r"^It\s+", meta.get("source_quote", ""), re.I):
                proof = [span for span in spans if span.to_dict() in meta.get("antecedent_spans", [])]
                proof = proof or spans
            else:
                proof = spans
            for name in meta.get("entity_mentions", []):
                canonical = context["aliases"].get(name, name)
                if canonical not in context["focus"]:
                    continue
                context["focus_dependencies"][canonical] = list(dict.fromkeys([
                    *context["dependencies"].get(canonical, []), *proof]))
                context["focus_policies"][canonical] = [*context["policies"].get(canonical, []), *policies]
                context["focus_trust_tiers"][canonical] = assertion.get("trust_tier", 1)
                context["focus_sensitivities"][canonical] = assertion.get("sensitivity", 0)
        break
    return context
