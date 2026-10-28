"""Tests for Dynamic Intelligence, Adaptive Currency, Dynamic Window Sizing, and Corpus-Aware IDF."""

from __future__ import annotations

from datetime import datetime, timezone

from mnemosyne.models import Hit
from mnemosyne.passages import rank_passages
from mnemosyne.pipeline import _fit_budget, _trim_hit_window
from mnemosyne.retrieval import query_support, similar_query_terms
from mnemosyne.text import (
    dynamic_concept_bridge,
    expand_taxonomic_concepts,
)


def test_dynamic_corpus_idf_weighting():
    """Verify that rare terms in the active candidate set receive higher dynamic weights than common terms."""
    # Hit texts where 'common' appears in all 4 docs, but 'platypus' appears in 0 docs
    hits = [
        Hit(
            id=f"h{i}",
            kind="evidence",
            text=f"This is a common daily entry number {i} discussing ordinary routine work.",
            score=1.0,
            tenant_id="t",
            branch="main",
            channel="c",
        )
        for i in range(4)
    ]

    # Query with common term vs rare/missing term
    rep_common = query_support("routine work", hits)
    rep_rare = query_support("platypus habitat", hits)

    assert rep_common["score"] >= 0.8
    assert rep_rare["score"] < 0.35, "Missing rare terms with high dynamic IDF must cap support"


def test_dynamic_window_trimming_adapted_to_budget():
    """Verify that _fit_budget dynamically sizes per_hit_budget based on budget // needed_sessions."""
    long_text = "Alice discussed the research paper on neural network quantization in deep learning. " * 30
    hits = [
        Hit(
            id=f"h{i}",
            kind="evidence",
            text=f"Session {i}: {long_text}",
            score=1.0 - i * 0.05,
            tenant_id="t",
            branch="main",
            channel="c",
        )
        for i in range(5)
    ]

    # Tight budget: 1200 tokens for 5 needed hits -> ~240 tokens per hit
    fitted_tight = _fit_budget(hits, budget=1200, min_distinct_hits=5, query="quantization")
    assert len(fitted_tight) == 5
    for h in fitted_tight:
        assert len(h.text.split()) < len(long_text.split())
        assert "truncated for budget" in h.text

    # Generous budget: 4000 tokens for 5 hits -> fits with larger windows
    fitted_large = _fit_budget(hits, budget=4000, min_distinct_hits=5, query="quantization")
    assert len(fitted_large) == 5


def test_trim_hit_window_preserves_query_focal_content():
    """Verify _trim_hit_window centers the window around paragraphs matching query tokens."""
    part1 = "Unrelated introductory filler about morning coffee and breakfast weather. " * 15
    part2 = "CRITICAL FOCAL PARAGRAPH: The pre-approved mortgage amount from Wells Fargo was $450,000. " * 5
    part3 = "Unrelated concluding filler about evening dinner and walking the dog. " * 15
    full_text = f"{part1}\n\n{part2}\n\n{part3}"

    hit = Hit(
        id="h_test",
        kind="evidence",
        text=full_text,
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="c",
    )

    trimmed = _trim_hit_window(hit, query="Wells Fargo mortgage pre-approved amount", max_tokens=250)
    assert "Wells Fargo" in trimmed.text
    assert "$450,000" in trimmed.text


def test_query_intent_adaptive_currency_promotion():
    """Verify that update-intent queries promote newer sessions in the same topic cluster,

    while earliest-intent queries remain chronological/neutral.
    """
    class Owner:
        pass

    owner = Owner()
    dt_old = datetime(2023, 1, 10, 10, 0, tzinfo=timezone.utc)
    dt_new = datetime(2023, 6, 20, 15, 0, tzinfo=timezone.utc)

    # Older session with slightly higher BM25 keyword repetition
    cand_old = Hit(
        id="cand_old",
        kind="evidence",
        text="French press coffee brewing: I use a French press coffee-to-water ratio of 1 to 15. French press coffee.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="test",
        metadata={"created_at": dt_old},
    )
    # Newer session with updated fact
    cand_new = Hit(
        id="cand_new",
        kind="evidence",
        text="French press coffee update: I switched my French press coffee ratio to 1 to 17 for a lighter cup.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="test",
        metadata={"created_at": dt_new},
    )

    # 1. Update/switch query: newer session MUST outrank older session
    update_query = "For the coffee-to-water ratio in my French press, did I switch to more water per tablespoon of coffee?"
    ranked_update = rank_passages(owner, update_query, [cand_old, cand_new], k=2)
    assert ranked_update[0].id == "cand_new", "Update intent must prioritize the newer session"

    # 2. Earliest/initial query: older session should NOT be penalized by recency boost
    earliest_query = "What was the earliest coffee-to-water ratio I used in my French press?"
    ranked_earliest = rank_passages(owner, earliest_query, [cand_old, cand_new], k=2)
    assert ranked_earliest[0].id == "cand_old"


def test_taxonomic_expansion_and_dynamic_concept_bridge():
    """Verify taxonomic hypernym expansion and dynamic corpus-learned concept bridging."""
    # Static taxonomy
    assert "brother" in expand_taxonomic_concepts(["siblings"])
    assert "sister" in expand_taxonomic_concepts(["siblings"])
    assert "espresso machine" in expand_taxonomic_concepts(["appliance"])
    assert "air fryer" in expand_taxonomic_concepts(["appliances"])
    assert "italian" in expand_taxonomic_concepts(["cuisines"])

    # Dynamic concept bridge with tenant co-occurrences
    tenant_corpus_cooccurrences = {
        "transportation": ["ferry", "commuter rail", "scooter"],
        "beverage": ["kombucha", "matcha latte"],
    }
    bridged = dynamic_concept_bridge("transportation", tenant_corpus_cooccurrences)
    assert "ferry" in bridged
    assert "scooter" in bridged

    # similar_query_terms integration
    assert similar_query_terms("appliance", "espresso")
    assert similar_query_terms("appliance", "blender")
    assert similar_query_terms("cuisine", "mexican")
    assert similar_query_terms("sibling", "sister")
    assert similar_query_terms("grandma", "grandmother")

    # Co-hyponyms must NEVER match each other
    assert similar_query_terms("mexican", "italian") is False
    assert similar_query_terms("football", "tennis") is False
    assert similar_query_terms("brother", "sister") is False
    assert similar_query_terms("blender", "toaster") is False
    assert similar_query_terms("bicycle", "truck") is False


def test_conjunctive_nominal_abstention_grounding():
    """Verify that query with nominal conjunction 'X and Y' requires grounding for BOTH X and Y."""
    text_only_headphones = "I purchased new noise-canceling headphones last Friday for $199."
    hit = Hit(
        id="h1",
        kind="evidence",
        text=text_only_headphones,
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="c",
    )

    # 1. Query asks for both headphones AND iPad: one conjunct missing
    res = query_support("What is the total cost of my recently purchased headphones and the iPad?", [hit])
    assert res["anchor_grounding"]["satisfied"] is False
    assert any("iPad" in err or "ipad" in err for err in res["anchor_grounding"]["missing_conjunctions"])
    assert res["score"] <= 0.35

    # 2. Both conjuncts missing: must fail grounding
    res_both = query_support("Where can I buy soccer and basketball gear?", [hit])
    assert res_both["anchor_grounding"]["satisfied"] is False
    assert len(res_both["anchor_grounding"]["missing_conjunctions"]) > 0
    assert any("soccer and basketball" in err for err in res_both["anchor_grounding"]["missing_conjunctions"])
    assert res_both["score"] <= 0.35

    # 3. Co-hyponym leakage prevention: Italian in text cannot satisfy Mexican in 'Mexican and Italian'
    hit_italian = Hit(
        id="h2",
        kind="evidence",
        text="I went to a great Italian restaurant.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="c",
    )
    res_cuisines = query_support("Where can I buy Mexican and Italian food?", [hit_italian])
    assert res_cuisines["anchor_grounding"]["satisfied"] is False
    assert any("Mexican" in err or "mexican" in err for err in res_cuisines["anchor_grounding"]["missing_conjunctions"])
    assert "mexican" not in res_cuisines["matched_terms"]
    assert res_cuisines["score"] <= 0.35

    # 4. Range queries should not be falsely treated as missing conjunctions
    res_range = query_support("What happened between 2020 and 2022?", [hit])
    assert res_range["anchor_grounding"]["missing_conjunctions"] == []


def test_temporal_premise_event_axis_interval_overlap():
    """Verify that window with axis == 'event' evaluates event_start/event_end first and supports interval overlap."""
    from mnemosyne.pipeline import _event_time_interval
    from mnemosyne.retrieval import TimeWindow

    # Conversation created in November 2026, but the event occurred in December 2026
    h = Hit(
        id="h_event",
        kind="evidence",
        text="Attended the annual scientific conference in San Diego.",
        score=1.0,
        tenant_id="t",
        branch="main",
        channel="c",
        metadata={
            "created_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
            "event_start": datetime(2026, 12, 15, tzinfo=timezone.utc),
            "event_end": datetime(2026, 12, 18, tzinfo=timezone.utc),
        },
    )

    interval = _event_time_interval(h)
    assert interval is not None
    assert interval[0] == datetime(2026, 12, 15, tzinfo=timezone.utc)
    assert interval[1] == datetime(2026, 12, 18, tzinfo=timezone.utc)

    # Event window for December 2026
    win_dec = TimeWindow(
        label="December 2026",
        start=datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc),
        end=datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc),
        rest="conference",
        axis="event",
    )

    # Overlap check
    cand_start, cand_end = interval
    assert cand_start < win_dec.end and cand_end >= win_dec.start
