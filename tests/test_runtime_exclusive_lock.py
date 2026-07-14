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
from typing import Any

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
SUBPROCESS_TIMEOUT = 15


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
        timeout=SUBPROCESS_TIMEOUT,
    )


def _coordinator_namespace() -> dict[str, Any]:
    shell_source = HELPER.read_text()
    prefix = "IFS= read -r -d '' PYTHON_CODE <<'PY' || true\n"
    suffix = "\nPY\nexec env "
    _, found_prefix, embedded = shell_source.partition(prefix)
    source, found_suffix, _ = embedded.partition(suffix)
    assert found_prefix and found_suffix and source.endswith("\nmain()")
    namespace: dict[str, Any] = {}
    exec(compile(source.removesuffix("\nmain()"), str(HELPER), "exec"), namespace)
    return namespace


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


def _wait_for_zombie(pid: int, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        completed = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
        if completed.returncode == 0 and completed.stdout.strip().startswith("Z"):
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for group leader exit")


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
        f"deadline = time.monotonic() + {SUBPROCESS_TIMEOUT}; "
        "\nwhile not release.exists() and time.monotonic() < deadline: "
        "time.sleep(0.01)"
        "\nif not release.exists(): raise SystemExit(98)"
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
    try:
        _wait_for(ready)
        _wait_for(custody_dir / "locks" / LOCK_NAME / OWNER_NAME)
    except BaseException:
        release.touch(exist_ok=True)
        try:
            process.communicate(timeout=SUBPROCESS_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=SUBPROCESS_TIMEOUT)
        raise
    return process, ready, release


def _finish_owner(process: subprocess.Popen[str], release: Path) -> tuple[str, str]:
    release.touch()
    try:
        return process.communicate(timeout=SUBPROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=SUBPROCESS_TIMEOUT)
        raise


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
            timeout=SUBPROCESS_TIMEOUT,
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
        timeout=SUBPROCESS_TIMEOUT,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "child-ran\n"
    assert not (locks_dir / "runtime-exclusive").exists()


def test_child_launch_failure_releases_runtime_lock(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    invalid_executable = tmp_path / "invalid-executable"
    invalid_executable.write_text("not an executable image\n")
    invalid_executable.chmod(0o700)

    completed = _run(custody_dir, str(invalid_executable))

    _assert_fixed_failure(
        completed, code=65, result="lock_failed", custody_dir=custody_dir
    )
    assert not (locks_dir / LOCK_NAME).exists()


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
        timeout=SUBPROCESS_TIMEOUT,
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
        timeout=SUBPROCESS_TIMEOUT,
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
                time.sleep(0.05)
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
        stdout, stderr = process.communicate(timeout=SUBPROCESS_TIMEOUT)
        probe.wait(timeout=SUBPROCESS_TIMEOUT)

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


def test_writable_custody_ancestor_fails_before_child(tmp_path: Path) -> None:
    unsafe_ancestor = tmp_path / "unsafe"
    unsafe_ancestor.mkdir(mode=0o777)
    unsafe_ancestor.chmod(0o777)
    custody_dir = unsafe_ancestor / "custody"
    locks_dir = custody_dir / "locks"
    locks_dir.mkdir(parents=True, mode=0o700)
    locks_dir.chmod(0o700)
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


@pytest.mark.parametrize("raw", [b"", b"{"], ids=["empty", "partial-json"])
def test_held_incomplete_owner_publication_is_deferred(
    tmp_path: Path, raw: bytes
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    lock_dir, owner = _foreign_lock(locks_dir, raw)
    before = owner.stat()
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
        completed, code=75, result="lock_deferred", custody_dir=custody_dir
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


def test_group_leader_stays_published_until_post_exit_group_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _coordinator_namespace()
    child_holder = [None]
    received_signal = [None]

    class CompletedChild:
        pid = 4242

        @staticmethod
        def wait() -> int:
            assert child_holder[0] is None
            return 0

    monkeypatch.setattr(
        namespace["subprocess"], "Popen", lambda *_args, **_kwargs: CompletedChild()
    )

    def group_snapshot(group_id: int) -> dict[int, str]:
        assert group_id == CompletedChild.pid
        assert child_holder[0] is not None
        return {CompletedChild.pid: "Z"}

    namespace["process_group_snapshot"] = group_snapshot
    namespace["process_group_exists"] = lambda _group_id: False

    assert namespace["run_child"](
        ["/unused"], child_holder, received_signal, lambda *_args: None
    ) == (0, None)
    assert child_holder[0] is None


def test_process_group_snapshot_uses_fixed_ps_and_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _coordinator_namespace()
    captured: dict[str, object] = {}

    class CompletedProbe:
        returncode = 0
        stdout = " 4242 4242 Z\n 5252 4242 S\n"

    def run(command: list[str], **kwargs: object) -> CompletedProbe:
        captured["command"] = command
        captured.update(kwargs)
        return CompletedProbe()

    monkeypatch.setattr(namespace["subprocess"], "run", run)

    assert namespace["process_group_snapshot"](4242) == {4242: "Z", 5252: "S"}
    assert captured["command"] == ["/bin/ps", "-axo", "pid=,pgid=,stat="]
    assert captured["env"] == {"LANG": "C", "LC_ALL": "C"}


def test_signal_after_leader_exit_is_forwarded_while_group_drains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _coordinator_namespace()
    child_holder = [None]
    received_signal = [None]
    forwarded: list[tuple[int, int]] = []
    group_states = iter(
        [
            {4242: "Z"},
            {4242: "Z", 5252: "S"},
            {4242: "Z"},
            {4242: "Z"},
        ]
    )

    class CompletedChild:
        pid = 4242

        @staticmethod
        def wait() -> int:
            assert child_holder[0] is None
            return 0

    monkeypatch.setattr(
        namespace["subprocess"], "Popen", lambda *_args, **_kwargs: CompletedChild()
    )

    def forward(signum: int, _frame: object) -> None:
        if received_signal[0] is None:
            received_signal[0] = signum
        child = child_holder[0]
        if child is not None:
            forwarded.append((child.pid, signum))

    snapshot_calls = 0

    def group_snapshot(_group_id: int) -> dict[int, str]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 2:
            forward(signal.SIGTERM, None)
        return next(group_states)

    namespace["process_group_snapshot"] = group_snapshot
    namespace["process_group_exists"] = lambda _group_id: False

    assert namespace["run_child"](
        ["/unused"], child_holder, received_signal, forward
    ) == (0, signal.SIGTERM)
    assert forwarded == [(CompletedChild.pid, signal.SIGTERM)]


def test_post_exit_group_drain_is_bounded_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _coordinator_namespace()
    uncertain = namespace["ChildStateUncertain"]
    child_holder = [None]
    received_signal = [None]
    group_states = iter([{4242: "Z"}, {4242: "Z", 5252: "S"}])

    class CompletedChild:
        pid = 4242

        @staticmethod
        def wait() -> int:
            return 0

    monkeypatch.setattr(
        namespace["subprocess"], "Popen", lambda *_args, **_kwargs: CompletedChild()
    )
    namespace["GROUP_DRAIN_WAIT_SECONDS"] = 0
    namespace["process_group_snapshot"] = lambda _group_id: next(group_states)

    with pytest.raises(uncertain):
        namespace["run_child"](
            ["/unused"], child_holder, received_signal, lambda *_args: None
        )
    assert child_holder[0] is not None


def test_post_reap_probe_rejects_a_residual_group_missed_by_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _coordinator_namespace()
    uncertain = namespace["ChildStateUncertain"]
    child_holder = [None]
    received_signal = [None]

    class CompletedChild:
        pid = 4242

        @staticmethod
        def wait() -> int:
            return 0

    monkeypatch.setattr(
        namespace["subprocess"], "Popen", lambda *_args, **_kwargs: CompletedChild()
    )
    namespace["process_group_snapshot"] = lambda _group_id: {4242: "Z"}
    namespace["process_group_exists"] = lambda _group_id: True

    with pytest.raises(uncertain):
        namespace["run_child"](
            ["/unused"], child_holder, received_signal, lambda *_args: None
        )
    assert child_holder[0] is None


def test_signal_forward_permission_failure_is_uncertain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _coordinator_namespace()
    uncertain = namespace["ChildStateUncertain"]
    child_holder, received_signal, forward, previous = namespace[
        "install_signal_handlers"
    ]()

    class RunningChild:
        pid = 4242

    child_holder[0] = RunningChild()

    def deny_signal(_group_id: int, _signum: int) -> None:
        raise PermissionError(1, "denied")

    monkeypatch.setattr(namespace["os"], "killpg", deny_signal)
    try:
        with pytest.raises(uncertain):
            forward(signal.SIGTERM, None)
    finally:
        namespace["restore_signal_handlers"](previous)

    assert received_signal[0] == signal.SIGTERM


def test_indeterminate_post_launch_state_retains_lock_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    namespace = _coordinator_namespace()
    uncertain = namespace.get("ChildStateUncertain")
    assert uncertain is not None
    sentinel = tmp_path / "child-ran"
    monkeypatch.setenv("MNEMO_CUSTODY_DIR", str(custody_dir))
    monkeypatch.setattr(
        namespace["sys"],
        "argv",
        [
            str(HELPER),
            "uncertain-child-state",
            "--",
            sys.executable,
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
            str(sentinel),
        ],
    )

    def fail_after_launch(_group_id: int) -> None:
        _wait_for(sentinel)
        raise uncertain

    namespace["process_group_snapshot"] = fail_after_launch

    with pytest.raises(SystemExit) as stopped:
        namespace["main"]()

    assert stopped.value.code == 65
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "runtime-exclusive-lock result=lock_failed\n"
    assert sentinel.exists()
    owner = locks_dir / LOCK_NAME / OWNER_NAME
    assert owner.is_file()
    with owner.open("rb") as retained:
        fcntl.flock(retained, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_lock_is_held_until_same_process_group_descendants_exit(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    sentinel = tmp_path / "grandchild-finished"
    grandchild = f"""
import fcntl
import os
from pathlib import Path
import sys
import time

expected_parent = int(sys.argv[3])
deadline = time.monotonic() + {SUBPROCESS_TIMEOUT}
while os.getppid() == expected_parent and time.monotonic() < deadline:
    time.sleep(0.01)
if os.getppid() == expected_parent:
    Path(sys.argv[1]).write_text("parent-still-alive")
    raise SystemExit(2)
owner = Path(sys.argv[2])
result = "lock-missing"
if owner.exists():
    with owner.open("rb") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result = "lock-held"
        else:
            result = "lock-released"
Path(sys.argv[1]).write_text(result)
"""
    child = (
        "import os,subprocess,sys; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2], "
        "sys.argv[3], str(os.getpid())], "
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


def test_signal_after_leader_exit_reaches_same_group_descendant(
    tmp_path: Path,
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    leader_pid_file = tmp_path / "leader-pid"
    descendant_ready = tmp_path / "descendant-ready"
    descendant_forwarded = tmp_path / "descendant-forwarded"
    release = tmp_path / "release-descendant"
    descendant = f"""
from pathlib import Path
import signal
import sys
import time

ready = Path(sys.argv[1])
forwarded = Path(sys.argv[2])
release = Path(sys.argv[3])

def stop(_signum, _frame):
    forwarded.touch()
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
ready.touch()
deadline = time.monotonic() + {SUBPROCESS_TIMEOUT}
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
raise SystemExit(98 if not release.exists() else 0)
"""
    leader = (
        "import os,pathlib,subprocess,sys; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
        "subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[3], "
        "sys.argv[4], sys.argv[5]], stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
    )
    process = subprocess.Popen(
        [
            str(HELPER),
            "post-exit-signal",
            "--",
            sys.executable,
            "-c",
            leader,
            str(leader_pid_file),
            descendant,
            str(descendant_ready),
            str(descendant_forwarded),
            str(release),
        ],
        env=_environment(custody_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for(descendant_ready)
        _wait_for_zombie(int(leader_pid_file.read_text()))
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=SUBPROCESS_TIMEOUT)
    except BaseException:
        release.touch(exist_ok=True)
        try:
            process.communicate(timeout=SUBPROCESS_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=SUBPROCESS_TIMEOUT)
        raise

    assert process.returncode == -signal.SIGTERM
    assert stdout == ""
    assert stderr == ""
    assert descendant_forwarded.exists()
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
    stdout, stderr = process.communicate(timeout=SUBPROCESS_TIMEOUT)

    assert process.returncode == -handled_signal
    assert stdout == ""
    assert "owner_token" not in stderr
    assert str(custody_dir) not in stderr
    assert not (locks_dir / LOCK_NAME).exists()


def test_inherited_blocked_signal_is_unblocked_for_lock_lifetime(
    tmp_path: Path,
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    ready = tmp_path / "blocked-ready"
    forwarded = tmp_path / "blocked-forwarded"
    release = tmp_path / "blocked-release"
    child = f"""
import os
from pathlib import Path
import signal
import sys
import time

ready = Path(sys.argv[1])
forwarded = Path(sys.argv[2])
release = Path(sys.argv[3])

def handle(signum, _frame):
    forwarded.write_text(str(signum))
    raise SystemExit(0)

signal.signal(signal.SIGTERM, handle)
ready.write_text(str(os.getpid()))
deadline = time.monotonic() + {SUBPROCESS_TIMEOUT}
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
raise SystemExit(98)
"""
    launcher = (
        "import os,signal,sys; "
        "signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM}); "
        "os.execve(sys.argv[1], sys.argv[1:], os.environ)"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            launcher,
            str(HELPER),
            "blocked-signal",
            "--",
            sys.executable,
            "-c",
            child,
            str(ready),
            str(forwarded),
            str(release),
        ],
        env=_environment(custody_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for(ready)
        _wait_for(locks_dir / LOCK_NAME / OWNER_NAME)
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=SUBPROCESS_TIMEOUT)
    finally:
        cleanup_required = process.poll() is None or not forwarded.exists()
        if cleanup_required:
            release.touch(exist_ok=True)
            try:
                process.communicate(timeout=SUBPROCESS_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=SUBPROCESS_TIMEOUT)

    assert process.returncode == -signal.SIGTERM
    assert stdout == ""
    assert stderr == ""
    assert forwarded.read_text() == str(signal.SIGTERM)
    assert not (locks_dir / LOCK_NAME).exists()


def test_sigkill_residue_fails_closed_and_is_not_stolen(tmp_path: Path) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    process, ready, release = _spawn_owner(custody_dir, tmp_path)
    child_pid = int(ready.read_text())
    child_fingerprint = _process_fingerprint(child_pid)
    process.kill()
    process.wait(timeout=SUBPROCESS_TIMEOUT)
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
        release.touch(exist_ok=True)
        deadline = time.monotonic() + SUBPROCESS_TIMEOUT
        while time.monotonic() < deadline:
            try:
                current_fingerprint = _process_fingerprint(child_pid)
            except (OSError, subprocess.SubprocessError):
                break
            if current_fingerprint != child_fingerprint:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("timed out waiting for held child to exit")
        process.communicate(timeout=SUBPROCESS_TIMEOUT)


@pytest.mark.parametrize("operation", ["", "../bad", "bad\nname", "x" * 65])
def test_invalid_operation_is_usage_error(tmp_path: Path, operation: str) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    sentinel = tmp_path / "must-not-run"
    completed = _run(
        custody_dir,
        sys.executable,
        "-c",
        "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
        str(sentinel),
        operation=operation,
    )
    assert not sentinel.exists()
    assert completed.returncode == 64
    assert completed.stdout == ""
    assert completed.stderr == USAGE
    assert not (locks_dir / LOCK_NAME).exists()


def test_missing_custody_and_relative_command_are_usage_errors(tmp_path: Path) -> None:
    missing_sentinel = tmp_path / "missing-must-not-run"
    child = "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()"
    missing = _run(None, sys.executable, "-c", child, str(missing_sentinel))
    assert not missing_sentinel.exists()
    assert missing.returncode == 64
    assert missing.stdout == ""
    assert missing.stderr == USAGE

    custody_dir, locks_dir = _custody(tmp_path)
    relative_sentinel = tmp_path / "relative-must-not-run"
    relative = _run(custody_dir, "python3", "-c", child, str(relative_sentinel))
    assert not relative_sentinel.exists()
    assert relative.returncode == 64
    assert relative.stdout == ""
    assert relative.stderr == USAGE
    assert not (locks_dir / LOCK_NAME).exists()


@pytest.mark.parametrize(
    "shape",
    ["missing-separator", "misplaced-separator", "missing-command"],
)
def test_malformed_raw_arguments_fail_before_lock_or_child(
    tmp_path: Path, shape: str
) -> None:
    custody_dir, locks_dir = _custody(tmp_path)
    sentinel = tmp_path / "raw-argv-must-not-run"
    child = [
        sys.executable,
        "-c",
        "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
        str(sentinel),
    ]
    arguments = {
        "missing-separator": ["raw-argv", *child],
        "misplaced-separator": ["raw-argv", *child, "--"],
        "missing-command": ["raw-argv", "--"],
    }[shape]

    completed = subprocess.run(
        [str(HELPER), *arguments],
        check=False,
        capture_output=True,
        env=_environment(custody_dir),
        text=True,
        timeout=SUBPROCESS_TIMEOUT,
    )

    assert completed.returncode == 64
    assert completed.stdout == ""
    assert completed.stderr == USAGE
    assert not sentinel.exists()
    assert not (locks_dir / LOCK_NAME).exists()
