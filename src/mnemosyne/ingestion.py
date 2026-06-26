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
from mnemosyne.models import Assertion, Evidence, Resource
from mnemosyne.privacy import (
    classify_privacy,
    enforce_residency,
    enforce_residency_transfer,
    normalize_residency,
    normalize_residency_transfers,
)
from mnemosyne.provenance import SignedProvenanceVerifier
from mnemosyne.queue import InProcessQueue, QueueJob
from mnemosyne.retrieval import MediaEmbeddingProvider
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
    correction: dict[str, Any] | None = None

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
    correction_applied: bool = False
    correction_assertion_id: str | None = None

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
        runtime_residency: str | None = None,
        allowed_residency_transfers: tuple[str, ...] = (),
        require_runtime_residency: bool = False,
        media_embedding_provider: MediaEmbeddingProvider | None = None,
    ):
        self.engine = engine
        self.object_store = object_store or LocalObjectStore(Path(".mnemosyne/objects"))
        self.provenance_verifier = provenance_verifier or SignedProvenanceVerifier()
        self.queue = queue
        self.inline_text_limit = inline_text_limit
        self.allowed_residencies = tuple(normalize_residency(item) for item in allowed_residencies)
        self.runtime_residency = normalize_residency(runtime_residency) if runtime_residency else None
        self.allowed_residency_transfers = normalize_residency_transfers(tuple(allowed_residency_transfers))
        self.require_runtime_residency = require_runtime_residency
        self.media_embedding_provider = media_embedding_provider

    def ingest(self, request: IngestRequest, branch: str = "main") -> IngestResult:
        payload = request.payload_bytes()
        provenance = self.provenance_verifier.verify(payload, _provenance_manifest_for_request(request))
        classification = classify_request(request, payload)
        residency = normalize_residency(
            request.metadata.get("residency") or request.metadata.get("data_residency")
        )
        enforce_residency(residency, self.allowed_residencies)
        target_residency = self.runtime_residency
        if target_residency is None:
            target_value = request.metadata.get("processing_residency") or request.metadata.get("runtime_residency")
            target_residency = normalize_residency(target_value) if target_value else None
        if self.require_runtime_residency and target_residency is None:
            raise ValueError("runtime residency is required by this runtime")
        cross_region_transfer = enforce_residency_transfer(
            residency,
            target_residency,
            self.allowed_residency_transfers,
        )
        privacy = classify_privacy(_privacy_text(request, payload), residency=residency)
        privacy_metadata = {
            **privacy.to_dict(),
            "runtime_residency": target_residency,
            "cross_region_transfer": cross_region_transfer,
            "allowed_residency_transfers": list(self.allowed_residency_transfers),
        }
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
            "privacy": privacy_metadata,
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
            "runtime_residency": target_residency,
            "cross_region_transfer": cross_region_transfer,
            "allowed_residency_transfers": list(self.allowed_residency_transfers),
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

        embedding: list[float] | None = None
        if should_externalize and request.modality != "text" and self.media_embedding_provider is not None:
            embedding = self.media_embedding_provider.embed_media(
                payload,
                media_type=request.media_type,
                modality=request.modality,
                metadata=metadata,
            )
            metadata["media_embedding"] = {
                "provider": self.media_embedding_provider.name,
                "dims": self.media_embedding_provider.dims,
                "source": "raw-externalized-media",
            }
            capability_tags.append("raw-media-embedding-indexed")
            capability_tags = sorted(set(capability_tags))

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
        prediction_error = self._prediction_error_signal(
            tenant_id=request.tenant_id,
            branch=branch,
            content=content,
            already_present=already_present,
        )
        write_priority = self._write_priority_signal(
            request=request,
            content=content,
            trust_tier=trust_tier,
            prediction_error=prediction_error,
            already_present=already_present,
        )
        consolidation_metadata = dict(metadata.get("consolidation") or {})
        consolidation_metadata.setdefault("prediction_error", prediction_error["score"])
        consolidation_metadata.setdefault("prediction_error_gate", prediction_error["gate"])
        consolidation_metadata.setdefault("write_priority", write_priority)
        metadata["consolidation"] = consolidation_metadata
        metadata["write_priority"] = write_priority

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
                embedding=embedding,
                metadata=metadata,
                trust_tier=trust_tier,
                capability_tags=capability_tags,
                sensitivity=sensitivity,
                signed_provenance=request.signed_provenance,
                access_policy=access_policy,
            ),
            branch=branch,
        )
        # Tier-0 user-correction fast path (blueprint §20.7 / §30.2): the
        # highest-trust signal is applied immediately as an active supersession
        # in the same turn, bypassing the gated consolidation warm loop. Only
        # derived/inferred memory takes the candidate -> gate path.
        correction_applied = False
        correction_assertion_id: str | None = None
        if not already_present and is_tier0_user_correction(request, trust_tier):
            correction_assertion_id = self._apply_tier0_correction(
                request=request,
                cid=cid,
                branch=branch,
                trust_tier=trust_tier,
                sensitivity=sensitivity,
                access_policy=access_policy,
            )
            correction_applied = correction_assertion_id is not None

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
                    write_priority=write_priority,
                    prediction_error=prediction_error,
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
            correction_applied=correction_applied,
            correction_assertion_id=correction_assertion_id,
        )

    def _apply_tier0_correction(
        self,
        *,
        request: IngestRequest,
        cid: str,
        branch: str,
        trust_tier: int,
        sensitivity: int,
        access_policy: dict[str, Any],
    ) -> str | None:
        """Apply a tier-0 user correction immediately as an active assertion.

        Routes through ``engine.upsert_assertion`` so the belief core performs
        trust-tier-precedence supersession in the same turn (ungated), realizing
        the §20.7 fast-path correction shortcut. Returns the assertion id, or
        ``None`` if the request carries no well-formed correction triple.
        """
        triple = _correction_triple(request)
        if triple is None:
            return None
        assertion = Assertion(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            subject=triple["subject"],
            predicate=triple["predicate"],
            object=triple["object"],
            confidence=triple["confidence"],
            scope=triple["scope"],
            source_evidence_cids=[cid],
            status="active",
            trust_tier=trust_tier,
            sensitivity=sensitivity,
            access_policy=dict(access_policy),
        )
        return self.engine.upsert_assertion(assertion, branch=branch)

    def residency_policy(self) -> dict[str, object]:
        warnings: list[str] = []
        if not self.allowed_residencies:
            warnings.append("no allowed residency labels configured; all residency labels are accepted")
        if not self.require_runtime_residency:
            warnings.append("runtime residency is optional; missing processing residency will be accepted")
        return {
            "allowed_residencies": list(self.allowed_residencies),
            "runtime_residency": self.runtime_residency,
            "require_runtime_residency": self.require_runtime_residency,
            "request_runtime_residency_required": self.require_runtime_residency and self.runtime_residency is None,
            "allowed_residency_transfers": list(self.allowed_residency_transfers),
            "cross_region_transfers_allowed": bool(self.allowed_residency_transfers),
            "warnings": warnings,
        }

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
        write_priority: dict[str, Any],
        prediction_error: dict[str, Any],
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
                "write_priority": dict(write_priority),
                "prediction_error": dict(prediction_error),
                "replay_scores": {
                    cid: {
                        "importance": write_priority["components"]["importance"],
                        "novelty": write_priority["components"]["novelty"],
                        "surprise": prediction_error["score"],
                        "reward": write_priority["components"]["reward"],
                    }
                },
            },
        )

    def _prediction_error_signal(
        self,
        *,
        tenant_id: str,
        branch: str,
        content: str,
        already_present: bool,
    ) -> dict[str, Any]:
        if already_present:
            return {"score": 0.0, "support": 1.0, "gate": "duplicate_evidence", "hit_count": 0}
        query = " ".join(content.split())[:240]
        if not query:
            return {"score": 0.0, "support": 1.0, "gate": "empty_content", "hit_count": 0}
        try:
            result = self.engine.retrieve(query=query, tenant_id=tenant_id, branch=branch)
        except Exception:
            return {"score": 1.0, "support": 0.0, "gate": "unmeasured_fail_open_to_review", "hit_count": 0}
        support = result.explain.get("confidence", {}).get("query_support", {}).get("score")
        try:
            support_score = float(support)
        except (TypeError, ValueError):
            support_score = 0.0 if not result.hits else 0.5
        score = max(0.0, min(1.0, 1.0 - support_score))
        threshold = max(0.0, min(1.0, float(getattr(self.engine.policy, "prediction_error_threshold", 0.35))))
        return {
            "score": round(score, 6),
            "support": round(max(0.0, min(1.0, support_score)), 6),
            "threshold": threshold,
            "gate": "promote_to_consolidation" if score >= threshold else "low_prediction_error_metadata_only",
            "hit_count": len(result.hits),
        }

    def _write_priority_signal(
        self,
        *,
        request: IngestRequest,
        content: str,
        trust_tier: int,
        prediction_error: dict[str, Any],
        already_present: bool,
    ) -> dict[str, Any]:
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        importance = _bounded_signal(metadata.get("importance"), default=0.65 if request.correction else 0.45)
        novelty = 0.0 if already_present else _bounded_signal(metadata.get("novelty"), default=0.65)
        surprise = _bounded_signal(metadata.get("surprise"), default=float(prediction_error.get("score", 0.0)))
        raw_reward = _bounded_signal(metadata.get("reward"), default=0.5 if request.actor == "user" else 0.25)
        reward = raw_reward if trust_tier <= int(TrustTier.AUTHENTICATED) else min(raw_reward, 0.25)
        if trust_tier >= int(TrustTier.UNTRUSTED_EXTERNAL):
            reward = 0.0
        weights = dict(getattr(self.engine.policy, "write_priority_weights", {}) or {})
        total = sum(max(float(value), 0.0) for value in weights.values()) or 1.0
        components = {
            "importance": importance,
            "novelty": novelty,
            "surprise": surprise,
            "reward": reward,
        }
        raw_score = sum(max(float(weights.get(key, 0.0)), 0.0) * value for key, value in components.items()) / total
        caps = getattr(self.engine.policy, "write_priority_max_by_trust_tier", {}) or {}
        trust_cap = float(caps.get(trust_tier, caps.get(int(TrustTier.UNTRUSTED_EXTERNAL), 0.2)))
        score = max(0.0, min(1.0, raw_score, trust_cap))
        return {
            "score": round(score, 6),
            "components": {key: round(value, 6) for key, value in components.items()},
            "trust_cap": round(trust_cap, 6),
            "source": "g1_multi_signal_write_priority",
            "content_chars": len(content),
        }

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


def _bounded_signal(value: object, *, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        number = default
    if number != number:
        number = default
    return max(0.0, min(1.0, number))


def is_tier0_user_correction(request: IngestRequest, trust_tier: int) -> bool:
    """Return True for a tier-0 direct-user correction (blueprint §20.7).

    A tier-0 correction is the highest-trust signal and is applied immediately
    rather than via the gated warm loop. Detection requires the highest trust
    tier (``DIRECT_USER``), a direct-user actor, and a well-formed structured
    correction triple. Quarantined or lower-trust evidence never qualifies
    because its final ``trust_tier`` is no longer ``DIRECT_USER``.
    """
    if trust_tier != int(TrustTier.DIRECT_USER):
        return False
    if request.actor != "user":
        return False
    return _correction_triple(request) is not None


def _correction_triple(request: IngestRequest) -> dict[str, Any] | None:
    raw = request.correction
    if not isinstance(raw, dict):
        flagged = request.metadata.get("correction")
        raw = flagged if isinstance(flagged, dict) else None
    if not isinstance(raw, dict):
        return None
    subject = raw.get("subject")
    predicate = raw.get("predicate")
    obj = raw.get("object", raw.get("object_value", raw.get("value")))
    if not (
        isinstance(subject, str)
        and subject.strip()
        and isinstance(predicate, str)
        and predicate.strip()
        and isinstance(obj, str)
        and obj.strip()
    ):
        return None
    scope = raw.get("scope")
    confidence = raw.get("confidence")
    return {
        "subject": subject.strip(),
        "predicate": predicate.strip(),
        "object": obj.strip(),
        "scope": dict(scope) if isinstance(scope, dict) else {},
        "confidence": float(confidence) if isinstance(confidence, (int, float)) else 0.99,
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


def _provenance_manifest_for_request(request: IngestRequest) -> dict[str, Any] | None:
    if not request.signed_provenance:
        return None
    manifest = dict(request.signed_provenance)
    if "asset_path" in manifest or "c2pa_asset_path" in manifest:
        manifest["_ingest_context"] = {
            "tenant_id": request.tenant_id,
            "user_id": request.user_id,
            "actor": request.actor,
            "source_type": request.source_type,
            "source_identity": request.source_identity or "",
            "modality": request.modality,
            "media_type": request.media_type,
            "asset_path": str(manifest.get("asset_path") or manifest.get("c2pa_asset_path") or ""),
        }
    return manifest


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
