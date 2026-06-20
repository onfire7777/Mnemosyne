from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from mnemosyne.security import SessionAuthError, SessionIdentity, SessionTokenVerifier, TrustTier


SECRET = "session-unit-secret"


def sign_payload(payload: dict[str, object]) -> str:
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = base64.urlsafe_b64encode(
        hmac.new(SECRET.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return f"{encoded_payload}.{signature}"


def test_session_token_verifier_round_trips_identity() -> None:
    identity = SessionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        role="operator",
        source_trust_tier=int(TrustTier.USER_AUTHORED),
        expires_at=2_000_000_000,
        session_id="session-a",
    )
    token = SessionTokenVerifier(SECRET).sign(identity)

    verified = SessionTokenVerifier(SECRET).verify(token, now=1_900_000_000)

    assert verified == identity


def test_session_token_verifier_rejects_tampering() -> None:
    token = SessionTokenVerifier(SECRET).sign(
        SessionIdentity(
            tenant_id="tenant-a",
            user_id="user-a",
            role="operator",
            source_trust_tier=int(TrustTier.USER_AUTHORED),
        )
    )
    payload, signature = token.split(".")
    tampered_payload = payload[:-1] + ("A" if payload[-1] != "A" else "B")

    with pytest.raises(SessionAuthError, match="signature is invalid"):
        SessionTokenVerifier(SECRET).verify(f"{tampered_payload}.{signature}")


def test_session_token_verifier_rejects_expired_tokens() -> None:
    token = SessionTokenVerifier(SECRET).sign(
        SessionIdentity(
            tenant_id="tenant-a",
            user_id="user-a",
            role="operator",
            source_trust_tier=int(TrustTier.USER_AUTHORED),
            expires_at=100,
        )
    )

    with pytest.raises(SessionAuthError, match="expired"):
        SessionTokenVerifier(SECRET).verify(token, now=101)


def test_session_token_verifier_rejects_invalid_claims() -> None:
    invalid_role = sign_payload(
        {
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "role": "admin",
            "source_trust_tier": int(TrustTier.USER_AUTHORED),
        }
    )
    invalid_trust = sign_payload(
        {
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "role": "operator",
            "source_trust_tier": int(TrustTier.UNTRUSTED_EXTERNAL) + 1,
        }
    )

    with pytest.raises(SessionAuthError, match="role is not allowed"):
        SessionTokenVerifier(SECRET).verify(invalid_role)
    with pytest.raises(SessionAuthError, match="source_trust_tier is out of range"):
        SessionTokenVerifier(SECRET).verify(invalid_trust)
