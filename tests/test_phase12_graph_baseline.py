from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval.datasets.v2 import run_graph_ppr_baseline as baseline


def _jsonl_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _query_result(question_id: str) -> dict[str, object]:
    return {
        "question_id": question_id,
        "search": {"hits": []},
        "explanation": {
            "adapters": {"graph_backend": "postgres-recursive-ppr"},
            "channels": {"graph_ppr": 0},
        },
    }


class _FakeCLI:
    def __init__(self, *, store: str, **_: object) -> None:
        self.store = Path(store)

    def capture_batch(self, input_jsonl: Path) -> dict[str, object]:
        rows = _jsonl_rows(input_jsonl)
        self.store.write_text('{"relations": []}\n', encoding="utf-8")
        return {"results": [{"cid": f"cid-{index}"} for index, _ in enumerate(rows)]}

    def eval_query_batch(self, input_jsonl: Path) -> dict[str, object]:
        rows = _jsonl_rows(input_jsonl)
        return {"results": [_query_result(str(row["question_id"])) for row in rows]}


def test_local_capture_path_has_deterministic_dead_graph_baseline(tmp_path: Path) -> None:
    summary = baseline.run_baseline(tmp_path / "baseline")

    assert summary["dataset_id"] == "qa_scale_dev_v1"
    assert summary["decomposition_matrix"] == {"case_count": 16, "passed": 16}
    assert summary["traces_byte_identical"] is True
    for run in summary["runs"]:
        assert run["actual_engine"] == "local"
        assert run["disclosed_graph_backends"] == ["postgres-recursive-ppr"]
        assert run["query_count"] == 24
        assert run["relations"] == 0
        assert run["graph_ppr_channel_sum"] == 0
        assert run["direct_retrieval_recall_at_5"] == 0.5
        assert run["per_query"]["q01"] == {
            "direct_retrieval_recall_at_5": 0.5,
            "graph_ppr": 0,
        }

    # Pre-fix baseline: round 7 must create relations, produce a graph_ppr hit,
    # and lift q01's direct-retrieval Recall@5 proxy from 0.5 to 1.0. The full
    # answer-harness Recall@5 remains unmeasured until role commands are available.


def test_capture_results_reject_duplicate_cids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class DuplicateCaptureCLI(_FakeCLI):
        def capture_batch(self, input_jsonl: Path) -> dict[str, object]:
            super().capture_batch(input_jsonl)
            rows = _jsonl_rows(input_jsonl)
            return {"results": [{"cid": "duplicate"} for _ in rows]}

    monkeypatch.setattr(baseline, "MnemoCLI", DuplicateCaptureCLI)

    with pytest.raises(ValueError, match="capture CID custody"):
        baseline._run_retrieval(baseline.load_dataset(baseline._DATASET), tmp_path / "run")


def test_query_results_reject_question_order_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ReorderedQueryCLI(_FakeCLI):
        def eval_query_batch(self, input_jsonl: Path) -> dict[str, object]:
            rows = list(reversed(_jsonl_rows(input_jsonl)))
            return {"results": [_query_result(str(row["question_id"])) for row in rows]}

    monkeypatch.setattr(baseline, "MnemoCLI", ReorderedQueryCLI)

    with pytest.raises(ValueError, match="query order drift"):
        baseline._run_retrieval(baseline.load_dataset(baseline._DATASET), tmp_path / "run")


def test_output_path_boundary_requires_new_external_non_symlink_path(tmp_path: Path) -> None:
    external = tmp_path / "external"
    assert baseline._validate_output_path(external) == external.resolve()

    with pytest.raises(ValueError, match="outside the repository"):
        baseline._validate_output_path(Path.cwd() / ".phase12-baseline-test-output")

    link = tmp_path / "link"
    try:
        link.symlink_to(tmp_path / "target", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ValueError, match="non-symlink"):
        baseline._validate_output_path(link)


def test_graph_baseline_cli_retains_artifacts_and_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "cli-baseline"
    command = [
        sys.executable,
        "-m",
        "eval.datasets.v2.run_graph_ppr_baseline",
        "--output",
        str(output),
    ]

    first = subprocess.run(command, check=False, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    expected = {
        "summary.json",
        *{
            f"run-{run}/{name}"
            for run in (1, 2)
            for name in (
                "capture.jsonl",
                "metrics.json",
                "queries.jsonl",
                "store.json",
                "traces.jsonl",
            )
        },
    }
    artifacts = {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert set(artifacts) == expected

    second = subprocess.run(command, check=False, capture_output=True, text=True)
    assert second.returncode != 0
    assert "baseline output must not already exist" in second.stderr
    assert {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    } == artifacts


def test_graph_baseline_report_matches_generated_metrics(tmp_path: Path) -> None:
    summary = baseline.run_baseline(tmp_path / "report-baseline")
    first, second = summary["runs"]
    report = Path("eval/reports/phase-12-graph-baseline-2026-07-15.md").read_text(
        encoding="utf-8"
    )

    expected_rows = [
        f'| Captured corpus rows | {first["captured_count"]} | {second["captured_count"]} |',
        f'| Queries | {first["query_count"]} | {second["query_count"]} |',
        f'| Persisted relations | {first["relations"]} | {second["relations"]} |',
        "| `graph_ppr` channel contribution | "
        f'{first["graph_ppr_channel_sum"]} | {second["graph_ppr_channel_sum"]} |',
        "| Direct-query Recall@5 proxy | "
        f'{first["direct_retrieval_recall_at_5"]} | '
        f'{second["direct_retrieval_recall_at_5"]} |',
        "| Direct-query nDCG@5 proxy | "
        f'{first["direct_retrieval_ndcg_at_5"]} | '
        f'{second["direct_retrieval_ndcg_at_5"]} |',
        "| `traces.jsonl` SHA-256 | "
        f'`{first["trace_sha256"]}` | `{second["trace_sha256"]}` |',
    ]
    assert all(row in report for row in expected_rows)
    assert (
        "- Engine-under-test base commit: "
        "`7bca39e250f6227298cf3f0b1950fdd9d59905b3`"
    ) in report
    assert (
        "- Baseline runner/evidence commit: "
        "`833af4fe519af6fbc57bcd2e4eb983c38afe5000`"
    ) in report
    assert Path("eval/datasets/v2/run_graph_ppr_baseline.py").is_file()
    assert "Full answer-harness Recall@5 was not measured" in report
    assert (
        "Every measured explanation disclosed `graph_backend` as\n"
        "`postgres-recursive-ppr`, while the evaluator actually ran the local engine."
    ) in report
