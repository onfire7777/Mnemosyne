"""Tests for multi-granularity passage indexing, subpassage extraction, and hierarchical score fusion."""

from __future__ import annotations

from datetime import UTC, datetime

from mnemosyne.models import Hit
from mnemosyne.passages import (
    PassageIndex,
    SubPassage,
    extract_session_subpassages,
    rank_passages,
    retrieve_passages,
)


def test_extract_session_subpassages_standard_dialogue():
    """Verify subpassage extraction from standard conversational transcripts."""
    session_id = "session_diag_1"
    dialogue = (
        "User: Hi, can you give me some recommendations for dinner?\n"
        "Assistant: Certainly! Are you looking for Italian, Mexican, or Asian cuisines?\n"
        "User: I adopted a border collie named Juniper last week and want a pet-friendly patio.\n"
        "Assistant: A patio that welcomes dogs is a great idea. Bistro Bella has an outdoor pet-friendly terrace.\n"
        "User: Sounds wonderful, thank you!\n"
        "Assistant: You are very welcome! Have a great dinner with Juniper."
    )

    subs = extract_session_subpassages(
        session_id, dialogue, metadata={"tenant_id": "test_t"}
    )

    # Must contain macro session, user turns, and rounds
    granularities = [sp.granularity for sp in subs]
    assert "session" in granularities
    assert "round" in granularities
    assert "turn" in granularities

    # Check macro session
    session_sub = next(sp for sp in subs if sp.granularity == "session")
    assert isinstance(session_sub, SubPassage)
    assert session_sub.parent_id == session_id
    assert session_sub.sub_id == session_id
    assert session_sub.text == dialogue

    # Check turns
    turns = [sp for sp in subs if sp.granularity == "turn"]
    assert len(turns) == 3
    assert turns[0].speaker == "user"
    assert "dinner" in turns[0].text
    assert turns[1].speaker == "user"
    assert "Juniper" in turns[1].text
    assert turns[1].round_index == 1

    # Check rounds
    rounds = [sp for sp in subs if sp.granularity == "round"]
    assert len(rounds) == 3
    assert "dinner" in rounds[0].text and "Italian" in rounds[0].text
    assert "Juniper" in rounds[1].text and "Bistro Bella" in rounds[1].text
    assert rounds[1].sub_id == f"{session_id}:round:1"


def test_extract_session_subpassages_varied_speaker_tags():
    """Verify markdown and bracketed speaker tag parsing."""
    session_id = "session_tags_2"
    text = (
        "[User]: Hello world\n"
        "[Assistant]: Hello, how can I assist you today?\n"
        "**User:** What is the capital of France?\n"
        "**Assistant:** The capital of France is Paris."
    )
    subs = extract_session_subpassages(session_id, text)
    turns = [sp for sp in subs if sp.granularity == "turn"]
    rounds = [sp for sp in subs if sp.granularity == "round"]
    assert len(turns) == 2
    assert len(rounds) == 2
    assert "Hello world" in turns[0].text
    assert "capital of France" in turns[1].text
    assert "Paris" in rounds[1].text


def test_extract_session_subpassages_untagged_prose():
    """Verify fallback to paragraph chunking for untagged text/documents."""
    session_id = "doc_prose_3"
    prose = (
        "The Apollo program was the third United States human spaceflight program carried out by NASA.\n"
        "It succeeded in landing the first humans on the Moon in 1969.\n\n"
        "Project Apollo took its name from Apollo, the Greek god of light, music, and the sun.\n"
        "President John F. Kennedy set the national goal of landing a man on the Moon by the end of the 1960s.\n\n"
        "The mission utilized the Saturn V rocket, which was developed under the direction of Wernher von Braun."
    )
    subs = extract_session_subpassages(session_id, prose)
    rounds = [sp for sp in subs if sp.granularity == "round"]
    turns = [sp for sp in subs if sp.granularity == "turn"]

    # 3 distinct paragraphs
    assert len(rounds) == 3
    assert len(turns) == 3
    assert "Apollo program" in rounds[0].text
    assert "Saturn V" in rounds[2].text


def test_passage_index_multi_granularity_scoring():
    """Verify PassageIndex constructs subpassage postings and computes fused multi-granularity scores."""
    sess1 = (
        "User: I am learning to play the acoustic guitar.\n"
        "Assistant: That is a wonderful instrument to learn! Practice chords daily."
    )
    sess2 = (
        "User: My favorite hobby is oil painting landscapes.\n"
        "Assistant: Landscape painting with oils offers rich texture and color depth."
    )
    index = PassageIndex([sess1, sess2], session_ids=["sess_guitar", "sess_painting"])

    assert len(index.subpassages) > 0
    assert len(index.round_postings) > 0
    assert len(index.turn_postings) > 0

    scores = index.multi_granularity_scores(
        "acoustic guitar chords", alpha=0.5, beta=0.5
    )
    assert 0 in scores
    assert 1 in scores

    # Session 0 matches guitar and chords
    assert scores[0]["fused_score"] > scores[1]["fused_score"]
    assert scores[0]["max_round_score"] > 0.0
    assert scores[0]["max_turn_score"] > 0.0
    assert "guitar" in scores[0]["best_round_text"].lower()
    assert "guitar" in scores[0]["best_turn_text"].lower()


def test_needle_boosting_long_session_outranks_short_distractor():
    """Prove that hierarchical score fusion boosts a needle inside a 3,000-word transcript

    so it outranks a short distractor session that mentions a keyword.
    """
    # Build 3,000-word filler conversation
    filler_turns = []
    for i in range(25):
        filler_turns.append(
            f"User: Turn {i}: Let us discuss general software engineering principles and unit testing strategies."
        )
        filler_turns.append(
            f"Assistant: Turn {i}: Writing thorough test cases helps maintain high code quality and prevents regressions."
        )

    # Insert needle turn in round 12
    needle_user = "User: By the way, I adopted a rare border collie puppy named Juniper last Saturday!"
    needle_asst = "Assistant: Congratulations on adopting Juniper! A border collie will bring so much joy."
    filler_turns.insert(24, needle_user)
    filler_turns.insert(25, needle_asst)

    long_session_text = "\n".join(filler_turns)
    assert len(long_session_text.split()) > 700  # Substantial conversational text

    # Short distractor session mentioning only generic puppy/dog
    short_distractor_text = (
        "User: Can I bring a puppy to the office?\n"
        "Assistant: Pets are not allowed in the main building."
    )

    long_hit = Hit(
        id="session_needle_long",
        kind="evidence",
        tenant_id="tenant_1",
        branch="main",
        text=long_session_text,
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 6, 1, 10, 0, tzinfo=UTC)},
    )
    short_hit = Hit(
        id="session_distractor_short",
        kind="evidence",
        tenant_id="tenant_1",
        branch="main",
        text=short_distractor_text,
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 6, 1, 10, 0, tzinfo=UTC)},
    )

    query = "What is the name of my adopted border collie puppy Juniper?"

    # Rank with score fusion enabled
    owner = object()
    ranked = rank_passages(
        owner, query, [long_hit, short_hit], k=2, alpha=0.6, beta=0.6
    )

    assert len(ranked) == 2
    # The long session containing the exact needle MUST outrank the short distractor!
    assert ranked[0].id == "session_needle_long", (
        f"Expected needle session to rank first, but got {ranked[0].id} with score {ranked[0].score} "
        f"vs {ranked[1].id} with score {ranked[1].score}"
    )

    # Verify parent Hit.id is preserved
    assert ranked[0].id == "session_needle_long"
    assert "multi_granularity" in ranked[0].metadata
    mg = ranked[0].metadata["multi_granularity"]
    assert "Juniper" in mg["best_round_text"]
    assert mg["max_round_score"] > 0.0
    assert mg["max_turn_score"] > 0.0


def test_retrieve_passages_granularity_and_receipts():
    """Verify retrieve_passages entry point supports session, round, and turn granularities."""
    text1 = (
        "User: Where did I put my car keys?\n"
        "Assistant: You left your car keys on the kitchen counter next to the microwave.\n"
        "User: Thanks, found them!\n"
        "Assistant: Glad to hear that."
    )
    hit1 = Hit(
        id="session_keys_1",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text=text1,
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 5, 10, 8, 30, tzinfo=UTC)},
    )

    ops = object()
    query = "where did I leave my car keys"

    # 1. Session granularity (default): hit.id is parent Evidence CID
    session_hits = retrieve_passages(ops, query, [hit1], k=1, granularity="session")
    assert len(session_hits) == 1
    assert session_hits[0].id == "session_keys_1"
    assert "kitchen counter" in session_hits[0].text
    assert "multi_granularity" in session_hits[0].metadata

    # 2. Round granularity: hit.id is the round sub_id
    round_hits = retrieve_passages(ops, query, [hit1], k=1, granularity="round")
    assert len(round_hits) == 1
    assert "round" in round_hits[0].id
    assert round_hits[0].metadata["parent_session_id"] == "session_keys_1"
    assert round_hits[0].metadata["granularity"] == "round"
    assert "microwave" in round_hits[0].text

    # 3. Turn granularity: hit.id is the user turn sub_id
    turn_hits = retrieve_passages(ops, query, [hit1], k=1, granularity="turn")
    assert len(turn_hits) == 1
    assert "turn" in turn_hits[0].id
    assert turn_hits[0].metadata["parent_session_id"] == "session_keys_1"
    assert turn_hits[0].metadata["granularity"] == "turn"
    assert "car keys" in turn_hits[0].text
