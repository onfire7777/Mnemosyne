"""Empirical challenger probes for Milestone M3 Iteration 4 verification.

Executed by challenger_m3_it4_19 to adversarially probe:
1. Plural forms & false positive protection:
   - "CDs", "LPs", "EPs", "records", "albums" category matching
   - False positive protection on substring-containing words ("accredit", "succeed", "help", "step", etc.)
   - Set aggregation over 5 distinct album types (strict=4, inclusive=5)
2. Zero-match & single-match count queries in adaptive_synthesize:
   - Zero-match queries on unrelated turns guarantee count=0 (no turn hallucination)
   - Single-match queries on target item + unrelated turns guarantee count=1
3. Punctuation variants in comparative premise verification:
   - Colons in speaker tags and entity labels
   - Semicolons dividing independent clauses
   - Dashes, question marks, and exclamation marks
"""

from __future__ import annotations

import sys
from mnemosyne.answering import adaptive_synthesize
from mnemosyne.event_ledger import EventLedger
from mnemosyne.premise_verifier import PremiseConsistencyVerifier


def run_it4_probes() -> dict[str, int]:
    results = {"passed": 0, "failed": 0}
    print("=" * 70)
    print("STARTING ITERATION 4 ADVERSARIAL CHALLENGER PROBES")
    print("=" * 70)

    # =========================================================================
    # SUITE 1: Plural forms, category matching & false positive protection
    # =========================================================================
    print("\n[SUITE 1] Plural Forms, Category Matching & False Positive Protection")
    ledger = EventLedger()

    # 1.1 Category tagging for all 5 album forms (singular & plural)
    target_album_forms = [
        "CD",
        "CDs",
        "LP",
        "LPs",
        "EP",
        "EPs",
        "record",
        "records",
        "album",
        "albums",
    ]
    tag_failures = []
    for term in target_album_forms:
        tags = ledger._tag_entity(term)
        if "album" not in tags:
            tag_failures.append((term, tags))

    if not tag_failures:
        print(
            f"  [PASS] 1.1 All {len(target_album_forms)} album forms (singular & plural) correctly tagged with ('album',)."
        )
        results["passed"] += 1
    else:
        print(f"  [FAIL] 1.1 Tagging failed for forms: {tag_failures}")
        results["failed"] += 1

    # 1.2 False positive validation on substring-containing non-album words
    fp_words = [
        "broadcast",
        "accredit",
        "anecdote",
        "broadcasting equipment",
        "succeed",
        "help",
        "kelp",
        "dolphin",
        "alpaca",
        "calpurnia",
        "step",
        "sleep",
        "creep",
        "epoch",
        "repay",
        "stepfather",
    ]
    fp_hits = [w for w in fp_words if "album" in ledger._tag_entity(w)]
    if not fp_hits:
        print(
            f"  [PASS] 1.2 No false positives detected across {len(fp_words)} substring-containing non-album words."
        )
        results["passed"] += 1
    else:
        print(f"  [FAIL] 1.2 False positives detected in album taxonomy: {fp_hits}")
        results["failed"] += 1

    # 1.3 Dual set-aggregation across all 5 album types (singular)
    ev_all_singular = [
        {"cid": "c1", "session_id": "s1", "content": "User: I bought a CD for $15.00."},
        {
            "cid": "c2",
            "session_id": "s2",
            "content": "User: I bought an LP for $25.00.",
        },
        {
            "cid": "c3",
            "session_id": "s3",
            "content": "User: I bought a record for $30.00.",
        },
        {
            "cid": "c4",
            "session_id": "s4",
            "content": "User: I bought an album for $20.00.",
        },
        {
            "cid": "c5",
            "session_id": "s5",
            "content": "User: I bought an EP for $10.00.",
        },
    ]
    l_sing = EventLedger()
    l_sing.extract_from_evidence(ev_all_singular)
    agg_sing = l_sing.aggregate("How many albums did I buy?")
    if (
        agg_sing.strict_count == 4
        and agg_sing.inclusive_count == 5
        and agg_sing.strict_sum == 90.0
        and agg_sing.inclusive_sum == 100.0
    ):
        print(
            "  [PASS] 1.3 Singular album items aggregated correctly (strict=4 ($90.00), inclusive=5 ($100.00))."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 1.3 Singular album aggregation failed: strict={agg_sing.strict_count} (${agg_sing.strict_sum}), inclusive={agg_sing.inclusive_count} (${agg_sing.inclusive_sum})"
        )
        results["failed"] += 1

    # 1.4 Dual set-aggregation across all 5 album types (plural)
    ev_all_plural = [
        {"cid": "c1", "session_id": "s1", "content": "User: I bought CDs for $15.00."},
        {"cid": "c2", "session_id": "s2", "content": "User: I bought LPs for $25.00."},
        {
            "cid": "c3",
            "session_id": "s3",
            "content": "User: I bought records for $30.00.",
        },
        {
            "cid": "c4",
            "session_id": "s4",
            "content": "User: I bought albums for $20.00.",
        },
        {"cid": "c5", "session_id": "s5", "content": "User: I bought EPs for $10.00."},
    ]
    l_plur = EventLedger()
    l_plur.extract_from_evidence(ev_all_plural)
    agg_plur = l_plur.aggregate("How many albums did I buy?")
    if (
        agg_plur.strict_count == 4
        and agg_plur.inclusive_count == 5
        and agg_plur.strict_sum == 90.0
        and agg_plur.inclusive_sum == 100.0
    ):
        print(
            "  [PASS] 1.4 Plural album items aggregated correctly (strict=4 ($90.00), inclusive=5 ($100.00))."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 1.4 Plural album aggregation failed: strict={agg_plur.strict_count} (${agg_plur.strict_sum}), inclusive={agg_plur.inclusive_count} (${agg_plur.inclusive_sum})"
        )
        results["failed"] += 1

    # =========================================================================
    # SUITE 2: Zero-match and Single-match Count Queries in adaptive_synthesize
    # =========================================================================
    print(
        "\n[SUITE 2] Zero-Match and Single-Match Count Queries in adaptive_synthesize"
    )

    unrelated_turns = [
        {
            "cid": "u1",
            "session_id": "s1",
            "content": "User: The weather is quite sunny today.",
        },
        {
            "cid": "u2",
            "session_id": "s2",
            "content": "User: I am continuing work on our memory system.",
        },
        {
            "cid": "u3",
            "session_id": "s3",
            "content": "User: Let us schedule the sprint planning meeting for next Tuesday.",
        },
    ]

    count_test_cases = [
        ("How many CDs did I buy?", "User: I bought a CD for $15.00.", "album", 15.0),
        ("How many LPs did I buy?", "User: I bought an LP for $25.00.", "album", 25.0),
        (
            "How many records did I buy?",
            "User: I bought a record for $30.00.",
            "album",
            30.0,
        ),
        (
            "How many albums did I buy?",
            "User: I bought an album for $20.00.",
            "album",
            20.0,
        ),
        (
            "How many bicycles did I buy?",
            "User: I bought a bicycle for $500.00.",
            "bike",
            500.0,
        ),
        (
            "How many cars did I buy?",
            "User: I bought a car for $20000.00.",
            "car",
            20000.0,
        ),
    ]

    # 2.1 Zero-match queries over unrelated conversational turns
    zero_match_failures = []
    for query, _, _, _ in count_test_cases:
        ans = adaptive_synthesize(query, evidence_rows=unrelated_turns)
        cnt = ans.get("count")
        text = ans.get("answer", "")
        if cnt != 0 or "No records found" not in text:
            zero_match_failures.append((query, cnt, text))

    if not zero_match_failures:
        print(
            f"  [PASS] 2.1 All {len(count_test_cases)} category count queries returned count=0 and 'No records found' on unrelated turns."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 2.1 Zero-match query hallucinated counts: {zero_match_failures}"
        )
        results["failed"] += 1

    # 2.2 Single-match queries (target purchase + 3 unrelated conversational turns)
    single_match_failures = []
    for query, matching_turn, _, expected_cost in count_test_cases:
        ev_single = [
            {"cid": "m0", "session_id": "s0", "content": matching_turn}
        ] + unrelated_turns
        ans = adaptive_synthesize(query, evidence_rows=ev_single)
        cnt = ans.get("count")
        text = ans.get("answer", "")
        cost_str = f"${expected_cost:.2f}"
        if cnt != 1 or cost_str not in text:
            single_match_failures.append((query, cnt, text))

    if not single_match_failures:
        print(
            f"  [PASS] 2.2 All {len(count_test_cases)} single-match queries correctly isolated target item (count=1, cost verified)."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 2.2 Single-match query failed isolation: {single_match_failures}"
        )
        results["failed"] += 1

    # =========================================================================
    # SUITE 3: Punctuation Variants in Comparative Premise Verification
    # =========================================================================
    print("\n[SUITE 3] Punctuation Variants in Comparative Premise Verification")
    verifier = PremiseConsistencyVerifier()

    # 3.1 Colons in speaker turns and entity labels where both graduated (Consistent)
    colon_consistent_cases = [
        "Priya: graduated in 2020; Marcus: graduated in 2021.",
        "Speaker 1 (Priya): graduated from MIT. Speaker 2 (Marcus): graduated from Harvard.",
        "Priya: graduated in 2020\nMarcus: graduated in 2021",
    ]
    colon_consist_failures = []
    for text in colon_consistent_cases:
        ev = [{"content": text}]
        res = verifier.verify("Who graduated first, Priya or Marcus?", evidence_rows=ev)
        if not res.is_consistent or res.abstention_recommended:
            colon_consist_failures.append((text, res))

    if not colon_consist_failures:
        print(
            f"  [PASS] 3.1 All {len(colon_consistent_cases)} colon-formatted consistent transcripts correctly evaluated as consistent."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 3.1 Colon consistent cases falsely abstained: {colon_consist_failures}"
        )
        results["failed"] += 1

    # 3.2 Colons where only Marcus graduated (Abstention required)
    colon_counterfactual = [
        "Priya: moved to Seattle. Marcus: graduated from MIT in 2021.",
        "Priya: started a new company; Marcus: graduated from Stanford.",
    ]
    colon_cf_failures = []
    for text in colon_counterfactual:
        ev = [{"content": text}]
        res = verifier.verify("Who graduated first, Priya or Marcus?", evidence_rows=ev)
        if (
            res.is_consistent
            or not res.abstention_recommended
            or "Priya" not in (res.clean_abstention_text or "")
        ):
            colon_cf_failures.append((text, res))

    if not colon_cf_failures:
        print(
            f"  [PASS] 3.2 All {len(colon_counterfactual)} colon counterfactuals correctly detected mismatch and abstained."
        )
        results["passed"] += 1
    else:
        print(
            f"  [FAIL] 3.2 Colon counterfactuals failed to abstain: {colon_cf_failures}"
        )
        results["failed"] += 1

    # 3.3 Semicolons and sentence-ending punctuation (!, ?)
    punct_cases = [
        ("Priya moved to Seattle; Marcus graduated from MIT in June.", False, True, "Priya"),
        ("Priya graduated in 2020; Marcus graduated in 2021.", True, False, None),
        (
            "Did Priya move to Seattle? Yes. Marcus graduated from MIT in 2021!",
            False,
            True,
            "Priya",
        ),
        ("Priya graduated in 2020! Marcus graduated in 2021!", True, False, None),
    ]
    punct_failures = []
    for text, expected_consistent, expected_abstain, expected_mention in punct_cases:
        ev = [{"content": text}]
        res = verifier.verify("Who graduated first, Priya or Marcus?", evidence_rows=ev)
        if (
            res.is_consistent != expected_consistent
            or res.abstention_recommended != expected_abstain
        ):
            punct_failures.append((text, res))
        elif expected_mention and expected_mention not in (
            res.clean_abstention_text or ""
        ):
            punct_failures.append((text, res))

    if not punct_failures:
        print(
            f"  [PASS] 3.3 All {len(punct_cases)} punctuation variants (; ! ?) correctly evaluated consistency and abstention."
        )
        results["passed"] += 1
    else:
        print(f"  [FAIL] 3.3 Punctuation evaluation failed: {punct_failures}")
        results["failed"] += 1

    # 3.4 Dashes separating clauses where both entities graduated (Consistent)
    dash_consistent_cases = [
        "Priya graduated in 2020 - Marcus graduated in 2021.",
        "Priya graduated in 2020 -- Marcus graduated in 2021.",
        "Priya graduated in 2020 — Marcus graduated in 2021.",
        "Priya graduated in 2020 – Marcus graduated in 2021.",
    ]
    dash_failures = []
    for text in dash_consistent_cases:
        ev = [{"content": text}]
        res = verifier.verify("Who graduated first, Priya or Marcus?", evidence_rows=ev)
        if not res.is_consistent or res.abstention_recommended:
            dash_failures.append((text, res))

    if not dash_failures:
        print(
            f"  [PASS] 3.4 All {len(dash_consistent_cases)} dash variants for consistent predicates correctly evaluated as consistent."
        )
        results["passed"] += 1
    else:
        print(f"  [FAIL] 3.4 Dash variants failed: {dash_failures}")
        results["failed"] += 1

    print("\n" + "=" * 70)
    print(
        f"ITERATION 4 PROBE SUMMARY: {results['passed']} PASSED, {results['failed']} DEFECTS DETECTED"
    )
    print("=" * 70)

    return results


def test_m3_it4_challenger_suite() -> None:
    """Pytest test case asserting all Iteration 4 challenger probes pass with 0 defects."""
    res = run_it4_probes()
    assert res["failed"] == 0, (
        f"{res['failed']} defects detected in Iteration 4 challenger probes"
    )


if __name__ == "__main__":
    res = run_it4_probes()
    sys.exit(0 if res["failed"] == 0 else 1)
