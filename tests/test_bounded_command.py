"""Adversarial checks for bounded provider command execution."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

import pytest

import mnemosyne.providers.bounded_command as bounded_command
from mnemosyne.providers.bounded_command import (
    CommandOutputLimitError,
    run_bounded_command,
)


class _NoopJob:
    def close(self) -> None:
        pass


def _single_process_windows(
    argv: list[str], payload: bytes
) -> tuple[subprocess.Popen[bytes], object, object, _NoopJob]:
    stdin = tempfile.TemporaryFile()
    stdin.write(payload)
    stdin.seek(0)
    process = subprocess.Popen(
        argv, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    def terminate() -> None:
        if process.poll() is None:
            process.kill()

    return process, stdin, terminate, _NoopJob()


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


def _wait_for_file(path: Path, timeout_seconds: float = 2) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.exists(), f"{path} was not created before the bounded deadline"


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX selector path")
def test_posix_spawn_contract_matches_main(monkeypatch: pytest.MonkeyPatch) -> None:
    original_popen = subprocess.Popen
    seen: dict[str, object] = {}

    def capture_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        seen.update(kwargs)
        return original_popen(*args, **kwargs)  # type: ignore[arg-type, return-value]

    monkeypatch.setattr(bounded_command.subprocess, "Popen", capture_popen)
    result = run_bounded_command(
        _python("print('ok')"), b"", timeout_seconds=2, max_stdout_bytes=16
    )

    assert run_bounded_command is bounded_command._run_posix_bounded_command
    assert result.stdout == b"ok\n"
    assert set(seen) == {"stdin", "stdout", "stderr"}


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_each_output_stream_has_an_independent_limit(stream: str) -> None:
    code = (
        "import sys; "
        f"getattr(sys, '{stream}').buffer.write(b'x' * 128); "
        f"getattr(sys, '{stream}').flush()"
    )
    with pytest.raises(CommandOutputLimitError):
        run_bounded_command(
            _python(code),
            b"",
            timeout_seconds=2,
            max_stdout_bytes=16,
            max_stderr_bytes=16,
        )


@pytest.mark.skipif(os.name != "nt", reason="requires a native Windows Job Object")
def test_windows_timeout_kills_grandchild(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    child = "import time; time.sleep(30)"
    code = (
        "import pathlib, subprocess, sys, time; "
        f"child=subprocess.Popen([sys.executable, '-c', {child!r}]); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); time.sleep(30)"
    )

    outcome: queue.Queue[BaseException | None] = queue.Queue()

    def invoke() -> None:
        try:
            run_bounded_command(
                _python(code), b"", timeout_seconds=2, max_stdout_bytes=128
            )
        except BaseException as error:
            outcome.put(error)
        else:
            outcome.put(None)

    started = time.monotonic()
    runner = threading.Thread(target=invoke, daemon=True)
    runner.start()
    _wait_for_file(pid_file)
    runner.join(timeout=3)
    assert not runner.is_alive(), "bounded command did not finish after its deadline"
    error = outcome.get_nowait()
    assert isinstance(error, subprocess.TimeoutExpired)
    assert time.monotonic() - started < 5
    _assert_exited(pid_file)


@pytest.mark.skipif(os.name != "nt", reason="requires a native Windows Job Object")
def test_windows_leader_exit_with_held_pipes_kills_descendant(
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


@pytest.mark.skipif(os.name != "nt", reason="requires a native Windows Job Object")
def test_windows_leader_exit_with_devnull_kills_descendant(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "silent-holder.pid"
    child = "import time; time.sleep(30)"
    code = (
        "import os, pathlib, subprocess, sys, time; "
        f"child=subprocess.Popen([sys.executable, '-c', {child!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); "
        "os.close(1); os.close(2); time.sleep(0.5)"
    )

    result = run_bounded_command(
        _python(code), b"", timeout_seconds=2, max_stdout_bytes=128
    )
    assert result.returncode == 0
    _assert_exited(pid_file)


@pytest.mark.skipif(os.name != "nt", reason="requires a native Windows Job Object")
def test_windows_output_overflow_kills_pipe_holder(tmp_path: Path) -> None:
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
        run_bounded_command(_python(code), b"", timeout_seconds=2, max_stdout_bytes=16)
    assert time.monotonic() - started < 5
    _assert_exited(pid_file)


def test_mocked_windows_runs_leave_no_bounded_reader_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bounded_command, "_windows_process", _single_process_windows)
    before = {
        thread.ident
        for thread in threading.enumerate()
        if thread.name.startswith("bounded-command-")
    }
    for _ in range(3):
        assert (
            bounded_command._run_windows_bounded_command(
                _python("print('ok')"), b"", timeout_seconds=2, max_stdout_bytes=16
            ).stdout
            == b"ok\n"
        )
        with pytest.raises(CommandOutputLimitError):
            bounded_command._run_windows_bounded_command(
                _python("print('x' * 64)"), b"", timeout_seconds=2, max_stdout_bytes=16
            )
    after = {
        thread.ident
        for thread in threading.enumerate()
        if thread.name.startswith("bounded-command-")
    }
    assert after == before


def test_second_reader_start_failure_kills_target_and_joins_first_reader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(bounded_command, "_windows_process", _single_process_windows)
    pid_file = tmp_path / "start-failure.pid"
    code = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(30)"
    )
    original_start = threading.Thread.start

    def fail_stderr_reader(thread: threading.Thread) -> None:
        if thread.name == "bounded-command-stderr":
            _wait_for_file(pid_file)
            raise RuntimeError("simulated second reader start failure")
        original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", fail_stderr_reader)
    with pytest.raises(RuntimeError, match="simulated second reader"):
        bounded_command._run_windows_bounded_command(
            _python(code), b"", timeout_seconds=2, max_stdout_bytes=128
        )
    _assert_exited(pid_file)
    assert not any(
        thread.name.startswith("bounded-command-") and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_windows_process_assigns_job_before_releasing_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    process = types.SimpleNamespace(_handle=123)

    class StartupInfo:
        lpAttributeList: dict[str, list[int]]

    class Job(_NoopJob):
        def assign(self, assigned: object) -> None:
            assert assigned is process
            events.append("assign")

        def terminate(self) -> None:
            events.append("terminate")

    def popen(argv: list[str], **kwargs: object) -> object:
        events.append("popen")
        assert argv[:4] == [sys.executable, "-I", "-S", "-c"]
        assert argv[-1] == "110"
        assert kwargs["close_fds"] is True
        startupinfo = kwargs["startupinfo"]
        assert isinstance(startupinfo, StartupInfo)
        assert startupinfo.lpAttributeList == {"handle_list": [110]}
        return process

    monkeypatch.setitem(
        sys.modules, "msvcrt", types.SimpleNamespace(get_osfhandle=lambda fd: fd + 100)
    )
    monkeypatch.setattr(
        bounded_command.subprocess, "STARTUPINFO", StartupInfo, raising=False
    )
    monkeypatch.setattr(bounded_command.subprocess, "Popen", popen)
    monkeypatch.setattr(bounded_command.os, "pipe", lambda: (10, 11))
    monkeypatch.setattr(bounded_command.os, "set_inheritable", lambda *_: None)
    monkeypatch.setattr(
        bounded_command.os, "close", lambda fd: events.append(f"close:{fd}")
    )
    monkeypatch.setattr(
        bounded_command.os,
        "write",
        lambda fd, data: events.append(f"write:{fd}:{data!r}") or len(data),
    )
    monkeypatch.setattr(bounded_command, "_WindowsJob", Job)

    assigned_process, stdin, terminate, job = bounded_command._windows_process(
        ["provider", "literal arg"], b"payload"
    )
    try:
        assert assigned_process is process
        assert events.index("assign") < events.index("write:11:b'1'")
        terminate()
    finally:
        stdin.close()
        job.close()
