from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


REPO = Path(__file__).resolve().parents[1]
ROTATOR = REPO / "infra" / "scripts" / "rotate-production-mcp-client-cert.sh"
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
    post_compose_snapshot_bytes: bytes | None = None,
    fail_post_compose_snapshot: bool = False,
    replace_owner_token_on_compose: str | None = None,
    blackbox_query_returncode: int = 0,
    blackbox_sample_age_seconds: float = 0.0,
    blackbox_sample_at_last_snapshot: bool = False,
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
        if {post_compose_snapshot_bytes!r} is not None:
            payload = {post_compose_snapshot_bytes!r}
        compose_observations = record.with_name("dotenv-observations.jsonl")
        compose_observation = json.loads(
            compose_observations.read_text(encoding="utf-8").splitlines()[-1]
        )
        snapshot_observations = record.with_name("snapshot-observations.jsonl")
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
    raise SystemExit(
        42 if compose_transition.exists() and {fail_post_compose_snapshot!r} else 0
    )
if args in blackbox_probe_calls:
    if not compose_transition.exists() or direct_probe_record is None:
        raise SystemExit(95)
    probe_path = Path(direct_probe_record)
    if not probe_path.exists() or len(
        probe_path.read_text(encoding="utf-8").splitlines()
    ) != 2:
        raise SystemExit(96)
if args == blackbox_probe_calls[0]:
    print({CADDY_CONTAINER_ID!r})
    raise SystemExit(0)
if args == blackbox_probe_calls[1]:
    raise SystemExit(0)
if args == blackbox_probe_calls[2]:
    if {blackbox_query_returncode!r} != 0:
        raise SystemExit({blackbox_query_returncode!r})
    query_time = time.time()
    if {blackbox_sample_at_first_direct_probe!r}:
        sample_time = probe_path.with_name("first-direct-probe-epoch").read_text(
            encoding="ascii"
        )
    elif {blackbox_sample_at_last_snapshot!r}:
        sample_time = last_snapshot_epoch.read_text(encoding="ascii")
    else:
        sample_time = str(query_time - {blackbox_sample_age_seconds!r})
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
    if compose_transition.exists():
        second_compose_transition.touch()
    else:
        compose_transition.touch()
    raise SystemExit(0)
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
    responses: tuple[str, ...] = ("200", "200"),
    returncodes: tuple[int, ...] = (0, 0),
    child_canary: str = "",
) -> tuple[Path, Path]:
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


def argument_after(flag: str) -> str:
    index = args.index(flag)
    return args[index + 1]


materials = {{
    "root": Path(argument_after("--cacert")).read_bytes()
    == Path({str(expected.root)!r}).read_bytes(),
    "cert": Path(argument_after("--cert")).read_bytes()
    == Path({str(expected.bundle)!r}).read_bytes(),
    "key": Path(argument_after("--key")).read_bytes()
    == Path({str(expected.key)!r}).read_bytes(),
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


def _rotator_env(fixture: TlsFixture, docker: Path, stage: Path) -> dict[str, str]:
    return {
        **os.environ,
        "AWS_SECRET_ACCESS_KEY": "ambient-env-canary-must-not-leak",
        "MNEMO_SECRETS_DIR": str(fixture.secrets),
        "MCP_CLIENT_ROTATOR_COMPOSE_FILE": str(COMPOSE),
        "MCP_CLIENT_ROTATOR_DOCKER_BIN": str(docker),
        "MCP_CLIENT_ROTATOR_STAGE_DIR": str(stage),
    }


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
                "schema_version": 1,
                "blackbox_exporter_was_running": blackbox_running,
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
) -> RotationTransactionFixture:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8), stem="current")
    _write_compose_passwords(current)
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    curl, probe_record = _write_fake_curl(tmp_path, staged, **(curl_options or {}))
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
) -> tuple[Path, Path]:
    dotenv = Path(str(observation["dotenv_path"]))
    receipt_path = Path(str(observation["receipt_path"]))
    receipt = observation["receipt"]
    journal = observation["journal"]
    assert isinstance(receipt, dict)
    assert isinstance(journal, dict)
    assert set(journal) == TRANSACTION_FIELDS
    assert journal["schema_version"] == 2
    assert journal["phase"] == "activation_started"
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


def _run_rotator(
    env: dict[str, str],
    *args: str,
    child_umask: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROTATOR), *args],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=15,
        check=False,
        umask=-1 if child_umask is None else child_umask,
    )


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

    proc = _run_rotator(_rotator_env(current, docker, stage))

    assert proc.returncode == 0, proc.stderr
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
    transaction = _transaction_fixture(tmp_path)

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

        stopped = _run_rotator(transaction.env, TRANSACTION_ACTION)

        assert stopped.returncode == 74
        assert stopped.stdout == "mcp-client-rotation result=recovery_failed\n"
        assert _strict_json(_journal_path(transaction))["phase"] == "committed"
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
    canonical_cert = transaction.current.bundle.read_bytes()
    canonical_key = transaction.current.key.read_bytes()

    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        "rejected-recovery",
    )
    rejected = _run_rotator(recovery_env)

    assert rejected.returncode == 74
    assert rejected.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert os.path.lexists(journal_path)
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


def test_activation_started_is_durable_before_first_consumer_and_resume_fails_closed(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(tmp_path)

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
    journal_bytes = journal_path.read_bytes()
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

    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        "activation-started-recovery",
    )
    recovery_stage = Path(recovery_env["MCP_CLIENT_ROTATOR_STAGE_DIR"])
    recovered = _run_rotator(recovery_env)

    assert recovered.returncode == 74
    assert recovered.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert recovered.stderr == (
        "mcp-client-rotation failed: activation transaction requires verified "
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
    assert not recovery_stage.exists()


def test_fixture_runs_fresh_blackbox_probe_after_direct_probes_and_retains_commit(
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

    stopped = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert stopped.returncode == 74
    assert stopped.stdout == "mcp-client-rotation result=recovery_failed\n"
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == "committed"
    assert journal["compose_env"] is None
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    generations = _generation_paths(transaction, journal)
    journal_bytes = journal_path.read_bytes()
    generation_bytes = {path: path.read_bytes() for path in generations.values()}
    observations = _dotenv_observations(transaction.record)
    assert [str(observation["argv"][-1]) for observation in observations] == [
        "blackbox-exporter"
    ]
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

    probe_calls = _curl_calls(transaction.probe_record)
    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        "committed-recovery",
    )
    recovery_stage = Path(recovery_env["MCP_CLIENT_ROTATOR_STAGE_DIR"])
    recovered = _run_rotator(recovery_env)

    assert recovered.returncode == 74
    assert recovered.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert recovered.stderr == (
        "mcp-client-rotation failed: committed transaction requires verified "
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
    assert _curl_calls(transaction.probe_record) == probe_calls
    assert not recovery_stage.exists()


def test_committed_is_durable_after_all_probes_and_resume_fails_closed(
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
    assert _compose_env_artifact_paths(journal_path.parent) == []
    assert len(_curl_calls(transaction.probe_record)) == 2
    assert all(
        call in _docker_calls(transaction.record) for call in _blackbox_probe_calls()
    )
    generations = _generation_paths(transaction, journal)
    journal_bytes = journal_path.read_bytes()
    generation_bytes = {path: path.read_bytes() for path in generations.values()}

    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        "committed-interrupt-recovery",
    )
    recovered = _run_rotator(recovery_env)

    assert recovered.returncode == 74
    assert recovered.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert recovered.stderr == (
        "mcp-client-rotation failed: committed transaction requires verified "
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
    committed = _run_rotator(transaction.env, TRANSACTION_ACTION)
    assert committed.returncode == 74
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
        pytest.param({"blackbox_query_returncode": 42}, False, id="transport"),
        pytest.param(
            {"blackbox_sample_at_last_snapshot": True},
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
                "blackbox_sample_at_last_snapshot": True,
            },
            True,
            id="operator-final-snapshot",
        ),
        pytest.param(
            {"blackbox_sample_age_seconds": 30.0},
            False,
            id="fresh-before-boundary",
        ),
        pytest.param(
            {"blackbox_sample_age_seconds": 300.0},
            False,
            id="stale",
        ),
    ],
)
def test_fixture_blackbox_failure_retains_precommit_recovery_evidence(
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
        curl_options={"responses": ("204", "299")},
        operator_running=operator_running,
    )

    failed = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert failed.returncode == 74
    assert failed.stdout == "mcp-client-rotation result=publication_failed\n"
    assert failed.stderr == "mcp-client-rotation failed: blackbox probe failed\n"
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["phase"] == "activation_started"
    assert journal["compose_env"] is None
    assert "committed" not in journal_path.read_text(encoding="utf-8")
    assert len(_curl_calls(transaction.probe_record)) == 2
    docker_calls = _docker_calls(transaction.record)
    assert docker_calls[-3:] == _blackbox_probe_calls()
    assert all(docker_calls.count(call) == 1 for call in _blackbox_probe_calls())

    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        "blackbox-failure-recovery",
    )
    recovered = _run_rotator(recovery_env)

    assert recovered.returncode == 74
    assert recovered.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert recovered.stderr == (
        "mcp-client-rotation failed: activation transaction requires verified "
        "runtime recovery\n"
    )
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    assert journal_path.exists()
    assert _docker_calls(recovery_record) == []


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
            )
        },
        curl_options={
            "responses": responses,
            "returncodes": returncodes,
            "child_canary": child_canary,
        },
    )

    failed = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert failed.returncode == 74
    assert failed.stdout == "mcp-client-rotation result=publication_failed\n"
    assert failed.stderr == "mcp-client-rotation failed: direct probe failed\n"
    assert child_canary not in failed.stdout
    assert child_canary not in failed.stderr
    calls = _curl_calls(transaction.probe_record)
    assert [call["argv"] for call in calls] == [
        _direct_probe_call(transaction.current, route) for route in expected_routes
    ]
    assert all(
        call["materials"] == {"cert": True, "key": True, "root": True} for call in calls
    )
    assert all(call["snapshot_count"] == 1 for call in calls)
    journal_path = _journal_path(transaction)
    assert _strict_json(journal_path)["phase"] == "activation_started"
    assert "committed" not in journal_path.read_text(encoding="utf-8")
    assert not any(
        call in _blackbox_probe_calls() for call in _docker_calls(transaction.record)
    )

    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        "direct-probe-failure-recovery",
    )
    recovered = _run_rotator(recovery_env)

    assert recovered.returncode == 74
    assert recovered.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert recovered.stderr == (
        "mcp-client-rotation failed: activation transaction requires verified "
        "runtime recovery\n"
    )
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    assert journal_path.exists()
    assert _docker_calls(recovery_record) == []


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
        docker_options={"post_compose_containers": post_compose_containers},
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert proc.returncode == 74
    assert proc.stdout == "mcp-client-rotation result=publication_failed\n"
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 1
    dotenv, receipt = _assert_private_dotenv_observation(
        observations[0],
        "blackbox-exporter",
    )
    calls = _docker_calls(transaction.record)
    snapshot_indices = [
        index for index, call in enumerate(calls) if call == _consumer_snapshot_call()
    ]
    compose_index = calls.index(list(observations[0]["argv"]))
    assert len(snapshot_indices) == 2
    assert snapshot_indices[0] < compose_index < snapshot_indices[1]
    assert not dotenv.exists()
    assert not receipt.exists()
    journal_path = _journal_path(transaction)
    assert _strict_json(journal_path)["phase"] == "activation_started"
    assert "committed" not in journal_path.read_text(encoding="utf-8")
    assert VALID_DB_PASSWORD.decode() not in proc.stdout + proc.stderr
    assert VALID_ADMIN_PASSWORD.decode() not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    ("docker_options", "expected_snapshot_bytes"),
    [
        pytest.param(
            {"fail_post_compose_snapshot": True},
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
        docker_options=docker_options,
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert proc.returncode == 74
    assert proc.stdout == "mcp-client-rotation result=publication_failed\n"
    assert (
        proc.stderr == "mcp-client-rotation failed: consumer set validation failed "
        "after blackbox exporter activation\n"
    )
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 1
    dotenv, receipt = _assert_private_dotenv_observation(
        observations[0],
        "blackbox-exporter",
    )
    calls = _docker_calls(transaction.record)
    snapshot_indices = [
        index for index, call in enumerate(calls) if call == _consumer_snapshot_call()
    ]
    compose_index = calls.index(list(observations[0]["argv"]))
    assert len(snapshot_indices) == 2
    assert snapshot_indices[0] < compose_index < snapshot_indices[1]
    assert calls[compose_index + 1 :] == [_consumer_snapshot_call()]
    assert _snapshot_observations(transaction.record)[0]["payload_hex"] == (
        expected_snapshot_bytes.hex()
    )
    assert not dotenv.exists()
    assert not receipt.exists()
    assert _strict_json(_journal_path(transaction))["compose_env"] is None
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
        docker_options={"post_compose_snapshot_bytes": post_compose_snapshot_bytes},
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    assert proc.returncode == 74
    assert proc.stdout == "mcp-client-rotation result=publication_failed\n"
    assert (
        proc.stderr == "mcp-client-rotation failed: consumer set validation failed "
        "after blackbox exporter activation\n"
    )
    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 1
    dotenv, receipt = _assert_private_dotenv_observation(
        observations[0],
        "blackbox-exporter",
    )
    calls = _docker_calls(transaction.record)
    snapshot_indices = [
        index for index, call in enumerate(calls) if call == _consumer_snapshot_call()
    ]
    compose_index = calls.index(list(observations[0]["argv"]))
    assert len(snapshot_indices) == 2
    assert snapshot_indices[0] < compose_index < snapshot_indices[1]
    assert calls[compose_index + 1 :] == [_consumer_snapshot_call()]
    assert _snapshot_observations(transaction.record)[0]["payload_hex"] == (
        post_compose_snapshot_bytes.hex()
    )
    assert not dotenv.exists()
    assert not receipt.exists()
    assert _strict_json(_journal_path(transaction))["compose_env"] is None
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
        docker_options={"post_compose_containers": post_compose_containers},
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    observations = _dotenv_observations(transaction.record)
    assert len(observations) == 1
    dotenv, receipt = _assert_private_dotenv_observation(
        observations[0],
        "blackbox-exporter",
    )
    calls = _docker_calls(transaction.record)
    snapshot_indices = [
        index for index, call in enumerate(calls) if call == _consumer_snapshot_call()
    ]
    compose_index = calls.index(list(observations[0]["argv"]))
    assert len(snapshot_indices) == 2
    assert snapshot_indices[0] < compose_index < snapshot_indices[1]
    assert proc.returncode == 74
    assert proc.stdout == "mcp-client-rotation result=publication_failed\n"
    assert (
        proc.stderr == "mcp-client-rotation failed: consumer set validation failed "
        "after blackbox exporter activation\n"
    )
    assert not dotenv.exists()
    assert not receipt.exists()
    assert _strict_json(_journal_path(transaction))["compose_env"] is None
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
            "post_compose_containers": running_consumers,
            "post_second_compose_containers": (
                (OPERATOR_CONTAINER_ID, "infra", "operator", "running"),
            ),
        },
    )

    proc = _run_rotator(transaction.env, TRANSACTION_ACTION)

    observations = _dotenv_observations(transaction.record)
    assert [observation["argv"][-1] for observation in observations] == [
        "blackbox-exporter",
        "operator",
    ]
    artifacts = [
        _assert_private_dotenv_observation(observation, service)
        for observation, service in zip(
            observations,
            ("blackbox-exporter", "operator"),
            strict=True,
        )
    ]
    calls = _docker_calls(transaction.record)
    snapshot_indices = [
        index for index, call in enumerate(calls) if call == _consumer_snapshot_call()
    ]
    blackbox_compose_index = calls.index(list(observations[0]["argv"]))
    operator_compose_index = calls.index(list(observations[1]["argv"]))
    assert len(snapshot_indices) == 3
    assert snapshot_indices[0] < blackbox_compose_index < snapshot_indices[1]
    assert snapshot_indices[1] < operator_compose_index < snapshot_indices[2]
    assert proc.returncode == 74
    assert proc.stdout == "mcp-client-rotation result=publication_failed\n"
    assert (
        proc.stderr == "mcp-client-rotation failed: consumer set validation failed "
        "after operator activation\n"
    )
    assert all(not dotenv.exists() for dotenv, _ in artifacts)
    assert all(not receipt.exists() for _, receipt in artifacts)
    assert _strict_json(_journal_path(transaction))["compose_env"] is None
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
    expected_receipt = json.loads(json.dumps(observation["receipt"]))
    expected_receipt["compose_env"].update(
        owner_token=FOREIGN_OWNER_TOKEN,
        basename=foreign_dotenv.name,
        quarantine_basename=f"compose-env.{FOREIGN_OWNER_TOKEN}.quarantine",
    )
    assert re.fullmatch(r"[0-9a-f]{64}", FOREIGN_OWNER_TOKEN)
    assert proc.returncode == 74
    assert proc.stdout == "mcp-client-rotation result=publication_failed\n"
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
    transaction = _transaction_fixture(tmp_path)
    rotation = _stage_path(transaction.current).parent
    foreign = rotation / "foreign-data.keep"
    foreign.write_bytes(b"foreign-data-must-survive")
    foreign.chmod(0o600)

    interrupted = _run_rotator(
        _fault_env(transaction.env, interrupt_after=interrupt_after),
        TRANSACTION_ACTION,
    )

    assert interrupted.returncode == 74
    assert interrupted.stdout == "mcp-client-rotation result=publication_failed\n"
    journal_path = _journal_path(transaction)
    journal = _strict_json(journal_path)
    assert journal["schema_version"] == 2
    assert journal["phase"] == "activation_started"
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

    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        f"dotenv-crash-recovery-{interrupt_after}",
    )
    recovered = _run_rotator(recovery_env)

    assert recovered.returncode == 74
    assert recovered.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert recovered.stderr == (
        "mcp-client-rotation failed: activation transaction requires verified "
        "runtime recovery\n"
    )
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    recovered_journal = _strict_json(journal_path)
    assert recovered_journal["phase"] == "activation_started"
    assert recovered_journal["compose_env"] is None
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_bytes)
    assert _compose_env_artifact_paths(rotation) == []
    assert foreign.read_bytes() == b"foreign-data-must-survive"
    assert _docker_calls(recovery_record) == []
    combined_output = (
        interrupted.stdout + interrupted.stderr + recovered.stdout + recovered.stderr
    )
    assert VALID_DB_PASSWORD.decode() not in combined_output
    assert VALID_ADMIN_PASSWORD.decode() not in combined_output


def test_private_dotenv_partial_receipt_recovery_survives_restrictive_umask(
    tmp_path: Path,
) -> None:
    transaction = _transaction_fixture(tmp_path)
    interrupted = _run_rotator(
        _fault_env(
            transaction.env,
            interrupt_after="compose_receipt_partial_written",
        ),
        TRANSACTION_ACTION,
        child_umask=0o777,
    )
    assert interrupted.returncode == 74, (interrupted.stdout, interrupted.stderr)

    rotation = _stage_path(transaction.current).parent
    journal = _strict_json(_journal_path(transaction))
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
    recovery_env, recovery_record = _recovery_env(
        tmp_path,
        transaction,
        "restrictive-umask-recovery",
    )
    recovered = _run_rotator(recovery_env)

    assert recovered.returncode == 74
    assert recovered.stdout == "mcp-client-rotation result=recovery_failed\n"
    assert recovered.stderr == (
        "mcp-client-rotation failed: activation transaction requires verified "
        "runtime recovery\n"
    )
    recovered_journal = _strict_json(_journal_path(transaction))
    assert recovered_journal["phase"] == "activation_started"
    assert recovered_journal["compose_env"] is None
    assert (
        transaction.current.bundle.read_bytes()
        == transaction.staged.bundle.read_bytes()
    )
    assert transaction.current.key.read_bytes() == transaction.staged.key.read_bytes()
    assert all(path.read_bytes() == generation_bytes[path] for path in generation_bytes)
    assert _compose_env_artifact_paths(rotation) == []
    assert _docker_calls(recovery_record) == []


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
    assert proc.stdout == "mcp-client-rotation result=publication_failed\n"
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
