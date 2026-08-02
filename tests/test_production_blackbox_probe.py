from __future__ import annotations

import base64
import json
import os
import pwd
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / "infra" / "scripts" / "query-production-blackbox-probe.sh"
CADDY_ID = "a" * 64
SECOND_CADDY_ID = "b" * 64
SUCCESS = "production-blackbox-probe result=success\n"
FAILURE = "production-blackbox-probe result=failure\n"
CANARY = "blackbox-probe-canary-must-not-leak"
SAFE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
QUERY_URL = (
    "http://victoriametrics:8428/api/v1/query?query="
    "timestamp%28probe_success%7Bjob%3D%22blackbox-tls%22%2Cinstance%3D%22"
    "https%3A%2F%2Fmcp.mnemo.local%22%7D%5B2m%5D%29%20if%20%28"
    "last_over_time%28probe_success%7Bjob%3D%22blackbox-tls%22%2Cinstance%3D%22"
    "https%3A%2F%2Fmcp.mnemo.local%22%7D%5B2m%5D%29%20%3D%3D%201%29"
)
PS_CALL = [
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
]
CAPABILITY_CALL = [
    "--context",
    "colima",
    "exec",
    CADDY_ID,
    "/bin/busybox",
    "wget",
    "--help",
]
QUERY_CALL = [
    "--context",
    "colima",
    "exec",
    CADDY_ID,
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
]


def _vector_payload(
    sample_timestamp: int | float,
    *,
    query_timestamp: int | float | None = None,
    metric: dict[str, str] | None = None,
    value: object | None = None,
) -> dict[str, object]:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": metric
                    or {
                        "job": "blackbox-tls",
                        "instance": "https://mcp.mnemo.local",
                    },
                    "value": [
                        sample_timestamp + 5
                        if query_timestamp is None
                        else query_timestamp,
                        str(sample_timestamp) if value is None else value,
                    ],
                }
            ],
        },
    }


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode()


def _write_fake_docker(
    tmp_path: Path,
    response: bytes,
    *,
    caddy_ids: tuple[str, ...] = (CADDY_ID,),
    discovery_output: bytes | None = None,
    capability_exit: int = 0,
    capability_hang: bool = False,
    query_exit: int = 0,
    query_stream_over_cap: bool = False,
    child_output: str = "",
    docker_mode: int = 0o700,
) -> tuple[Path, Path]:
    docker = tmp_path / "docker"
    audit = tmp_path / "docker-audit.jsonl"
    encoded_response = base64.b64encode(response).decode("ascii")
    encoded_discovery = (
        None
        if discovery_output is None
        else base64.b64encode(discovery_output).decode("ascii")
    )
    encoded_over_cap = base64.b64encode(
        CANARY.encode() + (b"x" * (64 * 1024 + 1))
    ).decode("ascii")
    child_pid = tmp_path / "docker-child.pid"
    docker.write_text(
        f"""#!{sys.executable}
import base64
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
environment = dict(os.environ)
environment.pop("__CF_USER_TEXT_ENCODING", None)
audit = Path({str(audit)!r})
with audit.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({{"argv": args, "env": environment}}, sort_keys=True) + "\\n")

ps_call = {PS_CALL!r}
capability_call = {CAPABILITY_CALL!r}
query_call = {QUERY_CALL!r}
if args == ps_call:
    discovery = {encoded_discovery!r}
    if discovery is None:
        ids = {list(caddy_ids)!r}
        if ids:
            print("\\n".join(ids))
    else:
        sys.stdout.buffer.write(base64.b64decode(discovery))
        sys.stdout.buffer.flush()
    raise SystemExit(0)
if args == capability_call:
    if {capability_hang!r}:
        Path({str(child_pid)!r}).write_text(str(os.getpid()), encoding="ascii")
        time.sleep(60)
    if {child_output!r}:
        print({child_output!r}, file=sys.stderr)
    raise SystemExit({capability_exit})
if args == query_call:
    if {query_stream_over_cap!r}:
        Path({str(child_pid)!r}).write_text(str(os.getpid()), encoding="ascii")
        sys.stdout.buffer.write(base64.b64decode({encoded_over_cap!r}))
        sys.stdout.buffer.flush()
        time.sleep(60)
    if {child_output!r}:
        print({child_output!r}, file=sys.stderr)
    sys.stdout.buffer.write(base64.b64decode({encoded_response!r}))
    raise SystemExit({query_exit})
raise SystemExit(97)
""",
        encoding="utf-8",
    )
    docker.chmod(docker_mode)
    return docker, audit


def _run_probe(
    tmp_path: Path,
    args: list[str],
    response: bytes = b"{}",
    *,
    docker_override: Path | str | None = None,
    **docker_options: object,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    assert PROBE.is_file(), f"missing production helper: {PROBE}"
    docker, audit = _write_fake_docker(tmp_path, response, **docker_options)
    env = {
        **os.environ,
        "AWS_SECRET_ACCESS_KEY": CANARY,
        "BLACKBOX_PROBE_HOST": "attacker.invalid",
        "BLACKBOX_PROBE_QUERY": CANARY,
        "BLACKBOX_PROBE_URL": "https://attacker.invalid/steal",
        "HOME": f"/tmp/{CANARY}",
        "LC_ALL": "hostile_LOCALE",
        "MCP_CLIENT_BLACKBOX_PROBE_DOCKER_BIN": str(docker_override or docker),
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
        "TMPDIR": f"/tmp/{CANARY}",
    }
    proc = subprocess.run(
        [str(PROBE), *args],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )
    return proc, audit


def _calls(audit: Path) -> list[dict[str, object]]:
    if not audit.exists():
        return []
    return [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]


def _assert_fake_child_exited(tmp_path: Path) -> None:
    pid = int((tmp_path / "docker-child.pid").read_text(encoding="ascii"))
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    pytest.fail(f"fake Docker child {pid} survived helper exit")


def test_wrapper_pins_os_controlled_python_interpreter() -> None:
    wrapper = PROBE.read_text()

    assert 'exec "${PYTHON_ENV[@]}" /usr/bin/python3 - "$@"' in wrapper
    assert "command -v python3" not in wrapper


def test_wrapper_sanitizes_locale_before_bash_initialization() -> None:
    first_line = PROBE.read_text().splitlines()[0]

    assert first_line == "#!/usr/bin/env -S LC_ALL=C /bin/bash"


@pytest.mark.parametrize(
    "args",
    [
        pytest.param([], id="missing"),
        pytest.param([""], id="empty"),
        pytest.param(["-1"], id="negative"),
        pytest.param(["+1"], id="leading-plus"),
        pytest.param(["0"], id="zero"),
        pytest.param(["0.0"], id="fractional-zero"),
        pytest.param(["1."], id="missing-fraction"),
        pytest.param([".1"], id="missing-integer"),
        pytest.param(["01.0"], id="leading-zero"),
        pytest.param(["1.1234567890"], id="excess-fractional-precision"),
        pytest.param(["1e3"], id="scientific-boundary"),
        pytest.param([" 1"], id="leading-space"),
        pytest.param(["1\n"], id="newline"),
        pytest.param(["9" * 5_000], id="oversized-epoch"),
        pytest.param(["https://attacker.invalid"], id="caller-url"),
        pytest.param(["1", "https://attacker.invalid"], id="extra-url"),
    ],
)
def test_cli_requires_exactly_one_positive_epoch_with_optional_nanoseconds(
    tmp_path: Path,
    args: list[str],
) -> None:
    proc, audit = _run_probe(tmp_path, args)

    assert proc.returncode == 64
    assert proc.stdout == FAILURE
    assert proc.stderr == ""
    assert _calls(audit) == []


@pytest.mark.parametrize(
    ("docker_options", "expected_calls"),
    [
        pytest.param({"caddy_ids": ()}, 1, id="no-caddy"),
        pytest.param(
            {"caddy_ids": (CADDY_ID, SECOND_CADDY_ID)},
            1,
            id="multiple-caddy",
        ),
        pytest.param(
            {"capability_exit": 1, "child_output": CANARY},
            2,
            id="missing-busybox-wget",
        ),
        pytest.param(
            {"query_exit": 1, "child_output": CANARY},
            3,
            id="transport-failure",
        ),
    ],
)
def test_container_cardinality_and_transport_capability_fail_closed(
    tmp_path: Path,
    docker_options: dict[str, object],
    expected_calls: int,
) -> None:
    now = int(time.time())
    proc, audit = _run_probe(
        tmp_path,
        [str(now - 10)],
        _json_bytes(_vector_payload(now - 5)),
        **docker_options,
    )

    assert proc.returncode == 1
    assert proc.stdout == FAILURE
    assert proc.stderr == ""
    assert CANARY not in proc.stdout + proc.stderr
    assert len(_calls(audit)) == expected_calls


@pytest.mark.parametrize(
    "discovery_output",
    [
        pytest.param(b"not-a-container-id\n", id="malformed"),
        pytest.param(CANARY.encode() + b"\n", id="canary"),
        pytest.param(CANARY.encode() + (b"x" * 4_097), id="oversized"),
    ],
)
def test_caddy_discovery_is_bounded_strict_and_nonleaking(
    tmp_path: Path,
    discovery_output: bytes,
) -> None:
    now = int(time.time())
    proc, audit = _run_probe(
        tmp_path,
        [str(now - 10)],
        _json_bytes(_vector_payload(now - 5)),
        discovery_output=discovery_output,
    )

    assert proc.returncode == 1
    assert proc.stdout == FAILURE
    assert proc.stderr == ""
    assert CANARY not in proc.stdout + proc.stderr
    assert len(_calls(audit)) == 1


def test_hanging_capability_check_is_bounded_and_reaped(tmp_path: Path) -> None:
    now = int(time.time())
    started = time.monotonic()
    proc, audit = _run_probe(
        tmp_path,
        [str(now - 10)],
        _json_bytes(_vector_payload(now - 5)),
        capability_hang=True,
    )
    elapsed = time.monotonic() - started

    assert proc.returncode == 1
    assert proc.stdout == FAILURE
    assert proc.stderr == ""
    assert CANARY not in proc.stdout + proc.stderr
    assert elapsed < 10
    assert len(_calls(audit)) == 2
    _assert_fake_child_exited(tmp_path)


def test_query_stream_cap_terminates_and_reaps_child_immediately(
    tmp_path: Path,
) -> None:
    now = int(time.time())
    started = time.monotonic()
    proc, audit = _run_probe(
        tmp_path,
        [str(now - 10)],
        _json_bytes(_vector_payload(now - 5)),
        query_stream_over_cap=True,
    )
    elapsed = time.monotonic() - started

    assert proc.returncode == 1
    assert proc.stdout == FAILURE
    assert proc.stderr == ""
    assert CANARY not in proc.stdout + proc.stderr
    assert elapsed < 5
    assert len(_calls(audit)) == 3
    _assert_fake_child_exited(tmp_path)


@pytest.mark.parametrize(
    ("docker_override", "docker_options"),
    [
        pytest.param(
            "missing",
            {},
            id="missing",
        ),
        pytest.param(
            None,
            {"docker_mode": 0o722},
            id="group-writable",
        ),
    ],
)
def test_missing_or_untrusted_docker_fails_without_leaking(
    tmp_path: Path,
    docker_override: str | None,
    docker_options: dict[str, object],
) -> None:
    now = int(time.time())
    override = (
        tmp_path / f"{CANARY}-missing-docker" if docker_override == "missing" else None
    )
    proc, audit = _run_probe(
        tmp_path,
        [str(now - 10)],
        _json_bytes(_vector_payload(now - 5)),
        docker_override=override,
        **docker_options,
    )

    assert proc.returncode == 1
    assert proc.stdout == FAILURE
    assert proc.stderr == ""
    assert CANARY not in proc.stdout + proc.stderr
    assert _calls(audit) == []


INVALID_RESPONSE_CASES = (
    "empty",
    "malformed",
    "malformed-canary-body",
    "invalid-utf8",
    "trailing-bytes",
    "duplicate-key",
    "nested-duplicate-key",
    "oversized",
    "root-not-object",
    "status-not-string",
    "extra-top-level-field",
    "failure-status",
    "data-not-object",
    "extra-data-field",
    "result-type-not-string",
    "wrong-result-type",
    "result-not-array",
    "empty-vector",
    "multiple-series",
    "series-not-object",
    "extra-series-field",
    "metric-not-object",
    "unexpected-metric-name",
    "extra-label",
    "wrong-job",
    "wrong-instance",
    "value-not-array",
    "wrong-value-shape",
    "timestamp-not-number",
    "boolean-timestamp",
    "nan-timestamp",
    "infinite-timestamp",
    "overflowing-timestamp",
    "numeric-value",
    "wrong-string-value",
    "malformed-scientific-value",
    "oversized-scientific-exponent",
    "nan-value",
    "infinite-value",
    "overflowing-value",
    "sample-equals-start",
    "sample-equals-subsecond-start",
    "sample-before-subsecond-start",
    "query-before-sample",
    "future-query",
    "stale-sample",
    "future-sample",
)


def _invalid_response(case: str) -> tuple[int | float | str, bytes]:
    now = int(time.time())
    start = now - 20
    payload = _vector_payload(now - 5)
    data = payload["data"]
    assert isinstance(data, dict)
    result = data["result"]
    assert isinstance(result, list)
    series = result[0]
    assert isinstance(series, dict)
    metric = series["metric"]
    assert isinstance(metric, dict)

    if case == "empty":
        return start, b""
    if case == "malformed":
        return start, b"{"
    if case == "malformed-canary-body":
        return start, b'{"status":' + CANARY.encode()
    if case == "invalid-utf8":
        return start, b"\xff"
    if case == "trailing-bytes":
        return start, _json_bytes(payload) + CANARY.encode()
    if case == "duplicate-key":
        valid = _json_bytes(payload).decode()
        return start, ('{"status":"success","status":"success",' + valid[1:]).encode()
    if case == "nested-duplicate-key":
        return start, _json_bytes(payload).replace(
            b'"job":"blackbox-tls"',
            b'"job":"blackbox-tls","job":"blackbox-tls"',
            1,
        )
    if case == "oversized":
        return start, CANARY.encode() + (b"x" * 65_537)
    if case == "root-not-object":
        return start, _json_bytes([])
    if case == "status-not-string":
        payload["status"] = 1
    elif case == "extra-top-level-field":
        payload["extra"] = True
    elif case == "failure-status":
        payload["status"] = "error"
    elif case == "data-not-object":
        payload["data"] = []
    elif case == "extra-data-field":
        data["extra"] = True
    elif case == "result-type-not-string":
        data["resultType"] = 1
    elif case == "wrong-result-type":
        data["resultType"] = "matrix"
    elif case == "result-not-array":
        data["result"] = {}
    elif case == "empty-vector":
        data["result"] = []
    elif case == "multiple-series":
        data["result"] = [series, dict(series)]
    elif case == "series-not-object":
        data["result"] = [[]]
    elif case == "extra-series-field":
        series["extra"] = True
    elif case == "metric-not-object":
        series["metric"] = []
    elif case == "unexpected-metric-name":
        metric["__name__"] = "probe_success"
    elif case == "extra-label":
        metric["tenant"] = "primary"
    elif case == "wrong-job":
        metric["job"] = "other"
    elif case == "wrong-instance":
        metric["instance"] = "https://attacker.invalid"
    elif case == "value-not-array":
        series["value"] = {}
    elif case == "wrong-value-shape":
        series["value"] = [now]
    elif case == "timestamp-not-number":
        series["value"] = [str(now), str(now - 5)]
    elif case == "boolean-timestamp":
        series["value"] = [True, str(now - 5)]
    elif case == "nan-timestamp":
        return start, _json_bytes(payload).replace(str(now).encode(), b"NaN", 1)
    elif case == "infinite-timestamp":
        return start, _json_bytes(payload).replace(str(now).encode(), b"Infinity", 1)
    elif case == "overflowing-timestamp":
        return start, _json_bytes(payload).replace(str(now).encode(), b"1e309", 1)
    elif case == "numeric-value":
        series["value"] = [now, now - 5]
    elif case == "wrong-string-value":
        series["value"] = [now, "not-a-timestamp"]
    elif case == "malformed-scientific-value":
        series["value"] = [now, "1e"]
    elif case == "oversized-scientific-exponent":
        series["value"] = [now, "1e+1000"]
    elif case == "nan-value":
        series["value"] = [now, "NaN"]
    elif case == "infinite-value":
        series["value"] = [now, "Infinity"]
    elif case == "overflowing-value":
        series["value"] = [now, "1e309"]
    elif case == "sample-equals-start":
        series["value"] = [now, str(start)]
    elif case == "sample-equals-subsecond-start":
        start = f"{now - 5}.125000000"
        series["value"] = [now, start]
    elif case == "sample-before-subsecond-start":
        return now - 5.125, _json_bytes(
            _vector_payload(now - 5.25, query_timestamp=now)
        )
    elif case == "query-before-sample":
        series["value"] = [now - 10, str(now - 5)]
    elif case == "future-query":
        series["value"] = [now + 3600, str(now - 5)]
    elif case == "stale-sample":
        start = now - 500
        series["value"] = [now, str(now - 300)]
    elif case == "future-sample":
        series["value"] = [now, str(now + 3600)]
    else:  # pragma: no cover - the parametrization is the closed case set
        raise AssertionError(case)
    return start, _json_bytes(payload)


@pytest.mark.parametrize("case", INVALID_RESPONSE_CASES)
def test_response_schema_labels_value_and_freshness_fail_closed(
    tmp_path: Path,
    case: str,
) -> None:
    start, response = _invalid_response(case)

    proc, _ = _run_probe(tmp_path, [str(start)], response)

    assert proc.returncode == 1
    assert proc.stdout == FAILURE
    assert proc.stderr == ""
    assert CANARY not in proc.stdout + proc.stderr


def test_future_start_epoch_fails_closed(tmp_path: Path) -> None:
    now = int(time.time())
    proc, _ = _run_probe(
        tmp_path,
        [str(now + 60)],
        _json_bytes(_vector_payload(now - 5)),
    )

    assert proc.returncode == 1
    assert proc.stdout == FAILURE
    assert proc.stderr == ""
    assert CANARY not in proc.stdout + proc.stderr


def test_exact_query_transport_sanitized_environment_and_fresh_success(
    tmp_path: Path,
) -> None:
    now = int(time.time())
    proc, audit = _run_probe(
        tmp_path,
        [str(now - 10)],
        _json_bytes(_vector_payload(now - 5)),
    )

    assert proc.returncode == 0
    assert proc.stdout == SUCCESS
    assert proc.stderr == ""
    calls = _calls(audit)
    assert [call["argv"] for call in calls] == [PS_CALL, CAPABILITY_CALL, QUERY_CALL]
    expected_environment = {
        "HOME": pwd.getpwuid(os.getuid()).pw_dir,
        "LC_ALL": "C",
        "PATH": SAFE_PATH,
        "TMPDIR": "/tmp",
    }
    assert all(call["env"] == expected_environment for call in calls)
    audit_text = audit.read_text(encoding="utf-8")
    assert CANARY not in audit_text
    assert "attacker.invalid" not in audit_text


def test_scientific_raw_sample_timestamp_is_accepted(tmp_path: Path) -> None:
    now = time.time()
    raw_sample = now - 5
    proc, _ = _run_probe(
        tmp_path,
        [f"{now - 10:.9f}"],
        _json_bytes(
            _vector_payload(
                raw_sample,
                query_timestamp=now,
                value=f"{raw_sample:.9e}",
            )
        ),
    )

    assert proc.returncode == 0
    assert proc.stdout == SUCCESS
    assert proc.stderr == ""


def test_raw_sample_one_nanosecond_after_boundary_is_accepted(tmp_path: Path) -> None:
    now = int(time.time())
    second = now - 5
    proc, _ = _run_probe(
        tmp_path,
        [f"{second}.123456788"],
        _json_bytes(
            _vector_payload(
                second,
                query_timestamp=now,
                value=f"{second}.123456789",
            )
        ),
    )

    assert proc.returncode == 0
    assert proc.stdout == SUCCESS
    assert proc.stderr == ""
