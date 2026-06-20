from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from mnemosyne.security import (
    OidcJwtVerifier,
    SessionAuthError,
    SessionIdentity,
    SessionTokenVerifier,
    TrustTier,
    issue_session_from_oidc,
    parse_session_keyring,
    parse_session_revoke_list,
)


SECRET = "session-unit-secret"
ISSUER = "https://idp.example.test/"
AUDIENCE = "mnemosyne-production"


def sign_payload(payload: dict[str, object]) -> str:
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = base64.urlsafe_b64encode(
        hmac.new(SECRET.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return f"{encoded_payload}.{signature}"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def signed_oidc_token(
    payload: dict[str, object],
    *,
    kid: str = "idp-key-1",
    alg: str = "RS256",
    private_key: rsa.RSAPrivateKey | None = None,
) -> tuple[dict[str, object], str]:
    key = private_key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "alg": "RS256",
                "use": "sig",
                "n": b64url(public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")),
                "e": b64url(public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")),
            }
        ]
    }
    header = {"alg": alg, "kid": kid, "typ": "JWT"}
    header_b64 = b64url(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    payload_b64 = b64url(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return jwks, f"{header_b64}.{payload_b64}.{b64url(signature)}"


def signed_es256_oidc_token(payload: dict[str, object], *, kid: str = "idp-ec-key-1") -> tuple[dict[str, object], str]:
    key = ec.generate_private_key(ec.SECP256R1())
    public_numbers = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "EC",
                "kid": kid,
                "alg": "ES256",
                "use": "sig",
                "crv": "P-256",
                "x": b64url(public_numbers.x.to_bytes(32, "big")),
                "y": b64url(public_numbers.y.to_bytes(32, "big")),
            }
        ]
    }
    header = {"alg": "ES256", "kid": kid, "typ": "JWT"}
    header_b64 = b64url(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    payload_b64 = b64url(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return jwks, f"{header_b64}.{payload_b64}.{b64url(signature)}"


def oidc_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-a",
        "tenant_id": "tenant-a",
        "mnemosyne_role": "operator",
        "mnemosyne_source_trust_tier": int(TrustTier.USER_AUTHORED),
        "exp": 2_000_000_000,
        "nbf": 1_800_000_000,
        "iat": 1_800_000_000,
        "jti": "idp-session-a",
    }
    payload.update(overrides)
    return payload


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


def test_session_token_verifier_supports_keyring_rotation() -> None:
    keyring = {"old": "old-secret", "current": "current-secret"}
    identity = SessionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        role="operator",
        source_trust_tier=int(TrustTier.USER_AUTHORED),
        session_id="session-a",
    )

    token = SessionTokenVerifier(keyring, active_key_id="current").sign(identity)
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "==").decode("utf-8"))
    verified = SessionTokenVerifier(keyring, active_key_id="current").verify(token)

    assert payload["kid"] == "current"
    assert verified == identity


def test_session_token_verifier_rejects_revoked_key_and_session_ids() -> None:
    keyring = {"old": "old-secret", "current": "current-secret"}
    identity = SessionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        role="operator",
        source_trust_tier=int(TrustTier.USER_AUTHORED),
        session_id="session-a",
    )
    token = SessionTokenVerifier(keyring, active_key_id="old").sign(identity)

    with pytest.raises(SessionAuthError, match="key id is revoked"):
        SessionTokenVerifier(keyring, active_key_id="current", revoked_key_ids={"old"}).verify(token)
    with pytest.raises(SessionAuthError, match="session id is revoked"):
        SessionTokenVerifier(keyring, active_key_id="current", revoked_session_ids={"session-a"}).verify(token)


def test_session_token_verifier_requires_known_key_id_for_keyrings() -> None:
    token_without_key = SessionTokenVerifier(SECRET).sign(
        SessionIdentity(
            tenant_id="tenant-a",
            user_id="user-a",
            role="operator",
            source_trust_tier=int(TrustTier.USER_AUTHORED),
        )
    )

    with pytest.raises(SessionAuthError, match="key id is required"):
        SessionTokenVerifier({"current": "current-secret"}).verify(token_without_key)


def test_session_keyring_parsers_accept_json_and_csv() -> None:
    assert parse_session_keyring('{"old":"a","current":"b"}') == {"old": "a", "current": "b"}
    assert parse_session_keyring("old=a,current=b") == {"old": "a", "current": "b"}
    assert parse_session_revoke_list("old, session-a,") == {"old", "session-a"}


def test_oidc_jwt_verifier_maps_valid_jwks_token_to_session_identity() -> None:
    jwks, token = signed_oidc_token(oidc_payload())

    identity = OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE).verify(token, now=1_900_000_000)

    assert identity == SessionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        role="operator",
        source_trust_tier=int(TrustTier.USER_AUTHORED),
        expires_at=2_000_000_000,
        session_id="idp-session-a",
    )


@pytest.mark.parametrize(
    ("payload_overrides", "message"),
    [
        ({"iss": "https://evil.example.test/"}, "issuer"),
        ({"aud": "other-audience"}, "audience"),
        ({"exp": 100}, "expired"),
        ({"nbf": 2_100_000_000}, "not yet valid"),
        ({"iat": 2_100_000_000}, "issued-at"),
        ({"mnemosyne_role": "admin"}, "role"),
        ({"mnemosyne_source_trust_tier": 99}, "source_trust_tier"),
        ({"tenant_id": ""}, "tenant_id"),
    ],
)
def test_oidc_jwt_verifier_rejects_invalid_claims(payload_overrides: dict[str, object], message: str) -> None:
    jwks, token = signed_oidc_token(oidc_payload(**payload_overrides))

    with pytest.raises(SessionAuthError, match=message):
        OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE).verify(token, now=1_900_000_000)


def test_oidc_jwt_verifier_rejects_unknown_kid_bad_alg_and_tampering() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks, token = signed_oidc_token(oidc_payload(), kid="known", private_key=key)
    _, unknown_kid_token = signed_oidc_token(oidc_payload(), kid="unknown", private_key=key)
    _, bad_alg_token = signed_oidc_token(oidc_payload(), alg="none", private_key=key)
    header, _, signature = token.split(".")
    tampered_payload = b64url(
        json.dumps({**oidc_payload(), "tenant_id": "tenant-b"}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )

    verifier = OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE)
    with pytest.raises(SessionAuthError, match="kid is unknown"):
        verifier.verify(unknown_kid_token, now=1_900_000_000)
    with pytest.raises(SessionAuthError, match="alg is not allowed"):
        verifier.verify(bad_alg_token, now=1_900_000_000)
    with pytest.raises(SessionAuthError, match="signature is invalid"):
        verifier.verify(f"{header}.{tampered_payload}.{signature}", now=1_900_000_000)


def test_oidc_jwt_verifier_supports_es256_jwks_tokens() -> None:
    jwks, token = signed_es256_oidc_token(oidc_payload())

    identity = OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE).verify(token, now=1_900_000_000)

    assert identity.tenant_id == "tenant-a"
    assert identity.user_id == "user-a"
    assert identity.role == "operator"


@pytest.mark.parametrize(
    ("payload_overrides", "message"),
    [
        ({"sub": ""}, "sub"),
        ({"mnemosyne_role": ""}, "mnemosyne_role"),
        ({"mnemosyne_source_trust_tier": ""}, "mnemosyne_source_trust_tier"),
        ({"aud": [{"nested": "bad"}]}, "audience"),
        ({"exp": ""}, "exp is invalid"),
        ({"nbf": "soon"}, "nbf is invalid"),
        ({"iat": "later"}, "iat is invalid"),
    ],
)
def test_oidc_jwt_verifier_rejects_missing_or_malformed_claims(payload_overrides: dict[str, object], message: str) -> None:
    jwks, token = signed_oidc_token(oidc_payload(**payload_overrides))

    with pytest.raises(SessionAuthError, match=message):
        OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE).verify(token, now=1_900_000_000)


def test_oidc_jwt_verifier_rejects_unsafe_jwks_metadata() -> None:
    jwks, _ = signed_oidc_token(oidc_payload())
    duplicate = {"keys": [jwks["keys"][0], dict(jwks["keys"][0])]}
    wrong_use = {"keys": [{**jwks["keys"][0], "use": "enc"}]}
    wrong_ops = {"keys": [{**jwks["keys"][0], "key_ops": ["sign"]}]}

    with pytest.raises(SessionAuthError, match="duplicate kid"):
        OidcJwtVerifier(duplicate, issuer=ISSUER, audience=AUDIENCE)
    with pytest.raises(SessionAuthError, match="key use"):
        OidcJwtVerifier(wrong_use, issuer=ISSUER, audience=AUDIENCE)
    with pytest.raises(SessionAuthError, match="key_ops"):
        OidcJwtVerifier(wrong_ops, issuer=ISSUER, audience=AUDIENCE)
    with pytest.raises(SessionAuthError, match="allowed algorithms"):
        OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE, allowed_algorithms=())


def test_oidc_jwt_verifier_refreshes_jwks_for_unknown_kid() -> None:
    old_jwks, _ = signed_oidc_token(oidc_payload(), kid="old-key")
    new_jwks, token = signed_oidc_token(oidc_payload(), kid="new-key")
    refreshes = 0

    def load_rotated_jwks() -> dict[str, object]:
        nonlocal refreshes
        refreshes += 1
        return new_jwks

    identity = OidcJwtVerifier(
        old_jwks,
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_loader=load_rotated_jwks,
        jwks_cache_ttl_seconds=300,
    ).verify(token, now=1_900_000_000)

    assert identity.tenant_id == "tenant-a"
    assert refreshes == 1


def test_oidc_jwt_verifier_can_disable_unknown_kid_refresh() -> None:
    old_jwks, _ = signed_oidc_token(oidc_payload(), kid="old-key")
    new_jwks, token = signed_oidc_token(oidc_payload(), kid="new-key")

    def load_rotated_jwks() -> dict[str, object]:
        return new_jwks

    verifier = OidcJwtVerifier(
        old_jwks,
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_loader=load_rotated_jwks,
        refresh_on_unknown_kid=False,
    )

    with pytest.raises(SessionAuthError, match="kid is unknown"):
        verifier.verify(token, now=1_900_000_000)


def test_oidc_jwt_verifier_refreshes_expired_jwks_cache() -> None:
    old_jwks, _ = signed_oidc_token(oidc_payload(), kid="shared-key")
    new_jwks, token = signed_oidc_token(oidc_payload(), kid="shared-key")
    refreshes = 0

    def load_rotated_jwks() -> dict[str, object]:
        nonlocal refreshes
        refreshes += 1
        return new_jwks

    identity = OidcJwtVerifier(
        old_jwks,
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_loader=load_rotated_jwks,
        jwks_cache_ttl_seconds=0,
    ).verify(token, now=1_900_000_000)

    assert identity.user_id == "user-a"
    assert refreshes == 1


def test_oidc_jwt_verifier_fails_closed_when_jwks_refresh_fails() -> None:
    jwks, token = signed_oidc_token(oidc_payload())

    def fail_refresh() -> dict[str, object]:
        raise RuntimeError("network unavailable")

    verifier = OidcJwtVerifier(
        jwks,
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_loader=fail_refresh,
        jwks_cache_ttl_seconds=0,
    )

    with pytest.raises(SessionAuthError, match="JWKS refresh failed"):
        verifier.verify(token, now=1_900_000_000)


def test_issue_session_from_oidc_rejects_non_positive_ttl() -> None:
    jwks, token = signed_oidc_token(oidc_payload())
    verifier = OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE)

    with pytest.raises(SessionAuthError, match="max TTL"):
        issue_session_from_oidc(
            verifier=verifier,
            idp_token=token,
            signer=SessionTokenVerifier(SECRET),
            max_ttl_seconds=0,
            now=1_900_000_000,
        )
