"""Unit and integration tests for speaker-aware fact distillation and EpisodicUserDigest."""

from __future__ import annotations

from datetime import UTC, datetime

from mnemosyne.episodic_facts import (
    DistilledFact,
    EpisodicUserDigest,
    build_episodic_user_digest,
    extract_episodic_facts,
    extract_open_domain_facts,
)
from mnemosyne.models import Assertion, Evidence


def test_speaker_filtering_assistant_turns_excluded() -> None:
    """Assistant turns with biographical facts must be categorized as agent_experience and excluded from user digest."""
    # Assistant claiming residence and family
    assistant_text = (
        "assistant: In 2018, I lived in Boston. My daughter is named Alice."
    )
    facts = extract_episodic_facts(assistant_text, speaker_role="assistant")

    # Assertions must have subject="assistant" and speaker_role="assistant"
    for a in facts.assertions:
        assert a.subject == "assistant"
        assert a.qualifiers.get("speaker_role") == "assistant"
        assert a.qualifiers.get("epistemic_class") == "agent_experience"

    digest = build_episodic_user_digest(facts)
    assert len(digest.facts) == 0

    rendered = digest.render_markdown()
    assert "Boston" not in rendered
    assert "Alice" not in rendered
    assert "(No active user facts recorded)" in rendered


def test_assistant_hypothetical_statements_not_extracted() -> None:
    """Assistant hypothetical scenarios must never be extracted as facts."""
    hypothetical_turns = [
        "assistant: Suppose you bought 3 guitars and spent $500 on bike repairs.",
        "assistant: Imagine you moved to Chicago next year.",
        "assistant: What if you lived in Tokyo?",
        "assistant: Let's say you paid $100 for dinner yesterday.",
    ]
    for turn in hypothetical_turns:
        facts = extract_episodic_facts(turn, speaker_role="assistant")
        digest = build_episodic_user_digest(facts)
        assert len(digest.facts) == 0
        md = digest.render_markdown()
        assert "guitar" not in md.lower()
        assert "chicago" not in md.lower()
        assert "tokyo" not in md.lower()
        assert "bike" not in md.lower()


def test_user_facts_extracted_and_digest_formatting() -> None:
    """User facts are extracted and cleanly formatted into an authoritative digest."""
    user_text = (
        "user: I live in San Diego. My wife Sarah and my pet dog Buster live with me. "
        "I bought 2 guitars and spent $450 on bike repairs."
    )
    facts = extract_episodic_facts(user_text, speaker_role="user")

    # Verify user facts extracted
    digest = build_episodic_user_digest(facts)
    assert isinstance(digest, EpisodicUserDigest)
    assert len(digest.facts) >= 4

    categories = {f.category for f in digest.facts}
    assert "residence" in categories
    assert "family_pet" in categories
    assert "expense" in categories
    assert "count" in categories

    rendered = digest.render_markdown()
    assert (
        "=== EPISODIC USER-FACT & STATE DIGEST (AUTHORITATIVE USER STATEMENTS) ==="
        in rendered
    )
    assert "NOTE: The facts below were authored by the user" in rendered
    assert "## Current State & Facts:" in rendered
    assert "- Residence: San Diego [CURRENT]" in rendered
    assert "- Family/Pet (has_family): Sarah [CURRENT]" in rendered
    assert "- Family/Pet (has_pet): Buster [CURRENT]" in rendered
    assert "- Quantity/Possession: 2 guitars [CURRENT]" in rendered
    assert "- Expense: $450 on bike repairs [CURRENT]" in rendered
    assert (
        "========================================================================"
        in rendered
    )


def test_multi_turn_mixed_dialogue_digest() -> None:
    """In a multi-turn conversation, only user statements are retained in the digest, with chronological tracking."""
    evidence_items = [
        Evidence(
            tenant_id="t1",
            user_id="u1",
            actor="user",
            source_type="conversation",
            cid="ev1",
            content="user: In 2020, I lived in Boise.",
            created_at=datetime(2020, 1, 1, 12, 0, tzinfo=UTC),
        ),
        Evidence(
            tenant_id="t1",
            user_id="u1",
            actor="assistant",
            source_type="conversation",
            cid="ev2",
            content="assistant: Nice city! I lived in Seattle before. Suppose you bought 5 cars, where would you park?",
            created_at=datetime(2020, 1, 1, 12, 5, tzinfo=UTC),
        ),
        Evidence(
            tenant_id="t1",
            user_id="u1",
            actor="user",
            source_type="conversation",
            cid="ev3",
            content="user: In 2024, I moved to San Diego. I bought 2 guitars.",
            created_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        ),
        Evidence(
            tenant_id="t1",
            user_id="u1",
            actor="assistant",
            source_type="conversation",
            cid="ev4",
            content="assistant: San Diego has great beaches! I own a parrot myself.",
            created_at=datetime(2024, 1, 1, 12, 5, tzinfo=UTC),
        ),
    ]

    all_assertions: list[Assertion] = []
    for ev in evidence_items:
        role = "assistant" if ev.actor == "assistant" else "user"
        extracted = extract_episodic_facts(ev, speaker_role=role)
        all_assertions.extend(extracted.assertions)

    digest = build_episodic_user_digest(all_assertions)

    # Seattle and parrot from assistant must not be present
    rendered = digest.render_markdown()
    assert "Seattle" not in rendered
    assert "parrot" not in rendered
    assert "5 cars" not in rendered

    # Current user state
    assert "- Residence: San Diego [CURRENT]" in rendered
    assert "- Quantity/Possession: 2 guitars [CURRENT]" in rendered

    # Trajectories present
    assert "## Chronological State Trajectories:" in rendered
    assert "user.residence:" in rendered
    assert "Boise" in rendered
    assert "San Diego" in rendered


def test_episodic_user_digest_as_of_temporal_slicing() -> None:
    """as_of argument slices active facts at an arbitrary historical point in time."""
    assertions = [
        Assertion(
            tenant_id="t1",
            user_id="u1",
            branch="main",
            subject="user",
            predicate="residence",
            object="Boise",
            valid_from=datetime(2020, 1, 1, tzinfo=UTC),
            valid_to=datetime(2024, 1, 1, tzinfo=UTC),
            status="superseded",
            qualifiers={"speaker_role": "user"},
        ),
        Assertion(
            tenant_id="t1",
            user_id="u1",
            branch="main",
            subject="user",
            predicate="residence",
            object="San Diego",
            valid_from=datetime(2024, 1, 1, tzinfo=UTC),
            valid_to=None,
            status="active",
            qualifiers={"speaker_role": "user"},
        ),
    ]

    # As of 2022: Boise was current, San Diego had not happened yet
    digest_2022 = build_episodic_user_digest(
        assertions, as_of=datetime(2022, 6, 1, tzinfo=UTC)
    )
    current_2022 = [f for f in digest_2022.facts if f.is_current]
    assert len(current_2022) == 1
    assert current_2022[0].value == "Boise"

    # As of 2025: San Diego is current
    digest_2025 = build_episodic_user_digest(
        assertions, as_of=datetime(2025, 1, 1, tzinfo=UTC)
    )
    current_2025 = [f for f in digest_2025.facts if f.is_current]
    assert len(current_2025) == 1
    assert current_2025[0].value == "San Diego"


def test_distilled_fact_dataclass_contract() -> None:
    """DistilledFact maintains frozen slots and required attributes."""
    fact = DistilledFact(
        fact_id="f1",
        speaker_role="user",
        category="residence",
        subject="user",
        predicate="residence",
        value="Portland",
        valid_from=datetime(2023, 5, 1, tzinfo=UTC),
        valid_to=None,
        is_current=True,
        scope={"city": "Portland"},
    )
    assert fact.fact_id == "f1"
    assert fact.speaker_role == "user"
    assert fact.category == "residence"
    assert fact.subject == "user"
    assert fact.predicate == "residence"
    assert fact.value == "Portland"
    assert fact.is_current is True
    assert fact.scope == {"city": "Portland"}


def test_user_hypothetical_statements_excluded_from_digest() -> None:
    """User hypothetical statements ('suppose', 'what if', 'imagine') are tagged and excluded from digest."""
    turns = [
        "user: Suppose I moved to Chicago.",
        "user: What if I bought 5 cars?",
        "user: Imagine I lived in Tokyo next year.",
    ]
    for turn in turns:
        extracted = extract_episodic_facts(turn, speaker_role="user")
        for a in extracted.assertions:
            assert (
                a.qualifiers.get("is_hypothetical") is True
                or a.scope.get("is_hypothetical") is True
            )
        digest = build_episodic_user_digest(extracted)
        assert len(digest.facts) == 0
        md = digest.render_markdown()
        assert "chicago" not in md.lower()
        assert "5 cars" not in md.lower()
        assert "tokyo" not in md.lower()


def test_timezone_naive_and_aware_sorting_in_digest() -> None:
    """Assertions with mixed naive and UTC-aware datetimes sort cleanly without TypeError."""
    a1 = Assertion(
        tenant_id="t1",
        subject="user",
        predicate="residence",
        object="Boston",
        valid_from=datetime(2020, 1, 1),  # naive
        valid_to=datetime(2023, 1, 1),  # naive
        status="superseded",
        qualifiers={"speaker_role": "user"},
    )
    a2 = Assertion(
        tenant_id="t1",
        subject="user",
        predicate="residence",
        object="San Diego",
        valid_from=datetime(2023, 1, 1, tzinfo=UTC),  # aware
        status="active",
        qualifiers={"speaker_role": "user"},
    )
    digest = build_episodic_user_digest([a1, a2])
    assert len(digest.facts) == 2
    assert digest.facts[0].value == "Boston"
    assert digest.facts[1].value == "San Diego"
    assert digest.facts[1].is_current is True

    # as_of query with naive datetime
    digest_as_of = build_episodic_user_digest([a1, a2], as_of=datetime(2021, 1, 1))
    current_facts = [f for f in digest_as_of.facts if f.is_current]
    assert len(current_facts) == 1
    assert current_facts[0].value == "Boston"


def test_as_of_single_valued_deduplication() -> None:
    """Under point-in-time as_of lookup, multiple un-expired single-valued attributes deduplicate to the latest."""
    a1 = Assertion(
        tenant_id="t1",
        subject="user",
        predicate="residence",
        object="Boston",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,  # omitted valid_to
        status="active",
        qualifiers={"speaker_role": "user"},
    )
    a2 = Assertion(
        tenant_id="t1",
        subject="user",
        predicate="residence",
        object="Chicago",
        valid_from=datetime(2022, 1, 1, tzinfo=UTC),
        valid_to=None,  # omitted valid_to
        status="active",
        qualifiers={"speaker_role": "user"},
    )

    # In 2021, only Boston occurred so only Boston is current
    digest_2021 = build_episodic_user_digest(
        [a1, a2], as_of=datetime(2021, 1, 1, tzinfo=UTC)
    )
    current_2021 = [f for f in digest_2021.facts if f.is_current]
    assert len(current_2021) == 1
    assert current_2021[0].value == "Boston"

    # In 2023, both occurred, but single-value attribute residence deduplicates to the latest (Chicago)
    digest_2023 = build_episodic_user_digest(
        [a1, a2], as_of=datetime(2023, 1, 1, tzinfo=UTC)
    )
    current_2023 = [f for f in digest_2023.facts if f.is_current]
    assert len(current_2023) == 1
    assert current_2023[0].value == "Chicago"


def test_open_domain_hypothetical_prefix_stripped_and_excluded_from_digest() -> None:
    """Hypothetical markers are stripped from subjects and open-domain hypothetical assertions are excluded from digest."""
    text = "user: Suppose Alice prefers dark mode. Hypothetically I work at Apple."
    facts = extract_episodic_facts(text, speaker_role="user")

    # Assertions must be extracted with cleaned subjects
    assert len(facts.assertions) == 2
    subjects = {a.subject for a in facts.assertions}
    assert "Alice" in subjects
    assert "user" in subjects
    assert "Suppose Alice" not in subjects
    assert "Hypothetically I" not in subjects

    # Must be flagged as is_hypothetical in both qualifiers and scope
    for a in facts.assertions:
        assert a.qualifiers.get("is_hypothetical") is True
        assert a.scope.get("is_hypothetical") is True

    # Must be filtered out of EpisodicUserDigest
    digest = build_episodic_user_digest(facts)
    current_facts = [f for f in digest.facts if f.is_current]
    assert len(current_facts) == 0
    assert len(digest.facts) == 0

    rendered = digest.render_markdown()
    assert "prefers" not in rendered.lower()
    assert "dark mode" not in rendered.lower()
    assert "apple" not in rendered.lower()


def test_direct_extract_open_domain_facts_strips_hypothetical_markers() -> None:
    """Direct calls to extract_open_domain_facts strip leading hypothetical triggers and tag is_hypothetical."""
    res1 = extract_open_domain_facts(
        "Suppose Alice prefers dark mode.", speaker_role="user"
    )
    assert len(res1.assertions) == 1
    a1 = res1.assertions[0]
    assert a1.subject == "Alice"
    assert a1.predicate == "prefers"
    assert a1.object == "dark mode"
    assert a1.qualifiers.get("is_hypothetical") is True
    assert a1.scope.get("is_hypothetical") is True

    res2 = extract_open_domain_facts(
        "Hypothetically I work at Apple.", speaker_role="user"
    )
    assert len(res2.assertions) == 1
    a2 = res2.assertions[0]
    assert a2.subject == "user"
    assert a2.predicate == "work_at"
    assert a2.object == "Apple"
    assert a2.qualifiers.get("is_hypothetical") is True
    assert a2.scope.get("is_hypothetical") is True


def test_mixed_real_and_hypothetical_open_domain_statements() -> None:
    """Real user statements are retained in the digest while hypothetical ones are excluded."""
    text = "user: Alice prefers dark mode. Suppose Bob likes coffee."
    facts = extract_episodic_facts(text, speaker_role="user")

    digest = build_episodic_user_digest(facts)
    current_facts = [f for f in digest.facts if f.is_current]
    assert len(current_facts) == 1
    assert current_facts[0].subject == "Alice"
    assert current_facts[0].predicate == "prefers"
    assert current_facts[0].value == "dark mode"

    rendered = digest.render_markdown()
    assert (
        "prefers: dark mode" in rendered.lower()
        or "dark mode [current]" in rendered.lower()
    )
    assert "bob" not in rendered.lower()
    assert "coffee" not in rendered.lower()
