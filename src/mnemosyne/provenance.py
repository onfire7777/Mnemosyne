"""Signed provenance verification decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any


@dataclass(frozen=True, slots=True)
class ProvenanceDecision:
    valid: bool
    trusted: bool
    quarantine: bool
    trust_delta: int
    reason: str
    manifest: dict[str, Any] | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SignedProvenanceVerifier:
    """Deterministic verifier for C2PA-like manifest metadata.

    Real C2PA verification is delegated to a production verifier. This local
    verifier enforces the essential contract: a manifest must bind to the exact
    bytes being ingested before it can raise trust, and digest mismatch
    quarantines the item.
    """

    def verify(self, payload: bytes, manifest: dict[str, Any] | None) -> ProvenanceDecision:
        if not manifest:
            return ProvenanceDecision(
                valid=False,
                trusted=False,
                quarantine=False,
                trust_delta=0,
                reason="no signed provenance manifest",
            )
        actual = sha256(payload).hexdigest()
        expected = str(manifest.get("sha256") or manifest.get("content_hash") or "")
        if expected != actual:
            return ProvenanceDecision(
                valid=False,
                trusted=False,
                quarantine=True,
                trust_delta=-5,
                reason="signed provenance digest mismatch",
                manifest=dict(manifest),
                diagnostics={"expected": expected, "actual": actual},
            )
        signer = manifest.get("issuer") or manifest.get("signer") or manifest.get("claim_generator")
        signature = manifest.get("signature") or manifest.get("signature_ref")
        trusted = bool(signer and signature)
        return ProvenanceDecision(
            valid=True,
            trusted=trusted,
            quarantine=False,
            trust_delta=1 if trusted else 0,
            reason="signed provenance digest verified" if trusted else "digest verified without trusted signature",
            manifest=dict(manifest),
            diagnostics={"actual": actual},
        )
