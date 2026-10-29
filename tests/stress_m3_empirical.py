"""Empirical stress test suite for Milestone M3 verification.

Adversarially probes:
1. EventLedger multi-session counting and deduplication:
   - Identical items across 2 sessions (same month, no date, cross-month window).
   - Multiple items in 1 session (currency extraction, count phrase, short 2-char tokens).
   - Dual set-aggregation: strict core items vs borderline/accessory items across all taxonomy domains.
   - Unit contamination (activity count summed into monetary USD total).
2. PremiseConsistencyVerifier:
   - Location mismatch (Sacramento vs San Diego).
   - Role/title mismatch (Manager vs Senior Tech Lead, boundary capture).
   - Missing entity (pet hamster, cat, etc. when dog Buster is recorded).
   - Comparative counterfactual timeline (Tom vs Alex when neither participated, and passage co-occurrence).
   - Calibrated direct abstention.
3. Answering protocol:
   - Direct answering without hedging headers.
   - Greedy header stripping stress test ("Please note that...", "As an AI...").
4. Adaptive synthesize integration:
   - Intent routing for "how many" vs "how much spent".
"""

from __future__ import annotations

import sys
from typing import Any
from mnemosyne.answering import (
    _clean_hedging_headers,
    adaptive_synthesize,
    detect_synthesis_intent,
)
from mnemosyne.event_ledger import EventLedger
from mnemosyne.models import Assertion
from mnemosyne.premise_verifier import PremiseConsistencyVerifier


def run_tests() -> dict[str, Any]:
    results: dict[str, Any] = {"passed": 0, "defects_found": 0, "findings": []}

    print("=" * 70)
    print("STARTING EMPIRICAL STRESS TEST SUITE FOR MILESTONE M3")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # TEST SUITE 1: EventLedger Multi-Session Counting & Deduplication
    # -------------------------------------------------------------------------
    print("\n[SECTION 1] EventLedger Multi-Session Counting & Deduplication")

    # 1.1 Identical items across 2 sessions (same date / no date) -> MUST DEDUPLICATE
    ledger_nodate = EventLedger()
    ev_nodate = [
        {
            "cid": "c1",
            "session_id": "s1",
            "content": "User: I bought a bicycle for $500.",
        },
        {
            "cid": "c2",
            "session_id": "s2",
            "content": "User: Remember I bought a bicycle for $500.",
        },
    ]
    ledger_nodate.extract_from_evidence(ev_nodate)
    agg_nodate = ledger_nodate.aggregate("How many bikes did I buy?")
    if agg_nodate.strict_count == 1:
        print(
            "  [PASS] 1.1 Identical item across 2 sessions (no date) correctly deduplicated (count=1)."
        )
        results["passed"] += 1
    else:
        print(f"  [FAIL] 1.1 Deduplication failed: count={agg_nodate.strict_count}")
        results["defects_found"] += 1

    # 1.2 Identical items across 2 sessions with different months -> DEFECT INVESTIGATION
    ledger_cross_month = EventLedger()
    ev_cross_month = [
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
    ledger_cross_month.extract_from_evidence(ev_cross_month)
    agg_cross_month = ledger_cross_month.aggregate("How much did I spend on car care?")
    if agg_cross_month.strict_count == 2:
        print(
            f"  [DEFECT 1] Cross-month identical item double-counted! Strict count={agg_cross_month.strict_count}, sum=${agg_cross_month.strict_sum:.2f}"
        )
        results["defects_found"] += 1
        results["findings"].append(
            {
                "id": "DEFECT-1",
                "title": "Cross-month multi-session double counting",
                "detail": f"Items with identical entity across sessions in different months are assigned distinct canonical keys ({[e.canonical_key for e in agg_cross_month.strict_entries]}), double-counting sum to ${agg_cross_month.strict_sum:.2f}",
            }
        )
    else:
        print("  [PASS] 1.2 Cross-month identical item deduplicated.")
        results["passed"] += 1

    # 1.3 Multiple items in 1 session
    ledger_multi = EventLedger()
    ev_multi = [
        {
            "cid": "c1",
            "session_id": "s1",
            "content": "User: I bought a bicycle for $500, a helmet for $80, a bike lock for $45, and inner tubes for $25.",
        }
    ]
    multi_entries = ledger_multi.extract_from_evidence(ev_multi)
    if len(multi_entries) == 4:
        print(
            f"  [PASS] 1.3 Multiple items in 1 session extracted all {len(multi_entries)} items."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 1.3 Multiple items extraction missed items: count={len(multi_entries)}"
        )
        results["defects_found"] += 1

    # 1.4 Short 2-character token dropping (LP, EP, CD) -> DEFECT INVESTIGATION
    ledger_short = EventLedger()
    ev_short = [
        {"cid": "c1", "content": "User: I bought an LP for $25 and an EP for $10."}
    ]
    short_entries = ledger_short.extract_from_evidence(ev_short)
    if len(short_entries) == 0:
        print(
            "  [DEFECT 2] len(clean_ent) > 2 silently discards 2-letter tokens ('LP', 'EP', 'CD') defined in taxonomy!"
        )
        results["defects_found"] += 1
        results["findings"].append(
            {
                "id": "DEFECT-2",
                "title": "Short token entity dropping (len <= 2)",
                "detail": "clean_ent length check (len > 2) drops valid taxonomy keywords such as LP, EP, and CD.",
            }
        )
    else:
        print(f"  [PASS] 1.4 Short tokens extracted: count={len(short_entries)}")
        results["passed"] += 1

    # 1.5 Unit contamination in monetary aggregation -> DEFECT INVESTIGATION
    ledger_contam = EventLedger()
    ev_contam = [
        {"cid": "c1", "content": "User: I bought a bicycle for $500."},
        {"cid": "c2", "content": "User: I practiced cycling today."},
    ]
    ledger_contam.extract_from_evidence(ev_contam)
    agg_contam = ledger_contam.aggregate("How much did I spend on bike items?")
    if agg_contam.strict_sum == 501.0:
        print(
            f"  [DEFECT 3] Activity event count (value=1.0) contaminated monetary USD sum: ${agg_contam.strict_sum:.2f}"
        )
        results["defects_found"] += 1
        results["findings"].append(
            {
                "id": "DEFECT-3",
                "title": "Non-monetary activity value added into USD sum",
                "detail": f"EventLedger.aggregate sums all entry values when has_monetary is true, adding event counts into dollar sums: {agg_contam.synthesis_text}",
            }
        )
    else:
        print("  [PASS] 1.5 Unit isolation maintained.")
        results["passed"] += 1

    # 1.6 Dual set-aggregation: strict vs inclusive reporting
    ledger_dual = EventLedger()
    ev_dual = [
        {
            "cid": "c1",
            "content": "User: I bought a bicycle for $500.00, paid $120.00 for bike repairs, and bought inner tubes for $25.00. I also bought a cycling helmet for $80.00 and a bike lock for $45.00.",
        }
    ]
    ledger_dual.extract_from_evidence(ev_dual)
    agg_dual = ledger_dual.aggregate("How much did I spend on bike expenses?")
    if (
        agg_dual.strict_count == 3
        and agg_dual.inclusive_count == 5
        and "Strictly for core bike" in agg_dual.synthesis_text
    ):
        print(
            "  [PASS] 1.6 Dual set-aggregation formatted correctly (strict=3, inclusive=5)."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 1.6 Dual set-aggregation formatting failure: {agg_dual.synthesis_text}"
        )
        results["defects_found"] += 1

    # 1.7 Comma introductory clauses across sessions -> MUST DEDUPLICATE
    ledger_comma = EventLedger()
    ev_comma = [
        {
            "cid": "c1",
            "session_id": "s1",
            "content": "User: I bought a bicycle for $500.00.",
        },
        {
            "cid": "c2",
            "session_id": "s2",
            "content": "User: In March, I bought a bicycle for $500.00.",
        },
    ]
    ledger_comma.extract_from_evidence(ev_comma)
    agg_comma = ledger_comma.aggregate("How much did I spend on bikes?")
    if agg_comma.strict_count == 1 and agg_comma.strict_sum == 500.0:
        print(
            "  [PASS] 1.7 Introductory clause with comma correctly deduplicated (count=1, sum=$500.00)."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 1.7 Comma introductory clause deduplication failed: count={agg_comma.strict_count}, sum={agg_comma.strict_sum}"
        )
        results["defects_found"] += 1

    # 1.8 Standalone "CD" recognized in album taxonomy
    ledger_cd = EventLedger()
    ev_cd = [
        {"cid": "c1", "session_id": "s1", "content": "User: I bought a CD for $12.00."}
    ]
    ledger_cd.extract_from_evidence(ev_cd)
    agg_cd = ledger_cd.aggregate("How many albums did I buy?")
    if agg_cd.strict_count == 1 and "album" in ledger_cd.entries[0].category_tags:
        print(
            "  [PASS] 1.8 Standalone 'CD' correctly tagged in album taxonomy (count=1)."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 1.8 CD album taxonomy tagging failed: count={agg_cd.strict_count}, tags={ledger_cd.entries[0].category_tags if ledger_cd.entries else None}"
        )
        results["defects_found"] += 1

    # 1.9 Plural "CDs" tagging and category-specific query fallback avoidance
    ledger_cds = EventLedger()
    cds_tag = ledger_cds._tag_entity("CDs")
    ev_cds = [
        {"cid": "c1", "session_id": "s1", "content": "User: I bought a CD for $15.00."},
        {"cid": "c2", "session_id": "s2", "content": "User: Today is sunny."},
        {"cid": "c3", "session_id": "s3", "content": "User: How are you doing?"},
    ]
    resolved_cat = ledger_cds._resolve_target_category("How many CDs did I buy?")
    ans_cds = adaptive_synthesize("How many CDs did I buy?", evidence_rows=ev_cds)
    ev_zero = [
        {"cid": "c2", "session_id": "s2", "content": "User: Today is sunny."},
        {"cid": "c3", "session_id": "s3", "content": "User: How are you doing?"},
    ]
    ans_zero = adaptive_synthesize("How many CDs did I buy?", evidence_rows=ev_zero)
    if (
        "album" in cds_tag
        and resolved_cat == "album"
        and ans_cds.get("count") == 1
        and ans_zero.get("count") == 0
    ):
        print(
            "  [PASS] 1.9 Plural 'CDs' tagged as album, counts 1 CD without counting unrelated turns (0 on zero-match)."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 1.9 CDs test failed: cds_tag={cds_tag}, resolved={resolved_cat}, "
            f"count={ans_cds.get('count')}, zero_count={ans_zero.get('count')}"
        )
        results["defects_found"] += 1

    # -------------------------------------------------------------------------
    # TEST SUITE 2: PremiseConsistencyVerifier
    # -------------------------------------------------------------------------
    print("\n[SECTION 2] PremiseConsistencyVerifier")
    verifier = PremiseConsistencyVerifier()

    # 2.1 Location mismatch (Sacramento vs San Diego)
    ev_loc = [{"content": "User: I booked an Airbnb in San Diego for our summer trip."}]
    res_loc = verifier.verify(
        "When did I book the Airbnb in Sacramento?", evidence_rows=ev_loc
    )
    if (
        not res_loc.is_consistent
        and res_loc.abstention_recommended
        and "Sacramento" in (res_loc.clean_abstention_text or "")
        and "San Diego" in (res_loc.clean_abstention_text or "")
    ):
        print("  [PASS] 2.1 Location mismatch detected with calibrated abstention.")
        results["passed"] += 1
    else:
        print(f"  [FAIL] 2.1 Location mismatch check failed: {res_loc}")
        results["defects_found"] += 1

    # 2.2 Role/title mismatch (Software Engineer Manager vs Senior Tech Lead)
    ev_role = [{"content": "User: I was promoted to Senior Tech Lead at my company."}]
    res_role = verifier.verify(
        "How many engineers do I lead in my new role as Software Engineer Manager?",
        evidence_rows=ev_role,
    )
    if (
        not res_role.is_consistent
        and res_role.abstention_recommended
        and "Software Engineer Manager" in (res_role.clean_abstention_text or "")
    ):
        print("  [PASS] 2.2 Role/title mismatch detected with calibrated abstention.")
        results["passed"] += 1
    else:
        print(f"  [FAIL] 2.2 Role mismatch check failed: {res_role}")
        results["defects_found"] += 1

    # 2.3 Missing entity (pet hamster when dog Buster recorded)
    facts_pet = [
        Assertion(
            tenant_id="t", subject="user", predicate="family_pet", object="dog Buster"
        )
    ]
    ev_pet = [{"content": "User: I took Buster for a walk in the park."}]
    res_pet = verifier.verify(
        "What is the name of my pet hamster?", facts=facts_pet, evidence_rows=ev_pet
    )
    if (
        not res_pet.is_consistent
        and res_pet.abstention_recommended
        and "hamster" in (res_pet.clean_abstention_text or "")
    ):
        print(
            "  [PASS] 2.3 Missing entity (pet hamster) detected with clean abstention."
        )
        results["passed"] += 1
    else:
        print(f"  [FAIL] 2.3 Missing entity check failed: {res_pet}")
        results["defects_found"] += 1

    # 2.4 Comparative counterfactual timeline (Tom vs Alex when neither participated)
    ev_neither = [
        {
            "content": "User: Tom moved to Seattle last year. Alex started a new job in Boston."
        }
    ]
    res_comp = verifier.verify(
        "Who became a parent first, Tom or Alex?", evidence_rows=ev_neither
    )
    if (
        not res_comp.is_consistent
        and res_comp.abstention_recommended
        and "Neither Tom nor Alex" in (res_comp.clean_abstention_text or "")
    ):
        print(
            "  [PASS] 2.4 Comparative counterfactual (neither participated) cleanly abstained."
        )
        results["passed"] += 1
    else:
        print(f"  [FAIL] 2.4 Comparative counterfactual check failed: {res_comp}")
        results["defects_found"] += 1

    # 2.5 Comparative counterfactual co-occurrence false-positive -> DEFECT INVESTIGATION
    ev_cooccur = [
        {"content": "User: Tom moved to Seattle last year. Alex graduated from MIT."}
    ]
    res_cooccur = verifier.verify(
        "Who graduated first, Tom or Alex?", evidence_rows=ev_cooccur
    )
    if res_cooccur.is_consistent:
        print(
            "  [DEFECT 4] Comparative counterfactual false-positive! Passage containing both names and predicate causes verifier to claim both graduated."
        )
        results["defects_found"] += 1
        results["findings"].append(
            {
                "id": "DEFECT-4",
                "title": "Passage co-occurrence false-positive in comparative counterfactuals",
                "detail": "Verifier checks if entity name and predicate words exist anywhere in the same passage chunk, falsely concluding unparticipating entity did participate.",
            }
        )
    else:
        print("  [PASS] 2.5 Co-occurring passage counterfactual correctly flagged.")
        results["passed"] += 1

    # 2.6 Semicolon delimiter in comparative premise verifier
    ev_semi = [
        {"content": "User: Tom moved to Seattle; Alex graduated from MIT in June."}
    ]
    res_semi = verifier.verify(
        "Who graduated first, Tom or Alex?", evidence_rows=ev_semi
    )
    if (
        not res_semi.is_consistent
        and res_semi.abstention_recommended
        and "Tom" in (res_semi.clean_abstention_text or "")
    ):
        print(
            "  [PASS] 2.6 Semicolon-delimited comparative counterfactual correctly abstained."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 2.6 Semicolon delimiter check failed: is_consistent={res_semi.is_consistent}, abstention_recommended={res_semi.abstention_recommended}"
        )
        results["defects_found"] += 1

    # 2.7 Colon delimiter in entity label
    ev_colon = [{"content": "Tom: graduated in 2020; Alex: graduated in 2021."}]
    res_colon = verifier.verify(
        "Who graduated first, Tom or Alex?", evidence_rows=ev_colon
    )
    if res_colon.is_consistent and not res_colon.abstention_recommended:
        print(
            "  [PASS] 2.7 Colon transcript format in comparative premise verifier is consistent."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 2.7 Colon delimiter test failed: is_consistent={res_colon.is_consistent}, "
            f"abstention_recommended={res_colon.abstention_recommended}, text={res_colon.clean_abstention_text}"
        )
        results["defects_found"] += 1

    # -------------------------------------------------------------------------
    # TEST SUITE 3: Answering Protocol & Hedging Cleaner
    # -------------------------------------------------------------------------
    print("\n[SECTION 3] Answering Protocol & Hedging Cleaner")

    # 3.1 Standard hedging removal
    t_std = "Based on the provided chats, you have 2 bicycles."
    cleaned_std = _clean_hedging_headers(t_std)
    if cleaned_std == "You have 2 bicycles.":
        print("  [PASS] 3.1 Standard 'Based on...' hedging header stripped.")
        results["passed"] += 1
    else:
        print(f"  [FAIL] 3.1 Hedging strip failed: '{cleaned_std}'")
        results["defects_found"] += 1

    # 3.2 Greedy sentence obliteration -> DEFECT INVESTIGATION
    t_greedy = "Please note that your subscription expires tomorrow."
    cleaned_greedy = _clean_hedging_headers(t_greedy)
    if cleaned_greedy != "Your subscription expires tomorrow.":
        print(
            f"  [DEFECT 5] Greedy regex in _clean_hedging_headers obliterated entire sentence! '{t_greedy}' -> '{cleaned_greedy}'"
        )
        results["defects_found"] += 1
        results["findings"].append(
            {
                "id": "DEFECT-5",
                "title": "Greedy regex in _clean_hedging_headers destroys entire answer",
                "detail": f"Regex '^(?:Please note that|Note that)[^,\\n]*(?:,\\s*|\\s+)' greedily matches to the last space in the line, reducing '{t_greedy}' to '{cleaned_greedy}'",
            }
        )
    else:
        print("  [PASS] 3.2 'Please note that...' handled without sentence truncation.")
        results["passed"] += 1

    # -------------------------------------------------------------------------
    # TEST SUITE 4: Adaptive Synthesize Intent Routing
    # -------------------------------------------------------------------------
    print("\n[SECTION 4] Adaptive Synthesize Intent Routing")

    q_count = "How many bike items did I buy?"
    q_spend = "How much did I spend on bike expenses?"
    intent_count = detect_synthesis_intent(q_count)
    intent_spend = detect_synthesis_intent(q_spend)

    if intent_count == "count":
        print("  [PASS] 4.1 'How many...' correctly classified as count intent.")
        results["passed"] += 1
    else:
        print(f"  [FAIL] 4.1 'How many...' intent misclassified as '{intent_count}'.")
        results["defects_found"] += 1

    if intent_spend != "count":
        print(
            f"  [DEFECT 6] 'How much did I spend...' classified as '{intent_spend}', bypassing EventLedger in adaptive_synthesize!"
        )
        results["defects_found"] += 1
        results["findings"].append(
            {
                "id": "DEFECT-6",
                "title": "Spending queries bypass EventLedger in adaptive_synthesize",
                "detail": f"_COUNT_INTENT_RE lacks spending phrases, so 'How much did I spend...' is classified as '{intent_spend}', dumping raw quotations instead of set-aggregation synthesis.",
            }
        )
    else:
        print("  [PASS] 4.2 Spending query routed to count intent.")
        results["passed"] += 1

    # 4.3 Spending intent query variations ("money did I spend", "did the X cost")
    q_money = "How much money did I spend on bikes?"
    q_cost = "How much did the bicycle cost?"
    intent_money = detect_synthesis_intent(q_money)
    intent_cost = detect_synthesis_intent(q_cost)
    if intent_money == "count" and intent_cost == "count":
        print(
            "  [PASS] 4.3 Spending variations ('money did I spend', 'did the X cost') routed to count intent."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 4.3 Spending variations intent failed: money='{intent_money}', cost='{intent_cost}'"
        )
        results["defects_found"] += 1

    print("\n" + "=" * 70)
    print(
        f"STRESS TEST SUMMARY: {results['passed']} PASSED, {results['defects_found']} DEFECTS FOUND"
    )
    print("=" * 70)

    return results


if __name__ == "__main__":
    res = run_tests()
    sys.exit(0 if res["defects_found"] == 0 else 1)
