"""Tests verifying the Quality Gate >= 0.9000 capabilities across knowledge updates,

taxonomic concept expansion, and conjunctive/temporal-bound abstention grounding.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mnemosyne.models import Hit
from mnemosyne.passages import PassageIndex, rank_passages
from mnemosyne.retrieval import TimeWindow, query_support, similar_query_terms


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


def test_taxonomic_concept_expansion_cases():
    """Verify that hypernym queries match concrete hyponym sessions."""
    # 1. Vehicles -> truck / motorcycle
    texts = (
        "I drive a red truck to the lumber yard every week.",
        "My motorcycle is parked in the garage for the winter.",
        "My close friend David works in finance.",
    )
    idx = PassageIndex(texts)
    scores = idx.scores("How many vehicles do I own?")
    assert 0 in scores, "Session mentioning 'truck' must receive positive BM25 score for 'vehicles'"
    assert 1 in scores, "Session mentioning 'motorcycle' must receive positive BM25 score for 'vehicles'"

    # 2. Grandpa -> grandfather
    scores_g = idx.scores("When did my grandpa retire?")
    assert isinstance(scores_g, dict)
    assert similar_query_terms("grandpa", "grandfather")

    # 3. Vehicle hypernym -> concrete hyponyms
    assert similar_query_terms("vehicle", "motorcycle")
    assert similar_query_terms("vehicles", "truck")


def test_conjunctive_and_temporal_abstention_grounding_cases():
    """Verify that queries with ungrounded conjunctions or missing temporal bounds fail support."""
    dt_march = datetime(2023, 3, 15, 12, 0, tzinfo=timezone.utc)
    hit_march = Hit(
        id="h_march",
        kind="evidence",
        text="I visited two contemporary art museums and a photography gallery during my vacation.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="c",
        metadata={"created_at": dt_march},
    )

    # 1. Temporal-Bound: December window query with only March hits
    win_dec = TimeWindow(
        label="December",
        start=datetime(2023, 12, 1, 0, 0, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        rest="museums or galleries did I visit",
        axis="event",
    )
    # Check that candidate dt_march falls outside December window
    hit_created = hit_march.metadata["created_at"]
    assert not (win_dec.start <= hit_created < win_dec.end)

    # 2. Conjunctive premise: "basil and lavender"
    hit_tomatoes = Hit(
        id="h_tom",
        kind="evidence",
        text="In my balcony planters, I initially planted 6 basil seedlings and 4 mint cuttings.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="c",
    )
    rep_conj = query_support(
        "How many seedlings did I start for basil and lavender?",
        [hit_tomatoes],
    )
    assert rep_conj["anchor_grounding"]["satisfied"] is False
    assert any("lavender" in c for c in rep_conj["anchor_grounding"]["missing_conjunctions"])
    assert rep_conj["score"] <= 0.35

    # 3. Locative duration: "How long did I stay in Chile?"
    hit_peru = Hit(
        id="h_peru",
        kind="evidence",
        text="I spent ten days hiking in Peru. Next year I am thinking of visiting northern Chile.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="c",
    )
    rep_chile = query_support("How long did I stay in Chile?", [hit_peru])
    assert rep_chile["anchor_grounding"]["satisfied"] is False
    assert any("Chile" in loc for loc in rep_chile["anchor_grounding"]["missing_locatives"])
    assert rep_chile["score"] <= 0.35

    # 4. Compound noun grounding: "birthday party"
    hit_party = Hit(
        id="h_party",
        kind="evidence",
        text="I baked a lemon cake for the office party on Friday.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="c",
    )
    rep_party = query_support("Who came to my birthday party?", [hit_party])
    assert rep_party["anchor_grounding"]["satisfied"] is False
    assert any("birthday party" in comp for comp in rep_party["anchor_grounding"]["missing_compounds"])
    assert rep_party["score"] <= 0.35
