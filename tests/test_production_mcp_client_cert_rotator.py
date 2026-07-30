from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import pwd
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


REPO = Path(__file__).resolve().parents[1]
ROTATOR = REPO / "infra" / "scripts" / "rotate-production-mcp-client-cert.sh"
ROTATOR_TEST_TIMEOUT_SECONDS = 15
ROTATOR_LOCK_TEST_TIMEOUT_SECONDS = 120


@pytest.fixture(autouse=True)
def _runtime_lock_custody(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custody_dir = tmp_path.parent / f".{tmp_path.name}-runtime-lock-custody"
    locks_dir = custody_dir / "locks"
    locks_dir.mkdir(parents=True, mode=0o700)
    lock_dir = locks_dir / "runtime-exclusive"
    lock_dir.mkdir(mode=0o700)
    owner = lock_dir / "owner.json"
    owner_fd = os.open(owner, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    fcntl.flock(owner_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    owner_token = secrets.token_hex(32)
    metadata = {
        "host": socket.gethostname(),
        "operation": "rotate-production-mcp-client-cert",
        "owner_token": owner_token,
        "pid": os.getpid(),
        "process_start_fingerprint": _process_start_fingerprint(os.getpid()),
        "schema_version": 1,
        "started_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "uid": os.getuid(),
    }
    payload = (
        json.dumps(metadata, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")
    os.write(owner_fd, payload)
    os.fsync(owner_fd)
    os.set_inheritable(owner_fd, True)
    monkeypatch.setenv("MNEMO_CUSTODY_DIR", str(custody_dir))
    monkeypatch.setenv("MNEMO_RUNTIME_LOCK_OWNER_FD", str(owner_fd))
    yield
    assert owner.read_bytes() == payload
    os.close(owner_fd)
    owner.unlink()
    lock_dir.rmdir()
    locks_dir.rmdir()
    custody_dir.rmdir()


def _process_start_fingerprint(pid: int) -> str:
    if sys.platform.startswith("linux"):
        boot_id = (
            Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        )
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        closing = raw.rfind(")")
        return f"linux:{boot_id.lower()}:{raw[closing + 2 :].split()[19]}"
    completed = subprocess.run(
        ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
        check=True,
        capture_output=True,
        env={"LC_ALL": "C", "LANG": "C", "PATH": "/usr/bin:/bin"},
        text=True,
        timeout=2,
    )
    return f"darwin:{completed.stdout.strip()}"


def _runtime_lock_pass_fds(env: dict[str, str]) -> tuple[int, ...]:
    if "MNEMO_RUNTIME_LOCK_OWNER_FD" not in env:
        return ()
    return (int(env["MNEMO_RUNTIME_LOCK_OWNER_FD"]),)


def _real_runtime_lock_env(env: dict[str, str], tmp_path: Path) -> dict[str, str]:
    result = dict(env)
    result.pop("MNEMO_RUNTIME_LOCK_OWNER_FD", None)
    custody_dir = tmp_path / "real-runtime-lock-custody"
    (custody_dir / "locks").mkdir(parents=True, mode=0o700)
    result["MNEMO_CUSTODY_DIR"] = str(custody_dir)
    return result


VALIDATOR = REPO / "infra" / "validate" / "validate-production-mcp-client-tls.sh"
DIAGNOSTIC = (
    REPO / "infra" / "validate" / "diagnose-production-mcp-client-tls-for-rotation.sh"
)
COMPOSE = REPO / "infra" / "docker-compose.prod.yml"
IMAGE = (
    "smallstep/step-ca:0.28.4@sha256:"
    "0f88382ac5af5c6b7bbba0c6e8fcefef52aee6f22ea364df8e02a09ffd0d22f3"
)
TRANSACTION_ACTION = "--test-fixture-transaction"
TRANSACTION_JOURNAL = "transaction.json"
TRANSACTION_MARKER = "fixture-transaction.json"
COMPLETION_RECEIPT_FIELDS = {
    "schema_version",
    "transaction_id",
    "result",
    "completed_at",
}
BLACKBOX_CONTAINER_ID = "a" * 64
OPERATOR_CONTAINER_ID = "b" * 64
RECREATED_BLACKBOX_CONTAINER_ID = "c" * 64
CADDY_CONTAINER_ID = "d" * 64
FOREIGN_OWNER_TOKEN = "f" * 64
VALID_DB_PASSWORD = b"Db_password-1234!"
VALID_ADMIN_PASSWORD = b"Admin_password-5678!"
SAME_UID_REPLACEMENT = b"fixture-same-uid-replacement"
CONSUMER_FORMAT = "{{.ID}}"
CONSUMER_SNAPSHOT_FORMAT = r'{{.ID}}\t{{.Label "com.docker.compose.service"}}'
BLACKBOX_QUERY_URL = (
    "http://victoriametrics:8428/api/v1/query?query="
    "timestamp%28probe_success%7Bjob%3D%22blackbox-tls%22%2Cinstance%3D%22"
    "https%3A%2F%2Fmcp.mnemo.local%22%7D%5B2m%5D%29%20if%20%28"
    "last_over_time%28probe_success%7Bjob%3D%22blackbox-tls%22%2Cinstance%3D%22"
    "https%3A%2F%2Fmcp.mnemo.local%22%7D%5B2m%5D%29%20%3D%3D%201%29"
)
DOTENV_RECEIPT_NAME = "compose-env-owner.json"
COMPOSE_ENV_FIELDS = {
    "schema_version",
    "state",
    "owner_token",
    "basename",
    "quarantine_basename",
    "device",
    "inode",
    "uid",
    "mode",
    "nlink",
    "created_at",
}
DOTENV_RECEIPT_FIELDS = {"schema_version", "transaction_id", "compose_env"}
TRANSACTION_FIELDS = {
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
    "compose_env",
}


def _consumer_discovery_call(service: str) -> list[str]:
    return [
        "--context",
        "colima",
        "ps",
        "--filter",
        "status=running",
        "--filter",
        "label=com.docker.compose.project=infra",
        "--filter",
        f"label=com.docker.compose.service={service}",
        "--format",
        CONSUMER_FORMAT,
    ]


def _consumer_snapshot_call() -> list[str]:
    return [
        "--context",
        "colima",
        "ps",
        "--no-trunc",
        "--filter",
        "status=running",
        "--filter",
        "label=com.docker.compose.project=infra",
        "--filter",
        "label=com.docker.compose.service",
        "--format",
        CONSUMER_SNAPSHOT_FORMAT,
    ]


def _consumer_snapshot_bytes(*rows: tuple[str, str]) -> bytes:
    return "".join(f"{identifier}\t{service}\n" for identifier, service in rows).encode(
        "ascii"
    )


def _blackbox_probe_calls() -> list[list[str]]:
    discovery = [
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
    prefix = [
        "--context",
        "colima",
        "exec",
        CADDY_CONTAINER_ID,
        "/bin/busybox",
        "wget",
    ]
    return [
        discovery,
        [*prefix, "--help"],
        [*prefix, "-q", "-O", "-", "-T", "5", "-t", "2", BLACKBOX_QUERY_URL],
    ]


def _direct_probe_call(fixture: TlsFixture, route: str) -> list[str]:
    return [
        "--disable",
        "--silent",
        "--show-error",
        "--output",
        "/dev/null",
        "--connect-timeout",
        "5",
        "--max-time",
        "15",
        "--tlsv1.3",
        "--tls-max",
        "1.3",
        "--resolve",
        "mcp.mnemo.local:443:127.0.0.1",
        "--cacert",
        str(fixture.root),
        "--cert",
        str(fixture.bundle),
        "--key",
        str(fixture.key),
        "--write-out",
        "%{http_code}",
        f"https://mcp.mnemo.local{route}",
    ]


@dataclass(frozen=True)
class TlsFixture:
    secrets: Path
    root: Path
    bundle: Path
    key: Path
    password: Path
    root_key: ec.EllipticCurvePrivateKey
    root_cert: x509.Certificate
    intermediate_key: ec.EllipticCurvePrivateKey
    intermediate_cert: x509.Certificate


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _certificate(
    *,
    subject: x509.Name,
    issuer: x509.Name,
    public_key: ec.EllipticCurvePublicKey,
    issuer_key: ec.EllipticCurvePrivateKey,
    is_ca: bool,
    not_before: dt.datetime,
    not_after: dt.datetime,
    hostname: str = "mcp-client.mnemo.local",
    eku: ExtendedKeyUsageOID = ExtendedKeyUsageOID.CLIENT_AUTH,
) -> x509.Certificate:
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
    )
    if not is_ca:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname)]),
            critical=False,
        ).add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


def _tls_fixture(
    tmp_path: Path,
    *,
    remaining: dt.timedelta = dt.timedelta(hours=13),
    stem: str = "current",
    expired: bool = False,
    not_yet_valid: bool = False,
    hostname: str = "mcp-client.mnemo.local",
    eku: ExtendedKeyUsageOID = ExtendedKeyUsageOID.CLIENT_AUTH,
    issuer: TlsFixture | None = None,
    intermediate_remaining: dt.timedelta = dt.timedelta(days=30),
    intermediate_starts_in: dt.timedelta = dt.timedelta(days=-2),
    leaf_started: dt.timedelta = dt.timedelta(minutes=-1),
) -> TlsFixture:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    root_key = issuer.root_key if issuer else ec.generate_private_key(ec.SECP256R1())
    intermediate_key = (
        issuer.intermediate_key if issuer else ec.generate_private_key(ec.SECP256R1())
    )
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    root_name = issuer.root_cert.subject if issuer else _name(f"{stem} root")
    intermediate_name = (
        issuer.intermediate_cert.subject if issuer else _name(f"{stem} intermediate")
    )
    leaf_name = _name(hostname)
    ca_before = now - dt.timedelta(days=2)
    intermediate_before = now + intermediate_starts_in
    root_after = now + dt.timedelta(days=30)
    intermediate_after = now + intermediate_remaining
    if expired:
        leaf_before = now - dt.timedelta(hours=2)
        leaf_after = now - dt.timedelta(hours=1)
    elif not_yet_valid:
        leaf_before = now + dt.timedelta(hours=1)
        leaf_after = now + dt.timedelta(hours=2)
    else:
        leaf_before = now + leaf_started
        leaf_after = now + remaining
    root = (
        issuer.root_cert
        if issuer
        else _certificate(
            subject=root_name,
            issuer=root_name,
            public_key=root_key.public_key(),
            issuer_key=root_key,
            is_ca=True,
            not_before=ca_before,
            not_after=root_after,
        )
    )
    intermediate = (
        issuer.intermediate_cert
        if issuer
        else _certificate(
            subject=intermediate_name,
            issuer=root_name,
            public_key=intermediate_key.public_key(),
            issuer_key=root_key,
            is_ca=True,
            not_before=intermediate_before,
            not_after=intermediate_after,
        )
    )
    leaf = _certificate(
        subject=leaf_name,
        issuer=intermediate_name,
        public_key=leaf_key.public_key(),
        issuer_key=intermediate_key,
        is_ca=False,
        not_before=leaf_before,
        not_after=leaf_after,
        hostname=hostname,
        eku=eku,
    )
    secrets = tmp_path / stem / "secrets"
    secrets.mkdir(parents=True)
    root_path = secrets / "stepca-acme-root.crt"
    bundle_path = secrets / "mcp-client.crt"
    key_path = secrets / "mcp-client.key"
    password_path = secrets / "step-ca-jwk-provisioner-password"
    root_path.write_bytes(root.public_bytes(serialization.Encoding.PEM))
    bundle_path.write_bytes(
        leaf.public_bytes(serialization.Encoding.PEM)
        + intermediate.public_bytes(serialization.Encoding.PEM)
    )
    key_path.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    password_path.write_text("provisioner-canary-must-never-leak\n", encoding="utf-8")
    password_path.chmod(0o600)
    return TlsFixture(
        secrets,
        root_path,
        bundle_path,
        key_path,
        password_path,
        root_key,
        root,
        intermediate_key,
        intermediate,
    )


def _write_fake_docker(
    tmp_path: Path,
    staged: TlsFixture,
    *,
    direct_probe_record: Path | None = None,
    fail_issuance: bool = False,
    child_canary: str = "",
    context: str = "colima",
    network_project: str = "infra",
    network_name: str = "internal",
    image_present: bool = True,
    cli_version: str = "Smallstep CLI/0.28.7",
    staged_cert_mode: int = 0o644,
    containers: tuple[tuple[str, str, str, str], ...] = (
        (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
    ),
    post_compose_containers: tuple[tuple[str, str, str, str], ...] | None = None,
    post_second_compose_containers: (
        tuple[tuple[str, str, str, str], ...] | None
    ) = None,
    post_compose_sequential_containers: (
        tuple[tuple[str, str, str, str], ...] | None
    ) = None,
    post_compose_container_sequence: (
        tuple[tuple[tuple[str, str, str, str], ...], ...]
    ) = (),
    post_compose_snapshot_bytes: bytes | None = None,
    post_compose_snapshot_bytes_sequence: tuple[bytes | None, ...] = (),
    fail_post_compose_snapshot: bool = False,
    fail_post_compose_snapshot_sequence: tuple[bool, ...] = (),
    compose_returncodes: tuple[int, ...] = (),
    replace_owner_token_on_compose: str | None = None,
    blackbox_query_returncode: int = 0,
    blackbox_query_returncodes: tuple[int, ...] = (),
    blackbox_expected_direct_probe_counts: tuple[int, ...] = (),
    blackbox_sample_age_seconds: float = 0.0,
    blackbox_sample_age_seconds_by_query: tuple[float, ...] = (),
    blackbox_sample_at_last_snapshot: bool = False,
    blackbox_sample_at_last_snapshot_queries: tuple[int, ...] = (),
    blackbox_sample_at_first_direct_probe: bool = False,
) -> tuple[Path, Path]:
    record = tmp_path / "docker-record.json"
    post_compose_container_records = list(
        containers if post_compose_containers is None else post_compose_containers
    )
    post_second_compose_container_records = list(
        post_compose_container_records
        if post_second_compose_containers is None
        else post_second_compose_containers
    )
    post_compose_sequential_container_records = list(
        post_compose_container_records
        if post_compose_sequential_containers is None
        else post_compose_sequential_containers
    )
    post_compose_container_sequence_records = [
        list(records) for records in post_compose_container_sequence
    ]
    direct_probe_record_value = (
        None if direct_probe_record is None else str(direct_probe_record)
    )
    docker = tmp_path / "fake-docker"
    docker.write_text(
        f"""#!{sys.executable}
import hashlib
import json
import os
import shutil
import stat
import sys
import time
from pathlib import Path

args = sys.argv[1:]
record = Path({str(record)!r})
audit = record.with_name("docker-calls.jsonl")
with audit.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\\n")
# macOS injects this after exec into Python processes; the Docker binary does not.
os.environ.pop("__CF_USER_TEXT_ENCODING", None)
if args == ["context", "show"]:
    print({context!r})
    raise SystemExit(0)
containers = {list(containers)!r}
post_compose_containers = {post_compose_container_records!r}
post_second_compose_containers = {post_second_compose_container_records!r}
post_compose_sequential_containers = {post_compose_sequential_container_records!r}
post_compose_container_sequence = {post_compose_container_sequence_records!r}
compose_transition = record.with_name("compose-transition")
second_compose_transition = record.with_name("compose-transition-2")
sequential_query_transition = record.with_name("sequential-query-transition")
last_snapshot_epoch = record.with_name("last-snapshot-epoch")
discovery_calls = {{
    "blackbox-exporter": {_consumer_discovery_call("blackbox-exporter")!r},
    "operator": {_consumer_discovery_call("operator")!r},
}}
snapshot_call = {_consumer_snapshot_call()!r}
blackbox_probe_calls = {_blackbox_probe_calls()!r}
direct_probe_record = {direct_probe_record_value!r}

def active_containers():
    compose_observations = record.with_name("dotenv-observations.jsonl")
    compose_count = (
        len(compose_observations.read_text(encoding="utf-8").splitlines())
        if compose_observations.exists()
        else 0
    )
    if post_compose_container_sequence and compose_count:
        return post_compose_container_sequence[
            min(compose_count, len(post_compose_container_sequence)) - 1
        ]
    if second_compose_transition.exists():
        return post_second_compose_containers
    if sequential_query_transition.exists():
        return post_compose_sequential_containers
    if compose_transition.exists():
        return post_compose_containers
    return containers

if args == snapshot_call:
    rows = [
        f"{{identifier}}\t{{service}}"
        for identifier, project, service, state in active_containers()
        if project == "infra" and state == "running"
    ]
    payload = (("\\n".join(rows) + "\\n").encode("ascii") if rows else b"")
    if compose_transition.exists():
        compose_observations = record.with_name("dotenv-observations.jsonl")
        compose_observation = json.loads(
            compose_observations.read_text(encoding="utf-8").splitlines()[-1]
        )
        snapshot_observations = record.with_name("snapshot-observations.jsonl")
        snapshot_index = (
            len(snapshot_observations.read_text(encoding="utf-8").splitlines())
            if snapshot_observations.exists()
            else 0
        )
        snapshot_payloads = {post_compose_snapshot_bytes_sequence!r}
        snapshot_payload = (
            snapshot_payloads[snapshot_index]
            if snapshot_index < len(snapshot_payloads)
            else {post_compose_snapshot_bytes!r}
        )
        if snapshot_payload is not None:
            payload = snapshot_payload
        with snapshot_observations.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({{
                "payload_hex": payload.hex(),
                "dotenv_path": compose_observation["dotenv_path"],
                "dotenv_exists": os.path.lexists(compose_observation["dotenv_path"]),
                "receipt_path": compose_observation["receipt_path"],
                "receipt_exists": os.path.lexists(compose_observation["receipt_path"]),
            }}, sort_keys=True) + "\\n")
        snapshot_time = time.time_ns()
        last_snapshot_epoch.write_text(
            f"{{snapshot_time // 1_000_000_000}}.{{snapshot_time % 1_000_000_000:09d}}",
            encoding="ascii",
        )
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()
    snapshot_failures = {fail_post_compose_snapshot_sequence!r}
    snapshot_failed = (
        snapshot_failures[snapshot_index]
        if compose_transition.exists() and snapshot_index < len(snapshot_failures)
        else {fail_post_compose_snapshot!r}
    )
    raise SystemExit(
        42 if compose_transition.exists() and snapshot_failed else 0
    )
if args in blackbox_probe_calls:
    if not compose_transition.exists() or direct_probe_record is None:
        raise SystemExit(95)
    probe_path = Path(direct_probe_record)
    completed_blackbox_cycles = sum(
        json.loads(line) == blackbox_probe_calls[2]
        for line in audit.read_text(encoding="utf-8").splitlines()
    ) - (1 if args == blackbox_probe_calls[2] else 0)
    expected_probe_counts = {blackbox_expected_direct_probe_counts!r}
    expected_probe_count = (
        expected_probe_counts[completed_blackbox_cycles]
        if completed_blackbox_cycles < len(expected_probe_counts)
        else 2 * (completed_blackbox_cycles + 1)
    )
    if not probe_path.exists() or len(
        probe_path.read_text(encoding="utf-8").splitlines()
    ) != expected_probe_count:
        raise SystemExit(96)
if args == blackbox_probe_calls[0]:
    print({CADDY_CONTAINER_ID!r})
    raise SystemExit(0)
if args == blackbox_probe_calls[1]:
    raise SystemExit(0)
if args == blackbox_probe_calls[2]:
    query_index = completed_blackbox_cycles
    compose_observations = record.with_name("dotenv-observations.jsonl")
    compose_observation = json.loads(
        compose_observations.read_text(encoding="utf-8").splitlines()[-1]
    )
    journal_path = Path(compose_observation["dotenv_path"]).parent / {TRANSACTION_JOURNAL!r}
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    query_returncodes = {blackbox_query_returncodes!r}
    query_returncode = (
        query_returncodes[query_index]
        if query_index < len(query_returncodes)
        else {blackbox_query_returncode!r}
    )
    if {blackbox_sample_at_first_direct_probe!r}:
        sample_source = "first-direct-probe"
        sample_age = None
    elif (
        {blackbox_sample_at_last_snapshot!r}
        or query_index in {blackbox_sample_at_last_snapshot_queries!r}
    ):
        sample_source = "last-snapshot"
        sample_age = None
    else:
        sample_ages = {blackbox_sample_age_seconds_by_query!r}
        sample_age = (
            sample_ages[query_index]
            if query_index < len(sample_ages)
            else {blackbox_sample_age_seconds!r}
        )
        sample_source = "relative-age"
    snapshot_observations = record.with_name("snapshot-observations.jsonl")
    blackbox_observations = record.with_name("blackbox-observations.jsonl")
    with blackbox_observations.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({{
            "direct_probe_count": len(
                probe_path.read_text(encoding="utf-8").splitlines()
            ),
            "journal_exists": journal_path.exists(),
            "journal_phase": journal["phase"],
            "query_index": query_index,
            "sample_age_seconds": sample_age,
            "sample_source": sample_source,
            "snapshot_count": len(
                snapshot_observations.read_text(encoding="utf-8").splitlines()
            ),
        }}, sort_keys=True) + "\\n")
    if query_returncode != 0:
        raise SystemExit(query_returncode)
    query_time = time.time()
    if sample_source == "first-direct-probe":
        sample_time = probe_path.with_name("first-direct-probe-epoch").read_text(
            encoding="ascii"
        )
    elif sample_source == "last-snapshot":
        sample_time = last_snapshot_epoch.read_text(encoding="ascii")
    else:
        sample_time = str(query_time - sample_age)
    print(json.dumps({{
        "status": "success",
        "data": {{
            "resultType": "vector",
            "result": [{{
                "metric": {{
                    "job": "blackbox-tls",
                    "instance": "https://mcp.mnemo.local",
                }},
                "value": [
                    query_time,
                    sample_time,
                ],
            }}],
        }},
    }}, separators=(",", ":")))
    raise SystemExit(0)
for service in ("blackbox-exporter", "operator"):
    if args == discovery_calls[service]:
        identifiers = [
            identifier
            for identifier, project, candidate_service, state in active_containers()
            if project == "infra"
            and candidate_service == service
            and state == "running"
        ]
        if identifiers:
            print("\\n".join(identifiers))
        if (
            compose_transition.exists()
            and not second_compose_transition.exists()
            and {post_compose_sequential_containers is not None!r}
        ):
            sequential_query_transition.touch()
        raise SystemExit(0)
if args[:5] == ["--context", "colima", "network", "inspect", "infra_internal"]:
    print(json.dumps({{
        "Name": "infra_internal",
        "Internal": True,
        "Labels": {{
            "com.docker.compose.project": {network_project!r},
            "com.docker.compose.network": {network_name!r},
        }},
    }}))
    raise SystemExit(0)
if args[:4] == ["--context", "colima", "image", "inspect"]:
    raise SystemExit(0 if {image_present!r} and args[4] == {IMAGE!r} else 1)
if args[:3] == ["--context", "colima", "compose"] and "up" in args:
    dotenv = Path(args[args.index("--env-file") + 1])
    receipt_path = dotenv.parent / {DOTENV_RECEIPT_NAME!r}
    journal_path = dotenv.parent / {TRANSACTION_JOURNAL!r}
    dotenv_stat = os.lstat(dotenv)
    receipt_stat = os.lstat(receipt_path)
    rotation_stat = os.lstat(dotenv.parent)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    observation = record.with_name("dotenv-observations.jsonl")
    with observation.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({{
            "argv": args,
            "dotenv_path": str(dotenv),
            "dotenv_sha256": hashlib.sha256(dotenv.read_bytes()).hexdigest(),
            "dotenv_size": dotenv_stat.st_size,
            "dotenv_mode": stat.S_IMODE(dotenv_stat.st_mode),
            "dotenv_uid": dotenv_stat.st_uid,
            "dotenv_device": dotenv_stat.st_dev,
            "dotenv_inode": dotenv_stat.st_ino,
            "dotenv_nlink": dotenv_stat.st_nlink,
            "dotenv_mtime_ns": dotenv_stat.st_mtime_ns,
            "dotenv_regular": stat.S_ISREG(dotenv_stat.st_mode),
            "receipt_path": str(receipt_path),
            "receipt": receipt,
            "receipt_nlink": receipt_stat.st_nlink,
            "receipt_mode": stat.S_IMODE(receipt_stat.st_mode),
            "receipt_mtime_ns": receipt_stat.st_mtime_ns,
            "receipt_regular": stat.S_ISREG(receipt_stat.st_mode),
            "journal": journal,
            "rotation_parent_mode": stat.S_IMODE(rotation_stat.st_mode),
            "rotation_parent_uid": rotation_stat.st_uid,
            "rotation_parent_directory": stat.S_ISDIR(rotation_stat.st_mode),
            "env": dict(os.environ),
            "ambient_canary_present": any(
                "ambient-env-canary" in value for value in os.environ.values()
            ),
        }}, sort_keys=True) + "\\n")
    compose_call_index = len(observation.read_text(encoding="utf-8").splitlines()) - 1
    replacement_owner_token = {replace_owner_token_on_compose!r}
    if replacement_owner_token is not None:
        replacement_dotenv = dotenv.with_name(
            f"compose-env.{{replacement_owner_token}}.tmp"
        )
        dotenv.rename(replacement_dotenv)
        receipt["compose_env"]["owner_token"] = replacement_owner_token
        receipt["compose_env"]["basename"] = replacement_dotenv.name
        receipt["compose_env"]["quarantine_basename"] = (
            f"compose-env.{{replacement_owner_token}}.quarantine"
        )
        receipt_path.write_text(
            json.dumps(receipt, separators=(",", ":")) + "\\n", encoding="utf-8"
        )
        receipt_path.chmod(0o600)
    compose_returncodes = {compose_returncodes!r}
    compose_returncode = (
        compose_returncodes[compose_call_index]
        if compose_call_index < len(compose_returncodes)
        else 0
    )
    if compose_returncode == 0:
        if compose_transition.exists():
            second_compose_transition.touch()
        else:
            compose_transition.touch()
    raise SystemExit(compose_returncode)
if "run" not in args:
    raise SystemExit(97)
if args[-1] == "version":
    print({cli_version!r})
    raise SystemExit(0)
record.write_text(json.dumps({{"argv": args, "env": dict(os.environ)}}))
if {child_canary!r}:
    print({child_canary!r}, file=sys.stderr)
if {fail_issuance!r}:
    raise SystemExit(42)
stage = None
for index, value in enumerate(args):
    if value == "--mount" and index + 1 < len(args):
        mount = args[index + 1]
        if "dst=/work" in mount:
            stage = mount.split("src=", 1)[1].split(",dst=", 1)[0]
if stage is None:
    raise SystemExit(98)
stage_path = Path(stage)
shutil.copyfile({str(staged.bundle)!r}, stage_path / "mcp-client.crt")
shutil.copyfile({str(staged.key)!r}, stage_path / "mcp-client.key")
(stage_path / "mcp-client.crt").chmod({staged_cert_mode!r})
(stage_path / "mcp-client.key").chmod(0o600)
""",
        encoding="utf-8",
    )
    docker.chmod(0o700)
    return docker, record


def _write_fake_curl(
    tmp_path: Path,
    expected: TlsFixture,
    *,
    rollback_expected: TlsFixture | None = None,
    expected_pair_sequence: tuple[str, ...] = (),
    responses: tuple[str, ...] = ("200", "200"),
    returncodes: tuple[int, ...] = (0, 0),
    child_canary: str = "",
) -> tuple[Path, Path]:
    assert set(expected_pair_sequence) <= {"new", "old"}
    assert rollback_expected is not None or "old" not in expected_pair_sequence
    new_pair = (expected.bundle.read_bytes(), expected.key.read_bytes())
    old_pair = (
        new_pair
        if rollback_expected is None
        else (rollback_expected.bundle.read_bytes(), rollback_expected.key.read_bytes())
    )
    expected_env = {
        "HOME": pwd.getpwuid(os.getuid()).pw_dir,
        "LC_ALL": "C",
        "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
        "TMPDIR": "/tmp",
    }
    record = tmp_path / "curl-calls.jsonl"
    curl = tmp_path / "fake-curl"
    curl.write_text(
        f"""#!{sys.executable}
import json
import os
import sys
import time
from pathlib import Path

record = Path({str(record)!r})
calls = record.read_text(encoding="utf-8").splitlines() if record.exists() else []
index = len(calls)
# macOS injects this after exec into Python processes; curl does not.
os.environ.pop("__CF_USER_TEXT_ENCODING", None)
args = sys.argv[1:]
expected_env = {expected_env!r}
pair_sequence = {expected_pair_sequence!r}
expected_pairs = {{"new": {new_pair!r}, "old": {old_pair!r}}}
pair = pair_sequence[index] if index < len(pair_sequence) else "new"
expected_cert, expected_key = expected_pairs[pair]


def argument_after(flag: str) -> str:
    index = args.index(flag)
    return args[index + 1]


materials = {{
    "root": Path(argument_after("--cacert")).read_bytes()
    == Path({str(expected.root)!r}).read_bytes(),
    "cert": Path(argument_after("--cert")).read_bytes() == expected_cert,
    "key": Path(argument_after("--key")).read_bytes() == expected_key,
}}
snapshot = record.with_name("snapshot-observations.jsonl")
snapshot_count = (
    len(snapshot.read_text(encoding="utf-8").splitlines()) if snapshot.exists() else 0
)
if index == 0:
    probe_time = time.time_ns()
    record.with_name("first-direct-probe-epoch").write_text(
        f"{{probe_time // 1_000_000_000}}.{{probe_time % 1_000_000_000:09d}}",
        encoding="ascii",
    )
with record.open("a", encoding="utf-8") as handle:
    handle.write(
        json.dumps(
            {{
                "argv": args,
                "env": dict(os.environ),
                "materials": materials,
                "snapshot_count": snapshot_count,
            }}
        )
        + "\\n"
    )
if dict(os.environ) != expected_env or not all(materials.values()):
    raise SystemExit(97)
responses = {responses!r}
returncodes = {returncodes!r}
if snapshot_count == 0 or index >= len(responses) or index >= len(returncodes):
    raise SystemExit(98)
if {child_canary!r}:
    print({child_canary!r}, file=sys.stderr)
sys.stdout.write(responses[index])
raise SystemExit(returncodes[index])
""",
        encoding="utf-8",
    )
    curl.chmod(0o700)
    return curl, record


def _write_blocking_python_after_completion_mark(
    tmp_path: Path,
    entered: Path,
    release: Path,
) -> Path:
    real_python = shutil.which("python3")
    assert real_python
    fake_bin = tmp_path / "blocking-python-bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        f"""#!{sys.executable}
import os
from pathlib import Path
import subprocess
import sys
import time

arguments = sys.argv[1:]
if arguments[:2] == ["-", "mark-completion-emitted"]:
    completed = subprocess.run(
        [{real_python!r}, *arguments],
        input=sys.stdin.buffer.read(),
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    entered = Path({str(entered)!r})
    release = Path({str(release)!r})
    descriptor = os.open(entered, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    deadline = time.monotonic() + 15
    while not release.exists():
        if time.monotonic() >= deadline:
            raise SystemExit(96)
        time.sleep(0.02)
    raise SystemExit(0)
os.execv({real_python!r}, [{real_python!r}, *arguments])
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    return fake_bin


def _rotator_env(fixture: TlsFixture, docker: Path, stage: Path) -> dict[str, str]:
    return {
        **os.environ,
        "AWS_SECRET_ACCESS_KEY": "ambient-env-canary-must-not-leak",
        "MNEMO_SECRETS_DIR": str(fixture.secrets),
        "MCP_CLIENT_ROTATOR_COMPOSE_FILE": str(COMPOSE),
        "MCP_CLIENT_ROTATOR_DOCKER_BIN": str(docker),
        "MCP_CLIENT_ROTATOR_STAGE_DIR": str(stage),
    }


def _write_six_hour_floor_bypass_openssl(tmp_path: Path) -> Path:
    real_openssl = shutil.which("openssl")
    assert real_openssl
    fake_bin = tmp_path / "six-hour-floor-bypass-bin"
    fake_bin.mkdir()
    fake_openssl = fake_bin / "openssl"
    fake_openssl.write_text(
        f"""#!{sys.executable}
import os
import sys

arguments = sys.argv[1:]
if arguments[:1] == ["x509"] and "-checkend" in arguments:
    index = arguments.index("-checkend")
    if arguments[index + 1 : index + 2] == ["21600"]:
        raise SystemExit(0)
if arguments[:1] == ["verify"] and "-attime" in arguments:
    index = arguments.index("-attime")
    arguments = arguments[:index] + arguments[index + 2 :]
os.execv({real_openssl!r}, [{real_openssl!r}, *arguments])
""",
        encoding="utf-8",
    )
    fake_openssl.chmod(0o700)
    return fake_bin


def _write_compose_passwords(
    fixture: TlsFixture,
    *,
    db_password: bytes = VALID_DB_PASSWORD,
    admin_password: bytes = VALID_ADMIN_PASSWORD,
    mode: int = 0o600,
) -> None:
    for name, value in (
        ("kc_db_pw", db_password),
        ("kc_admin_pw", admin_password),
    ):
        path = fixture.secrets / name
        path.write_bytes(value)
        path.chmod(mode)


def _expected_dotenv_bytes(
    db_password: bytes = VALID_DB_PASSWORD,
    admin_password: bytes = VALID_ADMIN_PASSWORD,
) -> bytes:
    return (
        b"KC_DB_PASSWORD='"
        + db_password
        + b"'\nKC_ADMIN_PASSWORD='"
        + admin_password
        + b"'\n"
    )


def _stage_path(fixture: TlsFixture, name: str = "stage") -> Path:
    rotation = fixture.secrets / ".mcp-client-rotation"
    rotation.mkdir(exist_ok=True)
    rotation.chmod(0o700)
    return rotation / name


def _write_dotenv_residue(fixture: TlsFixture) -> tuple[Path, Path]:
    owner_token = FOREIGN_OWNER_TOKEN
    contents = b"foreign-private-data"
    rotation = _stage_path(fixture).parent
    dotenv = rotation / f"compose-env.{owner_token}.tmp"
    dotenv.write_bytes(contents)
    dotenv.chmod(0o600)
    dotenv_stat = os.lstat(dotenv)
    receipt = rotation / DOTENV_RECEIPT_NAME
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "transaction_id": "e" * 32,
                "compose_env": {
                    "schema_version": 1,
                    "state": "ready",
                    "owner_token": owner_token,
                    "basename": dotenv.name,
                    "quarantine_basename": f"compose-env.{owner_token}.quarantine",
                    "device": dotenv_stat.st_dev,
                    "inode": dotenv_stat.st_ino,
                    "uid": os.getuid(),
                    "mode": 0o600,
                    "nlink": 1,
                    "created_at": "2026-01-01T00:00:00Z",
                },
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    receipt.chmod(0o600)
    return dotenv, receipt


@dataclass(frozen=True)
class RotationTransactionFixture:
    current: TlsFixture
    staged: TlsFixture
    env: dict[str, str]
    record: Path
    probe_record: Path
    old_cert: bytes
    old_key: bytes


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _strict_json(path: Path) -> dict[str, object]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    parsed = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
    )
    assert isinstance(parsed, dict)
    return parsed


def _enable_transaction_fixture(
    fixture: TlsFixture,
    *,
    blackbox_running: bool = True,
    operator_running: bool = False,
) -> Path:
    marker = _stage_path(fixture, TRANSACTION_MARKER)
    marker.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "blackbox_exporter_was_running": blackbox_running,
                "compose_file_path": str(COMPOSE.resolve(strict=True)),
                "compose_file_sha256": _sha256_file(COMPOSE),
                "operator_was_running": operator_running,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    marker.chmod(0o600)
    return marker


def _transaction_fixture(
    tmp_path: Path,
    *,
    docker_options: dict[str, object] | None = None,
    curl_options: dict[str, object] | None = None,
    operator_running: bool = False,
    staged_remaining: dt.timedelta = dt.timedelta(hours=24),
) -> RotationTransactionFixture:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8), stem="current")
    _write_compose_passwords(current)
    staged = _tls_fixture(
        tmp_path,
        remaining=staged_remaining,
        stem="staged",
        issuer=current,
    )
    curl, probe_record = _write_fake_curl(
        tmp_path,
        staged,
        rollback_expected=current,
        **(curl_options or {}),
    )
    docker, record = _write_fake_docker(
        tmp_path,
        staged,
        direct_probe_record=probe_record,
        **(docker_options or {}),
    )
    _enable_transaction_fixture(current, operator_running=operator_running)
    return RotationTransactionFixture(
        current=current,
        staged=staged,
        env={
            **_rotator_env(current, docker, _stage_path(current, "transaction-stage")),
            "MCP_CLIENT_ROTATOR_TEST_CURL_BIN": str(curl.resolve(strict=True)),
        },
        record=record,
        probe_record=probe_record,
        old_cert=current.bundle.read_bytes(),
        old_key=current.key.read_bytes(),
    )


def _fault_env(
    env: dict[str, str],
    *,
    interrupt_after: str | None = None,
    interrupt_status: int | None = None,
    fail_fsync: str | None = None,
    fail_validation: str | None = None,
    mutate_generation: str | None = None,
    swap_dotenv_after_validation: bool = False,
) -> dict[str, str]:
    result = dict(env)
    if interrupt_after is not None:
        result["MCP_CLIENT_ROTATOR_TEST_INTERRUPT_AFTER_PHASE"] = interrupt_after
    if interrupt_status is not None:
        result["MCP_CLIENT_ROTATOR_TEST_INTERRUPT_EXIT_STATUS"] = str(interrupt_status)
    if fail_fsync is not None:
        result["MCP_CLIENT_ROTATOR_TEST_FAIL_FSYNC"] = fail_fsync
    if fail_validation is not None:
        result["MCP_CLIENT_ROTATOR_TEST_FAIL_VALIDATION"] = fail_validation
    if mutate_generation is not None:
        result["MCP_CLIENT_ROTATOR_TEST_MUTATE_GENERATION_BEFORE_RENAME"] = (
            mutate_generation
        )
    if swap_dotenv_after_validation:
        result["MCP_CLIENT_ROTATOR_TEST_SWAP_DOTENV_AFTER_VALIDATION"] = "1"
    return result


def _recovery_env(
    tmp_path: Path,
    transaction: RotationTransactionFixture,
    name: str,
    **faults: str,
) -> tuple[dict[str, str], Path]:
    fake_root = tmp_path / name
    fake_root.mkdir()
    docker, record = _write_fake_docker(fake_root, transaction.staged)
    env = _rotator_env(
        transaction.current,
        docker,
        _stage_path(transaction.current, f"{name}-stage"),
    )
    return _fault_env(env, **faults), record


def _journal_path(transaction: RotationTransactionFixture) -> Path:
    return transaction.current.secrets / ".mcp-client-rotation" / TRANSACTION_JOURNAL


def _completion_receipt_path(
    transaction: RotationTransactionFixture,
    transaction_id: str,
    state: str,
) -> Path:
    assert state in {"pending", "emitted"}
    return (
        transaction.current.secrets
        / ".mcp-client-rotation"
        / f"completion.{transaction_id}.{state}.json"
    )


def _completion_result_line(result: str, transaction_id: str) -> str:
    assert result in {"activated", "committed_recovered"}
    assert re.fullmatch(r"[0-9a-f]{32,64}", transaction_id)
    return f"mcp-client-rotation result={result} transaction_id={transaction_id}\n"


def _compose_env_artifact_paths(rotation: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in rotation.iterdir()
            if path.name == DOTENV_RECEIPT_NAME
            or path.name.startswith("compose-env.")
            or path.name.startswith(".compose-env")
        ),
        key=lambda path: path.name,
    )


def _generation_paths(
    transaction: RotationTransactionFixture,
    journal: dict[str, object],
) -> dict[str, Path]:
    rotation = transaction.current.secrets / ".mcp-client-rotation"
    files = [
        path
        for path in rotation.iterdir()
        if path.is_file()
        and not path.is_symlink()
        and path.name not in {TRANSACTION_JOURNAL, TRANSACTION_MARKER}
        and re.fullmatch(
            r"completion[.][0-9a-f]{32,64}[.](?:pending|emitted)[.]json",
            path.name,
        )
        is None
    ]
    result: dict[str, Path] = {}
    for field in (
        "old_cert_sha256",
        "old_key_sha256",
        "new_cert_sha256",
        "new_key_sha256",
    ):
        digest = journal[field]
        assert isinstance(digest, str)
        matches = [path for path in files if _sha256_file(path) == digest]
        assert len(matches) == 1
        result[field] = matches[0]
    return result


def _docker_calls(record: Path) -> list[list[str]]:
    audit = record.with_name("docker-calls.jsonl")
    if not audit.exists():
        return []
    return [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]


def _curl_calls(record: Path) -> list[dict[str, object]]:
    if not record.exists():
        return []
    return [
        json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()
    ]


def _dotenv_observations(record: Path) -> list[dict[str, object]]:
    observations = record.with_name("dotenv-observations.jsonl")
    if not observations.exists():
        return []
    return [
        json.loads(line)
        for line in observations.read_text(encoding="utf-8").splitlines()
    ]


def _snapshot_observations(record: Path) -> list[dict[str, object]]:
    observations = record.with_name("snapshot-observations.jsonl")
    if not observations.exists():
        return []
    return [
        json.loads(line)
        for line in observations.read_text(encoding="utf-8").splitlines()
    ]


def _blackbox_observations(record: Path) -> list[dict[str, object]]:
    observations = record.with_name("blackbox-observations.jsonl")
    if not observations.exists():
        return []
    return [
        json.loads(line)
        for line in observations.read_text(encoding="utf-8").splitlines()
    ]


def _expected_blackbox_observation(
    phase: str,
    query_index: int,
    *,
    direct_probe_count: int,
    snapshot_count: int,
    sample_age_seconds: float | None = 0.0,
    sample_source: str = "relative-age",
) -> dict[str, object]:
    return {
        "direct_probe_count": direct_probe_count,
        "journal_exists": True,
        "journal_phase": phase,
        "query_index": query_index,
        "sample_age_seconds": sample_age_seconds,
        "sample_source": sample_source,
        "snapshot_count": snapshot_count,
    }


def _expected_compose_call(service: str, dotenv: Path) -> list[str]:
    profile = ["--profile", "operator"] if service == "operator" else []
    return [
        "--context",
        "colima",
        "compose",
        "--project-directory",
        str(REPO / "infra"),
        "-p",
        "infra",
        *profile,
        "--env-file",
        str(dotenv),
        "-f",
        str(COMPOSE),
        "up",
        "-d",
        "--no-deps",
        "--no-build",
        "--force-recreate",
        service,
    ]


def _assert_private_dotenv_observation(
    observation: dict[str, object],
    service: str,
    *,
    expected_dotenv: bytes = _expected_dotenv_bytes(),
    expected_phase: str = "activation_started",
) -> tuple[Path, Path]:
    dotenv = Path(str(observation["dotenv_path"]))
    receipt_path = Path(str(observation["receipt_path"]))
    receipt = observation["receipt"]
    journal = observation["journal"]
    assert isinstance(receipt, dict)
    assert isinstance(journal, dict)
    assert set(journal) == TRANSACTION_FIELDS
    assert journal["schema_version"] == 2
    assert journal["phase"] == expected_phase
    compose_env = journal["compose_env"]
    assert isinstance(compose_env, dict)
    assert set(compose_env) == COMPOSE_ENV_FIELDS
    assert compose_env["schema_version"] == 1
    assert compose_env["state"] == "ready"
    assert set(receipt) == DOTENV_RECEIPT_FIELDS
    assert receipt["schema_version"] == 2
    assert receipt["transaction_id"] == journal["transaction_id"]
    assert receipt["compose_env"] == compose_env
    token = compose_env["owner_token"]
    assert isinstance(token, str)
    assert re.fullmatch(r"[0-9a-f]{64}", token)
    assert dotenv.name == f"compose-env.{token}.tmp"
    assert receipt_path == dotenv.parent / DOTENV_RECEIPT_NAME
    assert compose_env["basename"] == dotenv.name
    quarantine_basename = compose_env["quarantine_basename"]
    assert isinstance(quarantine_basename, str)
    assert quarantine_basename != dotenv.name
    assert compose_env["device"] == observation["dotenv_device"]
    assert compose_env["inode"] == observation["dotenv_inode"]
    assert compose_env["uid"] == os.getuid()
    assert compose_env["mode"] == 0o600
    assert compose_env["nlink"] == observation["dotenv_nlink"] == 1
    created_at = compose_env["created_at"]
    assert isinstance(created_at, str)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", created_at)
    assert dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")).tzinfo == dt.UTC
    assert observation["argv"] == _expected_compose_call(service, dotenv)
    assert observation["dotenv_sha256"] == hashlib.sha256(expected_dotenv).hexdigest()
    assert observation["dotenv_size"] == len(expected_dotenv)
    assert observation["dotenv_mode"] == 0o600
    assert observation["dotenv_uid"] == os.getuid()
    assert observation["dotenv_regular"] is True
    assert observation["receipt_nlink"] == 1
    assert observation["receipt_mode"] == 0o600
    assert observation["receipt_regular"] is True
    assert observation["rotation_parent_mode"] == 0o700
    assert observation["rotation_parent_uid"] == os.getuid()
    assert observation["rotation_parent_directory"] is True
    assert observation["env"] == {
        "HOME": pwd.getpwuid(os.getuid()).pw_dir,
        "LC_ALL": "C",
        "MNEMO_SECRETS_DIR": str(dotenv.parent.parent),
        "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
        "TMPDIR": "/tmp",
    }
    assert int(observation["receipt_mtime_ns"]) >= int(observation["dotenv_mtime_ns"])
    assert observation["ambient_canary_present"] is False
    assert not dotenv.is_relative_to(REPO)
    return dotenv, receipt_path


def _assert_completed_rollback(
    transaction: RotationTransactionFixture,
    completed: subprocess.CompletedProcess[str],
    *,
    services: tuple[str, ...],
    phases: tuple[str, ...],
    snapshots: tuple[bytes, ...],
    probe_snapshot_counts: tuple[int, ...],
    blackbox_observations: list[dict[str, object]],
) -> None:
    assert completed.returncode == 75
    assert completed.stdout == "mcp-client-rotation result=rolled_back\n"
    assert completed.stderr == ""
    assert not _journal_path(transaction).exists()
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    rotation = transaction.current.secrets / ".mcp-client-rotation"
    retained_generation_digests = sorted(
        _sha256_file(path)
        for path in rotation.iterdir()
        if path.is_file() and not path.is_symlink() and path.name != TRANSACTION_MARKER
    )
    assert retained_generation_digests == sorted(
        (
            _sha256_bytes(transaction.old_cert),
            _sha256_bytes(transaction.old_key),
            _sha256_file(transaction.staged.bundle),
            _sha256_file(transaction.staged.key),
        )
    )
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == len(services) == len(phases)
    artifacts = [
        _assert_private_dotenv_observation(
            observation,
            service,
            expected_phase=phase,
        )
        for observation, service, phase in zip(
            observations,
            services,
            phases,
            strict=True,
        )
    ]
    assert all(not dotenv.exists() for dotenv, _ in artifacts)
    assert all(not receipt.exists() for _, receipt in artifacts)
    compose_calls = [
        call
        for call in _docker_calls(transaction.record)
        if call[:3] == ["--context", "colima", "compose"] and "up" in call
    ]
    assert [call[-1] for call in compose_calls] == list(services)
    assert [
        observation["payload_hex"]
        for observation in _snapshot_observations(transaction.record)
    ] == [snapshot.hex() for snapshot in snapshots]
    probe_calls = _curl_calls(transaction.probe_record)
    assert [call["snapshot_count"] for call in probe_calls] == list(
        probe_snapshot_counts
    )
    assert all(
        call["materials"] == {"root": True, "cert": True, "key": True}
        for call in probe_calls
    )
    assert all(
        call["env"]
        == {
            "HOME": pwd.getpwuid(os.getuid()).pw_dir,
            "LC_ALL": "C",
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
            "TMPDIR": "/tmp",
        }
        for call in probe_calls
    )
    assert _blackbox_observations(transaction.record) == blackbox_observations
    combined_output = completed.stdout + completed.stderr
    assert VALID_DB_PASSWORD.decode() not in combined_output
    assert VALID_ADMIN_PASSWORD.decode() not in combined_output


def _assert_retained_rollback_failure(
    transaction: RotationTransactionFixture,
    failed: subprocess.CompletedProcess[str],
    *,
    cause: str,
) -> dict[str, object]:
    assert failed.returncode == 74
    assert failed.stdout == "mcp-client-rotation result=rollback_failed\n"
    assert failed.stderr == f"mcp-client-rotation failed: {cause}\n"
    journal = _strict_json(_journal_path(transaction))
    assert journal["phase"] == "rollback_pair_restored"
    assert journal["compose_env"] is None
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert len(_generation_paths(transaction, journal)) == 4
    assert _compose_env_artifact_paths(_journal_path(transaction).parent) == []
    combined_output = failed.stdout + failed.stderr
    assert VALID_DB_PASSWORD.decode() not in combined_output
    assert VALID_ADMIN_PASSWORD.decode() not in combined_output
    return journal


def _run_rotator(
    env: dict[str, str],
    *args: str,
    child_umask: int | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(ROTATOR), *args],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=ROTATOR_TEST_TIMEOUT_SECONDS,
        check=False,
        pass_fds=_runtime_lock_pass_fds(env),
        umask=-1 if child_umask is None else child_umask,
    )
    return completed


def _run_diagnostic(
    fixture: TlsFixture,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "MCP_CLIENT_TLS_HOSTNAME": "hostile-ambient.invalid",
        "MNEMO_SECRETS_DIR": str(fixture.secrets),
    }
    env.update(extra_env or {})
    return subprocess.run(
        [str(DIAGNOSTIC), str(fixture.root), str(fixture.bundle), str(fixture.key)],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )


def _run_validator(fixture: TlsFixture) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(VALIDATOR), str(fixture.root), str(fixture.bundle), str(fixture.key)],
        cwd=REPO,
        env={
            **os.environ,
            "MCP_CLIENT_TLS_HOSTNAME": "mcp-client.mnemo.local",
            "MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS": "21600",
            "MNEMO_SECRETS_DIR": str(fixture.secrets),
        },
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )


def _file_snapshot(path: Path) -> tuple[int, int, int, int, int, bytes]:
    path_stat = os.lstat(path)
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_uid,
        stat.S_IMODE(path_stat.st_mode),
        path_stat.st_nlink,
        path.read_bytes(),
    )


def _assert_canonical_matches_transaction_new_pair(
    transaction: RotationTransactionFixture,
    journal: dict[str, object],
) -> None:
    generations = _generation_paths(transaction, journal)
    assert (
        transaction.current.bundle.read_bytes()
        == generations["new_cert_sha256"].read_bytes()
    )
    assert (
        transaction.current.key.read_bytes()
        == generations["new_key_sha256"].read_bytes()
    )
    assert _run_validator(transaction.current).returncode == 0


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (43_201, "healthy"),
        (43_200, "renewal_due"),
        (21_601, "renewal_due"),
        (21_600, "hard_floor"),
        (7_201, "hard_floor"),
        (7_200, "emergency"),
        (1, "emergency"),
        (0, "emergency"),
        (-1, "expired"),
    ],
)
def test_lifetime_boundaries_use_exact_seconds(seconds: int, expected: str) -> None:
    proc = _run_rotator(os.environ.copy(), "--classify-remaining", str(seconds))

    assert proc.returncode == 0
    assert proc.stdout == f"mcp-client-rotation renewal_state={expected}\n"
    assert proc.stderr == ""


def test_renewal_above_twelve_hours_is_noop_without_docker(tmp_path: Path) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=13))
    stage = tmp_path / "unused-stage"
    env = _rotator_env(current, tmp_path / "missing-docker", stage)

    proc = _run_rotator(env)

    assert proc.returncode == 0
    assert proc.stdout == "mcp-client-rotation result=healthy_noop\n"
    assert proc.stderr == ""
    assert not stage.exists()


def test_healthy_noop_accepts_more_than_128_emitted_completion_receipts(
    tmp_path: Path,
) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=13))
    rotation = _stage_path(current).parent
    expected: dict[Path, bytes] = {}
    for index in range(129):
        transaction_id = f"{index:032x}"
        receipt = rotation / f"completion.{transaction_id}.emitted.json"
        payload = (
            json.dumps(
                {
                    "schema_version": 1,
                    "transaction_id": transaction_id,
                    "result": "activated",
                    "completed_at": "2026-07-14T04:00:00Z",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        receipt.write_bytes(payload)
        receipt.chmod(0o600)
        expected[receipt] = payload
    env = _rotator_env(current, tmp_path / "missing-docker", tmp_path / "unused-stage")

    proc = _run_rotator(env)

    assert proc.returncode == 0
    assert proc.stdout == "mcp-client-rotation result=healthy_noop\n"
    assert proc.stderr == ""
    assert all(path.read_bytes() == payload for path, payload in expected.items())


@pytest.mark.parametrize(
    ("remaining", "expired"),
    [
        (dt.timedelta(hours=8), False),
        (dt.timedelta(hours=5), False),
        (dt.timedelta(hours=1), False),
        (dt.timedelta(), True),
    ],
)
def test_renewal_stages_valid_replacement_with_hardened_exact_argv(
    tmp_path: Path,
    remaining: dt.timedelta,
    expired: bool,
) -> None:
    current = _tls_fixture(
        tmp_path, remaining=remaining, expired=expired, stem="current"
    )
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    docker, record = _write_fake_docker(tmp_path, staged)
    stage = _stage_path(current, "issued-stage")

    env = _real_runtime_lock_env(_rotator_env(current, docker, stage), tmp_path)

    proc = _run_rotator(env)

    owner = (
        Path(env["MNEMO_CUSTODY_DIR"]) / "locks" / "runtime-exclusive" / "owner.json"
    )

    assert proc.returncode == 0, proc.stderr
    assert not owner.exists()
    assert proc.stdout == "mcp-client-rotation result=staged_only\n"
    assert proc.stderr == ""
    payload = json.loads(record.read_text(encoding="utf-8"))
    argv = payload["argv"]
    assert argv == [
        "--context",
        "colima",
        "run",
        "--rm",
        "--pull",
        "never",
        "--read-only",
        "--user",
        "1000:1000",
        "--pids-limit",
        "64",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--network",
        "infra_internal",
        "--entrypoint",
        "/usr/local/bin/step",
        "--mount",
        f"type=bind,src={current.root},dst=/run/mnemo/root.crt,readonly",
        "--mount",
        (
            f"type=bind,src={current.password},"
            "dst=/run/mnemo/provisioner-password,readonly"
        ),
        "--mount",
        f"type=bind,src={stage},dst=/work",
        IMAGE,
        "ca",
        "certificate",
        "--ca-url",
        "https://ca.mnemo.local:9000",
        "--root",
        "/run/mnemo/root.crt",
        "--provisioner",
        "admin",
        "--provisioner-password-file",
        "/run/mnemo/provisioner-password",
        "--san",
        "mcp-client.mnemo.local",
        "--not-after",
        "24h",
        "mcp-client.mnemo.local",
        "/work/mcp-client.crt",
        "/work/mcp-client.key",
    ]
    output = proc.stdout + proc.stderr + json.dumps(payload)
    assert "provisioner-canary-must-never-leak" not in output
    assert "ambient-env-canary-must-not-leak" not in output
    assert set(payload["env"]) <= {"HOME", "LC_ALL", "PATH", "TMPDIR"}


def test_issuance_failure_redacts_child_output_and_uses_fixed_exit(
    tmp_path: Path,
) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8))
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    child_canary = "child-output-canary-must-not-leak"
    docker, _ = _write_fake_docker(
        tmp_path, staged, fail_issuance=True, child_canary=child_canary
    )

    proc = _run_rotator(
        _rotator_env(current, docker, _stage_path(current, "failed-issuance-stage"))
    )

    assert proc.returncode == 70
    assert proc.stdout == "mcp-client-rotation result=issuance_failed\n"
    assert proc.stderr == "mcp-client-rotation failed: staged issuance failed\n"
    assert child_canary not in proc.stdout + proc.stderr


def test_preflight_missing_docker_is_runtime_unavailable(tmp_path: Path) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8))

    proc = _run_rotator(
        _rotator_env(
            current,
            tmp_path / "missing-docker",
            _stage_path(current),
        )
    )

    assert proc.returncode == 69
    assert proc.stdout == "mcp-client-rotation result=runtime_unavailable\n"
    assert proc.stderr == "mcp-client-rotation failed: Docker is unavailable\n"


@pytest.mark.parametrize(
    ("context", "network_project", "image_present", "cli_version"),
    [
        ("desktop-linux", "infra", True, "Smallstep CLI/0.28.7"),
        ("colima", "foreign", True, "Smallstep CLI/0.28.7"),
        ("colima", "infra", False, "Smallstep CLI/0.28.7"),
        ("colima", "infra", True, "Smallstep CLI/0.28.6"),
    ],
    ids=["ambient-context", "foreign-network", "missing-image", "wrong-cli"],
)
def test_preflight_rejects_untrusted_docker_runtime_without_issuance(
    tmp_path: Path,
    context: str,
    network_project: str,
    image_present: bool,
    cli_version: str,
) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8))
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    docker, record = _write_fake_docker(
        tmp_path,
        staged,
        context=context,
        network_project=network_project,
        image_present=image_present,
        cli_version=cli_version,
    )

    proc = _run_rotator(_rotator_env(current, docker, _stage_path(current)))

    assert proc.returncode == 65
    assert proc.stdout == "mcp-client-rotation result=preflight_failed\n"
    assert not record.exists()


@pytest.mark.parametrize("remaining", [dt.timedelta(hours=5), dt.timedelta(hours=1)])
def test_renewal_rotation_diagnostic_accepts_only_near_expiry_source(
    tmp_path: Path, remaining: dt.timedelta
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=remaining)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "production MCP client TLS rotation source verified\n"
    assert proc.stderr == ""


def test_renewal_rotation_diagnostic_accepts_structurally_valid_expired_source(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, expired=True)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 0, proc.stderr


def test_renewal_rotation_diagnostic_rejects_source_normal_validator_accepts(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8))

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert "normal validator still accepts source pair" in proc.stderr


def test_preflight_rotation_diagnostic_rejects_non_leaf_horizon_failure(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=13),
        intermediate_remaining=dt.timedelta(hours=5),
    )

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


@pytest.mark.parametrize(
    ("intermediate_remaining", "intermediate_starts_in", "leaf_started"),
    [
        (
            dt.timedelta(minutes=-30),
            dt.timedelta(days=-2),
            dt.timedelta(hours=-2),
        ),
        (
            dt.timedelta(hours=4),
            dt.timedelta(minutes=30),
            dt.timedelta(minutes=-1),
        ),
    ],
    ids=["expired-intermediate", "future-intermediate"],
)
def test_preflight_rotation_diagnostic_requires_current_chain_for_live_leaf(
    tmp_path: Path,
    intermediate_remaining: dt.timedelta,
    intermediate_starts_in: dt.timedelta,
    leaf_started: dt.timedelta,
) -> None:
    fixture = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=5),
        intermediate_remaining=intermediate_remaining,
        intermediate_starts_in=intermediate_starts_in,
        leaf_started=leaf_started,
    )

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_requires_checkend_capability(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    real_openssl = shutil.which("openssl")
    assert real_openssl
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_openssl = fake_bin / "openssl"
    fake_openssl.write_text(
        f"""#!{sys.executable}
import os
import sys

if sys.argv[1:] == ["x509", "-help"]:
    print("x509 help without required capability", file=sys.stderr)
    raise SystemExit(0)
os.execv({real_openssl!r}, [{real_openssl!r}, *sys.argv[1:]])
""",
        encoding="utf-8",
    )
    fake_openssl.chmod(0o700)

    proc = _run_diagnostic(
        fixture,
        extra_env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_copied_source_paths(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    outside = tmp_path / "outside"
    outside.mkdir()
    copied_bundle = outside / fixture.bundle.name
    copied_key = outside / fixture.key.name
    shutil.copyfile(fixture.bundle, copied_bundle)
    shutil.copyfile(fixture.key, copied_key)
    copied_key.chmod(0o600)

    proc = subprocess.run(
        [str(DIAGNOSTIC), str(fixture.root), str(copied_bundle), str(copied_key)],
        cwd=REPO,
        env={**os.environ, "MNEMO_SECRETS_DIR": str(fixture.secrets)},
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )

    assert proc.returncode == 65
    assert proc.stdout == ""


@pytest.mark.parametrize("case", ["wrong-key", "malformed-chain", "encrypted"])
def test_preflight_rotation_diagnostic_rejects_non_time_failures(
    tmp_path: Path, case: str
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    if case == "wrong-key":
        other = ec.generate_private_key(ec.SECP256R1())
        fixture.key.write_bytes(
            other.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    elif case == "malformed-chain":
        leaf = x509.load_pem_x509_certificate(fixture.bundle.read_bytes())
        fixture.bundle.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    else:
        private_key = serialization.load_pem_private_key(
            fixture.key.read_bytes(), password=None
        )
        fixture.key.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(b"encrypted-canary"),
            )
        )
    fixture.key.chmod(0o600)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_wrong_root_only(tmp_path: Path) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    wrong_root = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=1),
        stem="wrong-root",
    )
    fixture.root.write_bytes(wrong_root.root.read_bytes())

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_wrong_eku_only(tmp_path: Path) -> None:
    fixture = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=1),
        eku=ExtendedKeyUsageOID.SERVER_AUTH,
    )

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_unsafe_key_mode(tmp_path: Path) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    fixture.key.chmod(0o644)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_final_key_symlink(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    target = fixture.secrets / "mcp-client-real.key"
    fixture.key.rename(target)
    fixture.key.symlink_to(target.name)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_not_yet_valid_source(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, not_yet_valid=True)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert "source certificate is not yet valid" in proc.stderr


def test_preflight_rotation_diagnostic_rejects_symlinked_parent(tmp_path: Path) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    linked = tmp_path / "linked-secrets"
    linked.symlink_to(fixture.secrets, target_is_directory=True)
    linked_fixture = TlsFixture(
        linked,
        linked / fixture.root.name,
        linked / fixture.bundle.name,
        linked / fixture.key.name,
        linked / fixture.password.name,
        fixture.root_key,
        fixture.root_cert,
        fixture.intermediate_key,
        fixture.intermediate_cert,
    )

    proc = _run_diagnostic(linked_fixture)

    assert proc.returncode == 65
    assert "path components must not be symlinks" in proc.stderr


def test_preflight_staged_validator_failure_is_issuance_failure(tmp_path: Path) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8), stem="current")
    invalid = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=1),
        stem="invalid-stage",
        issuer=current,
    )
    docker, _ = _write_fake_docker(tmp_path, invalid)

    proc = _run_rotator(_rotator_env(current, docker, _stage_path(current)))

    assert proc.returncode == 70
    assert proc.stdout == "mcp-client-rotation result=issuance_failed\n"
    assert proc.stderr == "mcp-client-rotation failed: staged validation failed\n"


def test_preflight_staged_certificate_unsafe_mode_is_issuance_failure(
    tmp_path: Path,
) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8), stem="current")
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    docker, _ = _write_fake_docker(tmp_path, staged, staged_cert_mode=0o666)

    proc = _run_rotator(_rotator_env(current, docker, _stage_path(current)))

    assert proc.returncode == 70
    assert proc.stdout == "mcp-client-rotation result=issuance_failed\n"
    assert proc.stderr == "mcp-client-rotation failed: staged validation failed\n"


def test_preflight_stage_must_be_inside_canonical_rotation_directory(
    tmp_path: Path,
) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8), stem="current")
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    docker, record = _write_fake_docker(tmp_path, staged)

    proc = _run_rotator(_rotator_env(current, docker, tmp_path / "outside-stage"))

    assert proc.returncode == 65
    assert proc.stdout == "mcp-client-rotation result=preflight_failed\n"
    assert not record.exists()


def test_preflight_existing_stage_is_never_overwritten(tmp_path: Path) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8))
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    docker, record = _write_fake_docker(tmp_path, staged)
    stage = _stage_path(current, "existing-stage")
    stage.mkdir()
    sentinel = stage / "sentinel"
    sentinel.write_text("owned", encoding="utf-8")

    proc = _run_rotator(_rotator_env(current, docker, stage))

    assert proc.returncode == 65
    assert proc.stdout == "mcp-client-rotation result=preflight_failed\n"
    assert sentinel.read_text(encoding="utf-8") == "owned"
    assert not record.exists()


def test_preflight_validator_source_is_unchanged() -> None:
    validator = REPO / "infra" / "validate" / "validate-production-mcp-client-tls.sh"
    assert shutil.which("openssl")
    assert "may not weaken the 21600-second floor" in validator.read_text(
        encoding="utf-8"
    )


def test_publish_journal_precedes_first_rename_and_is_strict_secret_free(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        curl_options={
            "expected_pair_sequence": ("old", "old"),
            "responses": ("204", "299"),
            "returncodes": (0, 0),
        },
    )

    proc = _run_rotator(
        _fault_env(transaction.env, interrupt_after="prepared"),
        TRANSACTION_ACTION,
    )

    assert proc.returncode != 0
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    raw_journal = journal_path.read_text(encoding="utf-8")
    assert len(raw_journal.encode()) <= 4096
    assert journal_path.stat().st_mode & 0o777 == 0o600
    assert journal_path.parent.stat().st_mode & 0o777 == 0o700
    assert set(journal) == TRANSACTION_FIELDS
    assert journal["schema_version"] == 2
    assert journal["phase"] == "prepared"
    assert journal["compose_env"] is None
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    assert re.fullmatch(r"[0-9a-f]{32,64}", transaction_id)
    created_at = journal["created_at"]
    assert isinstance(created_at, str) and len(created_at) <= 32
    assert created_at.endswith("Z")
    assert dt.datetime.fromisoformat(created_at.removesuffix("Z") + "+00:00")
    assert journal["blackbox_exporter_was_running"] is True
    assert journal["operator_was_running"] is False
    assert journal["old_cert_sha256"] == _sha256_bytes(transaction.old_cert)
    assert journal["old_key_sha256"] == _sha256_bytes(transaction.old_key)
    assert journal["new_cert_sha256"] == _sha256_file(transaction.staged.bundle)
    assert journal["new_key_sha256"] == _sha256_file(transaction.staged.key)
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    for secret in (
        str(transaction.current.secrets),
        transaction.current.password.read_text(encoding="utf-8").strip(),
        "ambient-env-canary-must-not-leak",
        "BEGIN CERTIFICATE",
        "BEGIN PRIVATE KEY",
    ):
        assert secret not in raw_journal
    generations = _generation_paths(transaction, journal)
    assert len(set(generations.values())) == 4
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in generations.values())


def test_publish_fixture_seam_requires_explicit_action_and_safe_marker(
    tmp_path: Path,
) -> None:
    unsafe = _transaction_fixture(tmp_path / "unsafe")
    marker = _stage_path(unsafe.current, TRANSACTION_MARKER)
    marker.chmod(0o644)

    rejected = _run_rotator(unsafe.env, TRANSACTION_ACTION)

    assert rejected.returncode == 65
    assert rejected.stdout == "mcp-client-rotation result=preflight_failed\n"
    assert not _journal_path(unsafe).exists()
    assert unsafe.current.bundle.read_bytes() == unsafe.old_cert
    assert unsafe.current.key.read_bytes() == unsafe.old_key

    default = _transaction_fixture(tmp_path / "default")
    staged_only = _run_rotator(default.env)

    assert staged_only.returncode == 0
    assert staged_only.stdout == "mcp-client-rotation result=staged_only\n"
    assert not _journal_path(default).exists()
    assert default.current.bundle.read_bytes() == default.old_cert
    assert default.current.key.read_bytes() == default.old_key


def test_publish_fixture_seam_ignores_ambient_tmpdir_override(
    tmp_path: Path,
) -> None:
    outside = (
        REPO
        / ".superpowers"
        / "sdd"
        / f"r1b-untrusted-temp-{os.getpid()}-{tmp_path.name}"
    )
    shutil.rmtree(outside, ignore_errors=True)
    try:
        transaction = _transaction_fixture(outside)
        env = dict(transaction.env)
        env["TMPDIR"] = str(transaction.current.secrets)

        rejected = _run_rotator(env, TRANSACTION_ACTION)

        assert rejected.returncode == 65
        assert rejected.stdout == "mcp-client-rotation result=preflight_failed\n"
        assert not _journal_path(transaction).exists()
        assert transaction.current.bundle.read_bytes() == transaction.old_cert
        assert transaction.current.key.read_bytes() == transaction.old_key
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def test_publish_fixture_seam_accepts_bounded_context_mode_pytest_root(
    tmp_path: Path,
) -> None:
    pytest_owner = next(
        parent for parent in tmp_path.parents if parent.name.startswith("pytest-of-")
    )
    temp_root = (
        pytest_owner.parent.parent
        if pytest_owner.parent.name.startswith(".ctx-mode-")
        else pytest_owner.parent
    )
    context_root = temp_root / f".ctx-mode-r1b-{os.getpid()}"
    fixture_root = context_root / pytest_owner.name / "pytest-0" / "fixture"
    shutil.rmtree(context_root, ignore_errors=True)
    try:
        transaction = _transaction_fixture(fixture_root)

        completed = _run_rotator(transaction.env, TRANSACTION_ACTION)

        assert completed.returncode == 0
        assert not _journal_path(transaction).exists()
        journal = _dotenv_observations(transaction.record)[0]["journal"]
        assert isinstance(journal, dict)
        transaction_id = journal["transaction_id"]
        assert isinstance(transaction_id, str)
        assert completed.stdout == _completion_result_line("activated", transaction_id)
        receipt = _strict_json(
            _completion_receipt_path(transaction, transaction_id, "emitted")
        )
        assert receipt["result"] == "activated"
    finally:
        shutil.rmtree(context_root, ignore_errors=True)


@pytest.mark.parametrize(
    ("interrupt_after", "expected_phase", "expected_cert", "expected_key"),
    [
        ("certificate_renamed", "prepared", "new", "old"),
        ("certificate_parent_fsynced", "prepared", "new", "old"),
        ("certificate_published", "certificate_published", "new", "old"),
        ("key_renamed", "certificate_published", "new", "new"),
        ("key_parent_fsynced", "certificate_published", "new", "new"),
        ("pair_published", "pair_published", "new", "new"),
    ],
)
def test_publish_interrupt_recovers_before_source_validation_and_retains_generations(
    tmp_path: Path,
    interrupt_after: str,
    expected_phase: str,
    expected_cert: str,
    expected_key: str,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after=interrupt_after),
        TRANSACTION_ACTION,
    )

    assert interrupted.returncode != 0
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == expected_phase
    expected_cert_bytes = (
        transaction.staged.bundle.read_bytes()
        if expected_cert == "new"
        else transaction.old_cert
    )
    expected_key_bytes = (
        transaction.staged.key.read_bytes()
        if expected_key == "new"
        else transaction.old_key
    )
    assert transaction.current.bundle.read_bytes() == expected_cert_bytes
    assert transaction.current.key.read_bytes() == expected_key_bytes
    generations = _generation_paths(transaction, journal)

    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        "recovery",
    )
    recovered = _run_rotator(recovery_env)

    assert recovered.returncode == 0
    assert recovered.stdout == "mcp-client-rotation result=staged_only\n"
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert not journal_path.exists()
    assert all(path.exists() for path in generations.values())
    assert not any(
        set(call) & {"up", "restart", "recreate", "operator", "blackbox-exporter"}
        for call in _docker_calls(recovery_record)
    )


@pytest.mark.parametrize(
    ("interrupt_after", "expected_phase", "expected_key"),
    [
        ("old_certificate_restored", "restoring_certificate", "new"),
        ("old_certificate_parent_fsynced", "restoring_certificate", "new"),
        ("old_key_restored", "restoring_key", "old"),
        ("old_key_parent_fsynced", "restoring_key", "old"),
    ],
)
def test_recovery_interrupt_immediately_after_rename_is_resumable(
    tmp_path: Path,
    interrupt_after: str,
    expected_phase: str,
    expected_key: str,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    first_interrupt = _run_rotator(
        _fault_env(transaction.env, interrupt_after="pair_published"),
        TRANSACTION_ACTION,
    )
    assert first_interrupt.returncode != 0

    recovery_env, _ = _recovery_env(
        tmp_path,
        transaction,
        "rename-recovery",
        interrupt_after=interrupt_after,
    )
    rename_interrupt = _run_rotator(recovery_env)

    assert rename_interrupt.returncode != 0
    assert _strict_json(_journal_path(transaction))["phase"] == expected_phase
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    expected_key_bytes = (
        transaction.staged.key.read_bytes()
        if expected_key == "new"
        else transaction.old_key
    )
    assert transaction.current.key.read_bytes() == expected_key_bytes

    resumed_env, _ = _recovery_env(tmp_path, transaction, "rename-resumed")
    resumed = _run_rotator(resumed_env)

    assert resumed.returncode == 0
    assert resumed.stdout == "mcp-client-rotation result=staged_only\n"
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert not _journal_path(transaction).exists()


def test_recovery_intent_is_durable_before_first_restore_rename(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    first_interrupt = _run_rotator(
        _fault_env(transaction.env, interrupt_after="pair_published"),
        TRANSACTION_ACTION,
    )
    assert first_interrupt.returncode != 0

    recovery_env, _ = _recovery_env(
        tmp_path,
        transaction,
        "intent-recovery",
        interrupt_after="restoring_certificate",
    )
    intent_interrupt = _run_rotator(recovery_env)

    assert intent_interrupt.returncode != 0
    assert _strict_json(_journal_path(transaction))["phase"] == "restoring_certificate"
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()

    resumed_env, _ = _recovery_env(tmp_path, transaction, "intent-resumed")
    resumed = _run_rotator(resumed_env)

    assert resumed.returncode == 0
    assert resumed.stdout == "mcp-client-rotation result=staged_only\n"
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert not _journal_path(transaction).exists()


def test_recovery_absence_preserves_missing_secret_root_preflight_result(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-secrets"
    env = {
        **os.environ,
        "MNEMO_SECRETS_DIR": str(missing),
        "MCP_CLIENT_ROTATOR_COMPOSE_FILE": str(COMPOSE),
        "MCP_CLIENT_ROTATOR_DOCKER_BIN": str(tmp_path / "missing-docker"),
        "MCP_CLIENT_ROTATOR_STAGE_DIR": str(missing / ".mcp-client-rotation/stage"),
    }

    proc = _run_rotator(env)

    assert proc.returncode == 65
    assert proc.stdout == "mcp-client-rotation result=preflight_failed\n"
    assert "source certificate" in proc.stderr


def test_recovery_interrupt_after_certificate_restore_is_resumable(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    first_interrupt = _run_rotator(
        _fault_env(transaction.env, interrupt_after="pair_published"),
        TRANSACTION_ACTION,
    )
    assert first_interrupt.returncode != 0

    recovery_env, _ = _recovery_env(
        tmp_path,
        transaction,
        "first-recovery",
        interrupt_after="restoring_key",
    )
    second_interrupt = _run_rotator(recovery_env)

    assert second_interrupt.returncode != 0
    assert _strict_json(_journal_path(transaction))["phase"] == "restoring_key"
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()

    resumed_env, _ = _recovery_env(tmp_path, transaction, "resumed-recovery")
    resumed = _run_rotator(resumed_env)

    assert resumed.returncode == 0
    assert resumed.stdout == "mcp-client-rotation result=staged_only\n"
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert not _journal_path(transaction).exists()


@pytest.mark.parametrize(
    "corruption",
    [
        "malformed",
        "duplicate",
        "unknown",
        "oversized",
        "unsafe_mode",
        "symlink",
        "generation_mismatch",
        "canonical_mismatch",
        "prepared_old_new",
        "pair_published_new_old",
        "activation_started_old_old",
        "activation_started_new_old",
        "activation_started_old_new",
        "committed_old_old",
        "committed_new_old",
        "committed_old_new",
        "old_pair_restored_old_new",
        "rollback_restoring_certificate_old_old",
        "rollback_restoring_key_new_new",
        "rollback_pair_restored_new_new",
    ],
)
def test_recovery_rejects_malformed_unsafe_or_digest_mismatched_evidence(
    tmp_path: Path,
    corruption: str,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    prepared = _run_rotator(
        _fault_env(transaction.env, interrupt_after="prepared"),
        TRANSACTION_ACTION,
    )
    assert prepared.returncode != 0
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    generation_paths = list(_generation_paths(transaction, journal).values())
    raw_journal = journal_path.read_text(encoding="utf-8").rstrip()
    if corruption == "malformed":
        journal_path.write_text("{", encoding="utf-8")
    elif corruption == "duplicate":
        journal_path.write_text(
            raw_journal[:-1] + ',"phase":"pair_published"}',
            encoding="utf-8",
        )
    elif corruption == "unknown":
        journal_path.write_text(
            raw_journal[:-1] + ',"unexpected":"value"}',
            encoding="utf-8",
        )
    elif corruption == "oversized":
        journal_path.write_text(
            raw_journal[:-1] + ',"padding":"' + ("x" * 4096) + '"}',
            encoding="utf-8",
        )
    elif corruption == "unsafe_mode":
        journal_path.chmod(0o644)
    elif corruption == "symlink":
        backing = journal_path.with_name("journal-backing.json")
        journal_path.rename(backing)
        journal_path.symlink_to(backing.name)
    elif corruption == "generation_mismatch":
        generation = _generation_paths(transaction, journal)["old_cert_sha256"]
        generation.write_bytes(generation.read_bytes() + b"corruption")
    elif corruption == "canonical_mismatch":
        transaction.current.bundle.write_bytes(b"unrelated-corruption")
    elif corruption == "prepared_old_new":
        transaction.current.key.write_bytes(transaction.staged.key.read_bytes())
    elif corruption == "pair_published_new_old":
        journal_path.write_text(
            json.dumps({**journal, "phase": "pair_published"}, separators=(",", ":")),
            encoding="utf-8",
        )
        transaction.current.bundle.write_bytes(transaction.staged.bundle.read_bytes())
    elif corruption in {"activation_started_old_old", "committed_old_old"}:
        journal_path.write_text(
            json.dumps(
                {**journal, "phase": corruption.removesuffix("_old_old")},
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    elif corruption in {"activation_started_new_old", "committed_new_old"}:
        journal_path.write_text(
            json.dumps(
                {**journal, "phase": corruption.removesuffix("_new_old")},
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        transaction.current.bundle.write_bytes(transaction.staged.bundle.read_bytes())
    elif corruption in {"activation_started_old_new", "committed_old_new"}:
        journal_path.write_text(
            json.dumps(
                {**journal, "phase": corruption.removesuffix("_old_new")},
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        transaction.current.key.write_bytes(transaction.staged.key.read_bytes())
    elif corruption == "old_pair_restored_old_new":
        journal_path.write_text(
            json.dumps(
                {**journal, "phase": "old_pair_restored"}, separators=(",", ":")
            ),
            encoding="utf-8",
        )
        transaction.current.key.write_bytes(transaction.staged.key.read_bytes())
    elif corruption == "rollback_restoring_certificate_old_old":
        journal_path.write_text(
            json.dumps(
                {**journal, "phase": "rollback_restoring_certificate"},
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    elif corruption in {
        "rollback_restoring_key_new_new",
        "rollback_pair_restored_new_new",
    }:
        journal_path.write_text(
            json.dumps(
                {
                    **journal,
                    "phase": corruption.removesuffix("_new_new"),
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        transaction.current.bundle.write_bytes(transaction.staged.bundle.read_bytes())
        transaction.current.key.write_bytes(transaction.staged.key.read_bytes())
    canonical_cert = transaction.current.bundle.read_bytes()
    canonical_key = transaction.current.key.read_bytes()
    journal_bytes = journal_path.read_bytes()
    generation_bytes = {path: path.read_bytes() for path in generation_paths}

    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        "rejected-recovery",
    )
    rejected = _run_rotator(recovery_env)

    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert os.path.lexists(journal_path)
    assert journal_path.read_bytes() == journal_bytes
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_paths)
    assert transaction.current.bundle.read_bytes() == canonical_cert
    assert transaction.current.key.read_bytes() == canonical_key
    assert _docker_calls(recovery_record) == []


@pytest.mark.parametrize(
    ("fail_fsync", "fail_validation", "phase", "expected_cert", "expected_key"),
    [
        ("journal-parent", None, "prepared", "old", "old"),
        ("certificate-parent", None, "prepared", "new", "old"),
        ("key-parent", None, "certificate_published", "new", "new"),
        (None, "published", "pair_published", "new", "new"),
    ],
)
def test_publish_fsync_or_validation_failure_retains_evidence_without_consumers(
    tmp_path: Path,
    fail_fsync: str | None,
    fail_validation: str | None,
    phase: str,
    expected_cert: str,
    expected_key: str,
) -> None:
    transaction = _transaction_fixture(tmp_path)

    failed = _run_rotator(
        _fault_env(
            transaction.env,
            fail_fsync=fail_fsync,
            fail_validation=fail_validation,
        ),
        TRANSACTION_ACTION,
    )

    assert failed.returncode == 74
    assert failed.stdout == "mcp-client-rotation result=publication_failed\n"
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == phase
    expected_cert_bytes = (
        transaction.staged.bundle.read_bytes()
        if expected_cert == "new"
        else transaction.old_cert
    )
    expected_key_bytes = (
        transaction.staged.key.read_bytes()
        if expected_key == "new"
        else transaction.old_key
    )
    assert transaction.current.bundle.read_bytes() == expected_cert_bytes
    assert transaction.current.key.read_bytes() == expected_key_bytes
    assert all(
        path.exists() for path in _generation_paths(transaction, journal).values()
    )
    assert "committed" not in journal_path.read_text(encoding="utf-8")
    assert "activated" not in failed.stdout
    assert not any(
        set(call) & {"up", "restart", "recreate", "operator", "blackbox-exporter"}
        for call in _docker_calls(transaction.record)
    )


@pytest.mark.parametrize(
    "mutate_generation",
    ["old_cert", "old_key", "new_cert", "new_key"],
)
def test_publish_rebinds_every_generation_digest_before_canonical_rename(
    tmp_path: Path,
    mutate_generation: str,
) -> None:
    transaction = _transaction_fixture(tmp_path)

    failed = _run_rotator(
        _fault_env(transaction.env, mutate_generation=mutate_generation),
        TRANSACTION_ACTION,
    )

    assert failed.returncode == 74
    assert failed.stdout == "mcp-client-rotation result=publication_failed\n"
    journal_path = _journal_path(transaction)
    assert _strict_json(journal_path)["phase"] == "prepared"
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert not any(
        set(call) & {"up", "restart", "recreate", "operator", "blackbox-exporter"}
        for call in _docker_calls(transaction.record)
    )


def test_ambiguous_published_validated_resume_fails_closed_without_consumer_work(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(tmp_path)

    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after="published_validated"),
        TRANSACTION_ACTION,
    )

    assert interrupted.returncode == 86
    assert interrupted.stdout == ""
    assert interrupted.stderr == ""
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == "published_validated"
    assert journal["compose_env"] is None
    generations = _generation_paths(transaction, journal)
    journal_bytes = journal_path.read_bytes()
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    assert _dotenv_observations(transaction.record) == []
    assert _curl_calls(transaction.probe_record) == []
    assert not any(
        call[:3] == ["--context", "colima", "compose"] and "up" in call
        for call in _docker_calls(transaction.record)
    )

    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        "published-validated-recovery",
    )
    recovered = _run_rotator(recovery_env)

    assert recovered.returncode == 74
    assert recovered.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert recovered.stderr == (
        "mcp-client-rotation failed: published transaction requires verified "
        "runtime recovery\n"
    )
    assert journal_path.read_bytes() == journal_bytes
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_bytes)
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    assert _docker_calls(recovery_record) == []


@pytest.mark.parametrize(
    "phase",
    ["pair_published", "published_validated", "activation_started", "committed"],
)
def test_transition_signal_style_status_propagates_without_terminal_result(
    tmp_path: Path,
    phase: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={"responses": ("204", "299")},
    )

    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after=phase,
            interrupt_status=143,
        ),
        TRANSACTION_ACTION,
    )

    assert interrupted.returncode == 143
    assert interrupted.stdout == ""
    assert interrupted.stderr == ""
    journal = _strict_json(_journal_path(transaction))
    assert journal["phase"] == phase
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()


def test_activation_started_resumes_verified_rollback_without_reissuing(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        curl_options={
            "expected_pair_sequence": ("old", "old"),
            "responses": ("204", "299"),
            "returncodes": (0, 0),
        },
    )

    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after="activation_started"),
        TRANSACTION_ACTION,
    )

    assert interrupted.returncode == 86
    assert interrupted.stdout == ""
    assert interrupted.stderr == ""
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == "activation_started"
    assert journal["compose_env"] is None
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    generations = _generation_paths(transaction, journal)
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    assert _dotenv_observations(transaction.record) == []
    assert _curl_calls(transaction.probe_record) == []
    assert not any(
        call[:3] == ["--context", "colima", "compose"] and "up" in call
        for call in _docker_calls(transaction.record)
    )
    assert not any(
        call in _blackbox_probe_calls() for call in _docker_calls(transaction.record)
    )

    issuance_calls = [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ]
    assert len(issuance_calls) == 1
    recovered = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert recovered.stderr == ""
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_bytes)
    assert [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ] == issuance_calls
    _assert_completed_rollback(
        transaction,
        recovered,
        services=("blackbox-exporter",),
        phases=("rollback_pair_restored",),
        snapshots=(
            _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")),
        ),
        probe_snapshot_counts=(1, 1),
        blackbox_observations=[
            _expected_blackbox_observation(
                "rollback_pair_restored",
                0,
                direct_probe_count=2,
                snapshot_count=1,
            )
        ],
    )


def test_activation_transition_parent_fsync_failure_recovers_by_visible_phase(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        curl_options={"expected_pair_sequence": ("old", "old")},
    )

    rolled_back = _run_rotator(
        _fault_env(
            transaction.env,
            fail_fsync="activation-journal-parent",
        ),
        TRANSACTION_ACTION,
    )

    _assert_completed_rollback(
        transaction,
        rolled_back,
        services=("blackbox-exporter",),
        phases=("rollback_pair_restored",),
        snapshots=(
            _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")),
        ),
        probe_snapshot_counts=(1, 1),
        blackbox_observations=[
            _expected_blackbox_observation(
                "rollback_pair_restored",
                0,
                direct_probe_count=2,
                snapshot_count=1,
            )
        ],
    )


def test_fixture_finalizes_activation_with_private_emitted_receipt(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "blackbox_sample_at_first_direct_probe": True,
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={"responses": ("204", "299")},
    )

    completed = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert completed.returncode == 0
    assert completed.stdout.count("mcp-client-rotation result=") == 1
    assert completed.stderr == ""
    journal_path = _journal_path(transaction)
    assert not journal_path.exists()
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    observations = _dotenv_observations(transaction.record)
    assert [str(observation["argv"][-1]) for observation in observations] == [
        "blackbox-exporter"
    ]
    journal = observations[0]["journal"]
    assert isinstance(journal, dict)
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    assert completed.stdout == _completion_result_line("activated", transaction_id)
    generations = _generation_paths(transaction, journal)
    assert len(generations) == 4
    assert all(path.exists() for path in generations.values())
    emitted_receipt = _completion_receipt_path(transaction, transaction_id, "emitted")
    pending_receipt = _completion_receipt_path(transaction, transaction_id, "pending")
    assert emitted_receipt.is_file()
    assert not emitted_receipt.is_symlink()
    receipt_stat = os.lstat(emitted_receipt)
    assert receipt_stat.st_uid == os.getuid()
    assert receipt_stat.st_mode & 0o777 == 0o600
    assert receipt_stat.st_nlink == 1
    receipt = _strict_json(emitted_receipt)
    assert set(receipt) == COMPLETION_RECEIPT_FIELDS
    assert receipt["schema_version"] == 1
    assert receipt["transaction_id"] == transaction_id
    assert receipt["result"] == "activated"
    completed_at = receipt["completed_at"]
    assert isinstance(completed_at, str) and completed_at.endswith("Z")
    dt.datetime.fromisoformat(completed_at[:-1] + "+00:00")
    assert not pending_receipt.exists()
    dotenv, receipt = _assert_private_dotenv_observation(
        observations[0], "blackbox-exporter"
    )
    assert _snapshot_observations(transaction.record) == [
        {
            "dotenv_exists": False,
            "dotenv_path": str(dotenv),
            "payload_hex": _consumer_snapshot_bytes(
                (RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter")
            ).hex(),
            "receipt_exists": False,
            "receipt_path": str(receipt),
        }
    ]
    assert _curl_calls(transaction.probe_record) == [
        {
            "argv": _direct_probe_call(transaction.current, "/health"),
            "env": {
                "HOME": pwd.getpwuid(os.getuid()).pw_dir,
                "LC_ALL": "C",
                "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
                "TMPDIR": "/tmp",
            },
            "materials": {"cert": True, "key": True, "root": True},
            "snapshot_count": 1,
        },
        {
            "argv": _direct_probe_call(transaction.current, "/stream/healthz"),
            "env": {
                "HOME": pwd.getpwuid(os.getuid()).pw_dir,
                "LC_ALL": "C",
                "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
                "TMPDIR": "/tmp",
            },
            "materials": {"cert": True, "key": True, "root": True},
            "snapshot_count": 1,
        },
    ]
    docker_calls = _docker_calls(transaction.record)
    assert docker_calls[-3:] == _blackbox_probe_calls()
    assert all(docker_calls.count(call) == 1 for call in _blackbox_probe_calls())


def test_committed_resume_reproves_runtime_and_finalizes_without_reactivation(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
    )

    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after="committed"),
        TRANSACTION_ACTION,
    )

    assert interrupted.returncode == 86
    assert interrupted.stdout == ""
    assert interrupted.stderr == ""
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == "committed"
    assert journal["compose_env"] is None
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    assert _compose_env_artifact_paths(journal_path.parent) == []
    assert len(_curl_calls(transaction.probe_record)) == 2
    assert all(
        call in _docker_calls(transaction.record) for call in _blackbox_probe_calls()
    )
    generations = _generation_paths(transaction, journal)
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    compose_observations = _dotenv_observations(transaction.record)
    issuance_calls = [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ]

    recovery_env = dict(transaction.env)
    recovery_stage = _stage_path(
        transaction.current, "committed-interrupt-recovery-stage"
    )
    recovery_env["MCP_CLIENT_ROTATOR_STAGE_DIR"] = str(recovery_stage)
    recovered = _run_rotator(recovery_env, TRANSACTION_ACTION)

    assert recovered.returncode == 0
    assert recovered.stdout == _completion_result_line(
        "committed_recovered", transaction_id
    )
    assert recovered.stdout.count("mcp-client-rotation result=") == 1
    assert recovered.stderr == ""
    assert not journal_path.exists()
    emitted_receipt = _completion_receipt_path(transaction, transaction_id, "emitted")
    assert not _completion_receipt_path(transaction, transaction_id, "pending").exists()
    receipt = _strict_json(emitted_receipt)
    assert set(receipt) == COMPLETION_RECEIPT_FIELDS
    assert receipt["transaction_id"] == transaction_id
    assert receipt["result"] == "committed_recovered"
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_bytes)
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    assert _dotenv_observations(transaction.record) == compose_observations
    assert [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ] == issuance_calls
    probe_calls = _curl_calls(transaction.probe_record)
    assert len(probe_calls) == 4
    assert [call["snapshot_count"] for call in probe_calls] == [1, 1, 3, 3]
    assert all(
        call["materials"] == {"root": True, "cert": True, "key": True}
        for call in probe_calls
    )
    assert _blackbox_observations(transaction.record) == [
        _expected_blackbox_observation(
            "activation_started",
            0,
            direct_probe_count=2,
            snapshot_count=1,
        ),
        _expected_blackbox_observation(
            "committed",
            1,
            direct_probe_count=4,
            snapshot_count=3,
        ),
    ]
    assert (interrupted.stdout + recovered.stdout).count(
        "mcp-client-rotation result="
    ) == 1
    assert not recovery_stage.exists()


@pytest.mark.parametrize(
    "failure",
    [
        "validation",
        "consumer-expansion",
        "direct-probe",
        "blackbox",
    ],
)
def test_trusted_committed_reproof_failure_restores_and_reproves_old_pair(
    tmp_path: Path,
    failure: str,
) -> None:
    blackbox_only = (
        (
            RECREATED_BLACKBOX_CONTAINER_ID,
            "infra",
            "blackbox-exporter",
            "running",
        ),
    )
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={"post_compose_containers": blackbox_only},
        curl_options={"responses": ("204", "299")},
    )
    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after="committed"),
        TRANSACTION_ACTION,
    )
    assert interrupted.returncode == 86
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    generations = _generation_paths(transaction, journal)
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    rollback_expected = TlsFixture(
        secrets=transaction.current.secrets,
        root=transaction.current.root,
        bundle=generations["old_cert_sha256"],
        key=generations["old_key_sha256"],
        password=transaction.current.password,
        root_key=transaction.current.root_key,
        root_cert=transaction.current.root_cert,
        intermediate_key=transaction.current.intermediate_key,
        intermediate_cert=transaction.current.intermediate_cert,
    )
    issuance_calls = [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ]

    expanded = blackbox_only + (
        (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
    )
    post_compose = expanded if failure == "consumer-expansion" else blackbox_only
    if failure in {"validation", "consumer-expansion"}:
        pair_sequence = ("new", "new", "old", "old")
        responses = ("204", "299", "204", "299")
        expected_probe_count = 4
        expected_blackbox_count = 2
        expected_direct_counts = (2, 4)
    elif failure == "direct-probe":
        pair_sequence = ("new", "new", "new", "old", "old")
        responses = ("204", "299", "500", "204", "299")
        expected_probe_count = 5
        expected_blackbox_count = 2
        expected_direct_counts = (2, 5)
    else:
        pair_sequence = ("new", "new", "new", "new", "old", "old")
        responses = ("204", "299", "204", "299", "204", "299")
        expected_probe_count = 6
        expected_blackbox_count = 3
        expected_direct_counts = (2, 4, 6)
    _write_fake_curl(
        tmp_path,
        transaction.staged,
        rollback_expected=rollback_expected,
        expected_pair_sequence=pair_sequence,
        responses=responses,
        returncodes=(0,) * len(responses),
    )
    _write_fake_docker(
        tmp_path,
        transaction.staged,
        direct_probe_record=transaction.probe_record,
        post_compose_containers=post_compose,
        post_second_compose_containers=blackbox_only,
        blackbox_query_returncodes=(0, 42) if failure == "blackbox" else (),
        blackbox_expected_direct_probe_counts=expected_direct_counts,
    )
    recovery_env = (
        _fault_env(transaction.env, fail_validation="committed")
        if failure == "validation"
        else transaction.env
    )

    recovered = _run_rotator(recovery_env, TRANSACTION_ACTION)

    assert recovered.returncode == 75
    assert recovered.stdout == "mcp-client-rotation result=rolled_back\n"
    assert recovered.stderr == ""
    assert not journal_path.exists()
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert all(
        path.read_bytes() == generation_bytes[path] for path in generations.values()
    )
    assert [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ] == issuance_calls
    assert len(_dotenv_observations(transaction.record)) == 2
    assert len(_curl_calls(transaction.probe_record)) == expected_probe_count
    assert len(_blackbox_observations(transaction.record)) == expected_blackbox_count
    assert "result=committed_recovered" not in recovered.stdout


@pytest.mark.parametrize(
    ("interrupt_after", "temporary_remains"),
    [
        ("completion_receipt_temp_created", True),
        ("completion_receipt_partial_written", True),
        ("completion_receipt_temp_written", True),
        ("completion_receipt_temp_fsynced", True),
        ("completion_receipt_pending_renamed", False),
    ],
)
@pytest.mark.parametrize("completion_result", ["activated", "committed_recovered"])
def test_completion_receipt_resumes_each_pre_pending_durability_window(
    tmp_path: Path,
    interrupt_after: str,
    temporary_remains: bool,
    completion_result: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
    )
    if completion_result == "committed_recovered":
        committed = _run_rotator(
            _fault_env(transaction.env, interrupt_after="committed"),
            TRANSACTION_ACTION,
        )
        assert committed.returncode == 86

    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after=interrupt_after),
        TRANSACTION_ACTION,
    )

    assert interrupted.returncode == 86
    assert interrupted.stdout == ""
    assert interrupted.stderr == ""
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == f"completion_authorized_{completion_result}"
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    rotation = journal_path.parent
    temporary_receipts = sorted(rotation.glob(".completion.*.tmp"))
    assert len(temporary_receipts) == (1 if temporary_remains else 0)
    if temporary_receipts:
        temporary = temporary_receipts[0]
        assert re.fullmatch(
            rf"[.]completion[.]{transaction_id}[.]{completion_result}[.]"
            r"[0-9]{8}T[0-9]{6}Z[.]tmp",
            temporary.name,
        )
        temporary_stat = os.lstat(temporary)
        assert temporary_stat.st_uid == os.getuid()
        assert temporary_stat.st_mode & 0o777 == 0o600
        assert temporary_stat.st_nlink == 1
    pending_receipt = _completion_receipt_path(transaction, transaction_id, "pending")
    assert pending_receipt.exists() is (not temporary_remains)
    emitted_receipt = _completion_receipt_path(transaction, transaction_id, "emitted")
    assert not emitted_receipt.exists()
    generations = _generation_paths(transaction, journal)
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    recovered = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert recovered.returncode == 0
    assert recovered.stdout == _completion_result_line(
        completion_result,
        transaction_id,
    )
    assert recovered.stderr == ""
    assert not journal_path.exists()
    assert list(rotation.glob(".completion.*.tmp")) == []
    assert not pending_receipt.exists()
    assert emitted_receipt.is_file()
    assert _strict_json(emitted_receipt)["result"] == completion_result
    assert all(
        path.read_bytes() == generation_bytes[path] for path in generations.values()
    )
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls
    _assert_canonical_matches_transaction_new_pair(transaction, journal)

    replayed = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert replayed.returncode == 0
    assert replayed.stdout == "mcp-client-rotation result=healthy_noop\n"
    assert replayed.stderr == ""
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls


@pytest.mark.parametrize("completion_result", ["activated", "committed_recovered"])
def test_recovered_pending_receipt_is_resynced_before_journal_unlink(
    tmp_path: Path,
    completion_result: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
    )
    if completion_result == "committed_recovered":
        committed = _run_rotator(
            _fault_env(transaction.env, interrupt_after="committed"),
            TRANSACTION_ACTION,
        )
        assert committed.returncode == 86
    renamed = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="completion_receipt_pending_renamed",
        ),
        TRANSACTION_ACTION,
    )
    assert renamed.returncode == 86
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    pending = _completion_receipt_path(transaction, transaction_id, "pending")
    assert pending.is_file()
    pending_bytes = pending.read_bytes()
    journal_bytes = journal_path.read_bytes()
    generations = _generation_paths(transaction, journal)
    protected_paths = (
        transaction.current.bundle,
        transaction.current.key,
        *generations.values(),
    )
    protected_snapshots = {path: _file_snapshot(path) for path in protected_paths}
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    resynced = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="completion_receipt_revalidated_parent_fsynced",
        ),
        TRANSACTION_ACTION,
    )

    assert resynced.returncode == 86
    assert resynced.stdout == ""
    assert resynced.stderr == ""
    assert journal_path.read_bytes() == journal_bytes
    assert pending.read_bytes() == pending_bytes
    assert {
        path: _file_snapshot(path) for path in protected_paths
    } == protected_snapshots
    assert not _completion_receipt_path(transaction, transaction_id, "emitted").exists()
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls

    recovered = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert recovered.returncode == 0
    assert recovered.stdout == _completion_result_line(
        completion_result,
        transaction_id,
    )
    assert recovered.stderr == ""
    assert not journal_path.exists()
    assert not pending.exists()
    assert _completion_receipt_path(transaction, transaction_id, "emitted").is_file()
    _assert_canonical_matches_transaction_new_pair(transaction, journal)


@pytest.mark.parametrize(
    "corruption",
    [
        "wrong-transaction",
        "wrong-result",
        "non-prefix",
        "oversized",
        "wrong-mode",
        "symlink",
        "hardlink",
        "directory",
        "multiple",
        "pending-collision",
        "emitted-collision",
        "legacy-random-name",
        "without-journal",
    ],
)
def test_untrusted_completion_temp_fails_closed_and_preserves_evidence(
    tmp_path: Path,
    corruption: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={"responses": ("204", "299")},
    )
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="completion_authorized_activated",
        ),
        TRANSACTION_ACTION,
    )
    assert interrupted.returncode == 86
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    rotation = journal_path.parent
    completed_at = "2026-07-14T04:00:00Z"
    compact_time = "20260714T040000Z"

    def payload(identifier: str, result: str = "activated") -> bytes:
        return (
            json.dumps(
                {
                    "schema_version": 1,
                    "transaction_id": identifier,
                    "result": result,
                    "completed_at": completed_at,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()

    foreign_transaction = "f" * 32
    if foreign_transaction == transaction_id:
        foreign_transaction = "e" * 32
    temp_transaction = (
        foreign_transaction if corruption == "wrong-transaction" else transaction_id
    )
    temp_result = "committed_recovered" if corruption == "wrong-result" else "activated"
    temp_name = f".completion.{temp_transaction}.{temp_result}.{compact_time}.tmp"
    if corruption == "legacy-random-name":
        temp_name = f".completion.{transaction_id}.deadbeef.tmp"
    temporary = rotation / temp_name
    expected_payload = payload(temp_transaction, temp_result)
    foreign = tmp_path / "foreign-completion-temp"
    if corruption == "symlink":
        foreign.write_bytes(expected_payload)
        foreign.chmod(0o600)
        temporary.symlink_to(foreign)
    elif corruption == "hardlink":
        foreign.write_bytes(expected_payload)
        foreign.chmod(0o600)
        os.link(foreign, temporary)
    elif corruption == "directory":
        temporary.mkdir()
    else:
        contents = expected_payload
        if corruption in {"multiple", "pending-collision", "emitted-collision"}:
            contents = b""
        elif corruption == "non-prefix":
            contents = b"not-a-canonical-prefix"
        elif corruption == "oversized":
            contents = b"x" * (512 + 1)
        temporary.write_bytes(contents)
        temporary.chmod(0o644 if corruption == "wrong-mode" else 0o600)
    if corruption == "multiple":
        second = rotation / (
            f".completion.{transaction_id}.activated.20260714T040001Z.tmp"
        )
        second.write_bytes(b"")
        second.chmod(0o600)
    if corruption in {"pending-collision", "emitted-collision"}:
        state = "pending" if corruption == "pending-collision" else "emitted"
        collision = _completion_receipt_path(transaction, transaction_id, state)
        collision.write_bytes(payload(transaction_id))
        collision.chmod(0o600)
    if corruption == "without-journal":
        journal_path.unlink()

    def artifact_snapshot() -> dict[str, tuple[int, int, int, bytes | str]]:
        snapshot: dict[str, tuple[int, int, int, bytes | str]] = {}
        for path in sorted(rotation.iterdir(), key=lambda item: item.name):
            if not path.name.startswith(("completion.", ".completion.")):
                continue
            path_stat = os.lstat(path)
            if path.is_symlink():
                contents: bytes | str = os.readlink(path)
            elif path.is_file():
                contents = path.read_bytes()
            else:
                contents = b""
            snapshot[path.name] = (
                path_stat.st_mode,
                path_stat.st_nlink,
                path_stat.st_ino,
                contents,
            )
        return snapshot

    artifacts = artifact_snapshot()
    journal_bytes = journal_path.read_bytes() if journal_path.exists() else None
    generations = _generation_paths(transaction, journal)
    protected_paths = (
        transaction.current.bundle,
        transaction.current.key,
        *generations.values(),
    )
    protected_snapshots = {path: _file_snapshot(path) for path in protected_paths}
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    rejected = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert rejected.stderr == (
        "mcp-client-rotation failed: "
        + (
            "pending completion finalization failed\n"
            if corruption == "non-prefix"
            else "transaction recovery failed\n"
        )
    )
    assert artifact_snapshot() == artifacts
    assert {
        path: _file_snapshot(path) for path in protected_paths
    } == protected_snapshots
    assert journal_path.exists() is (journal_bytes is not None)
    if journal_bytes is not None:
        assert journal_path.read_bytes() == journal_bytes
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls
    assert _run_validator(transaction.current).returncode == 0
    assert "result=activated" not in rejected.stdout


@pytest.mark.parametrize(
    ("interrupt_after", "journal_remains"),
    [
        ("completion_receipt_parent_fsynced", True),
        ("completion_journal_unlinked", False),
        ("completion_journal_parent_fsynced", False),
    ],
)
@pytest.mark.parametrize("completion_result", ["activated", "committed_recovered"])
def test_completion_receipt_recovers_each_pre_output_unlink_window_once(
    tmp_path: Path,
    interrupt_after: str,
    journal_remains: bool,
    completion_result: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
    )
    if completion_result == "committed_recovered":
        committed = _run_rotator(
            _fault_env(transaction.env, interrupt_after="committed"),
            TRANSACTION_ACTION,
        )
        assert committed.returncode == 86

    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after=interrupt_after),
        TRANSACTION_ACTION,
    )

    assert interrupted.returncode == 86
    assert interrupted.stdout == ""
    assert interrupted.stderr == ""
    journal_path = _journal_path(transaction)
    assert journal_path.exists() is journal_remains
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 1
    journal = observations[0]["journal"]
    assert isinstance(journal, dict)
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    pending_receipt = _completion_receipt_path(transaction, transaction_id, "pending")
    emitted_receipt = _completion_receipt_path(transaction, transaction_id, "emitted")
    assert pending_receipt.is_file()
    assert not emitted_receipt.exists()
    pending_payload = _strict_json(pending_receipt)
    assert set(pending_payload) == COMPLETION_RECEIPT_FIELDS
    assert pending_payload["transaction_id"] == transaction_id
    assert pending_payload["result"] == completion_result
    generations = _generation_paths(transaction, journal)
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    recovered = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert recovered.returncode == 0
    assert recovered.stdout == _completion_result_line(
        completion_result,
        transaction_id,
    )
    assert recovered.stderr == ""
    assert not journal_path.exists()
    assert not pending_receipt.exists()
    assert emitted_receipt.is_file()
    assert _strict_json(emitted_receipt) == pending_payload
    assert all(
        path.read_bytes() == generation_bytes[path] for path in generations.values()
    )
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls
    _assert_canonical_matches_transaction_new_pair(transaction, journal)
    assert (interrupted.stdout + recovered.stdout).count(
        "mcp-client-rotation result="
    ) == 1

    replayed = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert replayed.returncode == 0
    assert replayed.stdout == "mcp-client-rotation result=healthy_noop\n"
    assert replayed.stderr == ""
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls


def test_activated_authorization_phase_resumes_without_repeating_runtime_proof(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={"responses": ("204", "299")},
    )
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="completion_authorized_activated",
        ),
        TRANSACTION_ACTION,
    )
    assert interrupted.returncode == 86
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == "completion_authorized_activated"
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    assert not _completion_receipt_path(transaction, transaction_id, "pending").exists()
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    recovered = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert recovered.returncode == 0
    assert recovered.stdout == _completion_result_line("activated", transaction_id)
    assert recovered.stderr == ""
    assert not journal_path.exists()
    assert _completion_receipt_path(transaction, transaction_id, "emitted").is_file()
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls


def test_committed_recovery_authorization_resumes_without_repeating_reproof(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
    )
    committed = _run_rotator(
        _fault_env(transaction.env, interrupt_after="committed"),
        TRANSACTION_ACTION,
    )
    assert committed.returncode == 86
    authorized = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="completion_authorized_committed_recovered",
        ),
        TRANSACTION_ACTION,
    )
    assert authorized.returncode == 86
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == "completion_authorized_committed_recovered"
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    assert not _completion_receipt_path(transaction, transaction_id, "pending").exists()
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    recovered = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert recovered.returncode == 0
    assert recovered.stdout == _completion_result_line(
        "committed_recovered", transaction_id
    )
    assert recovered.stderr == ""
    assert not journal_path.exists()
    assert _completion_receipt_path(transaction, transaction_id, "emitted").is_file()
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls


@pytest.mark.parametrize("authorized_result", ["activated", "committed_recovered"])
def test_completion_authorization_rejects_mismatched_receipt_result(
    tmp_path: Path,
    authorized_result: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
    )
    if authorized_result == "committed_recovered":
        committed = _run_rotator(
            _fault_env(transaction.env, interrupt_after="committed"),
            TRANSACTION_ACTION,
        )
        assert committed.returncode == 86
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after=f"completion_authorized_{authorized_result}",
        ),
        TRANSACTION_ACTION,
    )
    assert interrupted.returncode == 86
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    wrong_result = (
        "committed_recovered" if authorized_result == "activated" else "activated"
    )
    pending_receipt = _completion_receipt_path(transaction, transaction_id, "pending")
    pending_receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_id": transaction_id,
                "result": wrong_result,
                "completed_at": "2026-07-14T04:00:00Z",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    pending_receipt.chmod(0o600)
    journal_bytes = journal_path.read_bytes()
    receipt_bytes = pending_receipt.read_bytes()
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    rejected = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert rejected.stderr == (
        "mcp-client-rotation failed: transaction recovery failed\n"
    )
    assert journal_path.read_bytes() == journal_bytes
    assert pending_receipt.read_bytes() == receipt_bytes
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls


@pytest.mark.parametrize(
    "interrupt_after",
    [
        "completion_authorized_activated",
        "completion_receipt_parent_fsynced",
    ],
)
def test_completion_recovery_enforces_the_six_hour_floor_before_success(
    tmp_path: Path,
    interrupt_after: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        staged_remaining=dt.timedelta(hours=5),
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={"responses": ("204", "299")},
    )
    initial_env = dict(transaction.env)
    fake_bin = _write_six_hour_floor_bypass_openssl(tmp_path)
    initial_env["PATH"] = f"{fake_bin}:{initial_env['PATH']}"
    interrupted = _run_rotator(
        _fault_env(initial_env, interrupt_after=interrupt_after),
        TRANSACTION_ACTION,
    )
    assert interrupted.returncode == 86
    assert interrupted.stdout == ""
    assert interrupted.stderr == ""
    assert _run_diagnostic(transaction.current).returncode == 0
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == "completion_authorized_activated"
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    generations = _generation_paths(transaction, journal)
    assert (
        transaction.current.bundle.read_bytes()
        == generations["new_cert_sha256"].read_bytes()
    )
    assert (
        transaction.current.key.read_bytes()
        == generations["new_key_sha256"].read_bytes()
    )
    pending_receipt = _completion_receipt_path(transaction, transaction_id, "pending")
    assert pending_receipt.exists() is (
        interrupt_after == "completion_receipt_parent_fsynced"
    )
    emitted_receipt = _completion_receipt_path(transaction, transaction_id, "emitted")
    assert not emitted_receipt.exists()
    journal_bytes = journal_path.read_bytes()
    pending_bytes = pending_receipt.read_bytes() if pending_receipt.exists() else None
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    canonical_bytes = (
        transaction.current.bundle.read_bytes(),
        transaction.current.key.read_bytes(),
    )
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    rejected = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert rejected.stderr == (
        "mcp-client-rotation failed: completed certificate validation failed\n"
    )
    assert journal_path.read_bytes() == journal_bytes
    assert pending_receipt.exists() is (pending_bytes is not None)
    if pending_bytes is not None:
        assert pending_receipt.read_bytes() == pending_bytes
    assert not emitted_receipt.exists()
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_bytes)
    assert (
        transaction.current.bundle.read_bytes(),
        transaction.current.key.read_bytes(),
    ) == canonical_bytes
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls
    assert "result=activated" not in rejected.stdout


def test_receipt_only_recovery_revalidates_canonical_pair_before_success(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={"responses": ("204", "299")},
    )
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="completion_journal_parent_fsynced",
        ),
        TRANSACTION_ACTION,
    )
    assert interrupted.returncode == 86
    assert not _journal_path(transaction).exists()
    journal = _dotenv_observations(transaction.record)[0]["journal"]
    assert isinstance(journal, dict)
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    pending_receipt = _completion_receipt_path(transaction, transaction_id, "pending")
    assert pending_receipt.is_file()
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)
    transaction.current.key.write_bytes(transaction.old_key)
    transaction.current.key.chmod(0o600)

    rejected = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert rejected.stderr == (
        "mcp-client-rotation failed: transaction recovery failed\n"
    )
    assert pending_receipt.is_file()
    assert not _completion_receipt_path(transaction, transaction_id, "emitted").exists()
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls
    assert "result=activated" not in rejected.stdout


def test_receipt_only_recovery_rejects_a_different_valid_canonical_pair(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={"responses": ("204", "299")},
    )
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="completion_journal_parent_fsynced",
        ),
        TRANSACTION_ACTION,
    )
    assert interrupted.returncode == 86
    assert not _journal_path(transaction).exists()
    journal = _dotenv_observations(transaction.record)[0]["journal"]
    assert isinstance(journal, dict)
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    pending_receipt = _completion_receipt_path(transaction, transaction_id, "pending")
    assert pending_receipt.is_file()
    replacement = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="valid-replacement",
        issuer=transaction.current,
    )
    transaction.current.bundle.write_bytes(replacement.bundle.read_bytes())
    transaction.current.key.write_bytes(replacement.key.read_bytes())
    transaction.current.key.chmod(0o600)
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    rejected = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert rejected.stderr == (
        "mcp-client-rotation failed: transaction recovery failed\n"
    )
    assert pending_receipt.is_file()
    assert not _completion_receipt_path(transaction, transaction_id, "emitted").exists()
    assert transaction.current.bundle.read_bytes() == replacement.bundle.read_bytes()
    assert transaction.current.key.read_bytes() == replacement.key.read_bytes()
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls
    assert "result=activated" not in rejected.stdout


def test_rotator_holds_process_lock_for_entire_invocation(tmp_path: Path) -> None:
    entered = tmp_path / "completion-mark-entered"
    release = tmp_path / "completion-mark-release"
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={"responses": ("204", "299")},
    )
    fake_bin = _write_blocking_python_after_completion_mark(
        tmp_path,
        entered,
        release,
    )
    env = dict(transaction.env)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    first = subprocess.Popen(
        [str(ROTATOR), TRANSACTION_ACTION],
        cwd=REPO,
        env=env,
        pass_fds=_runtime_lock_pass_fds(env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )
    first_stdout = ""
    first_stderr = ""
    try:
        deadline = time.monotonic() + ROTATOR_LOCK_TEST_TIMEOUT_SECONDS
        while not entered.exists() and first.poll() is None:
            if time.monotonic() >= deadline:
                pytest.fail("first rotator did not durably mark completion")
            time.sleep(0.02)
        assert entered.is_file()
        assert first.poll() is None
        journal_at_mark = _dotenv_observations(transaction.record)[0]["journal"]
        assert isinstance(journal_at_mark, dict)
        transaction_id_at_mark = journal_at_mark["transaction_id"]
        assert isinstance(transaction_id_at_mark, str)
        assert not _completion_receipt_path(
            transaction,
            transaction_id_at_mark,
            "pending",
        ).exists()
        assert _completion_receipt_path(
            transaction,
            transaction_id_at_mark,
            "emitted",
        ).is_file()

        deferred = _run_rotator(env, TRANSACTION_ACTION)

        assert deferred.returncode == 75
        assert deferred.stdout == "mcp-client-rotation result=lock_deferred\n"
        assert deferred.stderr == ""
        assert first.poll() is None
        release.write_bytes(b"")
        first_stdout, first_stderr = first.communicate(
            timeout=ROTATOR_LOCK_TEST_TIMEOUT_SECONDS,
        )
    finally:
        release.touch(exist_ok=True)
        if first.poll() is None:
            first.terminate()
            try:
                first.wait(timeout=10)
            except subprocess.TimeoutExpired:
                first.kill()
                first.wait(timeout=10)

    assert first.returncode == 0
    assert first_stderr == ""
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 1
    journal = observations[0]["journal"]
    assert isinstance(journal, dict)
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    assert first_stdout == _completion_result_line("activated", transaction_id)
    lock_path = transaction.current.secrets / ".mcp-client-rotation.lock"
    lock_stat = os.lstat(lock_path)
    assert lock_stat.st_uid == os.getuid()
    assert lock_stat.st_mode & 0o777 == 0o600
    assert lock_stat.st_nlink == 1
    _assert_canonical_matches_transaction_new_pair(transaction, journal)


@pytest.mark.parametrize("completion_result", ["activated", "committed_recovered"])
def test_completion_replay_reuses_durable_transaction_id(
    tmp_path: Path,
    completion_result: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
    )
    if completion_result == "committed_recovered":
        committed = _run_rotator(
            _fault_env(transaction.env, interrupt_after="committed"),
            TRANSACTION_ACTION,
        )
        assert committed.returncode == 86
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="completion_journal_parent_fsynced",
        ),
        TRANSACTION_ACTION,
    )
    assert interrupted.returncode == 86
    journal = _dotenv_observations(transaction.record)[0]["journal"]
    assert isinstance(journal, dict)
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    pending_receipt = _completion_receipt_path(transaction, transaction_id, "pending")
    emitted_receipt = _completion_receipt_path(transaction, transaction_id, "emitted")
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    emitted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="completion_result_emitted",
        ),
        TRANSACTION_ACTION,
    )

    expected_line = _completion_result_line(completion_result, transaction_id)
    assert emitted.returncode == 86
    assert emitted.stdout == expected_line
    assert emitted.stderr == ""
    assert pending_receipt.is_file()
    assert not emitted_receipt.exists()
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls

    replayed = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert replayed.returncode == 0
    assert replayed.stdout == expected_line
    assert replayed.stderr == ""
    assert not pending_receipt.exists()
    assert emitted_receipt.is_file()
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls
    _assert_canonical_matches_transaction_new_pair(transaction, journal)


@pytest.mark.parametrize("completion_result", ["activated", "committed_recovered"])
def test_completion_emission_state_failure_is_nonzero_and_replayable(
    tmp_path: Path,
    completion_result: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
    )
    if completion_result == "committed_recovered":
        committed = _run_rotator(
            _fault_env(transaction.env, interrupt_after="committed"),
            TRANSACTION_ACTION,
        )
        assert committed.returncode == 86
    pending = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="completion_journal_parent_fsynced",
        ),
        TRANSACTION_ACTION,
    )
    assert pending.returncode == 86
    journal = _dotenv_observations(transaction.record)[0]["journal"]
    assert isinstance(journal, dict)
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    pending_receipt = _completion_receipt_path(transaction, transaction_id, "pending")
    emitted_receipt = _completion_receipt_path(transaction, transaction_id, "emitted")
    assert pending_receipt.is_file()
    assert not emitted_receipt.exists()
    pending_snapshot = _file_snapshot(pending_receipt)
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    degraded = _run_rotator(
        _fault_env(transaction.env, fail_fsync="completion-emitted-parent"),
        TRANSACTION_ACTION,
    )

    expected_line = _completion_result_line(completion_result, transaction_id)
    assert degraded.returncode == 74
    assert degraded.stdout == expected_line
    assert degraded.stderr == (
        "mcp-client-rotation failed: completion emission state could not be recorded\n"
    )
    assert pending_receipt.is_file()
    assert not emitted_receipt.exists()
    assert _file_snapshot(pending_receipt) == pending_snapshot
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls

    replayed = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert replayed.returncode == 0
    assert replayed.stdout == expected_line
    assert replayed.stderr == ""
    assert not pending_receipt.exists()
    assert emitted_receipt.is_file()
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls
    _assert_canonical_matches_transaction_new_pair(transaction, journal)


@pytest.mark.parametrize(
    "artifact",
    ["symlink", "hardlink", "wrong-mode", "directory"],
)
def test_unsafe_rotation_process_lock_fails_before_transaction_mutation(
    tmp_path: Path,
    artifact: str,
) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=13))
    lock_path = current.secrets / ".mcp-client-rotation.lock"
    foreign = tmp_path / "foreign-lock"
    if artifact == "symlink":
        foreign.write_bytes(b"")
        foreign.chmod(0o600)
        lock_path.symlink_to(foreign)
    elif artifact == "hardlink":
        foreign.write_bytes(b"")
        foreign.chmod(0o600)
        os.link(foreign, lock_path)
    elif artifact == "wrong-mode":
        lock_path.write_bytes(b"")
        lock_path.chmod(0o644)
    else:
        lock_path.mkdir()
    before = os.lstat(lock_path)
    certificate = current.bundle.read_bytes()
    private_key = current.key.read_bytes()
    stage = tmp_path / "unused-stage"
    env = _rotator_env(current, tmp_path / "missing-docker", stage)

    rejected = _run_rotator(env)

    assert rejected.returncode == 65
    assert rejected.stdout == "mcp-client-rotation result=preflight_failed\n"
    assert rejected.stderr.startswith(
        "mcp-client-rotation failed: rotation process lock"
    )
    after = os.lstat(lock_path)
    assert (after.st_dev, after.st_ino, after.st_mode, after.st_nlink) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
    )
    assert current.bundle.read_bytes() == certificate
    assert current.key.read_bytes() == private_key
    assert not stage.exists()


def test_writable_secret_root_is_rejected_before_process_lock_creation(
    tmp_path: Path,
) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=13))
    current.secrets.chmod(0o777)
    lock_path = current.secrets / ".mcp-client-rotation.lock"
    certificate = current.bundle.read_bytes()
    private_key = current.key.read_bytes()
    stage = tmp_path / "unused-stage"
    env = _rotator_env(current, tmp_path / "missing-docker", stage)

    rejected = _run_rotator(env)

    assert rejected.returncode == 65
    assert rejected.stdout == "mcp-client-rotation result=preflight_failed\n"
    assert rejected.stderr == (
        "mcp-client-rotation failed: external secret root must not be "
        "group/world writable\n"
    )
    assert not lock_path.exists()
    assert current.bundle.read_bytes() == certificate
    assert current.key.read_bytes() == private_key
    assert not stage.exists()


@pytest.mark.parametrize(
    "corruption",
    [
        "premature-activated",
        "premature-committed-recovered",
        "foreign-transaction",
        "payload-transaction-mismatch",
        "unknown-result",
        "duplicate-key",
        "oversized",
        "unsafe-mode",
        "symlink",
        "hardlink",
        "pending-emitted-collision",
    ],
)
def test_untrusted_completion_receipt_fails_closed_and_preserves_evidence(
    tmp_path: Path,
    corruption: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={"responses": ("204", "299")},
    )
    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after="committed"),
        TRANSACTION_ACTION,
    )
    assert interrupted.returncode == 86
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    transaction_id = journal["transaction_id"]
    assert isinstance(transaction_id, str)
    foreign_transaction_id = "e" * 32
    if foreign_transaction_id == transaction_id:
        foreign_transaction_id = "d" * 32
    receipt_transaction_id = (
        foreign_transaction_id
        if corruption == "foreign-transaction"
        else transaction_id
    )
    pending_receipt = _completion_receipt_path(
        transaction, receipt_transaction_id, "pending"
    )
    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "transaction_id": (
            foreign_transaction_id
            if corruption == "payload-transaction-mismatch"
            else receipt_transaction_id
        ),
        "result": (
            "unknown"
            if corruption == "unknown-result"
            else "committed_recovered"
            if corruption == "premature-committed-recovered"
            else "activated"
        ),
        "completed_at": "2026-07-14T04:00:00Z",
    }
    encoded = (
        json.dumps(receipt_payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    if corruption == "duplicate-key":
        encoded = encoded.replace(
            b'"schema_version":1', b'"schema_version":1,"schema_version":1'
        )
    elif corruption == "oversized":
        encoded += b" " * 513

    foreign_path = tmp_path / "foreign-completion-receipt.json"
    if corruption == "symlink":
        foreign_path.write_bytes(encoded)
        foreign_path.chmod(0o600)
        pending_receipt.symlink_to(foreign_path)
    elif corruption == "hardlink":
        foreign_path.write_bytes(encoded)
        foreign_path.chmod(0o600)
        os.link(foreign_path, pending_receipt)
    else:
        pending_receipt.write_bytes(encoded)
        pending_receipt.chmod(0o644 if corruption == "unsafe-mode" else 0o600)
    if corruption == "pending-emitted-collision":
        emitted_receipt = _completion_receipt_path(
            transaction, receipt_transaction_id, "emitted"
        )
        emitted_receipt.write_bytes(encoded)
        emitted_receipt.chmod(0o600)

    journal_bytes = journal_path.read_bytes()
    generations = _generation_paths(transaction, journal)
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    docker_calls = _docker_calls(transaction.record)
    curl_calls = _curl_calls(transaction.probe_record)

    rejected = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert (
        rejected.stderr == "mcp-client-rotation failed: transaction recovery failed\n"
    )
    assert journal_path.read_bytes() == journal_bytes
    assert os.path.lexists(pending_receipt)
    assert all(
        path.read_bytes() == generation_bytes[path] for path in generations.values()
    )
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    assert _docker_calls(transaction.record) == docker_calls
    assert _curl_calls(transaction.probe_record) == curl_calls
    assert "result=rolled_back" not in rejected.stdout
    assert "result=committed_recovered" not in rejected.stdout


@pytest.mark.parametrize("journal_has_compose_state", [False, True])
def test_committed_residue_is_rejected_and_preserved_without_cleanup(
    tmp_path: Path,
    journal_has_compose_state: bool,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "blackbox_sample_at_first_direct_probe": True,
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
        },
        curl_options={"responses": ("204", "299")},
    )
    committed = _run_rotator(
        _fault_env(transaction.env, interrupt_after="committed"),
        TRANSACTION_ACTION,
    )
    assert committed.returncode == 86
    assert committed.stdout == ""
    assert committed.stderr == ""
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == "committed"
    generations = _generation_paths(transaction, journal)
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    _, receipt = _write_dotenv_residue(transaction.current)
    if journal_has_compose_state:
        journal["compose_env"] = _strict_json(receipt)["compose_env"]
        journal_path.write_text(
            json.dumps(journal, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        journal_path.chmod(0o600)
    journal_bytes = journal_path.read_bytes()
    artifact_bytes = {
        path: path.read_bytes()
        for path in _compose_env_artifact_paths(journal_path.parent)
    }
    probe_calls = _curl_calls(transaction.probe_record)

    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        f"committed-residue-{journal_has_compose_state}",
    )
    recovered = _run_rotator(recovery_env)

    assert recovered.returncode == 74
    assert recovered.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert (
        recovered.stderr == "mcp-client-rotation failed: transaction recovery failed\n"
    )
    assert journal_path.read_bytes() == journal_bytes
    assert all(path.read_bytes() == artifact_bytes[path] for path in artifact_bytes)
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_bytes)
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    assert _docker_calls(recovery_record) == []
    assert _curl_calls(transaction.probe_record) == probe_calls


@pytest.mark.parametrize(
    ("docker_options", "operator_running"),
    [
        pytest.param(
            {"blackbox_query_returncodes": (42, 0)},
            False,
            id="transport",
        ),
        pytest.param(
            {"blackbox_sample_at_last_snapshot_queries": (0,)},
            False,
            id="blackbox-only-final-snapshot",
        ),
        pytest.param(
            {
                "containers": (
                    (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
                    (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
                ),
                "post_compose_containers": (
                    (
                        RECREATED_BLACKBOX_CONTAINER_ID,
                        "infra",
                        "blackbox-exporter",
                        "running",
                    ),
                    (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
                ),
                "post_second_compose_containers": (
                    (
                        RECREATED_BLACKBOX_CONTAINER_ID,
                        "infra",
                        "blackbox-exporter",
                        "running",
                    ),
                    (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
                ),
                "blackbox_sample_at_last_snapshot_queries": (0,),
            },
            True,
            id="operator-final-snapshot",
        ),
        pytest.param(
            {"blackbox_sample_age_seconds_by_query": (30.0, 0.0)},
            False,
            id="fresh-before-boundary",
        ),
        pytest.param(
            {"blackbox_sample_age_seconds_by_query": (300.0, 0.0)},
            False,
            id="stale",
        ),
    ],
)
def test_fixture_blackbox_failure_rolls_back_recorded_consumers(
    tmp_path: Path,
    docker_options: dict[str, object],
    operator_running: bool,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
            **docker_options,
        },
        curl_options={
            "expected_pair_sequence": ("new", "new", "old", "old"),
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
        operator_running=operator_running,
    )

    rolled_back = _run_rotator(transaction.env, TRANSACTION_ACTION)

    expected_services = ("blackbox-exporter",) + (
        ("operator",) if operator_running else ()
    )
    docker_calls = _docker_calls(transaction.record)
    assert docker_calls[-3:] == _blackbox_probe_calls()
    assert all(docker_calls.count(call) == 2 for call in _blackbox_probe_calls())
    sample_ages = docker_options.get("blackbox_sample_age_seconds_by_query", ())
    assert isinstance(sample_ages, tuple)
    last_snapshot_queries = docker_options.get(
        "blackbox_sample_at_last_snapshot_queries", ()
    )
    assert isinstance(last_snapshot_queries, tuple)
    first_sample_age = (
        None if 0 in last_snapshot_queries else sample_ages[0] if sample_ages else 0.0
    )
    expected_blackbox = [
        _expected_blackbox_observation(
            "activation_started",
            0,
            direct_probe_count=2,
            snapshot_count=len(expected_services),
            sample_age_seconds=first_sample_age,
            sample_source=(
                "last-snapshot" if 0 in last_snapshot_queries else "relative-age"
            ),
        ),
        _expected_blackbox_observation(
            "rollback_pair_restored",
            1,
            direct_probe_count=4,
            snapshot_count=2 * len(expected_services),
            sample_age_seconds=(sample_ages[1] if len(sample_ages) > 1 else 0.0),
        ),
    ]
    snapshot_records = ((RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter"),) + (
        ((OPERATOR_CONTAINER_ID, "operator"),) if operator_running else ()
    )
    snapshot = _consumer_snapshot_bytes(*snapshot_records)
    _assert_completed_rollback(
        transaction,
        rolled_back,
        services=expected_services * 2,
        phases=("activation_started",) * len(expected_services)
        + ("rollback_pair_restored",) * len(expected_services),
        snapshots=(snapshot,) * (2 * len(expected_services)),
        probe_snapshot_counts=(
            (len(expected_services),) * 2 + (2 * len(expected_services),) * 2
        ),
        blackbox_observations=expected_blackbox,
    )


def test_rollback_recreates_recorded_operator_after_blackbox_only_intermediate(
    tmp_path: Path,
) -> None:
    initial_both = (
        (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
        (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
    )
    rollback_blackbox = (
        (
            RECREATED_BLACKBOX_CONTAINER_ID,
            "infra",
            "blackbox-exporter",
            "running",
        ),
    )
    rollback_both = rollback_blackbox + (
        (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
    )
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "containers": initial_both,
            "post_compose_container_sequence": (
                initial_both,
                rollback_blackbox,
                rollback_both,
            ),
            "compose_returncodes": (42, 0, 0),
        },
        curl_options={"expected_pair_sequence": ("old", "old")},
        operator_running=True,
    )

    rolled_back = _run_rotator(transaction.env, TRANSACTION_ACTION)

    _assert_completed_rollback(
        transaction,
        rolled_back,
        services=("blackbox-exporter", "blackbox-exporter", "operator"),
        phases=(
            "activation_started",
            "rollback_pair_restored",
            "rollback_pair_restored",
        ),
        snapshots=(
            _consumer_snapshot_bytes(
                (RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter")
            ),
            _consumer_snapshot_bytes(
                (RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter"),
                (OPERATOR_CONTAINER_ID, "operator"),
            ),
        ),
        probe_snapshot_counts=(2, 2),
        blackbox_observations=[
            _expected_blackbox_observation(
                "rollback_pair_restored",
                0,
                direct_probe_count=2,
                snapshot_count=2,
            )
        ],
    )


@pytest.mark.parametrize(
    (
        "case",
        "operator_running",
        "compose_returncodes",
        "cause",
        "expected_services",
    ),
    [
        pytest.param(
            "unexpected-operator",
            False,
            (42, 0),
            "consumer set validation failed after blackbox rollback recreation",
            ("blackbox-exporter", "blackbox-exporter"),
            id="recorded-blackbox-only-current-both",
        ),
        pytest.param(
            "operator-recreation",
            True,
            (42, 0, 42),
            "operator rollback recreation failed",
            ("blackbox-exporter", "blackbox-exporter", "operator"),
            id="operator-recreation-failure",
        ),
        pytest.param(
            "operator-stability",
            True,
            (42, 0, 0),
            "consumer set validation failed after operator rollback recreation",
            ("blackbox-exporter", "blackbox-exporter", "operator"),
            id="operator-stability-failure",
        ),
    ],
)
def test_rollback_consumer_divergence_retains_recovery_evidence(
    tmp_path: Path,
    case: str,
    operator_running: bool,
    compose_returncodes: tuple[int, ...],
    cause: str,
    expected_services: tuple[str, ...],
) -> None:
    initial_blackbox = (
        (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
    )
    initial_both = initial_blackbox + (
        (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
    )
    rollback_blackbox = (
        (
            RECREATED_BLACKBOX_CONTAINER_ID,
            "infra",
            "blackbox-exporter",
            "running",
        ),
    )
    rollback_both = rollback_blackbox + (
        (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
    )
    initial = initial_both if operator_running else initial_blackbox
    if case == "unexpected-operator":
        sequence = (initial, rollback_both)
        expected_snapshots = (
            _consumer_snapshot_bytes(
                (RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter"),
                (OPERATOR_CONTAINER_ID, "operator"),
            ),
        )
    elif case == "operator-recreation":
        sequence = (initial, rollback_blackbox)
        expected_snapshots = (
            _consumer_snapshot_bytes(
                (RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter")
            ),
        )
    else:
        assert case == "operator-stability"
        sequence = (initial, rollback_blackbox, rollback_blackbox)
        rollback_snapshot = _consumer_snapshot_bytes(
            (RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter")
        )
        expected_snapshots = (rollback_snapshot, rollback_snapshot)
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "containers": initial,
            "post_compose_container_sequence": sequence,
            "compose_returncodes": compose_returncodes,
        },
        operator_running=operator_running,
    )

    failed = _run_rotator(transaction.env, TRANSACTION_ACTION)

    journal = _assert_retained_rollback_failure(
        transaction,
        failed,
        cause=cause,
    )
    assert journal["blackbox_exporter_was_running"] is True
    assert journal["operator_was_running"] is operator_running
    observations = _dotenv_observations(transaction.record)
    assert [str(observation["argv"][-1]) for observation in observations] == list(
        expected_services
    )
    assert [str(observation["journal"]["phase"]) for observation in observations] == [
        "activation_started",
        *("rollback_pair_restored",) * (len(observations) - 1),
    ]
    assert [
        observation["payload_hex"]
        for observation in _snapshot_observations(transaction.record)
    ] == [snapshot.hex() for snapshot in expected_snapshots]
    assert _curl_calls(transaction.probe_record) == []
    assert _blackbox_observations(transaction.record) == []


@pytest.mark.parametrize(
    (
        "docker_options",
        "returncodes",
        "expected_probe_count",
        "expected_rollback_blackbox",
        "expected_rollback_snapshot",
        "expected_rollback_sample_age",
    ),
    [
        pytest.param(
            {"compose_returncodes": (0, 42)},
            (0, 0, 0, 0),
            2,
            False,
            None,
            None,
            id="recreation",
        ),
        pytest.param(
            {},
            (0, 0, 7, 0),
            3,
            False,
            _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")),
            None,
            id="direct-probe",
        ),
        pytest.param(
            {"blackbox_query_returncodes": (42, 42)},
            (0, 0, 0, 0),
            4,
            True,
            _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")),
            0.0,
            id="blackbox-query",
        ),
        pytest.param(
            {
                "blackbox_query_returncodes": (42, 0),
                "blackbox_sample_age_seconds_by_query": (0.0, 300.0),
            },
            (0, 0, 0, 0),
            4,
            True,
            _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")),
            300.0,
            id="blackbox-stale",
        ),
        pytest.param(
            {"post_second_compose_containers": ()},
            (0, 0, 0, 0),
            2,
            False,
            b"",
            None,
            id="consumer-cardinality",
        ),
    ],
)
def test_rollback_recreation_or_probe_failure_retains_recovery_evidence(
    tmp_path: Path,
    docker_options: dict[str, object],
    returncodes: tuple[int, ...],
    expected_probe_count: int,
    expected_rollback_blackbox: bool,
    expected_rollback_snapshot: bytes | None,
    expected_rollback_sample_age: float | None,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
            "post_second_compose_containers": (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
            ),
            "blackbox_query_returncodes": (42,),
            **docker_options,
        },
        curl_options={
            "expected_pair_sequence": ("new", "new", "old", "old"),
            "responses": ("204", "299", "204", "299"),
            "returncodes": returncodes,
        },
    )

    failed = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert failed.returncode == 74
    assert failed.stdout == "mcp-client-rotation result=rollback_failed\n"
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == "rollback_pair_restored"
    assert journal["compose_env"] is None
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    generations = _generation_paths(transaction, journal)
    assert all(path.exists() for path in generations.values())
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 2
    for observation, phase in zip(
        observations,
        ("activation_started", "rollback_pair_restored"),
        strict=True,
    ):
        _assert_private_dotenv_observation(
            observation,
            "blackbox-exporter",
            expected_phase=phase,
        )
    assert len(_curl_calls(transaction.probe_record)) == expected_probe_count
    expected_blackbox = [
        _expected_blackbox_observation(
            "activation_started",
            0,
            direct_probe_count=2,
            snapshot_count=1,
        )
    ]
    if expected_rollback_blackbox:
        expected_blackbox.append(
            _expected_blackbox_observation(
                "rollback_pair_restored",
                1,
                direct_probe_count=4,
                snapshot_count=2,
                sample_age_seconds=expected_rollback_sample_age,
            )
        )
    assert _blackbox_observations(transaction.record) == expected_blackbox
    snapshots = _snapshot_observations(transaction.record)
    assert (
        snapshots[0]["payload_hex"]
        == _consumer_snapshot_bytes(
            (RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter")
        ).hex()
    )
    if expected_rollback_snapshot is None:
        assert len(snapshots) == 1
    else:
        assert [snapshot["payload_hex"] for snapshot in snapshots] == [
            _consumer_snapshot_bytes(
                (RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter")
            ).hex(),
            expected_rollback_snapshot.hex(),
        ]
    assert VALID_DB_PASSWORD.decode() not in failed.stdout + failed.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in failed.stdout + failed.stderr


@pytest.mark.parametrize(
    (
        "faults",
        "expected_phase",
        "expected_pair",
        "expected_compose_count",
        "expected_probe_count",
        "expected_blackbox_count",
    ),
    [
        pytest.param(
            {"fail_fsync": "rollback-certificate-parent"},
            "rollback_restoring_certificate",
            "old-new",
            1,
            2,
            1,
            id="certificate-parent-fsync",
        ),
        pytest.param(
            {"fail_fsync": "rollback-key-parent"},
            "rollback_restoring_key",
            "old-old",
            1,
            2,
            1,
            id="key-parent-fsync",
        ),
        pytest.param(
            {"fail_validation": "rollback-finalization"},
            "rollback_pair_restored",
            "old-old",
            2,
            4,
            2,
            id="finalization",
        ),
    ],
)
def test_rollback_fsync_or_finalization_failure_retains_reachable_evidence(
    tmp_path: Path,
    faults: dict[str, str],
    expected_phase: str,
    expected_pair: str,
    expected_compose_count: int,
    expected_probe_count: int,
    expected_blackbox_count: int,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
            "post_second_compose_containers": (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
            ),
            "blackbox_query_returncodes": (42, 0),
        },
        curl_options={
            "expected_pair_sequence": ("new", "new", "old", "old"),
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
    )

    failed = _run_rotator(
        _fault_env(transaction.env, **faults),
        TRANSACTION_ACTION,
    )

    assert failed.returncode == 74
    assert failed.stdout == "mcp-client-rotation result=rollback_failed\n"
    assert "result=rolled_back" not in failed.stdout
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == expected_phase
    assert journal["compose_env"] is None
    generations = _generation_paths(transaction, journal)
    assert len(generations) == 4
    assert len(set(generations.values())) == 4
    assert all(
        path.is_file() and not path.is_symlink() for path in generations.values()
    )
    assert transaction.current.bundle.is_file()
    assert transaction.current.key.is_file()
    assert not transaction.current.bundle.is_symlink()
    assert not transaction.current.key.is_symlink()
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    expected_key = (
        transaction.staged.key.read_bytes()
        if expected_pair == "old-new"
        else transaction.old_key
    )
    assert transaction.current.key.read_bytes() == expected_key
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == expected_compose_count
    for index, observation in enumerate(observations):
        _assert_private_dotenv_observation(
            observation,
            "blackbox-exporter",
            expected_phase=(
                "activation_started" if index == 0 else "rollback_pair_restored"
            ),
        )
    assert len(_curl_calls(transaction.probe_record)) == expected_probe_count
    expected_blackbox = [
        _expected_blackbox_observation(
            "activation_started",
            0,
            direct_probe_count=2,
            snapshot_count=1,
        )
    ]
    if expected_blackbox_count == 2:
        expected_blackbox.append(
            _expected_blackbox_observation(
                "rollback_pair_restored",
                1,
                direct_probe_count=4,
                snapshot_count=2,
            )
        )
    assert _blackbox_observations(transaction.record) == expected_blackbox
    issuance_calls = [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ]
    assert len(issuance_calls) == 1
    assert VALID_DB_PASSWORD.decode() not in failed.stdout + failed.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in failed.stdout + failed.stderr


@pytest.mark.parametrize(
    ("interrupt_after", "expected_phase", "expected_pair"),
    [
        pytest.param(
            "rollback_restoring_certificate",
            "rollback_restoring_certificate",
            "new-new",
            id="certificate-phase",
        ),
        pytest.param(
            "rollback_certificate_restored",
            "rollback_restoring_certificate",
            "old-new",
            id="certificate-pre-fsync",
        ),
        pytest.param(
            "rollback_certificate_parent_fsynced",
            "rollback_restoring_certificate",
            "old-new",
            id="certificate-post-fsync",
        ),
        pytest.param(
            "rollback_restoring_key",
            "rollback_restoring_key",
            "old-new",
            id="key-phase",
        ),
        pytest.param(
            "rollback_key_restored",
            "rollback_restoring_key",
            "old-old",
            id="key-pre-fsync",
        ),
        pytest.param(
            "rollback_key_parent_fsynced",
            "rollback_restoring_key",
            "old-old",
            id="key-post-fsync",
        ),
        pytest.param(
            "rollback_pair_restored",
            "rollback_pair_restored",
            "old-old",
            id="pair-restored",
        ),
    ],
)
def test_restart_resumes_across_rollback_restore_boundaries_without_reissuing(
    tmp_path: Path,
    interrupt_after: str,
    expected_phase: str,
    expected_pair: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
            "post_second_compose_containers": (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
            ),
            "blackbox_query_returncodes": (42, 0),
        },
        curl_options={
            "expected_pair_sequence": ("new", "new", "old", "old"),
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
    )

    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after=interrupt_after),
        TRANSACTION_ACTION,
    )

    assert interrupted.returncode == 86
    assert interrupted.stdout == ""
    assert interrupted.stderr == ""
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == expected_phase
    assert journal["compose_env"] is None
    expected_cert = (
        transaction.staged.bundle.read_bytes()
        if expected_pair == "new-new"
        else transaction.old_cert
    )
    expected_key = (
        transaction.staged.key.read_bytes()
        if expected_pair in {"new-new", "old-new"}
        else transaction.old_key
    )
    assert transaction.current.bundle.read_bytes() == expected_cert
    assert transaction.current.key.read_bytes() == expected_key
    generations = _generation_paths(transaction, journal)
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    issuance_calls = [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ]
    assert len(issuance_calls) == 1
    activation_observations = _dotenv_observations(transaction.record)
    assert len(activation_observations) == 1
    _assert_private_dotenv_observation(
        activation_observations[0],
        "blackbox-exporter",
    )
    compose_calls = [
        call
        for call in _docker_calls(transaction.record)
        if call[:3] == ["--context", "colima", "compose"] and "up" in call
    ]
    assert len(compose_calls) == 1
    assert compose_calls[0][-1] == "blackbox-exporter"
    assert [
        observation["payload_hex"]
        for observation in _snapshot_observations(transaction.record)
    ] == [
        _consumer_snapshot_bytes(
            (RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter")
        ).hex()
    ]

    recovered = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert recovered.returncode == 75
    assert recovered.stdout == "mcp-client-rotation result=rolled_back\n"
    assert recovered.stdout.count("mcp-client-rotation result=") == 1
    assert not journal_path.exists()
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_bytes)
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ] == issuance_calls
    probe_calls = _curl_calls(transaction.probe_record)
    assert len(probe_calls) == 4
    assert [call["snapshot_count"] for call in probe_calls] == [1, 1, 2, 2]
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 2
    _assert_private_dotenv_observation(
        observations[1],
        "blackbox-exporter",
        expected_phase="rollback_pair_restored",
    )
    compose_calls = [
        call
        for call in _docker_calls(transaction.record)
        if call[:3] == ["--context", "colima", "compose"] and "up" in call
    ]
    assert len(compose_calls) == 2
    assert [call[-1] for call in compose_calls] == [
        "blackbox-exporter",
        "blackbox-exporter",
    ]
    assert [
        observation["payload_hex"]
        for observation in _snapshot_observations(transaction.record)
    ] == [
        _consumer_snapshot_bytes(
            (RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter")
        ).hex(),
        _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")).hex(),
    ]
    assert _blackbox_observations(transaction.record) == [
        _expected_blackbox_observation(
            "activation_started",
            0,
            direct_probe_count=2,
            snapshot_count=1,
        ),
        _expected_blackbox_observation(
            "rollback_pair_restored",
            1,
            direct_probe_count=4,
            snapshot_count=2,
        ),
    ]


@pytest.mark.parametrize(
    "tamper",
    ["alternate-path", "wrong-digest", "legacy-schema"],
)
def test_rollback_restart_rejects_tampered_compose_identity_marker(
    tmp_path: Path,
    tamper: str,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
            "post_second_compose_containers": (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
            ),
            "blackbox_query_returncodes": (42, 0),
        },
        curl_options={
            "expected_pair_sequence": ("new", "new", "old", "old"),
            "responses": ("204", "299", "204", "299"),
            "returncodes": (0, 0, 0, 0),
        },
    )
    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after="rollback_pair_restored"),
        TRANSACTION_ACTION,
    )
    assert interrupted.returncode == 86
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == "rollback_pair_restored"
    journal_bytes = journal_path.read_bytes()
    generations = _generation_paths(transaction, journal)
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    compose_calls_before = [
        call
        for call in _docker_calls(transaction.record)
        if call[:3] == ["--context", "colima", "compose"] and "up" in call
    ]
    issuance_calls = [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ]
    assert len(compose_calls_before) == 1
    assert len(issuance_calls) == 1
    probe_calls_before = _curl_calls(transaction.probe_record)

    marker = _stage_path(transaction.current, TRANSACTION_MARKER)
    marker_payload = _strict_json(marker)
    if tamper == "alternate-path":
        alternate_compose = tmp_path / "alternate-compose.yml"
        shutil.copyfile(COMPOSE, alternate_compose)
        alternate_compose.chmod(0o600)
        alternate_stat = os.lstat(alternate_compose)
        assert alternate_stat.st_uid == os.getuid()
        assert alternate_stat.st_mode & 0o777 == 0o600
        assert alternate_stat.st_nlink == 1
        marker_payload["compose_file_path"] = str(
            alternate_compose.resolve(strict=True)
        )
        marker_payload["compose_file_sha256"] = _sha256_file(alternate_compose)
    elif tamper == "wrong-digest":
        marker_payload["compose_file_sha256"] = "0" * 64
        assert marker_payload["compose_file_sha256"] != _sha256_file(COMPOSE)
    else:
        assert tamper == "legacy-schema"
        marker_payload["schema_version"] = 1
    marker.write_text(
        json.dumps(marker_payload, separators=(",", ":")),
        encoding="utf-8",
    )
    marker.chmod(0o600)

    failed = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert failed.returncode == 74
    assert failed.stdout == "mcp-client-rotation result=rollback_failed\n"
    assert journal_path.read_bytes() == journal_bytes
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_bytes)
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert [
        call
        for call in _docker_calls(transaction.record)
        if call[:3] == ["--context", "colima", "compose"] and "up" in call
    ] == compose_calls_before
    assert [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ] == issuance_calls
    assert _curl_calls(transaction.probe_record) == probe_calls_before
    assert VALID_DB_PASSWORD.decode() not in failed.stdout + failed.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in failed.stdout + failed.stderr


@pytest.mark.parametrize(
    ("responses", "returncodes", "expected_routes"),
    [
        (("199", "200"), (0, 0), ("/health",)),
        (("300", "200"), (0, 0), ("/health",)),
        (("200\n", "200"), (0, 0), ("/health",)),
        (("200junk", "200"), (0, 0), ("/health",)),
        (("200", "200"), (7, 0), ("/health",)),
        (("200", "500"), (0, 0), ("/health", "/stream/healthz")),
    ],
)
def test_direct_probe_rejects_transport_or_non_2xx_and_short_circuits(
    tmp_path: Path,
    responses: tuple[str, ...],
    returncodes: tuple[int, ...],
    expected_routes: tuple[str, ...],
) -> None:
    child_canary = "direct-probe-child-canary-must-not-leak"
    initial_probe_count = len(expected_routes)
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": (
                (
                    RECREATED_BLACKBOX_CONTAINER_ID,
                    "infra",
                    "blackbox-exporter",
                    "running",
                ),
            ),
            "post_second_compose_containers": (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
            ),
            "blackbox_expected_direct_probe_counts": (initial_probe_count + 2,),
        },
        curl_options={
            "expected_pair_sequence": ("new",) * initial_probe_count + ("old", "old"),
            "responses": responses[:initial_probe_count] + ("204", "299"),
            "returncodes": returncodes[:initial_probe_count] + (0, 0),
            "child_canary": child_canary,
        },
    )

    failed = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert failed.returncode == 75
    assert failed.stdout == "mcp-client-rotation result=rolled_back\n"
    assert child_canary not in failed.stdout
    assert child_canary not in failed.stderr
    calls = _curl_calls(transaction.probe_record)
    assert [call["argv"] for call in calls] == [
        _direct_probe_call(transaction.current, route) for route in expected_routes
    ] + [
        _direct_probe_call(transaction.current, route)
        for route in ("/health", "/stream/healthz")
    ]
    assert all(
        call["materials"] == {"cert": True, "key": True, "root": True} for call in calls
    )
    assert [call["snapshot_count"] for call in calls] == [
        *([1] * initial_probe_count),
        2,
        2,
    ]
    journal_path = _journal_path(transaction)
    assert not journal_path.exists()
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 2
    for observation, phase in zip(
        observations,
        ("activation_started", "rollback_pair_restored"),
        strict=True,
    ):
        _assert_private_dotenv_observation(
            observation,
            "blackbox-exporter",
            expected_phase=phase,
        )
    assert [
        observation["payload_hex"]
        for observation in _snapshot_observations(transaction.record)
    ] == [
        _consumer_snapshot_bytes(
            (RECREATED_BLACKBOX_CONTAINER_ID, "blackbox-exporter")
        ).hex(),
        _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")).hex(),
    ]
    assert _blackbox_observations(transaction.record) == [
        _expected_blackbox_observation(
            "rollback_pair_restored",
            0,
            direct_probe_count=initial_probe_count + 2,
            snapshot_count=2,
        )
    ]
    compose_calls = [
        call
        for call in _docker_calls(transaction.record)
        if call[:3] == ["--context", "colima", "compose"] and "up" in call
    ]
    assert [call[-1] for call in compose_calls] == [
        "blackbox-exporter",
        "blackbox-exporter",
    ]


@pytest.mark.parametrize(
    "unsafe_kind",
    [
        "missing-override",
        "missing",
        "relative",
        "directory",
        "non-executable",
        "symlink",
        "symlink-parent",
        "writable",
        "writable-parent",
    ],
)
def test_direct_probe_fixture_override_rejects_unsafe_executable(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    safe_curl = Path(transaction.env["MCP_CLIENT_ROTATOR_TEST_CURL_BIN"])
    unsafe_curl = safe_curl
    if unsafe_kind == "missing-override":
        unsafe_curl = Path("")
    elif unsafe_kind == "missing":
        unsafe_curl = tmp_path / "missing-curl"
    elif unsafe_kind == "relative":
        unsafe_curl = Path("fake-curl")
    elif unsafe_kind == "directory":
        unsafe_curl = tmp_path
    elif unsafe_kind == "non-executable":
        safe_curl.chmod(0o600)
    elif unsafe_kind == "symlink":
        unsafe_curl = tmp_path / "curl-symlink"
        unsafe_curl.symlink_to(safe_curl)
    elif unsafe_kind == "symlink-parent":
        linked_parent = tmp_path / "linked-parent"
        linked_parent.symlink_to(tmp_path, target_is_directory=True)
        unsafe_curl = linked_parent / safe_curl.name
    elif unsafe_kind == "writable-parent":
        safe_curl.parent.chmod(0o770)
    else:
        safe_curl.chmod(0o720)
    env = dict(transaction.env)
    if unsafe_kind == "missing-override":
        env.pop("MCP_CLIENT_ROTATOR_TEST_CURL_BIN")
    else:
        env["MCP_CLIENT_ROTATOR_TEST_CURL_BIN"] = str(unsafe_curl)

    rejected = _run_rotator(env, TRANSACTION_ACTION)

    assert rejected.returncode == 65
    assert rejected.stdout == "mcp-client-rotation result=preflight_failed\n"
    assert (
        rejected.stderr
        == "mcp-client-rotation failed: fixture direct-probe executable is unsafe\n"
    )
    assert _curl_calls(transaction.probe_record) == []
    assert _docker_calls(transaction.record) == []
    assert not _journal_path(transaction).exists()


def test_staged_only_path_never_executes_direct_probes(tmp_path: Path) -> None:
    transaction = _transaction_fixture(tmp_path)

    staged = _run_rotator(transaction.env)

    assert staged.returncode == 0
    assert staged.stdout == "mcp-client-rotation result=staged_only\n"
    assert staged.stderr == ""
    assert _curl_calls(transaction.probe_record) == []
    assert not any(
        call in _blackbox_probe_calls() for call in _docker_calls(transaction.record)
    )
    assert not _journal_path(transaction).exists()


def test_recovery_validation_failure_retains_journal_and_generations(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after="pair_published"),
        TRANSACTION_ACTION,
    )
    assert interrupted.returncode != 0
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    generations = _generation_paths(transaction, journal)

    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        "failed-validation-recovery",
        fail_validation="restored",
    )
    failed = _run_rotator(recovery_env)

    assert failed.returncode == 74
    assert failed.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert journal_path.exists()
    assert _strict_json(journal_path)["phase"] in {
        "old_pair_restored",
        "recovery_failed",
    }
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert all(path.exists() for path in generations.values())
    assert "committed" not in journal_path.read_text(encoding="utf-8")
    assert _docker_calls(recovery_record) == []


@pytest.mark.parametrize(
    ("operator_record", "operator_was_running"),
    [
        pytest.param(None, False, id="absent"),
        pytest.param(
            (OPERATOR_CONTAINER_ID, "foreign", "operator", "running"),
            False,
            id="foreign-project-is-absent",
        ),
        pytest.param(
            (OPERATOR_CONTAINER_ID, "infra", "operator", "exited"),
            False,
            id="stopped-is-absent",
        ),
        pytest.param(
            (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
            True,
            id="running",
        ),
    ],
)
def test_consumer_discovery_and_private_dotenv_preserve_operator_absence(
    tmp_path: Path,
    operator_record: tuple[str, str, str, str] | None,
    operator_was_running: bool,
) -> None:
    containers = [(BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running")]
    if operator_record is not None:
        containers.append(operator_record)
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={"containers": tuple(containers)},
        operator_running=operator_was_running,
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    calls = _docker_calls(transaction.record)
    observations = _dotenv_observations(transaction.record)
    expected_services = ["blackbox-exporter"] + (
        ["operator"] if operator_was_running else []
    )
    assert [str(observation["argv"][-1]) for observation in observations] == (
        expected_services
    )
    artifacts = [
        _assert_private_dotenv_observation(observation, service)
        for observation, service in zip(observations, expected_services, strict=True)
    ]
    snapshot_indices = [
        index for index, call in enumerate(calls) if call == _consumer_snapshot_call()
    ]
    assert len(snapshot_indices) == (3 if operator_was_running else 2)
    blackbox_compose_index = calls.index(list(observations[0]["argv"]))
    assert snapshot_indices[0] < blackbox_compose_index < snapshot_indices[1]
    if operator_was_running:
        operator_compose_index = calls.index(list(observations[1]["argv"]))
        assert snapshot_indices[1] < operator_compose_index < snapshot_indices[2]
        assert [
            call["snapshot_count"] for call in _curl_calls(transaction.probe_record)
        ] == [
            2,
            2,
        ]
    assert all(not dotenv.exists() for dotenv, _ in artifacts)
    assert all(not receipt.exists() for _, receipt in artifacts)
    assert VALID_DB_PASSWORD.decode() not in proc.stdout + proc.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "containers",
    [
        pytest.param((), id="missing-blackbox"),
        pytest.param(
            (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
                ("c" * 64, "infra", "blackbox-exporter", "running"),
            ),
            id="duplicate-blackbox",
        ),
        pytest.param(
            ((BLACKBOX_CONTAINER_ID, "foreign", "blackbox-exporter", "running"),),
            id="foreign-project-blackbox",
        ),
        pytest.param(
            ((BLACKBOX_CONTAINER_ID, "infra", "other", "running"),),
            id="foreign-service-blackbox",
        ),
        pytest.param(
            ((BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "exited"),),
            id="stopped-blackbox",
        ),
        pytest.param(
            (("not-a-container-id", "infra", "blackbox-exporter", "running"),),
            id="invalid-blackbox-id",
        ),
        pytest.param(
            (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
                (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
                ("c" * 64, "infra", "operator", "running"),
            ),
            id="duplicate-operator",
        ),
    ],
)
def test_consumer_discovery_rejects_invalid_cardinality_before_rotation(
    tmp_path: Path,
    containers: tuple[tuple[str, str, str, str], ...],
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={"containers": containers},
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    calls = _docker_calls(transaction.record)
    assert proc.returncode != 0
    assert calls.count(_consumer_snapshot_call()) == 1
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert not transaction.record.exists()
    assert not _journal_path(transaction).exists()
    assert _dotenv_observations(transaction.record) == []
    assert VALID_DB_PASSWORD.decode() not in proc.stdout + proc.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "post_compose_containers",
    [
        pytest.param((), id="blackbox-disappeared"),
        pytest.param(
            (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
                ("c" * 64, "infra", "blackbox-exporter", "running"),
            ),
            id="blackbox-cardinality-increased",
        ),
    ],
)
def test_post_compose_rediscovery_rejects_changed_consumer_cardinality(
    tmp_path: Path,
    post_compose_containers: tuple[tuple[str, str, str, str], ...],
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": post_compose_containers,
            "post_second_compose_containers": (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
            ),
        },
        curl_options={
            "expected_pair_sequence": ("old", "old"),
            "responses": ("204", "299"),
            "returncodes": (0, 0),
        },
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert proc.returncode == 75
    assert proc.stdout == "mcp-client-rotation result=rolled_back\n"
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 2
    artifacts = [
        _assert_private_dotenv_observation(
            observation,
            "blackbox-exporter",
            expected_phase=phase,
        )
        for observation, phase in zip(
            observations,
            ("activation_started", "rollback_pair_restored"),
            strict=True,
        )
    ]
    calls = _docker_calls(transaction.record)
    snapshot_indices = [
        index for index, call in enumerate(calls) if call == _consumer_snapshot_call()
    ]
    compose_indices = [
        calls.index(list(observation["argv"])) for observation in observations
    ]
    assert len(snapshot_indices) == 3
    assert snapshot_indices[0] < compose_indices[0] < snapshot_indices[1]
    assert snapshot_indices[1] < compose_indices[1] < snapshot_indices[2]
    assert [str(observation["argv"][-1]) for observation in observations] == [
        "blackbox-exporter",
        "blackbox-exporter",
    ]
    assert all(not dotenv.exists() for dotenv, _ in artifacts)
    assert all(not receipt.exists() for _, receipt in artifacts)
    journal_path = _journal_path(transaction)
    assert not journal_path.exists()
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    first_snapshot = _consumer_snapshot_bytes(
        *(
            (identifier, service)
            for identifier, project, service, state in post_compose_containers
            if project == "infra" and state == "running"
        )
    )
    assert [
        observation["payload_hex"]
        for observation in _snapshot_observations(transaction.record)
    ] == [
        first_snapshot.hex(),
        _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")).hex(),
    ]
    probe_calls = _curl_calls(transaction.probe_record)
    assert len(probe_calls) == 2
    assert all(call["snapshot_count"] == 2 for call in probe_calls)
    assert _blackbox_observations(transaction.record) == [
        _expected_blackbox_observation(
            "rollback_pair_restored",
            0,
            direct_probe_count=2,
            snapshot_count=2,
        )
    ]
    assert VALID_DB_PASSWORD.decode() not in proc.stdout + proc.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    ("docker_options", "expected_snapshot_bytes"),
    [
        pytest.param(
            {"fail_post_compose_snapshot_sequence": (True, False)},
            _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")),
            id="docker-ps-failure",
        ),
        pytest.param(
            {
                "post_compose_containers": (
                    (
                        BLACKBOX_CONTAINER_ID,
                        "infra",
                        "blackbox-exporter",
                        "running",
                    ),
                    (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
                ),
                "post_compose_sequential_containers": (),
            },
            _consumer_snapshot_bytes(
                (BLACKBOX_CONTAINER_ID, "blackbox-exporter"),
                (OPERATOR_CONTAINER_ID, "operator"),
            ),
            id="inconsistent-sequential-views",
        ),
    ],
)
def test_post_compose_consumer_snapshot_is_atomic_and_fail_closed(
    tmp_path: Path,
    docker_options: dict[str, object],
    expected_snapshot_bytes: bytes,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            **docker_options,
            "post_second_compose_containers": (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
            ),
        },
        curl_options={
            "expected_pair_sequence": ("old", "old"),
            "responses": ("204", "299"),
            "returncodes": (0, 0),
        },
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert proc.returncode == 75
    assert proc.stdout == "mcp-client-rotation result=rolled_back\n"
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 2
    artifacts = [
        _assert_private_dotenv_observation(
            observation,
            "blackbox-exporter",
            expected_phase=phase,
        )
        for observation, phase in zip(
            observations,
            ("activation_started", "rollback_pair_restored"),
            strict=True,
        )
    ]
    calls = _docker_calls(transaction.record)
    snapshot_indices = [
        index for index, call in enumerate(calls) if call == _consumer_snapshot_call()
    ]
    compose_indices = [
        calls.index(list(observation["argv"])) for observation in observations
    ]
    assert len(snapshot_indices) == 3
    assert snapshot_indices[0] < compose_indices[0] < snapshot_indices[1]
    assert snapshot_indices[1] < compose_indices[1] < snapshot_indices[2]
    assert [
        observation["payload_hex"]
        for observation in _snapshot_observations(transaction.record)
    ] == [
        expected_snapshot_bytes.hex(),
        _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")).hex(),
    ]
    assert all(not dotenv.exists() for dotenv, _ in artifacts)
    assert all(not receipt.exists() for _, receipt in artifacts)
    assert not _journal_path(transaction).exists()
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    probe_calls = _curl_calls(transaction.probe_record)
    assert len(probe_calls) == 2
    assert all(call["snapshot_count"] == 2 for call in probe_calls)
    assert _blackbox_observations(transaction.record) == [
        _expected_blackbox_observation(
            "rollback_pair_restored",
            0,
            direct_probe_count=2,
            snapshot_count=2,
        )
    ]
    assert VALID_DB_PASSWORD.decode() not in proc.stdout + proc.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "post_compose_snapshot_bytes",
    [
        pytest.param(b"x" * 4096 + b"\n", id="over-4096-bytes"),
        pytest.param(
            _consumer_snapshot_bytes(
                (BLACKBOX_CONTAINER_ID, "blackbox-exporter")
            ).removesuffix(b"\n"),
            id="missing-final-newline",
        ),
        pytest.param(
            BLACKBOX_CONTAINER_ID.encode() + b"\tblackbox-exporter\xff\n",
            id="non-ascii",
        ),
        pytest.param(
            _consumer_snapshot_bytes(
                (BLACKBOX_CONTAINER_ID, "blackbox-exporter"),
                *((f"{index:064x}", "sidecar") for index in range(1, 65)),
            ),
            id="row-flood-over-byte-cap",
        ),
        pytest.param(
            BLACKBOX_CONTAINER_ID.encode() + b"\tblackbox-exporter\textra\n",
            id="wrong-tab-count",
        ),
        pytest.param(
            _consumer_snapshot_bytes(
                (BLACKBOX_CONTAINER_ID, "blackbox-exporter"),
                (BLACKBOX_CONTAINER_ID, "sidecar"),
            ),
            id="duplicate-container-id",
        ),
        pytest.param(
            _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "-invalid")),
            id="invalid-service-grammar",
        ),
    ],
)
def test_post_compose_consumer_snapshot_rejects_untrusted_bytes(
    tmp_path: Path,
    post_compose_snapshot_bytes: bytes,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_snapshot_bytes_sequence": (
                post_compose_snapshot_bytes,
                None,
            ),
            "post_second_compose_containers": (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
            ),
        },
        curl_options={
            "expected_pair_sequence": ("old", "old"),
            "responses": ("204", "299"),
            "returncodes": (0, 0),
        },
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert proc.returncode == 75
    assert proc.stdout == "mcp-client-rotation result=rolled_back\n"
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 2
    artifacts = [
        _assert_private_dotenv_observation(
            observation,
            "blackbox-exporter",
            expected_phase=phase,
        )
        for observation, phase in zip(
            observations,
            ("activation_started", "rollback_pair_restored"),
            strict=True,
        )
    ]
    calls = _docker_calls(transaction.record)
    snapshot_indices = [
        index for index, call in enumerate(calls) if call == _consumer_snapshot_call()
    ]
    compose_indices = [
        calls.index(list(observation["argv"])) for observation in observations
    ]
    assert len(snapshot_indices) == 3
    assert snapshot_indices[0] < compose_indices[0] < snapshot_indices[1]
    assert snapshot_indices[1] < compose_indices[1] < snapshot_indices[2]
    assert [
        observation["payload_hex"]
        for observation in _snapshot_observations(transaction.record)
    ] == [
        post_compose_snapshot_bytes.hex(),
        _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")).hex(),
    ]
    assert all(not dotenv.exists() for dotenv, _ in artifacts)
    assert all(not receipt.exists() for _, receipt in artifacts)
    assert not _journal_path(transaction).exists()
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    probe_calls = _curl_calls(transaction.probe_record)
    assert len(probe_calls) == 2
    assert all(call["snapshot_count"] == 2 for call in probe_calls)
    assert _blackbox_observations(transaction.record) == [
        _expected_blackbox_observation(
            "rollback_pair_restored",
            0,
            direct_probe_count=2,
            snapshot_count=2,
        )
    ]
    assert VALID_DB_PASSWORD.decode() not in proc.stdout + proc.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in proc.stdout + proc.stderr


def test_post_blackbox_full_set_rejects_unexpected_operator_appearance(
    tmp_path: Path,
) -> None:
    post_compose_containers = (
        (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
        (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
    )
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={
            "post_compose_containers": post_compose_containers,
            "post_second_compose_containers": (
                (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
            ),
        },
        curl_options={
            "expected_pair_sequence": ("old", "old"),
            "responses": ("204", "299"),
            "returncodes": (0, 0),
        },
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 2
    artifacts = [
        _assert_private_dotenv_observation(
            observation,
            "blackbox-exporter",
            expected_phase=phase,
        )
        for observation, phase in zip(
            observations,
            ("activation_started", "rollback_pair_restored"),
            strict=True,
        )
    ]
    calls = _docker_calls(transaction.record)
    snapshot_indices = [
        index for index, call in enumerate(calls) if call == _consumer_snapshot_call()
    ]
    compose_indices = [
        calls.index(list(observation["argv"])) for observation in observations
    ]
    assert len(snapshot_indices) == 3
    assert snapshot_indices[0] < compose_indices[0] < snapshot_indices[1]
    assert snapshot_indices[1] < compose_indices[1] < snapshot_indices[2]
    assert proc.returncode == 75
    assert proc.stdout == "mcp-client-rotation result=rolled_back\n"
    assert all(not dotenv.exists() for dotenv, _ in artifacts)
    assert all(not receipt.exists() for _, receipt in artifacts)
    assert not _journal_path(transaction).exists()
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert [
        observation["payload_hex"]
        for observation in _snapshot_observations(transaction.record)
    ] == [
        _consumer_snapshot_bytes(
            (BLACKBOX_CONTAINER_ID, "blackbox-exporter"),
            (OPERATOR_CONTAINER_ID, "operator"),
        ).hex(),
        _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")).hex(),
    ]
    probe_calls = _curl_calls(transaction.probe_record)
    assert len(probe_calls) == 2
    assert all(call["snapshot_count"] == 2 for call in probe_calls)
    assert _blackbox_observations(transaction.record) == [
        _expected_blackbox_observation(
            "rollback_pair_restored",
            0,
            direct_probe_count=2,
            snapshot_count=2,
        )
    ]
    assert VALID_DB_PASSWORD.decode() not in proc.stdout + proc.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in proc.stdout + proc.stderr


def test_post_operator_full_set_rejects_blackbox_loss(tmp_path: Path) -> None:
    running_consumers = (
        (BLACKBOX_CONTAINER_ID, "infra", "blackbox-exporter", "running"),
        (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
    )
    transaction = _transaction_fixture(
        tmp_path,
        operator_running=True,
        docker_options={
            "containers": running_consumers,
            "post_compose_container_sequence": (
                running_consumers,
                ((OPERATOR_CONTAINER_ID, "infra", "operator", "running"),),
                running_consumers,
                running_consumers,
            ),
        },
        curl_options={
            "expected_pair_sequence": ("old", "old"),
            "responses": ("204", "299"),
            "returncodes": (0, 0),
        },
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    observations = _dotenv_observations(transaction.record)
    assert [observation["argv"][-1] for observation in observations] == [
        "blackbox-exporter",
        "operator",
        "blackbox-exporter",
        "operator",
    ]
    artifacts = [
        _assert_private_dotenv_observation(
            observation,
            service,
            expected_phase=phase,
        )
        for observation, service, phase in zip(
            observations,
            (
                "blackbox-exporter",
                "operator",
                "blackbox-exporter",
                "operator",
            ),
            (
                "activation_started",
                "activation_started",
                "rollback_pair_restored",
                "rollback_pair_restored",
            ),
            strict=True,
        )
    ]
    calls = _docker_calls(transaction.record)
    snapshot_indices = [
        index for index, call in enumerate(calls) if call == _consumer_snapshot_call()
    ]
    compose_indices = [
        calls.index(list(observation["argv"])) for observation in observations
    ]
    assert len(snapshot_indices) == 5
    for index, compose_index in enumerate(compose_indices):
        assert snapshot_indices[index] < compose_index < snapshot_indices[index + 1]
    assert proc.returncode == 75
    assert proc.stdout == "mcp-client-rotation result=rolled_back\n"
    assert all(not dotenv.exists() for dotenv, _ in artifacts)
    assert all(not receipt.exists() for _, receipt in artifacts)
    assert not _journal_path(transaction).exists()
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    both_consumers = _consumer_snapshot_bytes(
        (BLACKBOX_CONTAINER_ID, "blackbox-exporter"),
        (OPERATOR_CONTAINER_ID, "operator"),
    ).hex()
    assert [
        observation["payload_hex"]
        for observation in _snapshot_observations(transaction.record)
    ] == [
        both_consumers,
        _consumer_snapshot_bytes((OPERATOR_CONTAINER_ID, "operator")).hex(),
        both_consumers,
        both_consumers,
    ]
    probe_calls = _curl_calls(transaction.probe_record)
    assert len(probe_calls) == 2
    assert all(call["snapshot_count"] == 4 for call in probe_calls)
    assert _blackbox_observations(transaction.record) == [
        _expected_blackbox_observation(
            "rollback_pair_restored",
            0,
            direct_probe_count=2,
            snapshot_count=4,
        )
    ]
    assert VALID_DB_PASSWORD.decode() not in proc.stdout + proc.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "password",
    [
        pytest.param(b"A" * 16, id="minimum"),
        pytest.param(b"Z" * 512, id="maximum"),
        pytest.param(b"Abcd1234._~!@#$%^&*+=,:/?-", id="allowed-punctuation"),
    ],
)
def test_private_dotenv_accepts_exact_password_grammar_boundaries(
    tmp_path: Path,
    password: bytes,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    _write_compose_passwords(
        transaction.current,
        db_password=password,
        admin_password=password,
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    observations = _dotenv_observations(transaction.record)
    assert observations
    _assert_private_dotenv_observation(
        observations[0],
        "blackbox-exporter",
        expected_dotenv=_expected_dotenv_bytes(password, password),
    )
    assert password.decode() not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "case",
    [
        "too-short",
        "too-long",
        "newline",
        "quote",
        "backslash",
        "whitespace",
        "nul",
        "non-ascii",
        "unsafe-mode",
        "symlink",
    ],
)
@pytest.mark.parametrize("password_name", ["kc_db_pw", "kc_admin_pw"])
def test_private_dotenv_rejects_invalid_password_files_before_rotation(
    tmp_path: Path,
    case: str,
    password_name: str,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    password_path = transaction.current.secrets / password_name
    invalid_values = {
        "too-short": b"A" * 15,
        "too-long": b"A" * 513,
        "newline": (b"A" * 15) + b"\n",
        "quote": (b"A" * 15) + b"'",
        "backslash": (b"A" * 15) + b"\\",
        "whitespace": (b"A" * 15) + b" ",
        "nul": (b"A" * 15) + b"\x00",
        "non-ascii": (b"A" * 15) + b"\xff",
    }
    if case in invalid_values:
        password_path.write_bytes(invalid_values[case])
    elif case == "unsafe-mode":
        password_path.chmod(0o640)
    elif case == "symlink":
        backing = password_path.with_name(f"{password_name}.backing")
        password_path.rename(backing)
        password_path.symlink_to(backing.name)
    else:  # pragma: no cover - parametrization is the closed case set
        raise AssertionError(case)

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert proc.returncode != 0
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert not transaction.record.exists()
    assert not _journal_path(transaction).exists()
    assert _dotenv_observations(transaction.record) == []
    assert VALID_DB_PASSWORD.decode() not in proc.stdout + proc.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in proc.stdout + proc.stderr


def test_private_dotenv_cleanup_refuses_valid_foreign_owner_replacement(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        docker_options={"replace_owner_token_on_compose": FOREIGN_OWNER_TOKEN},
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    observations = _dotenv_observations(transaction.record)
    assert observations
    observation = observations[0]
    dotenv, receipt = _assert_private_dotenv_observation(
        observation,
        "blackbox-exporter",
    )
    foreign_dotenv = dotenv.with_name(f"compose-env.{FOREIGN_OWNER_TOKEN}.tmp")
    replacement_receipt = _strict_json(receipt)
    journal = _strict_json(_journal_path(transaction))
    generations = _generation_paths(transaction, journal)
    expected_receipt = json.loads(json.dumps(observation["receipt"]))
    expected_receipt["compose_env"].update(
        owner_token=FOREIGN_OWNER_TOKEN,
        basename=foreign_dotenv.name,
        quarantine_basename=f"compose-env.{FOREIGN_OWNER_TOKEN}.quarantine",
    )
    assert re.fullmatch(r"[0-9a-f]{64}", FOREIGN_OWNER_TOKEN)
    assert proc.returncode == 74
    assert proc.stdout == "mcp-client-rotation result=rollback_failed\n"
    assert journal["phase"] == "activation_started"
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    assert all(path.exists() for path in generations.values())
    assert not dotenv.exists()
    assert foreign_dotenv.exists()
    assert receipt.exists()
    assert type(replacement_receipt["schema_version"]) is int
    assert replacement_receipt == expected_receipt
    assert os.lstat(foreign_dotenv).st_ino == observation["dotenv_inode"]
    assert VALID_DB_PASSWORD.decode() not in proc.stdout + proc.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in proc.stdout + proc.stderr


def test_startup_preserves_foreign_dotenv_residue_and_fails_closed(
    tmp_path: Path,
) -> None:
    healthy = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=13))
    rotation = _stage_path(healthy).parent
    foreign_dotenv = rotation / f"compose-env.{FOREIGN_OWNER_TOKEN}.tmp"
    foreign_contents = b"foreign-private-data"
    foreign_dotenv.write_bytes(foreign_contents)
    foreign_dotenv.chmod(0o600)
    receipt = rotation / DOTENV_RECEIPT_NAME
    env = _rotator_env(
        healthy,
        tmp_path / "missing-docker",
        _stage_path(healthy, "unused-stage"),
    )

    proc = _run_rotator(env)

    assert proc.returncode == 74
    assert proc.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert proc.stderr == "mcp-client-rotation failed: transaction recovery failed\n"
    assert foreign_dotenv.read_bytes() == foreign_contents
    assert not receipt.exists()


@pytest.mark.parametrize(
    "case",
    [
        "legacy-transaction-v1",
        "legacy-receipt-v1",
        "float-receipt-v2",
    ],
)
def test_private_dotenv_recovery_preserves_artifacts_for_invalid_schema_state(
    tmp_path: Path,
    case: str,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="compose_receipt_link_parent_fsynced",
        ),
        TRANSACTION_ACTION,
    )
    rotation = _stage_path(transaction.current).parent
    receipt = rotation / DOTENV_RECEIPT_NAME
    journal = _journal_path(transaction)
    if case == "legacy-transaction-v1":
        state_path = journal
        state_payload = _strict_json(journal)
        state_payload["schema_version"] = 1
        del state_payload["compose_env"]
    elif case == "legacy-receipt-v1":
        state_path = receipt
        current_receipt = _strict_json(receipt)
        current_compose = current_receipt["compose_env"]
        assert isinstance(current_compose, dict)
        state_payload = {
            field: current_compose[field]
            for field in (
                "owner_token",
                "basename",
                "device",
                "inode",
                "uid",
                "mode",
                "created_at",
            )
        }
        state_payload["schema_version"] = 1
    elif case == "float-receipt-v2":
        state_path = receipt
        state_payload = _strict_json(receipt)
        state_payload["schema_version"] = 2.0
    else:  # pragma: no cover - parametrization is the closed case set
        raise AssertionError(case)
    state_path.write_text(
        json.dumps(state_payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    state_path.chmod(0o600)
    state_bytes = state_path.read_bytes()
    artifacts_before = {
        path.name: path.read_bytes() for path in _compose_env_artifact_paths(rotation)
    }

    recovery_env, _ = _recovery_env(
        tmp_path,
        transaction,
        f"invalid-schema-recovery-{case}",
    )
    rejected = _run_rotator(recovery_env)

    assert interrupted.returncode == 74
    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert (
        rejected.stderr == "mcp-client-rotation failed: transaction recovery failed\n"
    )
    assert {
        path.name: path.read_bytes() for path in _compose_env_artifact_paths(rotation)
    } == artifacts_before
    assert state_path.read_bytes() == state_bytes


def test_startup_preserves_valid_receipt_without_matching_journal(
    tmp_path: Path,
) -> None:
    healthy = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=13))
    dotenv, receipt = _write_dotenv_residue(healthy)
    artifact_bytes = {
        dotenv.name: dotenv.read_bytes(),
        receipt.name: receipt.read_bytes(),
    }
    env = _rotator_env(
        healthy,
        tmp_path / "missing-docker",
        _stage_path(healthy, "unused-stage"),
    )

    rejected = _run_rotator(env)

    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert (
        rejected.stderr == "mcp-client-rotation failed: transaction recovery failed\n"
    )
    assert not (dotenv.parent / TRANSACTION_JOURNAL).exists()
    assert {
        path.name: path.read_bytes() for path in (dotenv, receipt)
    } == artifact_bytes


def test_private_dotenv_recovery_rejects_compose_state_outside_activation_phase(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="compose_receipt_link_parent_fsynced",
        ),
        TRANSACTION_ACTION,
    )
    rotation = _stage_path(transaction.current).parent
    journal = _journal_path(transaction)
    journal_payload = _strict_json(journal)
    assert isinstance(journal_payload["compose_env"], dict)
    journal_payload["phase"] = "pair_published"
    journal.write_text(
        json.dumps(journal_payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    journal.chmod(0o600)
    journal_bytes = journal.read_bytes()
    artifacts_before = {
        path.name: path.read_bytes() for path in _compose_env_artifact_paths(rotation)
    }

    recovery_env, _ = _recovery_env(
        tmp_path,
        transaction,
        "invalid-compose-phase-recovery",
    )
    rejected = _run_rotator(recovery_env)

    assert interrupted.returncode == 74
    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert (
        rejected.stderr == "mcp-client-rotation failed: transaction recovery failed\n"
    )
    assert journal.read_bytes() == journal_bytes
    assert {
        path.name: path.read_bytes() for path in _compose_env_artifact_paths(rotation)
    } == artifacts_before


@pytest.mark.parametrize(
    ("interrupt_after", "expected_state"),
    [
        pytest.param("compose_env_planned", "planned", id="journal-planned"),
        pytest.param("compose_dotenv_created", "planned", id="dotenv-created"),
        pytest.param("compose_env_owned", "owned", id="journal-owned"),
        pytest.param("compose_payload_written", "owned", id="payload-written"),
        pytest.param(
            "compose_dotenv_payload_fsynced",
            "owned",
            id="payload-fsynced",
        ),
        pytest.param("compose_env_ready", "ready", id="journal-ready"),
        pytest.param(
            "compose_receipt_partial_written",
            "ready",
            id="receipt-partial-written",
        ),
        pytest.param(
            "compose_receipt_temp_fsynced",
            "ready",
            id="receipt-temp-fsynced",
        ),
        pytest.param("compose_receipt_linked", "ready", id="receipt-linked"),
        pytest.param(
            "compose_receipt_temp_unlinked",
            "ready",
            id="receipt-temp-unlinked",
        ),
        pytest.param(
            "compose_receipt_link_parent_fsynced",
            "ready",
            id="receipt-link-parent-fsynced",
        ),
        pytest.param("compose_receipt_durable", "ready", id="receipt-durable"),
        pytest.param("compose_env_cleanup", "cleanup", id="journal-cleanup"),
        pytest.param(
            "compose_dotenv_quarantined",
            "cleanup",
            id="dotenv-quarantined",
        ),
        pytest.param(
            "compose_dotenv_quarantine_parent_fsynced",
            "cleanup",
            id="dotenv-quarantine-parent-fsynced",
        ),
        pytest.param(
            "compose_dotenv_unlinked",
            "cleanup",
            id="dotenv-unlinked",
        ),
        pytest.param(
            "compose_dotenv_unlink_parent_fsynced",
            "cleanup",
            id="dotenv-unlink-parent-fsynced",
        ),
        pytest.param(
            "compose_receipt_quarantined",
            "cleanup",
            id="receipt-quarantined",
        ),
        pytest.param(
            "compose_receipt_quarantine_parent_fsynced",
            "cleanup",
            id="receipt-quarantine-parent-fsynced",
        ),
        pytest.param(
            "compose_receipt_unlinked",
            "cleanup",
            id="receipt-unlinked",
        ),
        pytest.param(
            "compose_receipt_unlink_parent_fsynced",
            "cleanup",
            id="receipt-unlink-parent-fsynced",
        ),
        pytest.param("compose_env_cleared", None, id="journal-cleared"),
    ],
)
def test_private_dotenv_crash_windows_recover_only_from_transaction_journal(
    tmp_path: Path,
    interrupt_after: str,
    expected_state: str | None,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        curl_options={"expected_pair_sequence": ("old", "old")},
    )
    rotation = _stage_path(transaction.current).parent
    foreign = rotation / "foreign-data.keep"
    foreign.write_bytes(b"foreign-data-must-survive")
    foreign.chmod(0o600)

    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after=interrupt_after),
        TRANSACTION_ACTION,
    )

    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["schema_version"] == 2
    assert journal["phase"] in {"activation_started", "rollback_pair_restored"}
    if journal["phase"] == "activation_started":
        assert interrupted.returncode == 86
        assert interrupted.stdout == ""
        assert (
            transaction.current.bundle.read_bytes()
            == transaction.staged.bundle.read_bytes()
        )
        assert (
            transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
        )
    else:
        assert interrupted.returncode == 74
        assert interrupted.stdout == "mcp-client-rotation result=rollback_failed\n"
        assert transaction.current.bundle.read_bytes() == transaction.old_cert
        assert transaction.current.key.read_bytes() == transaction.old_key
    compose_env = journal["compose_env"]
    if expected_state is None:
        assert compose_env is None
    else:
        assert isinstance(compose_env, dict)
        assert set(compose_env) == COMPOSE_ENV_FIELDS
        assert compose_env["schema_version"] == 1
        assert compose_env["state"] == expected_state
        token = compose_env["owner_token"]
        assert isinstance(token, str) and re.fullmatch(r"[0-9a-f]{64}", token)
        assert compose_env["basename"] == f"compose-env.{token}.tmp"
        quarantine = compose_env["quarantine_basename"]
        assert isinstance(quarantine, str) and quarantine != compose_env["basename"]
        created_at = compose_env["created_at"]
        assert isinstance(created_at, str) and created_at.endswith("Z")
        if expected_state == "planned":
            for field in ("device", "inode", "uid", "mode", "nlink"):
                assert compose_env[field] is None
        else:
            assert type(compose_env["device"]) is int
            assert type(compose_env["inode"]) is int and compose_env["inode"] > 0
            assert compose_env["uid"] == os.getuid()
            assert compose_env["mode"] == 0o600
            assert compose_env["nlink"] == 1
    generations = _generation_paths(transaction, journal)
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    assert foreign.read_bytes() == b"foreign-data-must-survive"

    issuance_calls = [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ]
    assert len(issuance_calls) == 1
    recovered = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert recovered.returncode == 75
    assert recovered.stdout == "mcp-client-rotation result=rolled_back\n"
    assert recovered.stderr == ""
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    assert not journal_path.exists()
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_bytes)
    assert _compose_env_artifact_paths(rotation) == []
    assert foreign.read_bytes() == b"foreign-data-must-survive"
    assert [
        call
        for call in _docker_calls(transaction.record)
        if "ca" in call and "certificate" in call
    ] == issuance_calls
    observations = _dotenv_observations(transaction.record)
    assert observations
    assert observations[-1]["journal"]["phase"] == "rollback_pair_restored"
    for observation in observations:
        phase = str(observation["journal"]["phase"])
        assert phase in {"activation_started", "rollback_pair_restored"}
        _assert_private_dotenv_observation(
            observation,
            "blackbox-exporter",
            expected_phase=phase,
        )
    artifacts = [
        (Path(str(observation["dotenv_path"])), Path(str(observation["receipt_path"])))
        for observation in observations
    ]
    assert all(not dotenv.exists() for dotenv, _ in artifacts)
    assert all(not receipt.exists() for _, receipt in artifacts)
    probe_calls = _curl_calls(transaction.probe_record)
    assert len(probe_calls) == 2
    assert all(
        call["materials"] == {"root": True, "cert": True, "key": True}
        for call in probe_calls
    )
    snapshot_count = len(_snapshot_observations(transaction.record))
    assert snapshot_count >= 1
    assert all(call["snapshot_count"] == snapshot_count for call in probe_calls)
    assert _blackbox_observations(transaction.record) == [
        _expected_blackbox_observation(
            "rollback_pair_restored",
            0,
            direct_probe_count=2,
            snapshot_count=snapshot_count,
        )
    ]
    combined_output = (
        interrupted.stdout + interrupted.stderr + recovered.stdout + recovered.stderr
    )
    assert VALID_DB_PASSWORD.decode() not in combined_output
    assert VALID_ADMIN_PASSWORD.decode() not in combined_output


def test_private_dotenv_partial_receipt_recovery_survives_restrictive_umask(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(
        tmp_path,
        curl_options={"expected_pair_sequence": ("old", "old")},
    )
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="compose_receipt_partial_written",
        ),
        TRANSACTION_ACTION,
        child_umask=0o777,
    )
    assert interrupted.returncode == 74, (interrupted.stdout, interrupted.stderr)
    assert interrupted.stdout == "mcp-client-rotation result=rollback_failed\n"
    assert interrupted.stderr == (
        "mcp-client-rotation failed: blackbox exporter rollback recreation failed\n"
    )

    rotation = _stage_path(transaction.current).parent
    journal = _strict_json(_journal_path(transaction))
    assert journal["phase"] == "rollback_pair_restored"
    assert transaction.current.bundle.read_bytes() == transaction.old_cert
    assert transaction.current.key.read_bytes() == transaction.old_key
    compose_env = journal["compose_env"]
    assert isinstance(compose_env, dict)
    partial_receipt = rotation / (
        f".compose-env-owner.{journal['transaction_id']}."
        f"{compose_env['owner_token']}.tmp"
    )

    assert partial_receipt.exists()
    assert os.lstat(partial_receipt).st_mode & 0o777 == 0o600

    generations = _generation_paths(transaction, journal)
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    recovered = _run_rotator(transaction.env, TRANSACTION_ACTION)

    _assert_completed_rollback(
        transaction,
        recovered,
        services=("blackbox-exporter",),
        phases=("rollback_pair_restored",),
        snapshots=(
            _consumer_snapshot_bytes((BLACKBOX_CONTAINER_ID, "blackbox-exporter")),
        ),
        probe_snapshot_counts=(1, 1),
        blackbox_observations=[
            _expected_blackbox_observation(
                "rollback_pair_restored",
                0,
                direct_probe_count=2,
                snapshot_count=1,
            )
        ],
    )
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_bytes)
    assert _compose_env_artifact_paths(rotation) == []


def test_private_dotenv_recovery_rejects_receipt_from_another_transaction(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="compose_receipt_link_parent_fsynced",
        ),
        TRANSACTION_ACTION,
    )
    rotation = _stage_path(transaction.current).parent
    receipt = rotation / DOTENV_RECEIPT_NAME
    receipt_payload = _strict_json(receipt)
    journal_payload = _strict_json(_journal_path(transaction))
    assert receipt_payload["transaction_id"] == journal_payload["transaction_id"]
    receipt_payload["transaction_id"] = (
        "d" * 32 if journal_payload["transaction_id"] != "d" * 32 else "c" * 32
    )
    receipt.write_text(
        json.dumps(receipt_payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    receipt.chmod(0o600)
    artifacts_before = {
        path.name: path.read_bytes() for path in _compose_env_artifact_paths(rotation)
    }

    recovery_env, _ = _recovery_env(
        tmp_path,
        transaction,
        "mismatched-receipt-recovery",
    )
    rejected = _run_rotator(recovery_env)

    assert interrupted.returncode == 74
    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert (
        rejected.stderr == "mcp-client-rotation failed: transaction recovery failed\n"
    )
    assert _strict_json(_journal_path(transaction)) == journal_payload
    assert {
        path.name: path.read_bytes() for path in _compose_env_artifact_paths(rotation)
    } == artifacts_before


@pytest.mark.parametrize("target_kind", ["dotenv", "receipt"])
def test_private_dotenv_recovery_preserves_unrecognized_owner_hardlink(
    tmp_path: Path,
    target_kind: str,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="compose_receipt_link_parent_fsynced",
        ),
        TRANSACTION_ACTION,
    )
    rotation = _stage_path(transaction.current).parent
    receipt = rotation / DOTENV_RECEIPT_NAME
    receipt_payload = _strict_json(receipt)
    compose_env = receipt_payload["compose_env"]
    assert isinstance(compose_env, dict)
    dotenv = rotation / str(compose_env["basename"])
    target = dotenv if target_kind == "dotenv" else receipt
    alias = rotation / f"foreign-{target_kind}-alias.keep"
    os.link(target, alias)
    journal_bytes = _journal_path(transaction).read_bytes()
    artifact_bytes = {
        path.name: path.read_bytes() for path in _compose_env_artifact_paths(rotation)
    }

    recovery_env, _ = _recovery_env(
        tmp_path,
        transaction,
        f"{target_kind}-hardlink-recovery",
    )
    rejected = _run_rotator(recovery_env)

    assert interrupted.returncode == 74
    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert (
        rejected.stderr == "mcp-client-rotation failed: transaction recovery failed\n"
    )
    assert target.stat().st_nlink == alias.stat().st_nlink == 2
    assert target.read_bytes() == alias.read_bytes()
    assert _journal_path(transaction).read_bytes() == journal_bytes
    assert {
        path.name: path.read_bytes() for path in _compose_env_artifact_paths(rotation)
    } == artifact_bytes


def test_private_dotenv_cleanup_quarantines_then_preserves_same_uid_replacement_race(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(tmp_path)

    proc = _run_rotator(
        _fault_env(transaction.env, swap_dotenv_after_validation=True),
        TRANSACTION_ACTION,
    )

    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 1
    observation = observations[0]
    dotenv, receipt = _assert_private_dotenv_observation(
        observation,
        "blackbox-exporter",
    )
    replacement_stat = os.lstat(dotenv)
    receipt_payload = _strict_json(receipt)
    journal = _strict_json(_journal_path(transaction))
    compose_env = journal["compose_env"]
    assert isinstance(compose_env, dict)
    assert proc.returncode == 74
    assert proc.stdout == "mcp-client-rotation result=rollback_failed\n"
    assert dotenv.read_bytes() == SAME_UID_REPLACEMENT
    assert replacement_stat.st_uid == os.getuid()
    assert replacement_stat.st_mode & 0o777 == 0o600
    assert replacement_stat.st_nlink == 1
    assert replacement_stat.st_dev == observation["dotenv_device"]
    assert replacement_stat.st_ino != observation["dotenv_inode"]
    receipt_compose = receipt_payload["compose_env"]
    assert isinstance(receipt_compose, dict)
    assert receipt_compose["device"] == observation["dotenv_device"]
    assert receipt_compose["inode"] == observation["dotenv_inode"]
    assert receipt_payload["transaction_id"] == journal["transaction_id"]
    assert journal["phase"] == "activation_started"
    assert compose_env["state"] == "cleanup"
    assert compose_env["device"] == observation["dotenv_device"]
    assert compose_env["inode"] == observation["dotenv_inode"]
    assert compose_env["nlink"] == 1
    assert not (dotenv.parent / str(compose_env["quarantine_basename"])).exists()
    assert {path.name for path in _compose_env_artifact_paths(dotenv.parent)} == {
        dotenv.name,
        receipt.name,
    }
    assert VALID_DB_PASSWORD.decode() not in proc.stdout + proc.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in proc.stdout + proc.stderr
