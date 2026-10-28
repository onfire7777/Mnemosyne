"""Atomic, owner-scoped text-document revisions without model extraction.

This service accepts an already authenticated AnswerReadContext. It is not an
authentication boundary; a transport must construct that context itself.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from typing import Any, Mapping
from uuid import uuid4

from mnemosyne.access_policy import may_read_item, validate_access_policy
from mnemosyne.answering import AnswerReadContext
from mnemosyne.document_storage import MAX_DOCUMENT_ENTRIES, DocumentConflict, document_key, opaque_id
from mnemosyne.mental_model_storage import json_copy
from mnemosyne.models import Evidence, utc_now
from mnemosyne.observations import Observation, ProofQuote
from mnemosyne.privacy import classify_privacy, detect_pii_tags
from mnemosyne.retrieval import read_evidence_for_context
from mnemosyne.security import SecurityPolicy


@dataclass(frozen=True)
class DocumentReceipt:
    document_id: str
    operation_id: str
    action: str
    revision: int
    created: int
    reused: int
    retired: int
    created_cids: tuple[str, ...] = field(default=(), compare=False, repr=False)
    reused_cids: tuple[str, ...] = field(default=(), compare=False, repr=False)
    retired_cids: tuple[str, ...] = field(default=(), compare=False, repr=False)
    tenant_id: str | None = field(default=None, compare=False, repr=False)
    user_id: str | None = field(default=None, compare=False, repr=False)
    branch: str = field(default="main", compare=False, repr=False)
    extracted: dict[str, Any] | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class DocumentView:
    document_id: str
    revision: int
    content: str
    segment_cids: tuple[str, ...]


def split_document_text(content: str, *, chunk_chars: int = 2048) -> list[str]:
    """Lossless paragraph chunks; edits do not repack subsequent paragraphs.

    Blank-line separators belong to the preceding paragraph. Long paragraphs
    split at exact character boundaries. Offsets count Unicode code points,
    never bytes; no whitespace, newline or Unicode normalization is performed.
    """
    if type(content) is not str:
        raise ValueError("document content must be text")
    if type(chunk_chars) is not int or not 64 <= chunk_chars <= 16384:
        raise ValueError("chunk_chars must be between 64 and 16384")
    result: list[str] = []
    start = 0
    for match in re.finditer(r"(?:\r?\n)[\t ]*(?:\r?\n)(?:[\t ]*\r?\n)*", content):
        end = match.end()
        result.extend(content[i:min(i + chunk_chars, end)] for i in range(start, end, chunk_chars))
        start = end
    result.extend(content[i:i + chunk_chars] for i in range(start, len(content), chunk_chars))
    return result


def _extract_segment_facts_and_observations(
    cid: str,
    content: str,
    *,
    document_id: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic fact and observation extraction for a newly created document segment."""
    facts: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    if not isinstance(content, str) or not content.strip():
        return facts, observations

    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+|\r?\n+", content)
        if s.strip()
    ]
    for sentence in sentences:
        # Match simple subject-predicate-object or key:value / key=value statements
        kv_match = re.match(r"^([A-Za-z0-9_.\-/ ]{2,64})\s*[:=]\s*(.+)$", sentence)
        if kv_match:
            subj = kv_match.group(1).strip()
            obj = kv_match.group(2).strip().rstrip(".")
            facts.append({
                "subject": subj,
                "predicate": "is",
                "object": obj,
                "evidence_cid": cid,
                "source_document_id": document_id,
                "text": sentence,
            })
        else:
            spo_match = re.match(
                r"^([A-Z][A-Za-z0-9_.\-/ ]{1,48})\s+(is|are|was|were|uses|used|runs|deploys|supports|owns|manages|prefers|requires|targets)\s+(.+)$",
                sentence,
            )
            if spo_match:
                facts.append({
                    "subject": spo_match.group(1).strip(),
                    "predicate": spo_match.group(2).strip(),
                    "object": spo_match.group(3).strip().rstrip("."),
                    "evidence_cid": cid,
                    "source_document_id": document_id,
                    "text": sentence,
                })
            else:
                facts.append({
                    "subject": document_id or cid,
                    "predicate": "states",
                    "object": sentence,
                    "evidence_cid": cid,
                    "source_document_id": document_id,
                    "text": sentence,
                })

        start_idx = content.find(sentence)
        end_idx = start_idx + len(sentence) if start_idx >= 0 else len(sentence)
        pq = ProofQuote(
            cid=cid,
            quote=sentence,
            start=max(0, start_idx),
            end=max(0, end_idx),
            sha256=sha256(sentence.encode("utf-8")).hexdigest(),
        )
        obs = Observation(
            tenant_id="default",
            user_id="default",
            subject=document_id or cid,
            topic="document_segment",
            content=sentence,
            proof_quotes=[pq],
            source_evidence_cids=[cid],
        )
        observations.append(obs.to_dict())
    return facts, observations


def extract_changed_segments(
    doc_result: DocumentReceipt | Mapping[str, Any] | Any,
    engine: Any = None,
) -> dict[str, Any]:
    """Trigger fact/observation extraction ONLY for newly created segments, skipping reused ones."""
    if isinstance(doc_result, Mapping):
        document_id = str(doc_result.get("document_id") or "")
        revision = int(doc_result.get("revision") or 1)
        created_cids = list(doc_result.get("created_cids") or ())
        reused_cids = list(doc_result.get("reused_cids") or ())
        retired_cids = list(doc_result.get("retired_cids") or ())
        tenant_id = doc_result.get("tenant_id")
        branch = str(doc_result.get("branch") or "main")
        segment_contents = doc_result.get("segment_contents") or {}
    else:
        document_id = str(getattr(doc_result, "document_id", "") or "")
        revision = int(getattr(doc_result, "revision", 1) or 1)
        created_cids = list(getattr(doc_result, "created_cids", ()) or ())
        reused_cids = list(getattr(doc_result, "reused_cids", ()) or ())
        retired_cids = list(getattr(doc_result, "retired_cids", ()) or ())
        tenant_id = getattr(doc_result, "tenant_id", None)
        branch = str(getattr(doc_result, "branch", "main") or "main")
        segment_contents = {}

    facts: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []

    for cid in created_cids:
        if not isinstance(cid, str) or not cid:
            continue
        content = ""
        if isinstance(segment_contents, Mapping) and isinstance(segment_contents.get(cid), str):
            content = segment_contents[cid]
        elif engine is not None:
            raw = None
            if isinstance(tenant_id, str) and tenant_id:
                try:
                    raw = engine.get_evidence(tenant_id, cid, branch)
                except Exception:
                    raw = None
            if raw is None and hasattr(engine, "evidence") and isinstance(engine.evidence, Mapping):
                raw = engine.evidence.get(cid)
            if raw is not None:
                content = getattr(raw, "content", "") or ""
        seg_facts, seg_obs = _extract_segment_facts_and_observations(
            cid, content, document_id=document_id
        )
        facts.extend(seg_facts)
        observations.extend(seg_obs)

    return {
        "document_id": document_id,
        "revision": revision,
        "extracted_cids": list(created_cids),
        "skipped_cids": list(reused_cids),
        "retired_cids": list(retired_cids),
        "extracted_count": len(created_cids),
        "skipped_count": len(reused_cids),
        "skipped_unchanged_count": len(reused_cids),
        "facts": facts,
        "observations": observations,
    }


class DocumentService:
    """Create, replace, append and read current private document revisions.

    Unchanged occurrences keep their source CIDs when their sensitivity meets
    the current revision's classification. A retired occurrence is never
    reactivated: A→B→A allocates a new occurrence.
    The most recent operation can be retried exactly; earlier consumed IDs are
    rejected after their fingerprints are removed for data minimization.
    """

    def __init__(self, engine: Any, *, max_content_chars: int = 2_000_000, security: SecurityPolicy | None = None):
        if type(max_content_chars) is not int or max_content_chars < 1:
            raise ValueError("max_content_chars must be positive")
        self.engine = engine
        self.max_content_chars = max_content_chars
        self.security = security or SecurityPolicy()

    @staticmethod
    def _scope(context: AnswerReadContext, document_id: str, *, write: bool = False) -> None:
        if not isinstance(context, AnswerReadContext):
            raise TypeError("documents require an authenticated AnswerReadContext")
        document_key(context.tenant_id, context.user_id, document_id, context.branch)
        if context.break_glass or context.as_of is not None:
            raise ValueError("document revisions require a current, non-break-glass context")
        if write and context.role == "reader":
            raise PermissionError("reader role cannot modify documents")

    def _authorize_record(self, context: AnswerReadContext, record: dict[str, Any]) -> None:
        if (record["tenant_id"], record["branch"], record["owner_id"]) != (
            context.tenant_id, context.branch, context.user_id,
        ):
            raise PermissionError("document is outside caller scope")
        self._authorize_settings(context, record["settings"])

    def _authorize_settings(self, context: AnswerReadContext, settings: dict[str, Any]) -> None:
        decision = may_read_item(
            item_tenant_id=context.tenant_id, sensitivity=settings.get("sensitivity", 0),
            access_policy=settings.get("access_policy", {}), context=context.to_filter(),
            policy_max_sensitivity=self.engine.policy.max_sensitivity,
        )
        if not decision.allowed or decision.redacted:
            raise PermissionError("document sources are not fully readable in this context")

    def _rows(self, context: AnswerReadContext, record: dict[str, Any]) -> list[Evidence]:
        self._authorize_record(context, record)
        rows: list[Evidence] = []
        for segment in record["segments"]:
            row = read_evidence_for_context(
                self.engine, context.tenant_id, segment["cid"], context.branch,
                access_context=context.to_filter(),
            )
            if row is None or row.user_id != context.user_id or row.document_segment_id != segment["segment_id"]:
                raise DocumentConflict("document source changed or is not readable")
            rows.append(row)
        return rows

    @staticmethod
    def _receipt(document_id: str, receipt: dict[str, Any]) -> DocumentReceipt:
        return DocumentReceipt(document_id=document_id, **{
            field: receipt[field] for field in ("operation_id", "action", "revision", "created", "reused", "retired")
        })

    def get(self, context: AnswerReadContext, document_id: str) -> DocumentView | None:
        self._scope(context, document_id)
        record = self.engine.get_document_record(context.tenant_id, context.user_id, document_id, context.branch)
        if record is None:
            return None
        self._authorize_record(context, record)
        if record["deleted"]:
            return None
        rows = self._rows(context, record)
        current = self.engine.get_document_record(context.tenant_id, context.user_id, document_id, context.branch)
        if current != record:
            raise DocumentConflict("document changed while reading; retry the read")
        checked_rows = self._rows(context, current)
        if [row.to_dict() for row in checked_rows] != [row.to_dict() for row in rows]:
            raise DocumentConflict("document source changed while reading; retry the read")
        return DocumentView(document_id, record["revision"], "".join(row.content for row in rows),
                            tuple(segment["cid"] for segment in record["segments"]))

    def create(
        self, context: AnswerReadContext, document_id: str, content: str, *,
        operation_id: str, chunk_chars: int = 2048, sensitivity: int = 0,
        access_policy: dict[str, Any] | None = None,
        auto_extract: bool = False,
    ) -> DocumentReceipt:
        self._scope(context, document_id, write=True)
        if type(sensitivity) is not int or not 0 <= sensitivity <= 3:
            raise ValueError("sensitivity must be between 0 and 3")
        policy = json_copy(access_policy or {})
        # Owner binding is also enforced by the first-class source read gate.
        # Principals here keep default vector storage in the private partition.
        policy["allow_principals"] = [context.user_id]
        policy = validate_access_policy(policy, tenant_id=context.tenant_id, location="document.access_policy")
        settings = {"splitter_version": 1, "chunk_chars": chunk_chars,
                    "trust_tier": context.source_trust_tier or 0, "sensitivity": sensitivity,
                    "access_policy": policy, "capability_tags": list(context.capability_tags)}
        return self._publish(context, document_id, content, operation_id=operation_id,
                             action="create", expected_revision=None, settings=settings,
                             auto_extract=auto_extract)

    def replace(
        self, context: AnswerReadContext, document_id: str, content: str, *,
        operation_id: str, expected_revision: int,
        auto_extract: bool = False,
    ) -> DocumentReceipt:
        return self._publish(context, document_id, content, operation_id=operation_id,
                             action="replace", expected_revision=expected_revision,
                             auto_extract=auto_extract)

    def append(
        self, context: AnswerReadContext, document_id: str, suffix: str, *,
        operation_id: str, expected_revision: int,
        auto_extract: bool = False,
    ) -> DocumentReceipt:
        """Append the exact suffix; no separator or newline is inserted."""
        return self._publish(context, document_id, suffix, operation_id=operation_id,
                             action="append", expected_revision=expected_revision,
                             auto_extract=auto_extract)

    def extract_changed_segments(self, doc_result: DocumentReceipt | Mapping[str, Any] | Any) -> dict[str, Any]:
        """Extract facts/observations only from newly created segments in `doc_result`."""
        return extract_changed_segments(doc_result, self.engine)

    def _publish(
        self, context: AnswerReadContext, document_id: str, content: str, *, operation_id: str,
        action: str, expected_revision: int | None, settings: dict[str, Any] | None = None,
        auto_extract: bool = False,
    ) -> DocumentReceipt:
        self._scope(context, document_id, write=True)
        opaque_id(operation_id, "operation_id")
        source_tier = context.source_trust_tier or 0
        permission = self.security.authorize_write(
            f"document_{action}", context.role, source_tier, target_sink="evidence",
            source_capability_tags=context.capability_tags,
        )
        if not permission.allowed:
            raise PermissionError(permission.reason)
        if type(content) is not str or len(content) > self.max_content_chars:
            raise ValueError("document content exceeds the configured text limit")
        if action != "create" and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expected_revision must be a positive integer")
        request_hash = sha256(json.dumps({
            "schema": 1, "action": action, "content": content,
            "expected_revision": expected_revision, "settings": settings,
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
        # Publication has no provider/queue effects. Holding the native source
        # transaction makes source admission, CAS, retirement and receipt atomic.
        with self.engine.source_transaction(context.tenant_id, context.branch):
            current = self.engine.get_document_record(context.tenant_id, context.user_id, document_id, context.branch)
            if current is not None:
                self._authorize_record(context, current)
                if current["deleted"]:
                    raise DocumentConflict("document was deleted and cannot be recreated")
                prior = next((r for r in current["receipts"] if r["operation_id"] == operation_id), None)
                if prior is not None:
                    if prior["request_hash"] != request_hash:
                        raise DocumentConflict("operation ID was consumed by a different or retired request")
                    # Recheck current custody even for an otherwise exact retry.
                    self._rows(context, current)
                    return self._receipt(document_id, prior)
            if action == "create":
                if current is not None:
                    raise DocumentConflict("document already exists")
                selected_settings = settings
                old_rows: list[Evidence] = []
            else:
                if current is None or current["revision"] != expected_revision:
                    raise DocumentConflict("document revision conflict")
                selected_settings = current["settings"]
                old_rows = self._rows(context, current)
            selected_settings = json_copy(selected_settings)
            if source_tier > selected_settings["trust_tier"]:
                raise PermissionError("a lower-trust writer cannot inherit the document's stronger source trust")
            if action == "append":
                content = "".join(row.content for row in old_rows) + content
            if len(content) > self.max_content_chars:
                raise ValueError("document content exceeds the configured text limit")
            pii_tags = detect_pii_tags(content)
            selected_settings["sensitivity"] = max(selected_settings["sensitivity"], 3 if pii_tags else 0)
            # Documents must stay fully readable by their writer. Refuse before
            # any source admission when classification raises sensitivity past
            # the caller's ceiling (for example PII written by an S2 agent).
            try:
                self._authorize_settings(context, selected_settings)
            except PermissionError as error:
                raise PermissionError(
                    "document content sensitivity exceeds the writer's read ceiling"
                ) from error
            chunks = split_document_text(content, chunk_chars=selected_settings["chunk_chars"])
            if len(chunks) > MAX_DOCUMENT_ENTRIES:
                raise ValueError("document exceeds the segment count limit")
            if current and len(current["receipts"]) >= MAX_DOCUMENT_ENTRIES:
                raise ValueError("document exceeds the operation receipt limit")
            by_text: dict[str, deque[Evidence]] = defaultdict(deque)
            for row in old_rows:
                # Classification applies to the whole document, including PII
                # newly formed across reordered chunk boundaries. Reusing a
                # lower-sensitivity source would bypass the manifest policy in
                # generic recall. Replace it so retirement and dependent-source
                # invalidation happen atomically with this revision.
                if row.sensitivity >= selected_settings["sensitivity"]:
                    by_text[row.content].append(row)
            plan = [(text, by_text[text].popleft() if by_text[text] else None) for text in chunks]
            reused_ids = {row.document_segment_id for _, row in plan if row is not None}
            removed = [entry for entry in (current or {}).get("segments", []) if entry["segment_id"] not in reused_ids]
            if len((current or {}).get("retired_segments", [])) + len(removed) > MAX_DOCUMENT_ENTRIES:
                raise ValueError("document exceeds the retired segment limit")
            segments: list[dict[str, str]] = []
            created_cids: list[str] = []
            reused_cids: list[str] = []
            retired_cids: list[str] = [entry["cid"] for entry in removed if "cid" in entry]
            created = reused = 0
            for text, row in plan:
                if row is not None:
                    reused += 1
                    reused_cids.append(row.cid)
                    segments.append({"segment_id": row.document_segment_id, "cid": row.cid})
                    continue
                row = Evidence(
                    tenant_id=context.tenant_id, user_id=context.user_id,
                    actor="user" if source_tier <= 1 else "external",
                    source_type="document", content=text, document_segment_id=f"segment-{uuid4().hex}",
                    source_identity=context.source_identity,
                    branch=context.branch, trust_tier=selected_settings["trust_tier"],
                    sensitivity=selected_settings["sensitivity"],
                    access_policy=json_copy(selected_settings["access_policy"]),
                    capability_tags=sorted(set(selected_settings["capability_tags"]) | set(context.capability_tags)
                                           | {f"pii:{tag}" for tag in pii_tags}
                                           | ({"data-only", "no-write-authority"} if source_tier >= 5 else set())),
                    metadata={"privacy": classify_privacy(text).to_dict(), "document_splitter_version": 1},
                )
                cid = self.engine.append_evidence(row, context.branch)
                admitted = read_evidence_for_context(
                    self.engine, context.tenant_id, cid, context.branch, access_context=context.to_filter(),
                )
                if (admitted is None or admitted.document_segment_id != row.document_segment_id
                        or admitted.user_id != context.user_id or admitted.content != text):
                    raise DocumentConflict("document source admission was refused")
                segments.append({"segment_id": row.document_segment_id, "cid": cid})
                created_cids.append(cid)
                created += 1
            revision = current["revision"] + 1 if current else 1
            receipt = {"operation_id": operation_id, "action": action, "revision": revision,
                       "request_hash": request_hash, "created": created, "reused": reused, "retired": len(removed)}
            now = utc_now().isoformat()
            record = {
                "schema_version": 1, "tenant_id": context.tenant_id, "owner_id": context.user_id,
                "branch": context.branch, "document_id": document_id, "revision": revision,
                "created_at": current["created_at"] if current else now, "updated_at": now,
                "deleted": False, "settings": selected_settings, "segments": segments,
                "retired_segments": (current["retired_segments"] if current else []) + removed,
                "receipts": (current["receipts"] if current else []) + [receipt],
            }
            self._authorize_record(context, record)
            saved = self.engine.save_document_record(
                context.tenant_id, context.user_id, document_id, record, context.branch,
                expected_revision=expected_revision,
            )
            result = self._receipt(document_id, saved["receipts"][-1])
            object.__setattr__(result, "created_cids", tuple(created_cids))
            object.__setattr__(result, "reused_cids", tuple(reused_cids))
            object.__setattr__(result, "retired_cids", tuple(retired_cids))
            object.__setattr__(result, "tenant_id", context.tenant_id)
            object.__setattr__(result, "user_id", context.user_id)
            object.__setattr__(result, "branch", context.branch)
            if auto_extract:
                extracted = extract_changed_segments(result, self.engine)
                object.__setattr__(result, "extracted", extracted)
        return result

    def _list_branch_document_records(
        self,
        tenant_id: str,
        branch: str,
        *,
        user_id: str | None = None,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if user_id and document_id:
            rec = self.engine.get_document_record(tenant_id, user_id, document_id, branch)
            return [rec] if rec is not None and not rec.get("deleted") else []
        records: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()
        for attr_name in ("document_records", "documents"):
            doc_store = getattr(self.engine, attr_name, None)
            if isinstance(doc_store, Mapping):
                for rec in doc_store.values():
                    if not isinstance(rec, dict) or rec.get("deleted"):
                        continue
                    if rec.get("tenant_id") != tenant_id or rec.get("branch") != branch:
                        continue
                    if user_id is not None and rec.get("owner_id") != user_id:
                        continue
                    if document_id is not None and rec.get("document_id") != document_id:
                        continue
                    key = (str(rec.get("owner_id")), str(rec.get("document_id")))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        loaded = self.engine.get_document_record(tenant_id, key[0], key[1], branch)
                        if loaded is not None and not loaded.get("deleted"):
                            records.append(loaded)
        if not records and hasattr(self.engine, "_connect") and callable(self.engine._connect):
            try:
                conn = self.engine._connect(tenant_id)
                rows = conn.execute(
                    "SELECT owner_id, document_id FROM documents WHERE tenant_id = ? AND branch = ?",
                    (tenant_id, branch),
                ).fetchall()
                for owner_val, doc_val in rows:
                    if user_id is not None and owner_val != user_id:
                        continue
                    if document_id is not None and doc_val != document_id:
                        continue
                    key = (str(owner_val), str(doc_val))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        loaded = self.engine.get_document_record(tenant_id, key[0], key[1], branch)
                        if loaded is not None and not loaded.get("deleted"):
                            records.append(loaded)
            except Exception:
                pass
        return records

    def reconcile_branch_manifests(
        self,
        tenant_id_or_context: str | AnswerReadContext,
        source_branch: str,
        target_branch: str = "main",
        *,
        user_id: str | None = None,
        document_id: str | None = None,
        auto_extract: bool = False,
    ) -> dict[str, Any]:
        """Reconcile branch-level document manifests from `source_branch` into `target_branch`."""
        if isinstance(tenant_id_or_context, AnswerReadContext):
            ctx = tenant_id_or_context
            if ctx.break_glass or ctx.as_of is not None:
                raise ValueError("document reconciliation requires a current, non-break-glass context")
            if ctx.role == "reader":
                raise PermissionError("reader role cannot reconcile documents")
            tenant_id = ctx.tenant_id
            resolved_user_id = user_id or ctx.user_id
        elif isinstance(tenant_id_or_context, str) and tenant_id_or_context.strip():
            tenant_id = tenant_id_or_context.strip()
            resolved_user_id = user_id
        else:
            raise ValueError("tenant_id must be a non-empty string or AnswerReadContext")

        if not isinstance(source_branch, str) or not source_branch.strip():
            raise ValueError("source_branch must be a non-empty string")
        if not isinstance(target_branch, str) or not target_branch.strip():
            raise ValueError("target_branch must be a non-empty string")
        source_branch = source_branch.strip()
        target_branch = target_branch.strip()
        if source_branch == target_branch:
            raise ValueError("source_branch and target_branch must differ")

        source_records = self._list_branch_document_records(
            tenant_id,
            source_branch,
            user_id=resolved_user_id,
            document_id=document_id,
        )
        source_evidence_by_cid: dict[str, Evidence | None] = {}
        for src_rec in source_records:
            for src_seg in src_rec.get("segments", []):
                src_cid = src_seg["cid"]
                if src_cid not in source_evidence_by_cid:
                    source_evidence_by_cid[src_cid] = self.engine.get_evidence(tenant_id, src_cid, source_branch)

        reconciled_docs: list[dict[str, Any]] = []
        all_created_cids: list[str] = []
        all_reused_cids: list[str] = []
        all_retired_cids: list[str] = []

        with self.engine.source_transaction(tenant_id, target_branch):
            for src_rec in source_records:
                doc_id = src_rec["document_id"]
                owner_id = src_rec["owner_id"]
                tgt_rec = self.engine.get_document_record(tenant_id, owner_id, doc_id, target_branch)

                # Index existing target segments by segment_id and by content
                tgt_by_seg_id: dict[str, dict[str, str]] = {}
                tgt_by_content: dict[str, deque[tuple[dict[str, str], Evidence]]] = defaultdict(deque)
                if tgt_rec is not None and not tgt_rec.get("deleted"):
                    for seg in tgt_rec.get("segments", []):
                        tgt_by_seg_id[seg["segment_id"]] = seg
                        ev = self.engine.get_evidence(tenant_id, seg["cid"], target_branch)
                        if ev is not None and not getattr(ev, "erased", False):
                            tgt_by_content[ev.content].append((seg, ev))

                reconciled_segments: list[dict[str, str]] = []
                reused_seg_ids: set[str] = set()
                doc_created_cids: list[str] = []
                doc_reused_cids: list[str] = []

                for src_seg in src_rec.get("segments", []):
                    src_seg_id = src_seg["segment_id"]
                    src_cid = src_seg["cid"]
                    src_ev = source_evidence_by_cid.get(src_cid)

                    # 1. Exact segment_id match on target_branch
                    if src_seg_id in tgt_by_seg_id:
                        tgt_seg = tgt_by_seg_id[src_seg_id]
                        tgt_ev = self.engine.get_evidence(tenant_id, tgt_seg["cid"], target_branch)
                        if tgt_ev is not None and (src_ev is None or tgt_ev.content == src_ev.content):
                            reconciled_segments.append({"segment_id": tgt_seg["segment_id"], "cid": tgt_seg["cid"]})
                            reused_seg_ids.add(tgt_seg["segment_id"])
                            doc_reused_cids.append(tgt_seg["cid"])
                            continue

                    # 2. Content match on target_branch with sufficient sensitivity
                    if src_ev is not None and tgt_by_content.get(src_ev.content):
                        candidate_queue = tgt_by_content[src_ev.content]
                        matched_seg = None
                        while candidate_queue:
                            cand_seg, cand_ev = candidate_queue.popleft()
                            if cand_seg["segment_id"] not in reused_seg_ids and cand_ev.sensitivity >= src_rec["settings"]["sensitivity"]:
                                matched_seg = cand_seg
                                break
                        if matched_seg is not None:
                            reconciled_segments.append({"segment_id": matched_seg["segment_id"], "cid": matched_seg["cid"]})
                            reused_seg_ids.add(matched_seg["segment_id"])
                            doc_reused_cids.append(matched_seg["cid"])
                            continue

                    # 3. Promote segment from source_branch onto target_branch
                    target_ev = self.engine.get_evidence(tenant_id, src_cid, target_branch)
                    if target_ev is None and src_ev is not None:
                        promoted = Evidence(
                            tenant_id=tenant_id,
                            user_id=owner_id,
                            actor=src_ev.actor,
                            source_type="document",
                            content=src_ev.content,
                            document_segment_id=src_seg_id,
                            source_identity=src_ev.source_identity,
                            branch=target_branch,
                            trust_tier=src_ev.trust_tier,
                            sensitivity=src_ev.sensitivity,
                            access_policy=json_copy(src_ev.access_policy),
                            capability_tags=list(src_ev.capability_tags),
                            metadata=json_copy(src_ev.metadata),
                        )
                        new_cid = self.engine.append_evidence(promoted, target_branch)
                    else:
                        new_cid = src_cid
                    reconciled_segments.append({"segment_id": src_seg_id, "cid": new_cid})
                    reused_seg_ids.add(src_seg_id)
                    doc_created_cids.append(new_cid)

                removed_target_segments = [
                    entry
                    for entry in (tgt_rec or {}).get("segments", [])
                    if entry["segment_id"] not in reused_seg_ids
                ]
                doc_retired_cids = [entry["cid"] for entry in removed_target_segments if "cid" in entry]

                # Preserve target branch's retired_segments plus newly retired target segments
                existing_retired = list(tgt_rec.get("retired_segments", [])) if tgt_rec is not None else []
                seen_retired_ids = {entry["segment_id"] for entry in existing_retired}
                for entry in removed_target_segments:
                    if entry["segment_id"] not in seen_retired_ids and entry["segment_id"] not in reused_seg_ids:
                        seen_retired_ids.add(entry["segment_id"])
                        existing_retired.append({"segment_id": entry["segment_id"], "cid": entry["cid"]})

                new_revision = (tgt_rec["revision"] + 1) if tgt_rec is not None else 1
                action = "create" if tgt_rec is None else "replace"
                op_id = f"reconcile-{source_branch}-{target_branch}-r{src_rec['revision']}-{uuid4().hex[:8]}"
                req_hash = sha256(
                    json.dumps(
                        {
                            "schema": 1,
                            "action": "reconcile",
                            "source_branch": source_branch,
                            "target_branch": target_branch,
                            "source_revision": src_rec["revision"],
                            "segments": reconciled_segments,
                        },
                        sort_keys=True,
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()

                receipt_entry = {
                    "operation_id": op_id,
                    "action": action,
                    "revision": new_revision,
                    "request_hash": req_hash,
                    "created": len(doc_created_cids),
                    "reused": len(doc_reused_cids),
                    "retired": len(removed_target_segments),
                }
                now = utc_now().isoformat()
                merged_settings = json_copy(src_rec["settings"])
                if tgt_rec is not None:
                    merged_settings["sensitivity"] = max(
                        merged_settings.get("sensitivity", 0),
                        tgt_rec["settings"].get("sensitivity", 0),
                    )
                new_record = {
                    "schema_version": 1,
                    "tenant_id": tenant_id,
                    "owner_id": owner_id,
                    "branch": target_branch,
                    "document_id": doc_id,
                    "revision": new_revision,
                    "created_at": tgt_rec["created_at"] if tgt_rec is not None else now,
                    "updated_at": now,
                    "deleted": False,
                    "settings": merged_settings,
                    "segments": reconciled_segments,
                    "retired_segments": existing_retired[:MAX_DOCUMENT_ENTRIES],
                    "receipts": ((tgt_rec["receipts"] if tgt_rec is not None else []) + [receipt_entry])[-MAX_DOCUMENT_ENTRIES:],
                }
                self.engine.save_document_record(
                    tenant_id,
                    owner_id,
                    doc_id,
                    new_record,
                    target_branch,
                    expected_revision=tgt_rec["revision"] if tgt_rec is not None else None,
                )

                doc_summary: dict[str, Any] = {
                    "document_id": doc_id,
                    "owner_id": owner_id,
                    "source_revision": src_rec["revision"],
                    "revision": new_revision,
                    "created": len(doc_created_cids),
                    "reused": len(doc_reused_cids),
                    "retired": len(removed_target_segments),
                    "created_cids": doc_created_cids,
                    "reused_cids": doc_reused_cids,
                    "retired_cids": doc_retired_cids,
                    "segment_cids": [s["cid"] for s in reconciled_segments],
                }
                if auto_extract:
                    doc_summary["extracted"] = extract_changed_segments(
                        {
                            "document_id": doc_id,
                            "revision": new_revision,
                            "created_cids": doc_created_cids,
                            "reused_cids": doc_reused_cids,
                            "retired_cids": doc_retired_cids,
                            "tenant_id": tenant_id,
                            "branch": target_branch,
                        },
                        self.engine,
                    )
                reconciled_docs.append(doc_summary)
                all_created_cids.extend(doc_created_cids)
                all_reused_cids.extend(doc_reused_cids)
                all_retired_cids.extend(doc_retired_cids)

        return {
            "tenant_id": tenant_id,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "reconciled_count": len(reconciled_docs),
            "reconciled_documents": [d["document_id"] for d in reconciled_docs],
            "documents": reconciled_docs,
            "created": len(all_created_cids),
            "reused": len(all_reused_cids),
            "retired": len(all_retired_cids),
            "created_cids": all_created_cids,
            "reused_cids": all_reused_cids,
            "retired_cids": all_retired_cids,
        }
