"""Capability mediation and trust-boundary enforcement."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass
from enum import IntEnum
from collections.abc import Mapping
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


class TrustTier(IntEnum):
    DIRECT_USER = 0
    USER_AUTHORED = 0
    OPERATOR = 0
    VERIFIED = 1
    AUTHENTICATED = 2
    NORMAL = 3
    LOW = 4
    UNTRUSTED_EXTERNAL = 5
    UNTRUSTED = 5


def more_trusted(left: int, right: int) -> int:
    """Return the more trusted tier on the blueprint's lower-is-better scale."""

    return min(left, right)


def less_trusted(left: int, right: int) -> int:
    """Return the less trusted tier on the blueprint's lower-is-better scale."""

    return max(left, right)


def meets_trust(source_tier: int, required_tier: int) -> bool:
    """True when source_tier is at least as trusted as required_tier."""

    return source_tier <= required_tier


def trust_weight(trust_tier: int) -> float:
    """Convert blueprint trust tiers to a confidence multiplier."""

    bounded = min(max(trust_tier, int(TrustTier.DIRECT_USER)), int(TrustTier.UNTRUSTED_EXTERNAL))
    return 1.0 - (bounded / float(TrustTier.UNTRUSTED_EXTERNAL))


WriteRole = Literal["reader", "agent", "consolidator", "operator"]
_WRITE_ROLES = {"reader", "agent", "consolidator", "operator"}


class SessionAuthError(ValueError):
    """Raised when a session token is missing, malformed, expired, or invalid."""


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    tenant_id: str
    user_id: str
    role: WriteRole
    source_trust_tier: int
    expires_at: int | None = None
    session_id: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SessionIdentity":
        role = str(payload.get("role", ""))
        if role not in _WRITE_ROLES:
            raise SessionAuthError("session role is not allowed")
        tenant_id = str(payload.get("tenant_id") or payload.get("tenant") or "")
        user_id = str(payload.get("user_id") or payload.get("user") or "")
        if not tenant_id or not user_id:
            raise SessionAuthError("session tenant_id and user_id are required")
        try:
            source_trust_tier = int(payload.get("source_trust_tier", payload.get("trust_tier", TrustTier.NORMAL)))
        except (TypeError, ValueError) as exc:
            raise SessionAuthError("session source_trust_tier is invalid") from exc
        if source_trust_tier < int(TrustTier.DIRECT_USER) or source_trust_tier > int(TrustTier.UNTRUSTED_EXTERNAL):
            raise SessionAuthError("session source_trust_tier is out of range")
        expires_at = payload.get("exp", payload.get("expires_at"))
        try:
            parsed_expires_at = int(expires_at) if expires_at is not None else None
        except (TypeError, ValueError) as exc:
            raise SessionAuthError("session exp is invalid") from exc
        return cls(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,  # type: ignore[arg-type]
            source_trust_tier=source_trust_tier,
            expires_at=parsed_expires_at,
            session_id=str(payload["session_id"]) if payload.get("session_id") else None,
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "role": self.role,
            "source_trust_tier": self.source_trust_tier,
        }
        if self.expires_at is not None:
            payload["exp"] = self.expires_at
        if self.session_id:
            payload["session_id"] = self.session_id
        return payload


class SessionTokenVerifier:
    """HMAC-SHA256 verifier for transport-provided Mnemosyne session claims."""

    def __init__(
        self,
        secret: str | bytes | Mapping[str, str | bytes],
        *,
        active_key_id: str | None = None,
        revoked_key_ids: set[str] | None = None,
        revoked_session_ids: set[str] | None = None,
    ):
        self.revoked_key_ids = set(revoked_key_ids or set())
        self.revoked_session_ids = set(revoked_session_ids or set())
        self.active_key_id: str | None = None
        if isinstance(secret, Mapping):
            self.secrets: dict[str | None, bytes] = {}
            for key_id, value in secret.items():
                normalized_key_id = str(key_id).strip()
                if not normalized_key_id:
                    raise SessionAuthError("session key id is required")
                normalized_secret = value.encode("utf-8") if isinstance(value, str) else bytes(value)
                if not normalized_secret:
                    raise SessionAuthError(f"session secret for key {normalized_key_id} is required")
                self.secrets[normalized_key_id] = normalized_secret
            if not self.secrets:
                raise SessionAuthError("session keyring is required")
            if active_key_id is not None:
                if active_key_id not in self.secrets:
                    raise SessionAuthError("active session key id is unknown")
                self.active_key_id = active_key_id
            elif len(self.secrets) == 1:
                self.active_key_id = next(iter(self.secrets))
        else:
            normalized_secret = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
            if not normalized_secret:
                raise SessionAuthError("session secret is required")
            self.secrets = {None: normalized_secret}

    def sign(self, identity: SessionIdentity) -> str:
        payload_data = identity.to_payload()
        if self.active_key_id is not None:
            if self.active_key_id in self.revoked_key_ids:
                raise SessionAuthError("active session key id is revoked")
            payload_data["kid"] = self.active_key_id
        payload = _b64url_encode(json.dumps(payload_data, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = _b64url_encode(hmac.new(self._signing_secret(), payload.encode("ascii"), hashlib.sha256).digest())
        return f"{payload}.{signature}"

    def verify(self, token: str, *, now: int | None = None) -> SessionIdentity:
        parts = token.split(".")
        if len(parts) != 2:
            raise SessionAuthError("session token must be payload.signature")
        payload_b64, signature_b64 = parts
        if None in self.secrets:
            try:
                expected = _b64url_encode(hmac.new(self.secrets[None], payload_b64.encode("ascii"), hashlib.sha256).digest())
            except UnicodeEncodeError as exc:
                raise SessionAuthError("session token must be payload.signature") from exc
            if not hmac.compare_digest(signature_b64, expected):
                raise SessionAuthError("session token signature is invalid")
        try:
            payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise SessionAuthError("session token payload is invalid") from exc
        if not isinstance(payload, dict):
            raise SessionAuthError("session token payload is invalid")
        key_id = payload.get("kid")
        if key_id is not None:
            key_id = str(key_id)
        secret = self._verification_secret(key_id)
        if None not in self.secrets:
            try:
                expected = _b64url_encode(hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).digest())
            except UnicodeEncodeError as exc:
                raise SessionAuthError("session token must be payload.signature") from exc
            if not hmac.compare_digest(signature_b64, expected):
                raise SessionAuthError("session token signature is invalid")
        identity = SessionIdentity.from_payload(payload)
        now_ts = int(time.time()) if now is None else now
        if identity.expires_at is not None and identity.expires_at <= now_ts:
            raise SessionAuthError("session token is expired")
        if identity.session_id and identity.session_id in self.revoked_session_ids:
            raise SessionAuthError("session id is revoked")
        return identity

    def _signing_secret(self) -> bytes:
        if self.active_key_id is not None:
            return self.secrets[self.active_key_id]
        if None not in self.secrets:
            raise SessionAuthError("active session key id is required")
        return self.secrets[None]

    def _verification_secret(self, key_id: str | None) -> bytes:
        if key_id is not None and key_id in self.revoked_key_ids:
            raise SessionAuthError("session token key id is revoked")
        if None in self.secrets:
            return self.secrets[None]
        if key_id is None:
            raise SessionAuthError("session token key id is required")
        if key_id not in self.secrets:
            raise SessionAuthError("session token key id is unknown")
        return self.secrets[key_id]


def parse_session_keyring(raw: str | None) -> dict[str, str]:
    """Parse a JSON object or comma-separated kid=secret session keyring."""

    if not raw:
        return {}
    stripped = raw.strip()
    if not stripped:
        return {}
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SessionAuthError("session keyring JSON is invalid") from exc
        if not isinstance(data, dict):
            raise SessionAuthError("session keyring must be a JSON object")
        return {str(key).strip(): str(value) for key, value in data.items() if str(key).strip()}
    keyring: dict[str, str] = {}
    for entry in stripped.split(","):
        if not entry.strip():
            continue
        if "=" not in entry:
            raise SessionAuthError("session keyring entries must be kid=secret")
        key_id, value = entry.split("=", 1)
        key_id = key_id.strip()
        if not key_id:
            raise SessionAuthError("session key id is required")
        keyring[key_id] = value
    return keyring


def parse_session_revoke_list(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


class OidcJwtVerifier:
    """Verify production IdP JWTs against OIDC/JWKS policy and map them to session claims."""

    _ALG_HASHES = {
        "RS256": hashes.SHA256,
        "RS384": hashes.SHA384,
        "RS512": hashes.SHA512,
        "ES256": hashes.SHA256,
        "ES384": hashes.SHA384,
        "ES512": hashes.SHA512,
    }
    _EC_CURVES = {
        "P-256": ec.SECP256R1,
        "P-384": ec.SECP384R1,
        "P-521": ec.SECP521R1,
    }

    def __init__(
        self,
        jwks: Mapping[str, Any],
        *,
        issuer: str,
        audience: str,
        tenant_claim: str = "tenant_id",
        user_claim: str = "sub",
        role_claim: str = "mnemosyne_role",
        trust_claim: str = "mnemosyne_source_trust_tier",
        session_id_claim: str = "jti",
        allowed_algorithms: tuple[str, ...] = ("RS256", "ES256"),
        leeway_seconds: int = 60,
    ):
        if not issuer:
            raise SessionAuthError("OIDC issuer is required")
        if not audience:
            raise SessionAuthError("OIDC audience is required")
        self.issuer = issuer
        self.audience = audience
        self.tenant_claim = tenant_claim
        self.user_claim = user_claim
        self.role_claim = role_claim
        self.trust_claim = trust_claim
        self.session_id_claim = session_id_claim
        self.allowed_algorithms = tuple(item for item in allowed_algorithms if item)
        if not self.allowed_algorithms:
            raise SessionAuthError("OIDC allowed algorithms are required")
        self.leeway_seconds = int(leeway_seconds)
        if self.leeway_seconds < 0:
            raise SessionAuthError("OIDC leeway must be non-negative")
        keys = jwks.get("keys")
        if not isinstance(keys, list) or not keys:
            raise SessionAuthError("OIDC JWKS must contain keys")
        self.keys_by_id: dict[str, Mapping[str, Any]] = {}
        for key in keys:
            if not isinstance(key, Mapping):
                continue
            key_id = str(key.get("kid") or "")
            if key_id:
                if key_id in self.keys_by_id:
                    raise SessionAuthError("OIDC JWKS contains duplicate kid")
                if key.get("use") not in (None, "sig"):
                    raise SessionAuthError("OIDC JWKS key use is not allowed")
                key_ops = key.get("key_ops")
                if key_ops is not None and (not isinstance(key_ops, list) or "verify" not in key_ops):
                    raise SessionAuthError("OIDC JWKS key_ops must allow verify")
                self.keys_by_id[key_id] = key
        if not self.keys_by_id:
            raise SessionAuthError("OIDC JWKS keys must include kid")

    def verify(self, token: str, *, now: int | None = None) -> SessionIdentity:
        header, payload, signing_input, signature = self._decode_compact_jwt(token)
        algorithm = str(header.get("alg") or "")
        if algorithm not in self.allowed_algorithms:
            raise SessionAuthError("OIDC token alg is not allowed")
        key_id = str(header.get("kid") or "")
        if not key_id:
            raise SessionAuthError("OIDC token kid is required")
        key = self.keys_by_id.get(key_id)
        if key is None:
            raise SessionAuthError("OIDC token kid is unknown")
        if str(key.get("alg") or algorithm) != algorithm:
            raise SessionAuthError("OIDC JWKS key alg does not match token alg")
        self._verify_signature(algorithm, key, signing_input, signature)
        self._verify_registered_claims(payload, now=now)
        return self._identity_from_claims(payload)

    @staticmethod
    def _decode_compact_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
        parts = token.split(".")
        if len(parts) != 3:
            raise SessionAuthError("OIDC token must be header.payload.signature")
        header_b64, payload_b64, signature_b64 = parts
        try:
            header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
            payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
            signature = _b64url_decode(signature_b64)
        except (binascii.Error, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise SessionAuthError("OIDC token is malformed") from exc
        if not isinstance(header, dict) or not isinstance(payload, dict):
            raise SessionAuthError("OIDC token header and payload must be JSON objects")
        return header, payload, f"{header_b64}.{payload_b64}".encode("ascii"), signature

    def _verify_signature(self, algorithm: str, key: Mapping[str, Any], signing_input: bytes, signature: bytes) -> None:
        try:
            if algorithm.startswith("RS"):
                public_key = self._rsa_public_key(key)
                public_key.verify(signature, signing_input, padding.PKCS1v15(), self._ALG_HASHES[algorithm]())
            elif algorithm.startswith("ES"):
                public_key = self._ec_public_key(key, algorithm)
                public_key.verify(
                    self._ecdsa_der_signature(algorithm, signature),
                    signing_input,
                    ec.ECDSA(self._ALG_HASHES[algorithm]()),
                )
            else:  # pragma: no cover - guarded by the allowed algorithm check.
                raise SessionAuthError("OIDC token alg is not allowed")
        except InvalidSignature as exc:
            raise SessionAuthError("OIDC token signature is invalid") from exc

    @staticmethod
    def _rsa_public_key(key: Mapping[str, Any]) -> rsa.RSAPublicKey:
        if key.get("kty") != "RSA":
            raise SessionAuthError("OIDC JWKS key type does not match RSA alg")
        try:
            n = int.from_bytes(_b64url_decode(str(key.get("n") or "")), "big")
            e = int.from_bytes(_b64url_decode(str(key.get("e") or "")), "big")
            public_key = rsa.RSAPublicNumbers(e=e, n=n).public_key()
        except (binascii.Error, ValueError) as exc:
            raise SessionAuthError("OIDC JWKS RSA key material is invalid") from exc
        if public_key.key_size < 2048:
            raise SessionAuthError("OIDC JWKS RSA key is too small")
        return public_key

    def _ec_public_key(self, key: Mapping[str, Any], algorithm: str) -> ec.EllipticCurvePublicKey:
        if key.get("kty") != "EC":
            raise SessionAuthError("OIDC JWKS key type does not match EC alg")
        curve_name = str(key.get("crv") or "")
        expected_curve = {"ES256": "P-256", "ES384": "P-384", "ES512": "P-521"}[algorithm]
        if curve_name != expected_curve:
            raise SessionAuthError("OIDC JWKS EC curve does not match token alg")
        curve_factory = self._EC_CURVES.get(curve_name)
        if curve_factory is None:
            raise SessionAuthError("OIDC JWKS EC curve is not supported")
        try:
            x = int.from_bytes(_b64url_decode(str(key.get("x") or "")), "big")
            y = int.from_bytes(_b64url_decode(str(key.get("y") or "")), "big")
            return ec.EllipticCurvePublicNumbers(x=x, y=y, curve=curve_factory()).public_key()
        except (binascii.Error, ValueError) as exc:
            raise SessionAuthError("OIDC JWKS EC key material is invalid") from exc

    @staticmethod
    def _ecdsa_der_signature(algorithm: str, signature: bytes) -> bytes:
        width = {"ES256": 32, "ES384": 48, "ES512": 66}[algorithm]
        if len(signature) != width * 2:
            raise SessionAuthError("OIDC ECDSA signature length is invalid")
        r = int.from_bytes(signature[:width], "big")
        s = int.from_bytes(signature[width:], "big")
        return encode_dss_signature(r, s)

    def _verify_registered_claims(self, payload: Mapping[str, Any], *, now: int | None) -> None:
        now_ts = int(time.time()) if now is None else int(now)
        if payload.get("iss") != self.issuer:
            raise SessionAuthError("OIDC token issuer is not allowed")
        aud = payload.get("aud")
        if isinstance(aud, str):
            audiences = {aud}
        elif isinstance(aud, list) and all(isinstance(item, str) for item in aud):
            audiences = set(aud)
        else:
            audiences = set()
        if self.audience not in audiences:
            raise SessionAuthError("OIDC token audience is not allowed")
        exp = payload.get("exp")
        if exp is None:
            raise SessionAuthError("OIDC token exp is required")
        try:
            exp_ts = int(exp)
        except (TypeError, ValueError) as exc:
            raise SessionAuthError("OIDC token exp is invalid") from exc
        if exp_ts < now_ts - self.leeway_seconds:
            raise SessionAuthError("OIDC token is expired")
        nbf = payload.get("nbf")
        if nbf is not None:
            try:
                nbf_ts = int(nbf)
            except (TypeError, ValueError) as exc:
                raise SessionAuthError("OIDC token nbf is invalid") from exc
            if nbf_ts > now_ts + self.leeway_seconds:
                raise SessionAuthError("OIDC token is not yet valid")
        iat = payload.get("iat")
        if iat is not None:
            try:
                iat_ts = int(iat)
            except (TypeError, ValueError) as exc:
                raise SessionAuthError("OIDC token iat is invalid") from exc
            if iat_ts > now_ts + self.leeway_seconds:
                raise SessionAuthError("OIDC token issued-at is in the future")

    def _identity_from_claims(self, payload: Mapping[str, Any]) -> SessionIdentity:
        identity_payload = {
            "tenant_id": self._required_claim(payload, self.tenant_claim),
            "user_id": self._required_claim(payload, self.user_claim),
            "role": self._required_claim(payload, self.role_claim),
            "source_trust_tier": self._required_claim(payload, self.trust_claim),
            "exp": payload["exp"],
        }
        session_id = payload.get(self.session_id_claim)
        if session_id:
            identity_payload["session_id"] = str(session_id)
        return SessionIdentity.from_payload(identity_payload)

    @staticmethod
    def _required_claim(payload: Mapping[str, Any], claim: str) -> Any:
        value = payload.get(claim)
        if value is None or value == "":
            raise SessionAuthError(f"OIDC token missing required claim: {claim}")
        return value


def issue_session_from_oidc(
    *,
    verifier: OidcJwtVerifier,
    idp_token: str,
    signer: SessionTokenVerifier,
    max_ttl_seconds: int = 3600,
    now: int | None = None,
) -> tuple[str, SessionIdentity]:
    if int(max_ttl_seconds) <= 0:
        raise SessionAuthError("session max TTL must be positive")
    identity = verifier.verify(idp_token, now=now)
    now_ts = int(time.time()) if now is None else int(now)
    max_exp = now_ts + int(max_ttl_seconds)
    issued = SessionIdentity(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        role=identity.role,
        source_trust_tier=identity.source_trust_tier,
        expires_at=min(identity.expires_at or max_exp, max_exp),
        session_id=identity.session_id,
    )
    return signer.sign(issued), issued


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


@dataclass(slots=True)
class CapabilityDecision:
    allowed: bool
    reason: str
    required_role: WriteRole
    required_trust: int
    operation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SecurityPolicy:
    min_preference_write_trust: int = int(TrustTier.USER_AUTHORED)
    min_belief_write_trust: int = int(TrustTier.NORMAL)
    min_correction_write_trust: int = int(TrustTier.USER_AUTHORED)
    min_branch_write_trust: int = int(TrustTier.NORMAL)
    min_branch_promotion_trust: int = int(TrustTier.USER_AUTHORED)
    min_policy_write_trust: int = int(TrustTier.OPERATOR)
    min_destructive_trust: int = int(TrustTier.USER_AUTHORED)
    consolidator_only_ops: tuple[str, ...] = (
        "run_consolidation_passes",
        "promote_candidate",
        "prune_memory",
        "demote_fidelity",
        "write_inferred_preference",
        "write_policy_variant",
    )
    immutable_rails: tuple[str, ...] = (
        "tenant_isolation_required",
        "retrieved_text_is_data_not_instruction",
        "source_trust_filter_required",
        "branch_promotion_requires_gate",
        "erasure_propagates_to_derived_indexes",
    )

    def authorize_write(
        self,
        operation: str,
        role: WriteRole,
        source_trust_tier: int,
        destructive: bool = False,
        target_sink: str | None = None,
    ) -> CapabilityDecision:
        if operation in self.consolidator_only_ops and role not in {"consolidator", "operator"}:
            return CapabilityDecision(False, "operation requires consolidator write authority", "consolidator", 0, operation)
        if target_sink in {"policy", "system_prompt", "safety_rail"}:
            if role != "operator" or not meets_trust(source_trust_tier, self.min_policy_write_trust):
                return CapabilityDecision(False, "policy and safety rails require operator authority", "operator", self.min_policy_write_trust, operation)
        if target_sink == "preference" and not meets_trust(source_trust_tier, self.min_preference_write_trust):
            return CapabilityDecision(False, "preference writes require user-authored or stronger evidence", "agent", self.min_preference_write_trust, operation)
        if target_sink == "belief" and not meets_trust(source_trust_tier, self.min_belief_write_trust):
            return CapabilityDecision(False, "belief writes require normal-or-stronger source trust", "agent", self.min_belief_write_trust, operation)
        if target_sink == "belief_correction" and not meets_trust(source_trust_tier, self.min_correction_write_trust):
            return CapabilityDecision(False, "belief corrections require user-authored or stronger evidence", "agent", self.min_correction_write_trust, operation)
        if target_sink == "branch" and not meets_trust(source_trust_tier, self.min_branch_write_trust):
            return CapabilityDecision(False, "branch writes require normal-or-stronger source trust", "agent", self.min_branch_write_trust, operation)
        if target_sink == "branch_promotion" and (role not in {"consolidator", "operator"} or not meets_trust(source_trust_tier, self.min_branch_promotion_trust)):
            return CapabilityDecision(False, "branch promotion requires operator/consolidator authority and user-authored trust", "consolidator", self.min_branch_promotion_trust, operation)
        if destructive and (role not in {"consolidator", "operator"} or not meets_trust(source_trust_tier, self.min_destructive_trust)):
            return CapabilityDecision(False, "destructive writes require mediated high-trust authority", "consolidator", self.min_destructive_trust, operation)
        return CapabilityDecision(True, "allowed", role, source_trust_tier, operation)


def sanitize_retrieved_text(text: str, trust_tier: int) -> dict[str, Any]:
    return {
        "kind": "retrieved_memory_data",
        "trust_tier": trust_tier,
        "instruction_authority": "none",
        "content": text,
    }
