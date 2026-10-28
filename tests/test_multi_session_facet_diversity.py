from __future__ import annotations

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, Hit
from mnemosyne.pipeline import _diversify_facets, _extract_query_facets, _fit_budget, _trim_hit_window
from mnemosyne.text import _tokenize_pure, approx_tokens, tokenize


def _make_hit(
    id: str,
    text: str,
    score: float = 1.0,
    metadata: dict | None = None,
) -> Hit:
    return Hit(
        id=id,
        kind="evidence",
        tenant_id="test-tenant",
        branch="main",
        text=text,
        score=score,
        channel="lexical",
        trust_tier=0,
        metadata=metadata or {},
    )


def test_hyphenated_compound_token_expansion() -> None:
    tokens = tokenize("bike-related accessories and state-of-the-art tools")
    assert "bike-related" in tokens
    assert "bike" in tokens
    assert "related" in tokens
    assert "state-of-the-art" in tokens
    assert "state" in tokens
    assert "art" in tokens

    pure = _tokenize_pure("cross-validation")
    assert pure == ["cross-validation", "cross", "validation"]

    # Retrieval matching
    engine = LocalMemoryEngine()
    try:
        e1 = engine.append_evidence(
            Evidence(
                tenant_id="t1",
                branch="main",
                user_id="u",
                actor="user",
                source_type="conversation",
                content="I purchased several bike-related components for the spring trip.",
                metadata={},
            )
        )
        res = engine.retrieve("What bike components did I purchase?", tenant_id="t1", record_access=False)
        assert len(res.hits) >= 1
        assert res.hits[0].id == e1
    finally:
        engine.close()


def test_counting_synonyms_passage_scores() -> None:
    engine = LocalMemoryEngine()
    try:
        e1 = engine.append_evidence(
            Evidence(
                tenant_id="t1",
                branch="main",
                user_id="u",
                actor="user",
                source_type="conversation",
                content="I have two brothers and one sister who live in Chicago.",
                metadata={},
            )
        )
        # Query uses "siblings", passage uses "brothers" and "sister"
        res = engine.retrieve("How many siblings do I have?", tenant_id="t1", record_access=False)
        assert len(res.hits) >= 1
        assert res.hits[0].id == e1
    finally:
        engine.close()


def test_facet_extraction_and_coverage_diversification() -> None:
    query = "Tell me about the hobbies of me, my parents, and my grandparents"
    facets = _extract_query_facets(query)
    assert len(facets) >= 3

    # Generate 6 hits: hits 0-3 about user, hit 4 about parents, hit 5 about grandparents
    hits = [
        _make_hit("h0", "I love playing guitar and writing code.", score=0.95),
        _make_hit("h1", "I spend my weekends hiking mountain trails.", score=0.90),
        _make_hit("h2", "I enjoy baking sourdough bread at home.", score=0.85),
        _make_hit("h3", "I play chess online every evening.", score=0.80),
        _make_hit("h4", "My parents enjoy gardening and growing organic tomatoes.", score=0.75),
        _make_hit("h5", "My grandparents love birdwatching and landscape painting.", score=0.70),
    ]

    diversified = _diversify_facets(query, hits, k=5)
    diversified_ids = [h.id for h in diversified[:3]]
    # Facet diversification must ensure parents (h4) and grandparents (h5) are promoted
    # into the top slots alongside the user hit (h0)
    assert "h0" in diversified_ids
    assert "h4" in diversified_ids
    assert "h5" in diversified_ids


def test_trim_hit_window_preserves_salient_passage() -> None:
    # Build a long multi-turn text exceeding 600 tokens
    paragraphs = [
        "First turn: casual talk about the weather and coffee.",
        "Second turn: discussed plans for lunch at the cafeteria.",
        "Third turn: detailed discussion about the robotics project architecture and sensors.",
        "Fourth turn: robotics motor calibration and PID controller tuning specifications.",
        "Fifth turn: wrapped up the meeting and scheduled the next sync.",
    ]
    long_text = "\n\n".join(paragraphs * 10)
    hit = _make_hit("h1", long_text, score=0.8)
    initial_tokens = approx_tokens(hit.text)
    assert initial_tokens > 600

    trimmed = _trim_hit_window(hit, query="robotics project sensors and motor calibration", max_tokens=300)
    trimmed_tokens = approx_tokens(trimmed.text)
    assert trimmed_tokens <= 350
    assert "robotics" in trimmed.text
    assert hit.id == trimmed.id


def test_fit_budget_packed_ensures_distinct_sessions_fit() -> None:
    # 5 distinct sessions, each ~500 tokens (total ~2500 tokens)
    sessions: list[Hit] = []
    for i in range(5):
        text = f"Session {i} discussion.\n\n" + ("Detailed notes about system engineering and design.\n\n" * 15)
        sessions.append(_make_hit(f"sess_{i}", text, score=1.0 - i * 0.1))

    budget = 1200
    # Standard fitting would only fit at most 2 sessions
    kept = _fit_budget(sessions, budget=budget, min_distinct_hits=5, query="system engineering")
    assert len(kept) >= 4
    total_tokens = sum(approx_tokens(h.text) for h in kept)
    assert total_tokens <= budget
