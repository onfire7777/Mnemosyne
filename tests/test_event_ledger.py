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
        entity="car cover",
        canonical_key="car cover_2026-05",
        value=65.0,
        unit="USD",
        category_tags=("car",),
        is_borderline=False,
        borderline_reason=None,
        evidence_cid="cid1",
        quote_span="bought a car cover for $65.00",
    )
    assert entry.entity == "car cover"
    assert entry.value == 65.0
    d = entry.to_dict()
    assert d["entry_id"] == "e1"
    assert d["action"] == "purchase"
    with pytest.raises(AttributeError):
        entry.entity = "new name"  # frozen


def test_set_aggregation_result_dataclass() -> None:
    res = SetAggregationResult(
        query="How much did I spend on car care?",
        target_category="car",
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
    assert res.target_category == "car"
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
            "content": "User: I bought a car cover for $65.00 and picked up detailing spray for $20.50.",
        },
        {
            "cid": "c2",
            "session_id": "sess_2",
            "created_at": "2026-04-15T15:00:00Z",
            "content": "User: I spent $500 on a mountain bike and paid $120 for bike repairs.",
        },
    ]
    entries = ledger.extract_from_evidence(evidence)
    assert len(entries) >= 4
    entities = [e.entity.lower() for e in entries]
    assert any("car cover" in ent for ent in entities)
    assert any("detailing spray" in ent for ent in entities)
    assert any("mountain bike" in ent for ent in entities)
    assert any("bike repairs" in ent for ent in entities)


def test_ledger_filters_assistant_turns() -> None:
    ledger = EventLedger()
    evidence = [
        {
            "cid": "c1",
            "session_id": "sess_1",
            "content": (
                "Assistant: You could buy a Ferrari for $250000.\n"
                "User: No thanks, I bought a used bicycle for $150."
            ),
        }
    ]
    entries = ledger.extract_from_evidence(evidence)
    entities = [e.entity.lower() for e in entries]
    assert not any("ferrari" in ent for ent in entities)
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
            "content": "User: I played tennis at the club and learned Italian cooking this weekend.",
        },
        {
            "cid": "c2",
            "session_id": "sess_2",
            "content": "User: I have three model kits waiting to be built.",
        },
    ]
    entries = ledger.extract_from_evidence(evidence)
    actions = [e.action for e in entries]
    assert "activity" in actions or "item" in actions
    tennis = [e for e in entries if "tennis" in e.entity.lower()]
    assert len(tennis) == 1
    model_kits = [e for e in entries if "model kit" in e.entity.lower()]
    assert len(model_kits) == 1
    assert model_kits[0].value == 3.0


def test_dual_set_aggregation_strict_equals_inclusive() -> None:
    ledger = EventLedger()
    evidence = [
        {
            "cid": "c1",
            "session_id": "sess_1",
            "content": "User: I bought a car cover for $65.00 and detailing spray for $20.50.",
        }
    ]
    ledger.extract_from_evidence(evidence)
    agg = ledger.aggregate("How much did I spend on car care?")
    assert agg.strict_count == 2
    assert agg.inclusive_count == 2
    assert agg.strict_sum == 85.50
    assert agg.inclusive_sum == 85.50
    # Single total formatting
    assert "You spent $85.50" in agg.synthesis_text
    assert "car cover" in agg.synthesis_text
    assert "detailing spray" in agg.synthesis_text


def test_dual_set_aggregation_strict_less_than_inclusive() -> None:
    ledger = EventLedger()
    evidence = [
        {
            "cid": "c1",
            "session_id": "sess_1",
            "content": (
                "User: I bought a bicycle for $500.00, paid $120.00 for bike repairs, "
                "and bought inner tubes for $25.00. I also bought a cycling helmet for $80.00 "
                "and a bike lock for $45.00."
            ),
        }
    ]
    ledger.extract_from_evidence(evidence)
    agg = ledger.aggregate("How much did I spend on bike expenses?")
    assert agg.strict_count == 3  # bicycle, repairs, tubes
    assert agg.inclusive_count == 5  # helmet, lock included
    assert agg.strict_sum == 645.00
    assert agg.inclusive_sum == 770.00
    assert len(agg.borderline_entries) == 2
    assert all(e.is_borderline for e in agg.borderline_entries)
    # Dual reporting formatting
    assert "Strictly for core bike" in agg.synthesis_text
    assert "$645.00" in agg.synthesis_text
    assert "$770.00" in agg.synthesis_text
    assert "accessories and related gear" in agg.synthesis_text


def test_adaptive_synthesize_integration_with_event_ledger() -> None:
    evidence = [
        {
            "cid": "c1",
            "session_id": "s1",
            "content": "User: I bought a car cover for $65.00.",
        },
        {
            "cid": "c2",
            "session_id": "s2",
            "content": "User: I bought detailing spray for $20.50.",
        },
    ]
    synth = adaptive_synthesize("How many car care items did I buy?", evidence)
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
    agg = ledger.aggregate("How many albums did I buy?")
    assert agg.strict_count == 1
    assert agg.inclusive_count == 2
    assert agg.strict_sum == 25.0
    assert agg.inclusive_sum == 35.0


def test_ledger_cross_month_deduplication() -> None:
    ledger = EventLedger()
    evidence = [
        {
            "cid": "c1",
            "session_id": "s1",
            "created_at": "2026-03-10",
            "content": "User: I bought a car cover for $65.00.",
        },
        {
            "cid": "c2",
            "session_id": "s2",
            "created_at": "2026-04-10",
            "content": "User: Remember I bought a car cover for $65.00.",
        },
    ]
    ledger.extract_from_evidence(evidence)
    agg = ledger.aggregate("How much did I spend on car care?")
    assert agg.strict_count == 1
    assert agg.strict_sum == 65.0


def test_ledger_monetary_unit_hygiene() -> None:
    ledger = EventLedger()
    evidence = [
        {"cid": "c1", "content": "User: I bought a bicycle for $500."},
        {"cid": "c2", "content": "User: I practiced cycling today."},
    ]
    ledger.extract_from_evidence(evidence)
    agg = ledger.aggregate("How much did I spend on bike items?")
    assert agg.strict_sum == 500.0


def test_adaptive_synthesize_spending_intent() -> None:
    evidence = [
        {
            "cid": "c1",
            "session_id": "s1",
            "content": "User: I bought a bicycle for $500.",
        },
    ]
    synth = adaptive_synthesize("How much did I spend on bike items?", evidence)
    assert synth["intent"] == "count"
    assert not synth["abstained"]
    assert len(synth["claims"]) >= 1
    assert "$500.00" in synth["claims"][0]["text"]

    synth_money = adaptive_synthesize(
        "How much money did I spend on bike items?", evidence
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
    agg = ledger.aggregate("How much did I spend on bikes?")
    assert agg.strict_count == 1
    assert agg.strict_sum == 500.0


def test_ledger_cd_album_taxonomy() -> None:
    ledger = EventLedger()
    evidence = [{"cid": "c1", "content": "User: I bought a CD for $12.00."}]
    ledger.extract_from_evidence(evidence)
    assert len(ledger.entries) == 1
    assert "album" in ledger.entries[0].category_tags
    agg = ledger.aggregate("How many albums did I buy?")
    assert agg.strict_count == 1
    assert agg.strict_sum == 12.0
