#!/usr/bin/env python3
"""Provider bake-off evidence harness.

This is a measurement/evidence wrapper around the existing eval harness and
``mneme provider-check``. It never changes provider defaults.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import resource as resource_mod
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_PROTOCOL = "mnemosyne-provider-bakeoff-report-v1"
CAP006_PROVIDER_SCHEMA = "mnemosyne.cap006.provider-receipt/v1"
RECEIPT_CLASS_SYNTHETIC_DEV = "synthetic-development"
CLAIM_STATUS_SYNTHETIC_DEV = "synthetic-development-receipt-only"
SYNTHETIC_PROVIDER_WORKLOAD_ID = "phase15-s4-provider-synthetic-dev-v1"
DEFAULT_FIXTURE = Path(__file__).with_name("sidecar-local-smoke.json")
PHASE15_S4_PROVIDER_REPORT = Path(__file__).resolve().parent / "reports" / "phase15-s4-provider.json"
PINNED_DIMENSIONS = 1024
PINNED_BATCH_SIZE = 2
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_LICENSE_STATUSES = ("verified", "missing", "rejected", "unverifiable")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"failed to read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return payload


def _resolve_path(value: str | os.PathLike[str], *, base: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base / path).resolve()


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_canonical(payload: object) -> str:
    return _sha256_text(_canonical_json(payload))


def _digest_payload(payload: object) -> str:
    return f"sha256:{_sha256_canonical(payload)}"


def _digest_pinned(value: object) -> bool:
    return isinstance(value, str) and bool(_DIGEST_RE.fullmatch(value))


def _git_identity() -> tuple[str, bool]:
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=_repo_root(),
        text=True,
    ).strip()
    porcelain = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=_repo_root(),
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


def _pss_or_working_set_bytes(rss_bytes: int) -> int:
    rollup = Path("/proc/self/smaps_rollup")
    if rollup.exists():
        for line in rollup.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Pss:"):
                parts = line.split()
                return int(parts[1]) * 1024
    return rss_bytes


def _meminfo_bytes() -> dict[str, int]:
    parsed: dict[str, int] = {}
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return parsed
    for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
        name, _, rest = line.partition(":")
        token = rest.strip().split()
        if not token:
            continue
        try:
            parsed[name] = int(token[0]) * 1024
        except ValueError:
            continue
    return parsed


def sample_resources() -> dict[str, Any]:
    mem = _meminfo_bytes()
    usage = resource_mod.getrusage(resource_mod.RUSAGE_SELF)
    rss_bytes = int(usage.ru_maxrss) * 1024
    load = list(os.getloadavg()) if hasattr(os, "getloadavg") else [0.0, 0.0, 0.0]
    swap_used = max(0, mem.get("SwapTotal", 0) - mem.get("SwapFree", 0))
    return {
        "sampled_monotonic": time.perf_counter(),
        "total_memory_bytes": mem.get("MemTotal", 0),
        "free_memory_bytes": mem.get("MemFree", 0),
        "available_memory_bytes": mem.get("MemAvailable", 0),
        "swap_bytes": swap_used,
        "process_rss_bytes": rss_bytes,
        "process_pss_or_working_set_bytes": _pss_or_working_set_bytes(rss_bytes),
        "vram_bytes": 0,
        "disk_bytes": 0,
        "network_bytes": 0,
        "load_averages": load,
        "cpu_seconds": usage.ru_utime + usage.ru_stime,
    }


def pinned_identical_workload() -> dict[str, Any]:
    corpus = [
        {"doc_id": "d_france", "text": "Paris is the capital of France."},
        {"doc_id": "d_germany", "text": "Berlin is the capital of Germany."},
        {"doc_id": "d_japan", "text": "Tokyo is the capital of Japan."},
        {"doc_id": "d_canada", "text": "Ottawa is the capital of Canada."},
    ]
    queries = [
        {"qid": "q_capital_france", "query": "capital of France", "relevant": ["d_france"]},
        {"qid": "q_capital_germany", "query": "capital of Germany", "relevant": ["d_germany"]},
        {"qid": "q_capital_japan", "query": "capital of Japan", "relevant": ["d_japan"]},
        {"qid": "q_capital_canada", "query": "capital of Canada", "relevant": ["d_canada"]},
    ]
    batching = {"size": PINNED_BATCH_SIZE, "order": "document-then-query"}
    dimensions = PINNED_DIMENSIONS
    workload = {
        "workload_id": SYNTHETIC_PROVIDER_WORKLOAD_ID,
        "corpus": corpus,
        "queries": queries,
        "batching": batching,
        "dimensions": dimensions,
        "corpus_digest": _digest_payload(corpus),
        "queries_digest": _digest_payload(queries),
        "batching_digest": _digest_payload(batching),
        "dimensions_digest": _digest_payload(dimensions),
    }
    workload["workload_digest"] = _digest_payload(
        {
            "corpus": workload["corpus_digest"],
            "queries": workload["queries_digest"],
            "batching": workload["batching_digest"],
            "dimensions": workload["dimensions_digest"],
        }
    )
    return workload


def _default_embed(text: str, dims: int) -> list[float]:
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


def _license_status(value: object) -> str:
    if value == "verified":
        return "verified"
    if value == "missing":
        return "missing"
    if value == "rejected":
        return "rejected"
    if value == "unverifiable":
        return "unverifiable"
    return "unverifiable"


def verify_candidate_license(license_record: object) -> dict[str, str]:
    if not isinstance(license_record, dict):
        return {
            "source": "",
            "identifier": "",
            "evidence_digest": "",
            "verification_status": "missing",
        }
    source = str(license_record.get("source") or "")
    identifier = str(license_record.get("identifier") or "")
    evidence_digest = str(license_record.get("evidence_digest") or "")
    claimed = license_record.get("verification_status")
    if claimed == "rejected":
        status = "rejected"
    elif not source or not identifier or not evidence_digest:
        status = "missing"
    elif not _digest_pinned(evidence_digest):
        status = "unverifiable"
    elif "evidence" in license_record:
        expected = f"sha256:{_sha256_text(str(license_record.get('evidence')))}"
        status = "verified" if expected == evidence_digest else "rejected"
    else:
        status = "verified"
    return {
        "source": source,
        "identifier": identifier,
        "evidence_digest": evidence_digest,
        "verification_status": _license_status(status),
    }


def _candidate_kind(value: object) -> str:
    if value is None or value == "measured":
        return "measured"
    if value == "smoke":
        return "smoke"
    if value == "unsupported":
        return "unsupported"
    if value == "unavailable":
        return "unavailable"
    return "unsupported"


def _admission_status(candidate: dict[str, Any], license_record: dict[str, str]) -> str:
    kind = _candidate_kind(candidate.get("kind"))
    if kind == "unsupported" or candidate.get("supported") is False:
        return "recorded-unsupported"
    if kind == "unavailable" or candidate.get("available") is False or candidate.get("installed") is False:
        return "recorded-unavailable"
    if not _digest_pinned(candidate.get("digest")):
        return "rejected-identity"
    status = license_record["verification_status"]
    if status == "missing" or status == "rejected" or status == "unverifiable":
        return "rejected-license"
    if status == "verified" and (kind == "measured" or kind == "smoke"):
        return "compared"
    return "recorded-unsupported"


def _embedder(candidate: dict[str, Any]) -> Callable[[str, int], list[float]]:
    embed = candidate.get("embed")
    if callable(embed):
        return embed
    return _default_embed


def _batched(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _observe(op_id: str, phase: str, outcome: str, started: float, ended: float) -> dict[str, Any]:
    return {
        "op_id": op_id,
        "phase": phase,
        "outcome": outcome,
        "issue_monotonic": started,
        "start_monotonic": started,
        "end_monotonic": ended,
    }


def _measure_candidate(
    candidate: dict[str, Any],
    workload: dict[str, Any],
    *,
    inject_outcomes: dict[str, str],
) -> dict[str, Any]:
    dims = int(workload["dimensions"])
    batching = dict(workload["batching"])
    embed = _embedder(candidate)
    before = sample_resources()
    observations: list[dict[str, Any]] = []
    cold_observations: list[dict[str, Any]] = []
    warm_observations: list[dict[str, Any]] = []
    vectors: dict[str, list[float]] = {}
    observed_lengths: list[int] = []
    embed_calls = 0
    batch_count = 0

    def _embed_text(text: str) -> list[float]:
        nonlocal embed_calls
        embed_calls += 1
        vector = list(embed(text, dims))
        observed_lengths.append(len(vector))
        return vector

    def _run_phase(phase: str) -> None:
        nonlocal batch_count
        target = cold_observations if phase == "cold" else warm_observations
        for batch_index, batch in enumerate(_batched(list(workload["corpus"]), int(batching["size"]))):
            started = time.perf_counter()
            for doc in batch:
                vectors[str(doc["doc_id"])] = _embed_text(str(doc["text"]))
            batch_count += 1
            ended = time.perf_counter()
            observation = _observe(f"{phase}:corpus-batch-{batch_index}", phase, "success", started, ended)
            observations.append(observation)
            target.append(observation)
        for query in workload["queries"]:
            qid = str(query["qid"])
            injected = inject_outcomes.get(qid)
            started = time.perf_counter()
            if injected == "timeout":
                observation = _observe(qid, phase, "timeout", started, time.perf_counter())
            elif injected == "error":
                observation = _observe(qid, phase, "error", started, time.perf_counter())
            elif injected is None:
                vectors[qid] = _embed_text(str(query["query"]))
                observation = _observe(qid, phase, "success", started, time.perf_counter())
            else:
                observation = _observe(qid, phase, "error", started, time.perf_counter())
            observations.append(observation)
            target.append(observation)

    _run_phase("cold")
    _run_phase("warm")
    after = sample_resources()

    hits: list[dict[str, Any]] = []
    for query in workload["queries"]:
        qid = str(query["qid"])
        query_vec = vectors.get(qid)
        if query_vec is None:
            hits.append({"qid": qid, "top": None, "relevant": list(query["relevant"]), "hit": False})
            continue
        ranked = sorted(
            (
                (_cosine(query_vec, vectors[str(doc["doc_id"])]), str(doc["doc_id"]))
                for doc in workload["corpus"]
                if str(doc["doc_id"]) in vectors
            ),
            reverse=True,
        )
        top = ranked[0][1] if ranked else None
        relevant = [str(item) for item in query["relevant"]]
        hits.append({"qid": qid, "top": top, "relevant": relevant, "hit": top in relevant})

    successes = sum(1 for item in observations if item["outcome"] == "success")
    timeouts = sum(1 for item in observations if item["outcome"] == "timeout")
    errors = sum(1 for item in observations if item["outcome"] == "error")
    shape_ok = bool(observed_lengths) and all(length == dims for length in observed_lengths)
    return {
        "cold": {
            "separated_from_warm": True,
            "sample_count": len(cold_observations),
            "observations": cold_observations,
        },
        "warm": {
            "separated_from_cold": True,
            "sample_count": len(warm_observations),
            "observations": warm_observations,
        },
        "observations": observations,
        "denominators": {
            "issued": len(observations),
            "successes": successes,
            "timeouts": timeouts,
            "errors": errors,
            "failed_remain_in_denominator": True,
        },
        "embedding_shape": {
            "dims": dims,
            "vector_count": len(observed_lengths),
            "observed_lengths": observed_lengths,
            "parity": shape_ok,
        },
        "correctness": {
            "pass": bool(hits) and all(item["hit"] for item in hits),
            "hits": hits,
            "parity": False,
        },
        "cost": {
            "embed_calls": embed_calls,
            "batch_count": batch_count,
            "estimated_units": float(embed_calls),
        },
        "resources": {
            "before": before,
            "during": [sample_resources()],
            "after": after,
        },
        "corpus_digest": workload["corpus_digest"],
        "queries_digest": workload["queries_digest"],
        "batching": batching,
        "dimensions": dims,
        "workload_digest": workload["workload_digest"],
    }


def _apply_shape_and_correctness_parity(candidates: list[dict[str, Any]]) -> None:
    compared = [item for item in candidates if item.get("status") == "compared"]
    if not compared:
        return
    reference_hits = _canonical_json((compared[0].get("correctness") or {}).get("hits"))
    reference_dims = (compared[0].get("embedding_shape") or {}).get("dims")
    for item in compared:
        shape = item.setdefault("embedding_shape", {})
        correctness = item.setdefault("correctness", {})
        shape_ok = shape.get("parity") is True and shape.get("dims") == reference_dims
        hits_ok = _canonical_json(correctness.get("hits")) == reference_hits
        shape["parity"] = bool(shape_ok)
        correctness["parity"] = bool(shape_ok and hits_ok and correctness.get("pass") is True)


def decide_provider_default(receipt: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    current_default = str(receipt.get("current_default") or "")
    noise_load = receipt.get("noise_load") if isinstance(receipt.get("noise_load"), dict) else {}
    if noise_load.get("noise_detected") is True:
        blockers.append("noise_rejected")
    if noise_load.get("load_detected") is True:
        blockers.append("load_rejected")

    candidates = [item for item in receipt.get("candidates", []) if isinstance(item, dict)]
    for candidate in candidates:
        license_record = candidate.get("license") if isinstance(candidate.get("license"), dict) else {}
        status = str(license_record.get("verification_status") or "")
        if status == "missing" or status == "rejected" or status == "unverifiable":
            blockers.append(f"license_{status}:{candidate.get('name')}")
        elif status and status not in _LICENSE_STATUSES:
            blockers.append(f"license_unverifiable:{candidate.get('name')}")

    compared = [item for item in candidates if item.get("status") == "compared"]
    smoke_success = [
        item
        for item in compared
        if item.get("kind") == "smoke" and (item.get("correctness") or {}).get("pass") is True
    ]
    measured_eligible = [
        item
        for item in compared
        if item.get("kind") == "measured"
        and item.get("installed") is True
        and item.get("available") is not False
        and item.get("supported") is not False
        and item.get("simulated") is False
        and _digest_pinned(item.get("digest"))
        and (item.get("license") or {}).get("verification_status") == "verified"
        and (item.get("correctness") or {}).get("pass") is True
        and (item.get("embedding_shape") or {}).get("parity") is True
    ]
    if smoke_success and not measured_eligible:
        blockers.append("smoke_success_does_not_select_default")
    if compared and all(item.get("kind") == "smoke" for item in compared):
        if "smoke_success_does_not_select_default" not in blockers:
            blockers.append("smoke_success_does_not_select_default")
    if not measured_eligible and not any(
        item.startswith("license_") or item == "smoke_success_does_not_select_default" for item in blockers
    ):
        blockers.append("no_eligible_measured_candidate")
    if not current_default:
        blockers.append("rollback_value_missing")

    blockers = sorted(set(blockers))
    if blockers:
        return {
            "decision": "no-decision",
            "selected": None,
            "rollback_value": current_default or None,
            "blockers": blockers,
            "config_promotion": False,
            "requires_retained_measured_evidence": True,
        }
    selected = sorted(measured_eligible, key=lambda item: str(item.get("name") or ""))[0]
    return {
        "decision": "select",
        "selected": selected["name"],
        "rollback_value": current_default,
        "blockers": [],
        "config_promotion": False,
        "requires_retained_measured_evidence": True,
    }


def _payload_for_result_digest(receipt: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(_canonical_json(receipt))
    artifacts = payload.get("raw_artifacts")
    if isinstance(artifacts, dict):
        artifacts.pop("result_digest", None)
    return payload


def _bind_raw_artifacts(receipt: dict[str, Any]) -> None:
    observations = [
        item.get("observations") or []
        for item in receipt.get("candidates", [])
        if isinstance(item, dict)
    ]
    receipt["raw_artifacts"] = {
        "observations_sha256": _digest_payload(observations),
        "workload_sha256": _digest_payload(receipt.get("workload")),
    }
    receipt["raw_artifacts"]["result_digest"] = _digest_payload(_payload_for_result_digest(receipt))


def run_provider_bakeoff(
    candidates: list[dict[str, Any]],
    *,
    current_default: str = "local",
    host_noise: bool = False,
    extra_load: bool = False,
    inject_outcomes: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    workload = pinned_identical_workload()
    repository_sha, clean_tree = _git_identity()
    utc_start = datetime.now(UTC).isoformat()
    monotonic_start = time.perf_counter()
    before = sample_resources()
    injected = inject_outcomes or {}
    during = [sample_resources()]
    recorded: list[dict[str, Any]] = []

    for raw in candidates:
        license_record = verify_candidate_license(raw.get("license"))
        kind = _candidate_kind(raw.get("kind"))
        status = _admission_status(raw, license_record)
        row: dict[str, Any] = {
            "name": str(raw.get("name") or ""),
            "kind": kind,
            "installed": raw.get("installed") is True,
            "available": raw.get("available") is not False,
            "supported": raw.get("supported") is not False,
            "digest": str(raw.get("digest") or ""),
            "license": license_record,
            "identity": {
                "name": str(raw.get("name") or ""),
                "digest": str(raw.get("digest") or ""),
            },
            "status": status,
            "simulated": False,
        }
        if status == "compared":
            row.update(
                _measure_candidate(
                    raw,
                    workload,
                    inject_outcomes=dict(injected.get(str(raw.get("name") or ""), {})),
                )
            )
        recorded.append(row)

    _apply_shape_and_correctness_parity(recorded)
    after = sample_resources()
    utc_end = datetime.now(UTC).isoformat()
    monotonic_end = time.perf_counter()
    receipt: dict[str, Any] = {
        "schema": CAP006_PROVIDER_SCHEMA,
        "receipt_class": RECEIPT_CLASS_SYNTHETIC_DEV,
        "official_claim": False,
        "admitted_measurement": False,
        "claim_status": CLAIM_STATUS_SYNTHETIC_DEV,
        "official_p95_claim": False,
        "performance_claim": None,
        "current_default": current_default,
        "identity": {
            "repository_sha": repository_sha,
            "clean_tree": clean_tree,
            "command": [sys.executable, "eval/provider_bakeoff/run.py"],
            "arguments": {
                "workload": SYNTHETIC_PROVIDER_WORKLOAD_ID,
                "current_default": current_default,
                "host_noise": host_noise,
                "extra_load": extra_load,
            },
            "utc_start": utc_start,
            "utc_end": utc_end,
            "monotonic_start": monotonic_start,
            "monotonic_end": monotonic_end,
            "host": _host_identity(),
            "digests": {
                "dataset": workload["workload_digest"],
                "fixture": _digest_payload(SYNTHETIC_PROVIDER_WORKLOAD_ID),
                "config": _digest_payload(
                    {
                        "current_default": current_default,
                        "host_noise": host_noise,
                        "extra_load": extra_load,
                    }
                ),
                "model": _digest_payload("synthetic-dev-hashing"),
                "tokenizer": _digest_payload("synthetic-dev-none"),
                "provider": _digest_payload([item["digest"] for item in recorded]),
                "container_image": _digest_payload("none"),
                "schema": _digest_payload(CAP006_PROVIDER_SCHEMA),
                "result_contract": _digest_payload("cap006-provider-receipt-v1-synthetic"),
            },
        },
        "sut_boundary": {
            "included_processes": ["synthetic-dev-provider-bakeoff"],
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
            **workload,
            "cold_warm_state": "separated",
            "warmup": {
                "explicit": True,
                "excluded_from_distribution": True,
                "count": len(workload["queries"]),
            },
        },
        "comparison": {
            "identical_corpus": True,
            "identical_queries": True,
            "identical_batching": True,
            "identical_dimensions": True,
            "workload_digest": workload["workload_digest"],
        },
        "candidates": recorded,
        "resources": {
            "before": before,
            "during": during,
            "after": after,
            "memory_pressure": (
                "none"
                if after["available_memory_bytes"] == 0
                else after["available_memory_bytes"] / max(after["total_memory_bytes"], 1)
            ),
            "swap_pagefile_delta": after["swap_bytes"] - before["swap_bytes"],
            "disk_index_growth": 0,
            "network_bytes": 0,
            "first_abort": None,
        },
        "noise_load": {
            "noise_detected": host_noise,
            "load_detected": extra_load,
            "rejected": host_noise or extra_load,
        },
        "ok": True,
    }
    receipt["decision"] = decide_provider_default(receipt)
    _bind_raw_artifacts(receipt)
    return receipt


def write_phase15_s4_provider_receipt(receipt: dict[str, Any], path: Path | None = None) -> Path:
    target = Path(path) if path is not None else PHASE15_S4_PROVIDER_REPORT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return target


def run_phase15_s4_provider_bakeoff() -> dict[str, Any]:
    def _pinned(name: str) -> dict[str, Any]:
        evidence = f"spdx:Apache-2.0:{name}"
        return {
            "name": name,
            "kind": "measured",
            "installed": True,
            "available": True,
            "supported": True,
            "digest": _digest_payload(name),
            "license": {
                "source": "spdx",
                "identifier": "Apache-2.0",
                "evidence": evidence,
                "evidence_digest": f"sha256:{_sha256_text(evidence)}",
            },
        }

    return run_provider_bakeoff(
        [_pinned("synthetic-a"), _pinned("synthetic-b")],
        current_default="local",
    )


def _finding(code: str, message: str, *, severity: str = "error") -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def _command(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise SystemExit(f"{field} must be a non-empty list of strings")
    return list(value)


def _subprocess_env(cwd: Path) -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(cwd / "src"), str(cwd)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _run_command(command: list[str], *, cwd: Path, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            env=_subprocess_env(cwd),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "duration_seconds": round(time.monotonic() - started, 6),
            "timed_out": True,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
    return {
        "command": command,
        "returncode": proc.returncode,
        "duration_seconds": round(time.monotonic() - started, 6),
        "timed_out": False,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _run_provider_check(manifest: Path, *, cwd: Path, timeout_seconds: float) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "mnemosyne.cli",
        "provider-check",
        "--provider-manifest",
        str(manifest),
    ]
    run = _run_command(command, cwd=cwd, timeout_seconds=timeout_seconds)
    payload: dict[str, Any] | None = None
    if run.get("stdout"):
        try:
            parsed = json.loads(str(run["stdout"]))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed
    return {
        "source": "provider_manifest",
        "manifest_path": str(manifest),
        "ok": bool(payload and payload.get("ok") is True and run["returncode"] == 0),
        "run": run,
        "report": payload,
    }


def _load_provider_check_report(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    return {
        "source": "provider_check_report",
        "path": str(path),
        "ok": payload.get("ok") is True,
        "report": payload,
    }


def _matching_markdown_path(report_path: Path) -> Path:
    return report_path.with_suffix(".md")


def _metric_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    seen_suite_counts: dict[str, int] = {}
    for suite in report.get("slo_suites", []):
        if not isinstance(suite, dict):
            continue
        suite_name = str(suite.get("suite") or "unknown")
        seen_suite_counts[suite_name] = seen_suite_counts.get(suite_name, 0) + 1
        suite_label = suite_name
        if suite_name == "retrieval":
            suite_label = "retrieval.synthetic" if seen_suite_counts[suite_name] > 1 else "retrieval.curated"
        for verdict in suite.get("verdicts", []):
            if not isinstance(verdict, dict):
                continue
            name = str(verdict.get("name") or "unnamed")
            metric_id = f"{suite_label}:{name}"
            ci = verdict.get("ci")
            rows[metric_id] = {
                "suite": suite_label,
                "name": name,
                "value": verdict.get("value"),
                "target": verdict.get("target"),
                "op": verdict.get("op"),
                "pass": verdict.get("pass") is True,
                "ci_present": isinstance(ci, dict) and ci.get("ci_low") is not None and ci.get("ci_high") is not None,
                "ci": ci if isinstance(ci, dict) else None,
            }
    for item in report.get("mandatory_classes", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "unnamed")
        rows[f"mandatory:{name}"] = {
            "suite": "mandatory",
            "name": name,
            "pass": item.get("passed") is True,
            "protected": True,
        }
    return rows


def _summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    metrics = _metric_rows(report)
    numeric_metrics = {
        key: value
        for key, value in metrics.items()
        if isinstance(value.get("value"), int | float) and not isinstance(value.get("value"), bool)
    }
    return {
        "meta": report.get("meta") if isinstance(report.get("meta"), dict) else {},
        "ignition": report.get("ignition") if isinstance(report.get("ignition"), dict) else {},
        "overall": report.get("overall") if isinstance(report.get("overall"), dict) else {},
        "metric_count": len(metrics),
        "numeric_metric_count": len(numeric_metrics),
        "confidence_intervals_present": bool(numeric_metrics)
        and all(item.get("ci_present") is True for item in numeric_metrics.values()),
        "metrics": metrics,
    }


def _load_arm_report(
    arm: dict[str, Any],
    *,
    fixture_base: Path,
    cwd: Path,
    execute: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    name = str(arm.get("name") or "")
    if not name:
        raise SystemExit("every bake-off arm requires a name")

    run: dict[str, Any] | None = None
    if execute:
        run = _run_command(_command(arm.get("command"), field=f"arms.{name}.command"), cwd=cwd, timeout_seconds=timeout_seconds)

    report_path = _resolve_path(str(arm.get("report") or ""), base=fixture_base)
    md_path = _matching_markdown_path(report_path)
    findings: list[dict[str, str]] = []
    report: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    if not report_path.exists():
        findings.append(_finding("report_missing", f"arm {name} is missing JSON report {report_path}"))
    else:
        report = _read_json(report_path)
        summary = _summarize_report(report)
    if not md_path.exists():
        findings.append(_finding("markdown_report_missing", f"arm {name} is missing Markdown report {md_path}"))
    if run and run.get("returncode") not in (0, None):
        findings.append(_finding("arm_command_failed", f"arm {name} command exited {run['returncode']}"))
    if run and run.get("timed_out"):
        findings.append(_finding("arm_command_timeout", f"arm {name} command timed out after {timeout_seconds}s"))

    return {
        "name": name,
        "kind": arm.get("kind"),
        "command": arm.get("command"),
        "report_path": str(report_path),
        "markdown_path": str(md_path),
        "report_found": report is not None,
        "markdown_found": md_path.exists(),
        "run": run,
        "summary": summary,
        "findings": findings,
    }


def _compare_arms(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    baseline_metrics = ((baseline.get("summary") or {}).get("metrics") or {})
    candidate_metrics = ((candidate.get("summary") or {}).get("metrics") or {})
    common = sorted(set(baseline_metrics).intersection(candidate_metrics))
    rows: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    for metric_id in common:
        base = baseline_metrics[metric_id]
        cand = candidate_metrics[metric_id]
        delta = None
        if isinstance(base.get("value"), int | float) and isinstance(cand.get("value"), int | float):
            delta = cand["value"] - base["value"]
        row = {
            "metric": metric_id,
            "baseline_value": base.get("value"),
            "candidate_value": cand.get("value"),
            "delta": delta,
            "baseline_pass": base.get("pass") is True,
            "candidate_pass": cand.get("pass") is True,
        }
        rows.append(row)
        if row["baseline_pass"] and not row["candidate_pass"]:
            regressions.append(row)
    return {
        "baseline": baseline["name"],
        "candidate": candidate["name"],
        "common_metric_count": len(common),
        "metrics": rows,
        "regressions": regressions,
    }


def build_report(
    fixture_path: Path = DEFAULT_FIXTURE,
    *,
    output_path: Path | None = None,
    provider_check_report: Path | None = None,
    provider_manifest: Path | None = None,
    noise_notes: Path | None = None,
    execute_arms: bool = False,
    cwd: Path | None = None,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    cwd = (cwd or _repo_root()).resolve()
    fixture_path = fixture_path.resolve()
    fixture = _read_json(fixture_path)
    findings: list[dict[str, str]] = []
    if fixture.get("protocol") != "mnemosyne-provider-bakeoff-v1":
        findings.append(_finding("fixture_protocol_unsupported", "fixture protocol must be mnemosyne-provider-bakeoff-v1"))

    arms_payload = fixture.get("arms")
    if not isinstance(arms_payload, list) or not arms_payload:
        raise SystemExit("fixture must contain non-empty arms list")
    arms = [
        _load_arm_report(
            arm,
            fixture_base=fixture_path.parent,
            cwd=cwd,
            execute=execute_arms,
            timeout_seconds=timeout_seconds,
        )
        for arm in arms_payload
        if isinstance(arm, dict)
    ]
    for arm in arms:
        findings.extend(arm["findings"])

    baselines = [arm for arm in arms if arm.get("kind") == "baseline"]
    if len(baselines) != 1:
        findings.append(_finding("baseline_count_invalid", "fixture must contain exactly one baseline arm"))
        baseline = arms[0]
    else:
        baseline = baselines[0]
    comparisons = [_compare_arms(baseline, arm) for arm in arms if arm is not baseline]
    if any(comparison["regressions"] for comparison in comparisons):
        findings.append(_finding("candidate_regression", "one or more candidates regressed on a baseline-passing verdict"))

    provider_check: dict[str, Any]
    if provider_check_report and provider_manifest:
        raise SystemExit("--provider-check-report and --provider-manifest are mutually exclusive")
    if provider_check_report:
        provider_check = _load_provider_check_report(provider_check_report.resolve())
    elif provider_manifest:
        provider_check = _run_provider_check(provider_manifest.resolve(), cwd=cwd, timeout_seconds=timeout_seconds)
    else:
        provider_check = {"source": "missing", "ok": False, "report": None}
    if provider_check.get("ok") is not True:
        findings.append(_finding("provider_check_missing_or_failed", "provider-check evidence is missing or failed"))

    required = fixture.get("required_evidence") if isinstance(fixture.get("required_evidence"), list) else []
    evidence = {
        "baseline_report_json": any(arm["kind"] == "baseline" and arm["report_found"] for arm in arms),
        "candidate_report_json": any(arm["kind"] != "baseline" and arm["report_found"] for arm in arms),
        "baseline_report_markdown": any(arm["kind"] == "baseline" and arm["markdown_found"] for arm in arms),
        "candidate_report_markdown": any(arm["kind"] != "baseline" and arm["markdown_found"] for arm in arms),
        "provider_check_report": provider_check.get("ok") is True,
        "noise_or_rerun_notes": bool(noise_notes and noise_notes.exists()),
    }
    missing_evidence = [str(item) for item in required if evidence.get(str(item)) is not True]
    for item in missing_evidence:
        severity = "warning" if item == "noise_or_rerun_notes" else "error"
        findings.append(_finding("required_evidence_missing", f"missing required evidence: {item}", severity=severity))

    confidence_intervals_present = all(
        (arm.get("summary") or {}).get("confidence_intervals_present") is True
        for arm in arms
        if arm.get("report_found")
    )
    acceptance = fixture.get("acceptance") if isinstance(fixture.get("acceptance"), dict) else {}
    promotion_reasons: list[str] = []
    if fixture.get("promotion_allowed_from_smoke") is not True:
        promotion_reasons.append("fixture_does_not_allow_promotion")
    if missing_evidence:
        promotion_reasons.append("required_evidence_missing")
    if provider_check.get("ok") is not True:
        promotion_reasons.append("provider_check_missing_or_failed")
    if not confidence_intervals_present and acceptance.get("confidence_intervals_required", True):
        promotion_reasons.append("confidence_intervals_missing")
    if any(comparison["regressions"] for comparison in comparisons):
        promotion_reasons.append("candidate_regression")
    if acceptance.get("margin_must_exceed_run_to_run_noise", True) and not evidence["noise_or_rerun_notes"]:
        promotion_reasons.append("noise_evidence_missing")

    report = {
        "protocol": REPORT_PROTOCOL,
        "generated_at": datetime.now(UTC).isoformat(),
        "ok": not any(item["severity"] == "error" for item in findings),
        "fixture": {
            "path": str(fixture_path),
            "protocol": fixture.get("protocol"),
            "purpose": fixture.get("purpose"),
            "promotion_allowed_from_smoke": fixture.get("promotion_allowed_from_smoke") is True,
        },
        "acceptance": acceptance,
        "evidence": evidence,
        "missing_evidence": missing_evidence,
        "provider_check": provider_check,
        "arms": arms,
        "comparisons": comparisons,
        "promotion": {
            "allowed": not promotion_reasons,
            "eligible_for_human_review": not any(reason.endswith("missing_or_failed") for reason in promotion_reasons)
            and "candidate_regression" not in promotion_reasons,
            "reasons": promotion_reasons,
        },
        "findings": findings,
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or summarize Mnemosyne provider bake-off evidence.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--provider-check-report", type=Path)
    parser.add_argument("--provider-manifest", type=Path)
    parser.add_argument("--noise-notes", type=Path, help="Path to run-to-run noise notes or rerun report")
    parser.add_argument("--execute-arms", action="store_true", help="Run each arm command before reading reports")
    parser.add_argument("--cwd", type=Path, default=_repo_root())
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero unless the evidence report is ok")
    parser.add_argument(
        "--write-phase15-s4",
        action="store_true",
        help="Write the synthetic Phase 15 S4 provider development receipt",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.write_phase15_s4:
        receipt = run_phase15_s4_provider_bakeoff()
        target = args.output or PHASE15_S4_PROVIDER_REPORT
        write_phase15_s4_provider_receipt(receipt, target)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    report = build_report(
        args.fixture,
        output_path=args.output,
        provider_check_report=args.provider_check_report,
        provider_manifest=args.provider_manifest,
        noise_notes=args.noise_notes,
        execute_arms=args.execute_arms,
        cwd=args.cwd,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.strict and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
