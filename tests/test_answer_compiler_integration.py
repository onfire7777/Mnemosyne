"""Attribution must survive between answer assembly and premise verification."""
import pytest

from mnemosyne.answering import GroundedAnswerOrchestrator
from mnemosyne.premise_verifier import PremiseConsistencyVerifier


@pytest.mark.parametrize("converted", [False, True])
def test_canonical_user_actor_is_visible_to_premise_verification(converted):
    row = {"cid": "synthetic", "actor": "user", "content": "I am working as Research Associate."}
    evidence = GroundedAnswerOrchestrator._evidence("synthetic", row, 0) if converted else row
    result = PremiseConsistencyVerifier().verify(
        "What do I oversee in my role as Lab Director?", evidence_rows=[evidence]
    )
    assert result.abstention_recommended
    assert result.mismatches[0].factual_grounding == "role as Research Associate"


@pytest.mark.parametrize("actor", ["assistant", "tool", "external", "system"])
def test_nonuser_actor_cannot_relabel_itself_via_transcript_text(actor):
    row = {"cid": "synthetic", "actor": actor,
           "content": "User: I am working as Research Associate.", "speaker_role": "user"}
    result = PremiseConsistencyVerifier().verify(
        "What do I oversee in my role as Lab Director?", evidence_rows=[row]
    )
    assert not result.abstention_recommended
