"""The outer resource guard preserves every attempt and stops its process group."""

import json
import os
from pathlib import Path
import sys

import pytest

from eval.public.monitor import run_monitored
import eval.public.monitor as monitor

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process-group monitor")


def test_success_retains_logs_and_refuses_reusing_attempt(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt"
    argv = [sys.executable, "-c", "print('retained output')"]
    result = run_monitored(argv, cwd=tmp_path, output_dir=attempt,
                           wall_seconds=5, pressure_probe=lambda: 1, poll_seconds=0.01)
    assert result["status"] == "succeeded"
    assert result["returncode"] == 0
    assert "retained output" in (attempt / "stdout.log").read_text()
    assert json.loads((attempt / "terminal.json").read_text()) == result
    with pytest.raises(FileExistsError):
        run_monitored(argv, cwd=tmp_path, output_dir=attempt,
                      wall_seconds=5, pressure_probe=lambda: 1)


@pytest.mark.parametrize("pressure", [2, 4, 0, None])
def test_non_normal_pressure_never_starts_child(tmp_path: Path, pressure: object) -> None:
    marker = tmp_path / "started"
    result = run_monitored(
        [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
        cwd=tmp_path, output_dir=tmp_path / "attempt", wall_seconds=5,
        pressure_probe=lambda: pressure,
    )
    assert result["status"] == "no_run"
    assert result["returncode"] is None
    assert not marker.exists()


@pytest.mark.parametrize("trigger", ["pressure", "timeout", "probe_error"])
def test_abort_stops_descendant_and_records_reason(tmp_path: Path, trigger: str) -> None:
    marker = tmp_path / "descendant-survived"
    ready = tmp_path / "ready"
    descendant = f"import time; time.sleep(1); open({str(marker)!r}, 'w').close()"
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); "
        f"open({str(ready)!r}, 'w').close(); time.sleep(10)"
    )

    def pressure_probe():
        if ready.exists() and trigger == "probe_error":
            raise OSError("probe unavailable")
        return 2 if ready.exists() and trigger == "pressure" else 1

    result = run_monitored(
        [sys.executable, "-c", parent], cwd=tmp_path,
        output_dir=tmp_path / "attempt", wall_seconds=0.25 if trigger == "timeout" else 5,
        pressure_probe=pressure_probe, poll_seconds=0.01,
    )
    assert ready.exists()
    assert result["status"] == "aborted"
    assert result["reason"] == {"pressure": "memory-pressure", "timeout": "wall-time-limit",
                                "probe_error": "monitor-error"}[trigger]
    # A surviving descendant would write after one second.
    import time
    time.sleep(1.05)
    assert not marker.exists()


def test_nonzero_exit_is_failure_not_a_score(tmp_path: Path) -> None:
    result = run_monitored([sys.executable, "-c", "raise SystemExit(7)"],
                           cwd=tmp_path, output_dir=tmp_path / "attempt",
                           wall_seconds=5, pressure_probe=lambda: 1, poll_seconds=0.01)
    assert result["status"] == "failed"
    assert result["returncode"] == 7


def test_slow_initial_probe_cannot_start_work_after_deadline(tmp_path: Path) -> None:
    import time
    marker = tmp_path / "started"

    def slow_probe():
        time.sleep(0.05)
        return 1

    result = run_monitored(
        [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
        cwd=tmp_path, output_dir=tmp_path / "attempt", wall_seconds=0.01,
        pressure_probe=slow_probe,
    )
    assert result["status"] == "no_run"
    assert result["reason"] == "wall-time-limit"
    assert "pid" not in result
    assert not marker.exists()


def test_cleanup_error_retains_failed_terminal_receipt(tmp_path: Path, monkeypatch) -> None:
    def broken_cleanup(process):
        process.wait(timeout=5)
        raise PermissionError("controlled cleanup error")

    monkeypatch.setattr(monitor, "_terminate_group", broken_cleanup)
    attempt = tmp_path / "attempt"
    result = run_monitored([sys.executable, "-c", "pass"], cwd=tmp_path,
                           output_dir=attempt, wall_seconds=5,
                           pressure_probe=lambda: 1, poll_seconds=0.01)
    assert result["status"] == "failed"
    assert result["reason"] == "cleanup-error"
    assert json.loads((attempt / "terminal.json").read_text()) == result


def test_cleanup_kills_child_that_ignores_term_after_parent_exits(tmp_path: Path) -> None:
    ready = tmp_path / "child-ready"
    marker = tmp_path / "survived"
    child = (
        "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"open({str(ready)!r},'w').close(); time.sleep(1); "
        f"open({str(marker)!r},'w').close()"
    )
    parent = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"ready=Path({str(ready)!r})\n"
        "while not ready.exists(): time.sleep(0.01)\n"
    )
    result = run_monitored([sys.executable, "-c", parent], cwd=tmp_path,
                           output_dir=tmp_path / "attempt", wall_seconds=5,
                           pressure_probe=lambda: 1, poll_seconds=0.01)
    assert ready.exists()
    assert result["status"] == "succeeded"
    import time
    time.sleep(1.05)
    assert not marker.exists()


def test_optional_resource_samples_are_retained_and_not_admission(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, 'process_group_rss_bytes', lambda group: 4096)
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'file').write_bytes(b'abc')
    attempt = tmp_path / 'attempt'
    result = run_monitored([sys.executable, '-c', 'pass'], cwd=tmp_path,
                           output_dir=attempt, wall_seconds=5, pressure_probe=lambda: 1,
                           poll_seconds=0.01, usage_roots=[data])
    assert result['status'] == 'succeeded'
    measurement = result['resource_diagnostics']
    assert measurement['peak_rss_verified'] is False
    assert measurement['admission_verified'] is False
    assert measurement['max_sampled_rss_bytes'] == 4096
    assert measurement['max_sampled_logical_file_bytes'] == 3
    rows = [json.loads(line) for line in (attempt / 'usage.jsonl').read_text().splitlines()]
    assert len(rows) == measurement['samples']
    assert all(row['logical_file_bytes'] == 3 for row in rows)


def test_resource_probe_failure_is_recorded_and_does_not_run_child(tmp_path, monkeypatch):
    def unavailable(roots):
        raise PermissionError('private path must not appear in receipt')
    monkeypatch.setattr(monitor, 'regular_file_bytes', unavailable)
    result = run_monitored([sys.executable, '-c', 'raise SystemExit(99)'], cwd=tmp_path,
                           output_dir=tmp_path / 'attempt', wall_seconds=5,
                           pressure_probe=lambda: 1, usage_roots=[tmp_path])
    assert result['status'] == 'no_run'
    assert result['reason'] == 'monitor-error'
    assert result['error_type'] == 'PermissionError'
    assert result['returncode'] is None
    assert 'private path' not in json.dumps(result)


def test_relative_usage_roots_resolve_against_child_cwd(tmp_path):
    child_cwd = tmp_path / 'child'
    child_cwd.mkdir()
    (child_cwd / 'measured').mkdir()
    (child_cwd / 'measured' / 'data').write_bytes(b'1234567')
    attempt = tmp_path / 'attempt'
    result = run_monitored([sys.executable, '-c', 'pass'], cwd=child_cwd,
                           output_dir=attempt, wall_seconds=5, pressure_probe=lambda: 1,
                           poll_seconds=0.01, usage_roots=[Path('measured')])
    assert result['status'] == 'succeeded'
    assert result['resource_diagnostics']['max_sampled_logical_file_bytes'] == 7
    assert result['resource_diagnostics']['disk_roots'] == [str(child_cwd / 'measured')]
    initial = json.loads((attempt / 'start.json').read_text())
    assert initial['resource_diagnostics']['disk_roots'] == [str(child_cwd / 'measured')]
