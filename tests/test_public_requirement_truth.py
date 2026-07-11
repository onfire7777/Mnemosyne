from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bench_005_cannot_complete_before_phase_12_qa_evidence() -> None:
    requirements = (ROOT / ".planning/REQUIREMENTS.md").read_text(encoding="utf-8")
    row = next(line for line in requirements.splitlines() if "BENCH-005" in line and "HippoRAG" in line)
    assert "[ ] BENCH-005" in row
    assert "Complete" not in row
    roadmap = (ROOT / ".planning/ROADMAP.md").read_text(encoding="utf-8")
    assert "BENCH-005 (reader-produced EM/F1 closure)" in requirements
    assert "BENCH-005 remains partial until" in roadmap


def test_phase_11_evidence_projection_keeps_retrieval_truth_boundaries() -> None:
    evidence = (ROOT / "eval/reports/phase-11-evidence.md").read_text(
        encoding="utf-8"
    )
    prose = " ".join(evidence.split())
    expected = {
        "MuSiQue": (
            "8.083333333333333",
            "10.416666666666668",
            "56.1",
            "74.7",
        ),
        "2Wiki": ("17.525", "23.725", "76.2", "90.4"),
        "HotpotQA": ("31.9", "37.4", "83.5", "96.3"),
    }
    for dataset, values in expected.items():
        rows = [
            line
            for line in evidence.splitlines()
            if line.startswith(f"| {dataset} |")
        ]
        assert len(rows) == 2
        metrics_row, baseline_row = rows
        assert all(value in baseline_row for value in values)
        assert "0/1000" in metrics_row
        assert "0" in metrics_row
        assert "absent" in metrics_row
    assert "Mnemosyne R@2 (%)" in evidence
    assert "Upstream R@5 (%)" in evidence
    assert "not comparable pass thresholds" in prose
    assert "No reader or judge ran" in prose
    assert "BENCH-005 remains partial" in prose
    assert "positive graph/PPR participation was not demonstrated" in prose
