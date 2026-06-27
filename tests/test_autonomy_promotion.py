from __future__ import annotations

import json
from pathlib import Path

from eval.g0.autonomy_promotion import run_autonomy_promotion_eval
from mnemosyne.credentials import (
    CREDENTIAL_FN_VERSION,
    CredentialPolicy,
    birth_groundedness_for_domain,
    build_credential_audit,
    compute_domain_credentials,
)
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.standing import EVIDENCE_DOMINANCE_GAP, SELF_GENERATED_CEILING, standing


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = REPO_ROOT / "eval/datasets/echo_chamber_sleeper_corpus.json"


def _dataset() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def test_domain_credentials_require_external_holdout_validation() -> None:
    dataset = _dataset()
    credentials = compute_domain_credentials(
        dataset["train_events"],
        dataset["holdout_events"],
        policy=CredentialPolicy(),
    )
    ops = credentials["ops"]

    assert ops.credential_fn_version == CREDENTIAL_FN_VERSION
    assert ops.value > 0.0
    assert ops.holdout_validated is True
    assert ops.external_only is True
    assert ops.provenance_assigned_domain is True
    assert ops.train_event_count >= 2
    assert ops.holdout_event_count >= 2

    base = birth_groundedness_for_domain("unknown", credentials)
    assert ops.birth_groundedness > base


def test_self_echo_sleeper_poison_and_mislabel_do_not_raise_ops_credential() -> None:
    dataset = _dataset()
    adversarial = dataset["adversarial_events"]
    credentials = compute_domain_credentials(adversarial, adversarial, policy=CredentialPolicy())
    audit = build_credential_audit(
        dataset["train_events"],
        dataset["holdout_events"],
        adversarial_rows=adversarial,
        policy=CredentialPolicy(),
    )

    assert birth_groundedness_for_domain("ops", credentials) == birth_groundedness_for_domain("unknown", {})
    assert audit["echo_chamber_uplift"] == 0.0
    rejected_reasons = {row["rejected_reason"] for row in audit["rejected_events"]}
    assert "not_external:self" in rejected_reasons
    assert "shares_self_generated_ancestor" in rejected_reasons


def test_credential_birth_groundedness_stays_inside_self_generated_band() -> None:
    dataset = _dataset()
    credentials = compute_domain_credentials(dataset["train_events"], dataset["holdout_events"])
    birth = birth_groundedness_for_domain("ops", credentials)
    self_score = standing(
        {
            "reality_class": "self_generated",
            "trust_tier": 0,
            "calibrated_confidence": 1.0,
            "birth_groundedness": birth,
        }
    )
    external_min = standing({"reality_class": "grounded", "trust_tier": 5, "calibrated_confidence": 0.0})

    assert self_score.groundedness <= SELF_GENERATED_CEILING
    assert self_score.authority is False
    assert external_min.groundedness - self_score.groundedness >= EVIDENCE_DOMINANCE_GAP
    assert self_score.explain["h11_earned_autonomy_bounded"] is True
    assert self_score.explain["inputs"]["credential_birth_groundedness_applied"] is True


def test_local_retrieval_consumes_earned_autonomy_metadata_without_authority_promotion() -> None:
    dataset = _dataset()
    credentials = compute_domain_credentials(dataset["train_events"], dataset["holdout_events"])
    birth = birth_groundedness_for_domain("ops", credentials)
    engine = LocalMemoryEngine()
    tenant = "earned-autonomy-retrieval"
    engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="test",
            actor="system",
            source_type="workspace-reflection",
            source_identity="test:earned-autonomy",
            content="Earned autonomy hypothesis for ops incident triage.",
            metadata={
                "reality_class": "self_generated",
                "confidence": 1.0,
                "earned_autonomy": {
                    "domain": "ops",
                    "credential_fn_version": CREDENTIAL_FN_VERSION,
                    "birth_groundedness": birth,
                },
            },
            trust_tier=5,
            access_policy={"tenant": tenant},
        )
    )

    result = engine.retrieve("Earned autonomy hypothesis ops incident triage", tenant, filt={"max_trust_tier": 5})
    score = result.hits[0].metadata["standing"]

    assert result.abstained is True
    assert score["groundedness"] <= SELF_GENERATED_CEILING
    assert score["authority"] is False
    assert score["explain"]["inputs"]["credential_birth_groundedness_applied"] is True


def test_g0_autonomy_promotion_fixture_reports_meta_rail_contracts() -> None:
    report = run_autonomy_promotion_eval(repo_root=REPO_ROOT)
    metrics = report["metrics"]

    assert report["schema_version"] == "g0.autonomy_promotion.v1"
    assert report["credential_fn_version"] == CREDENTIAL_FN_VERSION
    assert metrics["earned_autonomy_external_expansion"] > 0.0
    assert metrics["credential_external_only"] == 1.0
    assert metrics["credential_holdout_validated"] == 1.0
    assert metrics["credential_provenance_domain_contract"] == 1.0
    assert metrics["credential_bounded_decay_contract"] == 1.0
    assert metrics["credential_evidence_dominance_gap"] >= EVIDENCE_DOMINANCE_GAP
    assert metrics["echo_chamber_uplift"] == 0.0
    assert report["assigned_mislabel_domain"] == "finance"
    assert report["passed"] is True
