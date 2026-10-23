"""Shared validation for private, versioned text-document manifests.

Manifests contain source identities, never a second copy of source text. Engine
adapters own the transaction and persistence; this module never runs providers.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from mnemosyne.access_policy import validate_access_policy
from mnemosyne.ids import validate_document_segment_id
from mnemosyne.mental_model_storage import json_copy
from mnemosyne.models import parse_dt, utc_now


class DocumentConflict(ValueError):
    """A document revision, consumed operation or source precondition failed."""


_OPAQUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {
    "schema_version", "tenant_id", "branch", "owner_id", "document_id",
    "revision", "created_at", "updated_at", "deleted", "settings",
    "segments", "retired_segments", "receipts",
}
_SETTINGS = {"splitter_version", "chunk_chars", "trust_tier", "sensitivity",
             "access_policy", "capability_tags"}
_RECEIPT = {"operation_id", "action", "revision", "request_hash",
            "created", "reused", "retired"}
MAX_DOCUMENT_ENTRIES = 100_000


def opaque_id(value: Any, name: str) -> str:
    if type(value) is not str or not _OPAQUE.fullmatch(value):
        raise ValueError(f"{name} must be an opaque ASCII identifier of 1 to 256 characters")
    return value


def document_key(tenant_id: str, owner_id: str, document_id: str, branch: str) -> tuple[str, str, str, str]:
    for name, value in (("tenant_id", tenant_id), ("owner_id", owner_id), ("branch", branch)):
        if type(value) is not str or not value.strip() or len(value) > 512:
            raise ValueError(f"document {name} must be a nonempty string of at most 512 characters")
    opaque_id(document_id, "document_id")
    return tenant_id, branch, owner_id, document_id


def validate_document_record(record: dict[str, Any]) -> dict[str, Any]:
    if type(record) is not dict or set(record) != _FIELDS:
        raise ValueError("document record has missing or unsupported fields")
    row = json_copy(record)
    document_key(row["tenant_id"], row["owner_id"], row["document_id"], row["branch"])
    if type(row["schema_version"]) is not int or row["schema_version"] != 1:
        raise ValueError("unsupported document record schema")
    if type(row["revision"]) is not int or row["revision"] < 1:
        raise ValueError("document revision must be positive")
    if type(row["deleted"]) is not bool:
        raise ValueError("document deleted marker must be boolean")
    for name in ("created_at", "updated_at"):
        if type(row[name]) is not str:
            raise ValueError(f"document {name} must be an ISO timestamp")
        try:
            if parse_dt(row[name]) is None:
                raise ValueError()
        except (TypeError, ValueError) as error:
            raise ValueError(f"document {name} must be an ISO timestamp") from error
    if parse_dt(row["updated_at"]) < parse_dt(row["created_at"]):
        raise ValueError("document update predates creation")
    settings = row["settings"]
    if type(settings) is not dict or set(settings) - _SETTINGS:
        raise ValueError("unsupported document settings")
    for name, lower, upper in (("splitter_version", 1, 1), ("chunk_chars", 64, 16384),
                               ("trust_tier", 0, 5), ("sensitivity", 0, 3)):
        if name in settings and (type(settings[name]) is not int or not lower <= settings[name] <= upper):
            raise ValueError(f"invalid document {name}")
    tags = settings.get("capability_tags", [])
    if (type(tags) is not list or len(tags) > 128
            or any(type(tag) is not str or not tag.strip() or len(tag) > 256 for tag in tags)):
        raise ValueError("invalid document capability_tags")
    if "access_policy" in settings:
        settings["access_policy"] = validate_access_policy(
            settings["access_policy"], tenant_id=row["tenant_id"], location="document.access_policy",
        )
    seen_ids: set[str] = set()
    seen_cids: set[str] = set()
    for name in ("segments", "retired_segments"):
        entries = row[name]
        if type(entries) is not list or len(entries) > MAX_DOCUMENT_ENTRIES:
            raise ValueError("document segment lists must be bounded arrays")
        for entry in entries:
            if type(entry) is not dict or set(entry) != {"segment_id", "cid"}:
                raise ValueError("invalid document segment entry")
            opaque_id(entry["segment_id"], "segment_id")
            validate_document_segment_id(entry["segment_id"])
            cid = entry["cid"]
            if type(cid) is not str or not cid.strip() or len(cid) > 512:
                raise ValueError("invalid document source CID")
            if entry["segment_id"] in seen_ids or cid in seen_cids:
                raise ValueError("document segment occurrences must be unique")
            seen_ids.add(entry["segment_id"])
            seen_cids.add(cid)
    if row["deleted"] and row["segments"]:
        raise ValueError("deleted documents cannot have active segments")
    receipts = row["receipts"]
    if type(receipts) is not list or not receipts or len(receipts) > MAX_DOCUMENT_ENTRIES:
        raise ValueError("document receipts must be a nonempty bounded array")
    seen_operations: set[str] = set()
    previous_revision = 0
    for receipt in receipts:
        if type(receipt) is not dict or set(receipt) - _RECEIPT:
            raise ValueError("invalid document receipt")
        opaque_id(receipt.get("operation_id"), "operation_id")
        if receipt["operation_id"] in seen_operations:
            raise ValueError("document operation IDs cannot be reused")
        seen_operations.add(receipt["operation_id"])
        if receipt.get("action") not in {"create", "replace", "append"}:
            raise ValueError("invalid document operation action")
        revision = receipt.get("revision")
        if type(revision) is not int or not previous_revision < revision <= row["revision"]:
            raise ValueError("invalid document receipt revision")
        previous_revision = revision
        digest = receipt.get("request_hash")
        if digest is not None and (type(digest) is not str or not _HASH.fullmatch(digest)):
            raise ValueError("invalid document request hash")
        for name in ("created", "reused", "retired"):
            receipt.setdefault(name, 0)
            if type(receipt[name]) is not int or receipt[name] < 0:
                raise ValueError("document receipt counts must be nonnegative integers")
    return row


def prepare_document_save(
    tenant_id: str, owner_id: str, document_id: str, record: dict[str, Any],
    branch: str, current: dict[str, Any] | None, expected_revision: int | None,
) -> dict[str, Any]:
    key = document_key(tenant_id, owner_id, document_id, branch)
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
        raise ValueError("expected_revision must be a positive integer or None for creation")
    if current is None:
        if expected_revision is not None:
            raise DocumentConflict("document revision conflict")
        revision = 1
    else:
        current = validate_document_record(current)
        if current["deleted"]:
            raise DocumentConflict("document was deleted and cannot be recreated")
        if expected_revision is None or current["revision"] != expected_revision:
            raise DocumentConflict("document revision conflict")
        revision = expected_revision + 1
    copied = json_copy(record)
    copied["revision"] = revision
    copied = validate_document_record(copied)
    if document_key(copied["tenant_id"], copied["owner_id"], copied["document_id"], copied["branch"]) != key:
        raise ValueError("document storage scope mismatch")
    old_receipts = current["receipts"] if current else []
    if len(copied["receipts"]) != len(old_receipts) + 1:
        raise ValueError("each document publication requires exactly one new operation receipt")
    if copied["receipts"][-1]["revision"] != revision:
        raise ValueError("document receipt must name the committed revision")
    if copied["receipts"][-1]["request_hash"] is None:
        raise ValueError("new document receipt needs its request hash")
    for old, new in zip(old_receipts, copied["receipts"]):
        if {k: v for k, v in old.items() if k != "request_hash"} != {k: v for k, v in new.items() if k != "request_hash"}:
            raise ValueError("document operation receipts are immutable")
        # Retire old request hashes rather than retain a hash oracle for replaced
        # private text. A consumed old operation can never run again.
        new["request_hash"] = None
    if current:
        for name in ("created_at",):
            if copied[name] != current[name]:
                raise ValueError(f"document {name} is immutable")
        old_settings, new_settings = current["settings"], copied["settings"]
        if ({k: v for k, v in old_settings.items() if k != "sensitivity"}
                != {k: v for k, v in new_settings.items() if k != "sensitivity"}
                or new_settings.get("sensitivity", 0) < old_settings.get("sensitivity", 0)):
            raise ValueError("document settings are immutable except for increasing sensitivity")
        if parse_dt(copied["updated_at"]) < parse_dt(current["updated_at"]):
            raise ValueError("document time cannot move backwards")
        old_current = {x["segment_id"]: x for x in current["segments"]}
        new_current = {x["segment_id"]: x for x in copied["segments"]}
        for segment_id in old_current.keys() & new_current.keys():
            if old_current[segment_id] != new_current[segment_id]:
                raise ValueError("document segment identity is immutable")
        expected_retired = current["retired_segments"] + [x for x in current["segments"] if x["segment_id"] not in new_current]
        if copied["retired_segments"] != expected_retired:
            raise ValueError("document history can only change through source retirement or erasure")
    elif copied["retired_segments"]:
        raise ValueError("new documents cannot adopt retired segments")
    return copied


def validate_document_sources(
    ops: Any, saved: dict[str, Any], current: dict[str, Any] | None,
    records: Iterable[dict[str, Any]],
) -> list[str]:
    """Check source custody under the adapter's transaction, before any writes."""
    own_key = document_key(saved["tenant_id"], saved["owner_id"], saved["document_id"], saved["branch"])
    claimed_cids: set[str] = set()
    claimed_ids: set[str] = set()
    for record in records:
        key = document_key(record["tenant_id"], record["owner_id"], record["document_id"], record["branch"])
        if key == own_key:
            continue
        for entry in record["segments"] + record["retired_segments"]:
            claimed_cids.add(entry["cid"])
            if record["owner_id"] == saved["owner_id"]:
                claimed_ids.add(entry["segment_id"])
    for entry in saved["segments"]:
        row = ops.get_evidence(saved["tenant_id"], entry["cid"], saved["branch"])
        if (row is None or row.erased or row.retired_at is not None
                or row.tenant_id != saved["tenant_id"] or row.branch != saved["branch"]
                or row.user_id != saved["owner_id"] or row.document_segment_id != entry["segment_id"]
                or row.cid != entry["cid"]):
            raise DocumentConflict("document source is missing, retired or outside its custody")
        if entry["cid"] in claimed_cids or entry["segment_id"] in claimed_ids:
            raise DocumentConflict("document segment already belongs to another document")
    active = {entry["cid"] for entry in saved["segments"]}
    removed = [entry["cid"] for entry in (current or {}).get("segments", []) if entry["cid"] not in active]
    previous = {entry["cid"]: entry for entry in (current or {}).get("segments", [])}
    for cid in removed:
        row = ops.get_evidence(saved["tenant_id"], cid, saved["branch"])
        if (row is None or row.erased or row.retired_at is not None or row.user_id != saved["owner_id"]
                or row.tenant_id != saved["tenant_id"] or row.branch != saved["branch"] or row.cid != cid
                or row.document_segment_id != previous[cid]["segment_id"]):
            raise DocumentConflict("document source changed before retirement")
    return removed


def scrub_document_record(record: dict[str, Any], erased_cids: Iterable[str]) -> dict[str, Any] | None:
    erased = set(erased_cids)
    if not any(x["cid"] in erased for x in record["segments"] + record["retired_segments"]):
        return None
    copied = json_copy(record)
    for name in ("segments", "retired_segments"):
        copied[name] = [x for x in copied[name] if x["cid"] not in erased]
    copied["deleted"] = copied["deleted"] or not copied["segments"]
    copied["revision"] += 1
    copied["updated_at"] = max(utc_now(), parse_dt(record["updated_at"])).isoformat()
    for receipt in copied["receipts"]:
        receipt["request_hash"] = None
    return copied


def document_records_equivalent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return {k: v for k, v in left.items() if k != "branch"} == {k: v for k, v in right.items() if k != "branch"}
