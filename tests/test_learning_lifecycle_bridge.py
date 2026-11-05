from datetime import UTC, datetime
from mnemosyne.lifecycle import LifecycleState, FidelityTier, demotion_decision
from mnemosyne.experience.lifecycle import outcome_lifecycle
from mnemosyne.experience.runtime import stat_key


def test_verified_harmful_outcomes_accelerate_demotion_but_preserve_protected():
    now = datetime.now(UTC)
    state = LifecycleState("item", FidelityTier.VERBATIM, 0.4, 0.1, 0, None)
    learning = {
        "credit": {
            "c": {
                "target_kind": "item",
                "target_id": "item",
                "revision": 1,
                "task_class": "x",
            }
        },
        "stats": {
            stat_key("item", "item", 1, "x"): {
                "utility": 0.8,
                "n": 30,
                "last_outcome_at": now.isoformat(),
            }
        },
    }
    updated = outcome_lifecycle(state, "item", learning)
    assert updated.outcome_utility < 0
    assert demotion_decision(updated, now)[1]
    updated.protected = True
    assert not demotion_decision(updated, now)[1]
