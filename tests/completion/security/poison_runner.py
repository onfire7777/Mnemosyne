"""Runner for the MINJA / AgentPoison memory-poisoning corpus.

It drives every :class:`~poison_corpus.PoisonCase` through Mnemosyne's *public*
memory surface (``mnemosyne.mcp_tools.MemoryTools`` -> ``LocalMemoryEngine`` /
``IngestionPipeline``) -- the exact path a deployed agent or the ``mneme`` CLI
uses -- and decides, per case, whether the poison was *blocked*.

Block semantics, by vector (all checked against the real engine, no mocks):

``ingest_then_query``    Poison is ingested as untrusted external content, then
                         queried.  Blocked == the poison's ``leak_marker`` does
                         not appear in any surfaced hit under the default
                         ``OperatingPolicy`` (``max_trust_tier == 4`` filters the
                         tier-5 poison out of retrieval).

``write_authorization``  The case attempts a mediated write
                         (``SecurityPolicy.authorize_write``).  Blocked == the
                         capability decision is *denied*.

``tombstone_replay``     Content is ingested, ``forget``-erased, then re-ingested
                         verbatim.  Blocked == the re-append is a no-op that
                         leaves the evidence erased and the marker absent from
                         retrieval (``append_evidence.blocked_erased_replay``).

``cross_tenant_query``   Secret stored in tenant Alpha, queried from tenant Beta.
                         Blocked == the marker never surfaces for Beta.

``drift_then_query``     ``drift_count`` low-trust repeats are ingested, then the
                         topic is queried.  Blocked == the marker never surfaces.

``benign_ingest_query``  (control) Legitimate content is ingested and queried.
                         A *false positive* is recorded when the benign marker
                         fails to surface (the defense wrongly suppressed it).

REAL-MODEL NOTE
---------------
The block decisions above are deterministic trust / capability / tenant / erasure
gates and do not require a heavy ML model, so the runner is fully runnable now
with Mnemosyne's default :class:`HashingEmbeddingProvider`.  To exercise the
corpus against a *real* embedding/reranker model (the only ML-dependent surface),
pass an engine whose ``IngestionPipeline`` / retrieval adapters use a real
provider -- e.g. ``CommandMediaEmbeddingProvider`` or a sentence-transformer
adapter.  The contract is identical: build a ``MemoryTools`` over that engine and
hand it to :func:`run_corpus` via ``tools_factory``.  Stronger semantic ranking
can only *lower* leakage (poison is already filtered before ranking), so the
fallback path is conservative, not permissive.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Allow running both as a module (pytest, pythonpath=src) and as a script.
_SRC = Path(__file__).resolve().parents[3] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from mnemosyne.engine import LocalMemoryEngine  # noqa: E402
from mnemosyne.mcp_tools import MemoryTools  # noqa: E402
from mnemosyne.security import SecurityPolicy  # noqa: E402

from poison_corpus import (  # noqa: E402
    ATTACK_CATEGORIES,
    POISON_BLOCK_SLO,
    PoisonCase,
    PoisonCategory,
    all_cases,
    attack_cases,
    benign_cases,
)


# --------------------------------------------------------------------------- #
# Result model
# --------------------------------------------------------------------------- #

@dataclass(slots=True)
class CaseResult:
    case_id: str
    category: str
    vector: str
    # For attack cases: True == poison was blocked (good).
    # For benign controls: blocked is None; false_positive carries the signal.
    blocked: bool | None
    false_positive: bool | None
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "vector": self.vector,
            "blocked": self.blocked,
            "false_positive": self.false_positive,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass(slots=True)
class CategoryReport:
    category: str
    total: int
    blocked: int

    @property
    def block_rate(self) -> float:
        return self.blocked / self.total if self.total else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "total": self.total,
            "blocked": self.blocked,
            "block_rate": round(self.block_rate, 4),
        }


@dataclass(slots=True)
class CorpusReport:
    results: list[CaseResult]
    per_category: dict[str, CategoryReport]
    attack_total: int
    attack_blocked: int
    benign_total: int
    benign_false_positives: int
    slo: float = POISON_BLOCK_SLO

    @property
    def overall_block_rate(self) -> float:
        return self.attack_blocked / self.attack_total if self.attack_total else 1.0

    @property
    def false_positive_rate(self) -> float:
        return self.benign_false_positives / self.benign_total if self.benign_total else 0.0

    @property
    def meets_slo(self) -> bool:
        return self.overall_block_rate >= self.slo

    def failures(self) -> list[CaseResult]:
        return [r for r in self.results if r.blocked is False]

    def false_positives(self) -> list[CaseResult]:
        return [r for r in self.results if r.false_positive]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "attack_total": self.attack_total,
                "attack_blocked": self.attack_blocked,
                "overall_block_rate": round(self.overall_block_rate, 4),
                "slo": self.slo,
                "meets_slo": self.meets_slo,
                "benign_total": self.benign_total,
                "benign_false_positives": self.benign_false_positives,
                "false_positive_rate": round(self.false_positive_rate, 4),
            },
            "per_category": {k: v.to_dict() for k, v in self.per_category.items()},
            "failures": [r.to_dict() for r in self.failures()],
            "false_positives": [r.to_dict() for r in self.false_positives()],
            "results": [r.to_dict() for r in self.results],
        }


# --------------------------------------------------------------------------- #
# Per-vector evaluators (each builds a fresh isolated engine)
# --------------------------------------------------------------------------- #

ToolsFactory = Callable[[], MemoryTools]


def _default_tools_factory() -> MemoryTools:
    """Fresh in-memory engine + default security policy (production defaults)."""

    return MemoryTools(LocalMemoryEngine())


def _marker_surfaced(search_result: dict[str, Any], marker: str) -> tuple[bool, list[str]]:
    marker_lc = marker.lower()
    leaked: list[str] = []
    for hit in search_result.get("hits", []):
        text = str(hit.get("text", ""))
        if marker_lc in text.lower():
            leaked.append(f"{hit.get('id', '?')}[tier={hit.get('trust_tier')}]")
    return (bool(leaked), leaked)


def _eval_ingest_then_query(case: PoisonCase, tools: MemoryTools) -> CaseResult:
    tenant, user = "tenant-poison", "user-poison"
    ingest = tools.ingest(
        tenant_id=tenant,
        user_id=user,
        actor=case.actor,
        source_type=case.source_type,
        content=case.payload,
        source_identity=case.source_identity,
        metadata=dict(case.metadata),
        trust_tier=case.trust_tier,
    )
    # Query at the deployed default policy (no caller-supplied trust override).
    result = tools.search(tenant, case.effective_query())
    surfaced, leaked = _marker_surfaced(result, case.effective_leak_marker())
    blocked = not surfaced
    detail = (
        f"ingested at trust_tier={ingest['trust_tier']}; "
        + ("poison filtered from retrieval" if blocked else f"LEAKED via {leaked}")
    )
    return CaseResult(
        case_id=case.id,
        category=case.category.value,
        vector=case.vector,
        blocked=blocked,
        false_positive=None,
        detail=detail,
        evidence={
            "ingest_trust_tier": ingest["trust_tier"],
            "quarantined": ingest.get("quarantined"),
            "hit_count": len(result.get("hits", [])),
            "abstained": result.get("abstained"),
            "leaked_hits": leaked,
        },
    )


def _eval_write_authorization(case: PoisonCase, tools: MemoryTools) -> CaseResult:
    policy: SecurityPolicy = tools.security
    assert case.write_source_trust_tier is not None
    decision = policy.authorize_write(
        operation=case.write_op,
        role=case.write_role,  # type: ignore[arg-type]
        source_trust_tier=case.write_source_trust_tier,
        destructive=case.write_destructive,
        target_sink=case.write_sink,
    )
    blocked = not decision.allowed
    return CaseResult(
        case_id=case.id,
        category=case.category.value,
        vector=case.vector,
        blocked=blocked,
        false_positive=None,
        detail=(
            f"op={case.write_op} sink={case.write_sink} "
            f"tier={case.write_source_trust_tier}: "
            + ("DENIED -> " if blocked else "ALLOWED -> ")
            + decision.reason
        ),
        evidence={
            "allowed": decision.allowed,
            "reason": decision.reason,
            "required_role": decision.required_role,
            "required_trust": decision.required_trust,
        },
    )


def _eval_tombstone_replay(case: PoisonCase, tools: MemoryTools) -> CaseResult:
    tenant, user = "tenant-poison", "user-poison"
    first = tools.ingest(
        tenant_id=tenant,
        user_id=user,
        actor=case.actor,
        source_type=case.source_type,
        content=case.payload,
        trust_tier=case.trust_tier,
    )
    cid = first["cid"]
    forget_result = tools.forget(tenant, cid)
    # Attacker re-ingests the identical content to try to resurrect it.
    replay = tools.ingest(
        tenant_id=tenant,
        user_id="attacker",
        actor=case.actor,
        source_type=case.source_type,
        content=case.payload,
        trust_tier=case.trust_tier,
    )
    same_cid = replay["cid"] == cid
    engine = tools.engine
    key = engine._evidence_key(tenant, "main", cid)  # contract: erased rows retained
    stored = engine.evidence.get(key)
    still_erased = bool(stored and stored.erased)
    result = tools.search(tenant, case.effective_query())
    surfaced, leaked = _marker_surfaced(result, case.effective_leak_marker())
    # Block requires: forget succeeded, replay collided on the same cid, the row
    # stays erased, and the marker does not resurface in retrieval.
    blocked = (
        bool(forget_result.get("erased"))
        and same_cid
        and still_erased
        and not surfaced
    )
    return CaseResult(
        case_id=case.id,
        category=case.category.value,
        vector=case.vector,
        blocked=blocked,
        false_positive=None,
        detail=(
            f"forget.erased={forget_result.get('erased')} replay_same_cid={same_cid} "
            f"still_erased={still_erased} "
            + ("replay blocked, stays tombstoned" if blocked else f"RESURRECTED via {leaked}")
        ),
        evidence={
            "original_cid": cid,
            "replay_cid": replay["cid"],
            "same_cid": same_cid,
            "still_erased": still_erased,
            "leaked_hits": leaked,
        },
    )


def _eval_cross_tenant_query(case: PoisonCase, tools: MemoryTools) -> CaseResult:
    alpha, beta = "tenant-alpha", "tenant-beta"
    tools.ingest(
        tenant_id=alpha,
        user_id="alpha-user",
        actor=case.actor,
        source_type=case.source_type,
        content=case.payload,
        trust_tier=case.trust_tier,
    )
    # Query from the *other* tenant.
    beta_result = tools.search(beta, case.effective_query(), role="consolidator")
    surfaced, leaked = _marker_surfaced(beta_result, case.effective_leak_marker())
    blocked = not surfaced
    # Sanity: confirm the secret IS retrievable inside its own tenant, so we are
    # measuring isolation rather than a retrieval miss.
    alpha_result = tools.search(alpha, case.effective_query(), role="consolidator")
    own_tenant_surfaced, _ = _marker_surfaced(alpha_result, case.effective_leak_marker())
    return CaseResult(
        case_id=case.id,
        category=case.category.value,
        vector=case.vector,
        blocked=blocked,
        false_positive=None,
        detail=(
            f"own-tenant retrievable={own_tenant_surfaced}; "
            + ("no cross-tenant leak" if blocked else f"LEAKED to {beta} via {leaked}")
        ),
        evidence={
            "beta_hit_count": len(beta_result.get("hits", [])),
            "own_tenant_surfaced": own_tenant_surfaced,
            "leaked_hits": leaked,
        },
    )


def _eval_drift_then_query(case: PoisonCase, tools: MemoryTools) -> CaseResult:
    tenant, user = "tenant-poison", "user-poison"
    for i in range(case.drift_count):
        tools.ingest(
            tenant_id=tenant,
            user_id=user,
            actor=case.actor,
            source_type=case.source_type,
            content=f"{case.payload} (repetition {i})",
            trust_tier=case.trust_tier,
        )
    result = tools.search(tenant, case.effective_query())
    surfaced, leaked = _marker_surfaced(result, case.effective_leak_marker())
    blocked = not surfaced
    return CaseResult(
        case_id=case.id,
        category=case.category.value,
        vector=case.vector,
        blocked=blocked,
        false_positive=None,
        detail=(
            f"ingested {case.drift_count} low-trust repeats; "
            + ("all filtered from retrieval" if blocked else f"DRIFTED in via {leaked}")
        ),
        evidence={
            "drift_count": case.drift_count,
            "hit_count": len(result.get("hits", [])),
            "leaked_hits": leaked,
        },
    )


def _eval_benign_ingest_query(case: PoisonCase, tools: MemoryTools) -> CaseResult:
    tenant, user = "tenant-benign", "user-benign"
    tools.ingest(
        tenant_id=tenant,
        user_id=user,
        actor=case.actor,
        source_type=case.source_type,
        content=case.payload,
        trust_tier=case.trust_tier,
    )
    result = tools.search(tenant, case.effective_query())
    surfaced, _ = _marker_surfaced(result, case.effective_leak_marker())
    # False positive == benign content the defense wrongly suppressed.
    false_positive = not surfaced
    return CaseResult(
        case_id=case.id,
        category=case.category.value,
        vector=case.vector,
        blocked=None,
        false_positive=false_positive,
        detail=(
            "benign content retrievable (correct)"
            if surfaced
            else "FALSE POSITIVE: benign content wrongly suppressed"
        ),
        evidence={
            "hit_count": len(result.get("hits", [])),
            "abstained": result.get("abstained"),
            "surfaced": surfaced,
        },
    )


_EVALUATORS: dict[str, Callable[[PoisonCase, MemoryTools], CaseResult]] = {
    "ingest_then_query": _eval_ingest_then_query,
    "write_authorization": _eval_write_authorization,
    "tombstone_replay": _eval_tombstone_replay,
    "cross_tenant_query": _eval_cross_tenant_query,
    "drift_then_query": _eval_drift_then_query,
    "benign_ingest_query": _eval_benign_ingest_query,
}


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def evaluate_case(case: PoisonCase, tools_factory: ToolsFactory) -> CaseResult:
    evaluator = _EVALUATORS.get(case.vector)
    if evaluator is None:  # pragma: no cover - guarded by the corpus taxonomy.
        raise ValueError(f"unknown vector: {case.vector}")
    # Each case runs against a fresh, isolated engine so corpus order never
    # affects a result.
    tools = tools_factory()
    return evaluator(case, tools)


def run_corpus(
    cases: list[PoisonCase] | None = None,
    *,
    tools_factory: ToolsFactory | None = None,
) -> CorpusReport:
    cases = cases if cases is not None else all_cases()
    factory = tools_factory or _default_tools_factory
    results = [evaluate_case(case, factory) for case in cases]

    cat_total: dict[str, int] = defaultdict(int)
    cat_blocked: dict[str, int] = defaultdict(int)
    attack_total = attack_blocked = 0
    benign_total = benign_fp = 0

    for r in results:
        if r.blocked is None:  # benign control
            benign_total += 1
            if r.false_positive:
                benign_fp += 1
            continue
        cat_total[r.category] += 1
        attack_total += 1
        if r.blocked:
            cat_blocked[r.category] += 1
            attack_blocked += 1

    per_category = {
        cat: CategoryReport(cat, cat_total[cat], cat_blocked[cat])
        for cat in sorted(cat_total)
    }
    return CorpusReport(
        results=results,
        per_category=per_category,
        attack_total=attack_total,
        attack_blocked=attack_blocked,
        benign_total=benign_total,
        benign_false_positives=benign_fp,
    )


# --------------------------------------------------------------------------- #
# Reporting / CLI
# --------------------------------------------------------------------------- #

def format_report(report: CorpusReport) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Mnemosyne memory-poisoning corpus (MINJA / AgentPoison tier)")
    lines.append("FR-7 / G7 / blueprint section 16 (>=95% poison-block) / section 33")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"{'category':<28} {'blocked':>9} {'total':>7} {'rate':>8}")
    lines.append("-" * 56)
    for cat in ATTACK_CATEGORIES:
        rep = report.per_category.get(cat.value)
        if rep is None:
            continue
        lines.append(
            f"{cat.value:<28} {rep.blocked:>9} {rep.total:>7} {rep.block_rate:>7.1%}"
        )
    lines.append("-" * 56)
    lines.append(
        f"{'OVERALL (attacks)':<28} {report.attack_blocked:>9} "
        f"{report.attack_total:>7} {report.overall_block_rate:>7.1%}"
    )
    lines.append("")
    lines.append(
        f"SLO >= {report.slo:.0%} poison-block: "
        + ("PASS" if report.meets_slo else "FAIL")
    )
    lines.append(
        f"false-positive rate (benign blocked): "
        f"{report.false_positive_rate:.1%} "
        f"({report.benign_false_positives}/{report.benign_total})"
    )
    failures = report.failures()
    if failures:
        lines.append("")
        lines.append("FAILURES (poison NOT blocked):")
        for r in failures:
            lines.append(f"  - {r.case_id}: {r.detail}")
    fps = report.false_positives()
    if fps:
        lines.append("")
        lines.append("FALSE POSITIVES (benign wrongly blocked):")
        for r in fps:
            lines.append(f"  - {r.case_id}: {r.detail}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Mnemosyne MINJA/AgentPoison memory-poisoning corpus.",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the full machine-readable report"
    )
    parser.add_argument(
        "--attacks-only",
        action="store_true",
        help="run only adversarial cases (skip benign controls)",
    )
    parser.add_argument(
        "--category",
        choices=[c.value for c in PoisonCategory],
        help="restrict to a single category",
    )
    args = parser.parse_args(argv)

    if args.attacks_only:
        cases = attack_cases()
    else:
        cases = all_cases()
    if args.category:
        cases = [c for c in cases if c.category.value == args.category]
        # Keep benign controls available for FP reporting unless attacks-only.
        if not args.attacks_only and args.category != PoisonCategory.BENIGN_CONTROL.value:
            cases += benign_cases()

    report = run_corpus(cases)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_report(report))
    # Non-zero exit when the SLO is missed -- usable as a CI gate.
    return 0 if report.meets_slo else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
