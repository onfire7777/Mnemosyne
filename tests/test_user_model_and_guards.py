from __future__ import annotations

from mnemosyne.guard import no_degradation_guard
from mnemosyne.lifecycle import next_rehearsal_days
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
    model.add_entry(temporary)
    packet = model.context_packet(TENANT, USER, {"repo": "mnemosyne", "phase": "3"})

    authoritative = packet["authoritative"]
    assert [item["kind"] for item in authoritative][:2] == ["hard_instruction", "identity"]
    assert model.entries[inferred.id].status == "superseded"
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


def test_no_degradation_guard_blocks_memory_below_baseline() -> None:
    passing = no_degradation_guard(memory_score=0.82, no_memory_baseline=0.8, minimum_margin=0.01)
    failing = no_degradation_guard(memory_score=0.75, no_memory_baseline=0.8, minimum_margin=0.0)

    assert passing.passed is True
    assert failing.passed is False
    assert "degraded" in failing.reason

