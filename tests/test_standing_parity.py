from __future__ import annotations

import json
from pathlib import Path

from eval.g0.standing_parity import run_standing_parity_eval
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.standing import (
    AUTHORITY_THRESHOLD,
    GROUNDED_FLOOR,
    SELF_GENERATED_CEILING,
    STANDING_FN_VERSION,
    standing,
    standing_from_authority_state,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_standing_is_deterministic_and_fails_unknown_closed() -> None:
    signals = {
        "reality_class": "unknown",
        "trust_tier": 5,
        "calibrated_confidence": 1.0,
        "corroboration_count": 5,
        "contradiction_pressure": 0.0,
        "activation": 0.9,
    }
    first = standing(signals).to_dict()
    second = standing(dict(reversed(list(signals.items())))).to_dict()

    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert first["standing_fn_version"] == STANDING_FN_VERSION
    assert first["derived"] is True
    assert first["writes_evidence"] is False
    assert first["authority"] is False
    assert first["value"] < AUTHORITY_THRESHOLD
    assert first["value"] <= SELF_GENERATED_CEILING
    assert first["explain"]["fail_closed"] is True


def test_standing_preserves_banded_monotonicity() -> None:
    weak_grounded = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 4,
            "calibrated_confidence": 0.1,
            "corroboration_count": 0,
            "contradiction_pressure": 0.0,
        }
    )
    strong_grounded = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 0.9,
            "corroboration_count": 5,
            "contradiction_pressure": 0.0,
        }
    )
    contested_grounded = standing(
        {
            "reality_class": "grounded",
            "trust_tier": 0,
            "calibrated_confidence": 0.9,
            "corroboration_count": 5,
            "contradiction_pressure": 1.0,
        }
    )
    high_signal_generated = standing(
        {
            "reality_class": "self_generated",
            "trust_tier": 0,
            "calibrated_confidence": 1.0,
            "corroboration_count": 5,
            "contradiction_pressure": 0.0,
        }
    )

    assert weak_grounded.groundedness >= GROUNDED_FLOOR
    assert strong_grounded.groundedness >= weak_grounded.groundedness
    assert contested_grounded.groundedness <= strong_grounded.groundedness
    assert high_signal_generated.groundedness <= SELF_GENERATED_CEILING
    assert high_signal_generated.authority is False


def test_standing_module_is_pure_projection_surface() -> None:
    source = (REPO_ROOT / "src/mnemosyne/standing.py").read_text(encoding="utf-8")

    assert "mnemosyne.engine" not in source
    assert "LocalMemoryEngine" not in source
    assert "open(" not in source
    assert "subprocess" not in source
    assert "requests" not in source


def test_standing_mirrors_authority_state() -> None:
    advisory = standing_from_authority_state(answer_authority=False, critical_path=False)
    promoted = standing_from_authority_state(answer_authority=True, critical_path=True)

    assert advisory["authority"] is False
    assert advisory["authority_state"]["standing_authority_matches_state"] is True
    assert promoted["authority"] is True
    assert promoted["authority_state"]["standing_authority_matches_state"] is True


def test_local_retrieval_exposes_standing_without_decision_divergence() -> None:
    engine = LocalMemoryEngine()
    tenant = "standing-parity-local-retrieval"
    engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="test",
            actor="system",
            source_type="workspace-reflection",
            source_identity="test:standing-parity",
            content="Standing mirror retrieval abstention alpha was self generated.",
            metadata={"reality_class": "self_generated", "confidence": 0.2},
            trust_tier=5,
            access_policy={"tenant": tenant},
        )
    )

    result = engine.retrieve("Standing mirror retrieval abstention alpha", tenant, filt={"max_trust_tier": 5})
    reality = result.explain["reality_monitoring"]
    standing_report = result.explain["standing"]

    assert standing_report is reality["standing"]
    assert standing_report["standing_fn_version"] == STANDING_FN_VERSION
    assert result.hits
    assert standing_report["abstention_gate"]["active"] == reality["ungrounded_only"]
    assert standing_report["p1_mirror"]["zero_divergence"] is True
    assert result.abstained is True


def test_g0_standing_parity_fixture_reports_zero_divergence() -> None:
    report = run_standing_parity_eval(repo_root=REPO_ROOT)

    assert report["schema_version"] == "g0.standing_parity.v1"
    assert report["standing_fn_version"] == STANDING_FN_VERSION
    assert report["standing_decision_divergence"] == 0.0
    assert report["divergence_count"] == 0
    assert report["passed"] is True
    assert all(row["zero_divergence"] for row in report["retrieval_rows"])
    assert all(row["zero_divergence"] for row in report["consolidation_rows"])
