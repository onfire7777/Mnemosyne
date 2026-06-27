"""Sandboxed generative replay primitives.

The dreamer is deliberately shadow-only: it recombines already-retained
evidence into low-trust candidates for later gates, but never writes to the
ledger, never changes active beliefs, and never participates in answer
retrieval.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .models import Evidence
from .text import tokenize


@dataclass(frozen=True, slots=True)
class DreamCandidate:
    """Low-trust replay hypothesis produced from existing evidence."""

    id: str
    tenant_id: str
    branch: str
    content: str
    source_evidence_cids: tuple[str, ...]
    reality_class: str = "self_generated"
    trust_tier: int = 5
    shadow_only: bool = True
    promotion_required: bool = True
    critical_path: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_evidence_cids"] = list(self.source_evidence_cids)
        return data


@dataclass(frozen=True, slots=True)
class DreamReport:
    """Replay output contract for G3 shadow generativity."""

    tenant_id: str
    branch: str
    candidates: tuple[DreamCandidate, ...]
    source_count: int
    shadow_only: bool = True
    production_mutation: bool = False
    critical_path: bool = False
    promotion_gate_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return data


@dataclass(frozen=True, slots=True)
class SandboxedDreamer:
    """Deterministic low-trust generative replay specialist."""

    max_candidates: int = 3
    min_sources: int = 2
    max_sources: int = 64
    max_source_chars: int = 4096

    def dream(
        self,
        evidence: Sequence[Evidence | Mapping[str, Any]],
        *,
        tenant_id: str,
        branch: str = "dream-shadow",
        max_candidates: int | None = None,
    ) -> DreamReport:
        usable = [_coerce_source(item, max_chars=self.max_source_chars) for item in evidence[: self.max_sources]]
        usable = [
            item
            for item in usable
            if item["cid"]
            and item["content"]
            and item["tenant_id"] == tenant_id
            and item["access_tenant"] == tenant_id
        ]
        if len(usable) < self.min_sources:
            return DreamReport(tenant_id=tenant_id, branch=branch, candidates=(), source_count=len(usable))

        limit = max(0, int(max_candidates if max_candidates is not None else self.max_candidates))
        candidates: list[DreamCandidate] = []
        for left, right in zip(usable, usable[1:], strict=False):
            if len(candidates) >= limit:
                break
            left_terms = _salient_terms(left["content"])
            right_terms = _salient_terms(right["content"])
            if not left_terms or not right_terms:
                continue
            source_cids = (str(left["cid"]), str(right["cid"]))
            content = (
                "Sandbox replay hypothesis: "
                f"{left_terms[0]} may relate to {right_terms[0]} across retained evidence."
            )
            candidates.append(
                DreamCandidate(
                    id=_candidate_id(tenant_id, branch, content, source_cids),
                    tenant_id=tenant_id,
                    branch=branch,
                    content=content,
                    source_evidence_cids=source_cids,
                )
            )
        return DreamReport(
            tenant_id=tenant_id,
            branch=branch,
            candidates=tuple(candidates),
            source_count=len(usable),
        )


def _coerce_source(item: Evidence | Mapping[str, Any], *, max_chars: int) -> dict[str, str]:
    if isinstance(item, Evidence):
        access_tenant = item.access_policy.get("tenant") or item.tenant_id
        return {
            "cid": str(item.cid or ""),
            "content": item.content[:max_chars],
            "tenant_id": item.tenant_id,
            "access_tenant": str(access_tenant or ""),
        }
    access_policy = item.get("access_policy") if isinstance(item.get("access_policy"), Mapping) else {}
    access_tenant = access_policy.get("tenant") if isinstance(access_policy, Mapping) else None
    return {
        "cid": str(item.get("cid") or ""),
        "content": str(item.get("content") or "")[:max_chars],
        "tenant_id": str(item.get("tenant_id") or ""),
        "access_tenant": str(access_tenant or ""),
    }


def _salient_terms(text: str) -> list[str]:
    stop = {
        "about",
        "across",
        "after",
        "before",
        "evidence",
        "from",
        "into",
        "that",
        "their",
        "there",
        "this",
        "with",
    }
    terms = [term for term in tokenize(text) if len(term) >= 4 and term not in stop]
    ranked = sorted(set(terms), key=lambda term: (-terms.count(term), term))
    return ranked[:3]


def _candidate_id(tenant_id: str, branch: str, content: str, source_cids: tuple[str, ...]) -> str:
    payload = "\n".join([tenant_id, branch, content, *source_cids]).encode("utf-8")
    return "dream:" + hashlib.sha256(payload).hexdigest()[:24]
