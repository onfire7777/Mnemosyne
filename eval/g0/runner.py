"""G0 benchmark report builder.

G0 is the cognitive-architecture baseline layer: it does not replace the
existing eval lane, it gathers the existing artifacts into one metric catalog,
adds source fingerprints, records the baseline environment, and makes missing
program-specific metrics explicit instead of letting them disappear.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from eval.g0.confabulation import run_confabulation_eval

G0_METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "recall_at_k",
        "label": "recall@k",
        "class": "target",
        "direction": "increase",
        "target": 0.80,
        "target_op": ">=",
        "blueprint_metric": "recall@k",
    },
    {
        "id": "ndcg_at_k",
        "label": "nDCG@k",
        "class": "target",
        "direction": "increase",
        "target": 0.80,
        "target_op": ">=",
        "blueprint_metric": "nDCG@k",
    },
    {
        "id": "multi_hop_recall_at_k",
        "label": "multi-hop recall@k",
        "class": "target",
        "direction": "increase",
        "target": 0.80,
        "target_op": ">=",
        "blueprint_metric": "multi-hop recall/nDCG",
    },
    {
        "id": "multi_hop_ndcg_at_k",
        "label": "multi-hop nDCG@k",
        "class": "target",
        "direction": "increase",
        "target": 0.80,
        "target_op": ">=",
        "blueprint_metric": "multi-hop recall/nDCG",
    },
    {
        "id": "ece",
        "label": "expected calibration error",
        "class": "guardrail",
        "direction": "decrease",
        "target": 0.05,
        "target_op": "<=",
        "blueprint_metric": "ECE",
    },
    {
        "id": "abstention_precision",
        "label": "abstention precision",
        "class": "guardrail",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "abstention precision / recall",
    },
    {
        "id": "abstention_recall",
        "label": "abstention recall",
        "class": "guardrail",
        "direction": "increase",
        "target": 1.0,
        "target_op": ">=",
        "blueprint_metric": "abstention precision / recall",
    },
    {
        "id": "continual_learning_interference",
        "label": "continual-learning interference",
        "class": "target",
        "direction": "decrease",
        "target": 0.0,
        "target_op": "<=",
        "blueprint_metric": "continual-learning interference",
    },
    {
        "id": "confabulation_rate",
        "label": "confabulation rate",
        "class": "guardrail",
        "direction": "decrease",
        "target": 0.0,
        "target_op": "<=",
        "blueprint_metric": "confabulation rate",
    },
    {
        "id": "poison_block_rate",
        "label": "poison-block rate",
        "class": "guardrail",
        "direction": "increase",
        "target": 0.95,
        "target_op": ">=",
        "blueprint_metric": "poison-block rate",
    },
    {
        "id": "fast_path_p95_ms",
        "label": "fast-path P95 latency",
        "class": "guardrail",
        "direction": "decrease",
        "target": 400.0,
        "target_op": "<=",
        "blueprint_metric": "fast-path P95 latency",
    },
    {
        "id": "deep_path_p95_ms",
        "label": "deep-path P95 latency",
        "class": "reported",
        "direction": "decrease",
        "target": None,
        "target_op": None,
        "blueprint_metric": "deep-path P95 latency",
    },
    {
        "id": "cost_usd_per_1k_queries",
        "label": "cost per 1k queries",
        "class": "reported",
        "direction": "decrease",
        "target": None,
        "target_op": None,
        "blueprint_metric": "cost",
    },
    {
        "id": "controller_watts_per_dollar",
        "label": "controller watts per dollar",
        "class": "reported",
        "direction": "decrease",
        "target": None,
        "target_op": None,
        "blueprint_metric": "controller watts/$",
    },
)

SOURCE_PATHS = {
    "slo_v2_definitive": "eval/reports/slo_v2_definitive.json",
    "calibration_report": "eval/calibration/report.json",
    "latency_bench": "eval/latency/reports/latency_bench_latest.json",
    "warm_latency": "eval/latency_warm/reports/warm_latency_latest.json",
    "replay_fidelity": "eval/reports/replay_fidelity_latest.json",
}

DATASET_PATHS = (
    "eval/datasets/retrieval_curated.json",
    "eval/datasets/poison_suite.json",
    "eval/datasets/belief_cases.json",
    "eval/datasets/v2/retrieval_v2.json",
    "eval/datasets/v2/qa_hard_v2.json",
)

DEFAULT_SEEDS = {
    "harness_bootstrap_mean": 1234,
    "harness_bootstrap_percentile": 4321,
    "synthetic_retrieval": 7,
}


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    relative_path: str
    path: Path
    data: dict[str, Any] | None
    sha256: str | None

    @property
    def present(self) -> bool:
        return self.data is not None


def build_report(
    repo_root: Path,
    *,
    baseline_name: str = "baseline-0",
    pinned_commit: str | None = None,
) -> dict[str, Any]:
    """Build a complete G0 report from existing eval artifacts."""

    repo_root = repo_root.resolve()
    sources = _load_sources(repo_root)
    confabulation_report = run_confabulation_eval()
    sources["confabulation_eval"] = _computed_source(
        repo_root,
        "confabulation_eval",
        "computed:eval.g0.confabulation",
        confabulation_report,
    )
    metrics = [_build_metric(spec, sources) for spec in G0_METRIC_SPECS]
    measured = sum(1 for metric in metrics if metric["status"] == "measured")
    missing = len(metrics) - measured
    commit = pinned_commit or _git(repo_root, "rev-parse", "HEAD")
    tag_target = _git(repo_root, "rev-list", "-n", "1", baseline_name, check=False)
    dataset_manifests = [_dataset_manifest(repo_root, rel) for rel in DATASET_PATHS]

    report = {
        "schema_version": "g0.report.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blueprint_refs": [
            "docs/blueprint/cognitive-architecture/04-G0-BENCHMARK-SPEC.md",
            "docs/blueprint/eval/05-harness-architecture-and-ci-gating.md",
            "eval/calibration/report.json",
        ],
        "baseline": {
            "name": baseline_name,
            "pinned_commit": commit,
            "tag_exists": bool(tag_target),
            "tag_target": tag_target or None,
            "seeds": DEFAULT_SEEDS,
            "environment": _environment_summary(repo_root, sources),
        },
        "sources": [_source_summary(source) for source in sources.values()],
        "computed_evidence": {
            source.id: source.data
            for source in sources.values()
            if source.relative_path.startswith("computed:")
        },
        "dataset_manifests": dataset_manifests,
        "metrics": metrics,
        "coverage": {
            "total": len(metrics),
            "measured": measured,
            "missing": missing,
            "gate_ready": missing == 0,
            "missing_metric_ids": [m["id"] for m in metrics if m["status"] != "measured"],
        },
        "gate_contract": {
            "preregistration_required": True,
            "rule": "ship iff a preregistered target metric improves by its margin and no guardrail regresses",
            "gate_command": "python -m eval.g0.gate --baseline BASELINE.json --candidate CANDIDATE.json --prereg PREREG.json",
            "decision_log": "eval/g0/decision-log.jsonl",
        },
    }
    report["headline_slos"] = _headline_slos(report)
    return report


def write_report(report: dict[str, Any], out_dir: Path, *, write_baseline: bool = False) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    text = json.dumps(report, indent=2, sort_keys=True)
    json_path.write_text(text + "\n")
    md_path.write_text(render_markdown(report))
    paths = {"json": json_path, "markdown": md_path}
    if write_baseline:
        baseline_name = report["baseline"]["name"]
        baseline_path = out_dir.parent / "baselines" / f"{baseline_name}.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(text + "\n")
        paths["baseline"] = baseline_path
    return paths


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Mnemosyne G0 Benchmark Report",
        "",
        f"- Generated: `{report.get('generated_at')}`",
        f"- Baseline: `{report['baseline']['name']}` at `{report['baseline']['pinned_commit']}`",
        f"- Gate ready: **{report['coverage']['gate_ready']}** "
        f"({report['coverage']['measured']}/{report['coverage']['total']} metrics measured)",
        "",
        "## Metrics",
        "",
        "| Metric | Class | Status | Value | Target | Source |",
        "|---|---|---|---:|---|---|",
    ]
    for metric in report["metrics"]:
        target = "reported"
        if metric.get("target") is not None:
            target = f"{metric.get('target_op')} {metric.get('target')}"
        value = "" if metric.get("value") is None else str(metric["value"])
        source = metric.get("source_id") or ""
        lines.append(
            f"| {metric['id']} | {metric['class']} | {metric['status']} | "
            f"{value} | {target} | {source} |"
        )
    lines.extend(
        [
            "",
            "## Missing Metrics",
            "",
        ]
    )
    missing = [m for m in report["metrics"] if m["status"] != "measured"]
    if missing:
        for metric in missing:
            lines.append(f"- `{metric['id']}`: {metric['notes']}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Gate Contract",
            "",
            f"`{report['gate_contract']['gate_command']}`",
            "",
        ]
    )
    return "\n".join(lines)


def _build_metric(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    builders: dict[str, Callable[[dict[str, Any], dict[str, Source]], dict[str, Any]]] = {
        "recall_at_k": _metric_recall,
        "ndcg_at_k": _metric_ndcg,
        "multi_hop_recall_at_k": _metric_multi_hop_recall,
        "multi_hop_ndcg_at_k": _metric_multi_hop_ndcg,
        "ece": _metric_ece,
        "abstention_precision": _metric_abstention_precision,
        "abstention_recall": _metric_abstention_recall,
        "confabulation_rate": _metric_confabulation_rate,
        "poison_block_rate": _metric_poison_block_rate,
        "fast_path_p95_ms": _metric_fast_path_p95,
    }
    base = {
        "id": spec["id"],
        "label": spec["label"],
        "class": spec["class"],
        "direction": spec["direction"],
        "target": spec["target"],
        "target_op": spec["target_op"],
        "blueprint_metric": spec["blueprint_metric"],
        "status": "missing",
        "value": None,
        "pass": None,
        "source_id": None,
        "evidence_path": None,
        "notes": "No current artifact computes this G0 metric yet.",
    }
    builder = builders.get(spec["id"])
    if builder is None:
        return base
    measured = builder(spec, sources)
    return {**base, **measured}


def _metric_recall(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    suite = _source_data(sources, "slo_v2_definitive", "suites", "retrieval_v2")
    value = _nested(suite, "recall_at_k", "mean")
    return _measured(spec, value, "slo_v2_definitive", "/suites/retrieval_v2/recall_at_k/mean")


def _metric_ndcg(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    suite = _source_data(sources, "slo_v2_definitive", "suites", "retrieval_v2")
    value = _nested(suite, "ndcg_at_k", "mean")
    return _measured(spec, value, "slo_v2_definitive", "/suites/retrieval_v2/ndcg_at_k/mean")


def _metric_multi_hop_recall(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    suite = _source_data(sources, "slo_v2_definitive", "suites", "retrieval_qa_hard_v2")
    value = _nested(suite, "recall_at_k", "mean")
    return _measured(
        spec,
        value,
        "slo_v2_definitive",
        "/suites/retrieval_qa_hard_v2/recall_at_k/mean",
        note="Current proxy uses the hard QA/multi-hop gap suite from the definitive SLO artifact.",
    )


def _metric_multi_hop_ndcg(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    suite = _source_data(sources, "slo_v2_definitive", "suites", "retrieval_qa_hard_v2")
    value = _nested(suite, "ndcg_at_k", "mean")
    return _measured(
        spec,
        value,
        "slo_v2_definitive",
        "/suites/retrieval_qa_hard_v2/ndcg_at_k/mean",
        note="Current proxy uses the hard QA/multi-hop gap suite from the definitive SLO artifact.",
    )


def _metric_ece(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(sources, "calibration_report", "ece", "conformal_threshold", "overall")
    if value is not None:
        return _measured(spec, value, "calibration_report", "/ece/conformal_threshold/overall")
    suite = _source_data(sources, "slo_v2_definitive", "suites", "calibration_v2")
    return _measured(spec, suite.get("ece") if isinstance(suite, dict) else None, "slo_v2_definitive", "/suites/calibration_v2/ece")


def _metric_abstention_precision(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(
        sources,
        "calibration_report",
        "conformal_report",
        "overall",
        "abstention",
        "abstain_precision",
    )
    return _measured(spec, value, "calibration_report", "/conformal_report/overall/abstention/abstain_precision")


def _metric_abstention_recall(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(
        sources,
        "calibration_report",
        "conformal_report",
        "overall",
        "abstention",
        "abstain_recall",
    )
    return _measured(spec, value, "calibration_report", "/conformal_report/overall/abstention/abstain_recall")


def _metric_confabulation_rate(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    value = _source_data(sources, "confabulation_eval", "rate")
    return _measured(
        spec,
        value,
        "confabulation_eval",
        "/rate",
        note=(
            "Measured by the G0 confabulation fixture as the false-accept rate "
            "when only generated, low-fidelity, or confabulation-risk support is retrieved."
        ),
    )


def _metric_poison_block_rate(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    suite = _source_data(sources, "slo_v2_definitive", "suites", "poison_block_g7")
    value = suite.get("block_rate") if isinstance(suite, dict) else None
    return _measured(spec, value, "slo_v2_definitive", "/suites/poison_block_g7/block_rate")


def _metric_fast_path_p95(spec: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    bench = sources.get("latency_bench")
    data = bench.data if bench else None
    value = _nested(data, "components", "fast_path_total", "p95_ms")
    if value is not None:
        return _measured(
            spec,
            value,
            "latency_bench",
            "/components/fast_path_total/p95_ms",
            note="Uses long-lived local/in-process latency artifact, avoiding per-query CLI cold start.",
        )
    value = _nested(data, "components", "engine_fast_path_total", "p95_ms")
    if value is not None:
        return _measured(spec, value, "latency_bench", "/components/engine_fast_path_total/p95_ms")
    warm = sources.get("warm_latency")
    value = _nested(warm.data if warm else None, "components", "engine_fast_path_total", "p95_ms")
    return _measured(spec, value, "warm_latency", "/components/engine_fast_path_total/p95_ms")


def _measured(
    spec: dict[str, Any],
    value: Any,
    source_id: str,
    evidence_path: str,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    if value is None:
        return {}
    numeric = float(value)
    passed = _passes(numeric, spec.get("target"), spec.get("target_op"))
    return {
        "status": "measured",
        "value": round(numeric, 6),
        "pass": passed,
        "source_id": source_id,
        "evidence_path": evidence_path,
        "notes": note or "Measured from an existing eval artifact.",
    }


def _passes(value: float, target: Any, op: str | None) -> bool | None:
    if target is None or op is None:
        return None
    target_f = float(target)
    if op == ">=":
        return value >= target_f
    if op == "<=":
        return value <= target_f
    raise ValueError(f"unsupported target op: {op}")


def _load_sources(repo_root: Path) -> dict[str, Source]:
    return {source_id: _load_source(repo_root, source_id, rel) for source_id, rel in SOURCE_PATHS.items()}


def _load_source(repo_root: Path, source_id: str, relative_path: str) -> Source:
    path = repo_root / relative_path
    if not path.exists():
        return Source(source_id, relative_path, path, None, None)
    text = path.read_text()
    return Source(source_id, relative_path, path, json.loads(text), _sha256_text(text))


def _computed_source(repo_root: Path, source_id: str, label: str, data: dict[str, Any]) -> Source:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return Source(source_id, label, repo_root, data, _sha256_text(encoded))


def _source_summary(source: Source) -> dict[str, Any]:
    generated_at = None
    if isinstance(source.data, dict):
        generated_at = source.data.get("generated_at") or _nested(source.data, "meta", "generated_at")
    return {
        "id": source.id,
        "path": source.relative_path,
        "present": source.present,
        "sha256": source.sha256,
        "generated_at": generated_at,
    }


def _dataset_manifest(repo_root: Path, relative_path: str) -> dict[str, Any]:
    path = repo_root / relative_path
    manifest: dict[str, Any] = {
        "path": relative_path,
        "present": path.exists(),
        "sha256": None,
        "bytes": None,
        "counts": {},
    }
    if not path.exists():
        return manifest
    text = path.read_text()
    manifest["sha256"] = _sha256_text(text)
    manifest["bytes"] = len(text.encode())
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return manifest
    if isinstance(data, dict):
        for key in ("corpus", "queries", "attacks", "cases", "tasks"):
            value = data.get(key)
            if isinstance(value, list):
                manifest["counts"][key] = len(value)
        if "tenant" in data:
            manifest["tenant"] = data["tenant"]
        if "k" in data:
            manifest["k"] = data["k"]
    return manifest


def _environment_summary(repo_root: Path, sources: dict[str, Source]) -> dict[str, Any]:
    latency_config = _source_data(sources, "latency_bench", "config")
    warm_config = _source_data(sources, "warm_latency", "config")
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "repo_root": str(repo_root),
        "backend": _first_present(
            _nested(warm_config, "backend"),
            _nested(warm_config, "store_backend"),
            _nested(latency_config, "store_backend"),
            "local",
        ),
        "embedding_provider": _first_present(
            _nested(warm_config, "embedding_model"),
            _nested(latency_config, "embedding_model"),
            "local deterministic / artifact unspecified",
        ),
        "reranker_provider": _first_present(
            _nested(warm_config, "reranker_model"),
            _nested(latency_config, "reranker_model"),
            "artifact unspecified",
        ),
        "hardware": {
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
    }


def _headline_slos(report: dict[str, Any]) -> dict[str, Any]:
    ids = [
        "recall_at_k",
        "ndcg_at_k",
        "ece",
        "poison_block_rate",
        "fast_path_p95_ms",
    ]
    metric_map = {m["id"]: m for m in report["metrics"]}
    return {metric_id: metric_map[metric_id] for metric_id in ids}


def _source_data(sources: dict[str, Source], source_id: str, *path: str) -> Any:
    source = sources.get(source_id)
    if source is None or source.data is None:
        return None
    return _nested(source.data, *path)


def _nested(data: Any, *path: str) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _git(repo_root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Mnemosyne G0 benchmark report")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out-dir", type=Path, default=Path("eval/g0/reports"))
    parser.add_argument("--baseline-name", default="baseline-0")
    parser.add_argument("--pinned-commit", help="override the git HEAD recorded as the baseline commit")
    parser.add_argument("--write-baseline", action="store_true", help="also write eval/g0/baselines/<name>.json")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    report = build_report(repo_root, baseline_name=args.baseline_name, pinned_commit=args.pinned_commit)
    paths = write_report(report, repo_root / args.out_dir, write_baseline=args.write_baseline)
    if args.print_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"G0 report: {paths['json']}")
        print(f"G0 markdown: {paths['markdown']}")
        if "baseline" in paths:
            print(f"G0 baseline: {paths['baseline']}")
        print(
            f"G0 coverage: {report['coverage']['measured']}/{report['coverage']['total']} "
            f"measured; gate_ready={report['coverage']['gate_ready']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
