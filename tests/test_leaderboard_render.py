import hashlib
import json
from pathlib import Path

import pytest

from leaderboard.render import RenderError, render_site


def _result(record_id: str = "result-001") -> dict[str, object]:
    return {
        "schema_version": "mnemosyne.leaderboard.result/v1",
        "record_id": record_id,
        "system": "mnemosyne",
        "track": "development",
        "benchmark": "synthetic-retrieval",
        "benchmark_version": "1",
        "run_commit": "0123456789abcdef0123456789abcdef01234567",
        "build_fingerprint": f"sha256:{'1' * 64}",
        "config_digest": f"sha256:{'2' * 64}",
        "bundle_digest": f"sha256:{'3' * 64}",
        "trace_index_digest": f"sha256:{'4' * 64}",
        "metrics": [
            {
                "name": "recall_at_10",
                "family": "retrieval",
                "value": 0.75,
                "unit": "ratio",
                "confidence_interval": {"low": 0.60, "high": 0.85},
            }
        ],
        "publication": {"publishable": False, "label": "operator-run"},
        "operator_entry": {"operator": "synthetic-test", "disclosed": True},
        "history": {"supersedes": None},
    }


def _trace(question_id: str = "question-001") -> dict[str, object]:
    return {
        "answer": "doc-1",
        "gold_references": ["doc-1"],
        "question_id": question_id,
        "ranked_retrieved_hits": ["doc-1", "doc-2"],
        "scoring_family": "deterministic-retrieval",
        "stored_records": ["doc-1", "doc-2"],
    }


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _write_traces(path: Path, traces: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(
            json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n"
            for trace in traces
        ),
        encoding="utf-8",
    )
    return path


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_renders_one_validated_result_and_its_public_bundle_trace(
    tmp_path: Path,
) -> None:
    results = _write_json(tmp_path / "results.json", _result())
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])
    output = tmp_path / "site"

    render_site(results, {"result-001": traces}, output)

    record_path = output / "results" / f"{_digest('result-001')}.html"
    trace_path = (
        output
        / "traces"
        / _digest("result-001")
        / f"{_digest('question-001')}.html"
    )
    assert record_path.is_file()
    assert trace_path.is_file()
    index = (output / "index.html").read_text(encoding="utf-8")
    result_page = record_path.read_text(encoding="utf-8")
    trace_page = trace_path.read_text(encoding="utf-8")
    assert "mnemosyne" in index
    assert "development" in index
    assert "synthetic-retrieval" in index
    assert "operator-run" in index
    assert "not publishable" in index.lower()
    assert "synthetic-test" in index
    assert "recall_at_10" in index
    assert f"results/{_digest('result-001')}.html" in index
    for immutable in (
        "0123456789abcdef0123456789abcdef01234567",
        f"sha256:{'1' * 64}",
        f"sha256:{'2' * 64}",
        f"sha256:{'3' * 64}",
        f"sha256:{'4' * 64}",
    ):
        assert immutable in result_page
    assert (
        f"../traces/{_digest('result-001')}/{_digest('question-001')}.html"
        in result_page
    )
    assert "Stored context/evidence" in trace_page
    assert "doc-1" in trace_page
    assert "Retrieved context/evidence" in trace_page
    assert "Final answer" in trace_page
    assert "../../results/" in trace_page


def test_renders_qa_evidence_fields_that_exist_in_the_source_trace(
    tmp_path: Path,
) -> None:
    results = _write_json(tmp_path / "results.json", _result())
    trace = _trace()
    trace.pop("ranked_retrieved_hits")
    trace.pop("stored_records")
    trace["authorized_retrieval_hops"] = [
        {"query": "where", "retrieved_evidence": ["fact <one>"]}
    ]
    trace["answer"] = "final <answer>"
    traces = _write_traces(tmp_path / "traces.jsonl", [trace])
    output = tmp_path / "site"

    render_site(results, {"result-001": traces}, output)

    page = (
        output
        / "traces"
        / _digest("result-001")
        / f"{_digest('question-001')}.html"
    ).read_text(encoding="utf-8")
    assert "authorized_retrieval_hops" in page
    assert "fact &lt;one&gt;" in page
    assert "final &lt;answer&gt;" in page


def test_output_is_deterministic_for_logically_identical_input_orderings(
    tmp_path: Path,
) -> None:
    first_results = [_result("result-b"), _result("result-a")]
    second_results = list(reversed(first_results))
    first = _write_json(tmp_path / "first.json", first_results)
    second = _write_json(tmp_path / "second.json", second_results)
    a_first = _write_traces(
        tmp_path / "a-first.jsonl", [_trace("question-2"), _trace("question-1")]
    )
    a_second = _write_traces(
        tmp_path / "a-second.jsonl", [_trace("question-1"), _trace("question-2")]
    )
    b_first = _write_traces(
        tmp_path / "b-first.jsonl", [_trace("question-4"), _trace("question-3")]
    )
    b_second = _write_traces(
        tmp_path / "b-second.jsonl", [_trace("question-3"), _trace("question-4")]
    )
    first_output, second_output = tmp_path / "first-site", tmp_path / "second-site"

    render_site(
        first,
        {"result-b": b_first, "result-a": a_first},
        first_output,
    )
    render_site(
        second,
        {"result-a": a_second, "result-b": b_second},
        second_output,
    )

    assert _tree(first_output) == _tree(second_output)
    assert all(raw.endswith(b"\n") and b"\r\n" not in raw for raw in _tree(first_output).values())


def test_escapes_hostile_values_and_uses_only_safe_relative_links(
    tmp_path: Path,
) -> None:
    record = _result("../../<script>alert(1)</script>")
    record["system"] = '<img src=x onerror="alert(1)">'
    results = _write_json(tmp_path / "results.json", record)
    trace = _trace("../<trace>")
    trace["answer"] = "<b>not markup</b>"
    traces = _write_traces(tmp_path / "traces.jsonl", [trace])
    output = tmp_path / "site"

    render_site(results, {record["record_id"]: traces}, output)

    rendered = b"".join(_tree(output).values()).decode()
    assert "<script>" not in rendered
    assert "<img src=x" not in rendered
    assert "<b>not markup</b>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&lt;b&gt;not markup&lt;/b&gt;" in rendered
    assert "../../<script>" not in "\n".join(_tree(output))


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("{", "invalid JSON"),
        ('{"record_id":"first","record_id":"second"}', "duplicate JSON key"),
        ('{"value":NaN}', "non-finite"),
    ],
)
def test_rejects_malformed_result_json_without_partial_output(
    tmp_path: Path, raw: str, match: str
) -> None:
    results = tmp_path / "results.json"
    results.write_text(raw, encoding="utf-8")
    output = tmp_path / "site"

    with pytest.raises(RenderError, match=match):
        render_site(results, {}, output)

    assert not output.exists()


def test_rejects_contract_invalid_and_duplicate_results(tmp_path: Path) -> None:
    invalid = _result()
    invalid["publication"] = {"publishable": True, "label": "operator-run"}
    invalid_path = _write_json(tmp_path / "invalid.json", invalid)
    duplicate_path = _write_json(
        tmp_path / "duplicate.json", [_result(), _result()]
    )
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])

    with pytest.raises(RenderError, match="result contract"):
        render_site(invalid_path, {"result-001": traces}, tmp_path / "invalid-site")
    with pytest.raises(RenderError, match="duplicate result"):
        render_site(
            duplicate_path, {"result-001": traces}, tmp_path / "duplicate-site"
        )

    assert not (tmp_path / "invalid-site").exists()
    assert not (tmp_path / "duplicate-site").exists()


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("{", "invalid JSON"),
        ('{"question_id":"first","question_id":"second"}\n', "duplicate JSON key"),
        ('{"question_id":"question-001","score":Infinity}\n', "non-finite"),
        ('{"answer":"orphan"}\n', "question_id"),
    ],
)
def test_rejects_malformed_public_bundle_trace_rows(
    tmp_path: Path, raw: str, match: str
) -> None:
    results = _write_json(tmp_path / "results.json", _result())
    traces = tmp_path / "traces.jsonl"
    traces.write_text(raw, encoding="utf-8")
    output = tmp_path / "site"

    with pytest.raises(RenderError, match=match):
        render_site(results, {"result-001": traces}, output)

    assert not output.exists()


def test_rejects_duplicate_missing_and_unlinked_trace_sources(
    tmp_path: Path,
) -> None:
    results = _write_json(tmp_path / "results.json", _result())
    duplicates = _write_traces(
        tmp_path / "duplicates.jsonl", [_trace(), _trace()]
    )
    valid = _write_traces(tmp_path / "valid.jsonl", [_trace()])

    with pytest.raises(RenderError, match="duplicate question_id"):
        render_site(results, {"result-001": duplicates}, tmp_path / "duplicate-site")
    with pytest.raises(RenderError, match="missing trace source"):
        render_site(results, {}, tmp_path / "missing-site")
    with pytest.raises(RenderError, match="unlinked trace source"):
        render_site(
            results,
            {"result-001": valid, "orphan-result": valid},
            tmp_path / "unlinked-site",
        )


def test_failed_render_preserves_the_previous_output_byte_for_byte(
    tmp_path: Path,
) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "index.html").write_bytes(b"previous output\n")
    before = _tree(output)
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")

    with pytest.raises(RenderError):
        render_site(invalid, {}, output)

    assert _tree(output) == before
    assert not list(tmp_path.glob(".site-*"))
