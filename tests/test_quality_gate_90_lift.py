"""Tests verifying the Quality Gate >= 0.9000 capabilities across knowledge updates,

taxonomic concept expansion, and conjunctive/temporal-bound abstention grounding.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mnemosyne.models import Hit
from mnemosyne.passages import rank_passages


def test_knowledge_updates_currency_prioritization_cases():
    """Verify topic-cluster currency tie-breaking on knowledge update queries."""
    class Owner:
        pass

    owner = Owner()
    dt_old = datetime(2023, 3, 1, 10, 0, tzinfo=timezone.utc)
    dt_new = datetime(2023, 5, 1, 10, 0, tzinfo=timezone.utc)

    # 1. Marathons run in one pair of shoes
    hit_old_shoes = Hit(
        id="shoes_1",
        kind="evidence",
        text="Running log: I have run 2 marathons in my Brooks Ghost shoes so far. Great shoes for long races.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="test",
        metadata={"created_at": dt_old},
    )
    hit_new_shoes = Hit(
        id="shoes_2",
        kind="evidence",
        text="Race update: I have now run 5 marathons in my Brooks Ghost shoes across the region.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="test",
        metadata={"created_at": dt_new},
    )
    ranked = rank_passages(
        owner,
        "How many marathons have I run in my Brooks Ghost shoes?",
        [hit_old_shoes, hit_new_shoes],
        k=2,
    )
    assert ranked[0].id == "shoes_2", "Newer session with 5 marathons must rank above older session with 2"

    # 2. Credit card limit approval
    hit_old_card = Hit(
        id="card_1",
        kind="evidence",
        text="Finance update: I got approved for a credit card from Harbor Credit Union with a limit of $5,000.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="test",
        metadata={"created_at": dt_old},
    )
    hit_new_card = Hit(
        id="card_2",
        kind="evidence",
        text="Card letter: Harbor Credit Union increased my approved credit card limit to $8,000.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="test",
        metadata={"created_at": dt_new},
    )
    ranked_m = rank_passages(
        owner,
        "What credit limit did Harbor Credit Union approve on my card?",
        [hit_old_card, hit_new_card],
        k=2,
    )
    assert ranked_m[0].id == "card_2"
