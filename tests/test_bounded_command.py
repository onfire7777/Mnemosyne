"""Adversarial checks for bounded provider command execution."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from mnemosyne.providers.bounded_command import (
    CommandOutputLimitError,
    run_bounded_command,
)


def _python(code: str, *args: str) -> list[str]:
    return [sys.executable, "-c", code, *args]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _assert_exited(pid_file: Path) -> None:
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _alive(pid), f"descendant {pid} survived bounded-command cleanup"


def test_round_trip_preserves_payload_streams_status_and_literal_argv() -> None:
    result = run_bounded_command(
        _python(
            "import sys; data=sys.stdin.buffer.read(); "
            "sys.stdout.buffer.write(data + sys.argv[1].encode()); "
            "sys.stderr.buffer.write(b'err'); raise SystemExit(7)",
            "$(not-a-shell)&literal",
        ),
        b"\x00payload\xff",
        timeout_seconds=2,
        max_stdout_bytes=128,
        max_stderr_bytes=128,
    )

    assert result.returncode == 7
    assert result.stdout == b"\x00payload\xff$(not-a-shell)&literal"
    assert result.stderr == b"err"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_each_output_stream_has_an_independent_limit(stream: str) -> None:
    code = (
        "import sys; "
        f"getattr(sys, '{stream}').buffer.write(b'x' * 128); "
        f"getattr(sys, '{stream}').flush()"
    )
    with pytest.raises(CommandOutputLimitError):
        run_bounded_command(
            _python(code), b"", timeout_seconds=2, max_stdout_bytes=16, max_stderr_bytes=16
        )


def test_timeout_kills_grandchild(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    child = "import time; time.sleep(30)"
    code = (
        "import pathlib, subprocess, sys, time; "
        f"child=subprocess.Popen([sys.executable, '-c', {child!r}]); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); time.sleep(30)"
    )

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded_command(
            _python(code), b"", timeout_seconds=0.2, max_stdout_bytes=128
        )
    assert time.monotonic() - started < 5
    _assert_exited(pid_file)


def test_leader_exit_with_descendant_held_pipes_returns_and_kills_descendant(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "pipe-holder.pid"
    child = "import time; time.sleep(30)"
    code = (
        "import pathlib, subprocess, sys; "
        f"child=subprocess.Popen([sys.executable, '-c', {child!r}]); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))"
    )

    started = time.monotonic()
    result = run_bounded_command(
        _python(code), b"", timeout_seconds=2, max_stdout_bytes=128
    )
    assert time.monotonic() - started < 5
    assert result.returncode == 0
    _assert_exited(pid_file)


def test_output_overflow_kills_descendant_holding_pipes(tmp_path: Path) -> None:
    pid_file = tmp_path / "overflow-holder.pid"
    child = "import time; time.sleep(30)"
    code = (
        "import pathlib, subprocess, sys, time; "
        f"child=subprocess.Popen([sys.executable, '-c', {child!r}]); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); "
        "sys.stdout.write('x' * 128); sys.stdout.flush(); time.sleep(30)"
    )

    started = time.monotonic()
    with pytest.raises(CommandOutputLimitError):
        run_bounded_command(
            _python(code), b"", timeout_seconds=2, max_stdout_bytes=16
        )
    assert time.monotonic() - started < 5
    _assert_exited(pid_file)


def test_repeated_runs_leave_no_bounded_reader_threads() -> None:
    before = {thread.ident for thread in threading.enumerate() if thread.name.startswith("bounded-command-")}
    for _ in range(3):
        assert run_bounded_command(
            _python("print('ok')"), b"", timeout_seconds=2, max_stdout_bytes=16
        ).stdout == b"ok\n"
        with pytest.raises(CommandOutputLimitError):
            run_bounded_command(
                _python("print('x' * 64)"), b"", timeout_seconds=2, max_stdout_bytes=16
            )
    after = {thread.ident for thread in threading.enumerate() if thread.name.startswith("bounded-command-")}
    assert after == before
