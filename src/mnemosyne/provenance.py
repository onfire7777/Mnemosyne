"""Signed provenance verification decisions."""

from __future__ import annotations

import json
import subprocess
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
                trust_delta=5,
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
            trust_delta=-1 if trusted else 0,
            reason="signed provenance digest verified" if trusted else "digest verified without trusted signature",
            manifest=dict(manifest),
            diagnostics={"actual": actual},
        )


@dataclass(frozen=True, slots=True)
class C2paToolVerifier:
    """Verifier adapter for `c2patool`-style JSON verification.

    The configured tool must accept `asset_path --json` and write a JSON
    verification report to stdout. If no asset path is present in the manifest,
    this adapter delegates to the deterministic digest verifier.
    """

    tool_path: str = "c2patool"
    trusted_issuers: tuple[str, ...] = ()
    fallback: SignedProvenanceVerifier = field(default_factory=SignedProvenanceVerifier)
    timeout_seconds: float = 30.0

    def verify(self, payload: bytes, manifest: dict[str, Any] | None) -> ProvenanceDecision:
        asset_path = str((manifest or {}).get("asset_path") or (manifest or {}).get("c2pa_asset_path") or "")
        if not asset_path:
            return self.fallback.verify(payload, manifest)
        try:
            completed = subprocess.run(
                [self.tool_path, asset_path, "--json"],
                check=False,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ProvenanceDecision(
                valid=False,
                trusted=False,
                quarantine=True,
                trust_delta=5,
                reason="c2pa verifier execution failed",
                manifest=dict(manifest or {}),
                diagnostics={"error": str(exc), "tool": self.tool_path},
            )
        if completed.returncode != 0:
            return ProvenanceDecision(
                valid=False,
                trusted=False,
                quarantine=True,
                trust_delta=5,
                reason="c2pa verification failed",
                manifest=dict(manifest or {}),
                diagnostics={"returncode": completed.returncode, "stderr": completed.stderr[:1000]},
            )
        try:
            report = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            return ProvenanceDecision(
                valid=False,
                trusted=False,
                quarantine=True,
                trust_delta=5,
                reason="c2pa verifier returned invalid json",
                manifest=dict(manifest or {}),
                diagnostics={"error": str(exc)},
            )
        signer = _find_first(report, {"issuer", "signer", "claim_generator", "claimGenerator", "common_name", "name"})
        trusted = bool(signer) and (not self.trusted_issuers or str(signer) in self.trusted_issuers)
        return ProvenanceDecision(
            valid=True,
            trusted=trusted,
            quarantine=False,
            trust_delta=-2 if trusted else -1,
            reason="c2pa manifest verified" if trusted else "c2pa manifest valid but signer not trusted",
            manifest={**dict(manifest or {}), "c2pa": _report_summary(report)},
            diagnostics={"tool": self.tool_path, "signer": signer, "trusted_issuers": list(self.trusted_issuers)},
        )


def _find_first(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and item:
                return item
        for item in value.values():
            found = _find_first(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_first(item, keys)
            if found:
                return found
    return None


def _report_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "active_manifest": report.get("active_manifest") or report.get("activeManifest"),
        "claim_generator": _find_first(report, {"claim_generator", "claimGenerator"}),
        "issuer": _find_first(report, {"issuer", "signer", "common_name", "name"}),
    }
