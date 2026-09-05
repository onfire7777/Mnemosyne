"""Frontend smoke: public `render_site` HTML output contract.

Consumes `leaderboard.render.render_site` only. Does not re-test Backend
unit cases (validation matrix, publication restore, mixed-schema, etc.).
"""

from pathlib import Path
from urllib.parse import urlparse

import pytest

from leaderboard.render import RenderError, render_site
from tests.test_leaderboard_render import (
    _bind_v2_artifacts,
    _digest,
    _result,
    _trace,
    _write_json,
    _write_traces,
)
from tests.test_leaderboard_result_contract import _v2_development_record

HOSTILE_RECORD_ID = "../../<script>alert(1)</script>"


def _hrefs(html: str) -> list[str]:
    return [part.split('"', 1)[0] for part in html.split('href="')[1:]]


def _assert_safe_relative_hrefs(html: str) -> None:
    for href in _hrefs(html):
        parsed = urlparse(href)
        assert parsed.scheme == "", href
        assert parsed.netloc == "", href
        assert not href.startswith("/"), href


def _assert_leaderboard_site(output: Path, record_id: str) -> Path:
    index_path = output / "index.html"
    assert index_path.is_file()
    index = index_path.read_text(encoding="utf-8")
    assert index.startswith("<!doctype html>")
    assert "<html" in index
    assert "<title>Leaderboard</title>" in index
    assert "<h1>Leaderboard</h1>" in index

    digest = _digest(record_id)
    relative = f"results/{digest}.html"
    assert f'href="{relative}"' in index
    _assert_safe_relative_hrefs(index)

    result_path = output / "results" / f"{digest}.html"
    assert result_path.is_file()
    result_page = result_path.read_text(encoding="utf-8")
    assert result_page.startswith("<!doctype html>")
    assert "<html" in result_page
    assert 'href="../index.html"' in result_page
    _assert_safe_relative_hrefs(result_page)
    return result_path


def test_v1_render_site_writes_leaderboard_html_with_escaped_result_pages(
    tmp_path: Path,
) -> None:
    results = _write_json(tmp_path / "results.json", _result(HOSTILE_RECORD_ID))
    traces = _write_traces(tmp_path / "traces.jsonl", [_trace()])
    output = tmp_path / "site"

    render_site(results, {HOSTILE_RECORD_ID: traces}, output)

    _assert_leaderboard_site(output, HOSTILE_RECORD_ID)
    rendered = "".join(
        path.read_text(encoding="utf-8") for path in output.rglob("*.html")
    )
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert HOSTILE_RECORD_ID not in "\n".join(
        path.relative_to(output).as_posix() for path in output.rglob("*")
    )


def test_v2_development_record_renders_when_artifacts_are_bound(
    tmp_path: Path,
) -> None:
    record = _v2_development_record()
    artifacts = _bind_v2_artifacts(tmp_path, record)
    record_id = str(record["record_id"])
    results = _write_json(tmp_path / "results.json", record)
    output = tmp_path / "site"

    render_site(
        results,
        {record_id: artifacts["traces.jsonl"]},
        output,
        artifacts={
            record_id: {
                "build": artifacts["build.json"],
                "config": artifacts["config.json"],
                "bundle": artifacts["bundle-manifest.json"],
            }
        },
    )

    result_path = _assert_leaderboard_site(output, record_id)
    assert "DEVELOPMENT" in result_path.read_text(encoding="utf-8")


def test_render_error_does_not_leave_partial_destination(tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text("{", encoding="utf-8")
    output = tmp_path / "site"

    with pytest.raises(RenderError):
        render_site(results, {}, output)

    assert not output.exists()
