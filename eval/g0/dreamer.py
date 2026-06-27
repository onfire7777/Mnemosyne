"""G0 shadow dreamer ablation fixture.

This fixture measures G3 generative replay only in the sandboxed, shadow-only
mode. It never promotes candidates, mutates the answer path, or claims that
generated candidates are grounded facts.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.workspace import ShadowWorkspaceController, WorkspaceItem


DATASET_PATH = Path("eval/datasets/dreamer_shadow_ablation.json")


def run_dreamer_eval(*, repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    dataset_path = repo_root / DATASET_PATH
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    tenant = str(dataset["tenant"])
    engine = LocalMemoryEngine()
    evidence_rows: list[Evidence] = []
    for row in dataset.get("evidence", []):
        evidence = Evidence(
            tenant_id=tenant,
            user_id="g0",
            actor="user",
            source_type="operator-evidence",
            content=str(row["content"]),
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
        cid = engine.append_evidence(evidence)
        stored = engine.get_evidence(tenant, cid)
        if stored is None:
            raise RuntimeError(f"failed to load G0 dreamer evidence {cid}")
        evidence_rows.append(stored)

    before = engine.export_tenant(tenant)
    items = [
        WorkspaceItem(
            id=str(item["id"]),
            priority=float(item["priority"]),
            content=str(item["content"]),
            source="g0-dreamer-shadow-ablation",
        )
        for item in dataset.get("items", [])
    ]
    report = ShadowWorkspaceController(max_workspace_items=2, max_cycles=3, tick_ms=250).run_shadow_cycle(
        tenant_id=tenant,
        items=items,
        evidence=evidence_rows,
        confidence=0.82,
        resource_health=0.94,
        error_rate=0.01,
        latency_ms=80.0,
        memory_pressure=0.25,
        rail_budget=0.96,
    )
    after = engine.export_tenant(tenant)
    payload = report.to_dict()
    invocations = payload["specialist_invocations"]
    dreamer = invocations[0] if invocations else {}
    output = dreamer.get("output_summary", {}) if isinstance(dreamer, dict) else {}
    promotion_evidence = output.get("promotion_evidence") if isinstance(output.get("promotion_evidence"), dict) else {}
    source_cids = {row.cid for row in evidence_rows}
    dream_report = report.specialist_invocations and ShadowWorkspaceController().registry.build_specialist(
        "dreamer.shadow"
    ).dream(evidence_rows, tenant_id=tenant)
    candidates = [candidate.to_dict() for candidate in (dream_report.candidates if dream_report else ())]
    cid_backed_candidates = [
        candidate
        for candidate in candidates
        if len(candidate["source_evidence_cids"]) >= 2
        and set(candidate["source_evidence_cids"]).issubset(source_cids)
    ]
    checks = {
        "controller_shadow_only": payload.get("shadow_only") is True,
        "controller_critical_path_false": payload.get("critical_path") is False,
        "controller_production_mutation_false": payload.get("production_mutation") is False,
        "engine_unchanged": before == after,
        "dreamer_invoked": dreamer.get("name") == "dreamer.shadow",
        "dreamer_role_reported": dreamer.get("role") == "dreamer",
        "dreamer_shadow_only": dreamer.get("shadow_only") is True,
        "dreamer_critical_path_false": dreamer.get("critical_path") is False,
        "dreamer_not_critical_path_allowed": dreamer.get("critical_path_allowed") is False,
        "dreamer_production_mutation_false": output.get("production_mutation") is False,
        "dreamer_promotion_gate_required": output.get("promotion_gate_required") is True,
        "dreamer_created_candidate": int(output.get("candidate_count") or 0) > 0,
        "dreamer_low_trust_candidates": output.get("candidate_trust_tiers") == [5],
        "dreamer_self_generated_candidates": output.get("candidate_reality_classes") == ["self_generated"],
        "dreamer_cid_backed_candidates": len(cid_backed_candidates) == int(output.get("candidate_count") or 0),
        "promotion_evidence_schema": promotion_evidence.get("schema_version")
        == "specialist-promotion-evidence.v1",
        "promotion_evidence_specialist": promotion_evidence.get("specialist_name") == "dreamer.shadow",
        "promotion_evidence_role": promotion_evidence.get("specialist_role") == "dreamer",
        "promotion_evidence_shadow_only": promotion_evidence.get("shadow_only") is True,
        "promotion_evidence_critical_path_false": promotion_evidence.get("critical_path") is False,
        "promotion_evidence_not_critical_path_allowed": promotion_evidence.get("critical_path_allowed") is False,
        "promotion_evidence_production_mutation_false": promotion_evidence.get("production_mutation") is False,
        "promotion_evidence_gate_required": promotion_evidence.get("promotion_gate_required") is True,
        "promotion_evidence_not_promoted": promotion_evidence.get("promoted") is False,
        "promotion_evidence_gate_absent": promotion_evidence.get("gate_result") is None
        and promotion_evidence.get("gate_result_present") is False,
        "promotion_evidence_cid_backed_candidates": int(
            promotion_evidence.get("cid_backed_candidate_count") or 0
        )
        == int(output.get("candidate_count") or 0),
        "promotion_evidence_raw_content_absent": all(
            row.content not in str(promotion_evidence) for row in evidence_rows
        ),
        "promotion_evidence_raw_cids_absent": all(
            row.cid not in str(promotion_evidence) for row in evidence_rows if row.cid
        ),
    }
    contract = 1.0 if all(checks.values()) else 0.0
    candidate_count = int(output.get("candidate_count") or 0)
    corroborated_count = len(cid_backed_candidates)
    return {
        "schema_version": "g0.dreamer_shadow_ablation.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_path": DATASET_PATH.as_posix(),
        "definition": "Shadow-only generative replay fixture with CID-backed low-trust candidates.",
        "metric_note": (
            "Measures whether the sandboxed dreamer can produce corroborated replay candidates "
            "without mutating the ledger or entering the answer critical path."
        ),
        "tenant": tenant,
        "source_evidence_count": len(evidence_rows),
        "candidate_count": candidate_count,
        "corroborated_candidate_count": corroborated_count,
        "corroborated_candidate_yield": float(corroborated_count),
        "shadow_contract": contract,
        "specialist_promotion_evidence_contract": 1.0
        if all(
            value
            for key, value in checks.items()
            if key.startswith("promotion_evidence_")
        )
        else 0.0,
        "checks": checks,
        "workspace": {
            "cycle": payload["cycle"],
            "selected_item_ids": [item["id"] for item in payload["selected_items"]],
            "shadow_only": payload["shadow_only"],
            "critical_path": payload["critical_path"],
            "production_mutation": payload["production_mutation"],
            "escalation_required": payload["escalation_required"],
            "proto_self": asdict(report.proto_self),
        },
        "dreamer": dreamer,
        "candidates": candidates,
    }
