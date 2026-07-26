import hashlib
import json
import stat
from pathlib import Path

import pytest

import leaderboard.render as renderer
from leaderboard.render import RenderError, main, render_site


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


def test_metric_ties_are_deterministic_for_logically_identical_orderings(
    tmp_path: Path,
) -> None:
    first_record = _result()
    tied_metric = dict(first_record["metrics"][0])
    tied_metric["value"] = 0.5
    first_record["metrics"] = [first_record["metrics"][0], tied_metric]
    second_record = dict(first_record)
    second_record["metrics"] = list(reversed(first_record["metrics"]))
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])

    render_site(
        _write_json(tmp_path / "first.json", first_record),
        {"result-001": traces},
        tmp_path / "first-site",
    )
    render_site(
        _write_json(tmp_path / "second.json", second_record),
        {"result-001": traces},
        tmp_path / "second-site",
    )

    assert _tree(tmp_path / "first-site") == _tree(tmp_path / "second-site")


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


def test_rejects_cyclic_supersession_across_result_arrays(tmp_path: Path) -> None:
    first = _result("result-a")
    second = _result("result-b")
    first["history"] = {"supersedes": "result-b"}
    second["history"] = {"supersedes": "result-a"}
    results = _write_json(tmp_path / "results.json", [first, second])
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])

    with pytest.raises(RenderError, match="result contract"):
        render_site(
            results,
            {"result-a": traces, "result-b": traces},
            tmp_path / "site",
        )

    assert not (tmp_path / "site").exists()


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


def test_trace_jsonl_allows_literal_unicode_line_separator(tmp_path: Path) -> None:
    results = _write_json(tmp_path / "results.json", _result())
    traces = tmp_path / "traces.jsonl"
    traces.write_text(
        '{"question_id":"question-001","answer":"line\u2028break"}\n',
        encoding="utf-8",
    )
    output = tmp_path / "site"

    render_site(results, {"result-001": traces}, output)

    assert (output / "index.html").is_file()


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


def test_publication_failure_preserves_existing_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "index.html").write_bytes(b"previous output\n")
    before = _tree(output)
    results = _write_json(tmp_path / "results.json", _result())
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])
    real_replace = renderer.os.replace

    def fail_new_install(source: Path, destination: Path) -> None:
        if destination == output and "-backup-" not in source.name:
            raise OSError("injected install failure")
        real_replace(source, destination)

    monkeypatch.setattr(renderer.os, "replace", fail_new_install)

    with pytest.raises(RenderError, match="failed to publish"):
        render_site(results, {"result-001": traces}, output)

    assert _tree(output) == before
    assert not list(tmp_path.glob(".site-*"))


def test_double_replace_failure_restores_existing_site_by_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "index.html").write_bytes(b"previous output\n")
    before = _tree(output)
    results = _write_json(tmp_path / "results.json", _result())
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])
    real_replace = renderer.os.replace

    def fail_install_and_restore(source: Path, destination: Path) -> None:
        if destination == output and source != output:
            raise OSError("injected replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(renderer.os, "replace", fail_install_and_restore)

    with pytest.raises(RenderError, match="failed to publish"):
        render_site(results, {"result-001": traces}, output)

    assert _tree(output) == before
    assert not list(tmp_path.glob(".site-*"))


def test_failed_restore_copy_removes_partial_site_and_preserves_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "index.html").write_bytes(b"previous output\n")
    before = _tree(output)
    results = _write_json(tmp_path / "results.json", _result())
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])
    real_replace = renderer.os.replace

    def fail_install_and_restore(source: Path, destination: Path) -> None:
        if destination == output and source != output:
            raise OSError("injected replacement failure")
        real_replace(source, destination)

    def fail_partial_copy(source: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "partial.html").write_bytes(b"partial\n")
        raise OSError("injected copy failure")

    monkeypatch.setattr(renderer.os, "replace", fail_install_and_restore)
    monkeypatch.setattr(renderer.shutil, "copytree", fail_partial_copy)

    with pytest.raises(RenderError, match="backup preserved at"):
        render_site(results, {"result-001": traces}, output)

    assert not output.exists()
    backups = list(tmp_path.glob(".site-backup-*"))
    assert len(backups) == 1
    assert _tree(backups[0]) == before


def test_failed_partial_site_cleanup_reports_both_recovery_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "index.html").write_bytes(b"previous output\n")
    results = _write_json(tmp_path / "results.json", _result())
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])
    real_replace = renderer.os.replace
    real_rmtree = renderer.shutil.rmtree

    def fail_install_and_restore(source: Path, destination: Path) -> None:
        if destination == output and source != output:
            raise OSError("injected replacement failure")
        real_replace(source, destination)

    def fail_partial_copy(source: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "partial.html").write_bytes(b"partial\n")
        raise OSError("injected copy failure")

    def fail_partial_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        if path == output:
            raise OSError("injected cleanup failure")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(renderer.os, "replace", fail_install_and_restore)
    monkeypatch.setattr(renderer.shutil, "copytree", fail_partial_copy)
    monkeypatch.setattr(renderer.shutil, "rmtree", fail_partial_cleanup)

    with pytest.raises(
        RenderError,
        match=r"failed to remove partial site at: .*site; backup preserved at:",
    ):
        render_site(results, {"result-001": traces}, output)

    assert (output / "partial.html").is_file()
    backups = list(tmp_path.glob(".site-backup-*"))
    assert len(backups) == 1


def test_new_site_has_deployable_directory_permissions(tmp_path: Path) -> None:
    results = _write_json(tmp_path / "results.json", _result())
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])
    output = tmp_path / "site"

    render_site(results, {"result-001": traces}, output)

    assert stat.S_IMODE(output.stat().st_mode) == 0o755


def test_rejects_symlink_destination_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "index.html").write_bytes(b"unrelated data\n")
    before = _tree(target)
    output = tmp_path / "site"
    output.symlink_to(target, target_is_directory=True)
    results = _write_json(tmp_path / "results.json", _result())
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])

    with pytest.raises(RenderError, match="symlink"):
        render_site(results, {"result-001": traces}, output)

    assert output.is_symlink()
    assert _tree(target) == before
    assert not list(tmp_path.glob(".site-*"))


def test_cli_reports_publication_setup_failure_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results = _write_json(tmp_path / "results.json", _result())
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])
    invalid_parent = tmp_path / "not-a-directory"
    invalid_parent.write_text("file", encoding="utf-8")

    assert (
        main(
            [
                str(results),
                str(invalid_parent / "site"),
                f"result-001={traces}",
            ]
        )
        == 2
    )

    error = capsys.readouterr().err
    assert error.startswith("error: failed to publish site:")
    assert "Traceback" not in error


def test_cli_reports_utf8_publication_failure_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results = _write_json(tmp_path / "results.json", _result())
    traces = tmp_path / "traces.jsonl"
    traces.write_text(
        '{"question_id":"question-001","answer":"\\ud800"}\n',
        encoding="utf-8",
    )

    assert (
        main(
            [
                str(results),
                str(tmp_path / "site"),
                f"result-001={traces}",
            ]
        )
        == 2
    )

    error = capsys.readouterr().err
    assert error.startswith("error: failed to publish site:")
    assert "Traceback" not in error
    assert not list(tmp_path.glob(".site-*"))


def test_cli_reports_invalid_input_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")

    assert main([str(invalid), str(tmp_path / "site"), "result-001=missing"]) == 2

    error = capsys.readouterr().err
    assert error.startswith("error: invalid JSON:")
    assert "Traceback" not in error


def test_cli_renders_valid_input_and_rejects_duplicate_mappings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results = _write_json(tmp_path / "results.json", _result())
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])
    mapping = f"result-001={traces}"

    assert main([str(results), str(tmp_path / "site"), mapping]) == 0
    assert (tmp_path / "site" / "index.html").is_file()
    assert main([str(results), str(tmp_path / "other-site"), mapping, mapping]) == 2
    assert "invalid trace mapping" in capsys.readouterr().err
