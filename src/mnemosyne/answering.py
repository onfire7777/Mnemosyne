"""Bounded, read-only orchestration for provenance-grounded answers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, Protocol, Sequence

from mnemosyne.engine import MemoryEngine


_PUBLIC_ABSTENTION = "insufficient_authorized_evidence"


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


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    answer: str
    claims: tuple[AnswerClaim, ...]
    evidence: tuple[AnswerEvidence, ...]
    episodes: tuple[AnswerEpisode, ...]
    trace: AnswerTrace
    abstained: bool
    public_reason: str | None = None


class QueryDecomposer(Protocol):
    def decompose(self, payload: dict[str, object]) -> object: ...


class GroundedReader(Protocol):
    def read(self, payload: dict[str, object]) -> object: ...


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
        except Exception:
            # Providers and storage are untrusted at this boundary. Any ordinary
            # failure collapses to the same public abstention; process-control
            # BaseExceptions still propagate.
            return self._abstain()

    def answer(self, request: AnswerRequest, reader: GroundedReader) -> GroundedAnswer:
        """Validate model-proposed atomic claims against freshly replayed evidence."""
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
            return self._abstain()
        replayed = self.assemble(request)
        if replayed.abstained or (
            replayed.trace.evidence_fingerprint
            != assembled.trace.evidence_fingerprint
            or replayed.evidence != assembled.evidence
            or replayed.trace.hops != assembled.trace.hops
        ):
            return self._abstain()
        try:
            claims = self._claims(proposal, {row.cid for row in replayed.evidence})
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
            return self._reader_abstain(replayed)

    @staticmethod
    def _reader_abstain(assembled: GroundedAnswer) -> GroundedAnswer:
        """Preserve authorized retrieval custody when only the reader abstains."""
        return GroundedAnswer(
            answer="", claims=(), evidence=assembled.evidence,
            episodes=assembled.episodes, trace=assembled.trace, abstained=True,
        )

    def _assemble(self, request: AnswerRequest) -> GroundedAnswer:
        if len(request.question) > self.limits.max_query_characters:
            raise ValueError("question budget exceeded")
        queries = self._queries(
            self.decomposer.decompose({"question": request.question, "evidence": []})
        )
        seen_queries: set[str] = set()
        authorized: dict[str, dict[str, Any]] = {}
        hop_maps: list[dict[str, dict[str, Any]]] = []
        cid_hop: dict[str, int] = {}
        hops: list[AnswerHop] = []
        for hop_index in range(self.limits.max_hops):
            fresh_queries = tuple(query for query in queries if query.casefold() not in seen_queries)
            if not fresh_queries:
                break
            if len(fresh_queries) > self.limits.max_queries_per_hop:
                raise ValueError("query budget exceeded")
            seen_queries.update(query.casefold() for query in fresh_queries)
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
            if sum(len(str(row.get("content") or "")) for row in authorized.values()) > self.limits.max_characters:
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
            queries = self._queries(self.decomposer.decompose(payload))
            if not queries:
                break
        if not authorized:
            raise LookupError("no authorized evidence")
        fingerprint = _fingerprint(authorized)
        replayed: dict[str, dict[str, Any]] = {}
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
                raise LookupError("authorized evidence changed")
            replayed.update(replayed_hop_map)
        if set(replayed) != set(authorized) or _fingerprint(replayed) != fingerprint:
            raise LookupError("authorized evidence changed")
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
            raise LookupError("retrieval abstained")
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

    def _queries(self, value: object) -> tuple[str, ...]:
        if not isinstance(value, dict) or set(value) != {"queries"}:
            raise ValueError("invalid decomposer schema")
        raw = value["queries"]
        if not isinstance(raw, list) or len(raw) > self.limits.max_queries_per_hop:
            raise ValueError("invalid decomposer queries")
        queries: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str) or not item.strip() or len(item) > self.limits.max_query_characters:
                raise ValueError("invalid decomposer query")
            query = item.strip()
            if query.casefold() not in seen:
                queries.append(query)
                seen.add(query.casefold())
        return tuple(sorted(queries, key=lambda item: (item.casefold(), item)))

    @staticmethod
    def _claims(value: object, authorized_cids: set[str]) -> tuple[AnswerClaim, ...]:
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
            if not isinstance(row, dict) or set(row) != {"text", "evidence_cids"}:
                raise ValueError("invalid claim schema")
            text = row["text"]
            citations = row["evidence_cids"]
            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text) > 2_000
                or not isinstance(citations, list)
                or not citations
                or any(not isinstance(cid, str) or not cid for cid in citations)
                or len(set(citations)) != len(citations)
                or not set(citations) <= authorized_cids
            ):
                raise ValueError("claim is not grounded in authorized evidence")
            claims.append(AnswerClaim(text.strip(), tuple(citations)))
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
            content=str(row.get("content") or ""),
            source_identity=str(source_identity) if source_identity else None,
            session_id=str(session_id) if session_id else None,
            turn_index=turn_index if isinstance(turn_index, int) and not isinstance(turn_index, bool) else None,
            hop=hop,
        )

    @staticmethod
    def _abstain() -> GroundedAnswer:
        return GroundedAnswer(
            answer="",
            claims=(),
            evidence=(),
            episodes=(),
            trace=AnswerTrace((), ""),
            abstained=True,
            public_reason=_PUBLIC_ABSTENTION,
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
