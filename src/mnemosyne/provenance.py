"""Signed provenance verification decisions."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from mnemosyne.command_line import split_command


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


_POLICY_FIELDS = {
    "trusted_issuers",
    "trustedIssuers",
    "trusted_roots",
    "trustedRoots",
    "require_trusted_issuer",
    "requireTrustedIssuer",
    "require_trusted_root",
    "requireTrustedRoot",
    "rules",
}
_POLICY_RULE_FIELDS = {
    "name",
    "scope",
    "trusted_issuers",
    "trustedIssuers",
    "trusted_roots",
    "trustedRoots",
    "require_trusted_issuer",
    "requireTrustedIssuer",
    "require_trusted_root",
    "requireTrustedRoot",
}
_POLICY_SCOPE_FIELDS = {
    "tenant_id",
    "user_id",
    "actor",
    "source_type",
    "source_identity",
    "modality",
    "media_type",
    "asset_path",
    "asset_sha256",
}


@dataclass(frozen=True, slots=True)
class ProvenanceTrustRule:
    scope: tuple[tuple[str, tuple[str, ...]], ...] = ()
    trusted_issuers: tuple[str, ...] = ()
    trusted_roots: tuple[str, ...] = ()
    require_trusted_issuer: bool = True
    require_trusted_root: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProvenanceTrustRule":
        unknown = set(data) - _POLICY_RULE_FIELDS
        if unknown:
            raise ValueError(f"unknown provenance trust rule fields: {', '.join(sorted(unknown))}")
        raw_scope = data.get("scope", {}) or {}
        if not isinstance(raw_scope, dict):
            raise ValueError("provenance trust rule scope must be an object")
        unknown_scope = set(raw_scope) - _POLICY_SCOPE_FIELDS
        if unknown_scope:
            raise ValueError(f"unknown provenance trust scope fields: {', '.join(sorted(unknown_scope))}")
        scope = tuple(
            (str(key), _string_tuple(value, field=f"scope.{key}"))
            for key, value in sorted(raw_scope.items())
        )
        return cls(
            scope=scope,
            trusted_issuers=_trusted_issuer_tuple(data),
            trusted_roots=_trusted_root_tuple(data),
            require_trusted_issuer=_bool_field(
                data,
                snake_name="require_trusted_issuer",
                camel_name="requireTrustedIssuer",
                default=True,
            ),
            require_trusted_root=_bool_field(
                data,
                snake_name="require_trusted_root",
                camel_name="requireTrustedRoot",
                default=False,
            ),
        )

    def matches(self, context: dict[str, Any]) -> bool:
        for key, accepted_values in self.scope:
            actual = context.get(key)
            if actual is None or str(actual) not in accepted_values:
                return False
        return True


@dataclass(frozen=True, slots=True)
class ProvenanceTrustPolicy:
    """Issuer and certificate-root trust policy for production C2PA decisions."""

    trusted_issuers: tuple[str, ...] = ()
    trusted_roots: tuple[str, ...] = ()
    require_trusted_issuer: bool = True
    require_trusted_root: bool = False
    rules: tuple[ProvenanceTrustRule, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProvenanceTrustPolicy":
        unknown = set(data) - _POLICY_FIELDS
        if unknown:
            raise ValueError(f"unknown provenance trust policy fields: {', '.join(sorted(unknown))}")
        raw_rules = data.get("rules", ()) or ()
        if not isinstance(raw_rules, list | tuple):
            raise ValueError("provenance trust policy rules must be a list")
        return cls(
            trusted_issuers=_trusted_issuer_tuple(data),
            trusted_roots=_trusted_root_tuple(data),
            require_trusted_issuer=_bool_field(
                data,
                snake_name="require_trusted_issuer",
                camel_name="requireTrustedIssuer",
                default=True,
            ),
            require_trusted_root=_bool_field(
                data,
                snake_name="require_trusted_root",
                camel_name="requireTrustedRoot",
                default=False,
            ),
            rules=tuple(ProvenanceTrustRule.from_dict(dict(item)) for item in raw_rules),
        )

    def for_context(self, context: dict[str, Any]) -> "ProvenanceTrustPolicy":
        if not self.rules:
            return self
        matching_rules = tuple(rule for rule in self.rules if rule.matches(context))
        if not matching_rules:
            return ProvenanceTrustPolicy(require_trusted_issuer=True)
        trusted_issuers = tuple(
            dict.fromkeys(
                item
                for rule in matching_rules
                for item in (*self.trusted_issuers, *rule.trusted_issuers)
                if item
            )
        )
        trusted_roots = tuple(
            dict.fromkeys(
                _normalize_fingerprint(item)
                for rule in matching_rules
                for item in (*self.trusted_roots, *rule.trusted_roots)
                if item
            )
        )
        return ProvenanceTrustPolicy(
            trusted_issuers=trusted_issuers,
            trusted_roots=trusted_roots,
            require_trusted_issuer=self.require_trusted_issuer
            or any(rule.require_trusted_issuer for rule in matching_rules),
            require_trusted_root=self.require_trusted_root
            or any(rule.require_trusted_root for rule in matching_rules),
        )


def _bool_field(data: dict[str, Any], *, snake_name: str, camel_name: str, default: bool) -> bool:
    raw = data.get(snake_name, data.get(camel_name, default))
    if isinstance(raw, bool):
        return raw
    raise ValueError(f"{snake_name} must be boolean")


def _trusted_issuer_tuple(data: dict[str, Any]) -> tuple[str, ...]:
    return _string_tuple(data.get("trusted_issuers", data.get("trustedIssuers", ())) or (), field="trusted_issuers")


def _trusted_root_tuple(data: dict[str, Any]) -> tuple[str, ...]:
    roots = []
    for item in _string_tuple(
        data.get("trusted_roots", data.get("trustedRoots", ())) or (),
        field="trusted_roots",
    ):
        normalized = _normalize_fingerprint(item)
        if not _HEX_SHA256.fullmatch(normalized):
            raise ValueError("trusted_roots must contain SHA-256 certificate root fingerprints")
        roots.append(normalized)
    return tuple(dict.fromkeys(roots))


def _string_tuple(raw_values: Any, *, field: str) -> tuple[str, ...]:
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    elif not isinstance(raw_values, (list, tuple, set)):
        raw_values = [raw_values]
    values = (str(item).strip() for item in raw_values)
    return tuple(dict.fromkeys(item for item in values if item))


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
    trusted_roots: tuple[str, ...] = ()
    trust_policy: ProvenanceTrustPolicy = field(default_factory=ProvenanceTrustPolicy)
    fallback: SignedProvenanceVerifier = field(default_factory=SignedProvenanceVerifier)
    timeout_seconds: float = 30.0

    def verify(self, payload: bytes, manifest: dict[str, Any] | None) -> ProvenanceDecision:
        manifest_data = dict(manifest or {})
        public_manifest = _public_manifest(manifest_data)
        asset_path = str(manifest_data.get("asset_path") or manifest_data.get("c2pa_asset_path") or "")
        if not asset_path:
            return self.fallback.verify(payload, manifest)
        try:
            tool_argv = [self.tool_path] if Path(self.tool_path).exists() else split_command(self.tool_path)
            if not tool_argv:
                raise OSError("c2pa verifier command must not be empty")
            # Direct batch files may be shell-dispatched by Windows even with shell=False.
            tool_suffix = Path(tool_argv[0].rstrip(" .")).suffix.casefold()
            if os.name == "nt" and tool_suffix in {".bat", ".cmd"}:
                raise OSError("direct .bat/.cmd tool execution is disabled on Windows")
            completed = subprocess.run(
                [*tool_argv, asset_path, "--json"],
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
                manifest=public_manifest,
                diagnostics={"error": str(exc), "tool": self.tool_path},
            )
        if completed.returncode != 0:
            return ProvenanceDecision(
                valid=False,
                trusted=False,
                quarantine=True,
                trust_delta=5,
                reason="c2pa verification failed",
                manifest=public_manifest,
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
                manifest=public_manifest,
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
                manifest={**public_manifest, "c2pa": _report_summary(report, binding=binding)},
                diagnostics={"tool": self.tool_path, **dict(binding["diagnostics"])},
            )
        signer = _find_first(report, {"issuer", "signer", "claim_generator", "claimGenerator", "common_name", "commonName"})
        certificate_roots = _collect_certificate_fingerprints(report)
        trust_policy = self._effective_trust_policy(
            {
                **_policy_context(manifest_data),
                "asset_path": asset_path,
                "asset_sha256": actual_hash,
            }
        )
        trusted_issuers = trust_policy.trusted_issuers
        trusted_roots = trust_policy.trusted_roots
        issuer_trusted = bool(signer) and (
            (not trusted_issuers and not trust_policy.require_trusted_issuer) or str(signer) in trusted_issuers
        )
        root_required = trust_policy.require_trusted_root or bool(trusted_roots)
        root_trusted = bool(certificate_roots) and (
            not trusted_roots or any(item in trusted_roots for item in certificate_roots)
        )
        trusted = issuer_trusted and (root_trusted if root_required else True)
        trust_diagnostics = {
            "require_trusted_issuer": trust_policy.require_trusted_issuer,
            "trusted_issuers": list(trusted_issuers),
        }
        if root_required:
            trust_diagnostics.update(
                {
                    "require_trusted_root": trust_policy.require_trusted_root,
                    "trusted_roots": list(trusted_roots),
                    "certificate_roots": sorted(certificate_roots),
                }
            )
        if trust_policy.require_trusted_issuer and not issuer_trusted:
            return ProvenanceDecision(
                valid=True,
                trusted=False,
                quarantine=True,
                trust_delta=5,
                reason="c2pa manifest valid but signer rejected by trust policy",
                manifest={**public_manifest, "c2pa": _report_summary(report, binding=binding)},
                diagnostics={
                    "tool": self.tool_path,
                    "signer": signer,
                    "trusted_issuers": list(trusted_issuers),
                    "trust_policy": trust_diagnostics,
                    "asset_binding": binding["summary"],
                },
            )
        if root_required and not root_trusted:
            return ProvenanceDecision(
                valid=True,
                trusted=False,
                quarantine=True,
                trust_delta=5,
                reason="c2pa manifest valid but certificate root rejected by trust policy",
                manifest={**public_manifest, "c2pa": _report_summary(report, binding=binding)},
                diagnostics={
                    "tool": self.tool_path,
                    "signer": signer,
                    "trusted_issuers": list(trusted_issuers),
                    "certificate_roots": sorted(certificate_roots),
                    "trusted_roots": list(trusted_roots),
                    "trust_policy": trust_diagnostics,
                    "asset_binding": binding["summary"],
                },
            )
        return ProvenanceDecision(
            valid=True,
            trusted=trusted,
            quarantine=False,
            trust_delta=-2 if trusted else -1,
            reason="c2pa manifest verified" if trusted else "c2pa manifest valid but signer not trusted",
            manifest={**public_manifest, "c2pa": _report_summary(report, binding=binding)},
            diagnostics={
                "tool": self.tool_path,
                "signer": signer,
                "certificate_roots": sorted(certificate_roots),
                "trusted_issuers": list(trusted_issuers),
                "trusted_roots": list(trusted_roots),
                "trust_policy": trust_diagnostics,
                "asset_binding": binding["summary"],
            },
        )

    def _effective_trust_policy(self, context: dict[str, Any]) -> ProvenanceTrustPolicy:
        scoped_policy = self.trust_policy.for_context(context)
        issuers = tuple(dict.fromkeys(item for item in (*self.trusted_issuers, *scoped_policy.trusted_issuers) if item))
        roots = tuple(
            dict.fromkeys(
                _normalize_fingerprint(item)
                for item in (*self.trusted_roots, *scoped_policy.trusted_roots)
                if item
            )
        )
        return ProvenanceTrustPolicy(
            trusted_issuers=issuers,
            trusted_roots=roots,
            require_trusted_issuer=scoped_policy.require_trusted_issuer,
            require_trusted_root=scoped_policy.require_trusted_root,
        )


def _public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    public = dict(manifest)
    public.pop("_ingest_context", None)
    return public


def _policy_context(manifest: dict[str, Any]) -> dict[str, Any]:
    context = manifest.get("_ingest_context")
    if not isinstance(context, dict):
        return {}
    return {str(key): value for key, value in context.items() if key in _POLICY_SCOPE_FIELDS}


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
_CERT_FINGERPRINT_HINTS = ("cert", "certificate", "chain", "root", "signer", "trust")
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


def _collect_certificate_fingerprints(value: Any, path: tuple[str, ...] = ()) -> set[str]:
    matches: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            key_path = (*path, str(key))
            if _path_mentions_certificate(key_path):
                matches.update(_extract_fingerprint_values(item))
            matches.update(_collect_certificate_fingerprints(item, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            matches.update(_collect_certificate_fingerprints(item, (*path, str(index))))
    return matches


def _extract_fingerprint_values(value: Any) -> set[str]:
    if isinstance(value, str):
        normalized = _normalize_fingerprint(value)
        return {normalized} if _HEX_SHA256.fullmatch(normalized) else set()
    if isinstance(value, dict):
        matches: set[str] = set()
        for item in value.values():
            matches.update(_extract_fingerprint_values(item))
        return matches
    if isinstance(value, list):
        matches: set[str] = set()
        for item in value:
            matches.update(_extract_fingerprint_values(item))
        return matches
    return set()


def _path_mentions_certificate(path: tuple[str, ...]) -> bool:
    normalized = "_".join(_normalize_key(part) for part in path)
    return any(hint in normalized for hint in _CERT_FINGERPRINT_HINTS)


def _normalize_fingerprint(value: str) -> str:
    return re.sub(r"[^0-9a-f]", "", value.lower().removeprefix("sha256:"))


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
        "certificate_roots": sorted(_collect_certificate_fingerprints(report)),
        "asset_binding": dict((binding or {}).get("summary") or {"bound": False, "method": "unchecked"}),
    }


def _minimize_monomials(monomials: frozenset[frozenset[str]]) -> frozenset[frozenset[str]]:
    """Drop non-minimal monomials (positive-Boolean absorption).

    A derivation that strictly contains another derivation's sources adds no
    independent support, so it is absorbed. This keeps the provenance polynomial
    compact (blueprint §27 guard: store a compact semiring tag, not full copies).
    """
    items = {frozenset(monomial) for monomial in monomials}
    return frozenset(
        monomial
        for monomial in items
        if not any(other != monomial and other <= monomial for other in items)
    )


@dataclass(frozen=True, slots=True)
class HowProvenance:
    """Semiring how-provenance for a derived fact (Green/Karvounarakis/Tannen,
    PODS 2007; blueprint I5).

    A provenance polynomial over source-evidence CIDs in the positive-Boolean
    provenance semiring: a set of *monomials*, each a set of CIDs that are
    jointly required (``*`` / AND within a monomial), combined as alternative
    derivations (``+`` / OR across monomials). It records not just *which*
    sources supported a fact but *how* they combined. ``zero`` is the empty
    polynomial (unsupported); ``one`` is the single empty monomial (trivially
    true). Polynomials are kept in canonical minimal form for compactness.
    """

    monomials: frozenset[frozenset[str]] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        minimized = _minimize_monomials(self.monomials)
        if minimized != self.monomials:
            object.__setattr__(self, "monomials", minimized)

    @classmethod
    def zero(cls) -> "HowProvenance":
        return cls(frozenset())

    @classmethod
    def one(cls) -> "HowProvenance":
        return cls(frozenset({frozenset()}))

    @classmethod
    def source(cls, cid: str) -> "HowProvenance":
        """A base fact attributed to a single source CID."""
        return cls(frozenset({frozenset({cid})}))

    @property
    def is_zero(self) -> bool:
        return not self.monomials

    @property
    def is_one(self) -> bool:
        return self.monomials == frozenset({frozenset()})

    def combine_or(self, other: "HowProvenance") -> "HowProvenance":
        """Alternative derivations (semiring ``+``): support from either input."""
        return HowProvenance(self.monomials | other.monomials)

    def combine_and(self, other: "HowProvenance") -> "HowProvenance":
        """Joint derivation (semiring ``*``): both inputs are required together."""
        if self.is_zero or other.is_zero:
            return HowProvenance.zero()
        return HowProvenance(
            frozenset(left | right for left in self.monomials for right in other.monomials)
        )

    def sources(self) -> frozenset[str]:
        """Every source CID referenced by any derivation."""
        return frozenset(cid for monomial in self.monomials for cid in monomial)

    def prune(self, erased_cids: Any) -> "HowProvenance":
        """Drop derivations that depend on an erased source (blueprint §27/§25).

        Monomials referencing an erased CID are invalidated; derivations with
        surviving independent corroboration are retained with the erased source
        removed from provenance. Returns ``zero`` when every derivation depended
        on erased evidence.
        """
        erased = set(erased_cids)
        return HowProvenance(
            frozenset(monomial for monomial in self.monomials if not (monomial & erased))
        )

    def tag(self) -> str:
        """A compact, deterministic string tag for storage/inspection."""
        if self.is_zero:
            return "0"
        if self.is_one:
            return "1"
        return " + ".join(
            sorted("*".join(sorted(monomial)) for monomial in self.monomials)
        )

    def to_dict(self) -> dict[str, Any]:
        return {"monomials": sorted(sorted(monomial) for monomial in self.monomials)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HowProvenance":
        raw = data.get("monomials", [])
        if not isinstance(raw, (list, tuple)):
            raise ValueError("how-provenance 'monomials' must be a list")
        return cls(frozenset(frozenset(str(cid) for cid in monomial) for monomial in raw))


def how_provenance_for_sources(cids: Any, *, joint: bool = True) -> HowProvenance:
    """Build a :class:`HowProvenance` from a derived fact's source CIDs.

    ``joint=True`` (default) treats all sources as jointly required (a single
    AND monomial) — the common case for a fact distilled from several inputs.
    ``joint=False`` treats each source as an independent alternative derivation
    (corroboration), so erasing one leaves the others intact.
    """
    unique = [cid for cid in dict.fromkeys(str(cid) for cid in cids) if cid]
    if not unique:
        return HowProvenance.zero()
    if joint:
        return HowProvenance(frozenset({frozenset(unique)}))
    return HowProvenance(frozenset(frozenset({cid}) for cid in unique))
