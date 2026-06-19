"""Evidence ingestion pipeline for text, blobs, and multimodal payloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, Resource
from mnemosyne.provenance import SignedProvenanceVerifier
from mnemosyne.storage import LocalObjectStore


Modality = Literal["text", "image", "audio", "video", "binary", "multimodal"]


@dataclass(slots=True)
class IngestRequest:
    tenant_id: str
    user_id: str
    actor: str
    source_type: str
    content: str | None = None
    data: bytes | None = None
    source_identity: str | None = None
    media_type: str = "text/plain"
    modality: Modality = "text"
    metadata: dict[str, Any] = field(default_factory=dict)
    signed_provenance: dict[str, Any] | None = None
    trust_tier: int = 1
    sensitivity: int = 0

    def payload_bytes(self) -> bytes:
        if self.data is not None:
            return self.data
        return (self.content or "").encode("utf-8")


@dataclass(slots=True)
class IngestResult:
    cid: str
    branch: str
    content_pointer: str | None
    modality: Modality
    trust_tier: int
    quarantined: bool
    provenance: dict[str, Any]
    resource: Resource | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["resource"] = self.resource.to_dict() if self.resource else None
        return data


class IngestionPipeline:
    """Append evidence while preserving byte payloads and trust signals."""

    def __init__(
        self,
        engine: LocalMemoryEngine,
        object_store: LocalObjectStore | None = None,
        provenance_verifier: SignedProvenanceVerifier | None = None,
        inline_text_limit: int = 16_384,
    ):
        self.engine = engine
        self.object_store = object_store or LocalObjectStore(Path(".mnemosyne/objects"))
        self.provenance_verifier = provenance_verifier or SignedProvenanceVerifier()
        self.inline_text_limit = inline_text_limit

    def ingest(self, request: IngestRequest, branch: str = "main") -> IngestResult:
        payload = request.payload_bytes()
        provenance = self.provenance_verifier.verify(payload, request.signed_provenance)
        trust_tier = max(0, request.trust_tier + provenance.trust_delta)
        metadata = {
            **request.metadata,
            "media_type": request.media_type,
            "provenance_decision": provenance.to_dict(),
        }
        if provenance.quarantine:
            trust_tier = 0
            metadata["quarantine_reason"] = provenance.reason

        content_pointer: str | None = None
        resource: Resource | None = None
        should_externalize = (
            request.data is not None
            or request.modality != "text"
            or len(payload) > self.inline_text_limit
        )
        if should_externalize:
            record = self.object_store.put_bytes(
                payload,
                tenant_id=request.tenant_id,
                kind=request.modality,
                media_type=request.media_type,
                metadata={"source_type": request.source_type},
            )
            content_pointer = record.uri
            resource = record.to_resource()
            metadata["resource"] = resource.to_dict()

        content = request.content or ""
        if request.data is not None and request.modality != "text":
            content = metadata.get("alt_text") or metadata.get("description") or ""

        cid = self.engine.append_evidence(
            Evidence(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                actor=request.actor,  # type: ignore[arg-type]
                source_type=request.source_type,
                source_identity=request.source_identity,
                content=content,
                content_pointer=content_pointer,
                modality=request.modality,
                metadata=metadata,
                trust_tier=trust_tier,
                sensitivity=request.sensitivity,
                signed_provenance=request.signed_provenance,
                access_policy={"tenant": request.tenant_id},
            ),
            branch=branch,
        )
        return IngestResult(
            cid=cid,
            branch=branch,
            content_pointer=content_pointer,
            modality=request.modality,
            trust_tier=trust_tier,
            quarantined=provenance.quarantine,
            provenance=provenance.to_dict(),
            resource=resource,
        )
