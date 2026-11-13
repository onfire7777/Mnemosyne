"""Unit tests for EventLedger and SetAggregation synthesis."""

import pytest
from mnemosyne.answering import adaptive_synthesize
from mnemosyne.event_ledger import EventLedger, EventLedgerEntry, SetAggregationResult


def test_event_ledger_entry_dataclass() -> None:
    entry = EventLedgerEntry(
        entry_id="e1",
        session_id="s1",
        session_date="2026-05-01",
        event_date="2026-05-01",
        speaker_role="user",
        action="purchase",
        entity="desk lamp",
        canonical_key="desk lamp_2026-05",
        value=65.0,
        unit="USD",
        category_tags=("lamp",),
        is_borderline=False,
        borderline_reason=None,
        evidence_cid="cid1",
        quote_span="bought a desk lamp for $65.00",
    )
    assert entry.entity == "desk lamp"
    assert entry.value == 65.0
    d = entry.to_dict()
    assert d["entry_id"] == "e1"
    assert d["action"] == "purchase"
    with pytest.raises(AttributeError):
        entry.entity = "new name"  # frozen


def test_set_aggregation_result_dataclass() -> None:
    res = SetAggregationResult(
        query="How much did I spend on lamp?",
        target_category="lamp",
        total_entries_found=2,
        strict_entries=(),
        borderline_entries=(),
        strict_count=0,
        inclusive_count=0,
        strict_sum=0.0,
        inclusive_sum=0.0,
        unit="USD",
        synthesis_text="No records found",
    )
    assert res.target_category == "lamp"
    d = res.to_dict()
    assert d["total_entries_found"] == 2
    assert d["unit"] == "USD"


def test_ledger_extraction_purchases_and_expenses() -> None:
    ledger = EventLedger()
    evidence = [
        {
            "cid": "c1",
            "session_id": "sess_1",
            "created_at": "2026-04-10T12:00:00Z",
            "content": "User: I bought a desk lamp for $65.00 and picked up printer paper for $20.50.",
        },
        {
            "cid": "c2",
            "session_id": "sess_2",
            "created_at": "2026-04-15T15:00:00Z",
            "content": "User: I spent $500 on a standing desk and paid $120 for chair repairs.",
        },
    ]
    entries = ledger.extract_from_evidence(evidence)
    assert len(entries) >= 4
    entities = [e.entity.lower() for e in entries]
    assert any("desk lamp" in ent for ent in entities)
    assert any("printer paper" in ent for ent in entities)
    assert any("standing desk" in ent for ent in entities)
    assert any("chair repairs" in ent for ent in entities)


def test_ledger_filters_assistant_turns() -> None:
    ledger = EventLedger()
    evidence = [
        {
            "cid": "c1",
            "session_id": "sess_1",
            "content": (
                "Assistant: You could buy a yacht for $250000.\n"
                "User: No thanks, I bought a used bicycle for $150."
            ),
        }
    ]
    entries = ledger.extract_from_evidence(evidence)
    entities = [e.entity.lower() for e in entries]
    assert not any("yacht" in ent for ent in entities)
    assert any("bicycle" in ent for ent in entities)


def test_ledger_cross_session_deduplication() -> None:
    ledger = EventLedger()
    evidence = [
        {
            "cid": "c1",
            "session_id": "sess_1",
            "created_at": "2026-03-01",
            "content": "User: I bought Radiohead OK Computer on vinyl for $30.",
        },
        {
            "cid": "c2",
            "session_id": "sess_2",
            "created_at": "2026-03-05",
            "content": "User: Remember I bought Radiohead OK Computer on vinyl.",
        },
    ]
    entries = ledger.extract_from_evidence(evidence)
    # Both refer to OK Computer in March 2026; should deduplicate to 1 entry
    ok_entries = [e for e in entries if "ok computer" in e.canonical_key]
    assert len(ok_entries) == 1
    assert ok_entries[0].value == 30.0


def test_ledger_activity_and_count_extraction() -> None:
    ledger = EventLedger()
    evidence = [
        {
            "cid": "c1",
            "session_id": "sess_1",
            "content": "User: I played pickleball at the club and learned pottery this weekend.",
        },
        {
            "cid": "c2",
            "session_id": "sess_2",
            "content": "User: I have three jigsaw puzzles waiting to be built.",
        },
    ]
    entries = ledger.extract_from_evidence(evidence)
    actions = [e.action for e in entries]
    assert "activity" in actions or "item" in actions
    pickleball = [e for e in entries if "pickleball" in e.entity.lower()]
    assert len(pickleball) == 1
    puzzles = [e for e in entries if "jigsaw puzzle" in e.entity.lower()]
    assert len(puzzles) == 1
    assert puzzles[0].value == 3.0


def test_adaptive_synthesize_integration_with_event_ledger() -> None:
    evidence = [
        {
            "cid": "c1",
            "session_id": "s1",
            "content": "User: I bought a desk lamp for $65.00.",
        },
        {
            "cid": "c2",
            "session_id": "s2",
            "content": "User: I bought a reading lamp for $20.50.",
        },
    ]
    synth = adaptive_synthesize("How much did I spend on lamp?", evidence)
    assert synth["intent"] == "count"
    assert not synth["abstained"]
    assert synth["count"] == 2
    assert "claims" in synth
    assert len(synth["claims"]) == 1
    claim = synth["claims"][0]
    assert "85.50" in claim["text"] or "2" in claim["text"]
    assert "set_aggregation" in claim["derivation"]
    agg_dict = claim["derivation"]["set_aggregation"]
    assert agg_dict["strict_count"] == 2
    assert agg_dict["inclusive_count"] == 2


def test_ledger_two_letter_taxonomy_tokens() -> None:
    ledger = EventLedger()
    evidence = [
        {"cid": "c1", "content": "User: I bought an LP for $25 and an EP for $10."}
    ]
    entries = ledger.extract_from_evidence(evidence)
    assert len(entries) == 2
    entities = [e.entity.lower() for e in entries]
    assert "lp" in entities
    assert "ep" in entities
    # Two-letter terms match whole words only: "lp" must not match "ep".
    agg = ledger.aggregate("x", target_category="lp")
    assert agg.strict_count == 1
    assert agg.strict_sum == 25.0


def test_ledger_cross_month_deduplication() -> None:
    ledger = EventLedger()
    evidence = [
        {
            "cid": "c1",
            "session_id": "s1",
            "created_at": "2026-03-10",
            "content": "User: I bought a desk lamp for $65.00.",
        },
        {
            "cid": "c2",
            "session_id": "s2",
            "created_at": "2026-04-10",
            "content": "User: Remember I bought a desk lamp for $65.00.",
        },
    ]
    ledger.extract_from_evidence(evidence)
    agg = ledger.aggregate("How much did I spend on lamp?")
    assert agg.strict_count == 1
    assert agg.strict_sum == 65.0


def test_ledger_monetary_unit_hygiene() -> None:
    ledger = EventLedger()
    evidence = [
        {"cid": "c1", "content": "User: I bought a bicycle for $500."},
        {"cid": "c2", "content": "User: I practiced cycling today."},
    ]
    ledger.extract_from_evidence(evidence)
    agg = ledger.aggregate("How much did I spend on bicycle?")
    assert agg.strict_sum == 500.0


def test_adaptive_synthesize_spending_intent() -> None:
    evidence = [
        {
            "cid": "c1",
            "session_id": "s1",
            "content": "User: I bought a bicycle for $500.",
        },
    ]
    synth = adaptive_synthesize("How much did I spend on bicycle?", evidence)
    assert synth["intent"] == "count"
    assert not synth["abstained"]
    assert len(synth["claims"]) >= 1
    assert "$500.00" in synth["claims"][0]["text"]

    synth_money = adaptive_synthesize(
        "How much money did I spend on bicycle?", evidence
    )
    assert synth_money["intent"] == "count"
    assert not synth_money["abstained"]

    synth_cost = adaptive_synthesize("How much did the bicycle cost?", evidence)
    assert synth_cost["intent"] == "count"
    assert not synth_cost["abstained"]


def test_ledger_comma_introductory_clause_deduplication() -> None:
    ledger = EventLedger()
    evidence = [
        {"cid": "c1", "content": "User: I bought a bicycle for $500.00."},
        {"cid": "c2", "content": "User: In March, I bought a bicycle for $500.00."},
    ]
    ledger.extract_from_evidence(evidence)
    agg = ledger.aggregate("How much did I spend on bicycle?")
    assert agg.strict_count == 1
    assert agg.strict_sum == 500.0
