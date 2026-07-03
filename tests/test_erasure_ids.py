"""Tests for the Phase-2 erasure id producers (spec §4.2/§7 invariant 13)."""
from __future__ import annotations

import hashlib

from mnemosyne.erasure_ids import erasure_deletion_record_id, erasure_tombstone_hash

_CONTENT = "The orchid ledger note holds SSN 123-45-6789."
_TENANT = "tenant-erasure"
_USER = "user-7"


def test_tombstone_hash_is_deterministic_hex_sha256() -> None:
    a = erasure_tombstone_hash(_CONTENT, _TENANT, _USER)
    b = erasure_tombstone_hash(_CONTENT, _TENANT, _USER)
    assert a == b  # deterministic — a tombstone is a verifiable receipt
    assert len(a) == 64 and int(a, 16) >= 0  # 32-byte sha256 hex


def test_tombstone_hash_is_salted_not_raw_content_sha256() -> None:
    # The salt (domain prefix + framed fields) means it is NOT a bare
    # sha256(content); an attacker without the construction cannot reproduce it
    # from the plaintext alone by the naive digest.
    naive = hashlib.sha256(_CONTENT.encode()).hexdigest()
    assert erasure_tombstone_hash(_CONTENT, _TENANT, _USER) != naive


def test_tombstone_hash_separates_tenant_user_content_fields() -> None:
    # The \x1f field separator prevents delimiter-confusion collisions: moving a
    # character across a field boundary must change the digest.
    base = erasure_tombstone_hash("ab", "c", "d")
    shifted = erasure_tombstone_hash("a", "bc", "d")
    assert base != shifted
    # Distinct content, tenant, or user each change the digest.
    assert erasure_tombstone_hash(_CONTENT, _TENANT, _USER) != erasure_tombstone_hash(
        _CONTENT + "!", _TENANT, _USER
    )
    assert erasure_tombstone_hash(_CONTENT, _TENANT, _USER) != erasure_tombstone_hash(
        _CONTENT, _TENANT + "x", _USER
    )
    assert erasure_tombstone_hash(_CONTENT, _TENANT, _USER) != erasure_tombstone_hash(
        _CONTENT, _TENANT, _USER + "x"
    )


def test_deletion_record_id_is_random_per_call_not_recomputable() -> None:
    # Spec §7 invariant 13: keyed with a fresh discarded secret, so the same cid
    # yields a DIFFERENT id every call — no deterministic function of the inputs.
    cid = hashlib.sha256(_CONTENT.encode()).hexdigest()
    a = erasure_deletion_record_id(cid, _TENANT, _USER)
    b = erasure_deletion_record_id(cid, _TENANT, _USER)
    assert a != b
    assert len(a) == 64 and len(b) == 64


def test_deletion_record_id_resists_sha256_guess_confirmation() -> None:
    # An attacker who guesses the exact plaintext (and thus the real cid) still
    # cannot confirm it against the retained id: neither the cid nor any
    # sha256/tombstone-hash of guessable inputs equals the HMAC id.
    cid = hashlib.sha256(_CONTENT.encode()).hexdigest()
    record_id = erasure_deletion_record_id(cid, _TENANT, _USER)
    assert record_id != cid
    assert record_id != hashlib.sha256(_CONTENT.encode()).hexdigest()
    assert record_id != hashlib.sha256(cid.encode()).hexdigest()
    assert record_id != erasure_tombstone_hash(_CONTENT, _TENANT, _USER)
    # Even brute-forcing the full (tenant, user, content) triple through sha256
    # cannot match — the id is HMAC-keyed with a secret that was discarded.
    for guess in (_CONTENT, f"{_TENANT}|{_USER}|{cid}", f"{_TENANT}\x1f{_USER}\x1f{cid}"):
        assert record_id != hashlib.sha256(guess.encode()).hexdigest()
