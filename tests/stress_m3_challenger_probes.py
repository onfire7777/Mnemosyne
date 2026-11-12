"""Adversarial stress and edge-case probes for Milestone M3 Iteration 3 remediations.

Executed by challenger_m3_it3_19 to verify fixes and uncover subtle boundary defects.
"""

from __future__ import annotations

import sys
from mnemosyne.answering import adaptive_synthesize, detect_synthesis_intent
from mnemosyne.event_ledger import EventLedger
from mnemosyne.premise_verifier import PremiseConsistencyVerifier


def run_probes() -> dict[str, int]:
    results = {"passed": 0, "failed": 0}
    print("=" * 70)
    print("STARTING ADVERSARIAL STRESS PROBES: CHALLENGER M3 ITERATION 3")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # PROBE 1: Comma introductory clauses & multi-session deduplication
    # -------------------------------------------------------------------------
    print("\n[PROBE 1] Comma Introductory Clauses Multi-Session Deduplication")
    ev1 = [
        {
            "cid": "c1",
            "session_id": "s1",
            "content": "User: I bought a bicycle for $500.00.",
        },
        {
            "cid": "c2",
            "session_id": "s2",
            "content": "User: Last month, I ordered a bicycle for $500.00.",
        },
        {
            "cid": "c3",
            "session_id": "s3",
            "content": "User: In 2024, I purchased a bicycle for $500.00.",
        },
        {
            "cid": "c4",
            "session_id": "s4",
            "content": "User: Remember, I bought a bicycle for $500.00.",
        },
        {
            "cid": "c5",
            "session_id": "s5",
            "content": "User: Historically, I bought a bicycle for $500.00.",
        },
        {
            "cid": "c6",
            "session_id": "s6",
            "content": "User: As discussed, I ordered a bicycle for $500.00.",
        },
    ]
    ledger1 = EventLedger()
    ledger1.extract_from_evidence(ev1)
    agg1 = ledger1.aggregate("How much did I spend on bikes?")
    if (
        len(ledger1.entries) == 1
        and agg1.strict_count == 1
        and agg1.strict_sum == 500.0
    ):
        print(
            "  [PASS] 1.1 All 6 introductory clauses successfully deduplicated into 1 bicycle entry ($500.00)."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 1.1 Deduplication failure: entries={len(ledger1.entries)}, count={agg1.strict_count}, sum={agg1.strict_sum}"
        )
        results["failed"] += 1

    # -------------------------------------------------------------------------
    # PROBE 2: Taxonomy token "CD" vs "CDs" and false positive protection
    # -------------------------------------------------------------------------
    print("\n[PROBE 2] Taxonomy Token 'CD' / 'CDs' and False Positive Validation")
    ledger2 = EventLedger()

    # 2.1 False positive validation on non-album words
    fp_words = [
        "broadcast",
        "accredit",
        "anecdote",
        "broadcasting equipment",
        "succeed",
    ]
    fp_detected = [w for w in fp_words if "album" in ledger2._tag_entity(w)]
    if not fp_detected:
        print(
            "  [PASS] 2.1 No false positives on words containing cd substrings ('broadcast', 'accredit', etc.)."
        )
        results["passed"] += 1
    else:
        print(f"  [FAIL] 2.1 False positives detected in album taxonomy: {fp_detected}")
        results["failed"] += 1

    # 2.2 Singular CD and cd album tagging
    cd_singular_tag = ledger2._tag_entity("CD")
    cd_album_tag = ledger2._tag_entity("cd album")
    if "album" in cd_singular_tag and "album" in cd_album_tag:
        print(
            "  [PASS] 2.2 Singular 'CD' and 'cd album' correctly tagged with ('album',)."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 2.2 Tagging failed: CD={cd_singular_tag}, cd album={cd_album_tag}"
        )
        results["failed"] += 1

    # 2.3 Plural CDs tagging in ledger entries (DEFECT CHECK)
    cds_tag = ledger2._tag_entity("CDs")
    ev2_cds = [{"cid": "c1", "content": "User: I bought CDs for $20.00."}]
    l2_cds = EventLedger()
    l2_cds.extract_from_evidence(ev2_cds)
    agg2_cds = l2_cds.aggregate("How many albums did I buy?")
    if "album" in cds_tag and agg2_cds.strict_count == 1:
        print(
            "  [PASS] 2.3 Plural 'CDs' correctly tagged and counted under album taxonomy."
        )
        results["passed"] += 1
    else:
        print(
            f"  [DEFECT-1A] Plural 'CDs' missing from album taxonomy: tag={cds_tag}, albums count={agg2_cds.strict_count}"
        )
        results["failed"] += 1

    # 2.4 Query category resolution with CDs (DEFECT CHECK)
    ev2_query = [
        {"cid": "c1", "session_id": "s1", "content": "User: I bought a CD for $15.00."},
        {"cid": "c2", "session_id": "s2", "content": "User: Today is sunny."},
        {"cid": "c3", "session_id": "s3", "content": "User: How are you doing?"},
    ]
    resolved_cat = ledger2._resolve_target_category("How many CDs did I buy?")
    ans2_cds = adaptive_synthesize("How many CDs did I buy?", evidence_rows=ev2_query)
    if resolved_cat == "album" and ans2_cds.get("count") == 1:
        print(
            "  [PASS] 2.4 'How many CDs did I buy?' resolves to album category with count=1."
        )
        results["passed"] += 1
    else:
        print(
            f"  [DEFECT-1B] Category resolution failed for 'How many CDs did I buy?': resolved='{resolved_cat}', synth count={ans2_cds.get('count')} (hallucinated {ans2_cds.get('count')} turns as CDs)"
        )
        results["failed"] += 1

    # 2.5 Zero-match category-specific query does not count unrelated turns
    ev2_zero = [
        {"cid": "c1", "session_id": "s1", "content": "User: Today is sunny."},
        {"cid": "c2", "session_id": "s2", "content": "User: How are you doing?"},
    ]
    ans2_zero = adaptive_synthesize("How many CDs did I buy?", evidence_rows=ev2_zero)
    if ans2_zero.get("count") == 0 and "No records found" in ans2_zero.get(
        "answer", ""
    ):
        print(
            "  [PASS] 2.5 Zero-match category count does not hallucinate turns as items (count=0)."
        )
        results["passed"] += 1
    else:
        print(
            f"  [DEFECT-1C] Zero-match category query hallucinated count={ans2_zero.get('count')}, answer='{ans2_zero.get('answer')}'"
        )
        results["failed"] += 1

    # -------------------------------------------------------------------------
    # PROBE 3: Semicolons and Colons in Premise Consistency Verifier
    # -------------------------------------------------------------------------
    print("\n[PROBE 3] Semicolons and Colons in Premise Consistency Verifier")
    verifier = PremiseConsistencyVerifier()

    # 3.1 Semicolon separation between two clauses
    ev3_semi = [{"content": "Priya studied; Marcus graduated from Rice in June."}]
    res3_semi = verifier.verify(
        "Who graduated first, Priya or Marcus?", evidence_rows=ev3_semi
    )
    if (
        not res3_semi.is_consistent
        and res3_semi.abstention_recommended
        and "Priya" in (res3_semi.clean_abstention_text or "")
    ):
        print(
            "  [PASS] 3.1 Semicolon correctly splits clauses; abstains when only Marcus graduated."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 3.1 Semicolon splitting failure: is_consistent={res3_semi.is_consistent}"
        )
        results["failed"] += 1

    # 3.2 Colon delimiter in entity label (DEFECT CHECK)
    ev3_colon = [{"content": "Priya: graduated in 2020; Marcus: graduated in 2021."}]
    res3_colon = verifier.verify(
        "Who graduated first, Priya or Marcus?", evidence_rows=ev3_colon
    )
    if res3_colon.is_consistent and not res3_colon.abstention_recommended:
        print(
            "  [PASS] 3.2 Colon in entity labels does not separate subject from predicate."
        )
        results["passed"] += 1
    else:
        print(
            f"  [DEFECT-2] Colon in entity label splits name from verb: is_consistent={res3_colon.is_consistent}, abstention_text='{res3_colon.clean_abstention_text}'"
        )
        results["failed"] += 1

    # -------------------------------------------------------------------------
    # PROBE 4: Spending intent variations
    # -------------------------------------------------------------------------
    print("\n[PROBE 4] Spending Intent Variations")
    spending_queries = [
        "How much money did I spend on bikes?",
        "How much did the wiper blades cost?",
        "What did the bicycle cost?",
        "What did it cost?",
        "Total spent on groceries",
        "How much was spent on books?",
        "How much did I pay for the laptop?",
        "What did I pay for the tickets?",
        "Total cost of bike repairs",
        "Spending on books",
        "What was the total expenditure on books?",
    ]
    all_count = all(detect_synthesis_intent(q) == "count" for q in spending_queries)
    if all_count:
        print(
            f"  [PASS] 4.1 All {len(spending_queries)} spending phrasing variations routed to 'count' intent."
        )
        results["passed"] += 1
    else:
        unmatched = [
            q for q in spending_queries if detect_synthesis_intent(q) != "count"
        ]
        print(f"  [FAIL] 4.1 Spending variations failed routing: {unmatched}")
        results["failed"] += 1

    # End-to-end spending synthesis test
    ev4_synth = [
        {"cid": "c1", "session_id": "s1", "content": "User: The bicycle cost $450.00."}
    ]
    ans4 = adaptive_synthesize(
        "How much did the bicycle cost?", evidence_rows=ev4_synth
    )
    claim_text = ans4.get("claims", [{}])[0].get("text", "")
    if "$450.00" in claim_text:
        print(
            "  [PASS] 4.2 End-to-end spending synthesis correctly extracts and reports cost ($450.00)."
        )
        results["passed"] += 1
    else:
        print(f"  [FAIL] 4.2 Spending synthesis failed: {claim_text}")
        results["failed"] += 1

    print("\n" + "=" * 70)
    print(
        f"PROBE SUMMARY: {results['passed']} PASSED, {results['failed']} DEFECTS DETECTED"
    )
    print("=" * 70)
    return results


if __name__ == "__main__":
    res = run_probes()
    sys.exit(0 if res["failed"] == 0 else 1)
