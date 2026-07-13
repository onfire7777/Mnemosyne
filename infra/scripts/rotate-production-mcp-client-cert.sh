#!/usr/bin/env bash
# Stage a replacement production MCP client certificate through a confined issuer.
set -euo pipefail
set +x

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
VALIDATOR=$REPO_ROOT/infra/validate/validate-production-mcp-client-tls.sh
DIAGNOSTIC=$REPO_ROOT/infra/validate/diagnose-production-mcp-client-tls-for-rotation.sh
STEP_IMAGE='smallstep/step-ca:0.28.4@sha256:0f88382ac5af5c6b7bbba0c6e8fcefef52aee6f22ea364df8e02a09ffd0d22f3'

result() {
  printf 'mcp-client-rotation result=%s\n' "$1"
}

preflight_failed() {
  result preflight_failed
  printf 'mcp-client-rotation failed: %s\n' "$1" >&2
  exit 65
}

runtime_unavailable() {
  result runtime_unavailable
  printf 'mcp-client-rotation failed: %s\n' "$1" >&2
  exit 69
}

issuance_failed() {
  result issuance_failed
  printf 'mcp-client-rotation failed: %s\n' "$1" >&2
  exit 70
}

publication_failed() {
  result publication_failed
  printf 'mcp-client-rotation failed: %s\n' "$1" >&2
  exit 74
}

recovery_failed() {
  result recovery_failed
  printf 'mcp-client-rotation failed: %s\n' "$1" >&2
  exit 74
}

classify_remaining() {
  case "$1" in
    '' | -) return 1 ;;
  esac
  case "${1#-}" in
    *[!0-9]*) return 1 ;;
  esac
  if [ "$1" -gt 43200 ]; then
    printf 'healthy\n'
  elif [ "$1" -gt 21600 ]; then
    printf 'renewal_due\n'
  elif [ "$1" -gt 7200 ]; then
    printf 'hard_floor\n'
  elif [ "$1" -ge 0 ]; then
    printf 'emergency\n'
  else
    printf 'expired\n'
  fi
}

if [ "${1:-}" = '--classify-remaining' ]; then
  [ "$#" -eq 2 ] || {
    printf 'usage: %s --classify-remaining SECONDS\n' "$0" >&2
    exit 64
  }
  renewal_state=$(classify_remaining "$2") || {
    printf 'usage: %s --classify-remaining SECONDS\n' "$0" >&2
    exit 64
  }
  printf 'mcp-client-rotation renewal_state=%s\n' "$renewal_state"
  exit 0
fi

FIXTURE_TRANSACTION=0
if [ "${1:-}" = '--test-fixture-transaction' ]; then
  [ "$#" -eq 1 ] || {
    printf 'usage: %s --test-fixture-transaction\n' "$0" >&2
    exit 64
  }
  FIXTURE_TRANSACTION=1
  shift
fi

[ "$#" -eq 0 ] || {
  printf 'usage: %s\n' "$0" >&2
  exit 64
}

OPENSSL=$(command -v openssl) || preflight_failed 'openssl is required'
PYTHON=$(command -v python3) || preflight_failed 'python3 is required'
SECRETS_DIR=${MNEMO_SECRETS_DIR:-/secure/outside/repo}
case "$SECRETS_DIR" in
  /*) ;;
  *) preflight_failed 'external secret root must be an absolute path' ;;
esac
ROOT_CA=$SECRETS_DIR/stepca-acme-root.crt
CERT_BUNDLE=$SECRETS_DIR/mcp-client.crt
PRIVATE_KEY=$SECRETS_DIR/mcp-client.key
PROVISIONER_PASSWORD=$SECRETS_DIR/step-ca-jwk-provisioner-password
COMPOSE_FILE=${MCP_CLIENT_ROTATOR_COMPOSE_FILE:-$REPO_ROOT/infra/docker-compose.prod.yml}
ROTATION_DIR=$SECRETS_DIR/.mcp-client-rotation
STAGE_DIR=${MCP_CLIENT_ROTATOR_STAGE_DIR:-$ROTATION_DIR/stage.$$.new}

transaction_call() {
  "$PYTHON" - \
    "$1" \
    "$SECRETS_DIR" \
    "$ROTATION_DIR" \
    "$CERT_BUNDLE" \
    "$PRIVATE_KEY" \
    "$STAGE_DIR" <<'PY'
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import stat
import sys


class TransactionError(Exception):
    pass


def reject() -> None:
    raise TransactionError


ACTION, SECRETS, ROTATION, CERTIFICATE, PRIVATE_KEY, STAGE = sys.argv[1:]
UID = os.getuid()
CERTIFICATE_NAME = "mcp-client.crt"
PRIVATE_KEY_NAME = "mcp-client.key"
JOURNAL_NAME = "transaction.json"
MARKER_NAME = "fixture-transaction.json"
MAX_JOURNAL_BYTES = 4096
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY = getattr(os, "O_DIRECTORY", 0)
if not NOFOLLOW or not DIRECTORY:
    reject()

JOURNAL_FIELDS = {
    "schema_version",
    "transaction_id",
    "created_at",
    "phase",
    "old_cert_sha256",
    "old_key_sha256",
    "new_cert_sha256",
    "new_key_sha256",
    "blackbox_exporter_was_running",
    "operator_was_running",
}
PHASES = {
    "prepared",
    "certificate_published",
    "pair_published",
    "published_validated",
    "restoring_certificate",
    "restoring_key",
    "old_pair_restored",
}
INTERRUPT_POINTS = (PHASES - {"published_validated"}) | {
    "certificate_renamed",
    "certificate_parent_fsynced",
    "key_renamed",
    "key_parent_fsynced",
    "old_certificate_restored",
    "old_certificate_parent_fsynced",
    "old_key_restored",
    "old_key_parent_fsynced",
}
FSYNC_FAILURES = {"journal-parent", "certificate-parent", "key-parent"}
VALIDATION_FAILURES = {"published", "restored"}


def real_absolute(path: str) -> str:
    absolute = os.path.abspath(path)
    if absolute != path or os.path.realpath(path) != path:
        reject()
    return absolute


def open_directory(path: str, *, exact_mode: int | None = None) -> tuple[int, os.stat_result]:
    path = real_absolute(path)
    before = os.lstat(path)
    if not stat.S_ISDIR(before.st_mode) or stat.S_ISLNK(before.st_mode):
        reject()
    descriptor = os.open(path, os.O_RDONLY | DIRECTORY | NOFOLLOW)
    after = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(after.st_mode)
        or after.st_uid != UID
        or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
    ):
        os.close(descriptor)
        reject()
    mode = stat.S_IMODE(after.st_mode)
    if exact_mode is not None:
        if mode != exact_mode:
            os.close(descriptor)
            reject()
    elif mode & 0o022:
        os.close(descriptor)
        reject()
    return descriptor, after


def stat_entry(directory: int, name: str) -> os.stat_result:
    if "/" in name or name in {"", ".", ".."}:
        reject()
    return os.stat(name, dir_fd=directory, follow_symlinks=False)


def open_regular(
    directory: int,
    name: str,
    *,
    exact_mode: int | None = None,
    writable_public_forbidden: bool = False,
) -> tuple[int, os.stat_result]:
    before = stat_entry(directory, name)
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        reject()
    descriptor = os.open(name, os.O_RDONLY | NOFOLLOW, dir_fd=directory)
    after = os.fstat(descriptor)
    if (
        not stat.S_ISREG(after.st_mode)
        or after.st_uid != UID
        or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
    ):
        os.close(descriptor)
        reject()
    mode = stat.S_IMODE(after.st_mode)
    if exact_mode is not None and mode != exact_mode:
        os.close(descriptor)
        reject()
    if writable_public_forbidden and mode & 0o022:
        os.close(descriptor)
        reject()
    return descriptor, after


def read_limited(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining:
        chunk = os.read(descriptor, min(65536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    value = b"".join(chunks)
    if not value or len(value) > limit:
        reject()
    return value


def digest_entry(
    directory: int,
    name: str,
    *,
    exact_mode: int | None = None,
    public: bool = False,
) -> str:
    descriptor, _ = open_regular(
        directory,
        name,
        exact_mode=exact_mode,
        writable_public_forbidden=public,
    )
    try:
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def strict_json_bytes(value: bytes) -> dict[str, object]:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                reject()
            result[key] = item
        return result

    try:
        parsed = json.loads(value.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        reject()
    if not isinstance(parsed, dict):
        reject()
    return parsed


def load_marker(rotation_fd: int) -> dict[str, object]:
    descriptor, marker_stat = open_regular(rotation_fd, MARKER_NAME, exact_mode=0o600)
    try:
        marker = strict_json_bytes(read_limited(descriptor, 512))
    finally:
        os.close(descriptor)
    if marker_stat.st_dev != os.fstat(rotation_fd).st_dev:
        reject()
    if set(marker) != {
        "schema_version",
        "blackbox_exporter_was_running",
        "operator_was_running",
    }:
        reject()
    if marker["schema_version"] != 1 or isinstance(marker["schema_version"], bool):
        reject()
    if type(marker["blackbox_exporter_was_running"]) is not bool:
        reject()
    if type(marker["operator_was_running"]) is not bool:
        reject()
    secret_root = os.path.realpath(SECRETS)
    trusted_fixture_patterns = (
        r"/private/var/folders/[^/]+/[^/]+/T/(?:[.]ctx-mode-[A-Za-z0-9_-]+/)?pytest-of-[^/]+/pytest-[0-9]+(?:/.*)?",
        r"/(?:private/)?(?:tmp|var/tmp)/(?:[.]ctx-mode-[A-Za-z0-9_-]+/)?pytest-of-[^/]+/pytest-[0-9]+(?:/.*)?",
    )
    if not any(
        re.fullmatch(pattern, secret_root) for pattern in trusted_fixture_patterns
    ):
        reject()
    return marker


def test_controls(rotation_fd: int | None) -> tuple[str, str, str, str]:
    interrupt = os.environ.get("MCP_CLIENT_ROTATOR_TEST_INTERRUPT_AFTER_PHASE", "")
    fsync_failure = os.environ.get("MCP_CLIENT_ROTATOR_TEST_FAIL_FSYNC", "")
    validation_failure = os.environ.get("MCP_CLIENT_ROTATOR_TEST_FAIL_VALIDATION", "")
    generation_mutation = os.environ.get(
        "MCP_CLIENT_ROTATOR_TEST_MUTATE_GENERATION_BEFORE_RENAME", ""
    )
    if interrupt and interrupt not in INTERRUPT_POINTS:
        reject()
    if fsync_failure and fsync_failure not in FSYNC_FAILURES:
        reject()
    if validation_failure and validation_failure not in VALIDATION_FAILURES:
        reject()
    if generation_mutation and generation_mutation not in {
        "old_cert",
        "old_key",
        "new_cert",
        "new_key",
    }:
        reject()
    if interrupt or fsync_failure or validation_failure or generation_mutation:
        if rotation_fd is None:
            reject()
        load_marker(rotation_fd)
    return interrupt, fsync_failure, validation_failure, generation_mutation


def interrupt_after(rotation_fd: int, phase: str) -> None:
    interrupt, _, _, _ = test_controls(rotation_fd)
    if interrupt == phase:
        os._exit(86)


def fsync_directory(directory: int, rotation_fd: int, label: str = "") -> None:
    _, failure, _, _ = test_controls(rotation_fd)
    if label and failure == label:
        reject()
    os.fsync(directory)


def write_all(descriptor: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        written = os.write(descriptor, value[offset:])
        if written <= 0:
            reject()
        offset += written


def copy_entry(
    source_directory: int,
    source_name: str,
    target_directory: int,
    target_name: str,
    *,
    source_exact_mode: int | None = None,
    source_public: bool = False,
) -> None:
    source, _ = open_regular(
        source_directory,
        source_name,
        exact_mode=source_exact_mode,
        writable_public_forbidden=source_public,
    )
    target = -1
    try:
        target = os.open(
            target_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
            0o600,
            dir_fd=target_directory,
        )
        while True:
            chunk = os.read(source, 65536)
            if not chunk:
                break
            write_all(target, chunk)
        os.fchmod(target, 0o600)
        os.fsync(target)
    except BaseException:
        if target >= 0:
            os.close(target)
            target = -1
        try:
            os.unlink(target_name, dir_fd=target_directory)
        except OSError:
            pass
        raise
    finally:
        os.close(source)
        if target >= 0:
            os.close(target)


def generation_name(transaction_id: str, generation: str, kind: str) -> str:
    if generation not in {"old", "new"} or kind not in {"crt", "key"}:
        reject()
    return f"generation.{transaction_id}.{generation}.{kind}"


def validate_journal(value: dict[str, object]) -> dict[str, object]:
    if set(value) != JOURNAL_FIELDS:
        reject()
    if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
        reject()
    transaction_id = value["transaction_id"]
    if not isinstance(transaction_id, str) or not re.fullmatch(
        r"[0-9a-f]{32,64}", transaction_id
    ):
        reject()
    created_at = value["created_at"]
    if not isinstance(created_at, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
        created_at,
    ):
        reject()
    try:
        dt.datetime.fromisoformat(created_at[:-1] + "+00:00")
    except ValueError:
        reject()
    if value["phase"] not in PHASES:
        reject()
    for field in (
        "old_cert_sha256",
        "old_key_sha256",
        "new_cert_sha256",
        "new_key_sha256",
    ):
        if not isinstance(value[field], str) or not re.fullmatch(
            r"[0-9a-f]{64}", value[field]
        ):
            reject()
    if type(value["blackbox_exporter_was_running"]) is not bool:
        reject()
    if type(value["operator_was_running"]) is not bool:
        reject()
    return value


def load_journal(rotation_fd: int) -> dict[str, object]:
    descriptor, journal_stat = open_regular(
        rotation_fd,
        JOURNAL_NAME,
        exact_mode=0o600,
    )
    try:
        journal = validate_journal(
            strict_json_bytes(read_limited(descriptor, MAX_JOURNAL_BYTES))
        )
    finally:
        os.close(descriptor)
    if journal_stat.st_dev != os.fstat(rotation_fd).st_dev:
        reject()
    return journal


def write_journal(
    rotation_fd: int,
    journal: dict[str, object],
    *,
    parent_failure_label: str = "",
) -> None:
    journal = validate_journal(dict(journal))
    payload = (
        json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_JOURNAL_BYTES:
        reject()
    temporary_name = (
        f".transaction.{journal['transaction_id']}.{secrets.token_hex(8)}.tmp"
    )
    descriptor = -1
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
            0o600,
            dir_fd=rotation_fd,
        )
        write_all(descriptor, payload)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(
            temporary_name,
            JOURNAL_NAME,
            src_dir_fd=rotation_fd,
            dst_dir_fd=rotation_fd,
        )
        fsync_directory(
            rotation_fd,
            rotation_fd,
            parent_failure_label,
        )
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=rotation_fd)
        except OSError:
            pass
        raise


def validate_generations(rotation_fd: int, journal: dict[str, object]) -> None:
    transaction_id = str(journal["transaction_id"])
    mapping = {
        "old_cert_sha256": generation_name(transaction_id, "old", "crt"),
        "old_key_sha256": generation_name(transaction_id, "old", "key"),
        "new_cert_sha256": generation_name(transaction_id, "new", "crt"),
        "new_key_sha256": generation_name(transaction_id, "new", "key"),
    }
    for field, name in mapping.items():
        if digest_entry(rotation_fd, name, exact_mode=0o600) != journal[field]:
            reject()


def canonical_digests(secrets_fd: int) -> tuple[str, str]:
    return (
        digest_entry(secrets_fd, CERTIFICATE_NAME, public=True),
        digest_entry(secrets_fd, PRIVATE_KEY_NAME, exact_mode=0o600),
    )


def canonical_state(journal: dict[str, object], current: tuple[str, str]) -> str:
    states = {
        (journal["old_cert_sha256"], journal["old_key_sha256"]): "old_old",
        (journal["new_cert_sha256"], journal["old_key_sha256"]): "new_old",
        (journal["new_cert_sha256"], journal["new_key_sha256"]): "new_new",
        (journal["old_cert_sha256"], journal["new_key_sha256"]): "old_new",
    }
    state = states.get(current)
    if state is None:
        reject()
    return state


def require_reachable(journal: dict[str, object], state: str) -> None:
    allowed = {
        "prepared": {"old_old", "new_old"},
        "certificate_published": {"new_old", "new_new"},
        "pair_published": {"new_new"},
        "published_validated": {"new_new"},
        "restoring_certificate": {"old_old", "new_old", "new_new", "old_new"},
        "restoring_key": {"old_new", "old_old"},
        "old_pair_restored": {"old_old"},
    }
    if state not in allowed[str(journal["phase"])]:
        reject()


def publish_generation(
    rotation_fd: int,
    secrets_fd: int,
    generation: str,
    kind: str,
    transaction_id: str,
    *,
    expected_digest: str,
    parent_failure_label: str,
    pre_fsync_interrupt: str,
    post_fsync_interrupt: str,
) -> None:
    source_name = generation_name(transaction_id, generation, kind)
    temporary_name = f".publish.{transaction_id}.{kind}.{secrets.token_hex(8)}.tmp"
    copy_entry(
        rotation_fd,
        source_name,
        rotation_fd,
        temporary_name,
        source_exact_mode=0o600,
    )
    if digest_entry(rotation_fd, temporary_name, exact_mode=0o600) != expected_digest:
        os.unlink(temporary_name, dir_fd=rotation_fd)
        reject()
    canonical_name = CERTIFICATE_NAME if kind == "crt" else PRIVATE_KEY_NAME
    try:
        os.replace(
            temporary_name,
            canonical_name,
            src_dir_fd=rotation_fd,
            dst_dir_fd=secrets_fd,
        )
    except BaseException:
        try:
            os.unlink(temporary_name, dir_fd=rotation_fd)
        except OSError:
            pass
        raise
    interrupt_after(rotation_fd, pre_fsync_interrupt)
    fsync_directory(secrets_fd, rotation_fd, parent_failure_label)
    interrupt_after(rotation_fd, post_fsync_interrupt)


def journal_exists(rotation_fd: int) -> bool:
    try:
        stat_entry(rotation_fd, JOURNAL_NAME)
    except FileNotFoundError:
        return False
    return True


def mutate_generation_before_rename(
    rotation_fd: int,
    journal: dict[str, object],
) -> None:
    _, _, _, requested = test_controls(rotation_fd)
    if not requested:
        return
    generation, kind = {
        "old_cert": ("old", "crt"),
        "old_key": ("old", "key"),
        "new_cert": ("new", "crt"),
        "new_key": ("new", "key"),
    }[requested]
    name = generation_name(str(journal["transaction_id"]), generation, kind)
    before = stat_entry(rotation_fd, name)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != UID
        or stat.S_IMODE(before.st_mode) != 0o600
    ):
        reject()
    descriptor = os.open(name, os.O_WRONLY | os.O_TRUNC | NOFOLLOW, dir_fd=rotation_fd)
    try:
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            reject()
        write_all(descriptor, b"fixture-generation-mutation\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare_and_publish(
    secrets_fd: int,
    rotation_fd: int,
    stage_fd: int,
) -> None:
    marker = load_marker(rotation_fd)
    if journal_exists(rotation_fd):
        reject()
    transaction_id = secrets.token_hex(16)
    copies = (
        (secrets_fd, CERTIFICATE_NAME, "old", "crt", None, True),
        (secrets_fd, PRIVATE_KEY_NAME, "old", "key", 0o600, False),
        (stage_fd, CERTIFICATE_NAME, "new", "crt", None, True),
        (stage_fd, PRIVATE_KEY_NAME, "new", "key", 0o600, False),
    )
    for source_fd, source_name, generation, kind, exact_mode, public in copies:
        copy_entry(
            source_fd,
            source_name,
            rotation_fd,
            generation_name(transaction_id, generation, kind),
            source_exact_mode=exact_mode,
            source_public=public,
        )
    fsync_directory(rotation_fd, rotation_fd)
    old_cert = digest_entry(
        rotation_fd,
        generation_name(transaction_id, "old", "crt"),
        exact_mode=0o600,
    )
    old_key = digest_entry(
        rotation_fd,
        generation_name(transaction_id, "old", "key"),
        exact_mode=0o600,
    )
    new_cert = digest_entry(
        rotation_fd,
        generation_name(transaction_id, "new", "crt"),
        exact_mode=0o600,
    )
    new_key = digest_entry(
        rotation_fd,
        generation_name(transaction_id, "new", "key"),
        exact_mode=0o600,
    )
    created_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    journal: dict[str, object] = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "created_at": created_at.replace("+00:00", "Z"),
        "phase": "prepared",
        "old_cert_sha256": old_cert,
        "old_key_sha256": old_key,
        "new_cert_sha256": new_cert,
        "new_key_sha256": new_key,
        "blackbox_exporter_was_running": marker[
            "blackbox_exporter_was_running"
        ],
        "operator_was_running": marker["operator_was_running"],
    }
    write_journal(
        rotation_fd,
        journal,
        parent_failure_label="journal-parent",
    )
    interrupt_after(rotation_fd, "prepared")
    mutate_generation_before_rename(rotation_fd, journal)
    validate_generations(rotation_fd, journal)
    if canonical_state(journal, canonical_digests(secrets_fd)) != "old_old":
        reject()
    publish_generation(
        rotation_fd,
        secrets_fd,
        "new",
        "crt",
        transaction_id,
        expected_digest=str(journal["new_cert_sha256"]),
        parent_failure_label="certificate-parent",
        pre_fsync_interrupt="certificate_renamed",
        post_fsync_interrupt="certificate_parent_fsynced",
    )
    journal["phase"] = "certificate_published"
    write_journal(rotation_fd, journal)
    interrupt_after(rotation_fd, "certificate_published")
    if canonical_state(journal, canonical_digests(secrets_fd)) != "new_old":
        reject()
    publish_generation(
        rotation_fd,
        secrets_fd,
        "new",
        "key",
        transaction_id,
        expected_digest=str(journal["new_key_sha256"]),
        parent_failure_label="key-parent",
        pre_fsync_interrupt="key_renamed",
        post_fsync_interrupt="key_parent_fsynced",
    )
    journal["phase"] = "pair_published"
    write_journal(rotation_fd, journal)
    interrupt_after(rotation_fd, "pair_published")


def recover(secrets_fd: int, rotation_fd: int) -> None:
    journal = load_journal(rotation_fd)
    validate_generations(rotation_fd, journal)
    state = canonical_state(journal, canonical_digests(secrets_fd))
    require_reachable(journal, state)
    transaction_id = str(journal["transaction_id"])
    if journal["phase"] not in {
        "restoring_certificate",
        "restoring_key",
        "old_pair_restored",
    }:
        journal["phase"] = "restoring_certificate"
        write_journal(rotation_fd, journal)
        interrupt_after(rotation_fd, "restoring_certificate")
    if journal["phase"] == "restoring_certificate":
        state = canonical_state(journal, canonical_digests(secrets_fd))
        require_reachable(journal, state)
        publish_generation(
            rotation_fd,
            secrets_fd,
            "old",
            "crt",
            transaction_id,
            expected_digest=str(journal["old_cert_sha256"]),
            parent_failure_label="",
            pre_fsync_interrupt="old_certificate_restored",
            post_fsync_interrupt="old_certificate_parent_fsynced",
        )
        journal["phase"] = "restoring_key"
        write_journal(rotation_fd, journal)
        interrupt_after(rotation_fd, "restoring_key")
    if journal["phase"] == "restoring_key":
        state = canonical_state(journal, canonical_digests(secrets_fd))
        require_reachable(journal, state)
        publish_generation(
            rotation_fd,
            secrets_fd,
            "old",
            "key",
            transaction_id,
            expected_digest=str(journal["old_key_sha256"]),
            parent_failure_label="",
            pre_fsync_interrupt="old_key_restored",
            post_fsync_interrupt="old_key_parent_fsynced",
        )
        journal["phase"] = "old_pair_restored"
        write_journal(rotation_fd, journal)
        interrupt_after(rotation_fd, "old_pair_restored")
    state = canonical_state(journal, canonical_digests(secrets_fd))
    require_reachable(journal, state)


def main() -> None:
    if os.path.basename(CERTIFICATE) != CERTIFICATE_NAME:
        reject()
    if os.path.basename(PRIVATE_KEY) != PRIVATE_KEY_NAME:
        reject()
    if os.path.dirname(CERTIFICATE) != SECRETS or os.path.dirname(PRIVATE_KEY) != SECRETS:
        reject()
    controls_present = any(
        os.environ.get(name)
        for name in (
            "MCP_CLIENT_ROTATOR_TEST_INTERRUPT_AFTER_PHASE",
            "MCP_CLIENT_ROTATOR_TEST_FAIL_FSYNC",
            "MCP_CLIENT_ROTATOR_TEST_FAIL_VALIDATION",
            "MCP_CLIENT_ROTATOR_TEST_MUTATE_GENERATION_BEFORE_RENAME",
        )
    )
    rotation_present = os.path.lexists(ROTATION)
    if ACTION == "recover" and not rotation_present and not controls_present:
        print("absent")
        return
    secrets_fd, secrets_stat = open_directory(SECRETS)
    rotation_fd = -1
    try:
        if not rotation_present:
            if ACTION == "recover" and not controls_present:
                print("absent")
                return
            reject()
        if os.path.dirname(ROTATION) != SECRETS:
            reject()
        rotation_fd, rotation_stat = open_directory(ROTATION, exact_mode=0o700)
        if rotation_stat.st_dev != secrets_stat.st_dev:
            reject()
        test_controls(rotation_fd)
        if ACTION == "fixture-guard":
            load_marker(rotation_fd)
            return
        if ACTION == "recover":
            if not journal_exists(rotation_fd):
                print("absent")
                return
            recover(secrets_fd, rotation_fd)
            print("restored")
            return
        if ACTION == "publish":
            load_marker(rotation_fd)
            if os.path.dirname(STAGE) != ROTATION:
                reject()
            stage_fd, stage_stat = open_directory(STAGE, exact_mode=0o700)
            try:
                if stage_stat.st_dev != secrets_stat.st_dev:
                    reject()
                prepare_and_publish(secrets_fd, rotation_fd, stage_fd)
            finally:
                os.close(stage_fd)
            return
        if ACTION == "mark-published-validated":
            journal = load_journal(rotation_fd)
            validate_generations(rotation_fd, journal)
            if journal["phase"] != "pair_published":
                reject()
            state = canonical_state(journal, canonical_digests(secrets_fd))
            if state != "new_new":
                reject()
            journal["phase"] = "published_validated"
            write_journal(rotation_fd, journal)
            return
        if ACTION == "finish-recovery":
            journal = load_journal(rotation_fd)
            validate_generations(rotation_fd, journal)
            if journal["phase"] != "old_pair_restored":
                reject()
            state = canonical_state(journal, canonical_digests(secrets_fd))
            if state != "old_old":
                reject()
            os.unlink(JOURNAL_NAME, dir_fd=rotation_fd)
            fsync_directory(rotation_fd, rotation_fd)
            return
        reject()
    finally:
        if rotation_fd >= 0:
            os.close(rotation_fd)
        os.close(secrets_fd)


try:
    main()
except (OSError, TransactionError, ValueError, TypeError, OverflowError):
    raise SystemExit(1)
PY
}

if recovery_state=$(transaction_call recover); then
  case "$recovery_state" in
    absent) ;;
    restored)
      recovery_validation_failed=0
      if [ "${MCP_CLIENT_ROTATOR_TEST_FAIL_VALIDATION:-}" = restored ]; then
        if ! transaction_call fixture-guard >/dev/null 2>&1; then
          recovery_failed 'fixture recovery control is invalid'
        fi
        recovery_validation_failed=1
      elif ! env LC_ALL=C MCP_CLIENT_TLS_HOSTNAME=mcp-client.mnemo.local MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS=21600 MNEMO_SECRETS_DIR="$SECRETS_DIR" "$VALIDATOR" "$ROOT_CA" "$CERT_BUNDLE" "$PRIVATE_KEY" >/dev/null 2>&1; then
        recovery_validation_failed=1
      fi
      if [ "$recovery_validation_failed" -ne 0 ]; then
        recovery_failed 'restored certificate validation failed'
      fi
      if ! transaction_call finish-recovery >/dev/null 2>&1; then
        recovery_failed 'recovery finalization failed'
      fi
      ;;
    *) recovery_failed 'transaction recovery returned an invalid state' ;;
  esac
else
  recovery_status=$?
  [ "$recovery_status" -ne 86 ] || exit 86
  recovery_failed 'transaction recovery failed'
fi

if [ "$FIXTURE_TRANSACTION" -eq 1 ]; then
  if ! transaction_call fixture-guard >/dev/null 2>&1; then
    preflight_failed 'fixture transaction marker is invalid'
  fi
fi

source_path_error=$(
  "$PYTHON" - \
    "$ROOT_CA" public \
    "$CERT_BUNDLE" public \
    "$PRIVATE_KEY" private 2>/dev/null <<'PY'
import os
import stat
import sys


def reject(message: str) -> None:
    print(message)
    raise SystemExit(1)


arguments = sys.argv[1:]
for raw_path, kind in zip(arguments[::2], arguments[1::2]):
    path = os.path.abspath(raw_path)
    current = os.path.sep
    for component in path.split(os.path.sep)[1:]:
        current = os.path.join(current, component)
        try:
            component_stat = os.lstat(current)
        except OSError:
            reject("source certificate inputs must be regular files")
        if stat.S_ISLNK(component_stat.st_mode):
            reject("source certificate path components must not be symlinks")
    file_stat = os.lstat(path)
    if not stat.S_ISREG(file_stat.st_mode):
        reject("source certificate inputs must be regular files")
    if file_stat.st_uid != os.getuid():
        reject("source certificate inputs must be owned by the current user")
    mode = stat.S_IMODE(file_stat.st_mode)
    if kind == "private" and mode != 0o600:
        reject("source private key must have mode 0600")
    if kind == "public" and mode & 0o022:
        reject("source certificate inputs must not be group/world writable")
PY
) || preflight_failed "$source_path_error"

if env \
  LC_ALL=C \
  MCP_CLIENT_TLS_HOSTNAME=mcp-client.mnemo.local \
  MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS=21600 \
  MNEMO_SECRETS_DIR="$SECRETS_DIR" \
  "$VALIDATOR" "$ROOT_CA" "$CERT_BUNDLE" "$PRIVATE_KEY" \
  >/dev/null 2>&1; then
  :
elif env \
  LC_ALL=C \
  MCP_CLIENT_TLS_HOSTNAME=mcp-client.mnemo.local \
  MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS=21600 \
  MNEMO_SECRETS_DIR="$SECRETS_DIR" \
  "$DIAGNOSTIC" "$ROOT_CA" "$CERT_BUNDLE" "$PRIVATE_KEY" \
  >/dev/null 2>&1; then
  :
else
  preflight_failed 'source certificate validation failed'
fi

DECISION_EPOCH=$(date +%s) || preflight_failed 'renewal decision time is unavailable'
end_date=$("$OPENSSL" x509 -in "$CERT_BUNDLE" -noout -enddate 2>/dev/null) || \
  preflight_failed 'source certificate expiry could not be read'
end_epoch=$(
  "$PYTHON" - "$end_date" 2>/dev/null <<'PY'
from email.utils import parsedate_to_datetime
import sys


try:
    _, value = sys.argv[1].split("=", 1)
    print(int(parsedate_to_datetime(value).timestamp()))
except (TypeError, ValueError, OverflowError):
    raise SystemExit(1)
PY
) || preflight_failed 'source certificate expiry could not be parsed'
remaining_seconds=$((end_epoch - DECISION_EPOCH))
renewal_state=$(classify_remaining "$remaining_seconds") || \
  preflight_failed 'source certificate lifetime could not be classified'

if [ "$renewal_state" = healthy ]; then
  result healthy_noop
  exit 0
fi

for configuration_path in "$COMPOSE_FILE" "$STAGE_DIR"; do
  case "$configuration_path" in
    /*) ;;
    *) preflight_failed 'rotation configuration paths must be absolute' ;;
  esac
done

[ ! -e "$STAGE_DIR" ] && [ ! -L "$STAGE_DIR" ] || \
  preflight_failed 'staging directory already exists'

mount_path_error=$(
  "$PYTHON" - \
    "$ROOT_CA" public \
    "$PROVISIONER_PASSWORD" secret \
    "$COMPOSE_FILE" public \
    "$ROTATION_DIR" rotation \
    "$SECRETS_DIR" directory \
    "$STAGE_DIR" future 2>/dev/null <<'PY'
import os
import stat
import sys


def reject(message: str) -> None:
    print(message)
    raise SystemExit(1)


arguments = sys.argv[1:]
paths = list(zip(arguments[::2], arguments[1::2]))
for raw_path, kind in paths:
    if any(character in raw_path for character in (",", "\n", "\r")):
        reject("mount paths contain unsupported characters")
    path = os.path.abspath(raw_path)
    inspected = os.path.dirname(path) if kind == "future" else path
    current = os.path.sep
    for component in inspected.split(os.path.sep)[1:]:
        current = os.path.join(current, component)
        try:
            component_stat = os.lstat(current)
        except OSError:
            reject("rotation mount inputs are missing")
        if stat.S_ISLNK(component_stat.st_mode):
            reject("rotation mount path components must not be symlinks")
    if kind == "future":
        continue
    file_stat = os.lstat(path)
    expected_type = (
        stat.S_ISDIR if kind in ("directory", "rotation") else stat.S_ISREG
    )
    if not expected_type(file_stat.st_mode):
        reject("rotation mount inputs have the wrong type")
    if file_stat.st_uid != os.getuid():
        reject("rotation mount inputs must be owned by the current user")
    mode = stat.S_IMODE(file_stat.st_mode)
    if kind == "secret" and mode != 0o600:
        reject("provisioner password must have mode 0600")
    if kind == "public" and mode & 0o022:
        reject("rotation public inputs must not be group/world writable")
    if kind == "directory" and mode & 0o022:
        reject("rotation directories must not be group/world writable")
    if kind == "rotation" and mode != 0o700:
        reject("private rotation directory must have mode 0700")

rotation = os.path.abspath(paths[3][0])
secrets = os.path.abspath(paths[4][0])
stage = os.path.abspath(paths[5][0])
if os.path.dirname(stage) != rotation or os.path.basename(stage) in ("", ".", ".."):
    reject("staging directory must be a direct child of the private rotation directory")
if os.stat(rotation).st_dev != os.stat(secrets).st_dev:
    reject("staging and canonical certificate paths must share a filesystem")

password = os.path.abspath(paths[1][0])
data = open(password, "rb").read(4097)
if not data or len(data) > 4096 or b"\0" in data or b"\r" in data:
    reject("provisioner password has an invalid encoding")
if b"\n" in data[:-1] or data.count(b"\n") > 1:
    reject("provisioner password must contain exactly one line")
PY
) || preflight_failed "$mount_path_error"

compose_image=$(
  awk '$1 == "image:" && $2 ~ /^smallstep\/step-ca:/ {print $2}' "$COMPOSE_FILE"
) || preflight_failed 'Compose step-ca image could not be read'
[ "$compose_image" = "$STEP_IMAGE" ] || \
  preflight_failed 'Compose step-ca image is not the required digest pin'

DOCKER_BIN=${MCP_CLIENT_ROTATOR_DOCKER_BIN:-}
if [ -z "$DOCKER_BIN" ]; then
  DOCKER_BIN=$(command -v docker || :)
fi
[ -n "$DOCKER_BIN" ] && [ -x "$DOCKER_BIN" ] && [ ! -d "$DOCKER_BIN" ] || \
  runtime_unavailable 'Docker is unavailable'

SAFE_PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin
SAFE_HOME=$(
  "$PYTHON" -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)' 2>/dev/null
) || preflight_failed 'current user home could not be resolved'
SAFE_TMPDIR=/tmp
docker_call() {
  env -i \
    HOME="$SAFE_HOME" \
    LC_ALL=C \
    PATH="$SAFE_PATH" \
    TMPDIR="$SAFE_TMPDIR" \
    "$DOCKER_BIN" "$@"
}

if ! active_context=$(docker_call context show 2>/dev/null); then
  runtime_unavailable 'Docker is unavailable'
fi
[ "$active_context" = colima ] || preflight_failed 'Docker context must be colima'

network_json=$(
  docker_call --context colima network inspect infra_internal 2>/dev/null
) || preflight_failed 'required Docker network is unavailable'
printf '%s' "$network_json" | "$PYTHON" -c '
import json
import sys

value = json.load(sys.stdin)
if isinstance(value, list):
    if len(value) != 1:
        raise SystemExit(1)
    value = value[0]
labels = value.get("Labels") or {}
valid = (
    value.get("Name") == "infra_internal"
    and value.get("Internal") is True
    and labels.get("com.docker.compose.project") == "infra"
    and labels.get("com.docker.compose.network") == "internal"
)
raise SystemExit(not valid)
' 2>/dev/null || preflight_failed 'required Docker network identity is invalid'

docker_call --context colima image inspect "$STEP_IMAGE" \
  >/dev/null 2>&1 || preflight_failed 'required step-ca image is unavailable'

version_output=$(
  docker_call --context colima run \
    --rm \
    --pull never \
    --read-only \
    --user 1000:1000 \
    --pids-limit 64 \
    --cap-drop ALL \
    --security-opt no-new-privileges=true \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --network none \
    --entrypoint /usr/local/bin/step \
    "$STEP_IMAGE" version 2>/dev/null
) || preflight_failed 'step CLI version probe failed'
[ "$version_output" = 'Smallstep CLI/0.28.7' ] || \
  preflight_failed 'step CLI version is not approved'

mkdir -m 700 "$STAGE_DIR" || preflight_failed 'private staging directory could not be created'
stage_mode=$(
  "$PYTHON" - "$STAGE_DIR" 2>/dev/null <<'PY'
import os
import stat
import sys


value = os.lstat(sys.argv[1])
if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.getuid():
    raise SystemExit(1)
print(f"{stat.S_IMODE(value.st_mode):03o}")
PY
) || preflight_failed 'private staging directory could not be verified'
[ "$stage_mode" = 700 ] || preflight_failed 'private staging directory must have mode 0700'

if ! docker_call --context colima run \
  --rm \
  --pull never \
  --read-only \
  --user 1000:1000 \
  --pids-limit 64 \
  --cap-drop ALL \
  --security-opt no-new-privileges=true \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --network infra_internal \
  --entrypoint /usr/local/bin/step \
  --mount "type=bind,src=$ROOT_CA,dst=/run/mnemo/root.crt,readonly" \
  --mount "type=bind,src=$PROVISIONER_PASSWORD,dst=/run/mnemo/provisioner-password,readonly" \
  --mount "type=bind,src=$STAGE_DIR,dst=/work" \
  "$STEP_IMAGE" \
  ca certificate \
  --ca-url https://ca.mnemo.local:9000 \
  --root /run/mnemo/root.crt \
  --provisioner admin \
  --provisioner-password-file /run/mnemo/provisioner-password \
  --san mcp-client.mnemo.local \
  --not-after 24h \
  mcp-client.mnemo.local \
  /work/mcp-client.crt \
  /work/mcp-client.key \
  </dev/null >/dev/null 2>&1; then
  issuance_failed 'staged issuance failed'
fi

if ! "$PYTHON" - "$STAGE_DIR" "$SECRETS_DIR" >/dev/null 2>&1 <<'PY'
import os
import stat
import sys


stage = os.path.abspath(sys.argv[1])
secrets = os.path.abspath(sys.argv[2])
stage_stat = os.lstat(stage)
if (
    not stat.S_ISDIR(stage_stat.st_mode)
    or stage_stat.st_uid != os.getuid()
    or stat.S_IMODE(stage_stat.st_mode) != 0o700
    or stage_stat.st_dev != os.stat(secrets).st_dev
):
    raise SystemExit(1)

expected = {"mcp-client.crt", "mcp-client.key"}
if set(os.listdir(stage)) != expected:
    raise SystemExit(1)

for name in expected:
    value = os.lstat(os.path.join(stage, name))
    mode = stat.S_IMODE(value.st_mode)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.getuid()
        or value.st_dev != stage_stat.st_dev
        or value.st_size == 0
    ):
        raise SystemExit(1)
    if name.endswith(".key") and mode != 0o600:
        raise SystemExit(1)
    if name.endswith(".crt") and mode & 0o022:
        raise SystemExit(1)
PY
then
  issuance_failed 'staged validation failed'
fi

if ! env \
  LC_ALL=C \
  MCP_CLIENT_TLS_HOSTNAME=mcp-client.mnemo.local \
  MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS=21600 \
  MNEMO_SECRETS_DIR="$SECRETS_DIR" \
  "$VALIDATOR" \
  "$ROOT_CA" \
  "$STAGE_DIR/mcp-client.crt" \
  "$STAGE_DIR/mcp-client.key" \
  >/dev/null 2>&1; then
  issuance_failed 'staged validation failed'
fi

if [ "$FIXTURE_TRANSACTION" -eq 1 ]; then
  if transaction_call publish >/dev/null 2>&1; then
    :
  else
    transaction_status=$?
    [ "$transaction_status" -ne 86 ] || exit 86
    publication_failed 'fixture publication failed'
  fi
  if [ "${MCP_CLIENT_ROTATOR_TEST_FAIL_VALIDATION:-}" = published ]; then
    publication_failed 'published certificate validation failed'
  fi
  if ! env \
    LC_ALL=C \
    MCP_CLIENT_TLS_HOSTNAME=mcp-client.mnemo.local \
    MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS=21600 \
    MNEMO_SECRETS_DIR="$SECRETS_DIR" \
    "$VALIDATOR" \
    "$ROOT_CA" \
    "$CERT_BUNDLE" \
    "$PRIVATE_KEY" \
    >/dev/null 2>&1; then
    publication_failed 'published certificate validation failed'
  fi
  transaction_call mark-published-validated >/dev/null 2>&1 || \
    publication_failed 'published journal validation failed'
  publication_failed 'consumer activation is unavailable in the R1b fixture seam'
fi

result staged_only
