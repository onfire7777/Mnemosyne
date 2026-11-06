import os
from types import SimpleNamespace

import pytest

from mnemosyne.cli import _peak_rss_mb


def test_emit_serialization_failure_does_not_write_partial_json(capsys):
    from mnemosyne.cli import emit

    with pytest.raises(TypeError):
        emit({"a": "valid synthetic prefix", "z": object()})
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("peak", [None, 5120.0])
def test_compact_batch_preserves_peak_after_search_before_emit(tmp_path, monkeypatch, peak):
    from mnemosyne import cli

    query_file = tmp_path / "queries.jsonl"
    query_file.write_text(
        '{"question_id":"q1","tenant":"synthetic","query":"test"}\n',
        encoding="utf-8",
    )
    events = []

    def search(**kwargs):
        events.append("search")
        return {"hits": [], "explain": {"channels": []}, "abstained": True}

    def sample_peak():
        events.append("peak")
        return peak

    def prepare(queries, embedding):
        assert queries == ["test"]
        events.append("prepare")

    ticks = iter([10.0, 10.025])

    def clock():
        events.append("clock")
        return next(ticks)

    def emit(payload):
        events.append("emit")
        assert payload["peak_rss_mb"] == peak
        assert payload["peak_rss_scope"] == "current_process_lifetime_peak_before_output_serialization"
        assert payload["peak_rss_unit"] == "MiB"
        assert payload["count"] == 1
        assert payload["results"][0]["question_id"] == "q1"
        assert payload["results"][0]["latency_ms"] == 25.0

    adapters = SimpleNamespace(passage_graph=SimpleNamespace(prepare=prepare), embedding=object())
    tools = SimpleNamespace(engine=SimpleNamespace(adapters=adapters), search=search)
    monkeypatch.setattr(cli, "load_tools", lambda args: tools)
    monkeypatch.setattr(cli.time, "perf_counter", clock)
    monkeypatch.setattr(cli, "_peak_rss_mb", sample_peak)
    monkeypatch.setattr(cli, "emit", emit)
    cli.cmd_eval_query_batch(SimpleNamespace(
        evaluation_read_only=True, input_jsonl=str(query_file), max_records=1,
        compact=True, retrieval_mode="passages",
    ))
    assert events == ["prepare", "clock", "search", "clock", "peak", "emit"]


@pytest.mark.skipif(os.name != "nt", reason="Windows native memory accounting")
def test_windows_peak_memory_is_available_and_monotonic():
    before = _peak_rss_mb()
    probe = bytearray(8 * 1024 * 1024)
    for offset in range(0, len(probe), 4096):
        probe[offset] = 1
    after = _peak_rss_mb()
    assert before is not None and before > 0
    assert after is not None and after >= before


@pytest.mark.skipif(os.name != "nt", reason="Windows native memory accounting")
@pytest.mark.parametrize("failure", ["api_failure", "library_unavailable"])
def test_windows_peak_memory_failure_is_unknown_not_zero(monkeypatch, failure):
    import ctypes

    def memory_info(*args):
        return 0

    def load_library(name):
        if failure == "library_unavailable":
            raise OSError("library unavailable")
        return SimpleNamespace(GetProcessMemoryInfo=memory_info)

    monkeypatch.setattr(ctypes, "WinDLL", load_library)
    assert _peak_rss_mb() is None


@pytest.mark.skipif(os.name != "nt", reason="Windows native memory accounting")
def test_windows_peak_memory_preserves_values_above_four_gib(monkeypatch):
    import ctypes

    def memory_info(process, counters, size):
        assert size == ctypes.sizeof(counters._obj)
        counters._obj.PeakWorkingSetSize = 5 * 1024**3
        return 1

    monkeypatch.setattr(
        ctypes, "WinDLL",
        lambda name: SimpleNamespace(GetProcessMemoryInfo=memory_info),
    )
    assert _peak_rss_mb() == 5120.0
