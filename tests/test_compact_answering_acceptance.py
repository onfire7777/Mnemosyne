"""Contract tests for Phase 15 S4 / 15-03-04 physical 8 GiB acceptance.

Fail-closed admission only. These tests lock the receipt ABI and rejection
reasons. They do not admit a measured CAP-011 result or invent host numbers.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from eval.compact_answering.acceptance import (
    CLAIM_STATUS,
    EIGHT_GIB_BYTES,
    PHASE15_S4_8GB_LINUX_REPORT,
    PHASE15_S4_8GB_WINDOWS_REPORT,
    RECEIPT_SCHEMA,
    AcceptanceRejection,
    admit_receipt,
    cap011_status,
    development_stub_receipt,
    evaluate_dual_host,
    pinned_digests,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_WINDOWS = (
    REPO_ROOT / "eval" / "compact_answering" / "reports" / "phase15-s4-8gb-windows.json"
)
COMMITTED_LINUX = (
    REPO_ROOT / "eval" / "compact_answering" / "reports" / "phase15-s4-8gb-linux.json"
)


def _complete_physical_receipt(*, platform: str = "linux") -> dict:
    """In-memory eligible shape used only to mutate fail-closed cases."""
    digests = pinned_digests()
    return {
        "schema": RECEIPT_SCHEMA,
        "receipt_class": "physical-host",
        "official_claim": False,
        "admitted_measurement": False,
        "measured": True,
        "harness_ready": True,
        "claim_status": CLAIM_STATUS,
        "physical": True,
        "host_class": "physical",
        "virtualization": "none",
        "platform": platform,
        "identity": {
            "based_on_sha": "eed2d1f8a531b181665c4d1745b54472df0e7a41",
            "workload": "phase15-s4-8gb-acceptance-v1",
            "host": {
                "os_family": platform,
                "architecture": "x86_64",
                "cpu_flags": ["avx", "avx2", "sse4_2"],
                "physical_memory_bytes": EIGHT_GIB_BYTES,
            },
            "digests": dict(digests),
        },
        "sut_boundary": {
            "included_processes": ["mnemosyne-compact-acceptance"],
            "background_workers": [],
            "hidden_workers": False,
            "benchmark_process_count": 1,
            "host_workload_count": 1,
            "declared_concurrency": 1,
            "observed_concurrency": 1,
        },
        "resources": {
            "before": {
                "total_memory_bytes": EIGHT_GIB_BYTES,
                "available_memory_bytes": 2 * 1024**3,
                "swap_bytes": 0,
            },
            "during": [
                {
                    "total_memory_bytes": EIGHT_GIB_BYTES,
                    "available_memory_bytes": 2 * 1024**3,
                    "swap_bytes": 0,
                }
            ],
            "after": {
                "total_memory_bytes": EIGHT_GIB_BYTES,
                "available_memory_bytes": 2 * 1024**3,
                "swap_bytes": 0,
            },
            "swap_pagefile_delta": 0,
            "model_tokenizer_bytes": 512 * 1024**2,
            "sidecar_peak_bytes": 2 * 1024**3,
            "process_tree_peak_bytes": 5 * 1024**3,
            "min_available_memory_bytes": 2 * 1024**3,
            "first_abort": None,
        },
        "quality": {
            "weakened": False,
            "canonical_receipt": "24/24",
            "em": 1.0,
            "f1": 1.0,
            "recall_at_5": 1.0,
            "ndcg_at_5": 1.0,
            "cap003": True,
            "deterministic_retrieval": True,
            "grounding": True,
            "abstention": True,
            "section_31": True,
            "section_33": True,
            "custody": True,
        },
        "completeness": {
            "cold_load": True,
            "warm_runs": 3,
            "unload_reload": True,
            "raw_traces": True,
        },
        "cap011": {
            "status": "open",
            "closes": False,
            "measured": False,
        },
    }


def _reject_reason(receipt: dict) -> str:
    with pytest.raises(AcceptanceRejection) as caught:
        admit_receipt(receipt)
    return caught.value.reason


def test_rejects_non_physical_receipt() -> None:
    receipt = _complete_physical_receipt()
    receipt["physical"] = False
    receipt["host_class"] = "emulated"
    receipt["virtualization"] = "qemu"
    assert _reject_reason(receipt) == "non_physical"

    hypervisor = _complete_physical_receipt()
    hypervisor["identity"]["host"]["cpu_flags"] = ["avx2", "hypervisor"]
    assert _reject_reason(hypervisor) == "non_physical"

    stub = development_stub_receipt(platform="linux")
    assert _reject_reason(stub) == "non_physical"


def test_rejects_wrong_memory_receipt() -> None:
    receipt = _complete_physical_receipt()
    receipt["identity"]["host"]["physical_memory_bytes"] = 16 * 1024**3
    receipt["resources"]["before"]["total_memory_bytes"] = 16 * 1024**3
    assert _reject_reason(receipt) == "wrong_memory"


def test_rejects_wrong_architecture_receipt() -> None:
    receipt = _complete_physical_receipt()
    receipt["identity"]["host"]["architecture"] = "aarch64"
    assert _reject_reason(receipt) == "wrong_architecture"


def test_rejects_missing_avx2_receipt() -> None:
    receipt = _complete_physical_receipt()
    receipt["identity"]["host"]["cpu_flags"] = ["avx", "sse4_2"]
    assert _reject_reason(receipt) == "missing_avx2"


def test_rejects_hidden_worker_receipt() -> None:
    named = _complete_physical_receipt()
    named["sut_boundary"]["background_workers"] = ["undeclared-reranker"]
    assert _reject_reason(named) == "hidden_worker"

    flagged = _complete_physical_receipt()
    flagged["sut_boundary"]["hidden_workers"] = True
    assert _reject_reason(flagged) == "hidden_worker"

    extra_process = _complete_physical_receipt()
    extra_process["sut_boundary"]["benchmark_process_count"] = 2
    assert _reject_reason(extra_process) == "hidden_worker"

    extra_workload = _complete_physical_receipt()
    extra_workload["sut_boundary"]["host_workload_count"] = 2
    assert _reject_reason(extra_workload) == "hidden_worker"


def test_rejects_digest_mismatch_receipt() -> None:
    receipt = _complete_physical_receipt()
    receipt["identity"]["digests"]["artifact"] = "sha256:" + ("ab" * 32)
    assert _reject_reason(receipt) == "digest_mismatch"


def test_rejects_swap_pagefile_growth_receipt() -> None:
    delta = _complete_physical_receipt()
    delta["resources"]["swap_pagefile_delta"] = 4096
    assert _reject_reason(delta) == "swap_pagefile_growth"

    grew = _complete_physical_receipt()
    grew["resources"]["after"]["swap_bytes"] = 1024
    assert _reject_reason(grew) == "swap_pagefile_growth"


def test_rejects_incomplete_receipt() -> None:
    missing_quality = _complete_physical_receipt()
    del missing_quality["quality"]
    assert _reject_reason(missing_quality) == "incomplete"

    short_warm = _complete_physical_receipt()
    short_warm["completeness"]["warm_runs"] = 2
    short_warm["completeness"]["raw_traces"] = False
    assert _reject_reason(short_warm) == "incomplete"

    no_during = _complete_physical_receipt()
    no_during["resources"]["during"] = []
    assert _reject_reason(no_during) == "incomplete"


def test_rejects_quality_weakened_receipt() -> None:
    lowered = _complete_physical_receipt()
    lowered["quality"]["em"] = 0.9
    lowered["quality"]["f1"] = 0.9
    assert _reject_reason(lowered) == "quality_weakened"

    flagged = _complete_physical_receipt()
    flagged["quality"]["weakened"] = True
    assert _reject_reason(flagged) == "quality_weakened"

    skipped_rail = _complete_physical_receipt()
    skipped_rail["quality"]["section_31"] = False
    assert _reject_reason(skipped_rail) == "quality_weakened"

    drifted = _complete_physical_receipt()
    drifted["quality"]["canonical_receipt"] = "23/24"
    assert _reject_reason(drifted) == "quality_weakened"


def test_eligible_physical_receipt_admits_without_closing_cap011() -> None:
    receipt = _complete_physical_receipt(platform="windows")
    admitted = admit_receipt(receipt)
    assert admitted["admitted"] is True
    assert admitted["reason"] is None
    assert admitted["platform"] == "windows"
    assert admitted["official_claim"] is False
    assert admitted["cap011_closes"] is False
    assert receipt["cap011"]["closes"] is False
    assert receipt["admitted_measurement"] is False


def test_arm64_is_additional_evidence_not_a_required_host() -> None:
    receipt = _complete_physical_receipt()
    receipt["identity"]["host"]["architecture"] = "arm64"
    receipt["platform"] = "linux"
    status = cap011_status(receipt)
    assert status["host_role"] == "additional-arm64"
    assert status["required_host"] is False
    assert _reject_reason(receipt) == "wrong_architecture"


def test_development_stub_is_harness_ready_and_unmeasured() -> None:
    for platform in ("windows", "linux"):
        stub = development_stub_receipt(platform=platform)
        assert stub["schema"] == RECEIPT_SCHEMA
        assert stub["admitted_measurement"] is False
        assert stub["measured"] is False
        assert stub["harness_ready"] is True
        assert stub["claim_status"] == CLAIM_STATUS == "harness-ready-blocked"
        assert stub["official_claim"] is False
        assert stub["physical"] is False
        assert stub["platform"] == platform
        assert stub["cap011"]["status"] == "open"
        assert stub["cap011"]["closes"] is False
        assert stub["cap011"]["measured"] is False
        assert "cap011_remains_open" in stub["blockers"]
        assert "physical_dual_host_measurement_missing" in stub["blockers"]


def test_committed_json_stubs_do_not_close_cap011() -> None:
    assert COMMITTED_WINDOWS == PHASE15_S4_8GB_WINDOWS_REPORT
    assert COMMITTED_LINUX == PHASE15_S4_8GB_LINUX_REPORT
    windows = json.loads(COMMITTED_WINDOWS.read_text(encoding="utf-8"))
    linux = json.loads(COMMITTED_LINUX.read_text(encoding="utf-8"))
    for payload, platform in ((windows, "windows"), (linux, "linux")):
        assert payload["schema"] == RECEIPT_SCHEMA
        assert payload["admitted_measurement"] is False
        assert payload["measured"] is False
        assert payload["harness_ready"] is True
        assert payload["claim_status"] == CLAIM_STATUS
        assert payload["official_claim"] is False
        assert payload["platform"] == platform
        assert payload["cap011"]["closes"] is False
        assert payload["cap011"]["measured"] is False
        for key in ("p50_ms", "p95_ms", "p99_ms"):
            assert key not in payload or payload[key] is None
    dual = evaluate_dual_host(windows, linux)
    assert dual["both_admitted"] is False
    assert dual["cap011_closes"] is False
    assert "cap011_remains_open" in dual["blockers"]


def test_dual_host_requires_both_physical_receipts_and_still_separates_claims() -> None:
    windows = _complete_physical_receipt(platform="windows")
    linux = _complete_physical_receipt(platform="linux")
    dual = evaluate_dual_host(windows, linux)
    assert dual["both_admitted"] is True
    assert dual["cap011_closes"] is False
    assert dual["official_claim"] is False
    assert "physical_dual_host_measured_closure_pending" in dual["blockers"]

    weakened = copy.deepcopy(linux)
    weakened["quality"]["recall_at_5"] = 0.8
    mixed = evaluate_dual_host(windows, weakened)
    assert mixed["both_admitted"] is False
    assert mixed["cap011_closes"] is False
    assert mixed["linux_reason"] == "quality_weakened"
