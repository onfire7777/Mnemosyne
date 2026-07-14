from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time

import pytest


HELPER = (
    Path(__file__).resolve().parents[1]
    / "infra"
    / "scripts"
    / "runtime-exclusive-lock.sh"
)
LOCK_NAME = "runtime-exclusive"
OWNER_NAME = "owner.json"
USAGE = "usage: runtime-exclusive-lock.sh OPERATION -- /absolute/command [args...]\n"


def _custody(tmp_path: Path, *, mode: int = 0o700) -> tuple[Path, Path]:
    custody_dir = tmp_path / "custody"
    locks_dir = custody_dir / "locks"
    locks_dir.mkdir(parents=True, mode=mode)
    locks_dir.chmod(mode)
    return custody_dir, locks_dir


def _environment(custody_dir: Path | None) -> dict[str, str]:
    environment = dict(os.environ)
    if custody_dir is None:
        environment.pop("MNEMO_CUSTODY_DIR", None)
    else:
        environment["MNEMO_CUSTODY_DIR"] = str(custody_dir)
    return environment


def _run(
    custody_dir: Path | None,
    *command: str,
    operation: str = "test-operation",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HELPER), operation, "--", *command],
        check=False,
        capture_output=True,
        env=_environment(custody_dir),
        text=True,
    )


def _assert_fixed_failure(
    completed: subprocess.CompletedProcess[str],
    *,
    code: int,
    result: str,
    custody_dir: Path,
) -> None:
    assert completed.returncode == code
    assert completed.stdout == ""
    assert completed.stderr == f"runtime-exclusive-lock result={result}\n"
    assert str(custody_dir) not in completed.stderr


def _wait_for(path: Path, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path.name}")


def _start_owner(
    custody_dir: Path,
    tmp_path: Path,
    *,
    operation: str = "held-operation",
    exit_code: int = 0,
) -> tuple[subprocess.Popen[str], Path, Path]:
    ready = tmp_path / f"ready-{time.monotonic_ns()}"
    release = tmp_path / f"release-{time.monotonic_ns()}"
    child = (
        "import os, pathlib, sys, time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
        "release = pathlib.Path(sys.argv[2]); "
        "\nwhile not release.exists(): time.sleep(0.01)"
        "\nraise SystemExit(int(sys.argv[3]))"
    )
    process = subprocess.Popen(
        [
            str(HELPER),
            operation,
            "--",
            sys.executable,
            "-c",
            child,
            str(ready),
            str(release),
            str(exit_code),
        ],
        env=_environment(custody_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process, ready, release


def _spawn_owner(
    custody_dir: Path,
    tmp_path: Path,
    *,
    operation: str = "held-operation",
    exit_code: int = 0,
) -> tuple[subprocess.Popen[str], Path, Path]:
    process, ready, release = _start_owner(
        custody_dir,
        tmp_path,
        operation=operation,
        exit_code=exit_code,
    )
    _wait_for(ready)
    _wait_for(custody_dir / "locks" / LOCK_NAME / OWNER_NAME)
    return process, ready, release


def _finish_owner(process: subprocess.Popen[str], release: Path) -> tuple[str, str]:
    release.touch()
    return process.communicate(timeout=5)


def _process_fingerprint(pid: int) -> str:
    if sys.platform.startswith("linux"):
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        raw = Path(f"/proc/{pid}/stat").read_text()
        start_ticks = raw[raw.rfind(")") + 2 :].split()[19]
        return f"linux:{boot_id}:{start_ticks}"
    if sys.platform == "darwin":
        completed = subprocess.run(
            ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
            check=True,
            capture_output=True,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            text=True,
        )
        return f"darwin:{completed.stdout.strip()}"
    raise AssertionError(f"unsupported test platform: {sys.platform}")


def _valid_metadata(*, pid: int | None = None) -> dict[str, object]:
    owner_pid = os.getpid() if pid is None else pid
    return {
        "host": socket.gethostname(),
        "operation": "foreign-operation",
        "owner_token": "a" * 64,
        "pid": owner_pid,
        "process_start_fingerprint": _process_fingerprint(os.getpid()),
        "schema_version": 1,
        "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "uid": os.getuid(),
    }


def _canonical(metadata: dict[str, object]) -> bytes:
    return (
        json.dumps(metadata, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _foreign_lock(locks_dir: Path, raw: bytes) -> tuple[Path, Path]:
    lock_dir = locks_dir / LOCK_NAME
    lock_dir.mkdir(mode=0o700)
    lock_dir.chmod(0o700)
    owner = lock_dir / OWNER_NAME
    owner.write_bytes(raw)
    owner.chmod(0o600)
    return lock_dir, owner


def test_successful_child_releases_runtime_lock(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)

    completed = subprocess.run(
        [
            str(HELPER),
            "test-success",
            "--",
            sys.executable,
            "-c",
            "print('child-ran')",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "MNEMO_CUSTODY_DIR": str(custody_dir)},
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "child-ran\n"
    assert not (locks_dir / "runtime-exclusive").exists()


def test_coordinator_imports_are_isolated_before_lock_acquisition(
    tmp_path: Path,
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    sentinel = tmp_path / "shadow-import-ran"
    (shadow_dir / "secrets.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).touch()\n"
        "raise RuntimeError('shadow import executed')\n"
    )
    environment = _environment(custody_dir)
    environment["PYTHONPATH"] = str(shadow_dir)

    completed = subprocess.run(
        [
            str(HELPER),
            "isolated-imports",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(0)",
        ],
        check=False,
        capture_output=True,
        cwd=shadow_dir,
        env=environment,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""
    assert not sentinel.exists()
    assert not (locks_dir / LOCK_NAME).exists()


def test_child_receives_callers_standard_input(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    completed = subprocess.run(
        [
            str(HELPER),
            "stdin-passthrough",
            "--",
            sys.executable,
            "-c",
            "import sys; sys.stdout.write(sys.stdin.read())",
        ],
        check=False,
        capture_output=True,
        env=_environment(custody_dir),
        input="trusted-input\n",
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "trusted-input\n"
    assert completed.stderr == ""
    assert not (locks_dir / LOCK_NAME).exists()


def test_owner_metadata_is_private_canonical_and_locked(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, _, release = _spawn_owner(custody_dir, tmp_path)
    owner = locks_dir / LOCK_NAME / OWNER_NAME
    try:
        raw = owner.read_bytes()
        metadata = json.loads(raw)
        owner_stat = owner.stat()
        lock_stat = owner.parent.stat()

        assert raw == _canonical(metadata)
        assert set(metadata) == {
            "host",
            "operation",
            "owner_token",
            "pid",
            "process_start_fingerprint",
            "schema_version",
            "started_at",
            "uid",
        }
        assert metadata["schema_version"] == 1
        assert type(metadata["pid"]) is int
        assert metadata["pid"] == process.pid
        assert type(metadata["uid"]) is int
        assert metadata["uid"] == os.getuid()
        assert metadata["operation"] == "held-operation"
        assert re.fullmatch(r"[0-9a-f]{64}", str(metadata["owner_token"]))
        assert metadata["host"] == socket.gethostname()
        assert metadata["process_start_fingerprint"] == _process_fingerprint(
            process.pid
        )
        assert (
            datetime.strptime(str(metadata["started_at"]), "%Y-%m-%dT%H:%M:%SZ").tzinfo
            is None
        )
        assert owner_stat.st_uid == os.getuid()
        assert owner_stat.st_mode & 0o777 == 0o600
        assert owner_stat.st_nlink == 1
        assert lock_stat.st_uid == os.getuid()
        assert lock_stat.st_mode & 0o777 == 0o700
        assert owner_stat.st_dev == lock_stat.st_dev

        with owner.open("rb") as candidate:
            with pytest.raises(BlockingIOError):
                fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        stdout, stderr = _finish_owner(process, release)
    assert process.returncode == 0
    assert stdout == ""
    assert stderr == ""


def test_owner_lock_precedes_published_canonical_metadata(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    owner = locks_dir / LOCK_NAME / OWNER_NAME
    probe_result = tmp_path / "probe-result"
    probe_code = """
import fcntl
import json
from pathlib import Path
import sys
import time

owner = Path(sys.argv[1])
result = Path(sys.argv[2])
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    try:
        raw = owner.read_bytes()
        metadata = json.loads(raw)
        canonical = (json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\\n").encode()
        if raw != canonical:
            raise ValueError
        with owner.open("rb") as candidate:
            try:
                fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                result.write_text("blocked")
            else:
                result.write_text("acquired")
                time.sleep(0.25)
        raise SystemExit(0)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        time.sleep(0.001)
raise SystemExit(2)
"""
    probe = subprocess.Popen(
        [sys.executable, "-c", probe_code, str(owner), str(probe_result)]
    )
    process, ready, release = _start_owner(custody_dir, tmp_path)
    try:
        _wait_for(probe_result)
        assert probe_result.read_text() == "blocked"
        _wait_for(ready)
    finally:
        release.touch(exist_ok=True)
        stdout, stderr = process.communicate(timeout=5)
        probe.wait(timeout=5)

    assert process.returncode == 0
    assert probe.returncode == 0
    assert stdout == ""
    assert stderr == ""
    assert not (locks_dir / LOCK_NAME).exists()


def test_active_owner_defers_without_running_child(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, _, release = _spawn_owner(custody_dir, tmp_path)
    sentinel = tmp_path / "must-not-run"
    try:
        completed = _run(
            custody_dir,
            sys.executable,
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
            str(sentinel),
        )
        _assert_fixed_failure(
            completed,
            code=75,
            result="lock_deferred",
            custody_dir=custody_dir,
        )
        assert not sentinel.exists()
        assert (locks_dir / LOCK_NAME).is_dir()
    finally:
        _finish_owner(process, release)
    assert process.returncode == 0


@pytest.mark.parametrize("mode", [0o755, 0o770])
def test_unsafe_locks_parent_fails_before_child(tmp_path: Path, mode: int) -> None:
    custody_dir, _ = _custody(tmp_path, mode=mode)
    sentinel = tmp_path / "must-not-run"
    completed = _run(
        custody_dir,
        sys.executable,
        "-c",
        "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
        str(sentinel),
    )
    _assert_fixed_failure(
        completed, code=65, result="lock_failed", custody_dir=custody_dir
    )
    assert not sentinel.exists()


def test_symlinked_locks_parent_fails_before_child(tmp_path: Path) -> None:
    custody_dir = tmp_path / "custody"
    custody_dir.mkdir()
    actual = tmp_path / "actual-locks"
    actual.mkdir(mode=0o700)
    (custody_dir / "locks").symlink_to(actual, target_is_directory=True)
    sentinel = tmp_path / "must-not-run"

    completed = _run(
        custody_dir,
        sys.executable,
        "-c",
        "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
        str(sentinel),
    )

    _assert_fixed_failure(
        completed, code=65, result="lock_failed", custody_dir=custody_dir
    )
    assert not sentinel.exists()


def test_regular_file_in_custody_path_has_fixed_failure_output(tmp_path: Path) -> None:
    regular = tmp_path / "regular"
    regular.write_text("not a directory")
    custody_dir = regular / "custody"

    completed = _run(custody_dir, sys.executable, "-c", "raise SystemExit(0)")

    _assert_fixed_failure(
        completed, code=65, result="lock_failed", custody_dir=custody_dir
    )


def test_symlinked_lock_entry_fails_before_child(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (locks_dir / LOCK_NAME).symlink_to(foreign, target_is_directory=True)
    sentinel = tmp_path / "must-not-run"

    completed = _run(
        custody_dir,
        sys.executable,
        "-c",
        "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
        str(sentinel),
    )

    _assert_fixed_failure(
        completed, code=65, result="lock_failed", custody_dir=custody_dir
    )
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "raw",
    [
        b"{}\n",
        b'{"schema_version":1,"schema_version":1}\n',
        b"\xff\xfe\n",
        b"{" + (b" " * 4096) + b"}\n",
        _canonical({**_valid_metadata(), "extra": "field"}),
        _canonical({**_valid_metadata(), "pid": True}),
    ],
    ids=["missing", "duplicate", "utf8", "oversize", "extra", "bool-pid"],
)
def test_malformed_metadata_fails_closed_without_rewrite(
    tmp_path: Path, raw: bytes
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    lock_dir, owner = _foreign_lock(locks_dir, raw)
    before = owner.stat()
    sentinel = tmp_path / "must-not-run"

    completed = _run(
        custody_dir,
        sys.executable,
        "-c",
        "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
        str(sentinel),
    )

    _assert_fixed_failure(
        completed, code=65, result="lock_failed", custody_dir=custody_dir
    )
    assert not sentinel.exists()
    assert lock_dir.is_dir()
    assert owner.read_bytes() == raw
    assert owner.stat().st_ino == before.st_ino


def test_dead_owner_is_never_stolen(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    metadata = _valid_metadata(pid=2_147_483_647)
    lock_dir, owner = _foreign_lock(locks_dir, _canonical(metadata))
    sentinel = tmp_path / "must-not-run"

    with owner.open("r+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = _run(
            custody_dir,
            sys.executable,
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
            str(sentinel),
        )

    _assert_fixed_failure(
        completed, code=65, result="lock_failed", custody_dir=custody_dir
    )
    assert not sentinel.exists()
    assert lock_dir.is_dir()
    assert owner.read_bytes() == _canonical(metadata)


def test_live_pid_without_held_owner_lock_is_forged(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    raw = _canonical(_valid_metadata())
    lock_dir, owner = _foreign_lock(locks_dir, raw)

    completed = _run(custody_dir, sys.executable, "-c", "raise SystemExit(0)")

    _assert_fixed_failure(
        completed, code=65, result="lock_failed", custody_dir=custody_dir
    )
    assert lock_dir.is_dir()
    assert owner.read_bytes() == raw


def test_pid_reuse_fingerprint_mismatch_is_not_contention(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    metadata = _valid_metadata()
    metadata["process_start_fingerprint"] = (
        f"{metadata['process_start_fingerprint']}-mismatch"
    )
    _, owner = _foreign_lock(locks_dir, _canonical(metadata))
    with owner.open("r+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = _run(custody_dir, sys.executable, "-c", "raise SystemExit(0)")

    _assert_fixed_failure(
        completed, code=65, result="lock_failed", custody_dir=custody_dir
    )


def test_child_exit_and_output_are_preserved_after_cleanup(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    completed = _run(
        custody_dir,
        sys.executable,
        "-c",
        "import sys; print('child-out'); print('child-err', file=sys.stderr); sys.exit(7)",
    )

    assert completed.returncode == 7
    assert completed.stdout == "child-out\n"
    assert completed.stderr == "child-err\n"
    assert not (locks_dir / LOCK_NAME).exists()


def test_child_signal_status_is_preserved_after_cleanup(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)

    completed = _run(
        custody_dir,
        sys.executable,
        "-c",
        "import os,signal; os.kill(os.getpid(), signal.SIGTERM)",
    )

    assert completed.returncode == -signal.SIGTERM
    assert completed.stdout == ""
    assert completed.stderr == ""
    assert not (locks_dir / LOCK_NAME).exists()


def test_lock_is_held_until_same_process_group_descendants_exit(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    sentinel = tmp_path / "grandchild-finished"
    grandchild = (
        "import pathlib,sys,time; time.sleep(0.25); "
        "pathlib.Path(sys.argv[1]).write_text("
        "'lock-held' if pathlib.Path(sys.argv[2]).exists() else 'lock-missing')"
    )
    child = (
        "import subprocess,sys; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2], "
        "sys.argv[3]], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL)"
    )

    completed = _run(
        custody_dir,
        sys.executable,
        "-c",
        child,
        grandchild,
        str(sentinel),
        str(locks_dir / LOCK_NAME / OWNER_NAME),
    )

    assert completed.returncode == 0, completed.stderr
    assert sentinel.read_text() == "lock-held"
    assert not (locks_dir / LOCK_NAME).exists()


def test_owner_token_mutation_causes_release_failure_and_retains_evidence(
    tmp_path: Path,
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, _, release = _spawn_owner(custody_dir, tmp_path)
    owner = locks_dir / LOCK_NAME / OWNER_NAME
    metadata = json.loads(owner.read_bytes())
    metadata["owner_token"] = (
        "0" * 64 if metadata["owner_token"] != "0" * 64 else "1" * 64
    )
    with owner.open("r+b") as stream:
        stream.seek(0)
        stream.write(_canonical(metadata))
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())

    stdout, stderr = _finish_owner(process, release)

    assert process.returncode == 74
    assert stdout == ""
    assert stderr == "runtime-exclusive-lock result=release_failed\n"
    assert owner.exists()
    assert json.loads(owner.read_bytes())["owner_token"] == metadata["owner_token"]


def test_owner_mode_mutation_release_failure_overrides_child_result(
    tmp_path: Path,
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, _, release = _spawn_owner(custody_dir, tmp_path, exit_code=9)
    owner = locks_dir / LOCK_NAME / OWNER_NAME
    owner.chmod(0o640)

    stdout, stderr = _finish_owner(process, release)

    assert process.returncode == 74
    assert stdout == ""
    assert stderr == "runtime-exclusive-lock result=release_failed\n"
    assert owner.exists()
    assert owner.stat().st_mode & 0o777 == 0o640


def test_owner_hardlink_causes_release_failure_and_retains_evidence(
    tmp_path: Path,
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, _, release = _spawn_owner(custody_dir, tmp_path)
    owner = locks_dir / LOCK_NAME / OWNER_NAME
    linked = tmp_path / "linked-owner-evidence"
    os.link(owner, linked)

    stdout, stderr = _finish_owner(process, release)

    assert process.returncode == 74
    assert stdout == ""
    assert stderr == "runtime-exclusive-lock result=release_failed\n"
    assert owner.exists()
    assert linked.exists()
    assert owner.stat().st_ino == linked.stat().st_ino
    assert owner.stat().st_nlink == 2


def test_owner_inode_substitution_causes_release_failure_and_retains_evidence(
    tmp_path: Path,
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, _, release = _spawn_owner(custody_dir, tmp_path)
    owner = locks_dir / LOCK_NAME / OWNER_NAME
    original = tmp_path / "original-owner-evidence"
    raw = owner.read_bytes()
    owner.rename(original)
    owner.write_bytes(raw)
    owner.chmod(0o600)

    stdout, stderr = _finish_owner(process, release)

    assert process.returncode == 74
    assert stdout == ""
    assert stderr == "runtime-exclusive-lock result=release_failed\n"
    assert original.read_bytes() == raw
    assert owner.read_bytes() == raw
    assert original.stat().st_ino != owner.stat().st_ino


def test_locks_parent_substitution_causes_release_failure_and_retains_evidence(
    tmp_path: Path,
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, _, release = _spawn_owner(custody_dir, tmp_path)
    displaced = tmp_path / "displaced-locks"
    locks_dir.rename(displaced)
    locks_dir.mkdir(mode=0o700)

    stdout, stderr = _finish_owner(process, release)

    assert process.returncode == 74
    assert stdout == ""
    assert stderr == "runtime-exclusive-lock result=release_failed\n"
    assert (displaced / LOCK_NAME / OWNER_NAME).exists()
    assert locks_dir.is_dir()


def test_lock_directory_substitution_causes_release_failure_and_retains_evidence(
    tmp_path: Path,
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, _, release = _spawn_owner(custody_dir, tmp_path)
    lock_dir = locks_dir / LOCK_NAME
    displaced = tmp_path / "displaced-runtime-lock"
    lock_dir.rename(displaced)
    lock_dir.mkdir(mode=0o700)

    stdout, stderr = _finish_owner(process, release)

    assert process.returncode == 74
    assert stdout == ""
    assert stderr == "runtime-exclusive-lock result=release_failed\n"
    assert (displaced / OWNER_NAME).exists()
    assert lock_dir.is_dir()


def test_extra_lock_entry_causes_release_failure_without_recursive_cleanup(
    tmp_path: Path,
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, _, release = _spawn_owner(custody_dir, tmp_path)
    extra = locks_dir / LOCK_NAME / "foreign-evidence"
    extra.write_text("preserve")
    extra.chmod(0o600)

    stdout, stderr = _finish_owner(process, release)

    assert process.returncode == 74
    assert stdout == ""
    assert stderr == "runtime-exclusive-lock result=release_failed\n"
    assert extra.read_text() == "preserve"
    assert (locks_dir / LOCK_NAME / OWNER_NAME).exists()


@pytest.mark.parametrize(
    "handled_signal", [signal.SIGHUP, signal.SIGINT, signal.SIGTERM]
)
def test_handled_signal_forwards_cleans_and_preserves_signal_status(
    tmp_path: Path, handled_signal: signal.Signals
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, _, _ = _spawn_owner(custody_dir, tmp_path)

    process.send_signal(handled_signal)
    stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == -handled_signal
    assert stdout == ""
    assert "owner_token" not in stderr
    assert str(custody_dir) not in stderr
    assert not (locks_dir / LOCK_NAME).exists()


def test_sigkill_residue_fails_closed_and_is_not_stolen(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, ready, _ = _spawn_owner(custody_dir, tmp_path)
    child_pid = int(ready.read_text())
    process.kill()
    process.wait(timeout=5)
    try:
        completed = _run(custody_dir, sys.executable, "-c", "raise SystemExit(0)")
        _assert_fixed_failure(
            completed,
            code=65,
            result="lock_failed",
            custody_dir=custody_dir,
        )
        assert (locks_dir / LOCK_NAME / OWNER_NAME).exists()
    finally:
        try:
            os.kill(child_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


@pytest.mark.parametrize("operation", ["", "../bad", "bad\nname", "x" * 65])
def test_invalid_operation_is_usage_error(tmp_path: Path, operation: str) -> None:
    custody_dir, _ = _custody(tmp_path)
    completed = _run(
        custody_dir,
        sys.executable,
        "-c",
        "raise SystemExit(0)",
        operation=operation,
    )
    assert completed.returncode == 64
    assert completed.stdout == ""
    assert completed.stderr == USAGE


def test_missing_custody_and_relative_command_are_usage_errors(tmp_path: Path) -> None:
    missing = _run(None, sys.executable, "-c", "raise SystemExit(0)")
    assert missing.returncode == 64
    assert missing.stdout == ""
    assert missing.stderr == USAGE

    custody_dir, _ = _custody(tmp_path)
    relative = _run(custody_dir, "python3", "-c", "raise SystemExit(0)")
    assert relative.returncode == 64
    assert relative.stdout == ""
    assert relative.stderr == USAGE
