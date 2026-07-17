from __future__ import annotations

from mnemosyne.security import (
    PROSPECTIVE_SCHEDULER_CAPABILITY,
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


def test_prospective_authorization_binds_session_identity_and_scheduler_capability() -> None:
    policy = SecurityPolicy()

    scheduled = policy.authorize_prospective_memory(
        "schedule",
        _identity(),
        tenant_id="tenant-a",
        actor_id="user-a",
        owner_id="user-a",
    )
    assert scheduled == ProspectiveMemoryAuthorization(
        allowed=True,
        reason="allowed",
        operation="schedule",
        tenant_id="tenant-a",
        actor_id="user-a",
        owner_id="user-a",
        scope="subject",
    )

    missing_capability = policy.authorize_prospective_memory(
        "evaluate",
        _identity(role="operator"),
        tenant_id="tenant-a",
        actor_id="user-a",
    )
    assert missing_capability.allowed is False
    assert "scheduler capability" in missing_capability.reason

    scheduler = policy.authorize_prospective_memory(
        "evaluate",
        _identity(role="operator", capabilities=(PROSPECTIVE_SCHEDULER_CAPABILITY,)),
        tenant_id="tenant-a",
        actor_id="user-a",
    )
    assert scheduler.allowed is True
    assert scheduler.scope == "tenant"
    assert scheduler.actor_id == "user-a"


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
        assert decision.allowed is False
        assert decision.tenant_id is None
        assert decision.actor_id is None
        assert decision.owner_id is None
        assert decision.scope is None
