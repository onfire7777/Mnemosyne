"""Unit tests for PremiseConsistencyVerifier and decisive answering protocol."""

from mnemosyne.answering import (
    AnswerReadContext,
    AnswerRequest,
    GroundedAnswerOrchestrator,
    _clean_hedging_headers,
    adaptive_synthesize,
)
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence
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


def test_verifier_lodging_location_conflict() -> None:
    verifier = PremiseConsistencyVerifier()
    evidence = [
        {
            "cid": "c1",
            "content": "User: I booked an Airbnb in San Diego for our summer trip.",
        }
    ]
    query = "When did I book the Airbnb in Sacramento?"
    res = verifier.verify(query, evidence_rows=evidence)
    assert res.is_consistent is False
    assert res.abstention_recommended is True
    m = res.mismatches[0]
    assert m.mismatch_type == "location_conflict"
    assert "Sacramento" in res.clean_abstention_text
    assert "San Diego" in res.clean_abstention_text


def test_verifier_missing_pet_entity() -> None:
    verifier = PremiseConsistencyVerifier()
    evidence = [
        {
            "cid": "c1",
            "content": "User: I took my golden retriever Buster to the vet today.",
        }
    ]
    facts = [
        Assertion(
            tenant_id="default",
            subject="user",
            predicate="family_pet",
            object="dog Buster",
        )
    ]
    query = "What is the name of my pet hamster?"
    res = verifier.verify(query, facts=facts, evidence_rows=evidence)
    assert res.is_consistent is False
    assert res.abstention_recommended is True
    m = res.mismatches[0]
    assert m.mismatch_type == "missing_entity"
    assert "hamster" in res.clean_abstention_text


def test_verifier_comparative_timeline_counterfactual() -> None:
    verifier = PremiseConsistencyVerifier()
    evidence = [
        {
            "cid": "c1",
            "content": "User: Tom moved to Seattle last year. Alex started a new job in Boston.",
        }
    ]
    query = "Who became a parent first, Tom or Alex?"
    res = verifier.verify(query, evidence_rows=evidence)
    assert res.is_consistent is False
    assert res.abstention_recommended is True
    m = res.mismatches[0]
    assert m.mismatch_type == "counterfactual_comparison"
    assert "Neither Tom nor Alex" in res.clean_abstention_text


def test_verifier_consistent_query() -> None:
    verifier = PremiseConsistencyVerifier()
    evidence = [
        {
            "cid": "c1",
            "content": "User: I booked an Airbnb in San Diego for our summer trip.",
        }
    ]
    query = "When did I book the Airbnb in San Diego?"
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

    t3 = "It appears that you spent $65 on a car cover."
    assert _clean_hedging_headers(t3) == "You spent $65 on a car cover."

    t4 = "As an AI, I see that you visited Paris in 2024."
    assert _clean_hedging_headers(t4) == "I see that you visited Paris in 2024."

    t5 = "You have 2 siblings: your brother David and your sister Sarah."
    assert _clean_hedging_headers(t5) == t5

    t6 = "Please note that your subscription expires tomorrow."
    assert _clean_hedging_headers(t6) == "Your subscription expires tomorrow."

    t7 = "As an AI assistant I cannot do that."
    assert _clean_hedging_headers(t7) == "I cannot do that."


def test_verifier_comparative_timeline_cooccurring_entities() -> None:
    verifier = PremiseConsistencyVerifier()
    evidence = [
        {
            "cid": "c1",
            "content": "User: Tom moved to Seattle last year. Alex graduated from MIT.",
        }
    ]
    query = "Who graduated first, Tom or Alex?"
    res = verifier.verify(query, evidence_rows=evidence)
    assert res.is_consistent is False
    assert res.abstention_recommended is True
    assert "Alex is recorded as having graduated" in (res.clean_abstention_text or "")
    assert "no record of Tom" in (res.clean_abstention_text or "")


def test_orchestrator_premise_verifier_integration() -> None:
    engine = LocalMemoryEngine()
    engine.append_evidence(
        Evidence(
            tenant_id="t1",
            user_id="u1",
            actor="user",
            source_type="conversation",
            content="User: I booked an Airbnb in San Diego for our trip in July.",
            session_id="s1",
        )
    )
    context = AnswerReadContext(tenant_id="t1", user_id="u1")

    class SimpleDecomposer:
        def decompose(self, payload: dict[str, object]) -> object:
            return {"queries": [str(payload.get("question", ""))]}

    class SimpleReader:
        def read(self, payload: dict[str, object]) -> object:
            return {"claims": [], "unresolved": False}

    orchestrator = GroundedAnswerOrchestrator(engine, SimpleDecomposer())
    # False premise query: asking about Sacramento when booking is in San Diego
    request = AnswerRequest(
        question="When did I book the Airbnb in Sacramento?",
        context=context,
    )
    result = orchestrator.answer(request, SimpleReader())
    assert result.abstained is True
    assert result.public_reason == "premise_mismatch"
    assert "Sacramento" in result.answer
    assert "San Diego" in result.answer
    # Another tenant's evidence must never feed the premise wording.
    other = orchestrator.answer(
        AnswerRequest(
            question=request.question,
            context=AnswerReadContext(tenant_id="t2", user_id="u2"),
        ),
        SimpleReader(),
    )
    assert other.answer == ""
    assert other.public_reason != "premise_mismatch"


def test_adaptive_synthesize_premise_mismatch_abstention() -> None:
    evidence = [
        {
            "cid": "c1",
            "content": "User: I bought vinyl records on Bandcamp in San Francisco.",
        }
    ]
    # False premise: asking about purchases in Sacramento
    synth = adaptive_synthesize("What did I buy in Sacramento?", evidence)
    assert synth["abstained"] is True
    assert "Sacramento" in synth["answer"]
    assert "premise_verification" in synth


def test_verifier_semicolon_clause_splitting() -> None:
    verifier = PremiseConsistencyVerifier()
    evidence = [
        {
            "cid": "c1",
            "content": "User: Tom moved to Seattle; Alex graduated from MIT in June.",
        }
    ]
    res = verifier.verify("Who graduated first, Tom or Alex?", evidence_rows=evidence)
    assert res.is_consistent is False
    assert res.abstention_recommended is True
    assert "Tom" in (res.clean_abstention_text or "")
