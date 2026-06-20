"""Capability mediation and trust-boundary enforcement."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import shlex
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from enum import IntEnum
from collections.abc import Mapping, Sequence
from typing import Any, Callable, Literal

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


def load_session_secret_command(
    command: str | Sequence[str],
    *,
    timeout_seconds: float = 10.0,
) -> tuple[str | dict[str, str], str | None]:
    """Load session signing material from a shell-free command provider."""

    argv = shlex.split(command) if isinstance(command, str) else [str(item) for item in command]
    if not argv:
        raise SessionAuthError("session secret command must not be empty")
    if timeout_seconds <= 0:
        raise SessionAuthError("session secret command timeout must be positive")
    try:
        result = subprocess.run(
            [*argv, "get_session_secret"],
            input=json.dumps({"action": "get_session_secret"}),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SessionAuthError("session secret command timed out") from exc
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail[:200]}" if detail else ""
        raise SessionAuthError(f"session secret command failed{suffix}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SessionAuthError("session secret command response must be valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise SessionAuthError("session secret command response must be a JSON object")
    unknown_fields = set(payload).difference({"secret", "keyring", "active_key_id"})
    if unknown_fields:
        raise SessionAuthError("session secret command response contains unknown fields")
    has_secret = payload.get("secret") is not None
    has_keyring = payload.get("keyring") is not None
    if has_secret == has_keyring:
        raise SessionAuthError("session secret command response requires exactly one secret source")
    active_key_id = str(payload["active_key_id"]) if payload.get("active_key_id") is not None else None
    if has_secret:
        if active_key_id:
            raise SessionAuthError("session secret command active_key_id requires keyring")
        secret = str(payload["secret"])
        if not secret:
            raise SessionAuthError("session secret command secret is required")
        return secret, None
    keyring_payload = payload["keyring"]
    if not isinstance(keyring_payload, Mapping):
        raise SessionAuthError("session secret command keyring must be a JSON object")
    keyring = {str(key).strip(): str(value) for key, value in keyring_payload.items() if str(key).strip()}
    SessionTokenVerifier(keyring, active_key_id=active_key_id)
    return keyring, active_key_id


def parse_session_revoke_list(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _value_tuple(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if item is not None and item != "")
    return (str(value),)


def _nonempty_tuple(value: tuple[str, ...], *, field: str, allow_empty: bool) -> tuple[str, ...]:
    normalized = tuple(item.strip() for item in value if item and item.strip())
    if not allow_empty and not normalized:
        raise SessionAuthError(f"OIDC authz policy {field} is required")
    return normalized


def _normalize_matchers(value: Any, *, field: str) -> dict[str, tuple[str, ...]]:
    if value in (None, ""):
        return {}
    if not isinstance(value, Mapping):
        raise SessionAuthError(f"OIDC authz policy {field} must be an object")
    normalized: dict[str, tuple[str, ...]] = {}
    for claim, expected in value.items():
        claim_name = str(claim).strip()
        expected_values = _nonempty_tuple(_value_tuple(expected), field=f"{field}.{claim_name}", allow_empty=False)
        if not claim_name:
            raise SessionAuthError(f"OIDC authz policy {field} claim name is required")
        normalized[claim_name] = expected_values
    return normalized


def _claim_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value, *value.split()}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value if item is not None and item != ""}
    return {str(value)}


def _claim_equals(value: Any, expected: tuple[str, ...]) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set)):
        values = {str(item) for item in value if item is not None and item != ""}
        return values == set(expected)
    else:
        return str(value) in expected


def _claim_contains(value: Any, expected: tuple[str, ...]) -> bool:
    return bool(_claim_values(value).intersection(expected))


class OidcAuthorizationPolicy:
    """Map verified IdP claims to Mnemosyne authorization claims."""

    def __init__(
        self,
        *,
        rules: list[Mapping[str, Any]],
        allowed_client_ids: tuple[str, ...] = (),
        client_id_claims: tuple[str, ...] = ("azp", "client_id"),
    ):
        self.allowed_client_ids = _nonempty_tuple(allowed_client_ids, field="allowed_client_ids", allow_empty=False)
        self.client_id_claims = _nonempty_tuple(client_id_claims, field="client_id_claims", allow_empty=False)
        if not isinstance(rules, list) or not rules:
            raise SessionAuthError("OIDC authz policy requires rules")
        self.rules = [self._normalize_rule(rule) for rule in rules]

    @classmethod
    def from_mapping(cls, policy: Mapping[str, Any]) -> "OidcAuthorizationPolicy":
        allowed_fields = {"version", "allowed_client_ids", "client_ids", "client_id_claims", "rules"}
        unknown_fields = set(policy).difference(allowed_fields)
        if unknown_fields:
            raise SessionAuthError("OIDC authz policy contains unknown fields")
        try:
            version = int(policy.get("version", 1))
        except (TypeError, ValueError) as exc:
            raise SessionAuthError("OIDC authz policy version is invalid") from exc
        if version != 1:
            raise SessionAuthError("OIDC authz policy version is not supported")
        allowed = policy.get("allowed_client_ids", policy.get("client_ids", ()))
        client_claims = policy.get("client_id_claims", ("azp", "client_id"))
        rules = policy.get("rules")
        return cls(
            rules=rules if isinstance(rules, list) else [],
            allowed_client_ids=_value_tuple(allowed),
            client_id_claims=_value_tuple(client_claims) or ("azp", "client_id"),
        )

    def authorize(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        user_id: str,
        expires_at: int | None,
        session_id: str | None,
    ) -> SessionIdentity:
        self._verify_client(payload)
        matches = [rule for rule in self.rules if self._rule_matches(rule, payload, tenant_id=tenant_id)]
        if not matches:
            raise SessionAuthError("OIDC token is not authorized")
        if len(matches) > 1:
            raise SessionAuthError("OIDC token matches multiple authorization rules")
        rule = matches[0]
        identity_payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": rule["role"],
            "source_trust_tier": rule["source_trust_tier"],
            "exp": expires_at,
        }
        if session_id:
            identity_payload["session_id"] = session_id
        return SessionIdentity.from_payload(identity_payload)

    def audit_summary(self) -> dict[str, Any]:
        """Return a bounded, secret-free policy summary for deployment checks."""

        return {
            "version": 1,
            "fingerprint": self.fingerprint(),
            "allowed_client_ids_count": len(self.allowed_client_ids),
            "client_id_claims": list(self.client_id_claims),
            "rule_count": len(self.rules),
            "roles": sorted({str(rule["role"]) for rule in self.rules}),
            "source_trust_tiers": sorted({int(rule["source_trust_tier"]) for rule in self.rules}),
            "rules": [
                {
                    "index": index,
                    **({"name": rule["name"]} if rule["name"] else {}),
                    "role": str(rule["role"]),
                    "source_trust_tier": int(rule["source_trust_tier"]),
                    "tenant_matcher_count": len(rule["tenant_ids"]),
                    "claim_equals_fields": sorted(rule["claim_equals"]),
                    "claim_contains_fields": sorted(rule["claim_contains"]),
                }
                for index, rule in enumerate(self.rules)
            ],
        }

    def canonical_mapping(self) -> dict[str, Any]:
        """Return the deterministic full policy mapping used for fingerprinting."""

        return {
            "version": 1,
            "allowed_client_ids": sorted(self.allowed_client_ids),
            "client_id_claims": list(self.client_id_claims),
            "rules": [
                {
                    "name": rule["name"],
                    "tenant_ids": list(rule["tenant_ids"]),
                    "claim_equals": {
                        claim: list(expected)
                        for claim, expected in sorted(rule["claim_equals"].items())
                    },
                    "claim_contains": {
                        claim: list(expected)
                        for claim, expected in sorted(rule["claim_contains"].items())
                    },
                    "role": str(rule["role"]),
                    "source_trust_tier": int(rule["source_trust_tier"]),
                }
                for rule in self.rules
            ],
        }

    def fingerprint(self) -> str:
        """Return a stable SHA-256 fingerprint for rollout/change control."""

        payload = json.dumps(self.canonical_mapping(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _verify_client(self, payload: Mapping[str, Any]) -> None:
        if not self.allowed_client_ids:
            return
        token_client_ids = {
            str(payload[claim])
            for claim in self.client_id_claims
            if payload.get(claim) is not None and payload.get(claim) != ""
        }
        if not token_client_ids.intersection(self.allowed_client_ids):
            raise SessionAuthError("OIDC token client is not authorized")

    @staticmethod
    def _normalize_rule(rule: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(rule, Mapping):
            raise SessionAuthError("OIDC authz rule must be an object")
        allowed_fields = {"name", "tenant_ids", "tenants", "claim_equals", "claim_contains", "role", "source_trust_tier"}
        if set(rule).difference(allowed_fields):
            raise SessionAuthError("OIDC authz rule contains unknown fields")
        role = rule.get("role")
        if role not in _WRITE_ROLES:
            raise SessionAuthError("OIDC authz rule role is not allowed")
        try:
            source_trust_tier = int(rule.get("source_trust_tier"))
        except (TypeError, ValueError) as exc:
            raise SessionAuthError("OIDC authz rule source_trust_tier is invalid") from exc
        if source_trust_tier not in {int(item) for item in TrustTier}:
            raise SessionAuthError("OIDC authz rule source_trust_tier is out of range")
        tenant_ids = _nonempty_tuple(_value_tuple(rule.get("tenant_ids", rule.get("tenants", ()))), field="tenant_ids", allow_empty=True)
        claim_equals = _normalize_matchers(rule.get("claim_equals", {}), field="claim_equals")
        claim_contains = _normalize_matchers(rule.get("claim_contains", {}), field="claim_contains")
        if not tenant_ids and not claim_equals and not claim_contains:
            raise SessionAuthError("OIDC authz rule requires at least one matcher")
        return {
            "name": str(rule.get("name", "")).strip() or None,
            "role": str(role),
            "source_trust_tier": source_trust_tier,
            "tenant_ids": tenant_ids,
            "claim_equals": claim_equals,
            "claim_contains": claim_contains,
        }

    @staticmethod
    def _rule_matches(rule: Mapping[str, Any], payload: Mapping[str, Any], *, tenant_id: str) -> bool:
        tenant_ids = rule["tenant_ids"]
        if tenant_ids and tenant_id not in tenant_ids:
            return False
        for claim, expected in rule["claim_equals"].items():
            if not _claim_equals(payload.get(claim), expected):
                return False
        for claim, expected in rule["claim_contains"].items():
            if not _claim_contains(payload.get(claim), expected):
                return False
        return True


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
        jwks_loader: Callable[[], Mapping[str, Any]] | None = None,
        jwks_cache_ttl_seconds: int | None = None,
        refresh_on_unknown_kid: bool = True,
        authorization_policy: OidcAuthorizationPolicy | None = None,
    ):
        if not issuer:
            raise SessionAuthError("OIDC issuer is required")
        if not audience:
            raise SessionAuthError("OIDC audience is required")
        self._jwks_lock = threading.RLock()
        self._jwks_loader = jwks_loader
        self._jwks_loaded_at = int(time.time())
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
        self.jwks_cache_ttl_seconds = None if jwks_cache_ttl_seconds is None else int(jwks_cache_ttl_seconds)
        if self.jwks_cache_ttl_seconds is not None and self.jwks_cache_ttl_seconds < 0:
            raise SessionAuthError("OIDC JWKS cache TTL must be non-negative")
        self.refresh_on_unknown_kid = bool(refresh_on_unknown_kid)
        self.authorization_policy = authorization_policy
        self._install_jwks(jwks, loaded_at=self._jwks_loaded_at)

    def _install_jwks(self, jwks: Mapping[str, Any], *, loaded_at: int) -> None:
        keys = jwks.get("keys")
        if not isinstance(keys, list) or not keys:
            raise SessionAuthError("OIDC JWKS must contain keys")
        keys_by_id: dict[str, Mapping[str, Any]] = {}
        for key in keys:
            if not isinstance(key, Mapping):
                continue
            key_id = str(key.get("kid") or "")
            if key_id:
                if key_id in keys_by_id:
                    raise SessionAuthError("OIDC JWKS contains duplicate kid")
                if key.get("use") not in (None, "sig"):
                    raise SessionAuthError("OIDC JWKS key use is not allowed")
                key_ops = key.get("key_ops")
                if key_ops is not None and (not isinstance(key_ops, list) or "verify" not in key_ops):
                    raise SessionAuthError("OIDC JWKS key_ops must allow verify")
                keys_by_id[key_id] = key
        if not keys_by_id:
            raise SessionAuthError("OIDC JWKS keys must include kid")
        with self._jwks_lock:
            self.keys_by_id = keys_by_id
            self._jwks_loaded_at = loaded_at

    def refresh_jwks(self, *, now: int | None = None, force: bool = False) -> bool:
        if self._jwks_loader is None:
            return False
        now_ts = int(time.time()) if now is None else int(now)
        with self._jwks_lock:
            if not force and self.jwks_cache_ttl_seconds is None:
                return False
            if not force and self.jwks_cache_ttl_seconds is not None:
                if now_ts - self._jwks_loaded_at < self.jwks_cache_ttl_seconds:
                    return False
            try:
                jwks = self._jwks_loader()
            except SessionAuthError:
                raise
            except Exception as exc:  # noqa: BLE001 - exchange must fail closed on loader failures.
                raise SessionAuthError("OIDC JWKS refresh failed") from exc
            self._install_jwks(jwks, loaded_at=now_ts)
            return True

    def verify(self, token: str, *, now: int | None = None) -> SessionIdentity:
        now_ts = int(time.time()) if now is None else int(now)
        header, payload, signing_input, signature = self._decode_compact_jwt(token)
        self.refresh_jwks(now=now_ts)
        algorithm = str(header.get("alg") or "")
        if algorithm not in self.allowed_algorithms:
            raise SessionAuthError("OIDC token alg is not allowed")
        key_id = str(header.get("kid") or "")
        if not key_id:
            raise SessionAuthError("OIDC token kid is required")
        with self._jwks_lock:
            key = self.keys_by_id.get(key_id)
        if key is None and self.refresh_on_unknown_kid:
            self.refresh_jwks(now=now_ts, force=True)
            with self._jwks_lock:
                key = self.keys_by_id.get(key_id)
        if key is None:
            raise SessionAuthError("OIDC token kid is unknown")
        if str(key.get("alg") or algorithm) != algorithm:
            raise SessionAuthError("OIDC JWKS key alg does not match token alg")
        self._verify_signature(algorithm, key, signing_input, signature)
        self._verify_registered_claims(payload, now=now_ts)
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
        tenant_id = str(self._required_claim(payload, self.tenant_claim))
        user_id = str(self._required_claim(payload, self.user_claim))
        session_id = payload.get(self.session_id_claim)
        normalized_session_id = str(session_id) if session_id else None
        if self.authorization_policy is not None:
            return self.authorization_policy.authorize(
                payload,
                tenant_id=tenant_id,
                user_id=user_id,
                expires_at=int(payload["exp"]),
                session_id=normalized_session_id,
            )
        identity_payload = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": self._required_claim(payload, self.role_claim),
            "source_trust_tier": self._required_claim(payload, self.trust_claim),
            "exp": payload["exp"],
        }
        if normalized_session_id:
            identity_payload["session_id"] = normalized_session_id
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
