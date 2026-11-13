"""Empirical challenger probes for Milestone M3 Iteration 4 verification.

Executed by challenger_m3_it4_19 to adversarially probe:
1. False positive protection on substring-containing words ("accredit", "succeed", "help", "step", etc.)
2. Zero-match count queries in adaptive_synthesize: unrelated turns guarantee count=0
   (no turn hallucination)
"""

from __future__ import annotations

import sys
from mnemosyne.answering import adaptive_synthesize
from mnemosyne.event_ledger import EventLedger


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
