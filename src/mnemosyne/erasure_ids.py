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

Stdlib only. CIDs are never computed here.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

_TOMBSTONE_SALT_PREFIX = b"mnemosyne/erasure-tombstone/v1"
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
