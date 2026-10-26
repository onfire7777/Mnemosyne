"""Atomic, owner-scoped text-document revisions without model extraction.

This service accepts an already authenticated AnswerReadContext. It is not an
authentication boundary; a transport must construct that context itself.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any
from uuid import uuid4

from mnemosyne.access_policy import may_read_item, validate_access_policy
from mnemosyne.answering import AnswerReadContext
from mnemosyne.document_storage import MAX_DOCUMENT_ENTRIES, DocumentConflict, document_key, opaque_id
from mnemosyne.mental_model_storage import json_copy
from mnemosyne.models import Evidence, utc_now
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
                             action="create", expected_revision=None, settings=settings)

    def replace(
        self, context: AnswerReadContext, document_id: str, content: str, *,
        operation_id: str, expected_revision: int,
    ) -> DocumentReceipt:
        return self._publish(context, document_id, content, operation_id=operation_id,
                             action="replace", expected_revision=expected_revision)

    def append(
        self, context: AnswerReadContext, document_id: str, suffix: str, *,
        operation_id: str, expected_revision: int,
    ) -> DocumentReceipt:
        """Append the exact suffix; no separator or newline is inserted."""
        return self._publish(context, document_id, suffix, operation_id=operation_id,
                             action="append", expected_revision=expected_revision)

    def _publish(
        self, context: AnswerReadContext, document_id: str, content: str, *, operation_id: str,
        action: str, expected_revision: int | None, settings: dict[str, Any] | None = None,
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
            created = reused = 0
            for text, row in plan:
                if row is not None:
                    reused += 1
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
        return result
