"""Bounded subprocess capture for installed JSON provider commands."""

from __future__ import annotations

import os
import selectors
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Sequence


class CommandOutputLimitError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BoundedCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _run_bounded_command_windows(
    argv: Sequence[str],
    payload: bytes,
    *,
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> BoundedCommandResult:
    """Capture Windows pipes concurrently and stop at the configured byte caps."""
    with tempfile.TemporaryFile() as stdin:
        stdin.write(payload)
        stdin.seek(0)
        process = subprocess.Popen(  # noqa: S603 - argv is intentionally shell-free.
            list(argv), stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        assert process.stdout is not None and process.stderr is not None
        stdout = bytearray()
        stderr = bytearray()
        output_limit_exceeded = threading.Event()

        def drain(stream, destination: bytearray, limit: int) -> None:
            while True:
                available = limit - len(destination)
                chunk = stream.read1(min(64 * 1024, available + 1))
                if not chunk:
                    return
                if len(chunk) > available:
                    output_limit_exceeded.set()
                    return
                destination.extend(chunk)

        readers = [
            threading.Thread(target=drain, args=(process.stdout, stdout, max_stdout_bytes)),
            threading.Thread(target=drain, args=(process.stderr, stderr, max_stderr_bytes)),
        ]
        for reader in readers:
            reader.start()

        deadline = time.monotonic() + timeout_seconds
        try:
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(list(argv), timeout_seconds)
                if output_limit_exceeded.wait(min(remaining, 0.05)):
                    raise CommandOutputLimitError("provider output limit exceeded")
            for reader in readers:
                reader.join()
            if output_limit_exceeded.is_set():
                raise CommandOutputLimitError("provider output limit exceeded")
            return BoundedCommandResult(process.returncode, bytes(stdout), bytes(stderr))
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.wait()
            for reader in readers:
                reader.join()
            raise
        finally:
            process.stdout.close()
            process.stderr.close()


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
        return _run_bounded_command_windows(
            argv,
            payload,
            timeout_seconds=timeout_seconds,
            max_stdout_bytes=max_stdout_bytes,
            max_stderr_bytes=max_stderr_bytes,
        )

    with tempfile.TemporaryFile() as stdin:
        stdin.write(payload)
        stdin.seek(0)
        process = subprocess.Popen(  # noqa: S603 - argv is intentionally shell-free.
            list(argv), stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        assert process.stdout is not None and process.stderr is not None
        selector = selectors.DefaultSelector()
        streams = {process.stdout: bytearray(), process.stderr: bytearray()}
        limits = {process.stdout: max_stdout_bytes, process.stderr: max_stderr_bytes}
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout_seconds
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(list(argv), timeout_seconds)
                for key, _ in selector.select(min(remaining, 0.1)):
                    stream = key.fileobj
                    available = limits[stream] - len(streams[stream])
                    chunk = os.read(stream.fileno(), min(64 * 1024, available + 1))
                    if not chunk:
                        selector.unregister(stream)
                        continue
                    if len(chunk) > available:
                        raise CommandOutputLimitError("provider output limit exceeded")
                    streams[stream].extend(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(list(argv), timeout_seconds)
            returncode = process.wait(timeout=remaining)
            return BoundedCommandResult(
                returncode,
                bytes(streams[process.stdout]),
                bytes(streams[process.stderr]),
            )
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            selector.close()
