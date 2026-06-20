"""Local object storage for large and multimodal evidence payloads."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mnemosyne.ids import bytes_cid
from mnemosyne.models import Resource


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
        path = self._path_for_cid(cid)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
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
        cid = self._cid_from_uri(uri)
        return self._path_for_cid(cid).read_bytes()

    def exists(self, uri: str) -> bool:
        cid = self._cid_from_uri(uri)
        return self._path_for_cid(cid).exists()

    def shred(self, uri: str, *, tenant_id: str | None = None) -> dict[str, Any]:
        self._cid_from_uri(uri)
        return {
            "shredded": False,
            "crypto_shredded": False,
            "reason": "unencrypted_object_store_has_no_key",
        }

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


class EncryptedLocalObjectStore(LocalObjectStore):
    """AES-GCM local object store with per-object crypto-shred keys."""

    uri_prefix = "local-object+aesgcm://sha256/"

    def __init__(self, root: str | Path, key_manager: JsonKeyManager | None = None):
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
        path = self._path_for_cid(cid)
        path.parent.mkdir(parents=True, exist_ok=True)
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
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
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
        path = self._path_for_cid(cid)
        if not path.exists():
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
        envelope = json.loads(self._path_for_cid(cid).read_text(encoding="utf-8"))
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
