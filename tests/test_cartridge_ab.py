"""15-04-02 contract tests for the CAP-009 per-tenant cartridge A/B harness.

These tests freeze the evaluation-only receipt: identical tenant-scoped work,
complete setup/quality/resource/custody/failure/identity accounting, redaction
after raw-content and secret scans, and a bounded decision only. They do not
import model libraries, write product memory, or assert product adoption.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import pytest

from eval.provider_bakeoff.run import (
    CAP006_PROVIDER_SCHEMA,
    PHASE15_S4_PROVIDER_REPORT,
    pinned_identical_workload,
)
from eval.harness.metrics import ndcg_at_k, recall_at_k

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCH_PATH = REPO_ROOT / "eval" / "benches" / "bench_cartridge_ab.py"
COMMITTED_REPORT = (
    REPO_ROOT / "eval" / "benches" / "reports" / "phase15-s5-cartridge.json"
)
S4_RETRIEVAL_BASELINES = REPO_ROOT / "tests" / "benchmarks" / "baselines.json"
ALLOWED_DECISIONS = frozenset({"adopt", "research-only", "reject"})
FORBIDDEN_MODEL_MODULES = (
    "torch",
    "transformers",
    "safetensors",
    "accelerate",
    "vllm",
    "llama_cpp",
    "gguf",
    "sentence_transformers",
)
RESOURCE_SAMPLE_FIELDS = (
    "total_memory_bytes",
    "free_memory_bytes",
    "available_memory_bytes",
    "swap_bytes",
    "process_rss_bytes",
    "process_pss_or_working_set_bytes",
    "vram_bytes",
    "disk_bytes",
    "network_bytes",
    "load_averages",
    "cpu_seconds",
)
PROHIBITED_FIXTURE_FRAGMENTS = (
    "Paris is the capital of France",
    "Berlin is the capital of Germany",
    "Tokyo is the capital of Japan",
    "Ottawa is the capital of Canada",
    "capital of France",
    "capital of Germany",
    "capital of Japan",
    "capital of Canada",
    "cartridge-tenant",
    "tenant-id",
    "sk-",
    "AKIA",
    "api_key",
    "BEGIN PRIVATE KEY",
)
SECRET_LIKE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|BEGIN PRIVATE KEY|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_canonical(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _import_bench():
    from eval.benches import bench_cartridge_ab as bench

    return bench


def _assert_digest(value: object, *, field: str) -> str:
    assert isinstance(value, str) and value.startswith("sha256:"), field
    digest = value.removeprefix("sha256:")
    assert len(digest) == 64, field
    assert digest != "0" * 64, field
    return digest


def _walk_strings(payload: object) -> list[str]:
    found: list[str] = []
    if isinstance(payload, str):
        found.append(payload)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            found.append(str(key))
            found.extend(_walk_strings(value))
    elif isinstance(payload, list | tuple):
        for item in payload:
            found.extend(_walk_strings(item))
    return found


def _assert_redaction_safe(payload: dict[str, Any]) -> None:
    serialized = _canonical_json(payload)
    lowered = serialized.lower()
    for fragment in PROHIBITED_FIXTURE_FRAGMENTS:
        assert fragment.lower() not in lowered, f"prohibited fixture leaked: {fragment}"
    assert SECRET_LIKE.search(serialized) is None
    for key in ("prompt", "prompts", "corpus", "answer", "answers", "citation", "citations"):
        assert key not in payload
    workload = payload.get("workload")
    if isinstance(workload, dict):
        for forbidden in ("corpus", "queries", "prompts", "answers", "citations", "tenant_id"):
            assert forbidden not in workload
    for text in _walk_strings(payload):
        assert "Paris" not in text
        assert "tenant-" not in text.lower() or "tenant_digest" in text or "tenant_scoped" in text


def test_harness_does_not_import_model_libraries() -> None:
    tree = ast.parse(BENCH_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(FORBIDDEN_MODEL_MODULES)
    bench = _import_bench()
    assert bench.FORBIDDEN_MODEL_MODULES == FORBIDDEN_MODEL_MODULES
    assert bench.product_write_path() is False
    assert bench.model_import_path() is False


def test_s4_identical_work_abi_is_bound_unchanged() -> None:
    bench = _import_bench()
    s4 = pinned_identical_workload()
    bound = bench.bind_s4_identical_work()
    assert bound["workload_id"] == s4["workload_id"]
    assert bound["workload_digest"] == s4["workload_digest"]
    assert bound["corpus_digest"] == s4["corpus_digest"]
    assert bound["queries_digest"] == s4["queries_digest"]
    assert bound["batching"] == s4["batching"]
    assert bound["dimensions"] == s4["dimensions"]
    assert bound["retrieval_baselines_path"] == S4_RETRIEVAL_BASELINES
    assert bound["retrieval_baselines_digest"] == (
        "sha256:" + hashlib.sha256(S4_RETRIEVAL_BASELINES.read_bytes()).hexdigest()
    )
    assert bound["provider_schema"] == CAP006_PROVIDER_SCHEMA
    assert bound["provider_report"] == PHASE15_S4_PROVIDER_REPORT
    assert "corpus" not in bound
    assert "queries" not in bound
    receipt = bench.run_cartridge_ab()
    identity = receipt["identity"]
    assert identity["s4_binding"]["identical_work_abi"] == (
        "eval.provider_bakeoff.run:pinned_identical_workload"
    )
    assert identity["s4_binding"]["workload_digest"] == s4["workload_digest"]
    assert identity["s4_binding"]["retrieval_baselines_digest"] == bound[
        "retrieval_baselines_digest"
    ]
    assert identity["digests"]["s4_identical_work"] == s4["workload_digest"]


def test_s4_resource_receipt_identity_is_bound() -> None:
    bench = _import_bench()
    bound = bench.bind_s4_resource_receipt_identity()
    for field in (
        "schema",
        "identity_digest",
        "sut_boundary_digest",
        "resources_digest",
        "provider_receipt_digest",
        "field_set",
    ):
        assert field in bound
    _assert_digest(bound["identity_digest"], field="identity_digest")
    _assert_digest(bound["sut_boundary_digest"], field="sut_boundary_digest")
    _assert_digest(bound["resources_digest"], field="resources_digest")
    _assert_digest(bound["provider_receipt_digest"], field="provider_receipt_digest")
    assert set(RESOURCE_SAMPLE_FIELDS) <= set(bound["field_set"])
    receipt = bench.run_cartridge_ab()
    assert (
        receipt["identity"]["s4_binding"]["resource_receipt_identity"]
        == bound["identity_digest"]
    )
    assert receipt["identity"]["digests"]["s4_resource_receipt_identity"] == bound[
        "identity_digest"
    ]


def test_identical_tenant_scoped_work_across_arms() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab()
    workload = receipt["workload"]
    assert workload["tenant_scoped"] is True
    assert workload["tenant_id_omitted"] is True
    _assert_digest(workload["tenant_digest"], field="tenant_digest")
    _assert_digest(workload["corpus_digest"], field="corpus_digest")
    _assert_digest(workload["queries_digest"], field="queries_digest")
    _assert_digest(workload["reader_digest"], field="reader_digest")
    assert workload["identical_across_arms"] is True
    warmup = workload["warmup"]
    assert warmup["explicit"] is True
    assert warmup["excluded_from_distribution"] is True
    assert warmup["count"] >= 1
    assert workload["repetitions"] >= 1
    concurrency = workload["concurrency"]
    assert concurrency["declared_max_in_flight"] >= 1
    assert concurrency["observed_max_in_flight"] >= 1
    assert "matches_declaration" in concurrency
    assert receipt["sut_boundary"]["benchmark_process_count"] == 1
    assert receipt["sut_boundary"]["host_workload_count"] == 1
    arms = receipt["arms"]
    assert set(arms) == {"baseline", "cartridge"}
    assert arms["baseline"]["kind"] == "s4-retrieval-baseline"
    assert arms["cartridge"]["kind"] == "optional-offline-cartridge"
    assert arms["baseline"]["workload_digest"] == arms["cartridge"]["workload_digest"]
    assert arms["baseline"]["tenant_digest"] == arms["cartridge"]["tenant_digest"]
    assert receipt["comparison"]["identical_work"] is True


def test_setup_compile_time_and_artifact_size_are_accounted() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab()
    cartridge = receipt["arms"]["cartridge"]
    setup = cartridge["setup"]
    assert setup["hidden"] is False
    assert setup["excluded_from_query_time"] is True
    assert isinstance(setup["compile_time_ms"], int | float)
    assert math.isfinite(float(setup["compile_time_ms"]))
    assert float(setup["compile_time_ms"]) >= 0
    assert isinstance(setup["artifact_size_bytes"], int)
    assert setup["artifact_size_bytes"] >= 0
    query = receipt["query_time"]
    assert query["includes_setup"] is False
    assert query["includes_compile"] is False
    baseline_setup = receipt["arms"]["baseline"]["setup"]
    assert baseline_setup["excluded_from_query_time"] is True
    assert receipt["comparison"]["setup_cost_accounted"] is True


def test_cold_warm_latency_throughput_intervals_and_failures() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab()
    for arm in receipt["arms"].values():
        for phase_name in ("cold", "warm"):
            phase = arm[phase_name]
            assert phase["separated_from_warm" if phase_name == "cold" else "separated_from_cold"] is True
            assert phase["sample_count"] >= 1
            for stat in ("p50_ms", "p95_ms", "p99_ms", "throughput_qps"):
                assert isinstance(phase[stat], int | float)
                assert math.isfinite(float(phase[stat]))
            interval = phase["confidence_interval"]
            assert "ci_low" in interval and "ci_high" in interval
            assert interval["ci_method"]
        assert arm["cold"]["sample_count"] >= 1
        assert arm["warm"]["sample_count"] >= 1
        denominators = arm["denominators"]
        assert denominators["issued"] == (
            denominators["successes"] + denominators["timeouts"] + denominators["errors"]
        )
        assert denominators["failed_remain_in_denominator"] is True
        assert denominators["denominator_rule"]
    cases = receipt["cases"]
    assert cases
    case_ids = [row["case_id"] for row in cases]
    assert len(case_ids) == len(set(case_ids))
    for row in cases:
        _assert_digest(row["case_id"], field="case_id")
        assert row["outcome"] in {"success", "timeout", "error"}
        assert row["arm"] in {"baseline", "cartridge"}
        assert "prompt" not in row
        assert "answer" not in row
        assert "citation" not in row


def test_quality_and_custody_fields_are_digest_only() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab()
    comparison = receipt["comparison"]
    for field in (
        "answer_equality",
        "abstention_equality",
        "citation_equality",
        "retrieval_quality_match",
    ):
        assert comparison[field] is True
    for arm in receipt["arms"].values():
        quality = arm["quality"]
        assert 0.0 <= quality["recall_at_k"] <= 1.0
        assert 0.0 <= quality["ndcg_at_k"] <= 1.0
        _assert_digest(quality["answer_digest"], field="answer_digest")
        _assert_digest(quality["abstention_digest"], field="abstention_digest")
        _assert_digest(quality["citation_digest"], field="citation_digest")
        assert "answers" not in quality
        assert "citations" not in quality
    assert recall_at_k(["d1"], ["d1"], 1) == 1.0
    assert ndcg_at_k(["d1"], ["d1"], 1) == 1.0
    custody = receipt["custody"]
    assert custody["redacted"] is True
    assert custody["raw_content_omitted"] is True
    assert custody["tenant_identifiers_omitted"] is True
    assert custody["secrets_omitted"] is True
    assert custody["scan"]["raw_content"] == "pass"
    assert custody["scan"]["secrets"] == "pass"
    assert custody["class"]
    assert custody["consent"]


def test_resource_accounting_and_identity_are_complete() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab()
    resources = receipt["resources"]
    for sample_name in ("before", "after"):
        sample = resources[sample_name]
        for field in RESOURCE_SAMPLE_FIELDS:
            assert field in sample, field
    assert resources["during"]
    for field in (
        "memory_pressure",
        "swap_pagefile_delta",
        "disk_index_growth",
        "network_bytes",
        "first_abort",
        "peak_ram_bytes",
        "peak_vram_bytes",
        "disk_bytes",
        "network_bytes",
    ):
        assert field in resources, field
    for arm in receipt["arms"].values():
        peak = arm["resources"]
        for field in ("peak_ram_bytes", "peak_vram_bytes", "disk_bytes", "network_bytes"):
            assert field in peak
            assert isinstance(peak[field], int | float)
            assert math.isfinite(float(peak[field]))
    identity = receipt["identity"]
    assert len(identity["repository_sha"]) == 40
    assert len(identity["candidate_sha"]) == 40
    assert identity["candidate_sha"] == identity["repository_sha"]
    assert isinstance(identity["clean_tree"], bool)
    assert identity["command"]
    assert Path(str(identity["command"][-1])).name == "bench_cartridge_ab.py"
    host = identity["host"]
    for field in (
        "os",
        "os_release",
        "kernel",
        "architecture",
        "cpu_flags",
        "accelerator",
        "runtime_versions",
    ):
        assert field in host
    for field in (
        "dataset",
        "fixture",
        "config",
        "model",
        "tokenizer",
        "provider",
        "container_image",
        "schema",
        "result_contract",
        "hardware_receipt",
        "s4_identical_work",
        "s4_retrieval_baselines",
        "s4_provider_receipt",
        "s4_resource_receipt_identity",
    ):
        _assert_digest(identity["digests"][field], field=field)
    assert receipt["comparison"]["resource_accounting_complete"] is True
    assert receipt["comparison"]["identity_bound"] is True
    raw = receipt["raw_artifacts"]
    for field in ("observations_sha256", "workload_sha256", "result_digest"):
        _assert_digest(raw[field], field=field)
    complete = json.loads(_canonical_json(receipt))
    complete["raw_artifacts"].pop("result_digest", None)
    assert raw["result_digest"] == "sha256:" + _sha256_canonical(complete)


def test_injected_failures_remain_in_denominators() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab(
        inject_outcomes={"baseline": {"q_capital_france": "timeout", "q_capital_germany": "error"}}
    )
    baseline = receipt["arms"]["baseline"]
    denominators = baseline["denominators"]
    assert denominators["timeouts"] >= 1
    assert denominators["errors"] >= 1
    assert denominators["issued"] == (
        denominators["successes"] + denominators["timeouts"] + denominators["errors"]
    )
    outcomes = {row["outcome"] for row in receipt["cases"] if row["arm"] == "baseline"}
    assert "timeout" in outcomes
    assert "error" in outcomes
    assert denominators["failed_remain_in_denominator"] is True


def test_rejects_cross_tenant_reuse() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab(cross_tenant_reuse=True)
    assert receipt["decision"]["decision"] == "reject"
    assert "cross_tenant_reuse" in receipt["decision"]["reasons"]
    assert receipt["comparison"]["cross_tenant_reuse"] is True
    assert receipt["decision"]["product_adoption"] is False


def test_rejects_hidden_setup_cost() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab(hide_setup_cost=True)
    assert receipt["decision"]["decision"] == "reject"
    assert "hidden_setup_cost" in receipt["decision"]["reasons"]
    assert receipt["comparison"]["setup_cost_accounted"] is False


def test_rejects_raw_secret_persistence() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab(persist_raw_secret=True)
    assert receipt["decision"]["decision"] == "reject"
    assert "raw_secret_persistence" in receipt["decision"]["reasons"]
    assert receipt["custody"]["scan"]["secrets"] == "fail"
    assert receipt["comparison"]["raw_secret_persistence"] is True
    _assert_redaction_safe(receipt)


def test_rejects_identity_drift() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab(identity_drift=True)
    assert receipt["decision"]["decision"] == "reject"
    assert "identity_drift" in receipt["decision"]["reasons"]
    assert receipt["comparison"]["identity_bound"] is False


def test_rejects_quality_mismatch() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab(quality_mismatch=True)
    assert receipt["decision"]["decision"] == "reject"
    assert "quality_mismatch" in receipt["decision"]["reasons"]
    assert receipt["comparison"]["retrieval_quality_match"] is False or (
        receipt["comparison"]["answer_equality"] is False
        or receipt["comparison"]["abstention_equality"] is False
        or receipt["comparison"]["citation_equality"] is False
    )


def test_rejects_incomplete_resource_accounting() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab(omit_resource_fields=True)
    assert receipt["decision"]["decision"] == "reject"
    assert "incomplete_resource_accounting" in receipt["decision"]["reasons"]
    assert receipt["comparison"]["resource_accounting_complete"] is False


def test_rejects_redaction_failure() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab(leak_raw_content=True)
    assert receipt["decision"]["decision"] == "reject"
    assert "redaction_failure" in receipt["decision"]["reasons"]
    assert receipt["custody"]["scan"]["raw_content"] == "fail"
    assert receipt["comparison"]["redaction_passed"] is False
    _assert_redaction_safe(receipt)


def test_healthy_receipt_is_redaction_safe_and_research_only() -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab()
    assert receipt["schema"] == bench.CAP009_SCHEMA
    assert receipt["receipt_class"] == "synthetic-development"
    assert receipt["official_claim"] is False
    assert receipt["admitted_measurement"] is False
    assert receipt["product_adoption"] is False
    assert receipt["speedup_asserted"] is False
    assert receipt["cap_go_no_go"] == "15-04-05"
    decision = receipt["decision"]
    assert decision["decision"] in ALLOWED_DECISIONS
    assert decision["decision"] == "research-only"
    assert decision["product_adoption"] is False
    assert decision["speedup_asserted"] is False
    assert decision["numeric_threshold_invented"] is False
    assert decision["cap_go_no_go_owner"] == "15-04-05"
    assert "admitted_measurement_missing" in decision["blockers"]
    replay = bench.decide_cartridge(receipt)
    assert replay == decision
    _assert_redaction_safe(receipt)
    findings = bench.scan_report_for_prohibited_content(receipt)
    assert findings == []


def test_harness_never_adopts_from_smoke_or_historical_evidence() -> None:
    bench = _import_bench()
    smoke = bench.run_cartridge_ab(kind="smoke")
    historical = bench.run_cartridge_ab(use_historical=True)
    admitted_without_threshold = bench.run_cartridge_ab(admitted_measurement=True)
    for receipt in (smoke, historical, admitted_without_threshold):
        assert receipt["decision"]["decision"] != "adopt"
        assert receipt["decision"]["product_adoption"] is False
        assert receipt["decision"]["speedup_asserted"] is False
        assert receipt["speedup_asserted"] is False
    assert "smoke_or_historical_does_not_adopt" in smoke["decision"]["blockers"]
    assert "smoke_or_historical_does_not_adopt" in historical["decision"]["blockers"]
    assert admitted_without_threshold["decision"]["decision"] == "research-only"
    assert "approved_numeric_threshold_absent" in admitted_without_threshold["decision"][
        "blockers"
    ]


def test_committed_report_is_scanned_redacted_and_bounded() -> None:
    bench = _import_bench()
    assert COMMITTED_REPORT == bench.PHASE15_S5_CARTRIDGE_REPORT
    assert COMMITTED_REPORT.is_file()
    payload = json.loads(COMMITTED_REPORT.read_text(encoding="utf-8"))
    assert payload["schema"] == bench.CAP009_SCHEMA
    assert payload["receipt_class"] == "synthetic-development"
    assert payload["official_claim"] is False
    assert payload["admitted_measurement"] is False
    assert payload["product_adoption"] is False
    assert payload["speedup_asserted"] is False
    assert payload["cap_go_no_go"] == "15-04-05"
    assert payload["decision"]["decision"] in ALLOWED_DECISIONS
    assert payload["decision"]["decision"] != "adopt"
    assert payload["decision"]["product_adoption"] is False
    assert payload["decision"]["speedup_asserted"] is False
    assert payload["decision"]["numeric_threshold_invented"] is False
    assert payload["decision"]["cap_go_no_go_owner"] == "15-04-05"
    assert payload["custody"]["scan"]["raw_content"] == "pass"
    assert payload["custody"]["scan"]["secrets"] == "pass"
    _assert_redaction_safe(payload)
    assert bench.scan_report_for_prohibited_content(payload) == []
    identity = payload["identity"]
    assert identity["s4_binding"]["identical_work_abi"] == (
        "eval.provider_bakeoff.run:pinned_identical_workload"
    )
    _assert_digest(identity["s4_binding"]["workload_digest"], field="workload_digest")
    _assert_digest(
        identity["s4_binding"]["resource_receipt_identity"],
        field="resource_receipt_identity",
    )


@pytest.mark.parametrize(
    "fault",
    (
        "cross_tenant_reuse",
        "hide_setup_cost",
        "persist_raw_secret",
        "identity_drift",
        "quality_mismatch",
        "omit_resource_fields",
        "leak_raw_content",
    ),
)
def test_fault_receipts_remain_redaction_safe(fault: str) -> None:
    bench = _import_bench()
    receipt = bench.run_cartridge_ab(**{fault: True})
    assert receipt["decision"]["decision"] == "reject"
    _assert_redaction_safe(receipt)
    assert bench.scan_report_for_prohibited_content(receipt) == []
