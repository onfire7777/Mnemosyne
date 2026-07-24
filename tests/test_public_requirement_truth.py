from __future__ import annotations

import json
from pathlib import Path

from eval.harness.report import render_markdown


ROOT = Path(__file__).resolve().parents[1]


def test_bench_005_cannot_complete_before_phase_12_qa_evidence() -> None:
    requirements = (ROOT / ".planning/REQUIREMENTS.md").read_text(encoding="utf-8")
    row = next(
        line
        for line in requirements.splitlines()
        if "BENCH-005" in line and "HippoRAG" in line
    )
    assert "[ ] BENCH-005" in row
    assert "Complete" not in row
    roadmap = (ROOT / ".planning/ROADMAP.md").read_text(encoding="utf-8")
    assert "BENCH-005 (reader-produced EM/F1 closure)" in requirements
    assert "BENCH-005 remains partial until" in roadmap



def test_cap_003_stays_partial_until_measured_em_f1_at_least_0_85() -> None:
    """EM/F1 reporting honesty: CAP-003 is Partial without measured ≥ 0.85.

    Unit-path perfect scores on synthetic/public-CLI stand-ins must not flip the
    requirement to Complete. Live frozen + held-out thresholds remain open.
    """
    requirements = (ROOT / ".planning/REQUIREMENTS.md").read_text(encoding="utf-8")
    row = next(
        line
        for line in requirements.splitlines()
        if "CAP-003" in line and "qa_hard_v2" in line
    )
    assert "[ ] CAP-003" in row
    assert "Partial" in row
    assert "Complete" not in row
    assert "0.85" in row
    report = (ROOT / "eval/reports/phase-12-grounded-qa.md").read_text(encoding="utf-8")
    assert "CAP-003 remains Partial" in report
    assert "no CAP-003 Complete" in report
    # Gate numbers stay explicit; do not lower thresholds in prose or tables.
    assert "≥ 0.85" in report
    assert "Not re-measured live" in report

def test_phase_11_evidence_projection_keeps_retrieval_truth_boundaries() -> None:
    evidence = (ROOT / "eval/reports/phase-11-evidence.md").read_text(encoding="utf-8")
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
            line for line in evidence.splitlines() if line.startswith(f"| {dataset} |")
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
    assert "Executed engine: `local`" in evidence
    assert (
        "Configured/self-reported graph backend: `postgres-recursive-ppr`" in evidence
    )
    assert "not evidence that PostgreSQL executed" in prose


def test_slo_report_discloses_the_engine_that_executed() -> None:
    rendered = render_markdown(
        {
            "meta": {
                "backend": "postgres",
                "embedding_path": "external service (flags forwarded)",
            },
            "ignition": {},
            "overall": {},
        }
    )

    assert "**`postgres` engine**" in rendered
    assert "**external service (flags forwarded)**" in rendered
    assert "local deterministic engine" not in rendered
    assert "No model or provider identity is inferred" in rendered


def test_committed_slo_projections_match_retained_engine_metadata() -> None:
    reports = ROOT / "eval/reports"
    paired_reports = []
    for json_path in sorted(reports.rglob("slo_report*.json")):
        markdown_path = json_path.with_suffix(".md")
        if not markdown_path.is_file():
            continue
        paired_reports.append((json_path, markdown_path))
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        backend = payload["meta"]["backend"]
        markdown = markdown_path.read_text(encoding="utf-8")
        assert f"- **Backend:** `{backend}`" in markdown
        assert f"**`{backend}` engine**" in markdown

    assert len(paired_reports) == 9
