#!/usr/bin/env bash
# Run one trusted workflow while holding the shared production-runtime lock.
set -euo pipefail
set +x
umask 077

PYTHON=
for candidate in /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if [ -x "$candidate" ]; then
    PYTHON=$candidate
    break
  fi
done

if [ -z "$PYTHON" ]; then
  printf 'runtime-exclusive-lock result=lock_failed\n' >&2
  exit 65
fi

SAFE_PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
IFS= read -r -d '' PYTHON_CODE <<'PY' || true
import datetime as dt
import errno
import fcntl
import json
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import time


LOCK_NAME = "runtime-exclusive"
OWNER_NAME = "owner.json"
MAX_METADATA_BYTES = 2048
PUBLICATION_WAIT_SECONDS = 0.25
GROUP_DRAIN_WAIT_SECONDS = 5.0
GROUP_PROBE_TIMEOUT_SECONDS = 2.0
USAGE = "usage: runtime-exclusive-lock.sh OPERATION -- /absolute/command [args...]"
OPERATION = re.compile(r"[a-z][a-z0-9-]{0,63}")
TOKEN = re.compile(r"[0-9a-f]{64}")
EXPECTED_FIELDS = {
    "host",
    "operation",
    "owner_token",
    "pid",
    "process_start_fingerprint",
    "schema_version",
    "started_at",
    "uid",
}
UID = os.getuid()
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY = getattr(os, "O_DIRECTORY", 0)
HANDLED_SIGNALS = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)


class UsageFailure(Exception):
    pass


class LockFailure(Exception):
    pass


class LockDeferred(Exception):
    pass


class ChildStateUncertain(Exception):
    pass


class ReleaseFailure(Exception):
    pass


def fixed_failure(result, code):
    print("runtime-exclusive-lock result={}".format(result), file=sys.stderr)
    raise SystemExit(code)


def canonical(metadata):
    return (
        json.dumps(metadata, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def reject_constant(_value):
    raise ValueError


def parse_metadata(raw):
    if not raw or len(raw) > MAX_METADATA_BYTES:
        raise LockFailure
    try:
        text = raw.decode("utf-8", errors="strict")
        metadata = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError, TypeError):
        raise LockFailure
    if not isinstance(metadata, dict) or set(metadata) != EXPECTED_FIELDS:
        raise LockFailure
    if type(metadata["schema_version"]) is not int or metadata["schema_version"] != 1:
        raise LockFailure
    if type(metadata["uid"]) is not int or metadata["uid"] != UID:
        raise LockFailure
    if (
        type(metadata["pid"]) is not int
        or metadata["pid"] <= 0
        or metadata["pid"] > 2_147_483_647
    ):
        raise LockFailure
    if not isinstance(metadata["owner_token"], str) or TOKEN.fullmatch(
        metadata["owner_token"]
    ) is None:
        raise LockFailure
    if not isinstance(metadata["operation"], str) or OPERATION.fullmatch(
        metadata["operation"]
    ) is None:
        raise LockFailure
    for field, limit in (("host", 255), ("process_start_fingerprint", 512)):
        item = metadata[field]
        if (
            not isinstance(item, str)
            or not item
            or len(item) > limit
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in item)
        ):
            raise LockFailure
    if metadata["host"] != socket.gethostname():
        raise LockFailure
    timestamp = metadata["started_at"]
    if not isinstance(timestamp, str):
        raise LockFailure
    try:
        parsed = dt.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError:
        raise LockFailure
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != timestamp:
        raise LockFailure
    if parsed > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
        raise LockFailure
    if canonical(metadata) != raw:
        raise LockFailure
    return metadata


def process_fingerprint(pid):
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/sys/kernel/random/boot_id", "r", encoding="ascii") as stream:
                boot_id = stream.read(128).strip()
            with open("/proc/{}/stat".format(pid), "r", encoding="ascii") as stream:
                raw = stream.read(8192)
            closing = raw.rfind(")")
            if closing < 0:
                raise ValueError
            fields = raw[closing + 2 :].split()
            start_ticks = fields[19]
            if re.fullmatch(r"[0-9a-fA-F-]{36}", boot_id) is None:
                raise ValueError
            if re.fullmatch(r"[0-9]+", start_ticks) is None:
                raise ValueError
            return "linux:{}:{}".format(boot_id.lower(), start_ticks)
        except (OSError, IndexError, ValueError):
            raise LockFailure
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
                check=True,
                capture_output=True,
                env={"LC_ALL": "C", "LANG": "C", "PATH": "/usr/bin:/bin"},
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            raise LockFailure
        started = completed.stdout.strip()
        if not started or len(started) > 128 or "\n" in started:
            raise LockFailure
        return "darwin:{}".format(started)
    raise LockFailure


def same_identity(left, right):
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def validate_directory(value, mode, device=None):
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != UID
        or stat.S_IMODE(value.st_mode) != mode
        or (device is not None and value.st_dev != device)
    ):
        raise LockFailure


def validate_owner_file(value, device):
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != UID
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_nlink != 1
        or value.st_dev != device
        or value.st_size > MAX_METADATA_BYTES
    ):
        raise LockFailure


def validate_owner(value, device):
    validate_owner_file(value, device)
    if value.st_size <= 0:
        raise LockFailure


def validate_ancestor_directory(value):
    mode = stat.S_IMODE(value.st_mode)
    root_sticky = value.st_uid == 0 and bool(mode & stat.S_ISVTX)
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid not in (0, UID)
        or (mode & 0o022 and not root_sticky)
    ):
        raise LockFailure


def open_secure_directory_path(path):
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        raise UsageFailure
    descriptor = None
    try:
        descriptor = os.open(os.path.sep, os.O_RDONLY | DIRECTORY | NOFOLLOW)
        root_stat = os.fstat(descriptor)
        validate_ancestor_directory(root_stat)
        descriptor_stat = root_stat
        components = path.split(os.path.sep)[1:]
        for index, component in enumerate(components):
            path_stat = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
            if index == len(components) - 1:
                validate_directory(path_stat, 0o700)
            else:
                validate_ancestor_directory(path_stat)
            child = None
            try:
                child = os.open(
                    component,
                    os.O_RDONLY | DIRECTORY | NOFOLLOW,
                    dir_fd=descriptor,
                )
                descriptor_stat = os.fstat(child)
                if index == len(components) - 1:
                    validate_directory(descriptor_stat, 0o700)
                else:
                    validate_ancestor_directory(descriptor_stat)
                if not same_identity(path_stat, descriptor_stat):
                    raise LockFailure
            except (OSError, LockFailure):
                if child is not None:
                    try:
                        os.close(child)
                    except OSError:
                        pass
                raise LockFailure
            os.close(descriptor)
            descriptor = child
        return descriptor, descriptor_stat
    except (OSError, LockFailure):
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise LockFailure


def open_parent(custody):
    locks_path = os.path.join(custody, "locks")
    descriptor, descriptor_stat = open_secure_directory_path(locks_path)
    return descriptor, descriptor_stat, locks_path


def stat_at(descriptor, name):
    try:
        return os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except OSError:
        raise LockFailure


def open_lock_directory(parent, parent_stat):
    path_stat = stat_at(parent, LOCK_NAME)
    validate_directory(path_stat, 0o700, parent_stat.st_dev)
    descriptor = None
    try:
        descriptor = os.open(
            LOCK_NAME, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=parent
        )
        descriptor_stat = os.fstat(descriptor)
        validate_directory(descriptor_stat, 0o700, parent_stat.st_dev)
        if not same_identity(path_stat, descriptor_stat):
            raise LockFailure
    except (OSError, LockFailure):
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise LockFailure
    return descriptor, descriptor_stat


def read_owner(descriptor, owner_stat):
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = os.read(descriptor, MAX_METADATA_BYTES + 1)
        after = os.fstat(descriptor)
    except OSError:
        raise LockFailure
    if not same_identity(owner_stat, after) or after.st_size != len(raw):
        raise LockFailure
    return raw


def owner_lock_is_held(descriptor):
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EAGAIN):
            return True
        raise LockFailure
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    return False


def inspect_existing(parent, parent_stat):
    lock_descriptor = None
    owner_descriptor = None
    try:
        lock_descriptor, lock_stat = open_lock_directory(parent, parent_stat)
        deadline = time.monotonic() + PUBLICATION_WAIT_SECONDS
        while True:
            try:
                owner_path_stat = os.stat(
                    OWNER_NAME, dir_fd=lock_descriptor, follow_symlinks=False
                )
            except FileNotFoundError:
                if time.monotonic() >= deadline:
                    raise LockFailure
                time.sleep(0.01)
                continue
            except OSError:
                raise LockFailure
            break
        validate_owner_file(owner_path_stat, lock_stat.st_dev)
        owner_descriptor = os.open(
            OWNER_NAME, os.O_RDWR | NOFOLLOW, dir_fd=lock_descriptor
        )
        owner_stat = os.fstat(owner_descriptor)
        validate_owner_file(owner_stat, lock_stat.st_dev)
        if not same_identity(owner_path_stat, owner_stat):
            raise LockFailure
        while True:
            current_stat = os.fstat(owner_descriptor)
            current_path_stat = stat_at(lock_descriptor, OWNER_NAME)
            validate_owner_file(current_stat, lock_stat.st_dev)
            validate_owner_file(current_path_stat, lock_stat.st_dev)
            if not same_identity(owner_stat, current_stat) or not same_identity(
                owner_stat, current_path_stat
            ):
                raise LockFailure
            try:
                metadata = parse_metadata(read_owner(owner_descriptor, current_stat))
            except LockFailure:
                if time.monotonic() >= deadline:
                    if owner_lock_is_held(owner_descriptor):
                        raise LockDeferred
                    raise LockFailure
                time.sleep(0.01)
                continue
            break
        if not owner_lock_is_held(owner_descriptor):
            raise LockFailure
        try:
            os.kill(metadata["pid"], 0)
        except (OSError, OverflowError):
            raise LockFailure
        if process_fingerprint(metadata["pid"]) != metadata["process_start_fingerprint"]:
            raise LockFailure
        raise LockDeferred
    except OSError:
        raise LockFailure
    finally:
        for descriptor in (owner_descriptor, lock_descriptor):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def write_all(descriptor, payload):
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise LockFailure
        offset += written


def acquire(parent, parent_stat, locks_path, operation):
    try:
        os.mkdir(LOCK_NAME, 0o700, dir_fd=parent)
    except FileExistsError:
        inspect_existing(parent, parent_stat)
        raise LockFailure
    except OSError:
        raise LockFailure

    lock_descriptor = None
    owner_descriptor = None
    try:
        lock_descriptor, lock_stat = open_lock_directory(parent, parent_stat)
        metadata = {
            "host": socket.gethostname(),
            "operation": operation,
            "owner_token": secrets.token_hex(32),
            "pid": os.getpid(),
            "process_start_fingerprint": process_fingerprint(os.getpid()),
            "schema_version": 1,
            "started_at": dt.datetime.now(dt.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "uid": UID,
        }
        payload = canonical(metadata)
        if len(payload) > MAX_METADATA_BYTES:
            raise LockFailure
        owner_descriptor = os.open(
            OWNER_NAME,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | NOFOLLOW,
            0o600,
            dir_fd=lock_descriptor,
        )
        fcntl.flock(owner_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        write_all(owner_descriptor, payload)
        os.fsync(owner_descriptor)
        owner_stat = os.fstat(owner_descriptor)
        owner_path_stat = stat_at(lock_descriptor, OWNER_NAME)
        validate_owner(owner_stat, lock_stat.st_dev)
        if not same_identity(owner_stat, owner_path_stat):
            raise LockFailure
        if parse_metadata(read_owner(owner_descriptor, owner_stat)) != metadata:
            raise LockFailure
        os.fsync(lock_descriptor)
        os.fsync(parent)
        return {
            "parent": parent,
            "parent_stat": parent_stat,
            "locks_path": locks_path,
            "lock": lock_descriptor,
            "lock_stat": lock_stat,
            "owner": owner_descriptor,
            "owner_stat": owner_stat,
            "metadata": metadata,
            "payload": payload,
        }
    except (OSError, LockFailure):
        for descriptor in (owner_descriptor, lock_descriptor):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        raise LockFailure


def current_parent_matches(state):
    path_descriptor = None
    try:
        path_descriptor, path_stat = open_secure_directory_path(state["locks_path"])
        descriptor_stat = os.fstat(state["parent"])
        validate_directory(descriptor_stat, 0o700)
        if not same_identity(path_stat, state["parent_stat"]) or not same_identity(
            descriptor_stat, state["parent_stat"]
        ):
            raise ReleaseFailure
    except (OSError, UsageFailure, LockFailure, ReleaseFailure):
        raise ReleaseFailure
    finally:
        if path_descriptor is not None:
            try:
                os.close(path_descriptor)
            except OSError:
                pass


def release(state):
    try:
        current_parent_matches(state)
        lock_path_stat = os.stat(
            LOCK_NAME, dir_fd=state["parent"], follow_symlinks=False
        )
        lock_descriptor_stat = os.fstat(state["lock"])
        validate_directory(lock_path_stat, 0o700, state["parent_stat"].st_dev)
        validate_directory(lock_descriptor_stat, 0o700, state["parent_stat"].st_dev)
        if not same_identity(lock_path_stat, state["lock_stat"]) or not same_identity(
            lock_descriptor_stat, state["lock_stat"]
        ):
            raise ReleaseFailure
        if sorted(os.listdir(state["lock"])) != [OWNER_NAME]:
            raise ReleaseFailure
        owner_path_stat = os.stat(
            OWNER_NAME, dir_fd=state["lock"], follow_symlinks=False
        )
        owner_descriptor_stat = os.fstat(state["owner"])
        validate_owner(owner_path_stat, state["lock_stat"].st_dev)
        validate_owner(owner_descriptor_stat, state["lock_stat"].st_dev)
        if not same_identity(owner_path_stat, state["owner_stat"]) or not same_identity(
            owner_descriptor_stat, state["owner_stat"]
        ):
            raise ReleaseFailure
        try:
            raw = read_owner(state["owner"], state["owner_stat"])
            metadata = parse_metadata(raw)
        except LockFailure:
            raise ReleaseFailure
        if raw != state["payload"] or metadata != state["metadata"]:
            raise ReleaseFailure
        os.unlink(OWNER_NAME, dir_fd=state["lock"])
        os.fsync(state["lock"])
        os.close(state["owner"])
        state["owner"] = None
        os.close(state["lock"])
        state["lock"] = None
        os.rmdir(LOCK_NAME, dir_fd=state["parent"])
        os.fsync(state["parent"])
        os.close(state["parent"])
        state["parent"] = None
    except (OSError, LockFailure, ReleaseFailure):
        raise ReleaseFailure


def close_state(state):
    for key in ("owner", "lock", "parent"):
        descriptor = state.get(key)
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
            state[key] = None


def parse_arguments():
    if len(sys.argv) < 4 or sys.argv[2] != "--":
        raise UsageFailure
    operation = sys.argv[1]
    command = sys.argv[3:]
    custody = os.environ.get("MNEMO_CUSTODY_DIR")
    if OPERATION.fullmatch(operation) is None or not command or not custody:
        raise UsageFailure
    if (
        not os.path.isabs(command[0])
        or os.path.normpath(command[0]) != command[0]
        or not os.path.isfile(command[0])
        or not os.access(command[0], os.X_OK)
    ):
        raise UsageFailure
    if not os.path.isabs(custody) or os.path.normpath(custody) != custody:
        raise UsageFailure
    return operation, command, custody


def install_signal_handlers():
    child_holder = [None]
    received_signal = [None]

    def forward(signum, _frame):
        if received_signal[0] is None:
            received_signal[0] = signum
        child = child_holder[0]
        if child is not None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass
            except OSError:
                raise ChildStateUncertain

    previous = {}
    for signum in HANDLED_SIGNALS:
        previous[signum] = signal.signal(signum, forward)
    return child_holder, received_signal, forward, previous


def restore_signal_handlers(previous):
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def process_group_snapshot(group_id):
    try:
        completed = subprocess.run(
            ["/bin/ps", "-axo", "pid=,pgid=,stat="],
            check=False,
            capture_output=True,
            env={"LANG": "C", "LC_ALL": "C"},
            text=True,
            timeout=GROUP_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        raise ChildStateUncertain
    if completed.returncode != 0:
        raise ChildStateUncertain
    members = {}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ChildStateUncertain
        try:
            pid, pgid = (int(field) for field in fields[:2])
        except ValueError:
            raise ChildStateUncertain
        if pgid == group_id:
            members[pid] = fields[2]
    return members


def process_group_exists(group_id):
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except OSError:
        raise ChildStateUncertain
    return True


def run_child(command, child_holder, received_signal, forward):
    try:
        child = subprocess.Popen(
            command,
            env=dict(os.environ),
            start_new_session=True,
        )
    except OSError:
        raise LockFailure
    child_holder[0] = child
    try:
        if received_signal[0] is not None:
            forward(received_signal[0], None)
        while True:
            members = process_group_snapshot(child.pid)
            leader_state = members.get(child.pid)
            if leader_state is None:
                raise ChildStateUncertain
            if leader_state.startswith("Z"):
                break
            time.sleep(0.05)
        drain_deadline = time.monotonic() + GROUP_DRAIN_WAIT_SECONDS
        while True:
            members = process_group_snapshot(child.pid)
            if any(pid != child.pid for pid in members):
                if time.monotonic() >= drain_deadline:
                    raise ChildStateUncertain
                time.sleep(0.05)
                continue
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
            try:
                members = process_group_snapshot(child.pid)
                retry_drain = any(pid != child.pid for pid in members)
                if not members.get(child.pid, "").startswith("Z"):
                    raise ChildStateUncertain
                if not retry_drain:
                    child_holder[0] = None
                    return_code = child.wait()
                    if process_group_exists(child.pid):
                        raise ChildStateUncertain
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            if not retry_drain:
                break
            if time.monotonic() >= drain_deadline:
                raise ChildStateUncertain
    except OSError:
        raise ChildStateUncertain
    return return_code, received_signal[0]


def terminate_with_signal(signum):
    if signum not in (signal.SIGKILL, signal.SIGSTOP):
        signal.signal(signum, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signum})
    os.kill(os.getpid(), signum)
    raise SystemExit(128 + signum)


def main():
    state = None
    previous_handlers = {}
    previous_mask = None
    received_signal = [None]
    try:
        operation, command, custody = parse_arguments()
        if not NOFOLLOW or not DIRECTORY:
            raise LockFailure
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, HANDLED_SIGNALS)
        child_holder, received_signal, forward, previous_handlers = (
            install_signal_handlers()
        )
        parent, parent_stat, locks_path = open_parent(custody)
        try:
            state = acquire(parent, parent_stat, locks_path, operation)
        except (LockFailure, LockDeferred):
            os.close(parent)
            raise
        runtime_mask = set(previous_mask).difference(HANDLED_SIGNALS)
        signal.pthread_sigmask(signal.SIG_SETMASK, runtime_mask)
        if received_signal[0] is None:
            return_code, _ = run_child(
                command, child_holder, received_signal, forward
            )
        else:
            return_code = 0
        try:
            release(state)
        except ReleaseFailure:
            close_state(state)
            fixed_failure("release_failed", 74)
        state = None
        if received_signal[0] is not None:
            terminate_with_signal(received_signal[0])
        if return_code < 0:
            terminate_with_signal(-return_code)
        raise SystemExit(return_code)
    except UsageFailure:
        print(USAGE, file=sys.stderr)
        raise SystemExit(64)
    except LockDeferred:
        fixed_failure("lock_deferred", 75)
    except ChildStateUncertain:
        if state is not None:
            close_state(state)
            state = None
        fixed_failure("lock_failed", 65)
    except (LockFailure, OSError):
        if state is not None:
            try:
                release(state)
            except ReleaseFailure:
                close_state(state)
                fixed_failure("release_failed", 74)
        fixed_failure("lock_failed", 65)
    finally:
        if previous_handlers:
            restore_signal_handlers(previous_handlers)
        if previous_mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


main()
PY
exec env LC_ALL=C LANG=C PATH="$SAFE_PATH" "$PYTHON" -I -c "$PYTHON_CODE" "$@"
