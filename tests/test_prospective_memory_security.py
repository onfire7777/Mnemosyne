from __future__ import annotations

from mnemosyne.security import (
    PROSPECTIVE_SCHEDULER_CAPABILITY,
    PROSPECTIVE_TENANT_READ_CAPABILITY,
    ProspectiveMemoryAuthorization,
    SecurityPolicy,
    SessionIdentity,
    TrustTier,
)


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
