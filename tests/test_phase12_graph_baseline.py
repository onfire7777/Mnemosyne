from __future__ import annotations

from pathlib import Path

from eval.datasets.v2.run_graph_ppr_baseline import run_baseline


def test_local_capture_path_has_deterministic_dead_graph_baseline(tmp_path: Path) -> None:
    summary = run_baseline(tmp_path / "baseline")

    assert summary["dataset_id"] == "qa_scale_dev_v1"
    assert summary["decomposition_matrix"] == {"case_count": 16, "passed": 16}
    assert summary["traces_byte_identical"] is True
    for run in summary["runs"]:
        assert run["actual_engine"] == "local"
        assert run["query_count"] == 24
        assert run["relations"] == 0
        assert run["graph_ppr_channel_sum"] == 0
        assert run["recall_at_5"] == 0.5

    # Pre-fix baseline: round 7 must create relations, produce a graph_ppr hit,
    # and lift the bridge query's harness Recall@5 from 0.5 to 1.0 (its
    # graph-specific bridge contribution is currently 0 and must become 1).


def test_graph_baseline_report_records_engine_and_pbpp_mismatch() -> None:
    report = Path("eval/reports/phase-12-graph-baseline-2026-07-15.md").read_text(
        encoding="utf-8"
    )

    assert "Recall@5 `0.5`" in report
    assert "Actual engine: `LocalMemoryEngine`" in report
    assert "`postgres-recursive-ppr`" in report
    assert "makes no QA EM/F1 claim" in report
