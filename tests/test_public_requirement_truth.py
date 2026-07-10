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
