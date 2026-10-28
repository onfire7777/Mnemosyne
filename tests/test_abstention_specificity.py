from __future__ import annotations

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, Hit
from mnemosyne.retrieval import query_support


def _make_hit(id: str, text: str, score: float = 1.0, metadata: dict | None = None) -> Hit:
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


def test_proper_noun_absence_caps_support_and_abstains() -> None:
    hit_sf = _make_hit(
        "h1",
        "I stayed at the Fairmont Hotel in San Francisco during my California vacation.",
    )
    query = "Where did I stay when visiting Sacramento?"

    supp = query_support(query, [hit_sf])
    assert supp["anchor_grounding"]["satisfied"] is False
    assert "Sacramento" in supp["anchor_grounding"]["missing_proper"]
    assert supp["score"] <= 0.35
    assert supp["anchor_grounding"]["capped"] is True

    # End-to-end engine verification: absence of proper noun Sacramento triggers abstention
    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(
            Evidence(
                tenant_id="t1",
                branch="main",
                user_id="u",
                actor="user",
                source_type="conversation",
                content="I stayed at the Fairmont Hotel in San Francisco during my vacation.",
                metadata={},
            )
        )
        res = engine.retrieve(query, tenant_id="t1", record_access=False)
        assert res.abstained is True
    finally:
        engine.close()


def test_proper_noun_present_allows_full_support() -> None:
    hit_sac = _make_hit(
        "h1",
        "I stayed at the Citizen Hotel in Sacramento during my California vacation.",
    )
    query = "Where did I stay when visiting Sacramento?"

    supp = query_support(query, [hit_sac])
    assert supp["anchor_grounding"]["satisfied"] is True
    assert supp["anchor_grounding"]["missing_proper"] == []
    assert supp["score"] >= 0.50

    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(
            Evidence(
                tenant_id="t1",
                branch="main",
                user_id="u",
                actor="user",
                source_type="conversation",
                content="I stayed at the Citizen Hotel in Sacramento during my California vacation.",
                metadata={},
            )
        )
        res = engine.retrieve(query, tenant_id="t1", record_access=False)
        assert res.abstained is False
    finally:
        engine.close()


def test_compound_noun_cross_document_isolation() -> None:
    hit_table = _make_hit("h1", "I bought an antique table lamp for the dining room.")
    hit_tennis = _make_hit("h2", "I watched the exciting tennis championship match yesterday.")
    query = "Did I buy a table tennis racket?"

    # Table and tennis appear in separate documents, NOT within <= 2 tokens in the same document
    supp_split = query_support(query, [hit_table, hit_tennis])
    assert supp_split["anchor_grounding"]["satisfied"] is False
    assert "table tennis" in supp_split["anchor_grounding"]["missing_compounds"]
    assert supp_split["score"] <= 0.35

    # Grounded hit with table tennis in the same hit
    hit_together = _make_hit("h3", "I bought a professional table tennis racket and balls.")
    supp_together = query_support(query, [hit_together])
    assert supp_together["anchor_grounding"]["satisfied"] is True
    assert supp_together["anchor_grounding"]["missing_compounds"] == []
    assert supp_together["score"] >= 0.50


def test_possessive_stripping_on_proper_nouns() -> None:
    hit = _make_hit("h1", "Sarah opened an art studio in Portland last month.")
    query = "Where is Sarah's studio located?"

    supp = query_support(query, [hit])
    # Sarah's should have 's stripped, leaving proper noun Sarah
    assert supp["anchor_grounding"]["satisfied"] is True
    assert supp["anchor_grounding"]["missing_proper"] == []


def test_focal_object_grounding() -> None:
    hit = _make_hit("h1", "My driver's license expires in October 2027.")
    query = "What is the expiration date of my passport?"

    supp = query_support(query, [hit])
    assert supp["anchor_grounding"]["satisfied"] is False
    assert "passport" in supp["anchor_grounding"]["missing_focal"]
    assert supp["score"] <= 0.35


def test_multihop_bridge_query_supported_via_extra_texts() -> None:
    hit = _make_hit("h1", "Arthur was born in Tintagel and was raised by Sir Ector.")
    query = "Who was Arthur's father?"

    # Without extra_texts, father is missing
    supp_without = query_support(query, [hit])
    assert "father" in supp_without["missing_terms"]

    # With extra_texts from 2-hop graph facts
    extra_texts = ["Arthur was the son of King Uther Pendragon, his biological father."]
    supp_with = query_support(query, [hit], extra_texts=extra_texts)
    assert "father" in supp_with["matched_terms"]
    assert supp_with["anchor_grounding"]["satisfied"] is True
    assert supp_with["score"] >= 0.50


def test_dense_cosine_override_blocked_when_anchor_missing() -> None:
    # When cosine_ranked evaluates top_score >= floor, but an anchor proper noun is missing
    query = "Where did I stay when visiting Sacramento?"
    hit = _make_hit("h1", "I stayed at a wonderful hotel in San Francisco.")
    supp = query_support(query, [hit])
    assert supp["anchor_grounding"]["satisfied"] is False

    top_score = 0.92
    floor = 0.80
    anchor_ok = bool(supp.get("anchor_grounding", {}).get("satisfied", True))
    semantic_supported = (top_score >= floor) and anchor_ok
    assert semantic_supported is False


def test_dense_cosine_override_allowed_for_pure_paraphrase() -> None:
    # Pure paraphrase without missing proper nouns or compound anchors
    query = "my feline companion"
    hit = _make_hit("h1", "I adopted an adorable little cat from the shelter.")
    supp = query_support(query, [hit])
    # No proper nouns, compound anchors, or focal objects missing
    assert supp["anchor_grounding"]["satisfied"] is True

    top_score = 0.88
    floor = 0.80
    anchor_ok = bool(supp.get("anchor_grounding", {}).get("satisfied", True))
    semantic_supported = (top_score >= floor) and anchor_ok
    assert semantic_supported is True

