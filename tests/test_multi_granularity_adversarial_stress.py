"""Adversarial stress-test suite for multi-granularity passage indexing and score fusion.

Empirical verification of:
1. Extremely long sessions (5,000+ words, 50+ dialogue rounds) with buried needles.
2. Varied dialogue formatting (markdown bold, bracketed, Human/AI, untagged prose, multi-line).
3. Degenerate and boundary sessions (empty, 1-turn, whitespace, zero-match).
4. Hit.id preservation invariant (Hit.id NEVER altered from parent Evidence CID).
5. Needle rank lift over distractors under hierarchical fusion vs baseline BM25.
6. Cache reuse and state consistency across queries.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from mnemosyne.models import Hit
from mnemosyne.passages import (
    extract_session_subpassages,
    rank_passages,
    retrieve_passages,
)


def _generate_long_session(
    num_rounds: int,
    words_per_round: int = 100,
    needle_round: int = 25,
    needle_user: str = "User: My secret emergency passcode is CobaltChameleon77.",
    needle_asst: str = "Assistant: Understood, I have recorded the CobaltChameleon77 passcode.",
    speaker_format: str = "standard",
) -> tuple[str, int]:
    """Generate a synthetic conversational transcript of specified length and format."""
    rounds = []
    filler_topics = [
        "distributed consensus algorithms such as Raft and Paxos",
        "database indexing strategies including B-Trees, LSM-Trees and GiST",
        "quantum key distribution protocols using entangled photon pairs",
        "asynchronous event loops and cooperative multitasking in operating systems",
        "compiler optimization passes including loop unrolling and constant folding",
        "optical character recognition pipelines and neural network feature extractors",
        "spacecraft telemetry encoding and forward error correction algorithms",
        "microservices resilience patterns like circuit breakers and bulkheads",
        "cryptographic primitives like zero-knowledge proofs and lattice cryptography",
        "computational fluid dynamics and Navier-Stokes numerical approximations",
    ]

    total_words = 0
    for r in range(num_rounds):
        if r == needle_round:
            if speaker_format == "markdown":
                user_line = needle_user.replace("User:", "**User:**")
                asst_line = needle_asst.replace("Assistant:", "**Assistant:**")
            elif speaker_format == "brackets":
                user_line = needle_user.replace("User:", "[User]:")
                asst_line = needle_asst.replace("Assistant:", "[Assistant]:")
            elif speaker_format == "human":
                user_line = needle_user.replace("User:", "Human:").replace(
                    "Assistant:", "AI:"
                )
                asst_line = needle_asst.replace("User:", "Human:").replace(
                    "Assistant:", "AI:"
                )
            else:
                user_line = needle_user
                asst_line = needle_asst
            rounds.append(f"{user_line}\n{asst_line}")
            total_words += len(user_line.split()) + len(asst_line.split())
            continue

        topic = filler_topics[r % len(filler_topics)]
        # Generate word padding for this round
        user_words = [f"word{i}_{r}" for i in range(words_per_round // 2)]
        asst_words = [f"reply{i}_{r}" for i in range(words_per_round // 2)]

        if speaker_format == "markdown":
            u_prefix = f"**User:** Round {r}: Let us deeply analyze {topic}."
            a_prefix = f"**Assistant:** Round {r}: When analyzing {topic}, several architectural considerations arise."
        elif speaker_format == "brackets":
            u_prefix = f"[User]: Round {r}: Let us deeply analyze {topic}."
            a_prefix = f"[Assistant]: Round {r}: When analyzing {topic}, several architectural considerations arise."
        elif speaker_format == "human":
            u_prefix = f"Human: Round {r}: Let us deeply analyze {topic}."
            a_prefix = f"AI: Round {r}: When analyzing {topic}, several architectural considerations arise."
        elif speaker_format == "untagged":
            u_prefix = f"Round {r} section. We analyze {topic} extensively."
            a_prefix = (
                f"Observational notes on {topic} confirm theoretical predictions."
            )
        else:
            u_prefix = f"User: Round {r}: Let us deeply analyze {topic}."
            a_prefix = f"Assistant: Round {r}: When analyzing {topic}, several architectural considerations arise."

        u_body = f"{u_prefix} " + " ".join(user_words)
        a_body = f"{a_prefix} " + " ".join(asst_words)
        rounds.append(f"{u_body}\n{a_body}")
        total_words += len(u_body.split()) + len(a_body.split())

    if speaker_format == "untagged":
        return "\n\n".join(rounds), total_words
    return "\n".join(rounds), total_words


# ===========================================================================
# 1. Long Sessions (5,000+ words, 50+ rounds) with Buried Needles
# ===========================================================================


def test_long_session_5000_words_needle_buried_at_middle():
    """Verify needle retrieval and score fusion in a 5,000+ word session with needle in middle."""
    needle_round = 35
    text, words = _generate_long_session(
        num_rounds=70,
        words_per_round=80,
        needle_round=needle_round,
        needle_user="User: My secret emergency passcode is CobaltChameleon77.",
        needle_asst="Assistant: I have safely recorded your emergency passcode CobaltChameleon77.",
    )
    assert words >= 5000, f"Expected 5,000+ words, got {words}"

    long_cid = f"cid_long_session_{uuid.uuid4().hex[:8]}"
    long_hit = Hit(
        id=long_cid,
        kind="evidence",
        tenant_id="test_tenant",
        branch="main",
        text=text,
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 1, 1, tzinfo=UTC)},
    )

    # Distractor 1: Short session mentioning passcode and emergency
    distractor_short_cid = f"cid_distractor_short_{uuid.uuid4().hex[:8]}"
    distractor_short = Hit(
        id=distractor_short_cid,
        kind="evidence",
        tenant_id="test_tenant",
        branch="main",
        text="User: How do I change my emergency passcode?\nAssistant: Go to security settings to change your emergency passcode.",
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 1, 1, tzinfo=UTC)},
    )

    # Distractor 2: Medium session discussing emergency procedures
    distractor_med_cid = f"cid_distractor_med_{uuid.uuid4().hex[:8]}"
    distractor_med = Hit(
        id=distractor_med_cid,
        kind="evidence",
        tenant_id="test_tenant",
        branch="main",
        text="User: What is the emergency protocol for server outages?\nAssistant: In an emergency, activate the secondary failover cluster immediately and verify that passcodes are valid across nodes.",
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 1, 1, tzinfo=UTC)},
    )

    query = "What is my emergency passcode CobaltChameleon77?"
    candidates = [distractor_short, long_hit, distractor_med]

    # Baseline BM25 (no fusion)
    owner_base = object()
    base_ranked = rank_passages(owner_base, query, candidates, k=3, alpha=0.0, beta=0.0)
    assert len(base_ranked) == 3

    # Fused BM25
    owner_fused = object()
    fused_ranked = rank_passages(
        owner_fused, query, candidates, k=3, alpha=0.5, beta=0.5
    )

    # 1. Fused ranker MUST rank long_hit at position 0
    assert fused_ranked[0].id == long_cid
    assert fused_ranked[0].score > base_ranked[0].score
    # 2. Invariant: Hit.id is preserved exactly
    assert all(
        h.id in {long_cid, distractor_short_cid, distractor_med_cid}
        for h in fused_ranked
    )
    # 3. Receipt verification
    mg = fused_ranked[0].metadata["multi_granularity"]
    assert "CobaltChameleon77" in mg["best_round_text"]
    assert "CobaltChameleon77" in mg["best_turn_text"]
    assert mg["best_round_index"] == needle_round
    assert mg["max_round_score"] > 0.0
    assert mg["max_turn_score"] > 0.0
    assert mg["fused_score"] > mg["session_score"]


def test_needle_buried_at_boundaries():
    """Verify needles buried at extreme boundaries: Round 0 (start) and Round 59 (end)."""
    # Start boundary
    text_start, _ = _generate_long_session(
        num_rounds=60,
        words_per_round=90,
        needle_round=0,
        needle_user="User: Important account PIN is 998244353.",
        needle_asst="Assistant: Account PIN 998244353 is stored.",
    )
    # End boundary
    text_end, _ = _generate_long_session(
        num_rounds=60,
        words_per_round=90,
        needle_round=59,
        needle_user="User: Secondary access token is EmeraldViper42.",
        needle_asst="Assistant: Secondary access token EmeraldViper42 confirmed.",
    )

    cid_start = "cid_needle_start"
    cid_end = "cid_needle_end"
    hit_start = Hit(
        id=cid_start,
        kind="evidence",
        tenant_id="t",
        branch="main",
        text=text_start,
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 2, 1, tzinfo=UTC)},
    )
    hit_end = Hit(
        id=cid_end,
        kind="evidence",
        tenant_id="t",
        branch="main",
        text=text_end,
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 2, 1, tzinfo=UTC)},
    )

    # Test start needle
    res_start = rank_passages(
        object(), "What is account PIN 998244353?", [hit_start, hit_end], k=2
    )
    assert res_start[0].id == cid_start
    assert res_start[0].metadata["multi_granularity"]["best_round_index"] == 0
    assert "998244353" in res_start[0].metadata["multi_granularity"]["best_round_text"]

    # Test end needle
    res_end = rank_passages(
        object(), "What is access token EmeraldViper42?", [hit_start, hit_end], k=2
    )
    assert res_end[0].id == cid_end
    assert res_end[0].metadata["multi_granularity"]["best_round_index"] == 59
    assert (
        "EmeraldViper42" in res_end[0].metadata["multi_granularity"]["best_round_text"]
    )


# ===========================================================================
# 2. Format Variations (Markdown, Tags, Prose, Mixed, Multi-line)
# ===========================================================================


def test_markdown_bold_formatting():
    """Verify subpassage extraction and needle retrieval with **User:** and **Assistant:** tags."""
    text, _ = _generate_long_session(
        num_rounds=50,
        words_per_round=40,
        needle_round=20,
        needle_user="User: My favorite telescope model is CelestronNexStar8.",
        needle_asst="Assistant: The CelestronNexStar8 has excellent aperture and optics.",
        speaker_format="markdown",
    )
    hit = Hit(
        id="cid_markdown_session",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text=text,
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 3, 1, tzinfo=UTC)},
    )
    res = rank_passages(
        object(), "favorite telescope model CelestronNexStar8", [hit], k=1
    )
    assert len(res) == 1
    assert res[0].id == "cid_markdown_session"
    mg = res[0].metadata["multi_granularity"]
    assert "CelestronNexStar8" in mg["best_round_text"]
    assert mg["best_round_index"] == 20


def test_bracketed_speaker_formatting():
    """Verify subpassage extraction with [User]: and [Assistant]: tags."""
    text, _ = _generate_long_session(
        num_rounds=50,
        words_per_round=40,
        needle_round=15,
        needle_user="User: The backup archive encryption key is SapphireKraken33.",
        needle_asst="Assistant: Verified encryption key SapphireKraken33.",
        speaker_format="brackets",
    )
    hit = Hit(
        id="cid_brackets_session",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text=text,
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 3, 1, tzinfo=UTC)},
    )
    res = rank_passages(object(), "archive encryption key SapphireKraken33", [hit], k=1)
    assert len(res) == 1
    assert res[0].id == "cid_brackets_session"
    mg = res[0].metadata["multi_granularity"]
    assert "SapphireKraken33" in mg["best_round_text"]
    assert mg["best_round_index"] == 15


def test_human_ai_speaker_formatting():
    """Verify subpassage extraction with Human: and AI: speaker tags."""
    text, _ = _generate_long_session(
        num_rounds=50,
        words_per_round=40,
        needle_round=10,
        needle_user="User: My sailboat is named WindDancer.",
        needle_asst="Assistant: WindDancer is a graceful name for a sailboat.",
        speaker_format="human",
    )
    hit = Hit(
        id="cid_human_session",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text=text,
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 3, 1, tzinfo=UTC)},
    )
    res = rank_passages(object(), "sailboat name WindDancer", [hit], k=1)
    assert len(res) == 1
    assert res[0].id == "cid_human_session"
    mg = res[0].metadata["multi_granularity"]
    assert "WindDancer" in mg["best_round_text"]


def test_untagged_multi_paragraph_prose():
    """Verify subpassage extraction and paragraph chunking for untagged prose."""
    paragraphs = [
        f"Paragraph {i}: Detailed discussion on astrophysics and stellar nucleosynthesis of heavy elements."
        for i in range(40)
    ]
    # Insert needle paragraph
    paragraphs[18] = (
        "Paragraph 18: In 1859, the Carrington Event caused major geomagnetic disturbances and sparked telegraph wires."
    )
    prose_text = "\n\n".join(paragraphs)

    hit = Hit(
        id="cid_prose_session",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text=prose_text,
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 3, 1, tzinfo=UTC)},
    )
    res = rank_passages(
        object(),
        "Carrington Event geomagnetic disturbances telegraph wires",
        [hit],
        k=1,
    )
    assert len(res) == 1
    assert res[0].id == "cid_prose_session"
    mg = res[0].metadata["multi_granularity"]
    assert "Carrington Event" in mg["best_round_text"]
    assert mg["best_round_index"] == 18


def test_multiline_conversation_turns():
    """Verify multi-line turns with embedded code and explanations are grouped correctly."""
    text = (
        "User: How do I implement quicksort in Python?\n"
        "Here is what I have tried so far:\n"
        "def qs(arr):\n"
        "    if len(arr) <= 1: return arr\n"
        "    pivot = arr[0]\n"
        "    return qs([x for x in arr[1:] if x < pivot]) + [pivot] + qs([x for x in arr[1:] if x >= pivot])\n"
        "Is this optimal?\n"
        "Assistant: Your implementation has O(n log n) average time complexity,\n"
        "but it creates new sublists at each recursion step which uses O(n) auxiliary space.\n"
        "User: My specific benchmark target is SortingBenchmarkOmega4.\n"
        "Assistant: Under SortingBenchmarkOmega4, an in-place Lomuto partition scheme performs 40% faster."
    )
    subs = extract_session_subpassages("sess_multiline", text)
    turns = [sp for sp in subs if sp.granularity == "turn"]
    rounds = [sp for sp in subs if sp.granularity == "round"]

    assert len(turns) == 2
    assert "def qs(arr):" in turns[0].text
    assert "SortingBenchmarkOmega4" in turns[1].text
    assert len(rounds) == 2
    assert "Lomuto" in rounds[1].text


# ===========================================================================
# 3. Degenerate, Boundary & Edge Cases
# ===========================================================================


def test_empty_and_whitespace_sessions():
    """Verify PassageIndex and rank_passages safely handle empty and whitespace-only text."""
    empty_hit = Hit(
        id="cid_empty",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="",
        score=1.0,
        channel="evidence",
        metadata={},
    )
    whitespace_hit = Hit(
        id="cid_whitespace",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="   \n\n\t   \n",
        score=1.0,
        channel="evidence",
        metadata={},
    )
    normal_hit = Hit(
        id="cid_normal",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: I enjoy playing chess online.\nAssistant: Chess is a great tactical game.",
        score=1.0,
        channel="evidence",
        metadata={},
    )

    candidates = [empty_hit, whitespace_hit, normal_hit]
    ranked = rank_passages(object(), "playing chess", candidates, k=5)

    # Empty and whitespace sessions score 0.0, so only normal_hit is returned
    assert len(ranked) == 1
    assert ranked[0].id == "cid_normal"
    assert ranked[0].id != "cid_empty"


def test_zero_match_query():
    """Verify zero matching terms gracefully returns empty list without exception."""
    hit = Hit(
        id="cid_test",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: Hello there.\nAssistant: General Kenobi.",
        score=1.0,
        channel="evidence",
        metadata={},
    )
    ranked = rank_passages(object(), "qwertyasdfghjkllkjhgfdsazxcvbnm", [hit], k=10)
    assert ranked == []


def test_empty_candidates_and_non_passages():
    """Verify empty candidate list and non-passage evidence kinds return empty lists."""
    assert rank_passages(object(), "query", [], k=5) == []

    non_passage = Hit(
        id="cid_obs",
        kind="observation",
        tenant_id="t",
        branch="main",
        text="Some observation text",
        score=1.0,
        channel="observation",
        metadata={},
    )
    assert rank_passages(object(), "query", [non_passage], k=5) == []


def test_extreme_k_values():
    """Verify rank_passages handles k=0, negative k, and k much larger than corpus."""
    hit1 = Hit(
        id="c1",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: apples\nAssistant: bananas",
        score=1.0,
        channel="evidence",
    )
    hit2 = Hit(
        id="c2",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: cherries\nAssistant: dates",
        score=1.0,
        channel="evidence",
    )

    # k = 0
    assert rank_passages(object(), "apples", [hit1, hit2], k=0) == []
    # k = -1
    assert rank_passages(object(), "apples", [hit1, hit2], k=-1) == []
    # k = 1000 with 2 items
    res_large = rank_passages(object(), "apples", [hit1, hit2], k=1000)
    assert len(res_large) == 1
    assert res_large[0].id == "c1"


def test_extreme_fusion_weights():
    """Verify fusion behavior with alpha=0, beta=0 (pure session) and alpha=2, beta=2 (heavy subpassage)."""
    long_text, _ = _generate_long_session(
        num_rounds=50,
        words_per_round=60,
        needle_round=25,
        needle_user="User: Unique code is DiamondPanther11.",
        needle_asst="Assistant: DiamondPanther11 acknowledged.",
    )
    hit_long = Hit(
        id="c_long",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text=long_text,
        score=1.0,
        channel="evidence",
    )

    # alpha=0, beta=0: score should equal session score
    res_zero = rank_passages(
        object(), "DiamondPanther11", [hit_long], k=1, alpha=0.0, beta=0.0
    )
    assert len(res_zero) == 1
    mg_zero = res_zero[0].metadata["multi_granularity"]
    assert res_zero[0].score == mg_zero["session_score"]

    # alpha=2.0, beta=2.0: score should equal session_score + 2*round + 2*turn
    res_heavy = rank_passages(
        object(), "DiamondPanther11", [hit_long], k=1, alpha=2.0, beta=2.0
    )
    assert len(res_heavy) == 1
    mg_heavy = res_heavy[0].metadata["multi_granularity"]
    expected_fused = (
        mg_heavy["session_score"]
        + 2.0 * mg_heavy["max_round_score"]
        + 2.0 * mg_heavy["max_turn_score"]
    )
    assert abs(res_heavy[0].score - expected_fused) < 1e-6


# ===========================================================================
# 4. Invariant: Hit.id is NEVER corrupted or altered from parent Evidence CID
# ===========================================================================


def test_hit_id_never_corrupted_across_diverse_cids():
    """Strict invariant test: Hit.id must match parent Evidence CID regardless of ID format."""
    cids = [
        "bafkreigh2akiscaildcqabsyg3dfr6chu3fgjhgn46teq2h5eb42r2y",  # IPFS CIDv1
        "urn:uuid:6ba7b810-9dad-11d1-80b4-00c04fd430c8",  # URN UUID
        "session:user_123:turn_999:rev_2",  # Colon-separated
        "evidence_#1289@branch/main$special",  # Special characters
        "1234567890",  # Numeric string
    ]

    candidates = [
        Hit(
            id=cid,
            kind="evidence",
            tenant_id="tenant_x",
            branch="main",
            text=f"User: Message for session {idx}.\nAssistant: Acknowledged message {idx}.",
            score=1.0,
            channel="evidence",
            metadata={
                "source_cid": cid,
                "created_at": datetime(2023, 1, 1 + idx, tzinfo=UTC),
            },
        )
        for idx, cid in enumerate(cids)
    ]

    for cid_target in cids:
        ranked = rank_passages(
            object(), f"session {cids.index(cid_target)}", candidates, k=5
        )
        assert len(ranked) > 0
        top_hit = ranked[0]
        # Invariant checks:
        assert top_hit.id == cid_target, (
            f"Hit.id corrupted! Expected {cid_target}, got {top_hit.id}"
        )
        assert top_hit.metadata.get("source_cid") == cid_target
        # Verify NO returned hit has corrupted ID
        for h in ranked:
            assert h.id in cids, f"Returned hit has unknown ID: {h.id}"
            assert not h.id.endswith(":round:0"), (
                f"Hit.id incorrectly replaced with subpassage ID: {h.id}"
            )
            assert not h.id.endswith(":turn:0"), (
                f"Hit.id incorrectly replaced with subpassage ID: {h.id}"
            )


# ===========================================================================
# 5. Needle Rank Lift Verification
# ===========================================================================


def test_needle_rank_lift_quantified():
    """Empirically measure rank lift of target session under fusion vs baseline BM25.

    Construct a scenario where:
    - Target: 6,000-word session with buried needle.
    - Distractors: Multiple short/medium sessions repeating query terms with high TF/length ratios.
    - Measure: baseline BM25 rank vs Fused BM25 rank.
    """
    needle_kw = "CrimsonGazelle88"
    long_text, _ = _generate_long_session(
        num_rounds=60,
        words_per_round=100,
        needle_round=30,
        needle_user=f"User: The project codename is {needle_kw}.",
        needle_asst=f"Assistant: Tracking project codename {needle_kw}.",
    )
    long_hit = Hit(
        id="cid_target_needle_long",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text=long_text,
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 5, 1, tzinfo=UTC)},
    )

    # 4 distractor sessions with partial matches in short texts
    distractors = [
        Hit(
            id=f"cid_distractor_{i}",
            kind="evidence",
            tenant_id="t",
            branch="main",
            text=(
                f"User: What is the project codename status?\n"
                f"Assistant: Project codename tracking is active for sprint {i}."
            ),
            score=1.0,
            channel="evidence",
            metadata={"created_at": datetime(2023, 5, 1, tzinfo=UTC)},
        )
        for i in range(4)
    ]

    all_candidates = distractors + [long_hit]
    query = f"What is the project codename {needle_kw}?"

    # Baseline: alpha=0, beta=0
    owner_base = object()
    ranked_base = rank_passages(
        owner_base, query, all_candidates, k=5, alpha=0.0, beta=0.0
    )
    base_ranks = {h.id: idx for idx, h in enumerate(ranked_base)}
    base_needle_rank = base_ranks.get("cid_target_needle_long", 999)

    # Fused: alpha=0.5, beta=0.5
    owner_fused = object()
    ranked_fused = rank_passages(
        owner_fused, query, all_candidates, k=5, alpha=0.5, beta=0.5
    )
    fused_ranks = {h.id: idx for idx, h in enumerate(ranked_fused)}
    fused_needle_rank = fused_ranks.get("cid_target_needle_long", 999)

    # In fused ranking, needle MUST be at rank 0 (top hit)
    assert fused_needle_rank == 0, f"Expected needle at rank 0, got {fused_needle_rank}"
    # Verify lift: fused rank is strictly better or tied with baseline
    assert fused_needle_rank <= base_needle_rank
    # Verify fused score is significantly higher than baseline score
    target_fused_hit = next(h for h in ranked_fused if h.id == "cid_target_needle_long")
    mg = target_fused_hit.metadata["multi_granularity"]
    score_lift = (mg["fused_score"] - mg["session_score"]) / max(
        mg["session_score"], 1e-6
    )
    assert score_lift > 0.5, (
        f"Expected >= 50% score lift from fusion, got {score_lift * 100:.1f}%"
    )


# ===========================================================================
# 6. Cache Reuse and State Consistency
# ===========================================================================


def test_cache_reuse_across_consecutive_queries():
    """Verify that reusing the same owner across queries preserves Hit.id and updates receipts."""
    owner = object()

    hit_a = Hit(
        id="cid_session_A",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: I love gardening and planting roses.\nAssistant: Roses require pruning in early spring.",
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 1, 1, tzinfo=UTC)},
    )
    hit_b = Hit(
        id="cid_session_B",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: I am building a wooden coffee table.\nAssistant: Sanding the surface thoroughly gives a smooth finish.",
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 1, 1, tzinfo=UTC)},
    )

    candidates = [hit_a, hit_b]

    # Query 1: Roses
    res1 = rank_passages(owner, "planting roses", candidates, k=2)
    assert res1[0].id == "cid_session_A"
    assert "roses" in res1[0].metadata["multi_granularity"]["best_round_text"].lower()

    # Query 2: Coffee table (reuses cached PassageIndex on owner)
    res2 = rank_passages(owner, "wooden coffee table", candidates, k=2)
    assert res2[0].id == "cid_session_B"
    assert (
        "coffee table"
        in res2[0].metadata["multi_granularity"]["best_round_text"].lower()
    )

    # Query 3: Incremental addition of a 3rd session
    hit_c = Hit(
        id="cid_session_C",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: My cat is named Whiskers.\nAssistant: Whiskers is a cute cat name.",
        score=1.0,
        channel="evidence",
        metadata={"created_at": datetime(2023, 1, 1, tzinfo=UTC)},
    )
    candidates_expanded = [hit_a, hit_b, hit_c]
    res3 = rank_passages(owner, "cat Whiskers", candidates_expanded, k=3)
    assert res3[0].id == "cid_session_C"
    assert "Whiskers" in res3[0].metadata["multi_granularity"]["best_round_text"]
    assert res3[0].id == "cid_session_C"


# ===========================================================================
# 7. Parameterized Needle Rank Lift Sweep & Robustness under Punctuation/Emojis
# ===========================================================================


@pytest.mark.parametrize(
    ("rounds", "wpr", "pos", "fmt", "min_words"),
    [
        (20, 50, 0.5, "standard", 1000),
        (50, 60, 0.0, "standard", 3000),
        (50, 60, 0.5, "standard", 3000),
        (50, 60, 0.98, "standard", 3000),
        (75, 70, 0.5, "markdown", 5000),
        (100, 80, 0.35, "standard", 7500),
    ],
)
def test_sweep_needle_rank_lift(
    rounds: int, wpr: int, pos: float, fmt: str, min_words: int
):
    """Systematically verify needle rank lift and top-1 ranking across round counts, word lengths, and positions."""
    needle_u = "User: The master encryption key is ObsidianFalcon99."
    needle_a = "Assistant: Recorded master encryption key ObsidianFalcon99."
    query = "What is the master encryption key ObsidianFalcon99?"

    needle_r = int(rounds * pos)
    text, total_w = _generate_long_session(
        num_rounds=rounds,
        words_per_round=wpr,
        needle_round=needle_r,
        needle_user=needle_u,
        needle_asst=needle_a,
        speaker_format=fmt,
    )
    assert total_w >= min_words, f"Expected at least {min_words} words, got {total_w}"

    target_hit = Hit(
        id="target_needle",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text=text,
        score=1.0,
        channel="evidence",
    )

    # 3 distractors with high term frequency in short transcripts
    d1 = Hit(
        id="dist_short_1",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: What is the master encryption key?\nAssistant: Use a 256-bit AES master encryption key.",
        score=1.0,
        channel="evidence",
    )
    d2 = Hit(
        id="dist_short_2",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: How do I generate an encryption key?\nAssistant: An encryption key can be generated using openssl rand master.",
        score=1.0,
        channel="evidence",
    )
    d3 = Hit(
        id="dist_med_1",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: Tell me about falcon birds.\nAssistant: The peregrine falcon is a bird of prey known for its speed.",
        score=1.0,
        channel="evidence",
    )

    candidates = [d1, d2, d3, target_hit]

    # Baseline BM25: alpha=0, beta=0
    r_base = rank_passages(object(), query, candidates, k=4, alpha=0.0, beta=0.0)
    base_ranks = {h.id: idx for idx, h in enumerate(r_base)}
    base_sc = next(h.score for h in r_base if h.id == "target_needle")
    base_rk = base_ranks["target_needle"]

    # Fused BM25: alpha=0.5, beta=0.5
    r_fused = rank_passages(object(), query, candidates, k=4, alpha=0.5, beta=0.5)
    fused_ranks = {h.id: idx for idx, h in enumerate(r_fused)}
    fused_sc = next(h.score for h in r_fused if h.id == "target_needle")
    fused_rk = fused_ranks["target_needle"]

    # Fused rank MUST be rank 0 (top hit) and strictly better than or equal to baseline rank
    assert fused_rk == 0, f"Expected fused rank 0, got {fused_rk}"
    assert fused_rk <= base_rk
    # Fused score MUST exhibit significant lift over baseline
    lift_pct = (fused_sc - base_sc) / max(base_sc, 1e-6) * 100.0
    assert lift_pct >= 100.0, f"Expected >= 100% lift, got {lift_pct:.1f}%"


def test_special_query_characters_and_emojis():
    """Verify regex metacharacters, unicode, and emojis in query and session texts do not fail."""
    text = (
        "User: Secret key [Project *.*] is 🔑 Falcon-99 (alpha|beta)?\n"
        "Assistant: Noted the 🔑 Falcon-99 key for [Project *.*]."
    )
    hit = Hit(
        id="cid_special",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text=text,
        score=1.0,
        channel="evidence",
    )

    # Query with unescaped regex characters
    res = rank_passages(
        object(), "key [Project *.*] 🔑 Falcon-99 (alpha|beta)?", [hit], k=1
    )
    assert len(res) == 1
    assert res[0].id == "cid_special"
    mg = res[0].metadata["multi_granularity"]
    assert "Falcon-99" in mg["best_round_text"]


# ===========================================================================
# 8. Defect Demonstration: Stale session_ids in Cached PassageIndex on Owner
# ===========================================================================


def test_defect_stale_session_ids_when_texts_are_identical():
    """Defect demonstration: when candidates have identical text but different CIDs,
    the cached PassageIndex on owner is not rebuilt, leaking the previous CID into
    best_round_id and best_turn_id receipts, and corrupting Hit.id in round/turn retrieval.
    """

    class OwnerWithDict:
        pass

    owner = OwnerWithDict()

    # Query 1: session with CID_ALPHA
    h1 = Hit(
        id="CID_ALPHA",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: hello world\nAssistant: hello there",
        score=1.0,
        channel="evidence",
    )
    res1 = rank_passages(owner, "hello", [h1], k=1)
    assert res1[0].id == "CID_ALPHA"
    assert res1[0].metadata["multi_granularity"]["best_round_id"] == "CID_ALPHA:round:0"

    # Query 2: session with identical text but different CID (CID_BETA)
    h2 = Hit(
        id="CID_BETA",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="User: hello world\nAssistant: hello there",
        score=1.0,
        channel="evidence",
    )
    res2 = rank_passages(owner, "hello", [h2], k=1)
    # The Hit.id of res2[0] is CID_BETA, but the subpassage receipt must also reference CID_BETA!
    assert (
        res2[0].metadata["multi_granularity"]["best_round_id"] == "CID_BETA:round:0"
    ), (
        f"Defect: Stale cached index leaked {res2[0].metadata['multi_granularity']['best_round_id']} "
        f"into candidate CID_BETA"
    )

    # In round retrieval, Hit.id must be CID_BETA:round:0, NOT CID_ALPHA:round:0!
    round_hits = retrieve_passages(owner, "hello", [h2], k=1, granularity="round")
    assert round_hits[0].id == "CID_BETA:round:0", (
        f"Defect: Hit.id corrupted to {round_hits[0].id} (expected CID_BETA:round:0)"
    )
