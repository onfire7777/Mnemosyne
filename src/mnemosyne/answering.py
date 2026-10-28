"""Bounded, read-only orchestration for provenance-grounded answers."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Mapping, Protocol, Sequence

from mnemosyne.engine import MemoryEngine
from mnemosyne.providers.deterministic_synthesis import DeterministicSynthesizer
from mnemosyne.retrieval import QUERY_SUPPORT_STOPWORDS, normalise_query_term
from mnemosyne.text import tokenize


_PUBLIC_ABSTENTION = "insufficient_authorized_evidence"
_ANCHOR_TOKEN = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*", re.UNICODE)
_CONTROL_LABELS = (
    re.compile(r"tenant(?:[\s_-]*ids?)\b", re.IGNORECASE),
    re.compile(r"user(?:[\s_-]*ids?)\b", re.IGNORECASE),
    re.compile(r"source(?:[\s_-]*identit(?:y|ies))\b", re.IGNORECASE),
    re.compile(r"auth(?:orization)?(?:[\s_-]*fields?)\b", re.IGNORECASE),
    re.compile(r"filter(?:[\s_-]*fields?)\b", re.IGNORECASE),
    re.compile(r"policy(?:[\s_-]*fields?)\b", re.IGNORECASE),
)
_FALLBACK_DENY_TERMS = {"command", "commands", "ignore", "instruction", "instructions", "policy"}


def _comparison(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _required_content(row: Mapping[str, Any]) -> str:
    content = row.get("content")
    if not isinstance(content, str) or not content:
        raise ValueError("authorized evidence content must be a non-empty string")
    return content


def _substantive(value: str) -> bool:
    return any(
        len(term) > 2 and term not in QUERY_SUPPORT_STOPWORDS
        for term in (normalise_query_term(token) for token in tokenize(value))
    )


def _control_ranges(source: str) -> tuple[tuple[int, int], ...]:
    ranges = []
    for pattern in _CONTROL_LABELS:
        for match in pattern.finditer(source):
            end = match.end()
            value = _ANCHOR_TOKEN.search(source, end)
            ranges.append((match.start(), value.end() if value else end))
    return tuple(ranges)


def _contains_control_label(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    return any(pattern.search(normalized) for pattern in _CONTROL_LABELS)


def _anchor_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        _comparison(re.sub(r"(?:['’]s)$", "", match.group(0), flags=re.IGNORECASE))
        for match in _ANCHOR_TOKEN.finditer(value)
    )


def _contains_token_span(proposal: str, anchor: str) -> bool:
    proposed = _anchor_tokens(proposal)
    expected = _anchor_tokens(anchor)
    return bool(expected) and any(
        proposed[index : index + len(expected)] == expected
        for index in range(len(proposed) - len(expected) + 1)
    )


def _literal_source_spans(proposal: str, source: str) -> tuple[str, ...]:
    """Return exact proposal and trailing token slices from the source."""
    proposed = _anchor_tokens(proposal)
    normalized_source = unicodedata.normalize("NFKC", source)
    if (
        not proposed
        or _contains_control_label(proposal)
        or (normalized_source != source and _contains_control_label(normalized_source))
        or _FALLBACK_DENY_TERMS.intersection(proposed)
        or not _substantive(proposal)
    ):
        return ()
    words = list(_ANCHOR_TOKEN.finditer(source))
    control_ranges = _control_ranges(source)
    source_tokens = tuple(_anchor_tokens(match.group(0))[0] for match in words)
    for index in range(len(source_tokens) - len(proposed) + 1):
        if source_tokens[index : index + len(proposed)] != proposed:
            continue
        start, end = words[index].start(), words[index + len(proposed) - 1].end()
        if any(left < end and start < right for left, right in control_ranges):
            return ()
        exact = source[start:end]
        trailing = [
            match.group(0)
            for match in reversed(words[index : index + len(proposed)])
            if _substantive(match.group(0))
            and not _FALLBACK_DENY_TERMS.intersection(_anchor_tokens(match.group(0)))
        ]
        return tuple(dict.fromkeys((exact, *trailing)))
    shared = [
        (match.group(0), index)
        for index, match in enumerate(words)
        if _anchor_tokens(match.group(0))[0] in proposed
        and _substantive(match.group(0))
        and not _FALLBACK_DENY_TERMS.intersection(_anchor_tokens(match.group(0)))
        and not any(
            left < match.end() and match.start() < right
            for left, right in control_ranges
        )
    ]
    if not shared:
        return ()
    return (min(shared, key=lambda item: (-len(item[0]), item[1]))[0],)


def _authorized_literal_tokens(source: str) -> tuple[str, ...]:
    normalized_source = unicodedata.normalize("NFKC", source)
    if normalized_source != source and _contains_control_label(normalized_source):
        return ()
    control_ranges = _control_ranges(source)
    selected: list[str] = []
    for match in reversed(list(_ANCHOR_TOKEN.finditer(source))):
        if any(left < match.end() and match.start() < right for left, right in control_ranges):
            continue
        raw = match.group(0)
        tokens = _anchor_tokens(raw)
        if (
            not _substantive(raw)
            or _FALLBACK_DENY_TERMS.intersection(tokens)
            or _comparison(raw) in {_comparison(value) for value in selected}
        ):
            continue
        selected.append(raw)
    return tuple(selected)


def _entity_spans(source: str) -> tuple[str, ...]:
    normalized_source = unicodedata.normalize("NFKC", source)
    if normalized_source != source and _contains_control_label(normalized_source):
        return ()
    words = list(_ANCHOR_TOKEN.finditer(source))
    control_ranges = _control_ranges(source)
    spans: list[str] = []
    start: int | None = None
    end = 0
    for match in words:
        raw = match.group(0)
        base = re.sub(r"(?:['’]s)$", "", raw, flags=re.IGNORECASE)
        letters = "".join(character for character in base if character.isalpha())
        base_terms = [normalise_query_term(token) for token in tokenize(base)]
        entity_like = bool(letters) and any(
            len(term) > 2 and term not in QUERY_SUPPORT_STOPWORDS
            for term in base_terms
        ) and (
            base[0].isupper()
            or letters.isupper()
            or (any(character.isupper() for character in letters[1:]) and any(character.islower() for character in letters))
            or (any(character.isdigit() for character in base) and any(character.isalpha() for character in base))
        )
        adjacent = start is not None and not source[end:match.start()].strip()
        if not entity_like or (start is not None and not adjacent):
            if start is not None:
                if not any(left < end and start < right for left, right in control_ranges):
                    spans.append(source[start:end])
            start = None
        if entity_like:
            if start is None:
                start = match.start()
            end = match.end() - (len(raw) - len(base))
        elif start is not None:
            if not any(left < end and start < right for left, right in control_ranges):
                spans.append(source[start:end])
            start = None
    if start is not None:
        if not any(left < end and start < right for left, right in control_ranges):
            spans.append(source[start:end])
    return tuple(
        anchor.strip()
        for anchor in spans
        if anchor.strip()
        and _substantive(anchor)
    )


def _source_bound_anchors(
    proposals: list[str],
    sources: tuple[str, ...],
    limits: AnswerLimits,
    *,
    expand_literal_tokens: bool = False,
) -> tuple[str, ...]:
    catalog = tuple(anchor for source in sources for anchor in _entity_spans(source))
    selected: list[str] = []
    seen: set[str] = set()
    for proposal in proposals:
        if _contains_control_label(proposal):
            continue
        matched_entity = False
        for anchor in catalog:
            key = _comparison(anchor)
            if _contains_token_span(proposal, anchor) and key not in seen:
                if len(anchor) > limits.max_query_characters:
                    raise ValueError("normalized anchor exceeds query budget")
                selected.append(anchor)
                seen.add(key)
                matched_entity = True
                if len(selected) > limits.max_queries_per_hop:
                    raise ValueError("normalized anchor count exceeds query budget")
        if matched_entity:
            continue
        for source in sources:
            spans = _literal_source_spans(proposal, source)
            for anchor in spans if expand_literal_tokens else spans[:1]:
                if _comparison(anchor) in seen:
                    continue
                if len(anchor) > limits.max_query_characters:
                    raise ValueError("normalized anchor exceeds query budget")
                if len(selected) == limits.max_queries_per_hop:
                    return tuple(selected)
                selected.append(anchor)
                seen.add(_comparison(anchor))
    return tuple(selected)


def _later_hop_anchors(
    proposals: list[str], sources: tuple[str, ...], seen: set[str], limits: AnswerLimits
) -> tuple[str, ...]:
    selected = _source_bound_anchors(
        proposals, sources, limits, expand_literal_tokens=True
    )
    catalog = tuple(
        anchor
        for source in sources
        for anchor in (*_entity_spans(source), *_authorized_literal_tokens(source))
    )
    ordered: list[str] = []
    keys = set(seen)
    for anchor in (*catalog, *selected):
        key = _comparison(anchor)
        if key not in keys:
            ordered.append(anchor)
            keys.add(key)
        if len(ordered) == limits.max_queries_per_hop:
            break
    return tuple(ordered)


@dataclass(frozen=True, slots=True)
class AnswerReadContext:
    """Complete immutable caller context reapplied at every retrieval hop."""

    tenant_id: str
    branch: str = "main"
    user_id: str | None = None
    role: str = "reader"
    source_identity: str | None = None
    source_trust_tier: int | None = None
    min_trust_tier: int | None = None
    max_trust_tier: int | None = None
    max_sensitivity: int | None = None
    capability_tags: tuple[str, ...] = ()
    purpose: tuple[str, ...] = ()
    residency: str | None = None
    region: str | None = None
    lawful_basis: tuple[str, ...] = ()
    break_glass: bool = False
    as_of: datetime | str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.branch or not self.role:
            raise ValueError("answer read context requires tenant, branch, and role")
        if self.role not in {"reader", "agent", "consolidator", "operator"}:
            raise ValueError("answer read context has invalid role")
        if self.source_identity is not None and not self.source_identity:
            raise ValueError("answer read context has invalid source identity")
        for name, value in (
            ("source_trust_tier", self.source_trust_tier),
            ("min_trust_tier", self.min_trust_tier),
            ("max_trust_tier", self.max_trust_tier),
        ):
            _bounded_int(value, name, maximum=5)
        _bounded_int(self.max_sensitivity, "max_sensitivity", maximum=3)
        if (
            self.min_trust_tier is not None
            and self.max_trust_tier is not None
            and self.min_trust_tier != self.max_trust_tier
        ):
            raise ValueError("legacy min_trust_tier contradicts max_trust_tier")
        effective_max_trust = (
            self.max_trust_tier
            if self.max_trust_tier is not None
            else self.min_trust_tier
        )
        object.__setattr__(self, "min_trust_tier", None)
        object.__setattr__(self, "max_trust_tier", effective_max_trust)
        object.__setattr__(self, "capability_tags", _strings(self.capability_tags, "capability_tags"))
        object.__setattr__(self, "purpose", _strings(self.purpose, "purpose"))
        object.__setattr__(self, "lawful_basis", _strings(self.lawful_basis, "lawful_basis"))
        object.__setattr__(self, "as_of", _as_of(self.as_of))

    def to_filter(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "tenant_id": self.tenant_id,
            "tenant": self.tenant_id,
            "branch": self.branch,
            "role": self.role,
            "source_identity": self.source_identity,
            "break_glass": self.break_glass,
        }
        optional = {
            "user_id": self.user_id,
            "min_trust_tier": self.min_trust_tier,
            "max_trust_tier": self.max_trust_tier,
            "max_sensitivity": self.max_sensitivity,
            "residency": self.residency,
            "region": self.region,
            "as_of": self.as_of,
        }
        value.update({key: item for key, item in optional.items() if item is not None})
        if self.capability_tags:
            value["capability_tags"] = list(self.capability_tags)
        if self.purpose:
            value["purpose"] = list(self.purpose)
        if self.lawful_basis:
            value["lawful_basis"] = list(self.lawful_basis)
        if self.source_trust_tier is not None:
            current = value.get("max_trust_tier")
            value["max_trust_tier"] = (
                self.source_trust_tier
                if current is None
                else min(int(current), self.source_trust_tier)
            )
        return value

    def narrow(self, **changes: Any) -> AnswerReadContext:
        """Return a context with equal or narrower authorization, never wider."""
        changes = dict(changes)
        if "min_trust_tier" in changes:
            legacy = changes.pop("min_trust_tier")
            if "max_trust_tier" in changes and changes["max_trust_tier"] != legacy:
                raise ValueError("legacy min_trust_tier contradicts max_trust_tier")
            changes["max_trust_tier"] = legacy
        unknown = set(changes) - set(asdict(self))
        if unknown:
            raise ValueError("answer read context cannot add fields")
        current = asdict(self)
        for key in (
            "tenant_id", "branch", "user_id", "role", "source_identity",
            "residency", "region", "as_of",
        ):
            if key in changes and changes[key] != current[key]:
                raise ValueError(f"answer read context cannot widen or replace {key}")
        for key in ("capability_tags", "purpose", "lawful_basis"):
            if key in changes and not set(changes[key]) <= set(current[key]):
                raise ValueError(f"answer read context cannot widen {key}")
        if "max_sensitivity" in changes and not _upper_bound_narrows(
            current["max_sensitivity"], changes["max_sensitivity"]
        ):
            raise ValueError("answer read context cannot widen max_sensitivity")
        if "max_trust_tier" in changes and not _upper_bound_narrows(
            current["max_trust_tier"], changes["max_trust_tier"]
        ):
            raise ValueError("answer read context cannot widen max_trust_tier")
        if "source_trust_tier" in changes and not _upper_bound_narrows(
            current["source_trust_tier"], changes["source_trust_tier"]
        ):
            raise ValueError("answer read context cannot widen source_trust_tier")
        if current["break_glass"] is False and changes.get("break_glass") is True:
            raise ValueError("answer read context cannot widen break_glass")
        return AnswerReadContext(**{**current, **changes})


@dataclass(frozen=True, slots=True)
class ReflectDisposition:
    """Bounded 5-trait disposition and scoped mission directive for reflection."""

    skepticism: float = 0.5
    abstraction: float = 0.5
    conciseness: float = 0.5
    empathy: float = 0.5
    literalism: float = 0.5
    mission: str | None = None

    def __post_init__(self) -> None:
        for trait in ("skepticism", "abstraction", "conciseness", "empathy", "literalism"):
            val = getattr(self, trait)
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError(f"disposition {trait} must be a number between 0.0 and 1.0")
            fval = float(val)
            if not (0.0 <= fval <= 1.0):
                raise ValueError(f"disposition {trait} must be between 0.0 and 1.0")
            object.__setattr__(self, trait, fval)
        if self.mission is not None:
            if not isinstance(self.mission, str) or not self.mission.strip():
                raise ValueError("disposition mission must be a non-empty string")
            if len(self.mission) > 500:
                raise ValueError("disposition mission exceeds maximum length of 500 characters")
            cleaned = self.mission.strip()
            normalized = unicodedata.normalize("NFKC", cleaned)
            if _contains_control_label(cleaned) or _contains_control_label(normalized):
                raise ValueError("disposition mission contains forbidden control labels (I11 violation)")
            tokens = set(_anchor_tokens(cleaned))
            if _FALLBACK_DENY_TERMS.intersection(tokens):
                raise ValueError("disposition mission contains denied instruction terms (I11 violation)")
            object.__setattr__(self, "mission", cleaned)

    def max_claims(self, default_max: int = 20) -> int:
        if self.conciseness <= 0.5:
            return default_max
        # Scale down from default_max at 0.5 to 1..3 at 1.0
        ratio = (self.conciseness - 0.5) / 0.5
        return max(1, int(round(default_max * (1.0 - 0.85 * ratio))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "skepticism": self.skepticism,
            "abstraction": self.abstraction,
            "conciseness": self.conciseness,
            "empathy": self.empathy,
            "literalism": self.literalism,
            "mission": self.mission,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any] | ReflectDisposition,
        *,
        mission: str | None = None,
    ) -> ReflectDisposition:
        if isinstance(data, ReflectDisposition):
            if mission is not None and mission != data.mission:
                return cls(
                    skepticism=data.skepticism,
                    abstraction=data.abstraction,
                    conciseness=data.conciseness,
                    empathy=data.empathy,
                    literalism=data.literalism,
                    mission=mission,
                )
            return data
        if not isinstance(data, Mapping):
            raise ValueError("disposition must be a mapping or ReflectDisposition")
        allowed = {"skepticism", "abstraction", "conciseness", "empathy", "literalism", "mission"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise ValueError(f"disposition has unknown fields: {', '.join(sorted(unknown))}")
        kwargs: dict[str, Any] = {k: data[k] for k in allowed if k in data}
        if mission is not None:
            kwargs["mission"] = mission
        return cls(**kwargs)


def coerce_disposition(
    disposition: ReflectDisposition | Mapping[str, Any] | None = None,
    *,
    mission: str | None = None,
) -> ReflectDisposition | None:
    if disposition is None and mission is None:
        return None
    if disposition is None:
        return ReflectDisposition(mission=mission)
    return ReflectDisposition.from_dict(disposition, mission=mission)


@dataclass(frozen=True, slots=True)
class AnswerLimits:
    max_hops: int = 3
    max_queries_per_hop: int = 4
    max_evidence: int = 20
    max_characters: int = 24_000
    max_query_characters: int = 2_000

    def __post_init__(self) -> None:
        if min(asdict(self).values()) < 1:
            raise ValueError("answer limits must be positive")


@dataclass(frozen=True, slots=True)
class AnswerRequest:
    question: str
    context: AnswerReadContext

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("answer question must be non-empty")


@dataclass(frozen=True, slots=True)
class AnswerEvidence:
    cid: str
    content: str
    source_identity: str | None
    session_id: str | None
    turn_index: int | None
    hop: int


@dataclass(frozen=True, slots=True)
class AnswerEpisode:
    source_identity: str | None
    session_id: str | None
    evidence_cids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnswerHop:
    index: int
    queries: tuple[str, ...]
    retrieved_cids: tuple[str, ...]
    channels: tuple[str, ...]
    evidence_fingerprint: str
    context: AnswerReadContext


@dataclass(frozen=True, slots=True)
class AnswerTrace:
    hops: tuple[AnswerHop, ...]
    evidence_fingerprint: str


@dataclass(frozen=True, slots=True)
class AnswerClaim:
    text: str
    evidence_cids: tuple[str, ...]
    spans: tuple[AnswerSpan, ...] = ()
    synthesis_operation: str | None = None


@dataclass(frozen=True, slots=True)
class AnswerSpan:
    cid: str
    start: int
    end: int
    slice_sha256: str


GroundedFailureKind = Literal[
    "assembly_error", "reader_error", "replay_error", "replay_drift", "invalid_reader_proposal"
]


class _NoAuthorizedEvidence(LookupError):
    """An ordinary no-answer outcome, distinct from provider/storage failures."""


class _EvidenceReplayDrift(LookupError):
    """Previously assembled evidence is no longer the same authorized evidence."""


class _EvidenceReplayError(RuntimeError):
    """The evidence replay could not complete."""


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    answer: str
    claims: tuple[AnswerClaim, ...]
    evidence: tuple[AnswerEvidence, ...]
    episodes: tuple[AnswerEpisode, ...]
    trace: AnswerTrace
    abstained: bool
    public_reason: str | None = None
    # Internal retry classification only; public_grounded_answer never emits it.
    failure_kind: GroundedFailureKind | None = None


class QueryDecomposer(Protocol):
    def decompose(self, payload: dict[str, object]) -> object: ...


class GroundedReader(Protocol):
    def read(self, payload: dict[str, object]) -> object: ...


class GroundedProvider(QueryDecomposer, GroundedReader, Protocol):
    @property
    def disclosure(self) -> dict[str, object]: ...


def public_grounded_answer(
    result: GroundedAnswer,
    disclosure: dict[str, object],
    *,
    include_derivation: bool = False,
) -> dict[str, object]:
    """Serialize validated claims without exposing raw evidence or read context."""
    return {
        "answer": result.answer,
        "claims": [
            {
                "text": claim.text,
                **({"derivation": {
                    "schema_version": "mnemosyne.claim-derivation/v1",
                    "kind": "synthesis" if claim.synthesis_operation is not None else "quotation",
                    "operation": claim.synthesis_operation,
                }} if include_derivation else {}),
                "evidence_cids": list(claim.evidence_cids),
                "spans": [
                    {
                        "cid": span.cid,
                        "start": span.start,
                        "end": span.end,
                        "slice_sha256": span.slice_sha256,
                    }
                    for span in claim.spans
                ],
            }
            for claim in result.claims
        ],
        "abstained": result.abstained,
        "hops": [
            {
                "index": hop.index,
                "queries": list(hop.queries),
                "channels": list(hop.channels),
                "retrieved_cids": list(hop.retrieved_cids),
            }
            for hop in result.trace.hops
        ],
        "reader": disclosure,
    }


class GroundedAnswerOrchestrator:
    """Assemble authorized evidence without creating a new ranking or write path."""

    def __init__(
        self,
        engine: MemoryEngine,
        decomposer: QueryDecomposer,
        *,
        limits: AnswerLimits | None = None,
    ) -> None:
        self.engine = engine
        self.decomposer = decomposer
        self.limits = limits or AnswerLimits()

    def assemble(self, request: AnswerRequest) -> GroundedAnswer:
        try:
            return self._assemble(request)
        except _NoAuthorizedEvidence:
            return self._abstain()
        except _EvidenceReplayDrift:
            return self._abstain("replay_drift")
        except _EvidenceReplayError:
            return self._abstain("replay_error")
        except Exception:
            # Providers and storage are untrusted at this boundary. Any ordinary
            # failure collapses to the same public abstention; process-control
            # BaseExceptions still propagate.
            return self._abstain("assembly_error")

    def answer(
        self,
        request: AnswerRequest,
        reader: GroundedReader,
        *,
        disposition: ReflectDisposition | Mapping[str, Any] | None = None,
        mission: str | None = None,
        hierarchy_first: bool = False,
    ) -> GroundedAnswer:
        """Validate model-proposed atomic claims against freshly replayed evidence."""
        disp = coerce_disposition(disposition, mission=mission)
        use_hierarchy = bool(hierarchy_first or (disp is not None and disp.abstraction > 0.6 and disp.literalism <= 0.7))
        if use_hierarchy:
            hierarchical = resolve_hierarchical_evidence(
                self.engine,
                request.question,
                request.context,
                disposition=disp,
                mission=disp.mission if disp is not None else mission,
            )
            if hierarchical["resolved_layer"] in {"mental_model", "observation", "knowledge_page"} and hierarchical["claims"]:
                h_claims: tuple[AnswerClaim, ...] = tuple(hierarchical["claims"])
                if disp is not None:
                    h_claims = h_claims[: disp.max_claims(len(h_claims))]
                h_evidence: tuple[AnswerEvidence, ...] = tuple(hierarchical["answer_evidence"])
                if h_claims and h_evidence:
                    h_hop = AnswerHop(
                        index=0,
                        queries=(request.question,),
                        retrieved_cids=tuple(row.cid for row in h_evidence),
                        channels=(f"hierarchy:{hierarchical['resolved_layer']}",),
                        evidence_fingerprint=hierarchical["evidence_fingerprint"],
                        context=request.context,
                    )
                    return GroundedAnswer(
                        answer="\n".join(claim.text for claim in h_claims),
                        claims=h_claims,
                        evidence=h_evidence,
                        episodes=_episodes(h_evidence),
                        trace=AnswerTrace((h_hop,), hierarchical["evidence_fingerprint"]),
                        abstained=False,
                    )
        assembled = self.assemble(request)
        if assembled.abstained:
            return assembled
        try:
            proposal = reader.read(
                {
                    "question": request.question,
                    "evidence": [
                        {"cid": row.cid, "content": row.content}
                        for row in assembled.evidence
                    ],
                }
            )
        except Exception:
            return self._abstain("reader_error")
        replayed = self.assemble(request)
        if replayed.failure_kind is not None:
            return self._abstain("replay_drift" if replayed.failure_kind == "replay_drift" else "replay_error")
        if replayed.abstained or (
            replayed.trace.evidence_fingerprint
            != assembled.trace.evidence_fingerprint
            or replayed.evidence != assembled.evidence
            or replayed.trace.hops != assembled.trace.hops
        ):
            return self._abstain("replay_drift")
        try:
            claims = self._claims(proposal, {row.cid: row.content for row in replayed.evidence})
            if disp is not None and claims:
                claims = _apply_disposition_to_claims(claims, disp, replayed.evidence)
            if not claims:
                return self._reader_abstain(replayed)
            return GroundedAnswer(
                answer="\n".join(claim.text for claim in claims),
                claims=claims,
                evidence=replayed.evidence,
                episodes=replayed.episodes,
                trace=replayed.trace,
                abstained=False,
            )
        except Exception:
            return self._reader_abstain(replayed, "invalid_reader_proposal")

    @staticmethod
    def _reader_abstain(
        assembled: GroundedAnswer, failure_kind: GroundedFailureKind | None = None,
    ) -> GroundedAnswer:
        """Preserve authorized retrieval custody when only the reader abstains."""
        return GroundedAnswer(
            answer="", claims=(), evidence=assembled.evidence,
            episodes=assembled.episodes, trace=assembled.trace, abstained=True,
            failure_kind=failure_kind,
        )

    def _assemble(self, request: AnswerRequest) -> GroundedAnswer:
        if len(request.question) > self.limits.max_query_characters:
            raise ValueError("question budget exceeded")
        queries = self._queries(
            self.decomposer.decompose({"question": request.question, "evidence": []}),
            sources=(request.question,),
        )
        seen_queries: set[str] = set()
        authorized: dict[str, dict[str, Any]] = {}
        hop_maps: list[dict[str, dict[str, Any]]] = []
        cid_hop: dict[str, int] = {}
        hops: list[AnswerHop] = []
        for hop_index in range(self.limits.max_hops):
            fresh_queries = tuple(query for query in queries if _comparison(query) not in seen_queries)
            if not fresh_queries:
                break
            if len(fresh_queries) > self.limits.max_queries_per_hop:
                raise ValueError("query budget exceeded")
            seen_queries.update(_comparison(query) for query in fresh_queries)
            referenced: set[str] = set()
            channels: set[str] = set()
            for query in fresh_queries:
                query_refs, query_channels = self._retrieve(query, request.context)
                referenced.update(query_refs)
                channels.update(query_channels)
            current = self._authorized_rows(request.context, referenced)
            hop_maps.append(current)
            for cid, row in current.items():
                authorized.setdefault(cid, row)
                cid_hop.setdefault(cid, hop_index)
            if len(authorized) > self.limits.max_evidence:
                raise ValueError("evidence budget exceeded")
            if sum(len(row["content"]) for row in authorized.values()) > self.limits.max_characters:
                raise ValueError("character budget exceeded")
            hops.append(
                AnswerHop(
                    index=hop_index,
                    queries=fresh_queries,
                    retrieved_cids=tuple(sorted(current)),
                    channels=tuple(sorted(channels)),
                    evidence_fingerprint=_fingerprint(current),
                    context=request.context,
                )
            )
            if hop_index + 1 >= self.limits.max_hops:
                break
            payload = {
                "question": request.question,
                "evidence": [
                    {"cid": cid, "content": row.get("content", "")}
                    for cid, row in sorted(authorized.items())
                ],
            }
            response = self.decomposer.decompose(payload)
            sources = tuple(row["content"] for row in payload["evidence"])
            proposals = self._query_proposals(response)
            queries = _later_hop_anchors(
                proposals, sources, seen_queries, self.limits
            )
            if not queries:
                break
        if not authorized:
            raise _NoAuthorizedEvidence("no authorized evidence")
        fingerprint = _fingerprint(authorized)
        replayed: dict[str, dict[str, Any]] = {}
        try:
            for hop, original_hop_map in zip(hops, hop_maps, strict=True):
                replayed_refs: set[str] = set()
                for query in hop.queries:
                    query_refs, _ = self._retrieve(query, request.context)
                    replayed_refs.update(query_refs)
                replayed_hop_map = self._authorized_rows(request.context, replayed_refs)
                if (
                    set(replayed_hop_map) != set(original_hop_map)
                    or _fingerprint(replayed_hop_map) != hop.evidence_fingerprint
                ):
                    raise _EvidenceReplayDrift("authorized evidence changed")
                replayed.update(replayed_hop_map)
            if set(replayed) != set(authorized) or _fingerprint(replayed) != fingerprint:
                raise _EvidenceReplayDrift("authorized evidence changed")
        except _NoAuthorizedEvidence as exc:
            raise _EvidenceReplayDrift("authorized evidence changed") from exc
        except _EvidenceReplayDrift:
            raise
        except Exception as exc:
            raise _EvidenceReplayError("authorized evidence replay failed") from exc
        evidence = tuple(
            self._evidence(cid, row, cid_hop[cid])
            for cid, row in sorted(replayed.items(), key=lambda item: _episode_key(item[1], item[0]))
        )
        episodes = _episodes(evidence)
        return GroundedAnswer(
            answer="",
            claims=(),
            evidence=evidence,
            episodes=episodes,
            trace=AnswerTrace(tuple(hops), fingerprint),
            abstained=False,
        )

    def _authorized_rows(
        self, context: AnswerReadContext, referenced: set[str]
    ) -> dict[str, dict[str, Any]]:
        if not referenced:
            return {}
        exported = self.engine.export_tenant_filtered(context.tenant_id, context.to_filter())
        rows = exported.get("evidence")
        if not isinstance(rows, list):
            raise ValueError("authorized export has invalid evidence")
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            cid = row.get("cid")
            if (
                isinstance(cid, str)
                and cid in referenced
                and row.get("branch", "main") == context.branch
                and not bool(row.get("erased"))
                and not _quarantined(row)
            ):
                content = row.get("content")
                if not isinstance(content, str) or not content:
                    raise ValueError("authorized evidence content must be a non-empty string")
                raw = self.engine.get_evidence(context.tenant_id, cid, context.branch)
                if (
                    raw is None
                    or raw.cid != cid
                    or raw.tenant_id != context.tenant_id
                    or raw.branch != context.branch
                    or raw.erased
                    or (context.as_of is not None and raw.created_at > context.as_of)
                ):
                    raise LookupError("authorized evidence is no longer active")
                authorized = dict(row)
                authorized["_access_policy_sha256"] = hashlib.sha256(
                    json.dumps(
                        raw.access_policy,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode()
                ).hexdigest()
                result[cid] = authorized
        return result

    def _retrieve(
        self, query: str, context: AnswerReadContext
    ) -> tuple[set[str], set[str]]:
        if not query or len(query) > self.limits.max_query_characters:
            raise ValueError("query budget exceeded")
        result = self.engine.retrieve(
            query,
            tenant_id=context.tenant_id,
            branch=context.branch,
            deep=True,
            filt=context.to_filter(),
            record_access=False,
        )
        if result.abstained:
            # Incomplete first-hop coverage is exactly why a decomposer needs
            # another hop. Keep hard grounding gates, but defer answerability
            # until source-bound expansion and final claim validation finish.
            explain = result.explain
            if (
                not result.hits
                or explain.get("gist_support", {}).get("applied")
                or explain.get("standing", {}).get("abstention_gate", {}).get("active")
                or explain.get("answer_grounding_floor", {}).get("active")
                or explain.get("reality_monitoring", {}).get("ungrounded_only")
                or not explain.get("confidence", {}).get("query_support")
            ):
                raise _NoAuthorizedEvidence("retrieval abstained")
        referenced: set[str] = set()
        channels: set[str] = set()
        for hit in result.hits:
            channels.add(str(hit.channel))
            if hit.kind == "evidence":
                if hit.provenance and set(hit.provenance) != {hit.id}:
                    raise ValueError("evidence hit has invalid provenance")
                referenced.add(str(hit.id))
                continue
            if hit.kind not in {"assertion", "relation", "preference"}:
                raise ValueError("retrieval returned an unknown hit kind")
            source_cids = _strict_source_cids(hit.metadata.get("source_evidence_cids"))
            if set(str(cid) for cid in hit.provenance) != set(source_cids):
                raise ValueError("projection hit provenance is inconsistent")
            referenced.update(source_cids)
        return referenced, channels

    def _queries(self, value: object, *, sources: tuple[str, ...]) -> tuple[str, ...]:
        return _source_bound_anchors(self._query_proposals(value), sources, self.limits)

    def _query_proposals(self, value: object) -> list[str]:
        if not isinstance(value, dict) or set(value) != {"queries"}:
            raise ValueError("invalid decomposer schema")
        raw = value["queries"]
        if not isinstance(raw, list) or len(raw) > self.limits.max_queries_per_hop:
            raise ValueError("invalid decomposer queries")
        proposals: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str) or not item.strip() or len(item) > self.limits.max_query_characters:
                raise ValueError("invalid decomposer query")
            proposal = item.strip()
            key = _comparison(proposal)
            if key not in seen:
                proposals.append(proposal)
                seen.add(key)
        return proposals

    @staticmethod
    def _claims(value: object, evidence: dict[str, str]) -> tuple[AnswerClaim, ...]:
        if not evidence or any(
            not isinstance(cid, str) or not cid or not isinstance(content, str) or not content
            for cid, content in evidence.items()
        ):
            raise ValueError("reader evidence must contain exact non-empty strings")
        if not isinstance(value, dict) or set(value) != {"claims", "unresolved"}:
            raise ValueError("invalid reader schema")
        unresolved = value["unresolved"]
        rows = value["claims"]
        if not isinstance(unresolved, bool) or not isinstance(rows, list):
            raise ValueError("invalid reader schema")
        if unresolved:
            if rows:
                raise ValueError("unresolved reader response contains claims")
            return ()
        if not rows or len(rows) > 20:
            raise ValueError("reader must return bounded claims")
        claims: list[AnswerClaim] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) not in ({"spans"}, {"synthesis"}):
                raise ValueError("invalid claim schema")
            synthesis = row["synthesis"] if "synthesis" in row else None
            if "synthesis" in row:
                if not isinstance(synthesis, dict) or set(synthesis) != {"operation", "spans"}:
                    raise ValueError("invalid synthesis schema")
                raw_spans = synthesis["spans"]
                max_spans = 16
            else:
                raw_spans = row["spans"]
                max_spans = 3
            if not isinstance(raw_spans, list) or not raw_spans or len(raw_spans) > max_spans:
                raise ValueError("claim spans are invalid")
            spans: list[AnswerSpan] = []
            occupied: dict[str, list[tuple[int, int]]] = {}
            for raw in raw_spans:
                if not isinstance(raw, dict) or set(raw) != {"cid", "quote"}:
                    raise ValueError("claim span schema is invalid")
                cid, quote = raw["cid"], raw["quote"]
                if not isinstance(cid, str) or cid not in evidence or not isinstance(quote, str) or not quote or len(quote) > 2_000:
                    raise ValueError("claim quote is invalid")
                start = evidence[cid].find(quote)
                if start < 0:
                    raise ValueError("claim quote is outside authorized evidence")
                if synthesis is not None and evidence[cid].find(quote, start + 1) >= 0:
                    raise ValueError("synthesis claim quote is ambiguous")
                end = start + len(quote)
                if any(start < right and left < end for left, right in occupied.setdefault(cid, [])):
                    raise ValueError("claim spans overlap")
                occupied[cid].append((start, end))
                spans.append(AnswerSpan(cid, start, end, hashlib.sha256(quote.encode("utf-8")).hexdigest()))
            if synthesis is not None:
                try:
                    result = DeterministicSynthesizer().synthesize(synthesis)
                except Exception as exc:
                    raise ValueError("invalid synthesis proposal") from exc
                if (
                    set(result) != {"answer", "operation", "provenance", "unresolved"}
                    or result["operation"] != synthesis["operation"]
                    or result["provenance"] != raw_spans
                    or result["unresolved"] is not False
                ):
                    raise ValueError("invalid synthesis result")
                rendered = result["answer"]
            else:
                rendered = " ".join(evidence[span.cid][span.start:span.end] for span in spans)
            if not isinstance(rendered, str) or not rendered.strip() or len(rendered) > 2_000:
                raise ValueError("claim span rendering is invalid")
            claims.append(AnswerClaim(rendered, tuple(dict.fromkeys(span.cid for span in spans)), tuple(spans),
                                      synthesis["operation"] if synthesis is not None else None))
        return tuple(claims)

    @staticmethod
    def _evidence(cid: str, row: Mapping[str, Any], hop: int) -> AnswerEvidence:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        episode = metadata.get("episode") if isinstance(metadata.get("episode"), Mapping) else {}
        if episode:
            _validate_episode(episode, row)
        source_identity = episode.get("source_identity", row.get("source_identity"))
        session_id = episode.get("session_id", row.get("session_id"))
        turn_index = episode.get("turn_index")
        return AnswerEvidence(
            cid=cid,
            content=_required_content(row),
            source_identity=str(source_identity) if source_identity else None,
            session_id=str(session_id) if session_id else None,
            turn_index=turn_index if isinstance(turn_index, int) and not isinstance(turn_index, bool) else None,
            hop=hop,
        )

    @staticmethod
    def _abstain(failure_kind: GroundedFailureKind | None = None) -> GroundedAnswer:
        return GroundedAnswer(
            answer="",
            claims=(),
            evidence=(),
            episodes=(),
            trace=AnswerTrace((), ""),
            abstained=True,
            public_reason=_PUBLIC_ABSTENTION,
            failure_kind=failure_kind,
        )


def episode_metadata(
    *, session_id: str, source_identity: str, turn_index: int
) -> dict[str, dict[str, object]]:
    """Validate the only non-oracle metadata admitted for episode adjacency."""
    if not session_id or not source_identity:
        raise ValueError("episode metadata requires session and source identity")
    if not isinstance(turn_index, int) or isinstance(turn_index, bool) or turn_index < 0:
        raise ValueError("episode turn index must be a non-negative integer")
    return {
        "episode": {
            "session_id": session_id,
            "source_identity": source_identity,
            "turn_index": turn_index,
        }
    }


def _fingerprint(rows: Mapping[str, Mapping[str, Any]]) -> str:
    payload = []
    for cid in sorted(rows):
        row = rows[cid]
        metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        payload.append(
            {
                "authorization": _authorization_metadata(row),
                "access_policy_sha256": row.get("_access_policy_sha256"),
                "branch": row.get("branch", "main"),
                "cid": cid,
                "content_sha256": hashlib.sha256(str(row.get("content") or "").encode()).hexdigest(),
                "erased": bool(row.get("erased")),
                "sensitivity": row.get("sensitivity"),
                "source_evidence_cids": _source_cids(row.get("source_evidence_cids")),
                "status": row.get("status", "active"),
                "tenant_id": row.get("tenant_id"),
                "trust_tier": row.get("trust_tier"),
                "valid_from": row.get("valid_from"),
                "valid_to": row.get("valid_to"),
                "quarantined": bool(metadata.get("quarantine_reason")),
                "safe_episode": metadata.get("episode"),
                "session_id": row.get("session_id"),
                "source_identity": row.get("source_identity"),
            }
        )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _episode_key(row: Mapping[str, Any], cid: str) -> tuple[str, str, int, str]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    episode = metadata.get("episode") if isinstance(metadata.get("episode"), Mapping) else {}
    turn = episode.get("turn_index")
    return (
        str(episode.get("source_identity") or row.get("source_identity") or ""),
        str(episode.get("session_id") or row.get("session_id") or ""),
        turn if isinstance(turn, int) and not isinstance(turn, bool) else 2**63 - 1,
        cid,
    )


def _episodes(evidence: Sequence[AnswerEvidence]) -> tuple[AnswerEpisode, ...]:
    groups: list[list[AnswerEvidence]] = []
    for row in evidence:
        previous = groups[-1][-1] if groups else None
        adjacent = (
            previous is not None
            and row.source_identity == previous.source_identity
            and row.session_id == previous.session_id
            and row.source_identity is not None
            and row.session_id is not None
            and row.turn_index is not None
            and previous.turn_index is not None
            and row.turn_index == previous.turn_index + 1
        )
        if adjacent:
            groups[-1].append(row)
        else:
            groups.append([row])
    return tuple(
        AnswerEpisode(
            source_identity=group[0].source_identity,
            session_id=group[0].session_id,
            evidence_cids=tuple(row.cid for row in group),
        )
        for group in groups
    )


def _quarantined(row: Mapping[str, Any]) -> bool:
    metadata = row.get("metadata")
    return isinstance(metadata, Mapping) and bool(metadata.get("quarantine_reason"))


def _authorization_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    privacy = row.get("privacy")
    if not isinstance(privacy, Mapping):
        return {}
    return {
        key: privacy.get(key)
        for key in (
            "access_decision",
            "effective_max_sensitivity",
            "redacted",
            "role",
            "unknown_access_policy_keys",
        )
        if key in privacy
    }


def _source_cids(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return sorted(str(item) for item in value if str(item))


def _strict_source_cids(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ValueError("projection hit has invalid source evidence")
    return tuple(dict.fromkeys(value))


def _as_of(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        if not value or ("Z" not in value and "+" not in value[10:] and "-" not in value[10:]):
            raise ValueError("answer as_of must include a timezone")
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("answer as_of must be an ISO datetime") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("answer as_of must be timezone-aware")
    return value.astimezone(UTC)


def _validate_episode(episode: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    if set(episode) != {"session_id", "source_identity", "turn_index"}:
        raise ValueError("episode metadata has invalid schema")
    if (
        not isinstance(episode["session_id"], str)
        or not episode["session_id"]
        or not isinstance(episode["source_identity"], str)
        or not episode["source_identity"]
        or episode["session_id"] != row.get("session_id")
        or episode["source_identity"] != row.get("source_identity")
        or not isinstance(episode["turn_index"], int)
        or isinstance(episode["turn_index"], bool)
        or episode["turn_index"] < 0
    ):
        raise ValueError("episode metadata does not match canonical evidence")


def _strings(value: Sequence[str], field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{field} must contain non-empty strings")
    return tuple(dict.fromkeys(value))


def _upper_bound_narrows(current: int | None, candidate: int | None) -> bool:
    return candidate is not None and (current is None or candidate <= current)


def _bounded_int(value: object, name: str, *, maximum: int) -> None:
    if value is None:
        return
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > maximum
    ):
        raise ValueError(f"answer read context has invalid {name}")


def _query_substantive_terms(text: str) -> set[str]:
    terms = {
        normalise_query_term(token)
        for token in tokenize(text)
        if len(normalise_query_term(token)) > 2 and normalise_query_term(token) not in QUERY_SUPPORT_STOPWORDS
    }
    if not terms:
        terms = {normalise_query_term(token) for token in tokenize(text) if normalise_query_term(token)}
    return terms


def _apply_disposition_to_claims(
    claims: tuple[AnswerClaim, ...],
    disp: ReflectDisposition,
    evidence: Sequence[AnswerEvidence],
) -> tuple[AnswerClaim, ...]:
    if not claims:
        return claims
    selected = list(claims)
    if disp.literalism > 0.7:
        literal_only = [c for c in selected if c.synthesis_operation is None]
        if literal_only:
            selected = literal_only
    if disp.mission:
        mission_terms = _query_substantive_terms(disp.mission)
        if mission_terms:
            ev_map = {row.cid: row.content for row in evidence}
            scored = []
            for idx, claim in enumerate(selected):
                claim_text = claim.text + " " + " ".join(ev_map.get(cid, "") for cid in claim.evidence_cids)
                overlap = len(_query_substantive_terms(claim_text) & mission_terms)
                scored.append((-overlap, idx, claim))
            scored.sort()
            if any(item[0] < 0 for item in scored):
                selected = [item[2] for item in scored if item[0] < 0] or [item[2] for item in scored]
    max_count = disp.max_claims(len(selected))
    return tuple(selected[:max_count])


def _verify_live_authorized_evidence(
    engine: Any,
    context: AnswerReadContext,
    cids: Sequence[str],
    *,
    disposition: ReflectDisposition | None = None,
) -> dict[str, dict[str, Any]]:
    if not cids:
        return {}
    unique_cids = list(dict.fromkeys(str(c) for c in cids if isinstance(c, str) and c))
    if not unique_cids:
        return {}
    exported_map: dict[str, Mapping[str, Any]] = {}
    if callable(getattr(engine, "export_tenant_filtered", None)):
        try:
            exported = engine.export_tenant_filtered(context.tenant_id, context.to_filter())
            for row in exported.get("evidence", []) or []:
                if isinstance(row, Mapping) and isinstance(row.get("cid"), str):
                    exported_map[row["cid"]] = row
        except Exception:
            exported_map = {}

    verified: dict[str, dict[str, Any]] = {}
    for cid in unique_cids:
        raw = engine.get_evidence(context.tenant_id, cid, context.branch) if callable(getattr(engine, "get_evidence", None)) else None
        if (
            raw is None
            or getattr(raw, "cid", None) != cid
            or getattr(raw, "tenant_id", context.tenant_id) != context.tenant_id
            or getattr(raw, "branch", context.branch) != context.branch
            or bool(getattr(raw, "erased", False))
            or getattr(raw, "retired_at", None) is not None
        ):
            continue
        created_at = getattr(raw, "created_at", None)
        if context.as_of is not None and isinstance(created_at, datetime) and created_at > context.as_of:
            continue
        if exported_map and cid not in exported_map:
            continue
        exp_row = exported_map.get(cid, {})
        if exp_row and (bool(exp_row.get("erased")) or _quarantined(exp_row)):
            continue
        trust_tier = getattr(raw, "trust_tier", exp_row.get("trust_tier", 0))
        if disposition is not None and disposition.skepticism > 0.8 and isinstance(trust_tier, int) and trust_tier >= 4:
            continue
        content = getattr(raw, "content", None) or (exp_row.get("content") if isinstance(exp_row, Mapping) else None)
        if not isinstance(content, str) or not content:
            continue
        row_dict = dict(exp_row) if isinstance(exp_row, Mapping) and exp_row else {
            "cid": cid,
            "content": content,
            "tenant_id": context.tenant_id,
            "branch": context.branch,
            "erased": False,
            "sensitivity": getattr(raw, "sensitivity", 0),
            "trust_tier": trust_tier,
            "source_identity": getattr(raw, "source_identity", None),
            "session_id": getattr(raw, "session_id", None),
            "metadata": getattr(raw, "metadata", {}) or {},
        }
        row_dict["content"] = content
        row_dict["_access_policy_sha256"] = hashlib.sha256(
            json.dumps(
                getattr(raw, "access_policy", {}) or {},
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
        verified[cid] = row_dict
    return verified


def resolve_hierarchical_evidence(
    engine: Any,
    question: str = "",
    context: AnswerReadContext | None = None,
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    branch: str = "main",
    disposition: ReflectDisposition | Mapping[str, Any] | None = None,
    mission: str | None = None,
) -> dict[str, Any]:
    """Resolve evidence hierarchically: MentalModels -> Observations/KnowledgePages -> Raw Evidence."""
    if context is None:
        context = AnswerReadContext(
            tenant_id=str(tenant_id or "default"),
            branch=str(branch or "main"),
            user_id=user_id,
        )
    disp = coerce_disposition(disposition, mission=mission)
    q_terms = _query_substantive_terms(question)
    mission_terms = _query_substantive_terms(disp.mission) if disp and disp.mission else set()

    layers_checked: list[str] = []
    matched_models: list[dict[str, Any]] = []
    matched_observations: list[dict[str, Any]] = []
    matched_pages: list[dict[str, Any]] = []
    contested_caveats: list[str] = []
    resolved_layer = "none"
    claims: list[AnswerClaim] = []
    verified_rows: dict[str, dict[str, Any]] = {}

    # Layer 1: Ready, non-stale MentalModels
    layers_checked.append("mental_model")
    if context.user_id and not context.break_glass:
        try:
            from mnemosyne.mental_models import MentalModelService

            mm_service = MentalModelService(engine)
            models = mm_service.list(context)
        except Exception:
            models = []
        for model in models:
            if not isinstance(model, Mapping):
                continue
            if model.get("status") != "ready" or bool(model.get("stale", False)):
                continue
            m_text = f"{model.get('name', '')} {model.get('question', '')} {model.get('answer', '')}"
            m_terms = _query_substantive_terms(m_text)
            if _comparison(str(model.get("question", ""))) != _comparison(question) and not (q_terms & m_terms):
                continue
            cids = list(model.get("source_evidence_cids") or [])
            if not cids:
                continue
            live_map = _verify_live_authorized_evidence(engine, context, cids, disposition=disp)
            if len(live_map) != len(set(cids)):
                continue
            # Build verified AnswerClaims from model claims or live evidence spans
            model_claims: list[AnswerClaim] = []
            for raw_claim in model.get("claims") or []:
                if not isinstance(raw_claim, Mapping):
                    continue
                c_text = str(raw_claim.get("text") or "").strip()
                c_spans: list[AnswerSpan] = []
                for raw_span in raw_claim.get("spans") or []:
                    if not isinstance(raw_span, Mapping):
                        continue
                    scid = str(raw_span.get("cid") or "")
                    start = raw_span.get("start")
                    end = raw_span.get("end")
                    sha = raw_span.get("slice_sha256")
                    if (
                        scid in live_map
                        and isinstance(start, int)
                        and isinstance(end, int)
                        and 0 <= start < end <= len(live_map[scid]["content"])
                    ):
                        actual_slice = live_map[scid]["content"][start:end]
                        actual_sha = hashlib.sha256(actual_slice.encode("utf-8")).hexdigest()
                        if sha is None or sha == actual_sha:
                            c_spans.append(AnswerSpan(scid, start, end, actual_sha))
                if c_text and c_spans:
                    deriv = raw_claim.get("derivation")
                    op = deriv.get("operation") if isinstance(deriv, Mapping) else None
                    model_claims.append(
                        AnswerClaim(
                            text=c_text,
                            evidence_cids=tuple(dict.fromkeys(s.cid for s in c_spans)),
                            spans=tuple(c_spans),
                            synthesis_operation=op if isinstance(op, str) else None,
                        )
                    )
            if model_claims:
                matched_models.append(dict(model))
                verified_rows.update(live_map)
                claims.extend(model_claims)
        if matched_models and claims:
            resolved_layer = "mental_model"

    # Layer 2: Active corroborated Observations & KnowledgePages
    if resolved_layer == "none":
        layers_checked.append("observation")
        raw_obs_list: list[Any] = []
        for method_name in ("list_observations", "observation_list"):
            fn = getattr(engine, method_name, None)
            if callable(fn):
                try:
                    raw_obs_list = list(
                        fn(
                            context.tenant_id,
                            branch=context.branch,
                            user_id=context.user_id,
                            status="active",
                        )
                    )
                    break
                except TypeError:
                    try:
                        raw_obs_list = list(fn(context.tenant_id, branch=context.branch))
                        break
                    except Exception:
                        pass
                except Exception:
                    pass

        from mnemosyne.observations import ProofQuote, verify_proof_quote

        scored_obs: list[tuple[int, float, dict[str, Any], list[AnswerClaim], dict[str, dict[str, Any]]]] = []
        for item in raw_obs_list:
            obs_dict = item.to_dict() if hasattr(item, "to_dict") else (dict(item) if isinstance(item, Mapping) else None)
            if not isinstance(obs_dict, dict):
                continue
            if obs_dict.get("status", "active") != "active":
                continue
            if context.user_id and obs_dict.get("user_id") and obs_dict.get("user_id") != context.user_id:
                continue
            indep_sources = int(obs_dict.get("independent_source_count", 1) or 1)
            standing = float(obs_dict.get("standing", 0.51) or 0.51)
            if disp is not None and disp.skepticism > 0.7 and (indep_sources < 2 and standing < 0.6):
                continue
            obs_text = f"{obs_dict.get('subject', '')} {obs_dict.get('topic', '')} {obs_dict.get('content', '')}"
            obs_terms = _query_substantive_terms(obs_text)
            overlap = len(q_terms & obs_terms)
            if mission_terms:
                overlap += 2 * len(mission_terms & obs_terms)
            if overlap == 0 and q_terms:
                continue
            raw_quotes = [ProofQuote.from_dict(q) for q in (obs_dict.get("proof_quotes") or [])]
            # Preserve multimodal block_index ordering
            raw_quotes.sort(key=lambda q: (0, q.block_index) if q.block_index is not None else (1, 0))
            obs_cids = list(
                dict.fromkeys(
                    [*(obs_dict.get("source_evidence_cids") or []), *(q.cid for q in raw_quotes if q.cid)]
                )
            )
            if not obs_cids:
                continue
            live_map = _verify_live_authorized_evidence(engine, context, obs_cids, disposition=disp)
            if len(live_map) != len(set(obs_cids)):
                continue
            valid_spans: list[AnswerSpan] = []
            quotes_valid = True
            for pq in raw_quotes:
                if pq.cid not in live_map:
                    quotes_valid = False
                    break
                ev_content = live_map[pq.cid]["content"]
                try:
                    verify_proof_quote(pq, ev_content, is_erased=False, is_retired=False)
                except Exception:
                    quotes_valid = False
                    break
                start = pq.start if pq.start is not None else ev_content.find(pq.quote)
                end = pq.end if pq.end is not None else (start + len(pq.quote))
                if 0 <= start < end <= len(ev_content):
                    slice_text = ev_content[start:end]
                    valid_spans.append(
                        AnswerSpan(
                            pq.cid,
                            start,
                            end,
                            hashlib.sha256(slice_text.encode("utf-8")).hexdigest(),
                        )
                    )
            if not quotes_valid:
                continue
            if not valid_spans:
                # Fallback span from first source_evidence_cid
                first_cid = obs_cids[0]
                ev_content = live_map[first_cid]["content"]
                quote_text = ev_content.strip() or ev_content
                start = ev_content.find(quote_text)
                end = start + len(quote_text)
                valid_spans.append(
                    AnswerSpan(
                        first_cid,
                        start,
                        end,
                        hashlib.sha256(quote_text.encode("utf-8")).hexdigest(),
                    )
                )
            contradictions = obs_dict.get("contradiction_history") or []
            if contradictions and (disp is None or disp.skepticism >= 0.5):
                for c in contradictions:
                    if isinstance(c, Mapping) and c.get("content"):
                        contested_caveats.append(f"Supersedes prior observation: {c['content']}")
            claim_text = " ".join(
                live_map[s.cid]["content"][s.start : s.end] for s in valid_spans
            ).strip() or str(obs_dict.get("content") or "").strip()
            obs_claim = AnswerClaim(
                text=claim_text,
                evidence_cids=tuple(dict.fromkeys(s.cid for s in valid_spans)),
                spans=tuple(valid_spans),
                synthesis_operation=None,
            )
            scored_obs.append((-overlap, -standing, obs_dict, [obs_claim], live_map))

        scored_obs.sort(key=lambda item: (item[0], item[1]))
        for _, _, obs_dict, obs_claims, live_map in scored_obs:
            matched_observations.append(obs_dict)
            verified_rows.update(live_map)
            claims.extend(obs_claims)
        if matched_observations and claims:
            resolved_layer = "observation"

    if resolved_layer == "none":
        layers_checked.append("knowledge_page")
        raw_pages: list[Any] = []
        for method_name in ("list_knowledge_pages", "knowledge_page_list"):
            fn = getattr(engine, method_name, None)
            if callable(fn):
                try:
                    raw_pages = list(fn(context.tenant_id, branch=context.branch, status="active"))
                    break
                except TypeError:
                    try:
                        raw_pages = list(fn(context.tenant_id, branch=context.branch))
                        break
                    except Exception:
                        pass
                except Exception:
                    pass
        for page in raw_pages:
            page_dict = page.to_dict() if hasattr(page, "to_dict") else (dict(page) if isinstance(page, Mapping) else None)
            if not isinstance(page_dict, dict):
                continue
            if page_dict.get("status", "active") != "active" or bool(page_dict.get("stale", False)):
                continue
            if context.user_id and page_dict.get("user_id") and page_dict.get("user_id") != context.user_id:
                continue
            p_text = f"{page_dict.get('path', '')} {page_dict.get('title', '')} {page_dict.get('content_markdown', '')}"
            p_terms = _query_substantive_terms(p_text)
            if not (q_terms & p_terms):
                continue
            p_cids = list(page_dict.get("source_evidence_cids") or [])
            if not p_cids:
                continue
            live_map = _verify_live_authorized_evidence(engine, context, p_cids, disposition=disp)
            if len(live_map) != len(set(p_cids)):
                continue
            page_spans: list[AnswerSpan] = []
            for cid in p_cids:
                ev_content = live_map[cid]["content"]
                quote_text = ev_content.strip() or ev_content
                start = ev_content.find(quote_text)
                end = start + len(quote_text)
                page_spans.append(
                    AnswerSpan(
                        cid,
                        start,
                        end,
                        hashlib.sha256(quote_text.encode("utf-8")).hexdigest(),
                    )
                )
            if page_spans:
                matched_pages.append(page_dict)
                verified_rows.update(live_map)
                claims.append(
                    AnswerClaim(
                        text=" ".join(live_map[s.cid]["content"][s.start : s.end] for s in page_spans),
                        evidence_cids=tuple(dict.fromkeys(s.cid for s in page_spans)),
                        spans=tuple(page_spans),
                        synthesis_operation=None,
                    )
                )
        if matched_pages and claims:
            resolved_layer = "knowledge_page"

    # Layer 3: Raw Evidence / Assertion fallback
    if resolved_layer == "none":
        layers_checked.append("evidence")
        try:
            retrieved = engine.retrieve(
                question,
                tenant_id=context.tenant_id,
                branch=context.branch,
                deep=True,
                filt=context.to_filter(),
                record_access=False,
            )
            fallback_cids: list[str] = []
            for hit in getattr(retrieved, "hits", []) or []:
                if getattr(hit, "kind", None) == "evidence":
                    fallback_cids.append(str(hit.id))
                else:
                    fallback_cids.extend(
                        str(c) for c in (getattr(hit, "metadata", {}) or {}).get("source_evidence_cids", []) if c
                    )
            live_map = _verify_live_authorized_evidence(engine, context, fallback_cids, disposition=disp)
            if live_map:
                verified_rows.update(live_map)
                resolved_layer = "evidence"
        except Exception:
            pass

    answer_evidence = tuple(
        GroundedAnswerOrchestrator._evidence(cid, row, 0)
        for cid, row in sorted(verified_rows.items(), key=lambda item: _episode_key(item[1], item[0]))
    )
    fingerprint = _fingerprint(verified_rows) if verified_rows else ""

    return {
        "resolved_layer": resolved_layer,
        "layers_checked": layers_checked,
        "mental_models": matched_models,
        "observations": matched_observations,
        "knowledge_pages": matched_pages,
        "evidence_cids": [row.cid for row in answer_evidence],
        "evidence_rows": [{"cid": row.cid, "content": row.content} for row in answer_evidence],
        "answer_evidence": answer_evidence,
        "evidence_fingerprint": fingerprint,
        "claims": claims,
        "contested_caveats": contested_caveats,
        "mission_applied": disp.mission if disp is not None else None,
        "disposition": disp.to_dict() if disp is not None else None,
    }


_COUNT_INTENT_RE = re.compile(
    r"\b(?:how many|count\b|total number|number of|how often|frequency of)\b",
    re.IGNORECASE,
)
_TIMELINE_INTENT_RE = re.compile(
    r"\b(?:timeline|chronolog(?:y|ical|ically)|order of events|sequence of events|when did .* happen|history of|progression of|over time|step[- ]by[- ]step history)\b",
    re.IGNORECASE,
)
_STATE_DIFF_INTENT_RE = re.compile(
    r"\b(?:how did .* change|what changed|state change|state transition|before (?:and|vs\.?|versus) after|changed? from .* to|evolve[d]?|shift(?:ed)? from|used to .* now|previous(?:ly)? vs\.? current)\b",
    re.IGNORECASE,
)
_COMPARISON_INTENT_RE = re.compile(
    r"\b(?:compare|comparison|comparing|difference[s]? between|differ(?:s|ed)? from|versus|\bvs\.?\b|contrast|similarit(?:y|ies) and difference[s]?)\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?)\b")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_TRANSITION_INLINE_RE = re.compile(
    r"(?:changed\s+from|moved\s+from|migrated\s+from|switched\s+from|from)\s+([^.,;]+?)\s+to\s+([^.,;]+)",
    re.IGNORECASE,
)


def detect_synthesis_intent(question: str) -> str:
    """Classify the synthesis intent of a question."""
    if not isinstance(question, str) or not question.strip():
        return "fact"
    normalized = _comparison(question)
    if _COUNT_INTENT_RE.search(normalized):
        return "count"
    if _TIMELINE_INTENT_RE.search(normalized):
        return "timeline"
    if _STATE_DIFF_INTENT_RE.search(normalized):
        return "state_diff"
    if _COMPARISON_INTENT_RE.search(normalized):
        return "comparison"
    return "fact"


def _extract_temporal_sort_key(content: str, row: Mapping[str, Any], index: int) -> tuple[int, str, int]:
    iso_match = _ISO_DATE_RE.search(content)
    if iso_match:
        return (0, iso_match.group(1), index)
    created_at = row.get("created_at") or row.get("valid_from")
    if isinstance(created_at, datetime):
        return (0, created_at.isoformat(), index)
    if isinstance(created_at, str) and created_at:
        return (0, created_at, index)
    year_match = _YEAR_RE.search(content)
    if year_match:
        return (1, year_match.group(1), index)
    turn_index = row.get("turn_index")
    if isinstance(turn_index, int) and not isinstance(turn_index, bool):
        return (2, f"{turn_index:09d}", index)
    return (3, f"{index:09d}", index)


def adaptive_synthesize(
    question: str,
    evidence_rows: Sequence[Mapping[str, Any] | AnswerEvidence],
    disposition: ReflectDisposition | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce provenance-verified multi-evidence derivations adapted to question intent."""
    disp = coerce_disposition(disposition)
    intent = detect_synthesis_intent(question)
    mission_terms = _query_substantive_terms(disp.mission) if disp and disp.mission else set()

    normalized_rows: list[dict[str, Any]] = []
    for idx, item in enumerate(evidence_rows):
        if isinstance(item, AnswerEvidence):
            row_dict: dict[str, Any] = {
                "cid": item.cid,
                "content": item.content,
                "source_identity": item.source_identity,
                "session_id": item.session_id,
                "turn_index": item.turn_index,
                "hop": item.hop,
            }
        elif isinstance(item, Mapping):
            row_dict = dict(item)
        else:
            row_dict = {
                "cid": getattr(item, "cid", ""),
                "content": getattr(item, "content", ""),
                "created_at": getattr(item, "created_at", None),
                "turn_index": getattr(item, "turn_index", None),
                "trust_tier": getattr(item, "trust_tier", None),
            }
        cid = str(row_dict.get("cid") or "").strip()
        content = str(row_dict.get("content") or "")
        if not cid or not content.strip() or _contains_control_label(content):
            continue
        if disp is not None and disp.skepticism > 0.8:
            trust_tier = row_dict.get("trust_tier")
            if isinstance(trust_tier, int) and trust_tier >= 4:
                continue
        quote = content.strip()
        start = content.find(quote)
        end = start + len(quote)
        slice_sha256 = hashlib.sha256(quote.encode("utf-8")).hexdigest()
        span_dict = {
            "cid": cid,
            "start": start,
            "end": end,
            "slice_sha256": slice_sha256,
            "quote": quote,
        }
        mission_overlap = len(_query_substantive_terms(content) & mission_terms) if mission_terms else 0
        normalized_rows.append(
            {
                **row_dict,
                "cid": cid,
                "content": content,
                "quote": quote,
                "span": span_dict,
                "_index": idx,
                "_mission_overlap": mission_overlap,
            }
        )

    if mission_terms and any(r["_mission_overlap"] > 0 for r in normalized_rows):
        normalized_rows = [r for r in normalized_rows if r["_mission_overlap"] > 0]

    timeline_events: list[dict[str, Any]] = []
    state_transitions: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    count_value: int | None = None

    ordered_for_time = sorted(
        normalized_rows,
        key=lambda r: _extract_temporal_sort_key(r["content"], r, r["_index"]),
    )
    for r in ordered_for_time:
        sort_key = _extract_temporal_sort_key(r["content"], r, r["_index"])
        timestamp_label = sort_key[1] if sort_key[0] in (0, 1) else None
        timeline_events.append(
            {
                "cid": r["cid"],
                "timestamp": timestamp_label,
                "turn_index": r.get("turn_index"),
                "summary": r["quote"],
                "span": r["span"],
            }
        )

    # Extract state transitions across consecutive temporal events and inline transition phrases
    for r in ordered_for_time:
        inline_match = _TRANSITION_INLINE_RE.search(r["quote"])
        if inline_match:
            from_state = inline_match.group(1).strip()
            to_state = inline_match.group(2).strip()
            state_transitions.append(
                {
                    "from_state": from_state,
                    "to_state": to_state,
                    "from_cid": r["cid"],
                    "to_cid": r["cid"],
                    "evidence_cids": [r["cid"]],
                    "spans": [r["span"]],
                }
            )
    if len(ordered_for_time) >= 2:
        for prev_row, curr_row in zip(ordered_for_time[:-1], ordered_for_time[1:]):
            if prev_row["quote"] != curr_row["quote"]:
                state_transitions.append(
                    {
                        "from_state": prev_row["quote"],
                        "to_state": curr_row["quote"],
                        "from_cid": prev_row["cid"],
                        "to_cid": curr_row["cid"],
                        "evidence_cids": list(dict.fromkeys([prev_row["cid"], curr_row["cid"]])),
                        "spans": [prev_row["span"], curr_row["span"]],
                    }
                )

    is_literal = bool(disp is not None and disp.literalism > 0.7)

    if intent == "count":
        count_value = len(normalized_rows)
        if normalized_rows:
            spans = [r["span"] for r in normalized_rows[:16]]
            cids = list(dict.fromkeys(r["cid"] for r in normalized_rows[:16]))
            text = (
                " ".join(r["quote"] for r in normalized_rows[:3])
                if is_literal
                else f"Count: {count_value} ({'; '.join(r['quote'] for r in normalized_rows[:5])})"
            )
            claims.append(
                {
                    "text": text,
                    "evidence_cids": cids,
                    "spans": spans,
                    "derivation": {
                        "schema_version": "mnemosyne.claim-derivation/v1",
                        "kind": "quotation" if is_literal else "synthesis",
                        "operation": None if is_literal else "count",
                    },
                }
            )
    elif intent == "timeline":
        for ev in timeline_events:
            prefix = f"[{ev['timestamp']}] " if ev["timestamp"] and not is_literal else ""
            claims.append(
                {
                    "text": f"{prefix}{ev['summary']}",
                    "evidence_cids": [ev["cid"]],
                    "spans": [ev["span"]],
                    "derivation": {
                        "schema_version": "mnemosyne.claim-derivation/v1",
                        "kind": "quotation" if is_literal else "synthesis",
                        "operation": None if is_literal else "timeline",
                    },
                }
            )
    elif intent == "state_diff":
        if state_transitions:
            for tr in state_transitions:
                text = (
                    " -> ".join(s["quote"] for s in tr["spans"])
                    if is_literal
                    else f"Transition from {tr['from_state']} to {tr['to_state']}"
                )
                claims.append(
                    {
                        "text": text,
                        "evidence_cids": tr["evidence_cids"],
                        "spans": tr["spans"],
                        "derivation": {
                            "schema_version": "mnemosyne.claim-derivation/v1",
                            "kind": "quotation" if is_literal else "synthesis",
                            "operation": None if is_literal else "state_diff",
                        },
                    }
                )
        else:
            for r in ordered_for_time:
                claims.append(
                    {
                        "text": r["quote"],
                        "evidence_cids": [r["cid"]],
                        "spans": [r["span"]],
                        "derivation": {
                            "schema_version": "mnemosyne.claim-derivation/v1",
                            "kind": "quotation",
                            "operation": None,
                        },
                    }
                )
    elif intent == "comparison":
        for r in normalized_rows:
            comparisons.append({"cid": r["cid"], "point": r["quote"], "span": r["span"]})
        if len(normalized_rows) >= 2 and not is_literal:
            spans = [r["span"] for r in normalized_rows[:16]]
            cids = list(dict.fromkeys(r["cid"] for r in normalized_rows[:16]))
            claims.append(
                {
                    "text": " vs. ".join(r["quote"] for r in normalized_rows[:4]),
                    "evidence_cids": cids,
                    "spans": spans,
                    "derivation": {
                        "schema_version": "mnemosyne.claim-derivation/v1",
                        "kind": "synthesis",
                        "operation": "comparison",
                    },
                }
            )
        else:
            for r in normalized_rows:
                claims.append(
                    {
                        "text": r["quote"],
                        "evidence_cids": [r["cid"]],
                        "spans": [r["span"]],
                        "derivation": {
                            "schema_version": "mnemosyne.claim-derivation/v1",
                            "kind": "quotation",
                            "operation": None,
                        },
                    }
                )
    else:
        for r in normalized_rows:
            claims.append(
                {
                    "text": r["quote"],
                    "evidence_cids": [r["cid"]],
                    "spans": [r["span"]],
                    "derivation": {
                        "schema_version": "mnemosyne.claim-derivation/v1",
                        "kind": "quotation",
                        "operation": None,
                    },
                }
            )

    if disp is not None and claims:
        claims = claims[: disp.max_claims(len(claims))]

    cited_cids = list(
        dict.fromkeys(cid for claim in claims for cid in claim["evidence_cids"])
    )

    return {
        "intent": intent,
        "answer": "\n".join(c["text"] for c in claims),
        "abstained": not bool(claims),
        "claims": claims,
        "timeline_events": timeline_events,
        "state_transitions": state_transitions,
        "comparisons": comparisons,
        "count": count_value if intent == "count" else len(normalized_rows),
        "cited_cids": cited_cids,
        "disposition": disp.to_dict() if disp is not None else None,
    }
