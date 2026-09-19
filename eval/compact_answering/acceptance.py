"""Physical 8 GiB compact-answering admission harness (Phase 15 S4 / 15-03-04).

Development/schema-stub path only. This module does not close CAP-011, invent
measured host numbers, or emit an official/public performance claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Literal, Mapping, Never

Platform = Literal["windows", "linux"]

RECEIPT_SCHEMA = "mnemosyne.cap011.8gb-acceptance-receipt/v1"
CLAIM_STATUS = "harness-ready-blocked"
WORKLOAD_ID = "phase15-s4-8gb-acceptance-v1"
BASED_ON_SHA = "eed2d1f8a531b181665c4d1745b54472df0e7a41"
EIGHT_GIB_BYTES = 8 * 1024**3
MAX_MODEL_TOKENIZER_BYTES = 1 * 1024**3
MAX_SIDECAR_PEAK_BYTES = 3 * 1024**3
MAX_PROCESS_TREE_BYTES = int(6.5 * 1024**3)
MIN_AVAILABLE_MEMORY_BYTES = int(1.5 * 1024**3)
REQUIRED_WARM_RUNS = 3
_REPORTS = Path(__file__).resolve().parent / "reports"
PHASE15_S4_8GB_WINDOWS_REPORT = _REPORTS / "phase15-s4-8gb-windows.json"
PHASE15_S4_8GB_LINUX_REPORT = _REPORTS / "phase15-s4-8gb-linux.json"
_DIGEST_KEYS = (
    "code",
    "artifact",
    "configuration",
    "provider",
    "corpus",
    "policy",
    "result_contract",
)
_REQUIRED_TOP = frozenset(
    {
        "schema",
        "receipt_class",
        "official_claim",
        "admitted_measurement",
        "measured",
        "harness_ready",
        "claim_status",
        "physical",
        "host_class",
        "virtualization",
        "platform",
        "identity",
        "sut_boundary",
        "resources",
        "quality",
        "completeness",
        "cap011",
    }
)
_X86_ARCH = frozenset({"x86_64", "amd64"})
_ARM_ARCH = frozenset({"arm64", "aarch64"})
_LOCKED_QUALITY_FLAGS = (
    "cap003",
    "deterministic_retrieval",
    "grounding",
    "abstention",
    "section_31",
    "section_33",
    "custody",
)
_LOCKED_QUALITY_SCORES = ("em", "f1", "recall_at_5", "ndcg_at_5")


class AcceptanceRejection(ValueError):
    """Fail-closed physical 8 GiB admission rejection."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or reason)


def pinned_digests() -> dict[str, str]:
    """Synthetic custody pins for the harness ABI. Not measured artifact claims."""
    return {
        key: (
            "sha256:"
            + hashlib.sha256(f"phase15-s4-8gb-synthetic-pin:{key}".encode("utf-8")).hexdigest()
        )
        for key in _DIGEST_KEYS
    }


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _report_path(platform: Platform) -> Path:
    match platform:
        case "windows":
            return PHASE15_S4_8GB_WINDOWS_REPORT
        case "linux":
            return PHASE15_S4_8GB_LINUX_REPORT
        case _:
            unused: Never = platform
            raise AcceptanceRejection("incomplete", f"unsupported platform: {unused}")


def _normalize_platform(value: object) -> Platform | None:
    if not isinstance(value, str):
        return None
    match value.casefold():
        case "windows" | "win32":
            return "windows"
        case "linux":
            return "linux"
        case _:
            return None


def _normalize_arch(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    return value.casefold()


def _cpu_flags(host: Mapping[str, Any]) -> list[str]:
    flags = host.get("cpu_flags")
    if not isinstance(flags, list):
        return []
    return [str(flag).casefold() for flag in flags]


def development_stub_receipt(*, platform: Platform) -> dict[str, Any]:
    """Schema-stable development stub. Never a measured or admitted CAP-011 run."""
    match platform:
        case "windows" | "linux":
            normalized = platform
        case _:
            unused: Never = platform
            raise AcceptanceRejection("incomplete", f"unsupported stub platform: {unused}")
    return {
        "schema": RECEIPT_SCHEMA,
        "receipt_class": "schema-stub",
        "official_claim": False,
        "admitted_measurement": False,
        "measured": False,
        "harness_ready": True,
        "claim_status": CLAIM_STATUS,
        "physical": False,
        "host_class": "development-stub",
        "virtualization": "none",
        "platform": normalized,
        "identity": {
            "based_on_sha": BASED_ON_SHA,
            "workload": WORKLOAD_ID,
            "host": {
                "os_family": normalized,
                "architecture": None,
                "cpu_flags": [],
                "physical_memory_bytes": None,
            },
            "digests": pinned_digests(),
        },
        "sut_boundary": {
            "included_processes": [],
            "background_workers": [],
            "hidden_workers": False,
            "benchmark_process_count": 0,
            "host_workload_count": 0,
            "declared_concurrency": 0,
            "observed_concurrency": 0,
        },
        "resources": {
            "before": {
                "total_memory_bytes": None,
                "available_memory_bytes": None,
                "swap_bytes": None,
            },
            "during": [],
            "after": {
                "total_memory_bytes": None,
                "available_memory_bytes": None,
                "swap_bytes": None,
            },
            "swap_pagefile_delta": None,
            "model_tokenizer_bytes": None,
            "sidecar_peak_bytes": None,
            "process_tree_peak_bytes": None,
            "min_available_memory_bytes": None,
            "first_abort": None,
        },
        "quality": {
            "weakened": False,
            "canonical_receipt": None,
            "em": None,
            "f1": None,
            "recall_at_5": None,
            "ndcg_at_5": None,
            "cap003": None,
            "deterministic_retrieval": None,
            "grounding": None,
            "abstention": None,
            "section_31": None,
            "section_33": None,
            "custody": None,
        },
        "completeness": {
            "cold_load": False,
            "warm_runs": 0,
            "unload_reload": False,
            "raw_traces": False,
        },
        "cap011": {
            "status": "open",
            "closes": False,
            "measured": False,
        },
        "blockers": [
            "physical_dual_host_measurement_missing",
            "cap011_remains_open",
        ],
    }


def cap011_status(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one receipt's host role. Never reports CAP-011 closed."""
    identity = receipt.get("identity") if isinstance(receipt.get("identity"), Mapping) else {}
    host = identity.get("host") if isinstance(identity.get("host"), Mapping) else {}
    arch = _normalize_arch(host.get("architecture"))
    platform = _normalize_platform(receipt.get("platform"))
    if arch in _ARM_ARCH:
        return {
            "host_role": "additional-arm64",
            "required_host": False,
            "closes": False,
        }
    if platform is not None and arch in _X86_ARCH:
        return {
            "host_role": f"required-{platform}",
            "required_host": True,
            "closes": False,
        }
    return {
        "host_role": "ineligible",
        "required_host": False,
        "closes": False,
    }


def _require_mapping(value: object, reason: str, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AcceptanceRejection(reason, f"{label} must be an object")
    return value


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def admit_receipt(receipt: object) -> dict[str, Any]:
    """Fail-closed single-host admission. Eligibility never closes CAP-011."""
    document = _require_mapping(receipt, "incomplete", "receipt")
    if (not _REQUIRED_TOP <= set(document)) or document.get("schema") != RECEIPT_SCHEMA:
        raise AcceptanceRejection("incomplete", "receipt is missing required CAP-011 fields")

    identity = _require_mapping(document.get("identity"), "incomplete", "identity")
    host = _require_mapping(identity.get("host"), "incomplete", "identity.host")
    sut = _require_mapping(document.get("sut_boundary"), "incomplete", "sut_boundary")
    resources = _require_mapping(document.get("resources"), "incomplete", "resources")
    quality = _require_mapping(document.get("quality"), "incomplete", "quality")
    completeness = _require_mapping(document.get("completeness"), "incomplete", "completeness")
    cap011 = _require_mapping(document.get("cap011"), "incomplete", "cap011")

    physical = document.get("physical") is True
    host_class = document.get("host_class")
    virtualization = document.get("virtualization")
    flags = _cpu_flags(host)
    if (
        not physical
        or host_class != "physical"
        or virtualization != "none"
        or "hypervisor" in flags
        or document.get("receipt_class") != "physical-host"
    ):
        raise AcceptanceRejection("non_physical", "receipt is not a physical 8 GiB host run")

    arch = _normalize_arch(host.get("architecture"))
    platform = _normalize_platform(document.get("platform"))
    os_family = _normalize_platform(host.get("os_family"))
    if platform is None or arch not in _X86_ARCH or (os_family is not None and os_family != platform):
        raise AcceptanceRejection(
            "wrong_architecture",
            "required hosts are native x86-64 Windows and Linux; ARM64 is additional only",
        )

    if "avx2" not in flags:
        raise AcceptanceRejection("missing_avx2", "required hosts must expose AVX2")

    physical_memory = _as_int(host.get("physical_memory_bytes"))
    before = _require_mapping(resources.get("before"), "incomplete", "resources.before")
    after = _require_mapping(resources.get("after"), "incomplete", "resources.after")
    during = resources.get("during")
    total_memory = _as_int(before.get("total_memory_bytes"))
    if physical_memory != EIGHT_GIB_BYTES or (total_memory is not None and total_memory != EIGHT_GIB_BYTES):
        raise AcceptanceRejection("wrong_memory", "required hosts must have exactly 8 GiB physical memory")

    workers = sut.get("background_workers")
    hidden_flag = sut.get("hidden_workers") is True
    benchmark_count = _as_int(sut.get("benchmark_process_count"))
    workload_count = _as_int(sut.get("host_workload_count"))
    declared = _as_int(sut.get("declared_concurrency"))
    observed = _as_int(sut.get("observed_concurrency"))
    if (
        hidden_flag
        or not isinstance(workers, list)
        or workers
        or benchmark_count != 1
        or workload_count != 1
        or declared != 1
        or observed != 1
    ):
        raise AcceptanceRejection("hidden_worker", "hidden or extra workers fail closed")

    expected_digests = pinned_digests()
    observed_digests = identity.get("digests")
    if not isinstance(observed_digests, Mapping) or dict(observed_digests) != expected_digests:
        raise AcceptanceRejection("digest_mismatch", "pinned compact custody digest mismatch")

    swap_delta = _as_int(resources.get("swap_pagefile_delta"))
    before_swap = _as_int(before.get("swap_bytes")) or 0
    after_swap = _as_int(after.get("swap_bytes")) or 0
    if swap_delta is None or swap_delta > 0 or after_swap > before_swap:
        raise AcceptanceRejection("swap_pagefile_growth", "swap or pagefile growth fails closed")

    model_bytes = _as_int(resources.get("model_tokenizer_bytes"))
    sidecar_peak = _as_int(resources.get("sidecar_peak_bytes"))
    tree_peak = _as_int(resources.get("process_tree_peak_bytes"))
    min_available = _as_int(resources.get("min_available_memory_bytes"))
    if (
        not isinstance(during, list)
        or not during
        or completeness.get("cold_load") is not True
        or _as_int(completeness.get("warm_runs")) is None
        or (_as_int(completeness.get("warm_runs")) or 0) < REQUIRED_WARM_RUNS
        or completeness.get("unload_reload") is not True
        or completeness.get("raw_traces") is not True
        or resources.get("first_abort") is not None
        or model_bytes is None
        or sidecar_peak is None
        or tree_peak is None
        or min_available is None
        or model_bytes > MAX_MODEL_TOKENIZER_BYTES
        or sidecar_peak > MAX_SIDECAR_PEAK_BYTES
        or tree_peak > MAX_PROCESS_TREE_BYTES
        or min_available < MIN_AVAILABLE_MEMORY_BYTES
    ):
        raise AcceptanceRejection("incomplete", "physical procedure or resource envelope is incomplete")

    if (
        quality.get("weakened") is not False
        or quality.get("canonical_receipt") != "24/24"
        or any(quality.get(name) is not True for name in _LOCKED_QUALITY_FLAGS)
        or any(quality.get(name) != 1.0 for name in _LOCKED_QUALITY_SCORES)
    ):
        raise AcceptanceRejection("quality_weakened", "quality, custody, or rail contract was weakened")

    if cap011.get("closes") is True or document.get("official_claim") is True:
        raise AcceptanceRejection("quality_weakened", "a single receipt cannot close CAP-011 or claim officially")

    return {
        "admitted": True,
        "reason": None,
        "platform": platform,
        "official_claim": False,
        "admitted_measurement": False,
        "cap011_closes": False,
        "host_role": f"required-{platform}",
    }


def _try_admit(receipt: object) -> dict[str, Any]:
    try:
        result = admit_receipt(receipt)
    except AcceptanceRejection as exc:
        return {"admitted": False, "reason": exc.reason}
    return {"admitted": True, "reason": None, **result}


def evaluate_dual_host(windows: object, linux: object) -> dict[str, Any]:
    """Combine Windows and Linux receipts. This harness never closes CAP-011."""
    windows_result = _try_admit(windows)
    linux_result = _try_admit(linux)
    windows_platform = None
    linux_platform = None
    if isinstance(windows, Mapping):
        windows_platform = _normalize_platform(windows.get("platform"))
    if isinstance(linux, Mapping):
        linux_platform = _normalize_platform(linux.get("platform"))
    both = (
        windows_result["admitted"]
        and linux_result["admitted"]
        and windows_platform == "windows"
        and linux_platform == "linux"
    )
    blockers = ["cap011_remains_open"]
    if both:
        blockers.append("physical_dual_host_measured_closure_pending")
    else:
        if not windows_result["admitted"] or not linux_result["admitted"]:
            blockers.append("physical_dual_host_measurement_missing")
    return {
        "both_admitted": both,
        "cap011_closes": False,
        "official_claim": False,
        "windows_reason": windows_result["reason"],
        "linux_reason": linux_result["reason"],
        "blockers": blockers,
    }


def load_receipt(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AcceptanceRejection("incomplete", "receipt file must be a JSON object")
    return payload


def write_stub_receipt(path: str | Path, *, platform: Platform) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(development_stub_receipt(platform=platform), indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CAP-011 compact 8 GiB acceptance harness (development stub path)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    stub = sub.add_parser("stub", help="emit a schema stub (does not close CAP-011)")
    stub.add_argument("--platform", choices=("windows", "linux"), required=True)
    admit = sub.add_parser("admit", help="fail-closed admit one receipt")
    admit.add_argument("--path", required=True)
    dual = sub.add_parser("dual", help="evaluate Windows + Linux receipts without closing CAP-011")
    dual.add_argument("--windows", required=True)
    dual.add_argument("--linux", required=True)
    args = parser.parse_args(argv)
    match args.command:
        case "stub":
            print(_canonical_json(development_stub_receipt(platform=args.platform)))
            return 0
        case "admit":
            try:
                print(_canonical_json(admit_receipt(load_receipt(args.path))))
            except AcceptanceRejection as exc:
                print(_canonical_json({"admitted": False, "reason": exc.reason, "cap011_closes": False}))
                return 2
            return 0
        case "dual":
            print(
                _canonical_json(
                    evaluate_dual_host(load_receipt(args.windows), load_receipt(args.linux))
                )
            )
            return 0
        case _:
            unused: Never = args.command
            raise SystemExit(f"unsupported command: {unused}")


if __name__ == "__main__":
    sys.exit(main())
