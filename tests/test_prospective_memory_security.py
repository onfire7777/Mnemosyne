from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from mnemosyne.security import (
    OidcAuthorizationPolicy,
    PROSPECTIVE_SCHEDULER_CAPABILITY,
    PROSPECTIVE_TENANT_READ_CAPABILITY,
    ProspectiveMemoryAuthorization,
    SecurityPolicy,
    SessionAuthError,
    SessionIdentity,
    SessionTokenVerifier,
    TrustTier,
    issue_session_from_oidc,
)


SESSION_SECRET = "prospective-session-secret"


def _sign_payload(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(
        hmac.new(SESSION_SECRET.encode(), encoded.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return f"{encoded}.{signature}"


def _identity(
    *,
    role: str = "agent",
    capabilities: tuple[str, ...] = (),
) -> SessionIdentity:
    return SessionIdentity(
        tenant_id="tenant-a",
        user_id="user-a",
        role=role,  # type: ignore[arg-type]
        source_trust_tier=int(TrustTier.USER_AUTHORED),
        capabilities=capabilities,
    )


def _assert_denied_unbound(decision: ProspectiveMemoryAuthorization) -> None:
    assert decision.allowed is False
    assert decision.tenant_id is None
    assert decision.actor_id is None
    assert decision.owner_id is None
    assert decision.scope is None


def test_subject_operations_are_allowed_and_bound_to_session_identity() -> None:
    policy = SecurityPolicy()

    for operation in ("schedule", "cancel", "read"):
        decision = policy.authorize_prospective_memory(
            operation,
            _identity(),
            tenant_id="tenant-a",
            actor_id="user-a",
            owner_id="user-a",
        )
        assert decision == ProspectiveMemoryAuthorization(
            allowed=True,
            reason="allowed",
            operation=operation,
            tenant_id="tenant-a",
            actor_id="user-a",
            owner_id="user-a",
            scope="subject",
        )

    reader = policy.authorize_prospective_memory(
        "read",
        _identity(role="reader"),
        tenant_id="tenant-a",
        owner_id="user-a",
    )
    assert reader.allowed is True
    assert reader.actor_id == "user-a"
    assert reader.owner_id == "user-a"
    assert reader.scope == "subject"


def test_reader_mutation_evaluation_and_missing_scheduler_authority_are_denied() -> None:
    policy = SecurityPolicy()

    missing_capability = policy.authorize_prospective_memory(
        "evaluate",
        _identity(role="operator"),
        tenant_id="tenant-a",
        actor_id="user-a",
    )
    _assert_denied_unbound(missing_capability)
    assert "scheduler capability" in missing_capability.reason

    for operation in ("schedule", "cancel"):
        decision = policy.authorize_prospective_memory(
            operation,
            _identity(role="reader"),
            tenant_id="tenant-a",
            owner_id="user-a",
        )
        _assert_denied_unbound(decision)
        assert "reader role cannot mutate" in decision.reason

    reader_evaluation = policy.authorize_prospective_memory(
        "evaluate",
        _identity(role="reader", capabilities=(PROSPECTIVE_SCHEDULER_CAPABILITY,)),
        tenant_id="tenant-a",
    )
    _assert_denied_unbound(reader_evaluation)
    assert "reader role cannot evaluate" in reader_evaluation.reason


def test_prospective_authorization_rejects_spoofed_unknown_and_malformed_context() -> None:
    policy = SecurityPolicy()
    identity = _identity()

    for decision in (
        policy.authorize_prospective_memory(
            "schedule",
            identity,
            tenant_id="tenant-b",
            actor_id="user-a",
            owner_id="user-a",
        ),
        policy.authorize_prospective_memory(
            "schedule",
            identity,
            tenant_id="tenant-a",
            actor_id="attacker",
            owner_id="user-a",
        ),
        policy.authorize_prospective_memory(
            "schedule",
            identity,
            tenant_id="tenant-a",
            actor_id="user-a",
            owner_id="other-user",
        ),
        policy.authorize_prospective_memory(
            "read",
            identity,
            tenant_id="tenant-a",
            actor_id="user-a",
            owner_id="other-user",
        ),
        policy.authorize_prospective_memory(
            "unknown",
            identity,
            tenant_id="tenant-a",
            actor_id="user-a",
            owner_id="user-a",
        ),
        policy.authorize_prospective_memory(
            "read",
            identity,
            tenant_id="tenant-a",
            actor_id="user-a",
        ),
        policy.authorize_prospective_memory(
            "read",
            _identity(capabilities=("prospective:unknown",)),
            tenant_id="tenant-a",
            actor_id="user-a",
            owner_id="user-a",
        ),
    ):
        _assert_denied_unbound(decision)

    for malformed_operation in (None, [], {}):
        _assert_denied_unbound(
            policy.authorize_prospective_memory(  # type: ignore[arg-type]
                malformed_operation,
                identity,
                tenant_id="tenant-a",
                owner_id="user-a",
            )
        )

    malformed_identities = (
        object(),
        _identity(role=[]),  # type: ignore[arg-type]
        _identity(capabilities=[]),  # type: ignore[arg-type]
        _identity(capabilities=(PROSPECTIVE_SCHEDULER_CAPABILITY,) * 2),
        SessionIdentity("tenant-a", "user-a", "agent", "normal"),  # type: ignore[arg-type]
        SessionIdentity("tenant-a", "user-a", "agent", 99),
    )
    for malformed_identity in malformed_identities:
        _assert_denied_unbound(
            policy.authorize_prospective_memory(  # type: ignore[arg-type]
                "read",
                malformed_identity,
                tenant_id="tenant-a",
                owner_id="user-a",
            )
        )

    malformed_requests = (
        {"tenant_id": "", "owner_id": "user-a"},
        {"tenant_id": "tenant-a", "owner_id": ""},
        {"tenant_id": "tenant-a", "owner_id": "user-a", "tenant_wide": 1},
    )
    for request in malformed_requests:
        _assert_denied_unbound(
            policy.authorize_prospective_memory(  # type: ignore[arg-type]
                "read",
                identity,
                **request,
            )
        )


def test_authorized_scheduler_evaluation_and_tenant_wide_read_are_explicit() -> None:
    policy = SecurityPolicy()

    scheduler = policy.authorize_prospective_memory(
        "evaluate",
        _identity(role="operator", capabilities=(PROSPECTIVE_SCHEDULER_CAPABILITY,)),
        tenant_id="tenant-a",
        actor_id="user-a",
    )
    assert scheduler == ProspectiveMemoryAuthorization(
        allowed=True,
        reason="allowed",
        operation="evaluate",
        tenant_id="tenant-a",
        actor_id="user-a",
        scope="tenant",
    )

    tenant_read = policy.authorize_prospective_memory(
        "read",
        _identity(role="reader", capabilities=(PROSPECTIVE_TENANT_READ_CAPABILITY,)),
        tenant_id="tenant-a",
        actor_id="user-a",
        tenant_wide=True,
    )
    assert tenant_read == ProspectiveMemoryAuthorization(
        allowed=True,
        reason="allowed",
        operation="read",
        tenant_id="tenant-a",
        actor_id="user-a",
        scope="tenant",
    )

    missing_read_capability = policy.authorize_prospective_memory(
        "read",
        _identity(role="reader"),
        tenant_id="tenant-a",
        tenant_wide=True,
    )
    _assert_denied_unbound(missing_read_capability)
    assert "explicit capability" in missing_read_capability.reason

    conflicting_scopes = (
        policy.authorize_prospective_memory(
            "evaluate",
            _identity(role="operator", capabilities=(PROSPECTIVE_SCHEDULER_CAPABILITY,)),
            tenant_id="tenant-a",
            owner_id="user-a",
        ),
        policy.authorize_prospective_memory(
            "evaluate",
            _identity(role="operator", capabilities=(PROSPECTIVE_SCHEDULER_CAPABILITY,)),
            tenant_id="tenant-a",
            tenant_wide=True,
        ),
        policy.authorize_prospective_memory(
            "read",
            _identity(capabilities=(PROSPECTIVE_TENANT_READ_CAPABILITY,)),
            tenant_id="tenant-a",
            owner_id="user-a",
            tenant_wide=True,
        ),
        policy.authorize_prospective_memory(
            "schedule",
            _identity(),
            tenant_id="tenant-a",
            owner_id="user-a",
            tenant_wide=True,
        ),
        policy.authorize_prospective_memory(
            "cancel",
            _identity(),
            tenant_id="tenant-a",
            owner_id="user-a",
            tenant_wide=True,
        ),
    )
    for decision in conflicting_scopes:
        _assert_denied_unbound(decision)


def test_prospective_writes_require_normal_or_stronger_source_trust() -> None:
    policy = SecurityPolicy()

    for operation, capabilities in (
        ("schedule", ()),
        ("cancel", ()),
        ("evaluate", (PROSPECTIVE_SCHEDULER_CAPABILITY,)),
    ):
        denied = policy.authorize_prospective_memory(
            operation,
            SessionIdentity(
                tenant_id="tenant-a",
                user_id="user-a",
                role="operator",
                source_trust_tier=int(TrustTier.UNTRUSTED_EXTERNAL),
                capabilities=capabilities,
            ),
            tenant_id="tenant-a",
            owner_id="user-a" if operation != "evaluate" else None,
        )
        _assert_denied_unbound(denied)
        assert "source trust" in denied.reason

        allowed = policy.authorize_prospective_memory(
            operation,
            SessionIdentity(
                tenant_id="tenant-a",
                user_id="user-a",
                role="operator",
                source_trust_tier=int(TrustTier.NORMAL),
                capabilities=capabilities,
            ),
            tenant_id="tenant-a",
            owner_id="user-a" if operation != "evaluate" else None,
        )
        assert allowed.allowed is True


def test_policy_controlled_capabilities_survive_oidc_session_issuance() -> None:
    policy = OidcAuthorizationPolicy.from_mapping(
        {
            "allowed_client_ids": ["scheduler-client"],
            "rules": [
                {
                    "claim_contains": {"groups": "mnemosyne-schedulers"},
                    "required_acr": "urn:mnemosyne:mfa",
                    "required_amr": "mfa",
                    "max_auth_age_seconds": 300,
                    "role": "operator",
                    "source_trust_tier": int(TrustTier.USER_AUTHORED),
                    "capabilities": [PROSPECTIVE_SCHEDULER_CAPABILITY],
                }
            ],
        }
    )
    identity = policy.authorize(
        {
            "azp": "scheduler-client",
            "groups": ["mnemosyne-schedulers"],
            "acr": "urn:mnemosyne:mfa",
            "amr": ["pwd", "mfa"],
            "auth_time": 1_900_000_000,
        },
        tenant_id="tenant-a",
        user_id="scheduler-a",
        expires_at=2_000_000_000,
        session_id="idp-session-a",
        now=1_900_000_100,
    )

    class VerifierStub:
        def verify(self, token: str, *, now: int | None = None) -> SessionIdentity:
            assert token == "idp-token"
            assert now == 1_900_000_100
            return identity

    signer = SessionTokenVerifier(SESSION_SECRET)
    token, issued = issue_session_from_oidc(
        verifier=VerifierStub(),  # type: ignore[arg-type]
        idp_token="idp-token",
        signer=signer,
        now=1_900_000_100,
    )

    assert policy.audit_summary()["rules"][0]["capabilities"] == [
        PROSPECTIVE_SCHEDULER_CAPABILITY
    ]
    assert policy.canonical_mapping()["rules"][0]["capabilities"] == [
        PROSPECTIVE_SCHEDULER_CAPABILITY
    ]
    assert issued.capabilities == (PROSPECTIVE_SCHEDULER_CAPABILITY,)
    assert signer.verify(token, now=1_900_000_100) == issued


def test_raw_oidc_capability_claims_cannot_mint_prospective_authority() -> None:
    policy = OidcAuthorizationPolicy.from_mapping(
        {
            "allowed_client_ids": ["scheduler-client"],
            "rules": [
                {
                    "tenant_ids": ["tenant-a"],
                    "role": "agent",
                    "source_trust_tier": int(TrustTier.NORMAL),
                }
            ],
        }
    )

    identity = policy.authorize(
        {
            "azp": "scheduler-client",
            "capabilities": [
                PROSPECTIVE_SCHEDULER_CAPABILITY,
                PROSPECTIVE_TENANT_READ_CAPABILITY,
            ],
        },
        tenant_id="tenant-a",
        user_id="agent-a",
        expires_at=2_000_000_000,
        session_id="idp-session-a",
    )

    assert identity.capabilities == ()
    decision = SecurityPolicy().authorize_prospective_memory(
        "evaluate",
        identity,
        tenant_id="tenant-a",
    )
    _assert_denied_unbound(decision)
    assert "scheduler capability" in decision.reason


def test_capability_free_oidc_policy_preserves_schema_v1_outputs() -> None:
    policy = OidcAuthorizationPolicy.from_mapping(
        {
            "version": 1,
            "allowed_client_ids": ["legacy-client"],
            "rules": [
                {
                    "name": "legacy-reader",
                    "tenant_ids": ["tenant-a"],
                    "role": "reader",
                    "source_trust_tier": int(TrustTier.NORMAL),
                }
            ],
        }
    )
    fingerprint = "cd9f986fc23a111d9ddd1425493a9dc1147ae7ef309047e1590ff12604327339"

    assert policy.canonical_mapping() == {
        "version": 1,
        "allowed_client_ids": ["legacy-client"],
        "client_id_claims": ["azp", "client_id"],
        "rules": [
            {
                "name": "legacy-reader",
                "tenant_ids": ["tenant-a"],
                "claim_equals": {},
                "claim_contains": {},
                "required_acr": [],
                "required_amr": [],
                "max_auth_age_seconds": None,
                "role": "reader",
                "source_trust_tier": int(TrustTier.NORMAL),
            }
        ],
    }
    assert policy.fingerprint() == fingerprint
    assert policy.audit_summary() == {
        "version": 1,
        "fingerprint": fingerprint,
        "allowed_client_ids_count": 1,
        "client_id_claims": ["azp", "client_id"],
        "rule_count": 1,
        "roles": ["reader"],
        "source_trust_tiers": [int(TrustTier.NORMAL)],
        "rules": [
            {
                "index": 0,
                "name": "legacy-reader",
                "role": "reader",
                "source_trust_tier": int(TrustTier.NORMAL),
                "tenant_matcher_count": 1,
                "claim_equals_fields": [],
                "claim_contains_fields": [],
                "elevated": False,
                "required_acr_configured": False,
                "required_amr_configured": False,
                "auth_time_required": False,
            }
        ],
    }


def test_session_verification_rejects_malformed_capability_claims() -> None:
    base_payload: dict[str, object] = {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "role": "operator",
        "source_trust_tier": int(TrustTier.USER_AUTHORED),
        "exp": 2_000_000_000,
    }
    malformed_capabilities = (
        PROSPECTIVE_SCHEDULER_CAPABILITY,
        [""],
        [PROSPECTIVE_SCHEDULER_CAPABILITY, PROSPECTIVE_SCHEDULER_CAPABILITY],
        ["prospective:unknown"],
    )

    for capabilities in malformed_capabilities:
        with pytest.raises(SessionAuthError, match="capabilit"):
            SessionTokenVerifier(SESSION_SECRET).verify(
                _sign_payload({**base_payload, "capabilities": capabilities}),
                now=1_900_000_000,
            )


@pytest.mark.parametrize("source_trust_tier", [True, False, 1.5, "1"])
def test_session_verification_rejects_non_integral_source_trust_tiers(
    source_trust_tier: object,
) -> None:
    with pytest.raises(SessionAuthError, match="source_trust_tier is invalid"):
        SessionTokenVerifier(SESSION_SECRET).verify(
            _sign_payload(
                {
                    "tenant_id": "tenant-a",
                    "user_id": "user-a",
                    "role": "agent",
                    "source_trust_tier": source_trust_tier,
                    "exp": 2_000_000_000,
                }
            ),
            now=1_900_000_000,
        )


@pytest.mark.parametrize("source_trust_tier", [True, False, 1.5, "1"])
def test_oidc_policy_rejects_non_integral_source_trust_tiers(
    source_trust_tier: object,
) -> None:
    with pytest.raises(SessionAuthError, match="source_trust_tier is invalid"):
        OidcAuthorizationPolicy.from_mapping(
            {
                "allowed_client_ids": ["scheduler-client"],
                "rules": [
                    {
                        "tenant_ids": ["tenant-a"],
                        "role": "agent",
                        "source_trust_tier": source_trust_tier,
                    }
                ],
            }
        )


def test_oidc_policy_rejects_untrusted_or_ambiguous_capability_rules() -> None:
    base_rule = {
        "claim_contains": {"groups": "mnemosyne-schedulers"},
        "required_acr": "urn:mnemosyne:mfa",
        "required_amr": "mfa",
        "max_auth_age_seconds": 300,
        "role": "agent",
        "source_trust_tier": int(TrustTier.NORMAL),
    }
    for capabilities in (
        ["prospective:unknown"],
        [PROSPECTIVE_SCHEDULER_CAPABILITY, PROSPECTIVE_SCHEDULER_CAPABILITY],
    ):
        with pytest.raises(SessionAuthError, match="capabilit"):
            OidcAuthorizationPolicy.from_mapping(
                {
                    "allowed_client_ids": ["scheduler-client"],
                    "rules": [{**base_rule, "capabilities": capabilities}],
                }
            )


@pytest.mark.parametrize(
    ("missing_field", "error"),
    [
        ("required_acr", "requires required_acr"),
        ("required_amr", "requires required_amr"),
        ("claim_contains", "requires a non-tenant claim matcher"),
        ("max_auth_age_seconds", "requires max_auth_age_seconds"),
    ],
)
def test_capability_bearing_agent_rules_require_elevated_controls(
    missing_field: str,
    error: str,
) -> None:
    rule = {
        "tenant_ids": ["tenant-a"],
        "claim_contains": {"groups": "mnemosyne-schedulers"},
        "required_acr": "urn:mnemosyne:mfa",
        "required_amr": "mfa",
        "max_auth_age_seconds": 300,
        "role": "agent",
        "source_trust_tier": int(TrustTier.NORMAL),
        "capabilities": [PROSPECTIVE_SCHEDULER_CAPABILITY],
    }
    del rule[missing_field]

    with pytest.raises(SessionAuthError, match=error):
        OidcAuthorizationPolicy.from_mapping(
            {
                "allowed_client_ids": ["scheduler-client"],
                "rules": [rule],
            }
        )


def test_existing_memory_plane_authorization_behavior_is_unchanged() -> None:
    policy = SecurityPolicy()

    allowed = policy.authorize_write(
        "remember",
        "agent",
        int(TrustTier.USER_AUTHORED),
        target_sink="memory",
    )
    assert allowed.allowed is True
    assert allowed.reason == "allowed"
    assert allowed.required_role == "agent"
    assert allowed.required_trust == int(TrustTier.USER_AUTHORED)

    tainted = policy.authorize_write(
        "remember",
        "operator",
        int(TrustTier.USER_AUTHORED),
        source_capability_tags=("quarantined",),
    )
    assert tainted.allowed is False
    assert "tainted data carries no write authority" in tainted.reason

    destructive = policy.authorize_write(
        "forget",
        "agent",
        int(TrustTier.USER_AUTHORED),
        destructive=True,
    )
    assert destructive.allowed is False
    assert destructive.required_role == "consolidator"
    assert "destructive writes require mediated high-trust authority" in destructive.reason
