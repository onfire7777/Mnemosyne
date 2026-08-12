from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="requires a POSIX shell environment")


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "infra" / "scripts" / "eval-window-admission.sh"
MUTATING_OR_ADMISSION_COMMANDS = {
    "brew",
    "colima",
    "docker",
    "memory_pressure",
    "ollama",
    "osascript",
    "pgrep",
    "sleep",
    "sysctl",
}
FORBIDDEN_AFTER_DOWNGRADE = {
    "brew",
    "colima",
    "docker",
    "memory_pressure",
    "ollama",
    "sleep",
    "sysctl",
}


def _write_fake(path: Path, name: str) -> None:
    executable = path / name
    executable.write_text(
        """#!/bin/sh
printf '%s' \"${0##*/}\" >>\"$CALL_LOG\"
for argument in \"$@\"; do
    printf '\\t%s' \"$argument\" >>\"$CALL_LOG\"
done
printf '\\n' >>\"$CALL_LOG\"
case \"${0##*/}\" in
    pgrep) [ \"${FAKE_PGREP_RUNNING:-all}\" != none ] ;;
    osascript) exit \"${FAKE_OSASCRIPT_STATUS:-0}\" ;;
    memory_pressure) printf 'System-wide memory free percentage: 99%%\\n' ;;
    sysctl) printf '{ 0.10 0.10 0.10 }\\n' ;;
    colima) printf 'default running aarch64 6 12GiB\\n' ;;
    *) exit 0 ;;
esac
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)


@pytest.fixture
def command_harness(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in sorted(MUTATING_OR_ADMISSION_COMMANDS):
        _write_fake(fake_bin, name)
    call_log = tmp_path / "calls.tsv"
    call_log.touch()
    environment = {
        "CALL_LOG": str(call_log),
        "FAKE_PGREP_RUNNING": "all",
        "HOME": str(tmp_path),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
    }
    return environment, call_log


def _run(
    environment: dict[str, str], **updates: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        cwd=REPO,
        env={**environment, **updates},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def _calls(path: Path) -> list[list[str]]:
    return [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()]


def test_confirmation_is_required_before_any_mutating_or_admission_command(
    command_harness: tuple[dict[str, str], Path],
) -> None:
    environment, call_log = command_harness

    result = _run(environment)

    assert result.returncode == 64
    assert _calls(call_log) == []
    assert "ADMISSION PENDING" not in result.stdout


@pytest.mark.parametrize("legacy_name", ["MNEMO_EVAL_QUIT", "MNEMO_EVAL_FLOOR"])
def test_legacy_control_knobs_fail_closed_before_mutation(
    command_harness: tuple[dict[str, str], Path], legacy_name: str
) -> None:
    environment, call_log = command_harness

    result = _run(environment, MNEMO_CONFIRM="1", **{legacy_name: "unsafe"})

    assert result.returncode == 64
    assert _calls(call_log) == []
    assert legacy_name in result.stderr


def test_unknown_keep_token_fails_closed_before_mutation(
    command_harness: tuple[dict[str, str], Path],
) -> None:
    environment, call_log = command_harness

    result = _run(environment, MNEMO_CONFIRM="1", MNEMO_EVAL_KEEP="Safari")

    assert result.returncode == 64
    assert _calls(call_log) == []
    assert "MNEMO_EVAL_KEEP" in result.stderr


def test_only_fixed_allowlisted_apps_are_queried_and_quit(
    command_harness: tuple[dict[str, str], Path],
) -> None:
    environment, call_log = command_harness

    result = _run(environment, MNEMO_CONFIRM="1")

    assert result.returncode == 3
    calls = _calls(call_log)
    pgrep_calls = [call for call in calls if call[0] == "pgrep"]
    assert pgrep_calls == [
        ["pgrep", "-fq", "Brave Browser"],
        ["pgrep", "-fq", "Discord"],
    ]
    assert [call for call in calls if call[0] == "osascript"] == [
        [
            "osascript",
            "-e",
            "with timeout of 5 seconds",
            "-e",
            'tell application "Brave Browser" to quit',
            "-e",
            "end timeout",
        ],
        [
            "osascript",
            "-e",
            "with timeout of 5 seconds",
            "-e",
            'tell application "Discord" to quit',
            "-e",
            "end timeout",
        ],
    ]


def test_keep_removes_only_the_named_allowlisted_app(
    command_harness: tuple[dict[str, str], Path],
) -> None:
    environment, call_log = command_harness

    result = _run(
        environment,
        MNEMO_CONFIRM="1",
        MNEMO_EVAL_KEEP="Brave Browser",
    )

    assert result.returncode == 3
    assert [call for call in _calls(call_log) if call[0] == "osascript"] == [
        [
            "osascript",
            "-e",
            "with timeout of 5 seconds",
            "-e",
            'tell application "Discord" to quit',
            "-e",
            "end timeout",
        ]
    ]


def test_quit_failure_stops_without_pending_status(
    command_harness: tuple[dict[str, str], Path],
) -> None:
    environment, call_log = command_harness

    result = _run(
        environment,
        MNEMO_CONFIRM="1",
        FAKE_OSASCRIPT_STATUS="42",
    )

    assert result.returncode == 1
    assert "ADMISSION PENDING" not in result.stdout
    assert len([call for call in _calls(call_log) if call[0] == "osascript"]) == 1


def test_success_is_nonzero_pending_and_never_runs_or_claims_admission(
    command_harness: tuple[dict[str, str], Path],
) -> None:
    environment, call_log = command_harness

    result = _run(environment, MNEMO_CONFIRM="1")

    assert result.returncode == 3
    assert "ADMISSION PENDING" in result.stdout
    assert ".planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md" in result.stdout
    assert "WINDOW OPEN" not in result.stdout + result.stderr
    assert not (FORBIDDEN_AFTER_DOWNGRADE & {call[0] for call in _calls(call_log)})
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "/opt/homebrew/bin/ollama",
        "brew services",
        "colima list",
        "docker ps",
        "memory_pressure",
        "validate-production-mcp-client-tls",
        "WINDOW OPEN",
    ):
        assert forbidden not in source
