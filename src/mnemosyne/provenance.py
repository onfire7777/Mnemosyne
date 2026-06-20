"""Signed provenance verification decisions."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
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
    verification report to stdout. The report must bind back to the exact asset
    through a payload SHA-256 or an explicit asset path. If no asset path is
    present in the manifest, this adapter delegates to the deterministic digest
    verifier.
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
        actual_hash = sha256(payload).hexdigest()
        binding = _verify_report_asset_binding(report, actual_hash, asset_path)
        if not binding["bound"]:
            return ProvenanceDecision(
                valid=False,
                trusted=False,
                quarantine=True,
                trust_delta=5,
                reason=str(binding["reason"]),
                manifest={**dict(manifest or {}), "c2pa": _report_summary(report, binding=binding)},
                diagnostics={"tool": self.tool_path, **dict(binding["diagnostics"])},
            )
        signer = _find_first(report, {"issuer", "signer", "claim_generator", "claimGenerator", "common_name", "commonName"})
        trusted = bool(signer) and (not self.trusted_issuers or str(signer) in self.trusted_issuers)
        return ProvenanceDecision(
            valid=True,
            trusted=trusted,
            quarantine=False,
            trust_delta=-2 if trusted else -1,
            reason="c2pa manifest verified" if trusted else "c2pa manifest valid but signer not trusted",
            manifest={**dict(manifest or {}), "c2pa": _report_summary(report, binding=binding)},
            diagnostics={
                "tool": self.tool_path,
                "signer": signer,
                "trusted_issuers": list(self.trusted_issuers),
                "asset_binding": binding["summary"],
            },
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


_HEX_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_ASSET_HASH_HINTS = ("asset", "content", "ingredient", "payload", "source")
_PATH_KEYS = {
    "asset_path",
    "assetPath",
    "c2pa_asset_path",
    "file_path",
    "filePath",
    "source_path",
    "sourcePath",
    "path",
}


def _verify_report_asset_binding(report: dict[str, Any], actual_hash: str, asset_path: str) -> dict[str, Any]:
    hashes = _collect_asset_hashes(report)
    if hashes:
        if actual_hash in hashes:
            return {
                "bound": True,
                "reason": "c2pa report asset hash matched",
                "summary": {"bound": True, "method": "sha256", "sha256": actual_hash},
                "diagnostics": {"actual_sha256": actual_hash, "candidate_hash_count": len(hashes)},
            }
        return {
            "bound": False,
            "reason": "c2pa report asset hash mismatch",
            "summary": {"bound": False, "method": "sha256", "candidate_hash_count": len(hashes)},
            "diagnostics": {"actual_sha256": actual_hash, "candidate_hashes": sorted(hashes)[:10]},
        }
    path_candidates = _collect_paths(report)
    if any(_same_path(candidate, asset_path) for candidate in path_candidates):
        return {
            "bound": True,
            "reason": "c2pa report asset path matched",
            "summary": {"bound": True, "method": "asset_path"},
            "diagnostics": {"path_candidate_count": len(path_candidates)},
        }
    return {
        "bound": False,
        "reason": "c2pa report does not bind to asset",
        "summary": {"bound": False, "method": "missing"},
        "diagnostics": {"path_candidate_count": len(path_candidates)},
    }


def _collect_asset_hashes(value: Any, path: tuple[str, ...] = ()) -> set[str]:
    matches: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            key_path = (*path, str(key))
            if _is_asset_hash_key(key_path):
                matches.update(_extract_sha256_values(item))
            if isinstance(item, dict) and _declares_sha256(item) and _path_mentions_asset(key_path):
                for hash_key in ("hash", "digest", "value"):
                    matches.update(_extract_sha256_values(item.get(hash_key)))
            matches.update(_collect_asset_hashes(item, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            matches.update(_collect_asset_hashes(item, (*path, str(index))))
    return matches


def _extract_sha256_values(value: Any) -> set[str]:
    if isinstance(value, str):
        candidate = value.lower().removeprefix("sha256:").strip()
        return {candidate} if _HEX_SHA256.fullmatch(candidate) else set()
    if isinstance(value, dict):
        matches: set[str] = set()
        for item in value.values():
            matches.update(_extract_sha256_values(item))
        return matches
    if isinstance(value, list):
        matches: set[str] = set()
        for item in value:
            matches.update(_extract_sha256_values(item))
        return matches
    return set()


def _collect_paths(value: Any) -> set[str]:
    matches: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _PATH_KEYS and isinstance(item, str) and item.strip():
                matches.add(item.strip())
            matches.update(_collect_paths(item))
    elif isinstance(value, list):
        for item in value:
            matches.update(_collect_paths(item))
    return matches


def _is_asset_hash_key(path: tuple[str, ...]) -> bool:
    normalized = "_".join(_normalize_key(part) for part in path)
    if "sha256" not in normalized and "sha_256" not in normalized:
        return False
    return normalized in {"sha256", "sha_256"} or _path_mentions_asset(path)


def _path_mentions_asset(path: tuple[str, ...]) -> bool:
    normalized = "_".join(_normalize_key(part) for part in path)
    return any(hint in normalized for hint in _ASSET_HASH_HINTS)


def _declares_sha256(value: dict[str, Any]) -> bool:
    algorithm = str(
        value.get("alg")
        or value.get("algorithm")
        or value.get("hash_alg")
        or value.get("hashAlgorithm")
        or ""
    )
    return _normalize_key(algorithm) in {"sha256", "sha_256"}


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _same_path(candidate: str, expected: str) -> bool:
    if candidate == expected:
        return True
    expected_path = Path(expected).expanduser().resolve(strict=False)
    candidate_path = Path(candidate).expanduser()
    possible = [candidate_path.resolve(strict=False)]
    if not candidate_path.is_absolute():
        possible.append((expected_path.parent / candidate_path).resolve(strict=False))
    return expected_path in possible


def _report_summary(report: dict[str, Any], *, binding: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "active_manifest": report.get("active_manifest") or report.get("activeManifest"),
        "claim_generator": _find_first(report, {"claim_generator", "claimGenerator"}),
        "issuer": _find_first(report, {"issuer", "signer", "common_name", "commonName"}),
        "asset_binding": dict((binding or {}).get("summary") or {"bound": False, "method": "unchecked"}),
    }
