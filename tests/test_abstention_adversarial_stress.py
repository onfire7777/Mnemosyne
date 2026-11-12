from __future__ import annotations

from datetime import datetime, timezone

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


# ---------------------------------------------------------------------------
# Passing Baseline Tests
# ---------------------------------------------------------------------------

def test_unanswerable_proper_noun_halifax() -> None:
    """Explicit ungrounded proper noun Halifax triggers abstention."""
    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="I stayed at the Harbourfront Inn in Kelowna during my Canada vacation.", metadata={}
        ))
        res = engine.retrieve("Where did I stay when visiting Halifax?", tenant_id="t1", record_access=False)
        assert res.abstained is True
        qs = res.explain["confidence"]["query_support"]
        assert qs["score"] <= 0.35
        assert qs["anchor_grounding"]["satisfied"] is False
        assert "Halifax" in qs["anchor_grounding"]["missing_proper"]
    finally:
        engine.close()


def test_unanswerable_compound_coffee_table() -> None:
    """Recognized compound anchor coffee table triggers abstention when only one half is grounded."""
    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="I drink coffee every morning at the corner cafe.", metadata={}
        ))
        res = engine.retrieve("Where did I buy my coffee table?", tenant_id="t1", record_access=False)
        assert res.abstained is True
        qs = res.explain["confidence"]["query_support"]
        assert qs["score"] <= 0.35
        assert qs["anchor_grounding"]["satisfied"] is False
        assert "coffee table" in qs["anchor_grounding"]["missing_compounds"]
    finally:
        engine.close()


def test_unanswerable_focal_object_trumpet() -> None:
    """Focal object trumpet triggers abstention when memory only has clarinets."""
    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="I have 5 vintage clarinets in my music room.", metadata={}
        ))
        res = engine.retrieve("How many vintage trumpets do I have in my music room?", tenant_id="t1", record_access=False)
        assert res.abstained is True
        qs = res.explain["confidence"]["query_support"]
        assert qs["score"] <= 0.35
        assert qs["anchor_grounding"]["satisfied"] is False
        assert "trumpet" in qs["anchor_grounding"]["missing_focal"]
    finally:
        engine.close()


def test_answerable_knowledge_update_does_not_falsely_abstain() -> None:
    """Superseded memory does not cause false abstention on answerable update."""
    engine = LocalMemoryEngine()
    try:
        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t1 = datetime(2025, 6, 1, tzinfo=timezone.utc)
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="My favorite color used to be blue.", created_at=t0, metadata={"created_at": t0.isoformat()}
        ))
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="Actually, my favorite color is now emerald green.", created_at=t1, metadata={"created_at": t1.isoformat()}
        ))
        res = engine.retrieve("What is my current favorite color?", tenant_id="t1", record_access=False)
        assert res.abstained is False
        assert res.confidence >= 0.50
        assert "emerald green" in res.hits[0].text
    finally:
        engine.close()


def test_answerable_2hop_linked_facts_does_not_falsely_abstain() -> None:
    """2-hop bridge query supported via extra_texts does not falsely abstain."""
    hit = _make_hit("h1", "Arthur was born in Tintagel and was raised by Sir Ector.")
    query = "Who was Arthur's father?"
    extra_texts = ["Arthur was the son of King Uther Pendragon, his biological father."]
    supp = query_support(query, [hit], extra_texts=extra_texts)
    assert "father" in supp["matched_terms"]
    assert supp["anchor_grounding"]["satisfied"] is True
    assert supp["score"] >= 0.50


# ---------------------------------------------------------------------------
# Adversarial Stress Failures
# ---------------------------------------------------------------------------

def test_adversarial_dr_okafor_with_randy_okafor_distractor() -> None:
    """False premise Dr. Okafor must abstain when memory only has Dr. Lindqvist + Randy Okafor."""
    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="Dr. Lindqvist prescribed me cyclobenzaprine for my acute back pain.", metadata={}
        ))
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="Former pitcher Randy Okafor won 300 games in Major League Baseball.", metadata={}
        ))
        query = "What medication did Dr. Okafor prescribe for my back pain?"
        res = engine.retrieve(query, tenant_id="t1", record_access=False)
        # MUST abstain because Dr. Okafor is ungrounded (Frankenstein split)
        assert res.abstained is True, f"Expected abstention but got confident answer with hits: {[h.text for h in res.hits]}"
        qs = res.explain["confidence"]["query_support"]
        assert qs["score"] <= 0.35
    finally:
        engine.close()


def test_adversarial_randy_lindqvist_frankenstein_proper_noun() -> None:
    """False premise Randy Lindqvist must abstain when Randy and Lindqvist are in separate documents."""
    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="Dr. Lindqvist prescribed me cyclobenzaprine for my back pain.", metadata={}
        ))
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="Randy Okafor won the Cy Young Award.", metadata={}
        ))
        query = "Did Randy Lindqvist prescribe medication for my back pain?"
        res = engine.retrieve(query, tenant_id="t1", record_access=False)
        assert res.abstained is True, f"Expected abstention but got confident answer with hits: {[h.text for h in res.hits]}"
    finally:
        engine.close()


def test_adversarial_possessive_entity_split_emmas_dog() -> None:
    """False premise Emma's dog must abstain when Emma and dog are in separate documents."""
    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="Emma bought a new laptop yesterday.", metadata={}
        ))
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="My dog ate some grass in the yard.", metadata={}
        ))
        query = "What did Emma's dog eat?"
        res = engine.retrieve(query, tenant_id="t1", record_access=False)
        assert res.abstained is True, "Expected abstention on ungrounded possessive entity phrase 'Emma's dog'"
    finally:
        engine.close()


def test_adversarial_possessive_dr_okafors_clinic() -> None:
    """False premise Dr. Okafor's clinic must abstain when split across documents."""
    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="Dr. Lindqvist opened a new clinic in downtown Seattle.", metadata={}
        ))
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="Former pitcher Randy Okafor won 300 games in Major League Baseball.", metadata={}
        ))
        query = "Where is Dr. Okafor's clinic located?"
        res = engine.retrieve(query, tenant_id="t1", record_access=False)
        assert res.abstained is True, "Expected abstention on ungrounded 'Dr. Okafor's clinic'"
    finally:
        engine.close()


def test_adversarial_general_compound_noun_holiday_party() -> None:
    """Compound noun holiday party not in hardcoded tuple must not match holiday and party in separate docs."""
    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="I went on holiday to London last summer.", metadata={}
        ))
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="We held a lively birthday party in Chicago.", metadata={}
        ))
        query = "Did I attend the holiday party in Chicago?"
        res = engine.retrieve(query, tenant_id="t1", record_access=False)
        assert res.abstained is True, "Expected abstention on Frankenstein compound 'holiday party'"
    finally:
        engine.close()


def test_adversarial_focal_object_outside_hardcoded_list_saxophone() -> None:
    """Focal domain object saxophone (absent from hardcoded set) must not falsely answer when guitar is present."""
    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="I decided to buy a new acoustic guitar while living in Seattle.", metadata={}
        ))
        query = "Did I buy a new saxophone when I was living in Seattle?"
        res = engine.retrieve(query, tenant_id="t1", record_access=False)
        assert res.abstained is True, "Expected abstention on absent focal object 'saxophone'"
    finally:
        engine.close()


def test_adversarial_numeric_anchor_mismatch_500_vs_50() -> None:
    """Numeric anchor 500 must trigger abstention when evidence only has 50."""
    engine = LocalMemoryEngine()
    try:
        engine.append_evidence(Evidence(
            tenant_id="t1", branch="main", user_id="u", actor="user", source_type="conversation",
            content="I had a wonderful $50 dinner in Tokyo.", metadata={}
        ))
        query = "How much did I spend on the $500 dinner in Tokyo?"
        res = engine.retrieve(query, tenant_id="t1", record_access=False)
        assert res.abstained is True, "Expected abstention on ungrounded numeric anchor '500'"
    finally:
        engine.close()
