"""G0 earned-autonomy promotion fixture.

Phase 7 P4 lets self-generated thoughts receive a higher birth groundedness
only in domains with externally corroborated, holdout-validated track records.
This fixture proves the Goodhart meta-rail: no credential can be earned by
self-echo, sleeper poison, or generator-chosen domain labels.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnemosyne.credentials import (
    CREDENTIAL_FN_VERSION,
    CredentialPolicy,
    assign_domain_from_provenance,
    birth_groundedness_for_domain,
    build_credential_audit,
    compute_domain_credentials,
)
from mnemosyne.standing import EVIDENCE_DOMINANCE_GAP, SELF_GENERATED_CEILING, standing


DATASET_PATH = Path("eval/datasets/echo_chamber_sleeper_corpus.json")


def run_autonomy_promotion_eval(*, repo_root: Path | None = None) -> dict[str, Any]:
    """Return deterministic P4 earned-autonomy metrics."""

    root = repo_root or Path.cwd()
    dataset_path = root / DATASET_PATH
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    policy = CredentialPolicy()
    train_events = list(dataset.get("train_events") or [])
    holdout_events = list(dataset.get("holdout_events") or [])
    adversarial_events = list(dataset.get("adversarial_events") or [])
    audit = build_credential_audit(
        train_events,
        holdout_events,
        adversarial_rows=adversarial_events,
        policy=policy,
    )
    credentials = compute_domain_credentials(train_events, holdout_events, policy=policy)
    adversarial_credentials = compute_domain_credentials(adversarial_events, adversarial_events, policy=policy)
    base_birth = birth_groundedness_for_domain("unknown", credentials, policy=policy)
    ops_birth = birth_groundedness_for_domain("ops", credentials, policy=policy)
    echo_births = [
        birth_groundedness_for_domain(domain, adversarial_credentials, policy=policy)
        for domain in ("ops", "finance", "unknown")
    ]
    max_echo_birth = max(echo_births or [base_birth])
    ops_self_score = standing(
        {
            "reality_class": "self_generated",
            "trust_tier": 0,
            "calibrated_confidence": 1.0,
            "birth_groundedness": ops_birth,
        }
    )
    external_floor = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 5,
            "calibrated_confidence": 0.0,
            "independent_corroboration_count": 0,
            "independent_corroboration_weight": 0.0,
        }
    )
    evidence_gap = round(external_floor.groundedness - ops_self_score.groundedness, 6)
    mislabel = next(row for row in adversarial_events if row.get("attack") == "domain_mislabel")
    assigned_mislabel_domain = assign_domain_from_provenance(
        mislabel,
        mislabel.get("provenance") if isinstance(mislabel.get("provenance"), dict) else {},
        mislabel.get("outcome") if isinstance(mislabel.get("outcome"), dict) else {},
    )
    metrics = {
        "earned_autonomy_external_expansion": round(max(0.0, ops_birth - base_birth), 6),
        "credential_external_only": audit["credential_external_only"],
        "credential_holdout_validated": audit["credential_holdout_validated"],
        "credential_provenance_domain_contract": 1.0 if assigned_mislabel_domain == "finance" else 0.0,
        "credential_bounded_decay_contract": audit["credential_bounded_decay_contract"],
        "credential_evidence_dominance_gap": evidence_gap,
        "echo_chamber_uplift": round(max(0.0, max_echo_birth - base_birth), 6),
    }
    passed = (
        metrics["earned_autonomy_external_expansion"] > 0.0
        and metrics["credential_external_only"] == 1.0
        and metrics["credential_holdout_validated"] == 1.0
        and metrics["credential_provenance_domain_contract"] == 1.0
        and metrics["credential_bounded_decay_contract"] == 1.0
        and metrics["credential_evidence_dominance_gap"] >= EVIDENCE_DOMINANCE_GAP
        and metrics["echo_chamber_uplift"] == 0.0
        and ops_self_score.groundedness <= SELF_GENERATED_CEILING
    )
    return {
        "schema_version": "g0.autonomy_promotion.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_path": DATASET_PATH.as_posix(),
        "credential_fn_version": CREDENTIAL_FN_VERSION,
        "definition": (
            "Earned-autonomy credentials raise self-thought birth groundedness "
            "only from external holdout corroboration while preserving the "
            "self < external evidence-dominance gap."
        ),
        "measurement_scope": "deterministic local fixture, not production operator evidence",
        "base_birth_groundedness": base_birth,
        "ops_birth_groundedness": ops_birth,
        "ops_self_generated_standing": ops_self_score.to_dict(),
        "external_floor_standing": external_floor.to_dict(),
        "assigned_mislabel_domain": assigned_mislabel_domain,
        "metrics": metrics,
        "credential_audit": audit,
        "passed": passed,
    }
