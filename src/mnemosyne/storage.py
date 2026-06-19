"""Local object storage for large and multimodal evidence payloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

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
