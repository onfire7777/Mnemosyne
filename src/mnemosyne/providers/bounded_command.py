"""Bounded subprocess capture for installed JSON provider commands."""

from __future__ import annotations

import ctypes
import json
import os
import queue
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import BinaryIO, Callable, Sequence


class CommandOutputLimitError(RuntimeError):
    pass


_CLEANUP_SECONDS = 0.5
_READ_CHUNK_BYTES = 64 * 1024
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _WindowsJob:
    """Own a Windows process tree; closing this handle kills every member."""

    def __init__(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [wintypes.HANDLE]
        self._close_handle.restype = wintypes.BOOL
        create = kernel32.CreateJobObjectW
        create.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        create.restype = wintypes.HANDLE
        set_information = kernel32.SetInformationJobObject
        set_information.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
        ]
        set_information.restype = wintypes.BOOL
        self._assign = kernel32.AssignProcessToJobObject
        self._assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._assign.restype = wintypes.BOOL
        self._terminate = kernel32.TerminateJobObject
        self._terminate.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._terminate.restype = wintypes.BOOL

        self.handle = create(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error(), "CreateJobObjectW")
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not set_information(
            self.handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error(), "SetInformationJobObject")

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        if not self._assign(self.handle, wintypes.HANDLE(process._handle)):  # type: ignore[attr-defined]
            raise ctypes.WinError(ctypes.get_last_error(), "AssignProcessToJobObject")

    def terminate(self) -> None:
        if self.handle and not self._terminate(self.handle, 1):
            error = ctypes.get_last_error()
            if error not in (0, 6):
                raise ctypes.WinError(error, "TerminateJobObject")

    def close(self) -> None:
        if self.handle:
            self._close_handle(self.handle)
            self.handle = wintypes.HANDLE()


_WINDOWS_HELPER = r"""
import json, msvcrt, os, struct, subprocess, sys, time

def read_exact(fd, length):
    chunks = []
    while length:
        chunk = os.read(fd, length)
        if not chunk:
            raise SystemExit(125)
        chunks.append(chunk)
        length -= len(chunk)
    return b''.join(chunks)

gate_fd = msvcrt.open_osfhandle(int(sys.argv[1]), os.O_RDONLY)
if not os.read(gate_fd, 1):
    raise SystemExit(125)
os.close(gate_fd)
header_size = struct.unpack('!I', read_exact(0, 4))[0]
argv = json.loads(read_exact(0, header_size).decode('utf-8'))
target = subprocess.Popen(argv, stdin=0, stdout=1, stderr=2, close_fds=False)
while target.poll() is None:
    time.sleep(0.02)
raise SystemExit(target.returncode)
"""


def _reader(
    stream: BinaryIO,
    output_index: int,
    limit: int,
    events: queue.Queue[tuple[str, object]],
    stopping: threading.Event,
) -> None:
    output = bytearray()
    try:
        while True:
            remaining = limit - len(output)
            chunk = os.read(stream.fileno(), min(_READ_CHUNK_BYTES, remaining + 1))
            if not chunk:
                events.put(("done", (output_index, output)))
                return
            if len(chunk) > remaining:
                events.put(("overflow", None))
                return
            output.extend(chunk)
    except OSError as error:
        if not stopping.is_set():
            events.put(("error", error))


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _join_readers(readers: Sequence[threading.Thread], deadline: float) -> None:
    for reader in readers:
        reader.join(timeout=_remaining(deadline))


def _cleanup(
    process: subprocess.Popen[bytes],
    terminate_tree: Callable[[], None],
    streams: Sequence[BinaryIO],
    readers: Sequence[threading.Thread],
    stopping: threading.Event,
) -> None:
    deadline = time.monotonic() + _CLEANUP_SECONDS
    stopping.set()
    try:
        terminate_tree()
    except OSError:
        pass
    try:
        process.wait(timeout=_remaining(deadline))
    except subprocess.TimeoutExpired:
        pass
    for stream in streams:
        try:
            stream.close()
        except OSError:
            pass
    _join_readers(readers, deadline)


def _posix_process(
    argv: Sequence[str], payload: bytes
) -> tuple[subprocess.Popen[bytes], BinaryIO, Callable[[], None]]:
    stdin = tempfile.TemporaryFile()
    stdin.write(payload)
    stdin.seek(0)
    process = subprocess.Popen(  # noqa: S603 - argv is intentionally shell-free.
        list(argv),
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    def terminate_tree() -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    return process, stdin, terminate_tree


def _windows_process(
    argv: Sequence[str], payload: bytes
) -> tuple[subprocess.Popen[bytes], BinaryIO, Callable[[], None], _WindowsJob]:
    header = json.dumps(list(argv), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stdin = tempfile.TemporaryFile()
    process: subprocess.Popen[bytes] | None = None
    job: _WindowsJob | None = None
    gate_read = -1
    gate_write = -1
    try:
        stdin.write(struct.pack("!I", len(header)))
        stdin.write(header)
        stdin.write(payload)
        stdin.seek(0)
        gate_read, gate_write = os.pipe()
        os.set_inheritable(gate_read, True)
        os.set_inheritable(gate_write, False)
        try:
            import msvcrt

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.lpAttributeList = {
                "handle_list": [msvcrt.get_osfhandle(gate_read)]
            }
            process = subprocess.Popen(  # noqa: S603 - helper argv is shell-free.
                [
                    sys.executable, "-I", "-S", "-c", _WINDOWS_HELPER,
                    str(msvcrt.get_osfhandle(gate_read)),
                ],
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                startupinfo=startupinfo,
            )
        finally:
            os.close(gate_read)
            gate_read = -1
        job = _WindowsJob()
        try:
            job.assign(process)
            os.write(gate_write, b"1")
        finally:
            os.close(gate_write)
            gate_write = -1

        def terminate_tree() -> None:
            job.terminate()

        return process, stdin, terminate_tree, job
    except BaseException:
        if gate_read >= 0:
            os.close(gate_read)
        if gate_write >= 0:
            os.close(gate_write)
        if job is not None:
            job.close()
        if process is not None:
            try:
                process.kill()
                process.wait(timeout=_CLEANUP_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                pass
        stdin.close()
        raise


@dataclass(frozen=True, slots=True)
class BoundedCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def run_bounded_command(
    argv: Sequence[str],
    payload: bytes,
    *,
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int = 64 * 1024,
) -> BoundedCommandResult:
    """Run without a shell while never retaining more than the declared limits."""
    if os.name == "nt":
        process, stdin, terminate_tree, job = _windows_process(argv, payload)
    else:
        process, stdin, terminate_tree = _posix_process(argv, payload)
        job = None
    assert process.stdout is not None and process.stderr is not None
    streams = (process.stdout, process.stderr)
    events: queue.Queue[tuple[str, object]] = queue.Queue()
    stopping = threading.Event()
    readers: list[threading.Thread] = []
    try:
        for stream, output_index, limit, name in (
            (process.stdout, 0, max_stdout_bytes, "bounded-command-stdout"),
            (process.stderr, 1, max_stderr_bytes, "bounded-command-stderr"),
        ):
            reader = threading.Thread(
                target=_reader,
                args=(stream, output_index, limit, events, stopping),
                name=name,
                daemon=True,
            )
            reader.start()
            readers.append(reader)

        deadline = time.monotonic() + timeout_seconds
        outputs: list[bytes | None] = [None, None]
        done = 0
        returncode: int | None = None
        terminated_after_exit = False
        while done < len(readers):
            remaining = _remaining(deadline)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(list(argv), timeout_seconds)
            try:
                event, value = events.get(timeout=min(remaining, 0.05))
            except queue.Empty:
                event = ""
                value = None
            if event == "overflow":
                raise CommandOutputLimitError("provider output limit exceeded")
            if event == "error":
                raise value  # type: ignore[misc]
            if event == "done":
                index, output = value  # type: ignore[misc]
                outputs[index] = bytes(output)
                done += 1

            polled = process.poll()
            if polled is not None:
                returncode = polled
                if not terminated_after_exit:
                    terminate_tree()
                    terminated_after_exit = True

        while returncode is None:
            remaining = _remaining(deadline)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(list(argv), timeout_seconds)
            try:
                returncode = process.wait(timeout=min(remaining, 0.05))
            except subprocess.TimeoutExpired:
                continue
        if not terminated_after_exit:
            terminate_tree()
        _join_readers(readers, time.monotonic() + _CLEANUP_SECONDS)
        return BoundedCommandResult(returncode, outputs[0] or b"", outputs[1] or b"")
    except BaseException:
        _cleanup(process, terminate_tree, streams, readers, stopping)
        raise
    finally:
        stdin.close()
        if job is not None:
            job.close()
