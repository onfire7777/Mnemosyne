"""Salted-hash + HMAC id producers for the Phase-2 erasure path (spec §4.2/§7).

Two DISTINCT, non-interchangeable id producers back erasure. They differ on
purpose: one is deterministic (a verifiable receipt inside the trust boundary),
the other is deliberately non-recomputable (a retained record that must not leak
what it references).

``erasure_tombstone_hash(content, tenant_id, user_id)`` — a DETERMINISTIC,
salted SHA-256 written into the CID-journal tombstone line (``salted_hash``)
when an evidence row is erased in ``tombstone_recompute`` mode. It is a
proof-of-erasure marker: an operator holding a candidate plaintext can confirm
it was the erased content (audit / right-to-be-forgotten receipts) WITHOUT the
journal retaining the plaintext. The journal is a LOCAL per-tenant file that
never leaves the trust boundary, so determinism is the desired property here.

Salt construction (documented, versioned, domain-separated):

    SALT_PREFIX = b"mnemosyne/erasure-tombstone/v1"
    digest = sha256( SALT_PREFIX
                     + 0x1F + utf8(tenant_id)
                     + 0x1F + utf8(user_id)
                     + 0x1F + utf8(content) ).hexdigest()

``0x1F`` (ASCII Unit Separator) is an unambiguous field delimiter that cannot
occur inside the hex cids / opaque ids being framed, so distinct
``(tenant_id, user_id, content)`` triples can never collide through delimiter
confusion. The ``…/v1`` prefix reserves room to rotate the construction.

``erasure_deletion_record_id(cid, tenant_id, user_id)`` — a NON-recomputable
HMAC id written into the deletion_log ``evidence_cid`` field in
``hard_delete_legal`` mode, REPLACING the real cid. Spec §7 privacy
invariant 13 requires that a *retained* deletion record must not let an
attacker confirm which cid was hard-deleted by computing ``sha256(guess)``.
Because ``ids.evidence_cid`` is itself a salted SHA-256 of the content, keeping
the cid (or any deterministic hash of guessable inputs) in the retained record
would be exactly such a confirmation oracle. We therefore key the id with a
FRESH random secret per record that is immediately discarded:

    key = secrets.token_bytes(32)                 # ephemeral, never stored
    id  = hmac_sha256(key, tenant_id|user_id|cid).hexdigest()

The discarded key makes the stored id computationally indistinguishable from
random, so no ``sha256(guess)`` (nor HMAC without the key) can ever match it:
the retained record proves *that* something was legally shredded without
revealing *what*. ``tombstone_recompute`` keeps the real cid (the tombstone row
still exists in the ledger), so this producer is used ONLY for hard deletes.

``erasure_cid_placeholder(cid, tenant_id, *, salt)`` — a NON-recomputable,
per-erasure-STABLE placeholder that REPLACES the erased cid everywhere it is
*referenced* inside a retained record (deletion_log ``propagated`` provenance
arrays, standing-cascade ``source_cid``/``affected_cids``/``derived_actions``,
and the audit row's ``target_id``). Task-9 replaced only the deletion_log's
top-level ``evidence_cid``; spec §7 invariant 13 requires that *no* retained
field expose the cid. A single ``sha256(guess)`` over guessable inputs must not
confirm which cid was shredded, yet the record must stay internally analyzable
(the same erased cid must map to the same token wherever it appears). We satisfy
both by keying an HMAC with a FRESH per-erasure ``salt`` that is generated once
(``build_erasure_placeholder_map``) and immediately discarded:

    salt = secrets.token_bytes(32)                    # ephemeral, never stored
    id   = hmac_sha256(salt, DOMAIN | tenant_id | cid).hexdigest()

Reusing the one salt across every cid in a single erasure makes the map
internally consistent (referential integrity of the retained record), while the
discarded salt makes each token computationally indistinguishable from random —
no ``sha256(guess)`` (nor HMAC without the salt) can reproduce it. This differs
from ``erasure_deletion_record_id`` (which fabricates a fresh RECORD id per row);
the placeholder is a stable REFERENCE token scoped to one erasure.

Stdlib only. CIDs are never computed here.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable, Mapping
from typing import Any

_TOMBSTONE_SALT_PREFIX = b"mnemosyne/erasure-tombstone/v1"
_PLACEHOLDER_DOMAIN = b"mnemosyne/erasure-cid-placeholder/v1"
_FIELD_SEP = b"\x1f"


def erasure_tombstone_hash(content: str, tenant_id: str, user_id: str) -> str:
    """Deterministic salted SHA-256 for a CID-journal tombstone (see module doc)."""
    hasher = hashlib.sha256()
    hasher.update(_TOMBSTONE_SALT_PREFIX)
    for field in (tenant_id, user_id, content):
        hasher.update(_FIELD_SEP)
        hasher.update(str(field or "").encode("utf-8"))
    return hasher.hexdigest()


def erasure_deletion_record_id(cid: str, tenant_id: str, user_id: str) -> str:
    """Non-recomputable HMAC id for a ``hard_delete_legal`` deletion_log row.

    Keyed with a fresh random secret that is discarded, so the retained id
    resists ``sha256(guess)`` cid-confirmation (spec §7 privacy invariant 13).
    Non-deterministic by design — every call returns a fresh value even for the
    same ``cid``."""
    key = secrets.token_bytes(32)
    message = _FIELD_SEP.join(
        (
            str(tenant_id or "").encode("utf-8"),
            str(user_id or "").encode("utf-8"),
            str(cid or "").encode("utf-8"),
        )
    )
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def erasure_cid_placeholder(cid: str, tenant_id: str, *, salt: bytes) -> str:
    """Non-recomputable, per-erasure-stable placeholder for a retained cid ref.

    Keyed HMAC-SHA256 over ``DOMAIN | tenant_id | cid`` with a caller-supplied
    ephemeral ``salt``. Deterministic for a fixed ``salt`` (so the SAME erased
    cid maps to the SAME token everywhere in one retained record — referential
    consistency), yet — because ``salt`` is fresh per erasure and discarded —
    ``sha256(guess)`` / HMAC-without-salt can never reproduce it (spec §7
    invariant 13). Callers get the salt+map via ``build_erasure_placeholder_map``.
    """
    message = _FIELD_SEP.join(
        (
            _PLACEHOLDER_DOMAIN,
            str(tenant_id or "").encode("utf-8"),
            str(cid or "").encode("utf-8"),
        )
    )
    return hmac.new(salt, message, hashlib.sha256).hexdigest()


def build_erasure_placeholder_map(cids: Iterable[Any], tenant_id: str) -> dict[str, str]:
    """Map each erased cid to a stable placeholder under ONE ephemeral salt.

    The salt is generated once here and immediately discarded, so within the
    returned map the same cid always yields the same placeholder (the retained
    record stays internally analyzable) while no placeholder can be reproduced by
    ``sha256(guess)`` (spec §7 invariant 13). Pass the erased source cid plus
    every erased-derived cid; retained (non-erased) cids must NOT be included —
    they still exist and are referenced verbatim.
    """
    salt = secrets.token_bytes(32)
    mapping: dict[str, str] = {}
    for cid in cids:
        text = str(cid or "")
        if text and text not in mapping:
            mapping[text] = erasure_cid_placeholder(text, tenant_id, salt=salt)
    return mapping


def redact_erased_cids(value: Any, placeholder_map: Mapping[str, str]) -> Any:
    """Recursively rebuild ``value``, swapping any erased cid for its placeholder.

    Returns a NEW structure and never mutates the input, so ``forget`` can redact
    only the copy it PERSISTS (deletion_log + audit) while still returning the
    real cids to its caller. Walks dicts (values only — keys are field names),
    lists, and tuples; leaves non-cid strings untouched.
    """
    if isinstance(value, str):
        return placeholder_map.get(value, value)
    if isinstance(value, Mapping):
        return {key: redact_erased_cids(item, placeholder_map) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_erased_cids(item, placeholder_map) for item in value]
    return value
