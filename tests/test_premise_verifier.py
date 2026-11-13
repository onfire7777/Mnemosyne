"""Unit tests for PremiseConsistencyVerifier and decisive answering protocol."""

from mnemosyne.answering import (
    _clean_hedging_headers,
)
from mnemosyne.premise_verifier import (
    PremiseConsistencyVerifier,
    PremiseMismatch,
    PremiseVerificationResult,
)


def test_premise_mismatch_dataclass() -> None:
    mismatch = PremiseMismatch(
        mismatch_type="role_title_conflict",
        query_premise="role as Software Engineer Manager",
        factual_grounding="role as Senior Tech Lead",
        confidence=0.95,
        candidate_unanswerability_signal="Role mismatch detected",
    )
    assert mismatch.mismatch_type == "role_title_conflict"
    assert mismatch.confidence == 0.95
    d = mismatch.to_dict()
    assert d["query_premise"] == "role as Software Engineer Manager"


def test_premise_verification_result_dataclass() -> None:
    res = PremiseVerificationResult(
        is_consistent=True,
        abstention_recommended=False,
        mismatches=(),
        clean_abstention_text=None,
    )
    assert res.is_consistent is True
    assert res.abstention_recommended is False
    d = res.to_dict()
    assert d["is_consistent"] is True


def test_verifier_role_title_conflict() -> None:
    verifier = PremiseConsistencyVerifier()
    evidence = [
        {
            "cid": "c1",
            "content": "User: I was just promoted to Senior Tech Lead at my company.",
        }
    ]
    query = "How many engineers do I lead in my new role as Software Engineer Manager?"
    res = verifier.verify(query, evidence_rows=evidence)
    assert res.is_consistent is False
    assert res.abstention_recommended is True
    assert len(res.mismatches) >= 1
    m = res.mismatches[0]
    assert m.mismatch_type == "role_title_conflict"
    assert "Software Engineer Manager" in res.clean_abstention_text
    assert "Senior Tech Lead" in res.clean_abstention_text


def test_verifier_consistent_query() -> None:
    verifier = PremiseConsistencyVerifier()
    evidence = [
        {
            "cid": "c1",
            "content": "User: I booked a cabin in Asheville for our autumn trip.",
        }
    ]
    query = "How many nights did I reserve the cabin in Asheville?"
    res = verifier.verify(query, evidence_rows=evidence)
    assert res.is_consistent is True
    assert res.abstention_recommended is False
    assert res.clean_abstention_text is None


def test_decisive_direct_answering_hedging_cleaner() -> None:
    # Test removal of various hedging headers
    t1 = "Based on the provided chats, you have 2 bicycles."
    assert _clean_hedging_headers(t1) == "You have 2 bicycles."

    t2 = "According to the relevant chat history, your role is Senior Tech Lead."
    assert _clean_hedging_headers(t2) == "Your role is Senior Tech Lead."

    t3 = "It appears that you spent $40 on a phone case."
    assert _clean_hedging_headers(t3) == "You spent $40 on a phone case."

    t4 = "As an AI, I see that you visited Paris in 2024."
    assert _clean_hedging_headers(t4) == "I see that you visited Paris in 2024."

    t5 = "You have 2 siblings: your brother Omar and your sister Ines."
    assert _clean_hedging_headers(t5) == t5

    t6 = "Please note that your subscription expires tomorrow."
    assert _clean_hedging_headers(t6) == "Your subscription expires tomorrow."

    t7 = "As an AI assistant I cannot do that."
    assert _clean_hedging_headers(t7) == "I cannot do that."
