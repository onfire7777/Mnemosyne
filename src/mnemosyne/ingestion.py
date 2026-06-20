"""Evidence ingestion pipeline for text, blobs, and multimodal payloads."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB, DEFAULT_CONSOLIDATION_PASSES
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ids import content_cid
from mnemosyne.media import MEDIA_EXTRACT_JOB, extract_derived_text
from mnemosyne.models import Evidence, Resource
from mnemosyne.privacy import classify_privacy, enforce_residency, normalize_residency
from mnemosyne.provenance import SignedProvenanceVerifier
from mnemosyne.queue import InProcessQueue, QueueJob
from mnemosyne.security import TrustTier
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
    trust_tier: int | None = None
    capability_tags: list[str] = field(default_factory=list)
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
    queued_jobs: list[dict[str, Any]] = field(default_factory=list)

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
        queue: InProcessQueue | None = None,
        inline_text_limit: int = 16_384,
        allowed_residencies: tuple[str, ...] = ("local",),
    ):
        self.engine = engine
        self.object_store = object_store or LocalObjectStore(Path(".mnemosyne/objects"))
        self.provenance_verifier = provenance_verifier or SignedProvenanceVerifier()
        self.queue = queue
        self.inline_text_limit = inline_text_limit
        self.allowed_residencies = tuple(normalize_residency(item) for item in allowed_residencies)

    def ingest(self, request: IngestRequest, branch: str = "main") -> IngestResult:
        payload = request.payload_bytes()
        provenance = self.provenance_verifier.verify(payload, request.signed_provenance)
        classification = classify_request(request, payload)
        residency = normalize_residency(
            request.metadata.get("residency") or request.metadata.get("data_residency")
        )
        enforce_residency(residency, self.allowed_residencies)
        privacy = classify_privacy(_privacy_text(request, payload), residency=residency)
        base_trust_tier = request.trust_tier if request.trust_tier is not None else classification["trust_tier"]
        trust_tier = min(max(base_trust_tier + provenance.trust_delta, int(TrustTier.DIRECT_USER)), int(TrustTier.UNTRUSTED_EXTERNAL))
        capability_tags = sorted(set(request.capability_tags + classification["capability_tags"]))
        capability_tags.append(f"residency:{residency}")
        if request.signed_provenance:
            capability_tags.append("provenance-valid" if provenance.valid else "provenance-invalid")
        if provenance.valid and _provenance_binds_asset(provenance.manifest):
            capability_tags.append("asset-bound-provenance")
        if provenance.trusted:
            capability_tags.append("provenance-verified")
        elif provenance.valid:
            capability_tags.append("provenance-untrusted")
        metadata = {
            **request.metadata,
            "media_type": request.media_type,
            "provenance_decision": provenance.to_dict(),
            "ingest_classification": classification,
            "privacy": privacy.to_dict(),
        }
        if provenance.quarantine:
            trust_tier = int(TrustTier.UNTRUSTED_EXTERNAL)
            metadata["quarantine_reason"] = provenance.reason
            capability_tags.append("quarantined")
        if trust_tier >= int(TrustTier.UNTRUSTED_EXTERNAL):
            capability_tags.extend(["data-only", "no-write-authority"])
        capability_tags = sorted(set(capability_tags))
        sensitivity = max(request.sensitivity, int(classification["sensitivity"]))
        access_policy = {
            "tenant": request.tenant_id,
            "max_sensitivity": sensitivity,
            "data_class": "pii" if sensitivity else "standard",
            "residency": residency,
            "allowed_residencies": list(self.allowed_residencies),
        }

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
        derived_text, derived_sources = extract_derived_text(metadata)
        if request.data is not None and request.modality != "text":
            content = derived_text
        if derived_sources:
            metadata["derived_text"] = derived_text
            metadata["derived_text_sources"] = derived_sources
            capability_tags.append("derived-text-indexed")
            capability_tags = sorted(set(capability_tags))
        predicted_cid = content_cid(
            content,
            {
                "tenant_id": request.tenant_id,
                "source_type": request.source_type,
                "content_pointer": content_pointer,
                "modality": request.modality,
            },
        )
        already_present = self._evidence_exists(request.tenant_id, predicted_cid, branch)

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
                capability_tags=capability_tags,
                sensitivity=sensitivity,
                signed_provenance=request.signed_provenance,
                access_policy=access_policy,
            ),
            branch=branch,
        )
        queued_jobs: list[dict[str, Any]] = []
        if self.queue and not already_present:
            if should_externalize and request.modality != "text" and not derived_sources:
                queued_jobs.append(
                    self._enqueue_media_extraction(
                        cid=cid,
                        request=request,
                        branch=branch,
                        trust_tier=trust_tier,
                        sensitivity=sensitivity,
                        capability_tags=capability_tags,
                        content_pointer=content_pointer,
                    ).to_dict()
                )
            queued_jobs.append(
                self._enqueue_consolidation(
                    cid=cid,
                    request=request,
                    branch=branch,
                    trust_tier=trust_tier,
                    sensitivity=sensitivity,
                    capability_tags=capability_tags,
                ).to_dict()
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
            queued_jobs=queued_jobs,
        )

    def _evidence_exists(self, tenant_id: str, cid: str, branch: str) -> bool:
        get_evidence = getattr(self.engine, "get_evidence", None)
        if not callable(get_evidence):
            return False
        existing = get_evidence(tenant_id, cid, branch)
        return existing is not None and not bool(getattr(existing, "erased", False))

    def _enqueue_consolidation(
        self,
        *,
        cid: str,
        request: IngestRequest,
        branch: str,
        trust_tier: int,
        sensitivity: int,
        capability_tags: list[str],
    ) -> QueueJob:
        if self.queue is None:
            raise RuntimeError("consolidation queue is not configured")
        return self.queue.enqueue(
            CONSOLIDATE_EVIDENCE_JOB,
            {
                "tenant_id": request.tenant_id,
                "user_id": request.user_id,
                "branch": branch,
                "source_evidence_cids": [cid],
                "trigger": "ingest",
                "passes": list(DEFAULT_CONSOLIDATION_PASSES),
                "trust_tier": trust_tier,
                "sensitivity": sensitivity,
                "capability_tags": list(capability_tags),
                "modality": request.modality,
                "source_type": request.source_type,
                "source_identity": request.source_identity,
            },
        )

    def _enqueue_media_extraction(
        self,
        *,
        cid: str,
        request: IngestRequest,
        branch: str,
        trust_tier: int,
        sensitivity: int,
        capability_tags: list[str],
        content_pointer: str | None,
    ) -> QueueJob:
        if self.queue is None:
            raise RuntimeError("media extraction queue is not configured")
        return self.queue.enqueue(
            MEDIA_EXTRACT_JOB,
            {
                "tenant_id": request.tenant_id,
                "user_id": request.user_id,
                "branch": branch,
                "source_evidence_cid": cid,
                "content_pointer": content_pointer,
                "media_type": request.media_type,
                "modality": request.modality,
                "source_trust_tier": trust_tier,
                "sensitivity": sensitivity,
                "capability_tags": list(capability_tags),
                "metadata": dict(request.metadata),
            },
        )


def classify_request(request: IngestRequest, payload: bytes) -> dict[str, Any]:
    text = (request.content or payload.decode("utf-8", errors="ignore"))[:32_768]
    trust_tier = _classify_trust_tier(request.actor, request.source_type)
    capability_tags = [_actor_tag(request.actor), f"source:{request.source_type}"]
    if trust_tier >= int(TrustTier.UNTRUSTED_EXTERNAL):
        capability_tags.extend(["data-only", "no-write-authority"])
    if _looks_imperative(text) and trust_tier >= int(TrustTier.LOW):
        capability_tags.extend(["imperative-untrusted", "sanitize-as-data"])
    pii_tags = _pii_tags(text)
    capability_tags.extend(pii_tags)
    sensitivity = 3 if pii_tags else 0
    return {
        "actor": request.actor,
        "source_type": request.source_type,
        "source_identity": request.source_identity,
        "trust_tier": trust_tier,
        "capability_tags": sorted(set(capability_tags)),
        "sensitivity": sensitivity,
        "sanitize_as_data": "sanitize-as-data" in capability_tags or trust_tier >= int(TrustTier.UNTRUSTED_EXTERNAL),
        "pii_detected": sorted(pii_tags),
    }


def _classify_trust_tier(actor: str, source_type: str) -> int:
    if actor == "user":
        return int(TrustTier.DIRECT_USER)
    if actor == "system":
        return int(TrustTier.VERIFIED)
    if actor in {"assistant", "tool"}:
        return int(TrustTier.AUTHENTICATED)
    if actor == "external":
        if source_type in {"signed", "c2pa", "trusted-api"}:
            return int(TrustTier.AUTHENTICATED)
        return int(TrustTier.UNTRUSTED_EXTERNAL)
    return int(TrustTier.NORMAL)


def _provenance_binds_asset(manifest: dict[str, Any] | None) -> bool:
    if not manifest:
        return False
    if manifest.get("sha256") or manifest.get("content_hash"):
        return True
    c2pa = manifest.get("c2pa")
    if isinstance(c2pa, dict):
        asset_binding = c2pa.get("asset_binding")
        return isinstance(asset_binding, dict) and asset_binding.get("bound") is True
    return False


def _privacy_text(request: IngestRequest, payload: bytes) -> str:
    if request.content:
        return request.content
    for key in ("description", "alt_text", "caption", "transcript", "ocr_text"):
        value = request.metadata.get(key)
        if isinstance(value, str) and value:
            return value
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _actor_tag(actor: str) -> str:
    return {
        "user": "direct-user",
        "system": "system-authored",
        "assistant": "assistant-authored",
        "tool": "tool-authored",
        "external": "external-source",
    }.get(actor, "unknown-actor")


def _looks_imperative(text: str) -> bool:
    return bool(
        re.search(
            r"\b(ignore|disregard|forget|override|delete|exfiltrate|reveal|send|execute|run|call|update|write)\b",
            text,
            re.I,
        )
    )


def _pii_tags(text: str) -> list[str]:
    tags: list[str] = []
    if re.search(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", text):
        tags.append("pii-email")
    if re.search(r"\b\d{3}-\d{2}-\d{4}\b", text):
        tags.append("pii-ssn")
    if re.search(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b", text):
        tags.append("pii-phone")
    return tags
