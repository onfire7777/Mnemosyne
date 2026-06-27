"""G0 Standing parity fixture.

Phase 7 P1 introduces Standing as a derived projection over existing memory
signals. This fixture proves the P1 contract: Standing mirrors the existing
boolean reality-monitoring and shadow/advisory decisions without changing the
critical-path retrieval or consolidation behavior.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.standing import STANDING_FN_VERSION, standing_from_shadow_flag


RETRIEVAL_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "grounded_only",
        "tenant": "g0-standing-grounded-only",
        "query": "standing alpha grounded contract",
        "evidence": [
            {
                "content": "Standing alpha grounded contract uses operator evidence.",
                "source_type": "operator-note",
                "reality_class": "grounded",
                "trust_tier": 0,
            }
        ],
    },
    {
        "id": "self_generated_only",
        "tenant": "g0-standing-self-generated-only",
        "query": "standing beta generated contract",
        "evidence": [
            {
                "content": "Standing beta generated contract came from workspace reflection.",
                "source_type": "workspace-reflection",
                "reality_class": "self_generated",
                "trust_tier": 5,
            }
        ],
    },
    {
        "id": "externally_suggested_only",
        "tenant": "g0-standing-externally-suggested-only",
        "query": "standing gamma suggested contract",
        "evidence": [
            {
                "content": "Standing gamma suggested contract came from unverified outside input.",
                "source_type": "external-suggestion",
                "reality_class": "externally_suggested",
                "trust_tier": 5,
            }
        ],
    },
    {
        "id": "unknown_only",
        "tenant": "g0-standing-unknown-only",
        "query": "standing delta unknown contract",
        "evidence": [
            {
                "content": "Standing delta unknown contract has no trusted source.",
                "source_type": "scratchpad",
                "reality_class": "unknown",
                "trust_tier": 5,
            }
        ],
    },
    {
        "id": "mixed_grounded_and_generated",
        "tenant": "g0-standing-mixed",
        "query": "standing epsilon mixed contract",
        "evidence": [
            {
                "content": "Standing epsilon mixed contract has operator evidence.",
                "source_type": "operator-note",
                "reality_class": "grounded",
                "trust_tier": 0,
            },
            {
                "content": "Standing epsilon mixed contract also appears in reflection.",
                "source_type": "workspace-reflection",
                "reality_class": "self_generated",
                "trust_tier": 5,
            },
        ],
    },
)


CONSOLIDATION_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "shadow_advisory",
        "shadow_only": True,
        "critical_path": False,
        "expected_authority": False,
    },
    {
        "id": "promoted_critical_path",
        "shadow_only": False,
        "critical_path": True,
        "expected_authority": True,
    },
)


def run_standing_parity_eval(*, repo_root: Path | None = None) -> dict[str, Any]:
    """Run deterministic Standing parity checks."""

    _ = repo_root
    retrieval_rows = [_run_retrieval_case(case) for case in RETRIEVAL_CASES]
    consolidation_rows = [_run_consolidation_case(case) for case in CONSOLIDATION_CASES]
    comparison_count = len(retrieval_rows) + len(consolidation_rows)
    divergence_count = sum(1 for row in retrieval_rows if row["diverged"]) + sum(
        1 for row in consolidation_rows if row["diverged"]
    )
    divergence = round(divergence_count / comparison_count, 6) if comparison_count else 1.0
    return {
        "schema_version": "g0.standing_parity.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "standing_fn_version": STANDING_FN_VERSION,
        "definition": (
            "Byte-stable P1 parity between existing boolean reality/shadow "
            "decisions and the derived Standing authority mirror."
        ),
        "metric": "standing_decision_divergence",
        "standing_decision_divergence": divergence,
        "divergence_count": divergence_count,
        "comparison_count": comparison_count,
        "passed": divergence == 0.0,
        "retrieval_rows": retrieval_rows,
        "consolidation_rows": consolidation_rows,
    }


def _run_retrieval_case(case: dict[str, Any]) -> dict[str, Any]:
    engine = LocalMemoryEngine()
    tenant = str(case["tenant"])
    cids: list[str] = []
    for index, seed in enumerate(case.get("evidence", [])):
        cids.append(
            engine.append_evidence(
                Evidence(
                    tenant_id=tenant,
                    user_id="g0-eval",
                    actor="system" if seed["trust_tier"] >= 5 else "user",
                    source_type=str(seed["source_type"]),
                    source_identity=f"g0-standing:{case['id']}:{index}",
                    content=str(seed["content"]),
                    metadata={
                        "reality_class": seed["reality_class"],
                        "confidence": 0.96 if seed["trust_tier"] < 5 else 0.35,
                    },
                    trust_tier=int(seed["trust_tier"]),
                    capability_tags=["g0-standing-parity"],
                    access_policy={"tenant": tenant},
                )
            )
        )

    result = engine.retrieve(str(case["query"]), tenant, filt={"max_trust_tier": 5})
    reality = result.explain.get("reality_monitoring", {})
    standing = result.explain.get("standing", {})
    legacy_active = bool(reality.get("ungrounded_only"))
    standing_active = bool((standing.get("abstention_gate") or {}).get("active"))
    mirror = standing.get("p1_mirror") if isinstance(standing.get("p1_mirror"), dict) else {}
    missing_support = len(result.hits) == 0
    diverged = missing_support or legacy_active != standing_active or mirror.get("zero_divergence") is not True
    return {
        "case_id": case["id"],
        "tenant": tenant,
        "query": case["query"],
        "support_cids": cids,
        "hit_count": len(result.hits),
        "support_retrieved": not missing_support,
        "hit_ids": [hit.id for hit in result.hits],
        "legacy": {
            "ungrounded_only": legacy_active,
            "abstention_gate_active": bool((reality.get("abstention_gate") or {}).get("active")),
            "abstained": result.abstained,
            "confidence": round(float(result.confidence), 6),
        },
        "standing": {
            "ungrounded_only": standing_active,
            "abstention_gate_active": standing_active,
            "authoritative_hit_count": standing.get("authoritative_hit_count"),
            "low_standing_hit_ids": standing.get("low_standing_hit_ids"),
        },
        "zero_divergence": not diverged,
        "diverged": diverged,
    }


def _run_consolidation_case(case: dict[str, Any]) -> dict[str, Any]:
    standing = standing_from_shadow_flag(
        shadow_only=bool(case["shadow_only"]),
        critical_path=bool(case["critical_path"]),
    )
    expected = bool(case["expected_authority"])
    authority = bool(standing.get("authority"))
    mirror = standing.get("mirror") if isinstance(standing.get("mirror"), dict) else {}
    diverged = authority != expected or mirror.get("standing_authority_matches_boolean") is not True
    return {
        "case_id": case["id"],
        "shadow_only": bool(case["shadow_only"]),
        "critical_path": bool(case["critical_path"]),
        "expected_authority": expected,
        "standing_authority": authority,
        "standing_fn_version": standing.get("standing_fn_version"),
        "zero_divergence": not diverged,
        "diverged": diverged,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the G0 Standing parity fixture")
    parser.add_argument("--out", type=Path, help="write the fixture report JSON")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_standing_parity_eval()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.print_json or not args.out:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
