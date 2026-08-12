"""Bounded subprocess capture for installed JSON provider commands."""

from __future__ import annotations

import os
import selectors
import subprocess
import tempfile
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
        with (
            tempfile.TemporaryFile() as stdin,
            tempfile.TemporaryFile() as stdout,
            tempfile.TemporaryFile() as stderr,
        ):
            stdin.write(payload)
            stdin.seek(0)
            process = subprocess.Popen(  # noqa: S603 - argv is intentionally shell-free.
                list(argv), stdin=stdin, stdout=stdout, stderr=stderr
            )
            try:
                returncode = process.wait(timeout=timeout_seconds)
            except BaseException:
                process.kill()
                process.wait()
                raise
            stdout_size = stdout.seek(0, os.SEEK_END)
            stderr_size = stderr.seek(0, os.SEEK_END)
            if stdout_size > max_stdout_bytes or stderr_size > max_stderr_bytes:
                raise CommandOutputLimitError("provider output limit exceeded")
            stdout.seek(0)
            stderr.seek(0)
            return BoundedCommandResult(returncode, stdout.read(), stderr.read())

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
