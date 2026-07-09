from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from eval.provider_bakeoff.run import build_report  # noqa: E402


def _write_slo_report(path: Path, *, recall: float, passed: bool = True) -> None:
    payload = {
        "meta": {"backend": "local", "quick": True},
        "ignition": {"mode": "SHADOW", "suite_size": 25, "ignition_n": 40},
        "overall": {"passed": 2 if passed else 1, "total": 2, "all_pass": passed},
        "slo_suites": [
            {
                "suite": "retrieval",
                "verdicts": [
                    {
                        "name": "recall@k",
                        "value": recall,
                        "target": 0.8,
                        "op": ">=",
                        "pass": passed,
                        "ci": {
                            "point": recall,
                            "ci_low": max(0.0, recall - 0.1),
                            "ci_high": min(1.0, recall + 0.1),
                            "ci_method": "bootstrap",
                        },
                    }
                ],
            }
        ],
        "mandatory_classes": [{"name": "no_degradation_vs_no_memory", "passed": True}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.with_suffix(".md").write_text("# SLO report\n", encoding="utf-8")


def _write_fixture(tmp_path: Path, *, baseline: Path, candidate: Path, promotion_allowed: bool = False) -> Path:
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "protocol": "mnemosyne-provider-bakeoff-v1",
                "purpose": "test fixture",
                "promotion_allowed_from_smoke": promotion_allowed,
                "acceptance": {
                    "non_inferior_required": True,
                    "protected_case_regression_allowed": False,
                    "margin_must_exceed_run_to_run_noise": True,
                    "confidence_intervals_required": True,
                    "public_benchmarks_are_claims": False,
                },
                "arms": [
                    {
                        "name": "baseline",
                        "kind": "baseline",
                        "command": ["python", "eval/run_eval.py"],
                        "report": str(baseline),
                    },
                    {
                        "name": "candidate",
                        "kind": "candidate-smoke",
                        "command": ["python", "eval/run_eval.py"],
                        "report": str(candidate),
                    },
                ],
                "required_evidence": [
                    "baseline_report_json",
                    "candidate_report_json",
                    "baseline_report_markdown",
                    "candidate_report_markdown",
                    "provider_check_report",
                    "noise_or_rerun_notes",
                ],
            }
        ),
        encoding="utf-8",
    )
    return fixture


def test_provider_bakeoff_blocks_smoke_promotion_with_complete_evidence(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_slo_report(baseline, recall=0.82)
    _write_slo_report(candidate, recall=0.83)
    provider_check = tmp_path / "provider-check.json"
    provider_check.write_text(json.dumps({"ok": True, "checks": {"embedding": {"ok": True}}}), encoding="utf-8")
    noise_notes = tmp_path / "noise.md"
    noise_notes.write_text("rerun noise envelope recorded\n", encoding="utf-8")

    report = build_report(
        _write_fixture(tmp_path, baseline=baseline, candidate=candidate),
        provider_check_report=provider_check,
        noise_notes=noise_notes,
        cwd=_REPO,
    )

    assert report["ok"] is True
    assert report["missing_evidence"] == []
    assert report["evidence"]["provider_check_report"] is True
    retrieval_metric = next(
        item for item in report["comparisons"][0]["metrics"] if item["metric"] == "retrieval.curated:recall@k"
    )
    assert retrieval_metric["delta"] > 0
    assert report["promotion"]["allowed"] is False
    assert report["promotion"]["reasons"] == ["fixture_does_not_allow_promotion"]


def test_provider_bakeoff_flags_candidate_regression(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write_slo_report(baseline, recall=0.82, passed=True)
    _write_slo_report(candidate, recall=0.72, passed=False)
    provider_check = tmp_path / "provider-check.json"
    provider_check.write_text(json.dumps({"ok": True}), encoding="utf-8")
    noise_notes = tmp_path / "noise.md"
    noise_notes.write_text("rerun noise envelope recorded\n", encoding="utf-8")

    report = build_report(
        _write_fixture(tmp_path, baseline=baseline, candidate=candidate, promotion_allowed=True),
        provider_check_report=provider_check,
        noise_notes=noise_notes,
        cwd=_REPO,
    )

    assert report["ok"] is False
    assert report["comparisons"][0]["regressions"]
    assert "candidate_regression" in report["promotion"]["reasons"]
    assert any(item["code"] == "candidate_regression" for item in report["findings"])
