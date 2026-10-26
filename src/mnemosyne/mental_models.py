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
from datetime import UTC, datetime
from typing import Any, Callable, Mapping
from uuid import uuid4

from mnemosyne.answering import (
    AnswerLimits,
    AnswerReadContext,
    AnswerRequest,
    GroundedAnswerOrchestrator,
    public_grounded_answer,
)
from mnemosyne.retrieval import classify_scoped_evidence, derived_source_cids, query_time_window
from mnemosyne.mental_model_refresh import cancel_lease, new_schedule, public_schedule, require_lease

_TELEMETRY = frozenset({"access_count", "last_accessed", "last_accessed_at", "salience"})
_COLLECTIONS = ("evidence", "assertions", "relations", "preferences")
_MAX_HISTORY = 32
_STATES = {"pending", "ready", "stale", "error", "abstained"}


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
        filt = context.to_filter()
        exported = self.engine.export_tenant_filtered(context.tenant_id, filt)
        corpus: dict[str, Any] = {"scope": _scope(context), "policy": self.engine.policy.to_dict()}
        evidence: dict[str, dict[str, Any]] = {}
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
                included.append(stable)
            corpus[collection] = sorted(included, key=_canonical)
        return _digest(corpus), evidence

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
                fingerprint, evidence = snapshot or self._snapshot(context)
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
            snapshot = (self._snapshot(context) if any(record.get("status") not in {"pending", "error"}
                                                       for record in records) else None)
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
