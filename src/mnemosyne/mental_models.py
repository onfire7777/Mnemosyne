"""Private, revisioned saved answers over the existing grounded reader.

Models are advisory application records, never evidence. Freshness uses the
authorized branch corpus rather than only old citations, so new corrections can
invalidate an answer. Clean reads need neither a reader nor an embedding call.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from mnemosyne.answering import (
    AnswerLimits,
    AnswerReadContext,
    AnswerRequest,
    GroundedAnswerOrchestrator,
    public_grounded_answer,
)
from mnemosyne.retrieval import classify_scoped_evidence, derived_source_cids, query_time_window
from mnemosyne.mental_model_refresh import (
    cancel_lease,
    new_schedule,
    public_schedule,
    require_lease,
    trigger_on_consolidation,
)

_TELEMETRY = frozenset({"access_count", "last_accessed", "last_accessed_at", "salience"})
_COLLECTIONS = ("evidence", "assertions", "relations", "preferences")
_MAX_HISTORY = 32
_STATES = {"pending", "ready", "stale", "error", "abstained"}

_DEP_STOPWORDS = frozenset({
    "a", "about", "after", "all", "also", "an", "and", "any", "are", "as", "at",
    "be", "because", "been", "before", "being", "between", "both", "but", "by",
    "can", "could", "current", "currently", "did", "do", "does", "doing", "done",
    "during", "each", "either", "for", "from", "had", "has", "have", "having",
    "he", "her", "here", "hers", "him", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "just", "last", "many", "may", "me", "might", "more",
    "most", "much", "must", "my", "neither", "new", "next", "no", "nor", "not",
    "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours",
    "out", "over", "own", "same", "she", "should", "since", "so", "some", "such",
    "than", "that", "the", "their", "theirs", "them", "then", "there", "these",
    "they", "this", "those", "through", "to", "today", "too", "under", "until",
    "up", "upon", "us", "very", "was", "we", "were", "what", "when", "where",
    "which", "while", "who", "whom", "whose", "why", "will", "with", "within",
    "without", "would", "you", "your", "yours",
})

_PREDICATE_TERMS = frozenset({
    "address", "assigned", "authored", "belongs", "branch", "built", "changed",
    "color", "configured", "connected", "contains", "count", "created", "database",
    "date", "deadline", "depends", "deployed", "deployment", "deploys", "deprecated",
    "disabled", "email", "enabled", "endpoint", "environment", "error", "failed",
    "framework", "frequency", "health", "host", "hosted", "hosts", "implemented",
    "includes", "installed", "language", "latency", "lead", "level", "limit",
    "located", "location", "maintained", "maintains", "managed", "manager", "manages",
    "member", "migrated", "mode", "model", "modified", "moved", "name", "number",
    "operated", "operates", "owned", "owner", "owns", "path", "phone", "plan",
    "policy", "port", "prefer", "preference", "prefers", "price", "priority",
    "promoted", "protocol", "provider", "published", "quota", "rate", "region",
    "released", "replaced", "replaces", "reported", "reports", "requires", "resolved",
    "retention", "role", "route", "runs", "schedule", "scheduled", "schema", "scope",
    "service", "size", "stage", "start", "state", "status", "storage", "stored",
    "stores", "strategy", "succeeded", "Summary", "summary", "supports", "switched",
    "system", "target", "team", "tier", "time", "timeout", "title", "tool", "total",
    "type", "updated", "upgraded", "url", "use", "used", "uses", "using", "value",
    "version", "workflow", "works", "zone",
})


@dataclass(slots=True)
class MentalModelRecord:
    """Lightweight representation of a mental model with dependency metadata."""

    model_id: str
    question: str
    name: str = ""
    answer: str | dict[str, Any] | None = None
    source_evidence_cids: list[str] = field(default_factory=list)
    dependent_entities: list[str] = field(default_factory=list)
    dependent_predicates: list[str] = field(default_factory=list)
    dependent_cids: list[str] = field(default_factory=list)
    status: str = "ready"
    version: int = 1


def _normalize_dep_token(raw: str) -> str:
    token = raw.strip().strip(".,;:!?()[]{}'\"`")
    if token.lower().endswith("'s") or token.lower().endswith("’s"):
        token = token[:-2]
    return token.lower()


def _extract_tokens_from_text(text: str) -> tuple[list[str], list[str]]:
    """Return (entities, predicates) extracted from text."""
    if not isinstance(text, str) or not text.strip():
        return [], []
    entities: list[str] = []
    predicates: list[str] = []
    seen_ent: set[str] = set()
    seen_pred: set[str] = set()

    # Match hyphenated/underscored/dotted identifiers and words
    raw_Matches = re.findall(r"[A-Za-z0-9]+(?:[-_./][A-Za-z0-9]+)*", text)
    for idx, raw in enumerate(raw_Matches):
        norm = _normalize_dep_token(raw)
        if not norm or len(norm) < 2 or norm in _DEP_STOPWORDS:
            continue
        is_compound_id = any(sep in norm for sep in ("-", "_", ".", "/")) or any(ch.isdigit() for ch in norm)
        is_capitalized_mid_sentence = idx > 0 and raw[0].isupper()
        if norm in _PREDICATE_TERMS and not is_compound_id and not is_capitalized_mid_sentence:
            if norm not in seen_pred:
                seen_pred.add(norm)
                predicates.append(norm)
        elif len(norm) >= 3 or is_compound_id or is_capitalized_mid_sentence:
            if norm not in seen_ent:
                seen_ent.add(norm)
                entities.append(norm)
            # Compound identifiers also contribute their sub-parts if specific
            if is_compound_id:
                for part in re.split(r"[-_./]+", norm):
                    if len(part) >= 3 and part not in _DEP_STOPWORDS and part not in _PREDICATE_TERMS:
                        if part not in seen_ent:
                            seen_ent.add(part)
                            entities.append(part)
    return entities, predicates


def extract_model_dependencies(
    question: str,
    answer_text: str | Mapping[str, Any] | None = "",
    source_cids: Sequence[str] = (),
) -> dict[str, Any]:
    """Extract dependent entities, predicates, and source CIDs from a mental model."""
    q_text = question if isinstance(question, str) else ""
    a_text = ""
    extra_cids: list[str] = []
    if isinstance(answer_text, Mapping):
        raw_ans = answer_text.get("answer")
        if isinstance(raw_ans, str):
            a_text = raw_ans
        claims = answer_text.get("claims")
        if isinstance(claims, list):
            claim_texts: list[str] = []
            for claim in claims:
                if isinstance(claim, Mapping):
                    if isinstance(claim.get("text"), str):
                        claim_texts.append(claim["text"])
                    for cid in claim.get("evidence_cids", []) or []:
                        if isinstance(cid, str) and cid:
                            extra_cids.append(cid)
            if claim_texts and not a_text:
                a_text = "\n".join(claim_texts)
    elif isinstance(answer_text, str):
        a_text = answer_text

    q_entities, q_predicates = _extract_tokens_from_text(q_text)
    a_entities, a_predicates = _extract_tokens_from_text(a_text)

    entities = list(dict.fromkeys([*q_entities, *a_entities]))
    predicates = list(dict.fromkeys([*q_predicates, *a_predicates]))
    if not entities and predicates:
        entities = list(predicates)

    cids: list[str] = []
    for cid in [*source_cids, *extra_cids]:
        if isinstance(cid, str) and cid.strip() and cid.strip() not in cids:
            cids.append(cid.strip())

    return {
        "dependent_entities": entities,
        "dependent_predicates": predicates,
        "dependent_cids": cids,
        "question_entities": q_entities,
        "entities": entities,
        "predicates": predicates,
        "cids": cids,
    }


def is_affected_by_evidence(
    model: MentalModelRecord | Mapping[str, Any] | Any,
    new_evidence_content: str,
    new_evidence_cid: str | None = None,
) -> bool:
    """Return True when new evidence intersects a mental model's dependencies."""
    if isinstance(model, Mapping):
        question = str(model.get("question") or "")
        answer_val = model.get("answer")
        source_cids = list(model.get("source_evidence_cids") or [])
        explicit_entities = [
            _normalize_dep_token(str(e))
            for e in (model.get("dependent_entities") or [])
            if str(e).strip()
        ]
        explicit_predicates = [
            _normalize_dep_token(str(p))
            for p in (model.get("dependent_predicates") or [])
            if str(p).strip()
        ]
        explicit_cids = [
            str(c).strip()
            for c in (model.get("dependent_cids") or [])
            if str(c).strip()
        ]
    else:
        question = str(getattr(model, "question", "") or "")
        answer_val = getattr(model, "answer", None)
        source_cids = list(getattr(model, "source_evidence_cids", []) or [])
        explicit_entities = [
            _normalize_dep_token(str(e))
            for e in (getattr(model, "dependent_entities", []) or [])
            if str(e).strip()
        ]
        explicit_predicates = [
            _normalize_dep_token(str(p))
            for p in (getattr(model, "dependent_predicates", []) or [])
            if str(p).strip()
        ]
        explicit_cids = [
            str(c).strip()
            for c in (getattr(model, "dependent_cids", []) or [])
            if str(c).strip()
        ]

    deps = extract_model_dependencies(question, answer_val, [*source_cids, *explicit_cids])
    all_cids = set(deps["dependent_cids"]) | set(explicit_cids) | set(source_cids)
    if isinstance(new_evidence_cid, str) and new_evidence_cid.strip() and new_evidence_cid.strip() in all_cids:
        return True

    if not isinstance(new_evidence_content, str) or not new_evidence_content.strip():
        return False

    ev_entities, ev_predicates = _extract_tokens_from_text(new_evidence_content)
    ev_tokens = set(ev_entities) | set(ev_predicates)
    ev_lower = new_evidence_content.lower()

    def _matches_token(target: str) -> bool:
        if not target:
            return False
        if target in ev_tokens:
            return True
        if any(sep in target for sep in ("-", "_", ".", "/", " ")):
            return target in ev_lower
        if len(target) >= 5:
            stem = target[:5]
            if any(tok.startswith(stem) or stem.startswith(tok[:5]) for tok in ev_tokens if len(tok) >= 5):
                return True
        return False

    # Subject entities from the question (or explicit dependent_entities) are the primary anchor.
    anchor_entities = list(dict.fromkeys([*explicit_entities, *deps["question_entities"]]))
    if not anchor_entities:
        anchor_entities = list(deps["dependent_entities"])

    if anchor_entities:
        return any(_matches_token(ent) for ent in anchor_entities)

    predicates = list(dict.fromkeys([*explicit_predicates, *deps["dependent_predicates"]]))
    return any(_matches_token(pred) for pred in predicates)


def _question_clock(question: str, context: AnswerReadContext) -> str | None:
    now = context.as_of or datetime.now(UTC)
    window = query_time_window(question, now)
    if window is not None:
        if context.as_of is None and window.end == now:
            raise ValueError("moving-window mental model questions require an explicit as_of")
        return _digest([window.start.isoformat(), window.end.isoformat()])
    if re.search(r"\b(today|tonight|yesterday|tomorrow|this week|last week)\b", question, re.I):
        return now.astimezone().date().isoformat()
    if re.search(r"\b(now|currently|last \d+ (?:hours?|minutes?))\b", question, re.I):
        if context.as_of is None:
            raise ValueError("moving-window mental model questions require an explicit as_of")
        return now.isoformat()
    return None


def _reader_disclosure(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {"model", "provider", "selector", "content_sha256", "artifact_sha256",
               "configuration_sha256", "protocol"}
    return {role: {key: item for key, item in fields.items()
                   if key in allowed and isinstance(item, str) and len(item) <= 256}
            for role, fields in value.items()
            if role in {"query_decomposer", "grounded_reader"} and isinstance(fields, dict)}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False, default=lambda item: item.isoformat() if isinstance(item, datetime) else _invalid_json(item))


def _invalid_json(value: Any) -> Any:
    raise ValueError(f"unsupported model value: {type(value).__name__}")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _stable(item) for key, item in value.items() if key not in _TELEMETRY}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    return value


def _text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be non-empty text of at most {limit} characters")
    return value.strip()


def _scope(context: AnswerReadContext) -> dict[str, Any]:
    if not isinstance(context, AnswerReadContext):
        raise ValueError("mental models require an answer read context")
    _text(context.tenant_id, "tenant_id", 512)
    _text(context.branch, "branch", 512)
    _text(context.user_id, "user_id", 512)
    if context.break_glass:
        raise ValueError("mental models cannot persist break-glass access")
    value = json.loads(_canonical(context.to_filter()))
    for key in ("capability_tags", "purpose", "lawful_basis"):
        if key in value:
            value[key] = sorted(set(value[key]))
    return value


class MentalModelService:
    """Maintain scoped saved answers with optimistic publication checks."""

    def __init__(self, engine: Any, provider_factory: Callable[[], Any] | None = None):
        self.engine = engine
        self.provider_factory = provider_factory
        self._snapshot_cache: dict[tuple[str, str, str, str | None], tuple[str, datetime | None, tuple[str, dict[str, dict[str, Any]]]]] = {}

    def _get_cache(self) -> dict[Any, Any]:
        if not hasattr(self.engine, "_mental_model_snapshot_cache"):
            try:
                self.engine._mental_model_snapshot_cache = {}
            except (AttributeError, TypeError):
                return self._snapshot_cache
        return self.engine._mental_model_snapshot_cache

    def clear_watermark_cache(self) -> None:
        """Clear the snapshot digest cache for all tenants and branches."""
        self._snapshot_cache.clear()
        if hasattr(self.engine, "_mental_model_snapshot_cache"):
            try:
                self.engine._mental_model_snapshot_cache.clear()
            except Exception:
                pass

    def invalidate_watermark(self, tenant_id: str | None = None, branch: str | None = None) -> None:
        """Invalidate cached snapshots matching tenant_id and branch (or all if None)."""
        cache = self._get_cache()
        to_del = [
            k for k in list(cache)
            if (tenant_id is None or k[0] == tenant_id) and (branch is None or k[1] == branch)
        ]
        for k in to_del:
            cache.pop(k, None)

    def mutation_watermark(self, context: AnswerReadContext) -> str:
        """Return the current lightweight branch/tenant mutation watermark digest.

        Tracks mutation sequence numbers, revision counters, collection sizes, deletion logs,
        merges, and security policy. Advances immediately on any write, erasure, rollback,
        privacy change, or branch merge.
        """
        return self._mutation_watermark(context)

    def _mutation_watermark(self, context: AnswerReadContext) -> str:
        engine = self.engine
        tenant_id = context.tenant_id
        branch = context.branch
        parts: list[Any] = [tenant_id, branch]

        if callable(getattr(engine, "mutation_watermark", None)):
            try:
                return str(engine.mutation_watermark(tenant_id, branch))
            except Exception:
                pass

        if hasattr(engine, "policy") and hasattr(engine.policy, "to_dict"):
            try:
                parts.append(engine.policy.to_dict())
            except Exception:
                pass

        if hasattr(engine, "_store_version"):
            parts.append(getattr(engine, "_store_version"))

        if hasattr(engine, "audit_log") and isinstance(engine.audit_log, list):
            parts.append(len(engine.audit_log))
            if engine.audit_log:
                parts.append(engine.audit_log[-1].get("id"))
                parts.append(engine.audit_log[-1].get("op"))
            parts.append(len(getattr(engine, "deletion_log", [])))
            if getattr(engine, "deletion_log", None):
                parts.append(engine.deletion_log[-1].get("id"))
            parts.append(len(getattr(engine, "merge_log", [])))
            if getattr(engine, "merge_log", None):
                parts.append(engine.merge_log[-1])
            parts.append((
                len(getattr(engine, "evidence", {})),
                len(getattr(engine, "assertions", {})),
                len(getattr(engine, "relations", {})),
                len(getattr(engine, "preferences", {})),
            ))
            if hasattr(engine, "branches") and isinstance(engine.branches, dict):
                parts.append(engine.branches.get(branch))

        elif hasattr(engine, "_connect") and callable(engine._connect):
            try:
                conn = engine._connect(tenant_id)
                with getattr(engine, "_lock", nullcontext()):
                    row = conn.execute(
                        """
                        SELECT
                            (SELECT MAX(seq) FROM audit_log WHERE tenant_id = ? OR tenant_id = '*'),
                            (SELECT COUNT(*) FROM audit_log WHERE tenant_id = ? OR tenant_id = '*'),
                            (SELECT MAX(seq) FROM deletion_log WHERE tenant_id = ? OR tenant_id = '*'),
                            (SELECT COUNT(*) FROM deletion_log WHERE tenant_id = ? OR tenant_id = '*'),
                            (SELECT MAX(seq) FROM merge_log WHERE tenant_id = ? OR tenant_id = '*'),
                            (SELECT COUNT(*) FROM evidence WHERE tenant_id = ? AND branch = ? AND erased = 0),
                            (SELECT COUNT(*) FROM assertions WHERE tenant_id = ? AND branch = ?),
                            (SELECT COUNT(*) FROM relations WHERE tenant_id = ? AND branch = ?),
                            (SELECT COUNT(*) FROM preferences WHERE tenant_id = ?)
                        """,
                        (tenant_id, tenant_id, tenant_id, tenant_id, tenant_id,
                         tenant_id, branch, tenant_id, branch, tenant_id, branch, tenant_id),
                    ).fetchone()
                    parts.append(list(row) if row else None)
                    parts.append(getattr(conn, "total_changes", 0))
                    try:
                        dv = conn.execute("PRAGMA data_version").fetchone()
                        if dv:
                            parts.append(dv[0])
                    except Exception:
                        pass
            except Exception as exc:
                parts.append(f"sqlite_err:{exc}")

        elif hasattr(engine, "connect") and callable(engine.connect):
            try:
                with engine.connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT
                                (SELECT count(*) FROM audit_log WHERE tenant_id = %s),
                                (SELECT max(at) FROM audit_log WHERE tenant_id = %s),
                                (SELECT count(*) FROM deletion_log WHERE tenant_id = %s),
                                (SELECT count(*) FROM merge_log WHERE tenant_id = %s),
                                (SELECT count(*) FROM evidence WHERE tenant_id = %s AND branch = %s AND erased = false),
                                (SELECT count(*) FROM assertions WHERE tenant_id = %s AND branch = %s),
                                (SELECT count(*) FROM relations WHERE tenant_id = %s AND branch = %s),
                                (SELECT count(*) FROM preferences WHERE tenant_id = %s)
                            """,
                            (tenant_id, tenant_id, tenant_id, tenant_id,
                             tenant_id, branch, tenant_id, branch, tenant_id, branch, tenant_id),
                        )
                        parts.append(list(cur.fetchone() or []))
            except Exception as exc:
                parts.append(f"postgres_err:{exc}")

        else:
            parts.append(id(engine))

        return _digest(parts)

    def _lock(self) -> Any:
        return getattr(self.engine, "_lock", None) or nullcontext()

    def _publication_guard(self, context: AnswerReadContext) -> Any:
        guard = getattr(self.engine, "mental_model_guard", None)
        return guard(context.tenant_id) if callable(guard) else self._lock()

    @staticmethod
    def _write(context: AnswerReadContext) -> None:
        _scope(context)
        if context.role == "reader":
            raise PermissionError("mental model mutation requires a writer role")

    def _load(self, context: AnswerReadContext, model_id: str) -> dict[str, Any]:
        scope = _scope(context)
        _text(model_id, "model_id", 128)
        record = self.engine.get_mental_model_record(context.tenant_id, model_id, context.branch)
        if record is None or record.get("owner_id") != context.user_id:
            raise LookupError("mental model not found")
        if record.get("scope") != scope:
            raise PermissionError("mental model read scope differs from its saved scope")
        return record

    def _snapshot(self, context: AnswerReadContext) -> tuple[str, dict[str, dict[str, Any]]]:
        scope = _scope(context)
        filt = context.to_filter()
        exported = self.engine.export_tenant_filtered(context.tenant_id, filt)
        corpus: dict[str, Any] = {"scope": scope, "policy": self.engine.policy.to_dict()}
        evidence: dict[str, dict[str, Any]] = {}
        earliest_expiry: datetime | None = None

        for collection in _COLLECTIONS:
            rows = exported.get(collection, [])
            if not isinstance(rows, list):
                raise ValueError("invalid authorized corpus")
            included = []
            for row in rows:
                if not isinstance(row, dict) or row.get("branch", context.branch) != context.branch:
                    continue
                stable = _stable(row)
                if collection == "evidence":
                    cid = row.get("cid")
                    if not isinstance(cid, str) or not isinstance(row.get("content"), str):
                        raise ValueError("invalid authorized evidence")
                    raw = self.engine.get_evidence(context.tenant_id, cid, context.branch)
                    if (raw is None or raw.cid != cid or raw.tenant_id != context.tenant_id
                            or raw.branch != context.branch or raw.erased):
                        raise ValueError("source changed during snapshot")
                    allowed, _ = classify_scoped_evidence(
                        raw, tenant_id=context.tenant_id, branch=context.branch,
                        filt=filt, policy=self.engine.policy)
                    if (not allowed or not row["content"]
                            or (context.as_of is not None and raw.created_at > context.as_of)):
                        continue
                    stable["source_policy_sha256"] = _digest(raw.access_policy)
                    evidence[cid] = copy.deepcopy(row)

                    if isinstance(raw.access_policy, dict):
                        exp_str = raw.access_policy.get("expires_at")
                        if isinstance(exp_str, str):
                            try:
                                exp_dt = datetime.fromisoformat(exp_str).astimezone(UTC)
                                if earliest_expiry is None or exp_dt < earliest_expiry:
                                    earliest_expiry = exp_dt
                            except (ValueError, TypeError):
                                pass

                included.append(stable)
            corpus[collection] = sorted(included, key=_canonical)

        result_snapshot = (_digest(corpus), evidence)
        as_of_key = context.as_of.isoformat() if context.as_of is not None else None
        cache_key = (context.tenant_id, context.branch, _canonical(scope), as_of_key)
        watermark = self._mutation_watermark(context)
        cache = self._get_cache()
        cache[cache_key] = (watermark, earliest_expiry, (result_snapshot[0], copy.deepcopy(evidence)))
        return result_snapshot

    def _get_ready_snapshot(
        self, context: AnswerReadContext, record: dict[str, Any]
    ) -> tuple[str, dict[str, dict[str, Any]]] | None:
        if record.get("status") not in {"ready", "abstained"}:
            return None

        clock = _question_clock(record["question"], context)
        if record.get("time_fingerprint") != clock:
            return None

        scope = _scope(context)
        as_of_key = context.as_of.isoformat() if context.as_of is not None else None
        cache_key = (context.tenant_id, context.branch, _canonical(scope), as_of_key)

        cache = self._get_cache()
        entry = cache.get(cache_key)
        if entry is None:
            return None

        cached_watermark, earliest_expiry, (fingerprint, evidence) = entry

        watermark = self._mutation_watermark(context)
        if cached_watermark != watermark:
            cache.pop(cache_key, None)
            return None

        if fingerprint != record.get("corpus_fingerprint"):
            return None

        import mnemosyne.access_policy as access_policy_mod
        now = context.as_of or getattr(access_policy_mod, "datetime", datetime).now(UTC)
        if earliest_expiry is not None and now >= earliest_expiry:
            cache.pop(cache_key, None)
            return None

        if record.get("status") == "ready":
            if not self._answer_valid(record, evidence):
                cache.pop(cache_key, None)
                return None

        return fingerprint, copy.deepcopy(evidence)

    @staticmethod
    def _answer_valid(record: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> bool:
        """Rebuild saved claims through the same validator used for fresh answers."""
        answer = record.get("answer")
        if not isinstance(answer, dict):
            return False
        try:
            if not isinstance(answer.get("claims"), list) or not 1 <= len(answer["claims"]) <= 20:
                return False
            proposals = []
            for claim in answer["claims"]:
                if not isinstance(claim, dict) or set(claim) != {"text", "spans", "evidence_cids", "derivation"}:
                    return False
                if not isinstance(claim["spans"], list) or not 1 <= len(claim["spans"]) <= 16:
                    return False
                spans = []
                for span in claim["spans"]:
                    if not isinstance(span, dict) or set(span) != {"cid", "start", "end", "slice_sha256"}:
                        return False
                    content = evidence[span["cid"]]["content"]
                    start, end = span["start"], span["end"]
                    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(content):
                        return False
                    quote = content[start:end]
                    if hashlib.sha256(quote.encode()).hexdigest() != span["slice_sha256"]:
                        return False
                    spans.append({"cid": span["cid"], "quote": quote})
                derivation = claim["derivation"]
                if (not isinstance(derivation, dict)
                        or set(derivation) != {"schema_version", "kind", "operation"}
                        or derivation["schema_version"] != "mnemosyne.claim-derivation/v1"):
                    return False
                if derivation["kind"] == "quotation":
                    if derivation["operation"] is not None:
                        return False
                    proposals.append({"spans": spans})
                elif derivation["kind"] == "synthesis":
                    proposals.append({"synthesis": {"operation": derivation["operation"], "spans": spans}})
                else:
                    return False
            validated = GroundedAnswerOrchestrator._claims(
                {"claims": proposals, "unresolved": False},
                {cid: row["content"] for cid, row in evidence.items()},
            )
            sources = record.get("source_evidence_cids")
            if (not isinstance(sources, list) or not 1 <= len(sources) <= 10000
                    or any(not isinstance(cid, str) or cid not in evidence for cid in sources)
                    or len(sources) != len(set(sources))
                    or not {cid for claim in validated for cid in claim.evidence_cids}.issubset(sources)):
                return False
            return (answer.get("abstained") is False
                    and answer["answer"] == "\n".join(claim.text for claim in validated)
                    and len(validated) == len(answer["claims"])
                    and all(saved["text"] == claim.text
                            and saved["evidence_cids"] == list(claim.evidence_cids)
                            for saved, claim in zip(answer["claims"], validated, strict=True)))
        except (KeyError, TypeError, ValueError, IndexError):
            return False

    def _view(self, record: dict[str, Any], context: AnswerReadContext,
              snapshot: tuple[str, dict[str, dict[str, Any]]] | None = None) -> dict[str, Any]:
        if record.get("status") in {"pending", "error"}:
            # These states never return saved prose or source IDs. A corpus scan cannot
            # make them readable; an explicit refresh must still check current sources.
            ready, stale = False, False
        else:
            try:
                if snapshot is not None:
                    fingerprint, evidence = snapshot
                else:
                    cached = self._get_ready_snapshot(context, record)
                    if cached is not None:
                        fingerprint, evidence = cached
                    else:
                        fingerprint, evidence = self._snapshot(context)
                clock = _question_clock(record["question"], context)
                fresh = fingerprint == record.get("corpus_fingerprint") and record.get("time_fingerprint") == clock
                ready = fresh and record.get("status") == "ready" and self._answer_valid(record, evidence)
                stale = not (ready or (fresh and record.get("status") == "abstained"))
            except Exception:
                ready, stale = False, True
        payload = record.get("answer") if ready else {}
        refresh_error = record.get("refresh_error")
        return {
            "model_id": record["model_id"], "name": record["name"], "question": record["question"],
            "version": record["version"], "created_at": record["created_at"], "updated_at": record["updated_at"],
            "status": "stale" if stale else record["status"], "stale": stale,
            "answer": payload.get("answer", ""), "claims": copy.deepcopy(payload.get("claims", [])),
            "source_evidence_cids": list(record.get("source_evidence_cids", [])) if ready else [],
            "reader": _reader_disclosure(payload.get("reader", {})),
            "refresh_schedule": public_schedule(record),
            "refresh_error": refresh_error if isinstance(refresh_error, str) and refresh_error in {
                "source_changed_during_refresh", "provider_or_source_unavailable", "refresh_abstained"} else None,
        }

    def create(self, context: AnswerReadContext, name: str, question: str) -> dict[str, Any]:
        self._write(context)
        question = _text(question, "question", AnswerLimits().max_query_characters)
        _question_clock(question, context)
        now = datetime.now(UTC).isoformat()
        record = {
            "model_id": str(uuid4()), "tenant_id": context.tenant_id, "branch": context.branch,
            "owner_id": context.user_id, "scope": _scope(context),
            "name": _text(name, "name", 200),
            "question": question,
            "created_at": now, "updated_at": now, "status": "pending", "answer": None,
            "corpus_fingerprint": None, "source_evidence_cids": [], "revisions": [], "refresh_error": None,
        }
        record = self.engine.save_mental_model_record(context.tenant_id, record["model_id"], record,
                                                      branch=context.branch, expected_version=None)
        return self._view(record, context)

    def get(self, context: AnswerReadContext, model_id: str, refresh_if_stale: bool = False) -> dict[str, Any]:
        if type(refresh_if_stale) is not bool:
            raise ValueError("refresh_if_stale must be a boolean")
        with self._lock():
            record = self._load(context, model_id)
            view = self._view(record, context)
        if refresh_if_stale and view["status"] in {"stale", "pending", "error"}:
            return self.refresh(context, model_id)
        return view

    def list(self, context: AnswerReadContext) -> list[dict[str, Any]]:
        scope = _scope(context)
        with self._lock():
            records = [record for record in self.engine.list_mental_model_records(context.tenant_id, context.branch)
                       if record.get("owner_id") == context.user_id and record.get("scope") == scope]
            snapshot = None
            active_records = [r for r in records if r.get("status") not in {"pending", "error"}]
            if active_records:
                cached_candidates = [self._get_ready_snapshot(context, r) for r in active_records]
                if cached_candidates and all(c is not None for c in cached_candidates):
                    snapshot = cached_candidates[0]
                else:
                    snapshot = self._snapshot(context)
            return [self._view(record, context, snapshot) for record in records]

    def history(self, context: AnswerReadContext, model_id: str) -> list[dict[str, Any]]:
        # History deliberately contains no old answers, question text or source excerpts.
        result = []
        for entry in self._load(context, model_id).get("revisions", [])[-_MAX_HISTORY:]:
            if not isinstance(entry, dict):
                continue
            if (type(entry.get("version")) is not int or entry["version"] < 1
                    or not isinstance(entry.get("status"), str)
                    or entry.get("status") not in _STATES
                    or not isinstance(entry.get("event"), str)
                    or entry.get("event") not in {"update", "schedule", "refresh", "refresh_failed", "refresh_abstained"}
                    or type(entry.get("source_count")) is not int or not 0 <= entry["source_count"] <= 10000):
                continue
            digest = entry.get("answer_sha256")
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                continue
            try:
                at = datetime.fromisoformat(entry["at"])
                if at.tzinfo is None:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            result.append({"version": entry["version"], "event": entry["event"], "status": entry["status"],
                           "source_count": entry["source_count"], "answer_sha256": digest, "at": at.isoformat()})
        return result

    @staticmethod
    def _revision(record: dict[str, Any], event: str) -> None:
        answer = record.get("answer")
        entry = {"version": record.get("version", 0) + 1, "event": event,
                 "at": record["updated_at"], "status": record["status"],
                 "answer_sha256": _digest(answer) if answer else None,
                 "source_count": len(record.get("source_evidence_cids", []))}
        record["revisions"] = [*record.get("revisions", []), entry][-_MAX_HISTORY:]

    def update(self, context: AnswerReadContext, model_id: str, name: str | None = None,
               question: str | None = None, expected_version: int | None = None) -> dict[str, Any]:
        self._write(context)
        with self._publication_guard(context):
            record = self._load(context, model_id)
            if expected_version is not None and (type(expected_version) is not int or expected_version != record["version"]):
                raise ValueError("mental model version conflict")
            if name is not None:
                record["name"] = _text(name, "name", 200)
            if question is not None:
                record["question"] = _text(question, "question", AnswerLimits().max_query_characters)
                _question_clock(record["question"], context)
                record.update(answer=None, corpus_fingerprint=None, source_evidence_cids=[], status="pending", refresh_error=None)
            cancel_lease(record, due_now=question is not None)
            record["updated_at"] = datetime.now(UTC).isoformat()
            self._revision(record, "update")
            record = self.engine.save_mental_model_record(context.tenant_id, model_id, record,
                                                          branch=context.branch, expected_version=record["version"])
            return self._view(record, context)

    def schedule(self, context: AnswerReadContext, model_id: str, *, interval_seconds: int = 300,
                 enabled: bool = True, expected_version: int | None = None) -> dict[str, Any]:
        self._write(context)
        schedule = new_schedule(enabled, interval_seconds)
        with self._publication_guard(context):
            record = self._load(context, model_id)
            if expected_version is not None and (type(expected_version) is not int or expected_version != record["version"]):
                raise ValueError("mental model version conflict")
            record["refresh_schedule"] = schedule
            record["updated_at"] = datetime.now(UTC).isoformat()
            self._revision(record, "schedule")
            record = self.engine.save_mental_model_record(context.tenant_id, model_id, record,
                                                          branch=context.branch, expected_version=record["version"])
            return self._view(record, context)

    def delete(self, context: AnswerReadContext, model_id: str, expected_version: int | None = None) -> dict[str, Any]:
        self._write(context)
        with self._publication_guard(context):
            record = self._load(context, model_id)
            if expected_version is not None and (type(expected_version) is not int or expected_version != record["version"]):
                raise ValueError("mental model version conflict")
            deleted = self.engine.delete_mental_model_record(context.tenant_id, model_id, branch=context.branch,
                                                             expected_version=record["version"])
        return {"model_id": model_id, "deleted": deleted}

    def refresh(self, context: AnswerReadContext, model_id: str, force: bool = False) -> dict[str, Any]:
        return self._refresh(context, model_id, force=force)

    def _find_record_by_id(
        self,
        model_id: str,
        *,
        tenant_id: str | None = None,
        branch: str = "main",
    ) -> dict[str, Any] | None:
        if tenant_id is not None:
            rec = self.engine.get_mental_model_record(tenant_id, model_id, branch)
            if rec is not None:
                return rec
        mm_store = getattr(self.engine, "mental_models", None)
        if isinstance(mm_store, Mapping):
            for rec in mm_store.values():
                if isinstance(rec, dict) and rec.get("model_id") == model_id:
                    return rec
        return None

    def _context_from_record(self, record: Mapping[str, Any]) -> AnswerReadContext:
        scope = record.get("scope") or {}
        role = str(scope.get("role") or "agent")
        if role == "reader":
            role = "agent"
        return AnswerReadContext(
            tenant_id=str(record.get("tenant_id") or scope.get("tenant_id") or ""),
            branch=str(record.get("branch") or scope.get("branch") or "main"),
            user_id=str(record.get("owner_id") or scope.get("user_id") or ""),
            role=role,
            source_identity=scope.get("source_identity"),
            max_trust_tier=scope.get("max_trust_tier"),
            max_sensitivity=scope.get("max_sensitivity"),
            capability_tags=tuple(scope.get("capability_tags", ())),
            purpose=tuple(scope.get("purpose", ())),
            residency=scope.get("residency"),
            region=scope.get("region"),
            lawful_basis=tuple(scope.get("lawful_basis", ())),
            break_glass=bool(scope.get("break_glass", False)),
            as_of=scope.get("as_of"),
        )

    def delta_refresh(
        self,
        context_or_model_id: AnswerReadContext | str | None = None,
        model_id_or_cids: str | Sequence[Any] = (),
        new_evidence_cids: Sequence[Any] | None = None,
        *,
        context: AnswerReadContext | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        branch: str = "main",
        new_evidence: Sequence[Any] | None = None,
        refresh_now: bool = True,
        force: bool = False,
    ) -> dict[str, Any]:
        """Targeted delta refresh of a mental model (or all models in scope) when new evidence arrives.

        Supports calling conventions:
        - `delta_refresh(context, model_id, new_evidence_cids)`
        - `delta_refresh(model_id, new_evidence_cids, context=...)`
        - `delta_refresh(context, new_evidence=...)` (batch across scope)
        - `delta_refresh(tenant_id=..., user_id=..., new_evidence=...)` (batch across scope)
        """
        extra_items: list[Any] = []
        if new_evidence is not None:
            extra_items.extend(new_evidence)
        if new_evidence_cids is not None:
            extra_items.extend(new_evidence_cids)

        # Batch mode if no model_id was supplied
        if (
            context_or_model_id is None
            or (isinstance(context_or_model_id, AnswerReadContext) and not isinstance(model_id_or_cids, str))
        ):
            batch_ctx = context_or_model_id if isinstance(context_or_model_id, AnswerReadContext) else context
            if batch_ctx is None and tenant_id and user_id:
                batch_ctx = AnswerReadContext(tenant_id=tenant_id, branch=branch, user_id=user_id, role="agent")
            if not isinstance(model_id_or_cids, str):
                extra_items.extend(model_id_or_cids or ())
            return trigger_on_consolidation(
                self,
                batch_ctx,
                extra_items,
                tenant_id=tenant_id,
                user_id=user_id,
                branch=branch,
                refresh_now=refresh_now,
                force=force,
            )

        if isinstance(context_or_model_id, AnswerReadContext):
            resolved_context = context_or_model_id
            resolved_model_id = str(model_id_or_cids)
            raw_items = extra_items
        elif isinstance(context_or_model_id, str):
            resolved_model_id = context_or_model_id
            if isinstance(model_id_or_cids, str):
                raw_items = [model_id_or_cids, *extra_items]
            else:
                raw_items = [*(model_id_or_cids or ()), *extra_items]
            if context is not None:
                resolved_context = context
            else:
                found = self._find_record_by_id(resolved_model_id, tenant_id=tenant_id, branch=branch)
                if found is None:
                    raise LookupError("mental model not found")
                resolved_context = self._context_from_record(found)
        else:
            raise ValueError("invalid delta_refresh arguments")

        self._write(resolved_context)
        with self._lock():
            record = self._load(resolved_context, resolved_model_id)
            deps = extract_model_dependencies(
                record.get("question", ""),
                record.get("answer"),
                record.get("source_evidence_cids", []),
            )
            affected_cids: list[str] = []
            for item in raw_items:
                if isinstance(item, Mapping):
                    cid_str = str(item.get("cid") or "").strip()
                    ev_content = str(item.get("content") or item.get("text") or "")
                    if not ev_content and cid_str:
                        raw = self.engine.get_evidence(resolved_context.tenant_id, cid_str, resolved_context.branch)
                        ev_content = getattr(raw, "content", "") if raw is not None else ""
                else:
                    cid_str = str(item or "").strip()
                    if not cid_str:
                        continue
                    raw = self.engine.get_evidence(resolved_context.tenant_id, cid_str, resolved_context.branch)
                    ev_content = getattr(raw, "content", "") if raw is not None else ""
                if is_affected_by_evidence(record, ev_content, new_evidence_cid=cid_str or None):
                    affected_cids.append(cid_str or "inline")

            # Also check if any previously cited source CID was erased or missing
            cite_invalidated = False
            for src_cid in record.get("source_evidence_cids", []):
                raw_src = self.engine.get_evidence(resolved_context.tenant_id, src_cid, resolved_context.branch)
                if raw_src is None or getattr(raw_src, "erased", False):
                    cite_invalidated = True
                    break

            is_pending = record.get("status") in {"pending", "error"}
            affected = bool(affected_cids) or cite_invalidated or is_pending or force

            if not affected:
                # Model is unaffected by the delta evidence. Keep existing valid answer
                # fresh against the current snapshot without calling the provider.
                snapshot = self._snapshot(resolved_context)
                clock = _question_clock(record["question"], resolved_context)
                if (
                    record.get("status") in {"ready", "abstained"}
                    and record.get("time_fingerprint") == clock
                    and (record.get("status") == "abstained" or self._answer_valid(record, snapshot[1]))
                    and record.get("corpus_fingerprint") != snapshot[0]
                ):
                    record["corpus_fingerprint"] = snapshot[0]
                    record = self.engine.save_mental_model_record(
                        resolved_context.tenant_id,
                        resolved_model_id,
                        record,
                        branch=resolved_context.branch,
                        expected_version=record["version"],
                    )
                view = self._view(record, resolved_context, snapshot)
                return {
                    **view,
                    "refreshed": False,
                    "skipped": True,
                    "affected": False,
                    "affected_cids": [],
                    "preserved_previous_answer": False,
                    "dependencies": deps,
                    "dependent_entities": deps["dependent_entities"],
                    "dependent_predicates": deps["dependent_predicates"],
                    "dependent_cids": deps["dependent_cids"],
                }

            if not refresh_now:
                snapshot = self._snapshot(resolved_context)
                view = self._view(record, resolved_context, snapshot)
                return {
                    **view,
                    "refreshed": False,
                    "skipped": False,
                    "affected": True,
                    "affected_cids": list(affected_cids),
                    "preserved_previous_answer": record.get("status") == "ready",
                    "dependencies": deps,
                    "dependent_entities": deps["dependent_entities"],
                    "dependent_predicates": deps["dependent_predicates"],
                    "dependent_cids": deps["dependent_cids"],
                }

        # Model is affected: run targeted refresh while preserving previous valid answer on failure.
        return self._delta_refresh_affected(
            resolved_context,
            resolved_model_id,
            affected_cids=affected_cids,
        )

    def _delta_refresh_affected(
        self,
        context: AnswerReadContext,
        model_id: str,
        *,
        affected_cids: list[str],
    ) -> dict[str, Any]:
        with self._lock():
            record = self._load(context, model_id)
            if (record.get("refresh_schedule") or {}).get("lease") is not None:
                cancel_lease(record)
                record = self.engine.save_mental_model_record(
                    context.tenant_id,
                    model_id,
                    record,
                    branch=context.branch,
                    expected_version=record["version"],
                )
            before = self._snapshot(context)
            before_clock = _question_clock(record["question"], context)

        try:
            from mnemosyne.providers.grounded_reader import CommandGroundedProvider

            provider = (self.provider_factory or CommandGroundedProvider.from_environment)()
            result = GroundedAnswerOrchestrator(self.engine, provider).answer(
                AnswerRequest(question=record["question"], context=context),
                provider,
            )
            if result.failure_kind is not None:
                raise ValueError("grounded refresh attempt failed")
            disclosure = provider.disclosure
            if not isinstance(disclosure, dict) or set(disclosure) not in (
                {"query_decomposer"},
                {"query_decomposer", "grounded_reader"},
            ):
                disclosure = {}
            payload = public_grounded_answer(result, disclosure, include_derivation=True)
            state = "abstained" if result.abstained else "ready"
            sources = set(row.cid for row in result.evidence)
            pending = list(sources)
            while pending:
                cid = pending.pop()
                raw = self.engine.get_evidence(context.tenant_id, cid, context.branch)
                if raw is None or len(sources) > 10000:
                    raise ValueError("source unavailable")
                ancestors, valid = derived_source_cids(raw)
                if not valid:
                    raise ValueError("source lineage invalid")
                for ancestor in ancestors:
                    if ancestor not in sources:
                        sources.add(ancestor)
                        pending.append(ancestor)
            error = None
        except Exception:
            payload, state, sources, error = None, "error", set(), "provider_or_source_unavailable"

        preserved_previous = False
        refreshed_ok = state == "ready"
        with self._publication_guard(context):
            current = self._load(context, model_id)
            if current["version"] != record["version"]:
                raise ValueError("mental model changed during refresh")
            after = self._snapshot(context)
            after_clock = _question_clock(record["question"], context)
            event = "refresh"
            if (
                state in {"error", "abstained"}
                and before[0] == after[0]
                and before_clock == after_clock
                and current.get("status") == "ready"
                and self._answer_valid(current, after[1])
            ):
                payload = current["answer"]
                sources = set(current.get("source_evidence_cids", []))
                error = error or "refresh_abstained"
                event = "refresh_failed" if state == "error" else "refresh_abstained"
                state = "ready"
                preserved_previous = True
                refreshed_ok = False
            if before[0] != after[0] or before_clock != after_clock:
                payload, state, sources, error = None, "stale", set(), "source_changed_during_refresh"
                refreshed_ok = False
            record.update(
                answer=payload,
                status=state,
                source_evidence_cids=sorted(sources),
                corpus_fingerprint=after[0] if state in {"ready", "abstained"} else None,
                time_fingerprint=after_clock,
                updated_at=datetime.now(UTC).isoformat(),
                refresh_error=error,
            )
            if state == "ready" and not self._answer_valid(record, after[1]):
                record.update(
                    answer=None,
                    status="stale",
                    corpus_fingerprint=None,
                    source_evidence_cids=[],
                    refresh_error="source_changed_during_refresh",
                )
                refreshed_ok = False
            self._revision(record, event)
            record = self.engine.save_mental_model_record(
                context.tenant_id,
                model_id,
                record,
                branch=context.branch,
                expected_version=current["version"],
            )
            final_snapshot = self._snapshot(context)
            view = self._view(record, context, final_snapshot)
            deps = extract_model_dependencies(
                record.get("question", ""),
                record.get("answer"),
                record.get("source_evidence_cids", []),
            )
            return {
                **view,
                "refreshed": refreshed_ok,
                "skipped": False,
                "affected": True,
                "affected_cids": list(affected_cids),
                "preserved_previous_answer": preserved_previous,
                "dependencies": deps,
                "dependent_entities": deps["dependent_entities"],
                "dependent_predicates": deps["dependent_predicates"],
                "dependent_cids": deps["dependent_cids"],
            }

    def trigger_on_consolidation(
        self,
        context_or_cids: AnswerReadContext | Sequence[str],
        new_evidence_cids: Sequence[str] | None = None,
        *,
        context: AnswerReadContext | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Trigger delta refresh across scoped models after consolidation completes."""
        if isinstance(context_or_cids, AnswerReadContext):
            resolved_context = context_or_cids
            cids = list(new_evidence_cids or ())
        else:
            resolved_context = context
            cids = list(context_or_cids or ())
        return trigger_on_consolidation(self, resolved_context, cids, force=force)

    def _refresh(self, context: AnswerReadContext, model_id: str, force: bool = False, *,
                 lease_token: str | None = None, authorize: Callable[[], None] | None = None,
                 validate_authority: Callable[[], None] | None = None) -> dict[str, Any]:
        self._write(context)
        if type(force) is not bool:
            raise ValueError("force must be a boolean")
        if authorize is not None:
            authorize()
        with self._lock():
            record = self._load(context, model_id)
            if lease_token is not None:
                require_lease(record, lease_token)
            elif (record.get("refresh_schedule") or {}).get("lease") is not None:
                cancel_lease(record)
                record = self.engine.save_mental_model_record(context.tenant_id, model_id, record,
                                                              branch=context.branch, expected_version=record["version"])
            before = self._snapshot(context)
            before_clock = _question_clock(record["question"], context)
            view = self._view(record, context, before)
            if not force and view["status"] in {"ready", "abstained"}:
                return view
        # Corpus preparation can be slow. Recheck authority and lease immediately
        # before sending any source text to a provider, outside the error wrapper.
        if authorize is not None:
            authorize()
        if lease_token is not None:
            with self._lock():
                current = self._load(context, model_id)
                require_lease(current, lease_token)
                if current["version"] != record["version"]:
                    raise ValueError("mental model changed before refresh")
        # Expensive/provider work never holds the engine write lock.
        try:
            from mnemosyne.providers.grounded_reader import CommandGroundedProvider

            provider = (self.provider_factory or CommandGroundedProvider.from_environment)()
            result = GroundedAnswerOrchestrator(self.engine, provider).answer(
                AnswerRequest(question=record["question"], context=context), provider)
            if result.failure_kind is not None:
                raise ValueError("grounded refresh attempt failed")
            disclosure = provider.disclosure
            if not isinstance(disclosure, dict) or set(disclosure) not in (
                {"query_decomposer"}, {"query_decomposer", "grounded_reader"}):
                disclosure = {}
            payload = public_grounded_answer(result, disclosure, include_derivation=True)
            state = "abstained" if result.abstained else "ready"
            sources = set(row.cid for row in result.evidence)
            pending = list(sources)
            while pending:
                cid = pending.pop()
                raw = self.engine.get_evidence(context.tenant_id, cid, context.branch)
                if raw is None or len(sources) > 10000:
                    raise ValueError("source unavailable")
                ancestors, valid = derived_source_cids(raw)
                if not valid:
                    raise ValueError("source lineage invalid")
                for ancestor in ancestors:
                    if ancestor not in sources:
                        sources.add(ancestor)
                        pending.append(ancestor)
            error = None
        except Exception:
            payload, state, sources, error = None, "error", set(), "provider_or_source_unavailable"
        # Authorization callbacks may record audit events; run them before the
        # publication transaction, never inside a guard-owned SQLite transaction.
        if authorize is not None:
            authorize()
        with self._publication_guard(context):
            current = self._load(context, model_id)
            if lease_token is not None:
                require_lease(current, lease_token)
            if current["version"] != record["version"]:
                raise ValueError("mental model changed during refresh")
            after = self._snapshot(context)
            after_clock = _question_clock(record["question"], context)
            event = "refresh"
            if (state in {"error", "abstained"} and before[0] == after[0]
                    and self._view(current, context, after)["status"] == "ready"):
                # A failed optional regeneration must not destroy a still-valid
                # successful answer. Retain it only after current-scope replay.
                payload = current["answer"]
                sources = set(current.get("source_evidence_cids", []))
                error = error or "refresh_abstained"
                event = "refresh_failed" if state == "error" else "refresh_abstained"
                state = "ready"
            # Moving clock windows are checked at publication. A fixed-window
            # boundary crossed during generation cannot publish the old answer.
            if before[0] != after[0] or before_clock != after_clock:
                payload, state, sources, error = None, "stale", set(), "source_changed_during_refresh"
            record.update(answer=payload, status=state, source_evidence_cids=sorted(sources),
                          corpus_fingerprint=after[0] if state in {"ready", "abstained"} else None,
                          time_fingerprint=after_clock,
                          updated_at=datetime.now(UTC).isoformat(), refresh_error=error)
            if state == "ready" and not self._answer_valid(record, after[1]):
                record.update(answer=None, status="stale", corpus_fingerprint=None,
                              source_evidence_cids=[], refresh_error="source_changed_during_refresh")
            self._revision(record, event)
            if lease_token is not None:
                require_lease(current, lease_token)
            if validate_authority is not None:
                validate_authority()
            record = self.engine.save_mental_model_record(context.tenant_id, model_id, record,
                                                          branch=context.branch, expected_version=current["version"])
            # Do not reuse a pre-save authorization snapshot for returned prose.
            # Local/SQLite guards make publication atomic against their writers;
            # other engines still receive this fresh post-save read gate.
            return self._view(record, context, self._snapshot(context))
