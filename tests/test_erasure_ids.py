"""Tests for the Phase-2 erasure id producers (spec §4.2/§7 invariant 13)."""
from __future__ import annotations

import hashlib

from mnemosyne.erasure_ids import (
    build_erasure_placeholder_map,
    erasure_cid_placeholder,
    erasure_deletion_record_id,
    erasure_tombstone_hash,
    redact_erased_cids,
)

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


def test_placeholder_is_salt_stable_but_not_recomputable() -> None:
    # Spec §7 invariant 13: a placeholder is STABLE for a fixed ephemeral salt
    # (referential consistency within one retained record) yet a fresh salt gives
    # a different token, and no sha256(guess) reproduces it.
    cid = hashlib.sha256(_CONTENT.encode()).hexdigest()
    salt_a = b"\x11" * 32
    salt_b = b"\x22" * 32
    assert erasure_cid_placeholder(cid, _TENANT, salt=salt_a) == erasure_cid_placeholder(
        cid, _TENANT, salt=salt_a
    )
    assert erasure_cid_placeholder(cid, _TENANT, salt=salt_a) != erasure_cid_placeholder(
        cid, _TENANT, salt=salt_b
    )
    token = erasure_cid_placeholder(cid, _TENANT, salt=salt_a)
    assert len(token) == 64
    assert token not in {
        cid,
        hashlib.sha256(cid.encode()).hexdigest(),
        hashlib.sha256(_CONTENT.encode()).hexdigest(),
    }


def test_build_placeholder_map_consistent_within_one_erasure() -> None:
    # One ephemeral salt per map → same cid maps to same placeholder within the
    # map; distinct cids get distinct placeholders; a fresh map differs entirely.
    cid_a = hashlib.sha256(b"a").hexdigest()
    cid_b = hashlib.sha256(b"b").hexdigest()
    mapping = build_erasure_placeholder_map([cid_a, cid_b, cid_a], _TENANT)
    assert set(mapping) == {cid_a, cid_b}
    assert mapping[cid_a] != mapping[cid_b]
    assert mapping[cid_a] != cid_a
    assert build_erasure_placeholder_map([cid_a], _TENANT)[cid_a] != mapping[cid_a]


def test_redact_erased_cids_deep_replaces_and_leaves_input_untouched() -> None:
    cid = hashlib.sha256(b"target").hexdigest()
    other = hashlib.sha256(b"kept").hexdigest()
    mapping = {cid: "PH"}
    original = {
        "source_cid": cid,
        "affected_cids": [cid, other],
        "derived_actions": [{"cid": cid, "source_evidence_cids_before": [cid, other]}],
        "kept": other,
    }
    redacted = redact_erased_cids(original, mapping)
    # Erased cid gone everywhere; retained cid preserved.
    flat = repr(redacted)
    assert cid not in flat and "PH" in flat
    assert redacted["affected_cids"] == ["PH", other]
    assert redacted["derived_actions"][0]["source_evidence_cids_before"] == ["PH", other]
    # Input structure is NOT mutated (caller keeps the real cids).
    assert original["source_cid"] == cid
    assert original["affected_cids"] == [cid, other]
