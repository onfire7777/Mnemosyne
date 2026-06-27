"""Earned-autonomy credentials for self-generated thoughts.

Credentials are projections, not authorities. They are computed from external
corroboration outcomes and only raise the birth groundedness of future
self-generated thoughts within the self-generated Standing band.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping


CREDENTIAL_FN_VERSION = "earned-autonomy.credentials.v1"
UNKNOWN_DOMAIN = "unknown"
SELF_BIRTH_GROUNDEDNESS_BASE = 0.08
DEFAULT_MAX_BIRTH_UPLIFT = 0.24
DEFAULT_MIN_SUCCESS_RATE = 0.75
DEFAULT_MIN_TRAIN_EVENTS = 2
DEFAULT_MIN_HOLDOUT_EVENTS = 2
DEFAULT_DECAY_PER_WINDOW = 0.10

_EXTERNAL_SOURCES = {
    "external",
    "evidence",
    "grounded",
    "human",
    "operator",
    "sensor",
    "production",
    "signed_provenance",
    "trusted_external",
}
_SELF_SOURCES = {
    "self",
    "self_generated",
    "self-generated",
    "workspace",
    "dreamer",
    "simulation",
    "simulated",
    "reflection",
}
_CONFIRMED = {"confirmed", "corroborated", "true", "success", "supported", "accepted"}
_CONTRADICTED = {"contradicted", "false", "failure", "failed", "rejected", "unsupported"}


@dataclass(frozen=True, slots=True)
class CredentialPolicy:
    """Small immutable policy object for the earned-autonomy projection."""

    min_success_rate: float = DEFAULT_MIN_SUCCESS_RATE
    min_train_events: int = DEFAULT_MIN_TRAIN_EVENTS
    min_holdout_events: int = DEFAULT_MIN_HOLDOUT_EVENTS
    max_birth_uplift: float = DEFAULT_MAX_BIRTH_UPLIFT
    decay_per_window: float = DEFAULT_DECAY_PER_WINDOW


@dataclass(frozen=True, slots=True)
class CredentialEvent:
    """Normalized event used to compute a domain credential."""

    thought_id: str
    domain: str
    split: str
    source_class: str
    accepted: bool
    confirmed: bool
    contradicted: bool
    rejected_reason: str | None
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DomainCredential:
    """Per-domain credential derived from external holdout validation."""

    domain: str
    value: float
    birth_groundedness: float
    train_event_count: int
    train_success_rate: float
    holdout_event_count: int
    holdout_success_rate: float
    holdout_validated: bool
    external_only: bool
    provenance_assigned_domain: bool
    bounded: bool
    decayed_windows: int
    credential_fn_version: str = CREDENTIAL_FN_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def credential_policy_from_operating_policy(policy: Any | None) -> CredentialPolicy:
    """Derive credential knobs from ``OperatingPolicy`` without coupling to it."""

    if policy is None:
        return CredentialPolicy()
    return CredentialPolicy(
        min_success_rate=_bounded_unit(getattr(policy, "credential_min_success_rate", DEFAULT_MIN_SUCCESS_RATE)),
        min_train_events=_positive_int(getattr(policy, "credential_min_train_events", DEFAULT_MIN_TRAIN_EVENTS)),
        min_holdout_events=_positive_int(getattr(policy, "credential_min_holdout_events", DEFAULT_MIN_HOLDOUT_EVENTS)),
        max_birth_uplift=_bounded_unit(getattr(policy, "credential_max_birth_uplift", DEFAULT_MAX_BIRTH_UPLIFT)),
        decay_per_window=_bounded_unit(getattr(policy, "credential_decay_per_window", DEFAULT_DECAY_PER_WINDOW)),
    )


def normalize_credential_event(row: Mapping[str, Any], *, split: str) -> CredentialEvent:
    """Normalize one raw outcome row and reject self-corrobating inputs.

    The event's domain is assigned from source provenance. Generator-claimed
    fields such as ``claimed_domain`` are deliberately ignored.
    """

    provenance = _mapping(row.get("provenance"))
    outcome = _mapping(row.get("outcome"))
    source_class = _source_class(row, provenance, outcome)
    domain = assign_domain_from_provenance(row, provenance, outcome)
    confirmed = _result(row, outcome) in _CONFIRMED
    contradicted = _result(row, outcome) in _CONTRADICTED
    accepted = True
    reason = None
    if source_class != "external":
        accepted = False
        reason = f"not_external:{source_class}"
    elif domain == UNKNOWN_DOMAIN:
        accepted = False
        reason = "no_provenance_assigned_domain"
    elif not (confirmed or contradicted):
        accepted = False
        reason = "non_decisive_outcome"
    elif _has_self_generated_ancestor(row, provenance, outcome):
        accepted = False
        reason = "shares_self_generated_ancestor"
    return CredentialEvent(
        thought_id=str(row.get("thought_id") or outcome.get("thought_id") or ""),
        domain=domain,
        split="holdout" if split == "holdout" else "train",
        source_class=source_class,
        accepted=accepted,
        confirmed=confirmed,
        contradicted=contradicted,
        rejected_reason=reason,
        provenance={key: value for key, value in provenance.items() if key not in {"claimed_domain", "generator_domain"}},
    )


def compute_domain_credentials(
    train_rows: Iterable[Mapping[str, Any]],
    holdout_rows: Iterable[Mapping[str, Any]],
    *,
    policy: CredentialPolicy | None = None,
    decayed_windows_by_domain: Mapping[str, int] | None = None,
) -> dict[str, DomainCredential]:
    """Compute bounded, decaying credentials from external outcome streams."""

    effective_policy = policy or CredentialPolicy()
    train_events = [normalize_credential_event(row, split="train") for row in train_rows]
    holdout_events = [normalize_credential_event(row, split="holdout") for row in holdout_rows]
    domains = sorted({event.domain for event in train_events + holdout_events if event.domain != UNKNOWN_DOMAIN})
    credentials: dict[str, DomainCredential] = {}
    for domain in domains:
        train = [event for event in train_events if event.domain == domain and event.accepted]
        holdout = [event for event in holdout_events if event.domain == domain and event.accepted]
        train_rate = _success_rate(train)
        holdout_rate = _success_rate(holdout)
        holdout_validated = (
            len(train) >= effective_policy.min_train_events
            and len(holdout) >= effective_policy.min_holdout_events
            and train_rate >= effective_policy.min_success_rate
            and holdout_rate >= effective_policy.min_success_rate
        )
        raw_value = max(0.0, min(train_rate, holdout_rate) - effective_policy.min_success_rate)
        denominator = max(1e-9, 1.0 - effective_policy.min_success_rate)
        value = raw_value / denominator if holdout_validated else 0.0
        decayed_windows = max(0, int((decayed_windows_by_domain or {}).get(domain, 0)))
        if decayed_windows:
            value *= max(0.0, 1.0 - decayed_windows * effective_policy.decay_per_window)
        value = round(max(0.0, min(1.0, value)), 6)
        credentials[domain] = DomainCredential(
            domain=domain,
            value=value,
            birth_groundedness=birth_groundedness_from_value(value, policy=effective_policy),
            train_event_count=len(train),
            train_success_rate=round(train_rate, 6),
            holdout_event_count=len(holdout),
            holdout_success_rate=round(holdout_rate, 6),
            holdout_validated=holdout_validated,
            external_only=all(event.source_class == "external" for event in train + holdout),
            provenance_assigned_domain=all(event.domain == domain for event in train + holdout),
            bounded=0.0 <= value <= 1.0,
            decayed_windows=decayed_windows,
        )
    return credentials


def birth_groundedness_for_domain(
    domain: str,
    credentials: Mapping[str, DomainCredential],
    *,
    policy: CredentialPolicy | None = None,
) -> float:
    """Return the birth groundedness for a self-thought in a proven domain."""

    credential = credentials.get(str(domain or UNKNOWN_DOMAIN))
    value = credential.value if credential is not None else 0.0
    return birth_groundedness_from_value(value, policy=policy)


def birth_groundedness_from_value(value: float, *, policy: CredentialPolicy | None = None) -> float:
    """Map a bounded credential value to a self-band birth groundedness."""

    effective_policy = policy or CredentialPolicy()
    return round(
        SELF_BIRTH_GROUNDEDNESS_BASE + _bounded_unit(value) * effective_policy.max_birth_uplift,
        6,
    )


def build_credential_audit(
    train_rows: Iterable[Mapping[str, Any]],
    holdout_rows: Iterable[Mapping[str, Any]],
    *,
    adversarial_rows: Iterable[Mapping[str, Any]] = (),
    policy: CredentialPolicy | None = None,
) -> dict[str, Any]:
    """Return a bounded audit for earned-autonomy gate checks."""

    effective_policy = policy or CredentialPolicy()
    train_list = list(train_rows)
    holdout_list = list(holdout_rows)
    adversarial_list = list(adversarial_rows)
    credentials = compute_domain_credentials(train_list, holdout_list, policy=effective_policy)
    adversarial_credentials = compute_domain_credentials(adversarial_list, adversarial_list, policy=effective_policy)
    base_birth = birth_groundedness_from_value(0.0, policy=effective_policy)
    max_credential_birth = max(
        (credential.birth_groundedness for credential in credentials.values()),
        default=base_birth,
    )
    max_adversarial_birth = max(
        (credential.birth_groundedness for credential in adversarial_credentials.values()),
        default=base_birth,
    )
    events = [
        *(normalize_credential_event(row, split="train") for row in train_list),
        *(normalize_credential_event(row, split="holdout") for row in holdout_list),
        *(normalize_credential_event(row, split="train") for row in adversarial_list),
    ]
    rejected = [event for event in events if not event.accepted]
    return {
        "schema_version": "earned-autonomy-credential-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "credential_fn_version": CREDENTIAL_FN_VERSION,
        "policy": asdict(effective_policy),
        "credentials": {domain: credential.to_dict() for domain, credential in credentials.items()},
        "adversarial_credentials": {
            domain: credential.to_dict() for domain, credential in adversarial_credentials.items()
        },
        "base_birth_groundedness": base_birth,
        "max_credential_birth_groundedness": max_credential_birth,
        "earned_autonomy_external_expansion": round(max_credential_birth - base_birth, 6),
        "echo_chamber_uplift": round(max(0.0, max_adversarial_birth - base_birth), 6),
        "credential_external_only": _contract_value(
            all(credential.external_only for credential in credentials.values()) and bool(credentials)
        ),
        "credential_holdout_validated": _contract_value(
            all(credential.holdout_validated for credential in credentials.values()) and bool(credentials)
        ),
        "credential_provenance_domain_contract": _contract_value(
            all(credential.provenance_assigned_domain for credential in credentials.values()) and bool(credentials)
        ),
        "credential_bounded_decay_contract": _contract_value(
            all(credential.bounded for credential in credentials.values()) and bool(credentials)
        ),
        "rejected_event_count": len(rejected),
        "rejected_events": [event.to_dict() for event in rejected],
    }


def assign_domain_from_provenance(
    row: Mapping[str, Any],
    provenance: Mapping[str, Any] | None = None,
    outcome: Mapping[str, Any] | None = None,
) -> str:
    """Assign a domain from source provenance, never from generator claims."""

    _ = row
    sources = [outcome or {}, provenance or {}]
    allowed_keys = ("external_domain", "source_domain", "provenance_domain", "verified_domain", "domain")
    for source in sources:
        for key in allowed_keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return _slug(value)
    identity = str((outcome or {}).get("source_identity") or (provenance or {}).get("source_identity") or "").strip()
    if ":" in identity:
        return _slug(identity.split(":", 1)[0])
    source_type = str((outcome or {}).get("source_type") or (provenance or {}).get("source_type") or "").strip()
    if source_type and source_type not in _SELF_SOURCES:
        return _slug(source_type)
    return UNKNOWN_DOMAIN


def _source_class(row: Mapping[str, Any], provenance: Mapping[str, Any], outcome: Mapping[str, Any]) -> str:
    values = [
        row.get("corroboration_source"),
        row.get("source_class"),
        provenance.get("source_class"),
        provenance.get("source_type"),
        outcome.get("corroboration_source"),
        outcome.get("source_class"),
        outcome.get("source_type"),
    ]
    normalized = {_slug(value) for value in values if value}
    if normalized & {_slug(value) for value in _SELF_SOURCES}:
        return "self"
    if normalized & {_slug(value) for value in _EXTERNAL_SOURCES}:
        return "external"
    return "unknown"


def _result(row: Mapping[str, Any], outcome: Mapping[str, Any]) -> str:
    return _slug(outcome.get("result") or outcome.get("status") or row.get("result") or row.get("status"))


def _has_self_generated_ancestor(
    row: Mapping[str, Any],
    provenance: Mapping[str, Any],
    outcome: Mapping[str, Any],
) -> bool:
    for source in (row, provenance, outcome):
        for key in ("self_generated_ancestor", "self_generated", "shares_self_generated_ancestor"):
            if source.get(key) is True:
                return True
        ancestors = source.get("self_generated_ancestor_cids") or source.get("self_generated_ancestors")
        if isinstance(ancestors, list | tuple | set) and any(str(item) for item in ancestors):
            return True
    return False


def _success_rate(events: list[CredentialEvent]) -> float:
    decisive = [event for event in events if event.confirmed or event.contradicted]
    if not decisive:
        return 0.0
    successes = sum(1 for event in decisive if event.confirmed)
    return successes / len(decisive)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bounded_unit(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    if numeric != numeric:
        numeric = 0.0
    return round(max(0.0, min(1.0, numeric)), 6)


def _positive_int(value: Any) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = 1
    return max(1, numeric)


def _contract_value(ok: bool) -> float:
    return 1.0 if ok else 0.0


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return "_".join(part for part in text.split() if part) or UNKNOWN_DOMAIN
