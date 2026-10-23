"""Quality gate evaluation suite tests."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path


def _strip_nondeterministic_fields(report: dict) -> dict:
    cleaned = copy.deepcopy(report)
    meta = cleaned.get("meta", {})
    meta.pop("generated_at", None)
    meta.pop("git_commit", None)
    meta.pop("runtime_seconds", None)

    for q in cleaned.get("query_details", []):
        q.pop("latency_ms", None)

    return cleaned


def test_quality_gate_baseline_reproduces_bit_for_bit(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    baseline_path = repo_root / "eval" / "reports" / "quality_gate_baseline.json"
    assert baseline_path.is_file(), f"Committed baseline report missing at {baseline_path}"

    committed_baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    tmp_report = tmp_path / "quality_gate_reproduced.json"
    cmd = [
        sys.executable,
        "-m",
        "eval.run_quality_gate",
        "--split",
        "all",
        "--backend",
        "local",
        "--seed",
        "42",
        "--report",
        str(tmp_report),
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.returncode == 0, f"run_quality_gate failed:\n{proc.stderr}"
    assert tmp_report.is_file(), f"Reproduced report not created at {tmp_report}"

    reproduced_data = json.loads(tmp_report.read_text(encoding="utf-8"))

    # Assert 144 queries present (72 dev, 72 held-out)
    query_details = reproduced_data.get("query_details", [])
    assert len(query_details) == 144, f"Expected 144 queries, got {len(query_details)}"
    dev_queries = [q for q in query_details if q.get("split") == "dev"]
    heldout_queries = [q for q in query_details if q.get("split") == "held-out"]
    assert len(dev_queries) == 72, f"Expected 72 dev queries, got {len(dev_queries)}"
    assert len(heldout_queries) == 72, f"Expected 72 held-out queries, got {len(heldout_queries)}"

    # Strip runtime/timestamp non-deterministic fields
    expected_clean = _strip_nondeterministic_fields(committed_baseline)
    actual_clean = _strip_nondeterministic_fields(reproduced_data)

    # Assert exact bit-for-bit equivalence
    assert actual_clean == expected_clean, (
        f"Reproduced quality gate data differs from committed baseline!\n"
        f"Actual summary: {actual_clean.get('summary')}\n"
        f"Expected summary: {expected_clean.get('summary')}"
    )


def test_quality_gate_split_dev_baseline_assert_gate_passes() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    baseline_path = repo_root / "eval" / "reports" / "quality_gate_baseline.json"
    assert baseline_path.is_file(), f"Committed baseline report missing at {baseline_path}"

    cmd = [
        sys.executable,
        "-m",
        "eval.run_quality_gate",
        "--split",
        "dev",
        "--backend",
        "local",
        "--seed",
        "42",
        "--baseline",
        str(baseline_path),
        "--assert-gate",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"run_quality_gate --split dev failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert "pareto_no_quality_drop: value=0.5909 >= 0.5909" in proc.stdout


def test_quality_gate_split_all_baseline_assert_gate_passes() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    baseline_path = repo_root / "eval" / "reports" / "quality_gate_baseline.json"
    assert baseline_path.is_file(), f"Committed baseline report missing at {baseline_path}"

    cmd = [
        sys.executable,
        "-m",
        "eval.run_quality_gate",
        "--split",
        "all",
        "--backend",
        "local",
        "--seed",
        "42",
        "--baseline",
        str(baseline_path),
        "--assert-gate",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"run_quality_gate --split all failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert "pareto_no_quality_drop: value=0.6099 >= 0.6099" in proc.stdout


def test_quality_gate_nonexistent_baseline_fails_closed() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    nonexistent_path = repo_root / "eval" / "reports" / "nonexistent.json"
    assert not nonexistent_path.exists()

    cmd = [
        sys.executable,
        "-m",
        "eval.run_quality_gate",
        "--split",
        "dev",
        "--backend",
        "local",
        "--seed",
        "42",
        "--baseline",
        str(nonexistent_path),
        "--assert-gate",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, "Expected non-zero exit code for nonexistent baseline"

