"""G0 synthetic write-gate precision/recall regression cell.

This fixture drives trusted high-surprise, low-surprise, malformed, untrusted,
and fail-closed promotion cases through the existing ingestion prediction-error
signal and ``ConsolidationWorker._prediction_error_gate``. Surprise may change
replay priority. It must never raise write authority. Held-out labels stay in
this helper and are never passed to ingestion.

This is a development regression helper, not a publishable benchmark claim.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import RegressionCase
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.models import Assertion, Evidence
from mnemosyne.queue import InProcessQueue
from mnemosyne.security import CapabilityDecision, SecurityPolicy, TrustTier


FAILURE_CLASSES: tuple[str, ...] = (
    "security",
    "corroboration",
    "regression",
    "mutation_budget",
    "erasure",
    "capability",
    "low_surprise_metadata_only",
    "malformed_surprise",
    "untrusted_surprise",
)

HELD_OUT_LABEL_KEYS: frozenset[str] = frozenset(
    {
        "held_out_label",
        "should_write",
        "write_gate_label",
        "eval_label",
        "held_out",
        "failure_class",
    }
)

FACT_A = "The amber harbor beacon is cerulean."
FACT_B = "Independent note: amber harbor beacon is cerulean."


class _DenyPromoteSecurity(SecurityPolicy):
    def authorize_write(
        self,
        operation: str,
        role: str = "consolidator",
        source_trust_tier: int = 0,
        destructive: bool = False,
        target_sink: str | None = None,
        source_capability_tags: Any = None,
    ) -> CapabilityDecision:
        if operation == "promote_candidate":
            return CapabilityDecision(False, "security_denied", role, source_trust_tier, operation)
        return super().authorize_write(
            operation,
            role,
            source_trust_tier,
            destructive=destructive,
            target_sink=target_sink,
            source_capability_tags=source_capability_tags,
        )


def run_write_gating_eval() -> dict[str, Any]:
    """Run the deterministic G0 write-precision/recall regression fixture."""

    rows: list[dict[str, Any]] = []
    ingested_label_keys: list[str] = []
    for spec in _CASES:
        row, leaked = _run_case(spec)
        rows.append(row)
        ingested_label_keys.extend(leaked)

    confusion = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    failure_classes = {name: 0 for name in FAILURE_CLASSES}
    for row in rows:
        key = _confusion_key(should_write=row["should_write"], wrote=row["wrote"])
        confusion[key] += 1
        if row["mechanism_matched"] and row["failure_class"] in failure_classes:
            failure_classes[row["failure_class"]] += 1

    precision_den = confusion["tp"] + confusion["fp"]
    recall_den = confusion["tp"] + confusion["fn"]
    precision = (confusion["tp"] / precision_den) if precision_den else 0.0
    recall = (confusion["tp"] / recall_den) if recall_den else 0.0
    passed = (
        confusion["fp"] == 0
        and confusion["fn"] == 0
        and not ingested_label_keys
        and all(row["passed"] for row in rows)
        and set(failure_classes) == set(FAILURE_CLASSES)
    )
    return {
        "schema_version": "g0.write_gating.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metric": "write_precision_recall",
        "definition": (
            "Synthetic write-gate precision/recall over trusted high-surprise "
            "promotion versus fail-closed security, corroboration, regression, "
            "mutation-budget, erasure, capability, low-surprise, malformed, and "
            "untrusted cases. Surprise changes priority only."
        ),
        "metric_note": (
            "Deterministic local proxy for CAP-008 surprise-gated writes. "
            "This is a development regression cell, not an official or "
            "superiority claim. Held-out labels never enter ingestion."
        ),
        "total_cases": len(rows),
        "passed_cases": sum(1 for row in rows if row["passed"]),
        "confusion": confusion,
        "denominators": {
            "precision": precision_den,
            "recall": recall_den,
            "total": len(rows),
            "positive": confusion["tp"] + confusion["fn"],
            "negative": confusion["tn"] + confusion["fp"],
        },
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "failure_classes": failure_classes,
        "ingested_label_keys": ingested_label_keys,
        "passed": passed,
        "rows": rows,
    }


def _passing_case() -> RegressionCase:
    return RegressionCase(
        id="case-cerulean",
        signature="amber harbor beacon",
        query="amber harbor beacon",
        expected_substring="cerulean",
        protected=True,
    )


def _worker(
    engine: LocalMemoryEngine,
    *,
    security: SecurityPolicy | None = None,
    max_supersession_rate: float | None = None,
    gate_cases: list[RegressionCase] | None = None,
) -> ConsolidationWorker:
    return ConsolidationWorker(
        engine,
        gate_cases if gate_cases is not None else [_passing_case()],
        consolidation_min_steps=0,
        security=security,
        max_supersession_rate=max_supersession_rate,
    )


def _append(
    engine: LocalMemoryEngine,
    tenant: str,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
    trust_tier: int = 0,
    capability_tags: list[str] | None = None,
    actor: str = "user",
    source_type: str = "chat",
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="g0-eval",
            actor=actor,  # type: ignore[arg-type]
            source_type=source_type,
            source_identity=f"g0:write-gating:{tenant}",
            content=content,
            metadata=dict(metadata or {}),
            trust_tier=trust_tier,
            capability_tags=list(capability_tags or []),
            access_policy={"tenant": tenant},
        )
    )


def _ingest_pair(engine: LocalMemoryEngine, tenant: str, contents: tuple[str, str], **kwargs: Any) -> list[str]:
    queue = InProcessQueue()
    pipeline = IngestionPipeline(engine, queue=queue)
    cids: list[str] = []
    for content in contents:
        result = pipeline.ingest(
            IngestRequest(
                tenant_id=tenant,
                user_id="g0-eval",
                actor=str(kwargs.get("actor", "user")),
                source_type=str(kwargs.get("source_type", "chat")),
                content=content,
                metadata=dict(kwargs.get("metadata") or {}),
                capability_tags=list(kwargs.get("capability_tags") or []),
            )
        )
        cids.append(result.cid)
    return cids


def _collect_leaked_labels(engine: LocalMemoryEngine, tenant: str) -> list[str]:
    leaked: list[str] = []
    for row in engine.export_tenant(tenant).get("evidence", []):
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        leaked.extend(sorted(set(metadata) & HELD_OUT_LABEL_KEYS))
        consolidation = metadata.get("consolidation")
        if isinstance(consolidation, dict):
            leaked.extend(sorted(set(consolidation) & HELD_OUT_LABEL_KEYS))
    return leaked


def _promoted(run: Any) -> bool:
    return any(bool(item.get("promoted")) for item in run.candidate_results)


def _confusion_key(*, should_write: bool, wrote: bool) -> str:
    if should_write and wrote:
        return "tp"
    if not should_write and wrote:
        return "fp"
    if not should_write and not wrote:
        return "tn"
    return "fn"


def _run_case(spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    engine = LocalMemoryEngine()
    tenant = str(spec["tenant"])
    runner = spec["run"]
    outcome = runner(engine, tenant)
    leaked = _collect_leaked_labels(engine, tenant)
    should_write = bool(spec["should_write"])
    wrote = bool(outcome["wrote"])
    mechanism_matched = _mechanism_matched(
        spec.get("failure_class"),
        outcome,
        should_write=should_write,
        wrote=wrote,
    )
    passed = wrote is should_write and mechanism_matched and not leaked
    row = {
        "case_id": spec["case_id"],
        "should_write": should_write,
        "wrote": wrote,
        "passed": passed,
        "failure_class": spec["failure_class"],
        "mechanism_matched": mechanism_matched,
        "gate": outcome.get("gate"),
        "skipped": outcome.get("skipped") or [],
        "evidence_seen": outcome.get("evidence_seen"),
        "ingest_metadata": outcome.get("ingest_metadata") or {},
    }
    return row, leaked


def _mechanism_matched(
    failure_class: str | None,
    outcome: dict[str, Any],
    *,
    should_write: bool,
    wrote: bool,
) -> bool:
    if failure_class is None:
        return should_write is True and wrote is True
    if wrote:
        return False
    candidates = outcome.get("candidate_results") or []
    skipped = [str(item) for item in (outcome.get("skipped") or [])]
    failed = [str(item.get("failed_cases") or "") for item in candidates if isinstance(item, dict)]
    gate = outcome.get("gate")
    if failure_class == "security":
        return any("security_denied" in text for text in failed)
    if failure_class == "corroboration":
        return any("fact_external_corroboration" in text for text in failed)
    if failure_class == "regression":
        return any(bool(item.get("protected_regressions")) for item in candidates if isinstance(item, dict))
    if failure_class == "mutation_budget":
        rails = outcome.get("mutation_rails") if isinstance(outcome.get("mutation_rails"), dict) else {}
        violations = rails.get("violations") if isinstance(rails.get("violations"), list) else []
        return any(isinstance(item, dict) and item.get("rail") == "max_supersession_rate" for item in violations) or (
            rails.get("supersessions_allowed") == 0 and not any(bool(item.get("promoted")) for item in candidates if isinstance(item, dict))
        )
    if failure_class == "erasure":
        return outcome.get("evidence_seen") == 0
    if failure_class == "capability":
        return "source_marked_data_only" in skipped
    if failure_class == "low_surprise_metadata_only":
        return gate == "low_prediction_error_metadata_only" and "low_prediction_error_metadata_only" in skipped
    if failure_class == "malformed_surprise":
        return gate == "low_prediction_error_metadata_only"
    if failure_class == "untrusted_surprise":
        return "source_marked_data_only" in skipped
    return False


def _gate_name(run: Any) -> str | None:
    for item in run.pass_results:
        if item["name"] == "prediction_error_gate":
            return str(item["details"].get("gate") or "")
    return None


def _mutation_rails(run: Any) -> dict[str, Any]:
    for item in run.pass_results:
        if item["name"] == "mutation_rails" and isinstance(item.get("details"), dict):
            return item["details"]
    return {}


def _run_outcome(run: Any, **extra: Any) -> dict[str, Any]:
    payload = {
        "wrote": _promoted(run),
        "gate": _gate_name(run),
        "skipped": run.skipped,
        "evidence_seen": run.evidence_seen,
        "candidate_results": list(run.candidate_results),
        "mutation_rails": _mutation_rails(run),
    }
    payload.update(extra)
    return payload


def _run_trusted_high_surprise(engine: LocalMemoryEngine, tenant: str) -> dict[str, Any]:
    cid_a = _append(engine, tenant, FACT_A, metadata={"consolidation": {"prediction_error": 0.91}})
    cid_b = _append(
        engine,
        tenant,
        FACT_B,
        metadata={"consolidation": {"prediction_error": 0.91}},
        source_type="note",
    )
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": tenant,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": 0.91},
        }
    )
    return _run_outcome(run)


def _run_uncorroborated(engine: LocalMemoryEngine, tenant: str) -> dict[str, Any]:
    cid = _append(engine, tenant, FACT_A, metadata={"consolidation": {"prediction_error": 1.0}})
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": tenant,
            "source_evidence_cids": [cid],
            "prediction_error": {"score": 1.0},
        }
    )
    return _run_outcome(run)


def _run_low_surprise(engine: LocalMemoryEngine, tenant: str) -> dict[str, Any]:
    cid_a = _append(engine, tenant, FACT_A, metadata={"consolidation": {"prediction_error": 0.0}})
    cid_b = _append(
        engine,
        tenant,
        FACT_B,
        metadata={"consolidation": {"prediction_error": 0.0}},
        source_type="note",
    )
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": tenant,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": 0.0},
        }
    )
    return _run_outcome(run)


def _run_untrusted(engine: LocalMemoryEngine, tenant: str) -> dict[str, Any]:
    cids = _ingest_pair(
        engine,
        tenant,
        (FACT_A, FACT_B),
        actor="external",
        source_type="web",
        metadata={"surprise": 1.0, "importance": 1.0, "novelty": 1.0, "reward": 1.0},
    )
    ev = engine.get_evidence(tenant, cids[0])
    ingest_metadata = dict(ev.metadata) if ev is not None else {}
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": tenant,
            "source_evidence_cids": cids,
            "prediction_error": {"score": 1.0},
            "trust_tier": int(TrustTier.UNTRUSTED_EXTERNAL),
            "capability_tags": ["data-only", "no-write-authority"],
        }
    )
    return _run_outcome(
        run,
        ingest_metadata={
            "write_priority": (ingest_metadata.get("write_priority") or {}),
            "consolidation": (ingest_metadata.get("consolidation") or {}),
        },
    )


def _run_malformed(engine: LocalMemoryEngine, tenant: str) -> dict[str, Any]:
    cid_a = _append(engine, tenant, FACT_A)
    cid_b = _append(engine, tenant, FACT_B, source_type="note")
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": tenant,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": "not-a-number"},
        }
    )
    return _run_outcome(run)


def _run_erasure(engine: LocalMemoryEngine, tenant: str) -> dict[str, Any]:
    cid_a = _append(engine, tenant, FACT_A, metadata={"consolidation": {"prediction_error": 1.0}})
    cid_b = _append(
        engine,
        tenant,
        FACT_B,
        metadata={"consolidation": {"prediction_error": 1.0}},
        source_type="note",
    )
    engine.forget(tenant, cid_a, requested_by="operator")
    engine.forget(tenant, cid_b, requested_by="operator")
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": tenant,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": 1.0},
        }
    )
    return _run_outcome(run)


def _run_capability(engine: LocalMemoryEngine, tenant: str) -> dict[str, Any]:
    cid_a = _append(
        engine,
        tenant,
        FACT_A,
        metadata={"consolidation": {"prediction_error": 1.0}},
        capability_tags=["data-only", "no-write-authority"],
    )
    cid_b = _append(
        engine,
        tenant,
        FACT_B,
        metadata={"consolidation": {"prediction_error": 1.0}},
        capability_tags=["data-only", "no-write-authority"],
        source_type="note",
    )
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": tenant,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": 1.0},
            "capability_tags": ["data-only", "no-write-authority"],
        }
    )
    return _run_outcome(run)


def _run_security(engine: LocalMemoryEngine, tenant: str) -> dict[str, Any]:
    cid_a = _append(engine, tenant, FACT_A, metadata={"consolidation": {"prediction_error": 1.0}})
    cid_b = _append(
        engine,
        tenant,
        FACT_B,
        metadata={"consolidation": {"prediction_error": 1.0}},
        source_type="note",
    )
    run = _worker(engine, security=_DenyPromoteSecurity()).run_queue_payload(
        {
            "tenant_id": tenant,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": 1.0},
        }
    )
    return _run_outcome(run)


def _run_regression(engine: LocalMemoryEngine, tenant: str) -> dict[str, Any]:
    cid_a = _append(
        engine,
        tenant,
        "The amber harbor beacon is scarlet.",
        metadata={"consolidation": {"prediction_error": 1.0}},
    )
    cid_b = _append(
        engine,
        tenant,
        "Independent note: amber harbor beacon is scarlet.",
        metadata={"consolidation": {"prediction_error": 1.0}},
        source_type="note",
    )
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": tenant,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": 1.0},
        }
    )
    return _run_outcome(run)


def _run_mutation_budget(engine: LocalMemoryEngine, tenant: str) -> dict[str, Any]:
    for index in range(4):
        cid = _append(engine, tenant, f"Entity {index} value is alpha.")
        engine.upsert_assertion(
            Assertion(
                tenant_id=tenant,
                subject=f"Entity {index}",
                predicate="value is",
                object="alpha",
                source_evidence_cids=[cid],
                status="active",
                trust_tier=int(TrustTier.NORMAL),
                access_policy={"tenant": tenant},
            )
        )
    replacements = [
        _append(
            engine,
            tenant,
            f"Entity {index} value is beta.",
            metadata={"consolidation": {"prediction_error": 1.0}},
        )
        for index in range(4)
    ]
    before = {
        row["id"]
        for row in engine.export_tenant(tenant)["assertions"]
        if row.get("status") == "active" and row.get("branch", "main") == "main"
    }
    run = _worker(engine, max_supersession_rate=0.0, gate_cases=[]).run_queue_payload(
        {
            "tenant_id": tenant,
            "source_evidence_cids": replacements,
            "prediction_error": {"score": 1.0},
        }
    )
    after = {
        row["id"]
        for row in engine.export_tenant(tenant)["assertions"]
        if row.get("status") == "active" and row.get("branch", "main") == "main"
    }
    over_budget = bool(before - after)
    return _run_outcome(run, wrote=over_budget)


_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "trusted_high_surprise_corroborated",
        "tenant": "g0-write-gate-tp",
        "should_write": True,
        "failure_class": None,
        "run": _run_trusted_high_surprise,
    },
    {
        "case_id": "trusted_high_surprise_uncorroborated",
        "tenant": "g0-write-gate-corroboration",
        "should_write": False,
        "failure_class": "corroboration",
        "run": _run_uncorroborated,
    },
    {
        "case_id": "trusted_low_surprise",
        "tenant": "g0-write-gate-low",
        "should_write": False,
        "failure_class": "low_surprise_metadata_only",
        "run": _run_low_surprise,
    },
    {
        "case_id": "untrusted_high_surprise",
        "tenant": "g0-write-gate-untrusted",
        "should_write": False,
        "failure_class": "untrusted_surprise",
        "run": _run_untrusted,
    },
    {
        "case_id": "malformed_surprise",
        "tenant": "g0-write-gate-malformed",
        "should_write": False,
        "failure_class": "malformed_surprise",
        "run": _run_malformed,
    },
    {
        "case_id": "erased_high_surprise",
        "tenant": "g0-write-gate-erasure",
        "should_write": False,
        "failure_class": "erasure",
        "run": _run_erasure,
    },
    {
        "case_id": "capability_tainted",
        "tenant": "g0-write-gate-capability",
        "should_write": False,
        "failure_class": "capability",
        "run": _run_capability,
    },
    {
        "case_id": "security_denied",
        "tenant": "g0-write-gate-security",
        "should_write": False,
        "failure_class": "security",
        "run": _run_security,
    },
    {
        "case_id": "regression_protected",
        "tenant": "g0-write-gate-regression",
        "should_write": False,
        "failure_class": "regression",
        "run": _run_regression,
    },
    {
        "case_id": "mutation_budget",
        "tenant": "g0-write-gate-budget",
        "should_write": False,
        "failure_class": "mutation_budget",
        "run": _run_mutation_budget,
    },
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the G0 write-gating fixture")
    parser.add_argument("--out", type=Path, help="write the fixture report JSON")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_write_gating_eval()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.print_json or not args.out:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
