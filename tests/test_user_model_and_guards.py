from __future__ import annotations

from datetime import UTC, datetime

from mnemosyne.guard import no_degradation_guard
from mnemosyne.lifecycle import FidelityTier, LifecycleState, apply_rehearsal_schedule, next_rehearsal_days
from mnemosyne.user_model import LatentUserProfile, UserMemoryKind, UserModel, UserModelEntry


TENANT = "tenant-d"
USER = "user-d"


def test_six_category_user_model_scope_and_authority_order() -> None:
    model = UserModel()
    inferred = UserModelEntry(
        tenant_id=TENANT,
        user_id=USER,
        kind=UserMemoryKind.INFERRED_PREFERENCE,
        statement="Prefers long narrative updates.",
        scope={"repo": "mnemosyne"},
        confidence=0.6,
    )
    hard = UserModelEntry(
        tenant_id=TENANT,
        user_id=USER,
        kind=UserMemoryKind.HARD_INSTRUCTION,
        statement="Use concise operational updates.",
        scope={"repo": "mnemosyne"},
        confidence=1.0,
    )
    identity = UserModelEntry(
        tenant_id=TENANT,
        user_id=USER,
        kind=UserMemoryKind.IDENTITY,
        statement="User owns the Mnemosyne build.",
        scope={"repo": "mnemosyne"},
        confidence=0.95,
    )
    explicit = UserModelEntry(
        tenant_id=TENANT,
        user_id=USER,
        kind=UserMemoryKind.EXPLICIT_PREFERENCE,
        statement="Prefers verified implementation notes.",
        scope={"repo": "mnemosyne"},
        confidence=0.9,
    )
    situational = UserModelEntry(
        tenant_id=TENANT,
        user_id=USER,
        kind=UserMemoryKind.SITUATIONAL_PREFERENCE,
        statement="For this phase, prioritize parity evidence.",
        scope={"repo": "mnemosyne", "phase": "3"},
        confidence=0.85,
    )
    temporary = UserModelEntry(
        tenant_id=TENANT,
        user_id=USER,
        kind=UserMemoryKind.TEMPORARY_STATE,
        statement="Currently focused on Phase 3.",
        scope={"repo": "mnemosyne", "phase": "3"},
        confidence=0.8,
    )

    model.add_entry(inferred)
    model.add_entry(hard)
    model.add_entry(identity)
    model.add_entry(explicit)
    model.add_entry(situational)
    model.add_entry(temporary)
    packet = model.context_packet(TENANT, USER, {"repo": "mnemosyne", "phase": "3"})

    authoritative = packet["authoritative"]
    assert [item["kind"] for item in authoritative] == [
        "hard_instruction",
        "identity",
        "explicit_preference",
        "situational_preference",
        "temporary_state",
    ]
    assert model.entries[inferred.id].status == "superseded"
    assert packet["inferred"] == []
    assert packet["rules"]["hard_instruction_outranks_inference"] is True


def test_user_model_scope_exceptions_and_latent_profile_is_advisory() -> None:
    model = UserModel()
    model.add_entry(
        UserModelEntry(
            tenant_id=TENANT,
            user_id=USER,
            kind=UserMemoryKind.EXPLICIT_PREFERENCE,
            statement="Prefer tables for comparisons.",
            scope={"task": "review"},
            exceptions={"medium": "voice"},
            confidence=0.9,
        )
    )
    model.set_latent_profile(
        LatentUserProfile(
            tenant_id=TENANT,
            user_id=USER,
            embedding=[0.1, 0.2, 0.3],
            summary="Advisory latent profile only.",
        )
    )

    included = model.context_packet(TENANT, USER, {"task": "review", "medium": "text"})
    excepted = model.context_packet(TENANT, USER, {"task": "review", "medium": "voice"})

    assert len(included["authoritative"]) == 1
    assert len(excepted["authoritative"]) == 0
    assert included["latent_advisory"]["summary"] == "Advisory latent profile only."
    assert included["rules"]["latent_never_overrides_explicit"] is True


def test_rehearsal_schedule_expands_monotonically() -> None:
    intervals = [next_rehearsal_days(i) for i in range(8)]

    assert intervals == sorted(intervals)
    assert intervals[0] == 1
    assert intervals[-1] == 240


def test_rehearsal_scheduler_boosts_due_must_keep_memory() -> None:
    now = datetime(2026, 6, 21, tzinfo=UTC)
    state = LifecycleState(
        item_id="memory-1",
        tier=FidelityTier.VERBATIM,
        salience=0.1,
        importance=0.5,
        access_count=2,
        last_accessed=datetime(2026, 6, 1, tzinfo=UTC),
        must_keep=True,
        successful_rehearsals=1,
        next_rehearsal_at=datetime(2026, 6, 20, tzinfo=UTC),
    )

    updated, rehearsed = apply_rehearsal_schedule(state, now)

    assert rehearsed is True
    assert updated.successful_rehearsals == 2
    assert updated.access_count == 3
    assert updated.last_rehearsed_at == now
    assert updated.next_rehearsal_at == datetime(2026, 6, 28, tzinfo=UTC)
    assert updated.salience > state.salience


def test_no_degradation_guard_blocks_memory_below_baseline() -> None:
    passing = no_degradation_guard(memory_score=0.82, no_memory_baseline=0.8, minimum_margin=0.01)
    failing = no_degradation_guard(memory_score=0.75, no_memory_baseline=0.8, minimum_margin=0.0)

    assert passing.passed is True
    assert failing.passed is False
    assert "degraded" in failing.reason


def test_user_model_entry_serialization_round_trips() -> None:
    # Durable runtime-state parity (local <-> Postgres) depends on lossless
    # to_dict()/from_dict() for every populated field, including valid_to=None.
    entry = UserModelEntry(
        tenant_id=TENANT,
        user_id=USER,
        kind=UserMemoryKind.EXPLICIT_PREFERENCE,
        statement="Prefer concise summaries.",
        scope={"repo": "mnemosyne"},
        confidence=0.88,
        exceptions={"medium": "voice"},
        source_evidence_cids=["cid-1", "cid-2"],
    )

    serialized = entry.to_dict()
    restored = UserModelEntry.from_dict(serialized)

    assert restored.to_dict() == serialized
    assert serialized["kind"] == "explicit_preference"
    assert serialized["valid_to"] is None
    assert restored.id == entry.id
    assert restored.exceptions == {"medium": "voice"}
    assert restored.source_evidence_cids == ["cid-1", "cid-2"]


def test_latent_user_profile_serialization_round_trips() -> None:
    profile = LatentUserProfile(
        tenant_id=TENANT,
        user_id=USER,
        embedding=[0.1, 0.2, 0.3],
        summary="Advisory latent profile only.",
    )

    restored = LatentUserProfile.from_dict(profile.to_dict())

    assert restored.to_dict() == profile.to_dict()
    assert restored.embedding == [0.1, 0.2, 0.3]
    assert restored.summary == "Advisory latent profile only."


def test_lower_authority_entry_never_supersedes_higher_and_stays_inferred() -> None:
    # Inverse of the supersession test: a later, lower-authority inferred
    # preference must NOT displace an active hard instruction it conflicts with,
    # and it surfaces only in the advisory "inferred" bucket.
    model = UserModel()
    hard = UserModelEntry(
        tenant_id=TENANT,
        user_id=USER,
        kind=UserMemoryKind.HARD_INSTRUCTION,
        statement="Use concise operational updates.",
        scope={"repo": "mnemosyne"},
        confidence=1.0,
    )
    inferred = UserModelEntry(
        tenant_id=TENANT,
        user_id=USER,
        kind=UserMemoryKind.INFERRED_PREFERENCE,
        statement="Prefers long narrative updates.",
        scope={"repo": "mnemosyne"},
        confidence=0.6,
    )

    model.add_entry(hard)
    model.add_entry(inferred)

    assert model.entries[hard.id].status == "active"
    assert model.entries[inferred.id].status == "active"

    packet = model.context_packet(TENANT, USER, {"repo": "mnemosyne"})
    assert [item["kind"] for item in packet["authoritative"]] == ["hard_instruction"]
    assert [item["kind"] for item in packet["inferred"]] == ["inferred_preference"]
    assert packet["rules"]["latent_never_overrides_explicit"] is True


def test_authority_order_matches_blueprint_precedence() -> None:
    def authority_of(kind: UserMemoryKind) -> int:
        return UserModelEntry(tenant_id=TENANT, user_id=USER, kind=kind, statement="x").authority()

    assert (
        authority_of(UserMemoryKind.HARD_INSTRUCTION)
        > authority_of(UserMemoryKind.IDENTITY)
        > authority_of(UserMemoryKind.EXPLICIT_PREFERENCE)
        > authority_of(UserMemoryKind.SITUATIONAL_PREFERENCE)
        > authority_of(UserMemoryKind.TEMPORARY_STATE)
        > authority_of(UserMemoryKind.INFERRED_PREFERENCE)
    )
