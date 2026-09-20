#!/usr/bin/env python3
"""CAP-009 / 15-04-02 per-tenant cartridge A/B harness.

Evaluation-only. Binds the unchanged S4 identical-work ABI and resource-receipt
identity, compares tenant-scoped retrieval against an optional offline cartridge,
and emits a redacted receipt with a bounded decision. No model libraries, no
product write path, and no adoption or speedup claim from harness evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.harness.metrics import ndcg_at_k, recall_at_k
from eval.provider_bakeoff.run import (
    CAP006_PROVIDER_SCHEMA,
    PHASE15_S4_PROVIDER_REPORT,
    pinned_identical_workload,
    sample_resources,
)

CAP009_SCHEMA = "mnemosyne.cap009.cartridge-receipt/v1"
RECEIPT_CLASS_SYNTHETIC_DEV = "synthetic-development"
CLAIM_STATUS_SYNTHETIC_DEV = "synthetic-development-receipt-only"
WORKLOAD_ID = "phase15-s5-cartridge-synthetic-dev-v1"
S4_IDENTICAL_WORK_ABI = "eval.provider_bakeoff.run:pinned_identical_workload"
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
PHASE15_S5_CARTRIDGE_REPORT = (
    Path(__file__).resolve().parent / "reports" / "phase15-s5-cartridge.json"
)
RETRIEVAL_BASELINES_PATH = REPO_ROOT / "tests" / "benchmarks" / "baselines.json"
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
PEAK_RESOURCE_FIELDS = (
    "peak_ram_bytes",
    "peak_vram_bytes",
    "disk_bytes",
    "network_bytes",
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
TENANT_SCOPE_SEED = "cap009-dev-scope-v1"
READER_ID = "cap009-synthetic-grounded-reader-v1"
APPROVED_NUMERIC_THRESHOLD = None
WARMUP_COUNT = 1
REPETITIONS = 1
DECLARED_CONCURRENCY = 1
TOP_K = 1


def product_write_path() -> bool:
    return False


def model_import_path() -> bool:
    return False


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_canonical(payload: object) -> str:
    return _sha256_text(_canonical_json(payload))


def _digest_payload(payload: object) -> str:
    return f"sha256:{_sha256_canonical(payload)}"


def _digest_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _git_identity() -> tuple[str, bool]:
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    porcelain = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        text=True,
    )
    return sha, porcelain.strip() == ""


def _cpu_flags() -> list[str]:
    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.exists():
        return []
    for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("flags") or line.startswith("Features"):
            return line.split(":", 1)[1].split()
    return []


def _host_identity() -> dict[str, Any]:
    uname = platform.uname()
    return {
        "os": uname.system,
        "os_release": uname.version,
        "kernel": uname.release,
        "architecture": uname.machine,
        "cpu_flags": _cpu_flags(),
        "accelerator": "none",
        "runtime_versions": {"python": platform.python_version()},
    }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * pct))
    return ordered[idx]


def _interval(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"ci_low": 0.0, "ci_high": 0.0, "ci_method": "synthetic-dev-minmax"}
    return {
        "ci_low": min(values),
        "ci_high": max(values),
        "ci_method": "synthetic-dev-minmax",
    }


def _phase_stats(latencies_ms: list[float]) -> dict[str, Any]:
    total_s = sum(latencies_ms) / 1000.0 if latencies_ms else 0.0
    throughput = (len(latencies_ms) / total_s) if total_s > 0 else 0.0
    return {
        "sample_count": len(latencies_ms),
        "p50_ms": _percentile(latencies_ms, 0.50),
        "p95_ms": _percentile(latencies_ms, 0.95),
        "p99_ms": _percentile(latencies_ms, 0.99),
        "throughput_qps": throughput,
        "mean_ms": statistics.fmean(latencies_ms) if latencies_ms else 0.0,
        "confidence_interval": _interval(latencies_ms),
    }


def _embed(text: str, dims: int) -> list[float]:
    values = [0.0] * dims
    tokens = [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dims
        values[index] += 1.0
    if not tokens:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values[int.from_bytes(digest[:4], "big") % dims] = 1.0
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _assert_never(value: Never) -> Never:
    raise ValueError(f"unhandled variant: {value}")


def _as_outcome(value: str) -> str:
    if value == "success":
        return "success"
    if value == "timeout":
        return "timeout"
    if value == "error":
        return "error"
    return _assert_never(value)  # type: ignore[arg-type]


def _as_decision(value: str) -> str:
    if value == "adopt":
        return "adopt"
    if value == "research-only":
        return "research-only"
    if value == "reject":
        return "reject"
    return _assert_never(value)  # type: ignore[arg-type]


def bind_s4_identical_work() -> dict[str, Any]:
    workload = pinned_identical_workload()
    return {
        "workload_id": workload["workload_id"],
        "workload_digest": workload["workload_digest"],
        "corpus_digest": workload["corpus_digest"],
        "queries_digest": workload["queries_digest"],
        "batching": workload["batching"],
        "dimensions": workload["dimensions"],
        "retrieval_baselines_path": RETRIEVAL_BASELINES_PATH,
        "retrieval_baselines_digest": _digest_bytes(RETRIEVAL_BASELINES_PATH.read_bytes()),
        "provider_schema": CAP006_PROVIDER_SCHEMA,
        "provider_report": PHASE15_S4_PROVIDER_REPORT,
    }


def bind_s4_resource_receipt_identity() -> dict[str, Any]:
    retained = json.loads(PHASE15_S4_PROVIDER_REPORT.read_text(encoding="utf-8"))
    return {
        "schema": retained["schema"],
        "identity_digest": _digest_payload(retained["identity"]),
        "sut_boundary_digest": _digest_payload(retained["sut_boundary"]),
        "resources_digest": _digest_payload(retained["resources"]),
        "provider_receipt_digest": _digest_payload(retained),
        "field_set": list(RESOURCE_SAMPLE_FIELDS),
    }


def _tenant_digest() -> str:
    return _digest_payload(TENANT_SCOPE_SEED)


def _index_corpus(corpus: list[dict[str, Any]], dimensions: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for doc in corpus:
        rows.append(
            {
                "doc_id": str(doc["doc_id"]),
                "vector": _embed(str(doc["text"]), dimensions),
            }
        )
    return rows


def _compile_offline_cartridge(
    rows: list[dict[str, Any]],
    *,
    tenant_digest: str,
    dimensions: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    compiled = {
        "tenant_digest": tenant_digest,
        "dimensions": dimensions,
        "doc_digests": [_digest_payload(row["doc_id"]) for row in rows],
        "vector_digests": [_digest_payload(row["vector"]) for row in rows],
    }
    payload = _canonical_json(compiled).encode("utf-8")
    compile_time_ms = (time.perf_counter() - started) * 1000.0
    return {
        "compile_time_ms": compile_time_ms,
        "artifact_size_bytes": len(payload),
        "artifact_digest": _digest_bytes(payload),
        "tenant_digest": tenant_digest,
        "rows": rows,
    }


def _retrieve(query_text: str, rows: list[dict[str, Any]], *, dims: int) -> list[str]:
    query_vec = _embed(query_text, dims)
    scored = sorted(
        ((_cosine(query_vec, row["vector"]), row["doc_id"]) for row in rows),
        reverse=True,
    )
    return [doc_id for _, doc_id in scored[:TOP_K]]


def _read(retrieved: list[str], relevant: list[str]) -> dict[str, Any]:
    hit = bool(retrieved) and retrieved[0] in relevant
    if hit:
        return {
            "answer_token": f"ans:{retrieved[0]}",
            "abstained": False,
            "citation_tokens": list(retrieved),
        }
    return {
        "answer_token": "abstain",
        "abstained": True,
        "citation_tokens": [],
    }


def _peak_from_samples(samples: list[dict[str, Any]]) -> dict[str, int]:
    rss = [int(sample.get("process_rss_bytes") or 0) for sample in samples]
    vram = [int(sample.get("vram_bytes") or 0) for sample in samples]
    disk = [int(sample.get("disk_bytes") or 0) for sample in samples]
    network = [int(sample.get("network_bytes") or 0) for sample in samples]
    return {
        "peak_ram_bytes": max(rss) if rss else 0,
        "peak_vram_bytes": max(vram) if vram else 0,
        "disk_bytes": max(disk) if disk else 0,
        "network_bytes": max(network) if network else 0,
    }


def _resource_accounting_complete(
    resources: dict[str, Any],
    arms: dict[str, dict[str, Any]],
) -> bool:
    for sample_name in ("before", "after"):
        sample = resources.get(sample_name)
        if not isinstance(sample, dict):
            return False
        if any(field not in sample for field in RESOURCE_SAMPLE_FIELDS):
            return False
    if not resources.get("during"):
        return False
    for field in (
        "memory_pressure",
        "swap_pagefile_delta",
        "disk_index_growth",
        "network_bytes",
        "first_abort",
        *PEAK_RESOURCE_FIELDS,
    ):
        if field not in resources:
            return False
    for arm in arms.values():
        peak = arm.get("resources")
        if not isinstance(peak, dict):
            return False
        if any(field not in peak for field in PEAK_RESOURCE_FIELDS):
            return False
    return True


def scan_report_for_prohibited_content(payload: dict[str, Any]) -> list[str]:
    serialized = _canonical_json(payload)
    lowered = serialized.lower()
    findings: list[str] = []
    for fragment in PROHIBITED_FIXTURE_FRAGMENTS:
        if fragment.lower() in lowered:
            findings.append(f"raw:{fragment}")
    if SECRET_LIKE.search(serialized):
        findings.append("secret-like")
    return findings


def decide_cartridge(receipt: dict[str, Any]) -> dict[str, Any]:
    comparison = receipt.get("comparison") if isinstance(receipt.get("comparison"), dict) else {}
    custody = receipt.get("custody") if isinstance(receipt.get("custody"), dict) else {}
    scan = custody.get("scan") if isinstance(custody.get("scan"), dict) else {}
    identity = receipt.get("identity") if isinstance(receipt.get("identity"), dict) else {}
    arguments = identity.get("arguments") if isinstance(identity.get("arguments"), dict) else {}
    reasons: list[str] = []
    blockers: list[str] = []

    if comparison.get("cross_tenant_reuse") is True:
        reasons.append("cross_tenant_reuse")
    if comparison.get("setup_cost_accounted") is False:
        reasons.append("hidden_setup_cost")
    if comparison.get("raw_secret_persistence") is True or scan.get("secrets") == "fail":
        reasons.append("raw_secret_persistence")
    if comparison.get("identity_bound") is False:
        reasons.append("identity_drift")
    quality_mismatch = (
        comparison.get("retrieval_quality_match") is False
        or comparison.get("answer_equality") is False
        or comparison.get("abstention_equality") is False
        or comparison.get("citation_equality") is False
    )
    if quality_mismatch:
        reasons.append("quality_mismatch")
    if comparison.get("resource_accounting_complete") is False:
        reasons.append("incomplete_resource_accounting")
    if comparison.get("redaction_passed") is False or scan.get("raw_content") == "fail":
        reasons.append("redaction_failure")

    reasons = sorted(set(reasons))
    kind = str(arguments.get("kind") or "measured")
    use_historical = arguments.get("use_historical") is True
    admitted = (
        arguments.get("admitted_measurement") is True
        or receipt.get("admitted_measurement") is True
    )

    if reasons:
        decision = "reject"
        blockers.extend(reasons)
    elif kind == "smoke" or use_historical:
        decision = "research-only"
        blockers.append("smoke_or_historical_does_not_adopt")
        blockers.append("admitted_measurement_missing")
    elif admitted and APPROVED_NUMERIC_THRESHOLD is None:
        decision = "research-only"
        blockers.append("approved_numeric_threshold_absent")
    else:
        decision = "research-only"
        blockers.append("admitted_measurement_missing")
        if APPROVED_NUMERIC_THRESHOLD is None:
            blockers.append("approved_numeric_threshold_absent")

    blockers = sorted(set(blockers))
    return {
        "decision": _as_decision(decision),
        "reasons": reasons,
        "blockers": blockers,
        "product_adoption": False,
        "speedup_asserted": False,
        "numeric_threshold_invented": False,
        "cap_go_no_go_owner": "15-04-05",
    }


def _payload_for_result_digest(receipt: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(_canonical_json(receipt))
    artifacts = payload.get("raw_artifacts")
    if isinstance(artifacts, dict):
        artifacts.pop("result_digest", None)
    return payload


def _bind_raw_artifacts(receipt: dict[str, Any]) -> None:
    receipt["raw_artifacts"] = {
        "observations_sha256": _digest_payload(receipt.get("cases")),
        "workload_sha256": _digest_payload(receipt.get("workload")),
    }
    receipt["raw_artifacts"]["result_digest"] = _digest_payload(
        _payload_for_result_digest(receipt)
    )


def _run_arm(
    *,
    arm_name: str,
    rows: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    dimensions: int,
    inject: dict[str, str],
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    answers: list[str] = []
    abstentions: list[bool] = []
    citations: list[list[str]] = []
    retrieved_rows: list[tuple[list[str], list[str]]] = []
    successes = 0
    timeouts = 0
    errors = 0

    def _observe(phase: str, query: dict[str, Any], *, excluded: bool) -> None:
        nonlocal successes, timeouts, errors
        qid = str(query["qid"])
        issued = time.perf_counter()
        injected = inject.get(qid)
        outcome = "success"
        retrieved: list[str] = []
        relevant = [str(item) for item in query.get("relevant") or []]
        try:
            if injected == "timeout":
                outcome = "timeout"
            elif injected == "error":
                outcome = "error"
            else:
                retrieved = _retrieve(str(query["query"]), rows, dims=dimensions)
        except Exception:  # noqa: BLE001 - retain the failure in the denominator
            outcome = "error"
        ended = time.perf_counter()
        outcome = _as_outcome(outcome)
        if outcome == "success":
            successes += 1
        elif outcome == "timeout":
            timeouts += 1
        elif outcome == "error":
            errors += 1
        else:
            _assert_never(outcome)
        latency_ms = (ended - issued) * 1000.0
        samples.append(sample_resources())
        case_id = _digest_payload({"arm": arm_name, "phase": phase, "qid": qid})
        cases.append({"case_id": case_id, "outcome": outcome, "arm": arm_name})
        observations.append(
            {
                "case_id": case_id,
                "phase": phase,
                "outcome": outcome,
                "latency_ms": latency_ms,
                "excluded": excluded,
            }
        )
        if excluded or outcome != "success":
            return
        read = _read(retrieved, relevant)
        answers.append(str(read["answer_token"]))
        abstentions.append(bool(read["abstained"]))
        citations.append(list(read["citation_tokens"]))
        retrieved_rows.append((retrieved, relevant))

    for query in queries[:WARMUP_COUNT]:
        _observe("warmup", query, excluded=True)
    for query in queries:
        _observe("cold", query, excluded=False)
    for _rep in range(REPETITIONS):
        for query in queries:
            _observe("warm", query, excluded=False)

    issued = successes + timeouts + errors
    cold = [item["latency_ms"] for item in observations if item["phase"] == "cold"]
    warm = [item["latency_ms"] for item in observations if item["phase"] == "warm"]
    recalls = [recall_at_k(retrieved, relevant, TOP_K) for retrieved, relevant in retrieved_rows]
    ndcgs = [ndcg_at_k(retrieved, relevant, TOP_K) for retrieved, relevant in retrieved_rows]
    return {
        "cases": cases,
        "observations": observations,
        "samples": samples,
        "cold": {"separated_from_warm": True, **_phase_stats(cold)},
        "warm": {"separated_from_cold": True, **_phase_stats(warm)},
        "denominators": {
            "issued": issued,
            "successes": successes,
            "timeouts": timeouts,
            "errors": errors,
            "failed_remain_in_denominator": True,
            "denominator_rule": (
                "issued includes every cold/warm/warmup attempt; "
                "latency/throughput/quality exclude warmup and invalid measurements"
            ),
        },
        "quality": {
            "recall_at_k": statistics.fmean(recalls) if recalls else 0.0,
            "ndcg_at_k": statistics.fmean(ndcgs) if ndcgs else 0.0,
            "answer_digest": _digest_payload(answers),
            "abstention_digest": _digest_payload(abstentions),
            "citation_digest": _digest_payload(citations),
        },
        "resources": _peak_from_samples(samples),
    }


def run_cartridge_ab(
    *,
    cross_tenant_reuse: bool = False,
    hide_setup_cost: bool = False,
    persist_raw_secret: bool = False,
    identity_drift: bool = False,
    quality_mismatch: bool = False,
    omit_resource_fields: bool = False,
    leak_raw_content: bool = False,
    inject_outcomes: dict[str, dict[str, str]] | None = None,
    kind: str = "measured",
    use_historical: bool = False,
    admitted_measurement: bool = False,
) -> dict[str, Any]:
    s4 = bind_s4_identical_work()
    s4_identity = bind_s4_resource_receipt_identity()
    raw_workload = pinned_identical_workload()
    tenant_digest = _tenant_digest()
    foreign_tenant_digest = _digest_payload("cap009-dev-scope-other")
    repository_sha, clean_tree = _git_identity()
    utc_start = datetime.now(UTC).isoformat()
    monotonic_start = time.perf_counter()
    before = sample_resources()
    during = [sample_resources()]

    rows = _index_corpus(list(raw_workload["corpus"]), int(raw_workload["dimensions"]))
    cartridge_tenant = foreign_tenant_digest if cross_tenant_reuse else tenant_digest
    compiled = _compile_offline_cartridge(
        rows,
        tenant_digest=cartridge_tenant,
        dimensions=int(raw_workload["dimensions"]),
    )
    injected = inject_outcomes or {}
    baseline_run = _run_arm(
        arm_name="baseline",
        rows=rows,
        queries=list(raw_workload["queries"]),
        dimensions=int(raw_workload["dimensions"]),
        inject=dict(injected.get("baseline") or {}),
    )
    cartridge_run = _run_arm(
        arm_name="cartridge",
        rows=compiled["rows"],
        queries=list(raw_workload["queries"]),
        dimensions=int(raw_workload["dimensions"]),
        inject=dict(injected.get("cartridge") or {}),
    )
    after = sample_resources()
    utc_end = datetime.now(UTC).isoformat()
    monotonic_end = time.perf_counter()
    host = _host_identity()
    all_samples = [before, *during, after, *baseline_run["samples"], *cartridge_run["samples"]]
    peaks = _peak_from_samples(all_samples)
    scoped_corpus_digest = _digest_payload(
        {"tenant_digest": tenant_digest, "corpus": raw_workload["corpus_digest"]}
    )
    scoped_queries_digest = _digest_payload(
        {"tenant_digest": tenant_digest, "queries": raw_workload["queries_digest"]}
    )
    reader_digest = _digest_payload(READER_ID)
    workload_digest = _digest_payload(
        {
            "s4": s4["workload_digest"],
            "tenant_digest": tenant_digest,
            "corpus": scoped_corpus_digest,
            "queries": scoped_queries_digest,
            "reader": reader_digest,
        }
    )
    cartridge_workload_digest = (
        _digest_payload({"drift": True, "base": workload_digest})
        if identity_drift
        else workload_digest
    )
    baseline_quality = dict(baseline_run["quality"])
    cartridge_quality = dict(cartridge_run["quality"])
    answer_equality = baseline_quality["answer_digest"] == cartridge_quality["answer_digest"]
    abstention_equality = (
        baseline_quality["abstention_digest"] == cartridge_quality["abstention_digest"]
    )
    citation_equality = baseline_quality["citation_digest"] == cartridge_quality["citation_digest"]
    retrieval_match = (
        baseline_quality["recall_at_k"] == cartridge_quality["recall_at_k"]
        and baseline_quality["ndcg_at_k"] == cartridge_quality["ndcg_at_k"]
    )
    if quality_mismatch:
        cartridge_quality["recall_at_k"] = 0.0
        cartridge_quality["answer_digest"] = _digest_payload("quality-mismatch")
        answer_equality = False
        retrieval_match = False

    baseline_setup = {
        "hidden": False,
        "excluded_from_query_time": True,
        "compile_time_ms": 0.0,
        "artifact_size_bytes": 0,
    }
    cartridge_setup = {
        "hidden": hide_setup_cost,
        "excluded_from_query_time": not hide_setup_cost,
        "compile_time_ms": float(compiled["compile_time_ms"]),
        "artifact_size_bytes": int(compiled["artifact_size_bytes"]),
    }
    resources: dict[str, Any] = {
        "before": before,
        "during": during,
        "after": after,
        "memory_pressure": (
            0.0
            if after["total_memory_bytes"] == 0
            else 1.0 - (after["available_memory_bytes"] / max(after["total_memory_bytes"], 1))
        ),
        "swap_pagefile_delta": after["swap_bytes"] - before["swap_bytes"],
        "disk_index_growth": 0,
        "network_bytes": peaks["network_bytes"],
        "first_abort": None,
        "peak_ram_bytes": peaks["peak_ram_bytes"],
        "peak_vram_bytes": peaks["peak_vram_bytes"],
        "disk_bytes": peaks["disk_bytes"],
    }
    if omit_resource_fields:
        resources.pop("peak_vram_bytes", None)

    arms = {
        "baseline": {
            "name": "unchanged-s4-retrieval",
            "kind": "s4-retrieval-baseline",
            "workload_digest": workload_digest,
            "tenant_digest": tenant_digest,
            "setup": baseline_setup,
            "cold": baseline_run["cold"],
            "warm": baseline_run["warm"],
            "denominators": baseline_run["denominators"],
            "quality": baseline_quality,
            "resources": baseline_run["resources"],
        },
        "cartridge": {
            "name": "offline-cartridge",
            "kind": "optional-offline-cartridge",
            "workload_digest": cartridge_workload_digest,
            "tenant_digest": tenant_digest if not identity_drift else foreign_tenant_digest,
            "setup": cartridge_setup,
            "cold": cartridge_run["cold"],
            "warm": cartridge_run["warm"],
            "denominators": cartridge_run["denominators"],
            "quality": cartridge_quality,
            "resources": cartridge_run["resources"],
            "artifact_digest": compiled["artifact_digest"],
        },
    }
    accounting_complete = _resource_accounting_complete(resources, arms)
    identity_bound = (
        not identity_drift
        and arms["baseline"]["workload_digest"] == arms["cartridge"]["workload_digest"]
        and arms["baseline"]["tenant_digest"] == arms["cartridge"]["tenant_digest"]
    )
    cases = [*baseline_run["cases"], *cartridge_run["cases"]]
    arguments = {
        "workload": WORKLOAD_ID,
        "kind": kind,
        "use_historical": use_historical,
        "admitted_measurement": admitted_measurement,
        "faults": sorted(
            name
            for name, enabled in (
                ("cross_tenant_reuse", cross_tenant_reuse),
                ("hide_setup_cost", hide_setup_cost),
                ("persist_raw_secret", persist_raw_secret),
                ("identity_drift", identity_drift),
                ("quality_mismatch", quality_mismatch),
                ("omit_resource_fields", omit_resource_fields),
                ("leak_raw_content", leak_raw_content),
            )
            if enabled
        ),
    }
    receipt: dict[str, Any] = {
        "schema": CAP009_SCHEMA,
        "receipt_class": RECEIPT_CLASS_SYNTHETIC_DEV,
        "official_claim": False,
        "admitted_measurement": False,
        "claim_status": CLAIM_STATUS_SYNTHETIC_DEV,
        "product_adoption": False,
        "speedup_asserted": False,
        "cap_go_no_go": "15-04-05",
        "identity": {
            "repository_sha": repository_sha,
            "candidate_sha": repository_sha,
            "clean_tree": clean_tree,
            "command": [sys.executable, "eval/benches/bench_cartridge_ab.py"],
            "arguments": arguments,
            "utc_start": utc_start,
            "utc_end": utc_end,
            "monotonic_start": monotonic_start,
            "monotonic_end": monotonic_end,
            "host": host,
            "digests": {
                "dataset": s4["workload_digest"],
                "fixture": _digest_payload(WORKLOAD_ID),
                "config": _digest_payload(arguments),
                "model": _digest_payload("none-offline-cartridge-harness"),
                "tokenizer": _digest_payload("none"),
                "provider": _digest_payload("s4-retrieval-baseline"),
                "container_image": _digest_payload("none"),
                "schema": _digest_payload(CAP009_SCHEMA),
                "result_contract": _digest_payload("cap009-cartridge-receipt-v1"),
                "hardware_receipt": _digest_payload(host),
                "s4_identical_work": s4["workload_digest"],
                "s4_retrieval_baselines": s4["retrieval_baselines_digest"],
                "s4_provider_receipt": s4_identity["provider_receipt_digest"],
                "s4_resource_receipt_identity": s4_identity["identity_digest"],
            },
            "s4_binding": {
                "identical_work_abi": S4_IDENTICAL_WORK_ABI,
                "workload_digest": s4["workload_digest"],
                "retrieval_baselines_digest": s4["retrieval_baselines_digest"],
                "provider_receipt_digest": s4_identity["provider_receipt_digest"],
                "resource_receipt_identity": s4_identity["identity_digest"],
            },
        },
        "sut_boundary": {
            "included_processes": ["synthetic-dev-cartridge-ab"],
            "containers": [],
            "databases": [],
            "proxies": [],
            "caches": [],
            "indexes": [],
            "filesystems": ["workspace"],
            "background_workers": [],
            "benchmark_process_count": 1,
            "host_workload_count": 1,
        },
        "workload": {
            "workload_id": WORKLOAD_ID,
            "tenant_scoped": True,
            "tenant_id_omitted": True,
            "tenant_digest": tenant_digest,
            "corpus_digest": scoped_corpus_digest,
            "queries_digest": scoped_queries_digest,
            "reader_digest": reader_digest,
            "identical_across_arms": not identity_drift,
            "warmup": {
                "explicit": True,
                "excluded_from_distribution": True,
                "count": WARMUP_COUNT,
            },
            "repetitions": REPETITIONS,
            "concurrency": {
                "declared_max_in_flight": DECLARED_CONCURRENCY,
                "observed_max_in_flight": DECLARED_CONCURRENCY,
                "declared_overlap": False,
                "observed_overlap": False,
                "matches_declaration": True,
                "worker_count": 1,
            },
            "budgets": {
                "time_limit_s": 30,
                "case_limit": 32,
                "memory_limit_mb": 512,
                "vram_limit_mb": 0,
                "disk_limit_mb": 64,
                "network_limit_bytes": 0,
            },
        },
        "arms": arms,
        "query_time": {
            "includes_setup": hide_setup_cost,
            "includes_compile": hide_setup_cost,
            "duration_ms": (
                baseline_run["cold"]["mean_ms"]
                + baseline_run["warm"]["mean_ms"]
                + cartridge_run["cold"]["mean_ms"]
                + cartridge_run["warm"]["mean_ms"]
            ),
        },
        "comparison": {
            "identical_work": not identity_drift and not cross_tenant_reuse,
            "answer_equality": answer_equality,
            "abstention_equality": abstention_equality,
            "citation_equality": citation_equality,
            "retrieval_quality_match": retrieval_match,
            "identity_bound": identity_bound,
            "setup_cost_accounted": not hide_setup_cost,
            "resource_accounting_complete": accounting_complete,
            "cross_tenant_reuse": cross_tenant_reuse,
            "raw_secret_persistence": persist_raw_secret,
            "redaction_passed": not leak_raw_content,
        },
        "aggregates": {
            "baseline_warm_p95_ms": baseline_run["warm"]["p95_ms"],
            "cartridge_warm_p95_ms": cartridge_run["warm"]["p95_ms"],
            "baseline_recall_at_k": baseline_quality["recall_at_k"],
            "cartridge_recall_at_k": cartridge_quality["recall_at_k"],
            "compile_time_ms": cartridge_setup["compile_time_ms"],
            "artifact_size_bytes": cartridge_setup["artifact_size_bytes"],
        },
        "cases": cases,
        "diagnostics": [
            {"code": code, "detail": "redacted"}
            for code in arguments["faults"]
        ],
        "resources": resources,
        "custody": {
            "redacted": True,
            "class": "synthetic-development",
            "consent": "authored-from-scratch",
            "raw_content_omitted": True,
            "tenant_identifiers_omitted": True,
            "secrets_omitted": True,
            "scan": {
                "raw_content": "fail" if leak_raw_content else "pass",
                "secrets": "fail" if persist_raw_secret else "pass",
            },
        },
        "denominators": {
            "issued": (
                baseline_run["denominators"]["issued"] + cartridge_run["denominators"]["issued"]
            ),
            "successes": (
                baseline_run["denominators"]["successes"]
                + cartridge_run["denominators"]["successes"]
            ),
            "timeouts": (
                baseline_run["denominators"]["timeouts"] + cartridge_run["denominators"]["timeouts"]
            ),
            "errors": (
                baseline_run["denominators"]["errors"] + cartridge_run["denominators"]["errors"]
            ),
            "failed_remain_in_denominator": True,
            "denominator_rule": (
                "attempt/failure/coverage include every issued case; "
                "latency, throughput, and quality exclude warmup and invalid measurements"
            ),
        },
    }
    receipt["decision"] = decide_cartridge(receipt)
    findings = scan_report_for_prohibited_content(receipt)
    if findings:
        receipt["custody"]["scan"]["raw_content"] = "fail"
        receipt["comparison"]["redaction_passed"] = False
        receipt["decision"] = decide_cartridge(receipt)
    _bind_raw_artifacts(receipt)
    return receipt


def write_phase15_s5_cartridge_receipt(
    receipt: dict[str, Any] | None = None,
    path: Path | None = None,
) -> Path:
    target = Path(path) if path is not None else PHASE15_S5_CARTRIDGE_REPORT
    payload = receipt if receipt is not None else run_cartridge_ab()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> int:
    path = write_phase15_s5_cartridge_receipt()
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
