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

    # 1. Canon EOS 80D camera trips
    hit_old_canon = Hit(
        id="canon_1",
        kind="evidence",
        text="Photography log: I have taken my Canon EOS 80D camera on 4 trips so far. Great camera for travel.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="test",
        metadata={"created_at": dt_old},
    )
    hit_new_canon = Hit(
        id="canon_2",
        kind="evidence",
        text="Travel update: I have now taken my Canon EOS 80D camera on 7 trips across Europe.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="test",
        metadata={"created_at": dt_new},
    )
    ranked = rank_passages(
        owner,
        "How many trips have I taken my Canon EOS 80D camera on?",
        [hit_old_canon, hit_new_canon],
        k=2,
    )
    assert ranked[0].id == "canon_2", "Newer session with 7 trips must rank above older session with 4 trips"

    # 2. Wells Fargo mortgage pre-approval
    hit_old_mortgage = Hit(
        id="wf_1",
        kind="evidence",
        text="Finance update: I got pre-approved for a mortgage from Wells Fargo for the amount of $400,000.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="test",
        metadata={"created_at": dt_old},
    )
    hit_new_mortgage = Hit(
        id="wf_2",
        kind="evidence",
        text="Mortgage letter: Wells Fargo increased my pre-approved mortgage amount to $450,000.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="test",
        metadata={"created_at": dt_new},
    )
    ranked_m = rank_passages(
        owner,
        "What was the amount I was pre-approved for when I got my mortgage from Wells Fargo?",
        [hit_old_mortgage, hit_new_mortgage],
        k=2,
    )
    assert ranked_m[0].id == "wf_2"


def test_taxonomic_concept_expansion_cases():
    """Verify that hypernym queries match concrete hyponym sessions."""
    # 1. Siblings -> brother / sister
    texts = (
        "My brother Michael is an architect living in Seattle.",
        "My sister Sarah graduated from medical school last spring.",
        "My close friend David works in finance.",
    )
    idx = PassageIndex(texts)
    scores = idx.scores("What is the total number of siblings I have?")
    assert 0 in scores, "Session mentioning 'brother' must receive positive BM25 score for 'siblings'"
    assert 1 in scores, "Session mentioning 'sister' must receive positive BM25 score for 'siblings'"

    # 2. Grandma -> grandmother
    scores_g = idx.scores("How many years older is my grandma than me?")
    assert isinstance(scores_g, dict)
    assert similar_query_terms("grandma", "grandmother")

    # 3. Kitchen appliances -> espresso machine, air fryer
    assert similar_query_terms("appliance", "espresso")
    assert similar_query_terms("appliances", "air")


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

    # 2. Conjunctive premise: "tomatoes and chili peppers"
    hit_tomatoes = Hit(
        id="h_tom",
        kind="evidence",
        text="In my backyard garden, I initially planted 6 tomato plants and 4 cucumber vines.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="c",
    )
    rep_conj = query_support(
        "How many plants did I initially plant for tomatoes and chili peppers?",
        [hit_tomatoes],
    )
    assert rep_conj["anchor_grounding"]["satisfied"] is False
    assert any("chili" in c for c in rep_conj["anchor_grounding"]["missing_conjunctions"])
    assert rep_conj["score"] <= 0.35

    # 3. Locative duration: "How long was I in Korea for?"
    hit_japan = Hit(
        id="h_japan",
        kind="evidence",
        text="I spent two weeks traveling in Japan. Next year I am thinking of visiting South Korea.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="c",
    )
    rep_korea = query_support("How long was I in Korea for?", [hit_japan])
    assert rep_korea["anchor_grounding"]["satisfied"] is False
    assert any("Korea" in loc for loc in rep_korea["anchor_grounding"]["missing_locatives"])
    assert rep_korea["score"] <= 0.35

    # 4. Compound noun grounding: "birthday gift"
    hit_birthday = Hit(
        id="h_bday",
        kind="evidence",
        text="I organized a birthday celebration with chocolate cake and music.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="c",
    )
    rep_gift = query_support("What birthday gift did I buy for Sarah?", [hit_birthday])
    assert rep_gift["anchor_grounding"]["satisfied"] is False
    assert any("birthday gift" in comp for comp in rep_gift["anchor_grounding"]["missing_compounds"])
    assert rep_gift["score"] <= 0.35
