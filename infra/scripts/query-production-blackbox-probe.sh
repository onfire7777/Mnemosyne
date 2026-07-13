#!/usr/bin/env bash
# Query the fixed production MCP TLS blackbox metric through the internal Caddy container.
set -eu
set +x

SAFE_PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin
PATH=$SAFE_PATH
export PATH

failure() {
  printf 'production-blackbox-probe result=failure\n'
}

if [ ! -f /usr/bin/python3 ] || [ ! -x /usr/bin/python3 ]; then
  failure
  exit 1
fi

PYTHON_ENV=(/usr/bin/env -i LC_ALL=C PATH="$SAFE_PATH" TMPDIR=/tmp)
if [ "${MCP_CLIENT_BLACKBOX_PROBE_DOCKER_BIN+x}" = x ]; then
  PYTHON_ENV+=(
    "MCP_CLIENT_BLACKBOX_PROBE_DOCKER_BIN=$MCP_CLIENT_BLACKBOX_PROBE_DOCKER_BIN"
  )
fi

exec "${PYTHON_ENV[@]}" /usr/bin/python3 - "$@" <<'PY'
from __future__ import annotations

import json
import math
import os
import pwd
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Sequence


FAILURE = "production-blackbox-probe result=failure\n"
SUCCESS = "production-blackbox-probe result=success\n"
SAFE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
QUERY_URL = (
    "http://victoriametrics:8428/api/v1/query?query="
    "probe_success%7Bjob%3D%22blackbox-tls%22%2Cinstance%3D%22"
    "https%3A%2F%2Fmcp.mnemo.local%22%7D"
)
MAX_RESPONSE_BYTES = 64 * 1024


def finish(code: int) -> None:
    sys.stdout.write(SUCCESS if code == 0 else FAILURE)
    raise SystemExit(code)


def trusted_executable(path: str) -> bool:
    if not path.startswith("/") or "\n" in path or "\r" in path:
        return False
    try:
        metadata = os.stat(path)
    except OSError:
        return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid in {0, os.getuid()}
        and metadata.st_mode & 0o022 == 0
        and os.access(path, os.X_OK)
    )


def docker_binary() -> str:
    override = os.environ.get("MCP_CLIENT_BLACKBOX_PROBE_DOCKER_BIN")
    if override is not None:
        if trusted_executable(override):
            return override
        raise RuntimeError("invalid Docker executable")

    for directory in SAFE_PATH.split(":"):
        candidate = os.path.join(directory, "docker")
        if trusted_executable(candidate):
            return candidate
    raise RuntimeError("Docker executable unavailable")


def terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except OSError:
                pass
    try:
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_bounded(
    executable: str,
    arguments: Sequence[str],
    child_environment: dict[str, str],
    *,
    timeout_seconds: float,
    stdout_limit: int | None,
) -> tuple[int, bytes] | None:
    process = subprocess.Popen(
        [executable, *arguments],
        env=child_environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL if stdout_limit is None else subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    if stdout_limit is None:
        try:
            return process.wait(timeout=timeout_seconds), b""
        except subprocess.TimeoutExpired:
            terminate(process)
            return None

    assert process.stdout is not None
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    selector = selectors.DefaultSelector()
    selector.register(descriptor, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    output = bytearray()
    eof = False
    try:
        while not eof:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate(process)
                return None
            events = selector.select(min(remaining, 0.25))
            if not events and process.poll() is None:
                continue
            while True:
                read_size = min(64 * 1024, stdout_limit + 1 - len(output))
                if read_size <= 0:
                    terminate(process)
                    return None
                try:
                    chunk = os.read(descriptor, read_size)
                except BlockingIOError:
                    break
                if not chunk:
                    eof = True
                    break
                output.extend(chunk)
                if len(output) > stdout_limit:
                    terminate(process)
                    return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            terminate(process)
            return None
        try:
            return process.wait(timeout=remaining), bytes(output)
        except subprocess.TimeoutExpired:
            terminate(process)
            return None
    finally:
        selector.close()
        process.stdout.close()


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def valid_response(body: bytes, start_epoch: int, now: float) -> bool:
    def reject_constant(_value: str) -> object:
        raise ValueError("non-finite JSON number")

    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
        if type(payload) is not dict or set(payload) != {"status", "data"}:
            return False
        if payload["status"] != "success":
            return False
        data = payload["data"]
        if type(data) is not dict or set(data) != {"resultType", "result"}:
            return False
        if data["resultType"] != "vector":
            return False
        result = data["result"]
        if type(result) is not list or len(result) != 1:
            return False
        series = result[0]
        if type(series) is not dict or set(series) != {"metric", "value"}:
            return False
        metric = series["metric"]
        expected_metric = {
            "__name__": "probe_success",
            "job": "blackbox-tls",
            "instance": "https://mcp.mnemo.local",
        }
        if type(metric) is not dict or metric != expected_metric:
            return False
        value = series["value"]
        if type(value) is not list or len(value) != 2 or value[1] != "1":
            return False
        if type(value[1]) is not str or type(value[0]) not in {int, float}:
            return False
        sample_epoch = float(value[0])
        return (
            math.isfinite(sample_epoch)
            and start_epoch < sample_epoch <= now
            and now - sample_epoch <= 120
        )
    except (KeyError, TypeError, UnicodeDecodeError, ValueError):
        return False


def main(arguments: list[str]) -> int:
    if (
        len(arguments) != 1
        or len(arguments[0]) > 19
        or re.fullmatch(r"[0-9]+", arguments[0]) is None
    ):
        return 64
    try:
        start_epoch = int(arguments[0])
        executable = docker_binary()
        child_environment = {
            "HOME": pwd.getpwuid(os.getuid()).pw_dir,
            "LC_ALL": "C",
            "PATH": SAFE_PATH,
            "TMPDIR": "/tmp",
        }
        discovery = run_bounded(
            executable,
            [
                "--context",
                "colima",
                "ps",
                "--filter",
                "status=running",
                "--filter",
                "label=com.docker.compose.project=infra",
                "--filter",
                "label=com.docker.compose.service=caddy",
                "--format",
                "{{.ID}}",
            ],
            child_environment,
            timeout_seconds=5,
            stdout_limit=4096,
        )
        if discovery is None or discovery[0] != 0:
            return 1
        try:
            identifiers = discovery[1].decode("ascii").splitlines()
        except UnicodeDecodeError:
            return 1
        if len(identifiers) != 1 or re.fullmatch(r"[0-9a-f]{12,64}", identifiers[0]) is None:
            return 1
        container_id = identifiers[0]

        capability = run_bounded(
            executable,
            [
                "--context",
                "colima",
                "exec",
                container_id,
                "/bin/busybox",
                "wget",
                "--help",
            ],
            child_environment,
            timeout_seconds=5,
            stdout_limit=None,
        )
        if capability is None or capability[0] != 0:
            return 1

        query = run_bounded(
            executable,
            [
                "--context",
                "colima",
                "exec",
                container_id,
                "/bin/busybox",
                "wget",
                "-q",
                "-O",
                "-",
                "-T",
                "5",
                "-t",
                "2",
                QUERY_URL,
            ],
            child_environment,
            timeout_seconds=15,
            stdout_limit=MAX_RESPONSE_BYTES,
        )
        if query is None or query[0] != 0:
            return 1
        return 0 if valid_response(query[1], start_epoch, time.time()) else 1
    except (OSError, OverflowError, RuntimeError, subprocess.SubprocessError):
        return 1


try:
    exit_code = main(sys.argv[1:])
except Exception:
    exit_code = 1
finish(exit_code)
PY
