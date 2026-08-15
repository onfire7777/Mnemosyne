"""Local object storage for large and multimodal evidence payloads."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, Sequence
from urllib.parse import urlsplit

from mnemosyne.command_line import split_command

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mnemosyne.ids import bytes_cid
from mnemosyne.models import Resource
from mnemosyne.network_safety import safe_urlopen, validate_fetch_url


@dataclass(frozen=True, slots=True)
class ObjectRecord:
    tenant_id: str
    cid: str
    uri: str
    kind: str
    media_type: str
    byte_length: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_resource(self) -> Resource:
        return Resource(
            tenant_id=self.tenant_id,
            kind=self.kind,
            uri=self.uri,
            content_hash=self.cid,
            metadata={
                **self.metadata,
                "media_type": self.media_type,
                "byte_length": self.byte_length,
            },
            access_policy={"tenant": self.tenant_id},
        )


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically via a per-writer unique temp file.

    The content-addressed object stores can be written concurrently by several
    processes targeting the same CID (e.g. a test runner alongside a background
    consolidation session, both materialising ``.mnemosyne/objects``). A shared
    ``<cid>.tmp`` name made the second ``os.replace`` raise ``FileNotFoundError``
    once the first writer consumed the temp; a unique temp per writer keeps each
    replace independent and idempotent — whichever writer wins, the bytes are
    identical because the name is the content hash.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


class LocalObjectStore:
    """Content-addressed filesystem object store.

    The store only accepts CIDs that it computes itself, and read paths are
    derived from those CIDs. That keeps object lookup deterministic and avoids
    user-controlled path traversal.
    """

    uri_prefix = "local-object://sha256/"

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def put_bytes(
        self,
        data: bytes,
        tenant_id: str,
        kind: str = "blob",
        media_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
    ) -> ObjectRecord:
        cid = bytes_cid(data)
        if not self._object_exists(cid):
            self._write_object_bytes(cid, data)
        return ObjectRecord(
            tenant_id=tenant_id,
            cid=cid,
            uri=f"{self.uri_prefix}{cid}",
            kind=kind,
            media_type=media_type,
            byte_length=len(data),
            metadata=dict(metadata or {}),
        )

    def read_bytes(self, uri: str) -> bytes:
        return self._read_object_bytes(self._cid_from_uri(uri))

    def exists(self, uri: str) -> bool:
        return self._object_exists(self._cid_from_uri(uri))

    def shred(self, uri: str, *, tenant_id: str | None = None) -> dict[str, Any]:
        self._cid_from_uri(uri)
        return {
            "shredded": False,
            "crypto_shredded": False,
            "reason": "unencrypted_object_store_has_no_key",
        }

    # -- byte-backend seams -------------------------------------------------
    # These four methods are the ONLY places the store touches its physical
    # bytes; the envelope / AAD / CID-verify logic above and in the encrypted
    # subclass is backend-agnostic. The S3 stores override just these seams to
    # target SeaweedFS instead of the local filesystem.
    def _write_object_bytes(self, cid: str, data: bytes) -> None:
        path = self._path_for_cid(cid)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(path, data)

    def _read_object_bytes(self, cid: str) -> bytes:
        return self._path_for_cid(cid).read_bytes()

    def _object_exists(self, cid: str) -> bool:
        return self._path_for_cid(cid).exists()

    def _delete_object_bytes(self, cid: str) -> None:
        self._path_for_cid(cid).unlink(missing_ok=True)

    def _path_for_cid(self, cid: str) -> Path:
        if len(cid) != 64 or any(ch not in "0123456789abcdef" for ch in cid):
            raise ValueError("invalid object cid")
        path = (self.root / cid[:2] / cid).resolve()
        if self.root not in path.parents:
            raise ValueError("object path escaped store root")
        return path

    def _cid_from_uri(self, uri: str) -> str:
        if not uri.startswith(self.uri_prefix):
            raise ValueError("unsupported object uri")
        return uri.removeprefix(self.uri_prefix)


class ObjectKeyManager(Protocol):
    """Envelope-key manager boundary for local JSON and production KMS adapters."""

    def key_id(self, tenant_id: str, cid: str) -> str: ...

    def get_or_create_key(self, tenant_id: str, cid: str) -> bytes: ...

    def get_key(self, tenant_id: str, cid: str) -> bytes: ...

    def has_key(self, tenant_id: str, cid: str) -> bool: ...

    def shred_key(self, tenant_id: str, cid: str) -> bool: ...


class JsonKeyManager:
    """Small JSON key manager for local encrypted object storage.

    It is intentionally simple and file-backed for local parity tests. The
    production equivalent should be a KMS/HSM-backed adapter with the same
    get-or-create and shred semantics.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()

    def key_id(self, tenant_id: str, cid: str) -> str:
        return bytes_cid(f"{tenant_id}:{cid}".encode("utf-8"))

    def get_or_create_key(self, tenant_id: str, cid: str) -> bytes:
        data = self._load()
        key_id = self.key_id(tenant_id, cid)
        record = data.setdefault("keys", {}).get(key_id)
        if not record:
            record = {"tenant_id": tenant_id, "cid": cid, "key": _b64encode(os.urandom(32))}
            data["keys"][key_id] = record
            self._save(data)
        return _b64decode(str(record["key"]))

    def get_key(self, tenant_id: str, cid: str) -> bytes:
        data = self._load()
        key_id = self.key_id(tenant_id, cid)
        record = data.get("keys", {}).get(key_id)
        if not record:
            raise KeyError("object key is unavailable or has been shredded")
        return _b64decode(str(record["key"]))

    def has_key(self, tenant_id: str, cid: str) -> bool:
        return self.key_id(tenant_id, cid) in self._load().get("keys", {})

    def shred_key(self, tenant_id: str, cid: str) -> bool:
        data = self._load()
        key_id = self.key_id(tenant_id, cid)
        existed = data.get("keys", {}).pop(key_id, None) is not None
        if existed:
            self._save(data)
        return existed

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "keys": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True, indent=2), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(self.path)


class CommandKeyManager:
    """Command-backed key manager for KMS/HSM/Vault style deployments.

    The command is invoked without a shell. Each call appends the action name as
    the final argv item and sends a JSON request on stdin. The command must emit
    JSON on stdout:

    - `get_or_create_key` / `get_key`: `{"key": "<urlsafe-base64-32-byte-key>"}`
    - `has_key`: `{"exists": true}`
    - `shred_key`: `{"shredded": true}`
    """

    def __init__(self, command: str | Sequence[str], timeout_seconds: float = 30.0):
        self.command = _command_argv(command)
        if not self.command:
            raise ValueError("object key command must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("object key command timeout must be positive")
        self.timeout_seconds = timeout_seconds

    def key_id(self, tenant_id: str, cid: str) -> str:
        return bytes_cid(f"{tenant_id}:{cid}".encode("utf-8"))

    def get_or_create_key(self, tenant_id: str, cid: str) -> bytes:
        return self._key_action("get_or_create_key", tenant_id, cid)

    def get_key(self, tenant_id: str, cid: str) -> bytes:
        return self._key_action("get_key", tenant_id, cid)

    def has_key(self, tenant_id: str, cid: str) -> bool:
        response = self._call("has_key", tenant_id, cid)
        return bool(response.get("exists"))

    def shred_key(self, tenant_id: str, cid: str) -> bool:
        response = self._call("shred_key", tenant_id, cid)
        return bool(response.get("shredded"))

    def _key_action(self, action: str, tenant_id: str, cid: str) -> bytes:
        response = self._call(action, tenant_id, cid)
        raw_key = response.get("key", response.get("key_b64", response.get("plaintext_key")))
        if not isinstance(raw_key, str):
            raise ValueError(f"object key command {action} response must include a base64 key")
        key = _b64decode(raw_key)
        if len(key) != 32:
            raise ValueError("object key command must return a 32-byte AES-256 key")
        return key

    def _call(self, action: str, tenant_id: str, cid: str) -> dict[str, Any]:
        payload = {
            "action": action,
            "tenant_id": tenant_id,
            "cid": cid,
            "key_id": self.key_id(tenant_id, cid),
        }
        try:
            completed = subprocess.run(
                [*self.command, action],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"object key command timed out during {action}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip()[:512]
            suffix = f": {detail}" if detail else ""
            raise ValueError(f"object key command failed during {action}{suffix}")
        try:
            parsed = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(f"object key command {action} response must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"object key command {action} response must be a JSON object")
        return parsed


class EncryptedLocalObjectStore(LocalObjectStore):
    """AES-GCM local object store with per-object crypto-shred keys."""

    uri_prefix = "local-object+aesgcm://sha256/"

    def __init__(self, root: str | Path, key_manager: ObjectKeyManager | None = None):
        super().__init__(root)
        self.key_manager = key_manager or JsonKeyManager(self.root / ".keys.json")

    def put_bytes(
        self,
        data: bytes,
        tenant_id: str,
        kind: str = "blob",
        media_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
    ) -> ObjectRecord:
        cid = bytes_cid(data)
        key = self.key_manager.get_or_create_key(tenant_id, cid)
        nonce = os.urandom(12)
        aad = _object_aad(tenant_id, cid, kind, media_type)
        ciphertext = AESGCM(key).encrypt(nonce, data, aad)
        envelope = {
            "version": 1,
            "algorithm": "AES-256-GCM",
            "tenant_id": tenant_id,
            "cid": cid,
            "kind": kind,
            "media_type": media_type,
            "byte_length": len(data),
            "metadata": dict(metadata or {}),
            "nonce": _b64encode(nonce),
            "ciphertext": _b64encode(ciphertext),
        }
        self._write_object_bytes(cid, json.dumps(envelope, sort_keys=True).encode("utf-8"))
        return ObjectRecord(
            tenant_id=tenant_id,
            cid=cid,
            uri=f"{self.uri_prefix}{cid}",
            kind=kind,
            media_type=media_type,
            byte_length=len(data),
            metadata={
                **dict(metadata or {}),
                "encrypted": True,
                "encryption_alg": "AES-256-GCM",
                "key_id": self.key_manager.key_id(tenant_id, cid),
            },
        )

    def read_bytes(self, uri: str) -> bytes:
        cid = self._cid_from_uri(uri)
        envelope = self._read_envelope(cid)
        tenant_id = str(envelope["tenant_id"])
        kind = str(envelope["kind"])
        media_type = str(envelope["media_type"])
        key = self.key_manager.get_key(tenant_id, cid)
        plaintext = AESGCM(key).decrypt(
            _b64decode(str(envelope["nonce"])),
            _b64decode(str(envelope["ciphertext"])),
            _object_aad(tenant_id, cid, kind, media_type),
        )
        if bytes_cid(plaintext) != cid:
            raise ValueError("object plaintext digest mismatch")
        return plaintext

    def exists(self, uri: str) -> bool:
        cid = self._cid_from_uri(uri)
        if not self._object_exists(cid):
            return False
        try:
            envelope = self._read_envelope(cid)
        except (json.JSONDecodeError, KeyError, OSError):
            return False
        return self.key_manager.has_key(str(envelope["tenant_id"]), cid)

    def shred(self, uri: str, *, tenant_id: str | None = None) -> dict[str, Any]:
        cid = self._cid_from_uri(uri)
        try:
            envelope = self._read_envelope(cid)
        except FileNotFoundError:
            return {"shredded": False, "crypto_shredded": False, "reason": "object_not_found", "cid": cid}
        object_tenant = str(envelope["tenant_id"])
        if tenant_id and tenant_id != object_tenant:
            return {"shredded": False, "crypto_shredded": False, "reason": "tenant_mismatch", "cid": cid}
        shredded = self.key_manager.shred_key(object_tenant, cid)
        return {
            "shredded": shredded,
            "crypto_shredded": shredded,
            "reason": "key_shredded" if shredded else "key_not_found",
            "cid": cid,
            "key_id": self.key_manager.key_id(object_tenant, cid),
        }

    def _read_envelope(self, cid: str) -> dict[str, Any]:
        envelope = json.loads(self._read_object_bytes(cid).decode("utf-8"))
        if envelope.get("cid") != cid:
            raise ValueError("object envelope cid mismatch")
        if envelope.get("algorithm") != "AES-256-GCM":
            raise ValueError("unsupported encrypted object algorithm")
        return envelope


def _object_aad(tenant_id: str, cid: str, kind: str, media_type: str) -> bytes:
    return json.dumps(
        {"tenant_id": tenant_id, "cid": cid, "kind": kind, "media_type": media_type},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))


def _command_argv(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return split_command(command)
    return [str(item) for item in command]


# --- S3 / SeaweedFS byte backend ---------------------------------------------
# A minimal, dependency-free S3 client: stdlib urllib for transport and a
# hand-rolled AWS Signature V4 (hashlib/hmac). It exposes only the four verbs
# the object stores need (Put/Get/Head/Delete + CreateBucket), path-style, and
# routes every request through ``network_safety.safe_urlopen`` with the endpoint
# host on the internal-host allowlist. Deliberately NOT boto3 — the package
# dependency set stays exactly ["cryptography>=42"].


class S3ObjectStoreError(RuntimeError):
    """Raised for any S3 backend failure surfaced to the object store."""


class S3ObjectNotFoundError(S3ObjectStoreError):
    """Raised when an object (or bucket) is absent (HTTP 404)."""


@dataclass(frozen=True)
class S3ObjectStoreConfig:
    endpoint: str
    bucket: str
    region: str = "us-east-1"
    access_key: str = ""
    secret_key: str = ""
    timeout_seconds: float = 30.0


def _load_seaweed_credentials(path: Path) -> tuple[str, str]:
    """Read S3 access/secret from a flat ``{"accessKey","secretKey"}`` file or a
    SeaweedFS ``s3.json`` identities file (``identities[].credentials[]``)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("accessKey") and data.get("secretKey"):
        return str(data["accessKey"]), str(data["secretKey"])
    identities = data.get("identities") if isinstance(data, dict) else None
    if isinstance(identities, list):
        for identity in identities:
            creds = identity.get("credentials") if isinstance(identity, dict) else None
            if isinstance(creds, list) and creds and isinstance(creds[0], dict):
                access = creds[0].get("accessKey")
                secret = creds[0].get("secretKey")
                if access and secret:
                    return str(access), str(secret)
    raise ValueError(f"could not parse S3 credentials from {path}")


def s3_config_from_env(environ: dict[str, str] | None = None) -> S3ObjectStoreConfig:
    """Build an :class:`S3ObjectStoreConfig` from the ``MNEMOSYNE_S3_*`` env.

    Credentials come from ``MNEMOSYNE_S3_ACCESS_KEY``/``MNEMOSYNE_S3_SECRET_KEY``
    or, failing that, the JSON file named by ``MNEMOSYNE_S3_CREDENTIALS_FILE``.
    """
    env = dict(os.environ if environ is None else environ)
    endpoint = env.get("MNEMOSYNE_S3_ENDPOINT", "https://s3.mnemo.local").rstrip("/")
    bucket = env.get("MNEMOSYNE_S3_BUCKET", "").strip()
    if not bucket:
        raise ValueError("MNEMOSYNE_S3_BUCKET is required for the s3 object store backend")
    region = env.get("MNEMOSYNE_S3_REGION", "us-east-1").strip() or "us-east-1"
    access_key = env.get("MNEMOSYNE_S3_ACCESS_KEY", "").strip()
    secret_key = env.get("MNEMOSYNE_S3_SECRET_KEY", "").strip()
    creds_file = env.get("MNEMOSYNE_S3_CREDENTIALS_FILE", "").strip()
    if (not access_key or not secret_key) and creds_file:
        access_key, secret_key = _load_seaweed_credentials(Path(creds_file))
    if not access_key or not secret_key:
        raise ValueError(
            "s3 object store requires MNEMOSYNE_S3_ACCESS_KEY/MNEMOSYNE_S3_SECRET_KEY "
            "or MNEMOSYNE_S3_CREDENTIALS_FILE"
        )
    timeout = float(env.get("MNEMOSYNE_S3_TIMEOUT", "30"))
    return S3ObjectStoreConfig(
        endpoint=endpoint,
        bucket=bucket,
        region=region,
        access_key=access_key,
        secret_key=secret_key,
        timeout_seconds=timeout,
    )


def _s3_uri_encode(path: str) -> str:
    """RFC-3986 path encoding for the SigV4 canonical URI (slashes preserved)."""
    out: list[str] = []
    for byte in path.encode("utf-8"):
        char = chr(byte)
        if char.isalnum() or char in "/-._~":
            out.append(char)
        else:
            out.append(f"%{byte:02X}")
    return "".join(out)


def _s3_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = hmac.new(("AWS4" + secret_key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
    k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


class SeaweedS3Client:
    """Path-style S3 client for SeaweedFS using stdlib urllib + manual SigV4."""

    service = "s3"

    def __init__(self, config: S3ObjectStoreConfig):
        parsed = urlsplit(config.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("S3 endpoint must be an http(s) URL with a host")
        self.config = config
        self._scheme = parsed.scheme
        self._host = parsed.hostname
        self._host_header = parsed.netloc
        self._allowed_hosts = (self._host,)

    def put_object(self, key: str, data: bytes) -> None:
        self._request("PUT", f"/{self.config.bucket}/{key}", body=data)

    def get_object(self, key: str) -> bytes:
        return self._request("GET", f"/{self.config.bucket}/{key}")

    def head_object(self, key: str) -> bool:
        try:
            self._request("HEAD", f"/{self.config.bucket}/{key}")
            return True
        except S3ObjectNotFoundError:
            return False

    def delete_object(self, key: str) -> None:
        try:
            self._request("DELETE", f"/{self.config.bucket}/{key}")
        except S3ObjectNotFoundError:
            return

    def create_bucket(self) -> None:
        """Best-effort bucket creation. SeaweedFS auto-creates a bucket on the
        first object write, and the least-privilege object identity is
        intentionally not granted the admin CreateBucket action, so an
        AccessDenied / already-exists response is treated as success."""
        try:
            self._request("PUT", f"/{self.config.bucket}")
        except S3ObjectStoreError as exc:
            message = str(exc)
            if not any(token in message for token in ("AccessDenied", "BucketAlready", "403", "409")):
                raise

    def _request(self, method: str, canonical_uri: str, *, body: bytes = b"") -> bytes:
        cfg = self.config
        url = f"{self._scheme}://{self._host_header}{canonical_uri}"
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload = body or b""
        payload_hash = hashlib.sha256(payload).hexdigest()
        canonical_headers = (
            f"host:{self._host_header}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            [method, _s3_uri_encode(canonical_uri), "", canonical_headers, signed_headers, payload_hash]
        )
        credential_scope = f"{date_stamp}/{cfg.region}/{self.service}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = _s3_signing_key(cfg.secret_key, date_stamp, cfg.region, self.service)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            f"AWS4-HMAC-SHA256 Credential={cfg.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        headers = {
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Authorization": authorization,
        }
        data = payload if method in {"PUT", "POST"} else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        validated = validate_fetch_url(
            url,
            allow_insecure_localhost=False,
            allow_internal_hosts=self._allowed_hosts,
            purpose="s3 object store URL",
        )
        try:
            with safe_urlopen(request, validated=validated, timeout=cfg.timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                # SeaweedFS answers a missing object/bucket with 404 for a
                # signed reader; 403 stays a real AccessDenied (never masked).
                raise S3ObjectNotFoundError(f"s3 {method} {canonical_uri} -> 404") from exc
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:256]
            except Exception:  # noqa: BLE001 - best-effort error detail only.
                detail = ""
            raise S3ObjectStoreError(f"s3 {method} {canonical_uri} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise S3ObjectStoreError(f"s3 {method} {canonical_uri} failed: {exc.reason}") from exc


class _S3ByteBackend:
    """Byte-backend seams that store content-addressed objects in S3.

    Mixed into the local stores AHEAD of them in the MRO so these four seam
    overrides win while every envelope/AAD/CID-verify code path is inherited
    unchanged. Object key layout mirrors the local sharding: ``cid[:2]/cid``.
    """

    _s3: SeaweedS3Client

    def _object_key(self, cid: str) -> str:
        if len(cid) != 64 or any(ch not in "0123456789abcdef" for ch in cid):
            raise ValueError("invalid object cid")
        return f"{cid[:2]}/{cid}"

    def _write_object_bytes(self, cid: str, data: bytes) -> None:
        self._s3.put_object(self._object_key(cid), data)

    def _read_object_bytes(self, cid: str) -> bytes:
        try:
            return self._s3.get_object(self._object_key(cid))
        except S3ObjectNotFoundError as exc:
            raise FileNotFoundError(f"object {cid} not found in s3 object store") from exc

    def _object_exists(self, cid: str) -> bool:
        return self._s3.head_object(self._object_key(cid))

    def _delete_object_bytes(self, cid: str) -> None:
        self._s3.delete_object(self._object_key(cid))


class S3ObjectStore(_S3ByteBackend, LocalObjectStore):
    """Content-addressed S3/SeaweedFS object store (unencrypted payloads)."""

    uri_prefix = "s3-object://sha256/"

    def __init__(self, client: SeaweedS3Client):
        self._s3 = client


class EncryptedS3ObjectStore(_S3ByteBackend, EncryptedLocalObjectStore):
    """AES-GCM object store whose ciphertext envelopes live in S3/SeaweedFS.

    The app-layer AES-GCM envelope + external key manager are inherited from
    ``EncryptedLocalObjectStore`` unchanged, so ``encrypted``/``key_provider``/
    crypto-shred semantics are byte-identical to the local encrypted store; only
    the physical byte backend is S3.
    """

    uri_prefix = "s3-object+aesgcm://sha256/"

    def __init__(self, client: SeaweedS3Client, key_manager: ObjectKeyManager):
        if key_manager is None:
            raise ValueError("EncryptedS3ObjectStore requires an object key manager")
        self._s3 = client
        self.key_manager = key_manager
