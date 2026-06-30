from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from mnemosyne.security import (
    OidcAuthorizationPolicy,
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
MFA_ACR = "urn:mnemosyne:mfa"
MFA_RULE = {
    "required_acr": MFA_ACR,
    "required_amr": "mfa",
    "max_auth_age_seconds": 300,
}


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
        "auth_time": 1_899_999_900,
        "acr": MFA_ACR,
        "amr": ["pwd", "mfa"],
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


def test_oidc_jwt_verifier_selects_signing_key_from_mixed_jwks() -> None:
    """Real IdPs (Keycloak, Auth0, Azure AD) publish encryption keys alongside
    the signing key in one JWKS. The verifier must select the ``use:sig`` key
    and ignore non-signing keys rather than rejecting the whole document."""

    jwks, token = signed_oidc_token(oidc_payload())
    sig_key = jwks["keys"][0]
    enc_key = {**sig_key, "kid": "idp-enc-key", "use": "enc", "alg": "RSA-OAEP"}
    sign_only_key = {**sig_key, "kid": "idp-sign-only", "key_ops": ["sign"]}
    mixed = {"keys": [enc_key, sign_only_key, sig_key]}

    identity = OidcJwtVerifier(mixed, issuer=ISSUER, audience=AUDIENCE).verify(token, now=1_900_000_000)

    assert identity.tenant_id == "tenant-a"
    assert identity.user_id == "user-a"


def test_oidc_jwt_verifier_rejects_unsafe_jwks_metadata() -> None:
    jwks, _ = signed_oidc_token(oidc_payload())
    duplicate = {"keys": [jwks["keys"][0], dict(jwks["keys"][0])]}
    only_enc = {"keys": [{**jwks["keys"][0], "use": "enc"}]}
    only_sign_ops = {"keys": [{**jwks["keys"][0], "key_ops": ["sign"]}]}

    with pytest.raises(SessionAuthError, match="duplicate kid"):
        OidcJwtVerifier(duplicate, issuer=ISSUER, audience=AUDIENCE)
    # A JWKS whose only key cannot verify signatures leaves nothing usable.
    with pytest.raises(SessionAuthError, match="no usable signing key"):
        OidcJwtVerifier(only_enc, issuer=ISSUER, audience=AUDIENCE)
    with pytest.raises(SessionAuthError, match="no usable signing key"):
        OidcJwtVerifier(only_sign_ops, issuer=ISSUER, audience=AUDIENCE)
    with pytest.raises(SessionAuthError, match="allowed algorithms"):
        OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE, allowed_algorithms=())


@pytest.mark.skipif(
    not os.environ.get("MNEMOSYNE_OIDC_JWKS_URL"),
    reason="live IdP JWKS test requires MNEMOSYNE_OIDC_JWKS_URL (e.g. a local Keycloak certs endpoint)",
)
def test_oidc_jwt_verifier_loads_real_idp_jwks_live() -> None:
    """Operator-run evidence: load a real IdP's JWKS (mixed sig+enc keyset) and
    confirm the verifier installs at least one usable signing key.

    Enable with, e.g.::

        MNEMOSYNE_OIDC_JWKS_URL=http://127.0.0.1:8089/realms/master/protocol/openid-connect/certs \\
        MNEMOSYNE_OIDC_ISSUER=http://127.0.0.1:8089/realms/master uv run pytest \\
        tests/test_security_sessions.py -k real_idp_jwks_live
    """

    from mnemosyne.oidc_jwks import load_oidc_jwks

    jwks_url = os.environ["MNEMOSYNE_OIDC_JWKS_URL"]
    issuer = os.environ.get("MNEMOSYNE_OIDC_ISSUER", jwks_url)
    jwks = load_oidc_jwks(
        jwks=None,
        jwks_file=None,
        jwks_url=jwks_url,
        allow_insecure_url=True,
        timeout=10.0,
        max_bytes=1_000_000,
    )
    assert isinstance(jwks.get("keys"), list) and jwks["keys"]

    verifier = OidcJwtVerifier(jwks, issuer=issuer, audience="mnemosyne")
    # The real keyset installed at least one verifiable signing key.
    assert verifier.keys_by_id
    assert all(key.get("use", "sig") == "sig" for key in verifier.keys_by_id.values())


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


def test_oidc_authorization_policy_maps_claims_without_raw_role_or_trust() -> None:
    payload = oidc_payload(groups=["mnemosyne-operators"], scope="openid mnemosyne.write", azp="cli-client")
    payload.pop("mnemosyne_role")
    payload.pop("mnemosyne_source_trust_tier")
    jwks, token = signed_oidc_token(payload)
    policy = OidcAuthorizationPolicy.from_mapping(
        {
            "allowed_client_ids": ["cli-client"],
            "rules": [
                {
                    "tenant_ids": ["tenant-a"],
                    "claim_contains": {
                        "groups": ["mnemosyne-operators"],
                        "scope": "mnemosyne.write",
                    },
                    "role": "operator",
                    "source_trust_tier": 0,
                    **MFA_RULE,
                }
            ],
        }
    )

    identity = OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE, authorization_policy=policy).verify(
        token,
        now=1_900_000_000,
    )

    assert identity.tenant_id == "tenant-a"
    assert identity.user_id == "user-a"
    assert identity.role == "operator"
    assert identity.source_trust_tier == 0
    assert identity.session_id == "idp-session-a"


def test_oidc_authorization_policy_rejects_elevated_rules_without_mfa() -> None:
    with pytest.raises(SessionAuthError, match="non-tenant claim matcher"):
        OidcAuthorizationPolicy.from_mapping(
            {
                "allowed_client_ids": ["cli-client"],
                "rules": [
                    {
                        "tenant_ids": ["tenant-a"],
                        "role": "operator",
                        "source_trust_tier": 0,
                    }
                ],
            }
        )
    with pytest.raises(SessionAuthError, match="requires required_acr"):
        OidcAuthorizationPolicy.from_mapping(
            {
                "allowed_client_ids": ["cli-client"],
                "rules": [
                    {
                        "tenant_ids": ["tenant-a"],
                        "claim_contains": {"groups": "mnemosyne-operators"},
                        "role": "operator",
                        "source_trust_tier": 0,
                    }
                ],
            }
        )
    with pytest.raises(SessionAuthError, match="requires required_amr"):
        OidcAuthorizationPolicy.from_mapping(
            {
                "allowed_client_ids": ["cli-client"],
                "rules": [
                    {
                        "tenant_ids": ["tenant-a"],
                        "claim_contains": {"groups": "mnemosyne-operators"},
                        "required_acr": MFA_ACR,
                        "role": "operator",
                        "source_trust_tier": 0,
                    }
                ],
            }
        )
    with pytest.raises(SessionAuthError, match="requires max_auth_age_seconds"):
        OidcAuthorizationPolicy.from_mapping(
            {
                "allowed_client_ids": ["cli-client"],
                "rules": [
                    {
                        "tenant_ids": ["tenant-a"],
                        "claim_contains": {"groups": "mnemosyne-operators"},
                        "required_acr": MFA_ACR,
                        "required_amr": "mfa",
                        "role": "operator",
                        "source_trust_tier": 0,
                    }
                ],
            }
        )


def test_oidc_authorization_policy_rejects_stale_or_missing_mfa_claims() -> None:
    policy = OidcAuthorizationPolicy.from_mapping(
        {
            "allowed_client_ids": ["cli-client"],
            "rules": [
                {
                    "tenant_ids": ["tenant-a"],
                    "claim_contains": {"groups": "mnemosyne-operators"},
                    "role": "operator",
                    "source_trust_tier": 0,
                    **MFA_RULE,
                }
            ],
        }
    )
    base_payload = oidc_payload(groups=["mnemosyne-operators"], azp="cli-client")

    stale_payload = dict(base_payload, auth_time=1_899_999_000)
    with pytest.raises(SessionAuthError, match="not authorized"):
        policy.authorize(
            stale_payload,
            tenant_id="tenant-a",
            user_id="user-a",
            expires_at=2_000_000_000,
            session_id="idp-session-a",
            now=1_900_000_000,
        )

    missing_amr = dict(base_payload)
    missing_amr.pop("amr")
    with pytest.raises(SessionAuthError, match="not authorized"):
        policy.authorize(
            missing_amr,
            tenant_id="tenant-a",
            user_id="user-a",
            expires_at=2_000_000_000,
            session_id="idp-session-a",
            now=1_900_000_000,
        )


def test_oidc_authorization_policy_supports_agent_role_and_claim_equals() -> None:
    payload = oidc_payload(department="memory-platform", azp="cli-client")
    payload.pop("mnemosyne_role")
    payload.pop("mnemosyne_source_trust_tier")
    jwks, token = signed_oidc_token(payload)
    policy = OidcAuthorizationPolicy.from_mapping(
        {
            "allowed_client_ids": ["cli-client"],
            "rules": [
                {
                    "tenant_ids": ["tenant-a"],
                    "claim_equals": {"department": "memory-platform"},
                    "role": "agent",
                    "source_trust_tier": 3,
                }
            ],
        }
    )

    identity = OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE, authorization_policy=policy).verify(
        token,
        now=1_900_000_000,
    )

    assert identity.role == "agent"
    assert identity.source_trust_tier == 3


def test_oidc_authorization_policy_claim_equals_requires_exact_list_match() -> None:
    payload = oidc_payload(departments=["memory-platform", "security"], azp="cli-client")
    payload.pop("mnemosyne_role")
    payload.pop("mnemosyne_source_trust_tier")
    jwks, token = signed_oidc_token(payload)
    partial_policy = OidcAuthorizationPolicy.from_mapping(
        {
            "allowed_client_ids": ["cli-client"],
            "rules": [
                {
                    "claim_equals": {"departments": ["memory-platform"]},
                    "role": "agent",
                    "source_trust_tier": 3,
                }
            ],
        }
    )

    with pytest.raises(SessionAuthError, match="not authorized"):
        OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE, authorization_policy=partial_policy).verify(
            token,
            now=1_900_000_000,
        )

    exact_policy = OidcAuthorizationPolicy.from_mapping(
        {
            "allowed_client_ids": ["cli-client"],
            "rules": [
                {
                    "claim_equals": {"departments": ["memory-platform", "security"]},
                    "role": "agent",
                    "source_trust_tier": 3,
                }
            ],
        }
    )

    identity = OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE, authorization_policy=exact_policy).verify(
        token,
        now=1_900_000_000,
    )
    assert identity.role == "agent"


def test_oidc_authorization_policy_denies_unmatched_client_and_rules() -> None:
    payload = oidc_payload(groups=["mnemosyne-readers"], scope="openid", azp="wrong-client")
    jwks, token = signed_oidc_token(payload)
    policy = OidcAuthorizationPolicy.from_mapping(
        {
            "allowed_client_ids": ["cli-client"],
            "rules": [
                {
                    "tenant_ids": ["tenant-a"],
                    "claim_contains": {"groups": "mnemosyne-operators"},
                    "role": "operator",
                    "source_trust_tier": 0,
                    **MFA_RULE,
                }
            ],
        }
    )

    with pytest.raises(SessionAuthError, match="client is not authorized"):
        OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE, authorization_policy=policy).verify(
            token,
            now=1_900_000_000,
        )

    payload["azp"] = "cli-client"
    jwks, token = signed_oidc_token(payload)
    with pytest.raises(SessionAuthError, match="not authorized"):
        OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE, authorization_policy=policy).verify(
            token,
            now=1_900_000_000,
        )


def test_oidc_authorization_policy_rejects_malformed_or_ambiguous_rules() -> None:
    with pytest.raises(SessionAuthError, match="allowed_client_ids"):
        OidcAuthorizationPolicy.from_mapping(
            {
                "rules": [
                    {
                        "tenant_ids": ["tenant-a"],
                        "claim_contains": {"groups": "mnemosyne-operators"},
                        "role": "operator",
                        "source_trust_tier": 0,
                        **MFA_RULE,
                    }
                ]
            }
        )
    with pytest.raises(SessionAuthError, match="role"):
        OidcAuthorizationPolicy.from_mapping(
            {
                "allowed_client_ids": ["cli-client"],
                "rules": [
                    {
                        "tenant_ids": ["tenant-a"],
                        "claim_contains": {"groups": "mnemosyne-operators"},
                        "role": "writer",
                        "source_trust_tier": 0,
                        **MFA_RULE,
                    }
                ],
            }
        )
    with pytest.raises(SessionAuthError, match="unknown fields"):
        OidcAuthorizationPolicy.from_mapping(
            {
                "allowed_client_ids": ["cli-client"],
                "unexpected": True,
                "rules": [
                    {
                        "tenant_ids": ["tenant-a"],
                        "claim_contains": {"groups": "mnemosyne-operators"},
                        "role": "operator",
                        "source_trust_tier": 0,
                        **MFA_RULE,
                    }
                ],
            }
        )

    payload = oidc_payload(groups=["mnemosyne-operators"], azp="cli-client")
    jwks, token = signed_oidc_token(payload)
    policy = OidcAuthorizationPolicy.from_mapping(
        {
            "allowed_client_ids": ["cli-client"],
            "rules": [
                {
                    "tenant_ids": ["tenant-a"],
                    "claim_contains": {"groups": "mnemosyne-operators"},
                    "role": "operator",
                    "source_trust_tier": 0,
                    **MFA_RULE,
                },
                {
                    "tenant_ids": ["tenant-a"],
                    "claim_contains": {"groups": "mnemosyne-operators"},
                    "role": "consolidator",
                    "source_trust_tier": 1,
                    **MFA_RULE,
                },
            ],
        }
    )
    with pytest.raises(SessionAuthError, match="multiple authorization rules"):
        OidcJwtVerifier(jwks, issuer=ISSUER, audience=AUDIENCE, authorization_policy=policy).verify(
            token,
            now=1_900_000_000,
        )


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
