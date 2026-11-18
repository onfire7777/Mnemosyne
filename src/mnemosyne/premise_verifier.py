"""Dynamic premise-consistency and counterfactual verifier for conversational memory.

Deconstructs query presuppositions (currently roles/titles) and verifies them
against episodic facts, entity state trajectories, and authorized evidence.

When a premise contradicts episodic reality or is entirely ungrounded,
it surfaces an unanswerability signal and formats a calibrated clean
abstention without confabulation or hedging.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from mnemosyne.episodic_facts import (
    DistilledFact,
    EntityAttributeTrajectory,
    EpisodicUserDigest,
)
from mnemosyne.models import Assertion

MismatchType = Literal[
    "missing_entity",
    "entity_conflict",
    "role_title_conflict",
    "location_conflict",
    "temporal_event_conflict",
    "counterfactual_comparison",
]


@dataclass(frozen=True, slots=True)
class PremiseMismatch:
    """A detected contradiction or ungrounded presupposition in a user query."""

    mismatch_type: MismatchType
    query_premise: str
    factual_grounding: str | None
    confidence: float
    candidate_unanswerability_signal: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PremiseVerificationResult:
    """The outcome of verifying query presuppositions against episodic memory."""

    is_consistent: bool
    abstention_recommended: bool
    mismatches: tuple[PremiseMismatch, ...]
    clean_abstention_text: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Regular expressions for presupposition deconstruction
_ROLE_TITLE_RE = re.compile(
    r"\b(?:role|position|job|title|promotion|promoted\s+to|working\s+as|hired\s+as|serving\s+as|lead\s+as)"
    r"\s+(?:as\s+)?(?:a\s+|an\s+|the\s+)?"
    r"(?P<title>[A-Za-z][A-Za-z0-9/&-]{1,25}(?:\s+[A-Za-z][A-Za-z0-9/&-]{1,25}){0,4}?)"
    r"(?:\?|,|\.|;|\s+(?:how|when|where|what|who|which|in\s+my|at|for|since|after|before|recently|last|this|and|but)\b|$)",
    re.IGNORECASE,
)
_QUOTED_PREMISE_RE = re.compile(
    r"""(?:\b(?:named|called|titled|entitled|book|movie|show|course|project|podcast|album|song|game|paper|article)\s+)?["“](?P<quoted>[A-Z0-9][^"”]{3,60})["”]"""
)


def _clean_str(val: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", val).split()).strip()


def _utc(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _user_role_texts(rows: Sequence[Mapping[str, Any] | Any]) -> list[str]:
    """Keep speaker and subject attribution when reading legacy text evidence."""
    texts: list[str] = []
    for row in rows:
        get = row.get if isinstance(row, Mapping) else lambda key, default=None: getattr(row, key, default)
        subject = str(get("subject") or "user").lower()
        if subject not in {"user", "self", "i"}:
            continue
        # Canonical evidence actor wins over client-supplied role aliases or
        # quoted transcript labels. AnswerEvidence preserves this field.
        speaker = str(get("actor") or get("speaker_role") or get("role") or get("speaker") or "").lower()
        if speaker and speaker != "user":
            continue
        content = str(get("content") or "")
        parts = re.split(r"(?im)^\s*(user|assistant|system|tool)\s*:\s*", content)
        if len(parts) > 1:
            texts.extend(parts[i + 1] for i in range(1, len(parts), 2) if parts[i].lower() == "user")
        elif speaker == "user":
            texts.append(content)
    return texts


class PremiseConsistencyVerifier:
    """Verifies query presuppositions against episodic memory and trajectories."""

    def verify(
        self,
        query: str,
        facts: Sequence[Assertion | DistilledFact] | EpisodicUserDigest | None = None,
        evidence_rows: Sequence[Mapping[str, Any] | Any] | None = None,
        trajectories: Sequence[EntityAttributeTrajectory] | None = None,
        *,
        evaluated_at: datetime | None = None,
    ) -> PremiseVerificationResult:
        """Deconstruct and verify query premises, returning structured mismatches and clean abstention."""
        mismatches: list[PremiseMismatch] = []
        at = _utc(evaluated_at)
        if at is not None:
            eligible_rows = []
            for row in evidence_rows or []:
                stamp = row.get("created_at") if isinstance(row, Mapping) else getattr(row, "created_at", None)
                created_at = _utc(stamp)
                if stamp is not None and (created_at is None or created_at > at):
                    continue
                eligible_rows.append(row)
            evidence_rows = eligible_rows

        # 1. Gather all fact records and evidence text
        distilled_facts, raw_trajectories, all_evidence_texts = self._normalize_inputs(
            facts=facts,
            evidence_rows=evidence_rows,
            trajectories=trajectories,
        )

        # 2. Check Role / Title presuppositions
        role_mismatch = self._check_role_title(
            query, distilled_facts, raw_trajectories, _user_role_texts(evidence_rows or []), at
        )
        if role_mismatch is not None:
            mismatches.append(role_mismatch)

        # 3. Check explicit quoted proper-entity presuppositions when evidence is provided
        quoted_mismatch = self._check_quoted_entity(query, all_evidence_texts)
        if quoted_mismatch is not None:
            mismatches.append(quoted_mismatch)

        if not mismatches:
            return PremiseVerificationResult(
                is_consistent=True,
                abstention_recommended=False,
                mismatches=(),
                clean_abstention_text=None,
            )

        # Build clean direct abstention text from primary mismatch
        primary = mismatches[0]
        clean_text = primary.candidate_unanswerability_signal

        return PremiseVerificationResult(
            is_consistent=False,
            abstention_recommended=True,
            mismatches=tuple(mismatches),
            clean_abstention_text=clean_text,
        )

    def _normalize_inputs(
        self,
        facts: Sequence[Assertion | DistilledFact] | EpisodicUserDigest | None,
        evidence_rows: Sequence[Mapping[str, Any] | Any] | None,
        trajectories: Sequence[EntityAttributeTrajectory] | None,
    ) -> tuple[list[DistilledFact], list[EntityAttributeTrajectory], list[str]]:
        distilled_facts: list[DistilledFact] = []
        raw_trajectories: list[EntityAttributeTrajectory] = list(trajectories or [])
        all_evidence_texts: list[str] = []

        if isinstance(facts, EpisodicUserDigest):
            distilled_facts.extend(facts.facts)
            if not raw_trajectories and facts.trajectories:
                raw_trajectories.extend(facts.trajectories)
        elif facts is not None:
            for f in facts:
                if isinstance(f, DistilledFact):
                    distilled_facts.append(f)
                elif isinstance(f, Assertion):
                    # Convert Assertion to DistilledFact representation
                    qualifiers = getattr(f, "qualifiers", {}) or {}
                    speaker_role = (
                        str(qualifiers.get("speaker_role") or "user").strip().lower()
                    )
                    fact_id = getattr(f, "assertion_id", getattr(f, "id", ""))
                    val = getattr(f, "object_value", getattr(f, "object", None))
                    distilled_facts.append(
                        DistilledFact(
                            fact_id=str(fact_id),
                            speaker_role=speaker_role,
                            category=f.predicate,
                            subject=f.subject,
                            predicate=f.predicate,
                            value=val,
                            valid_from=f.valid_from,
                            valid_to=f.valid_to,
                            is_current=bool(f.valid_to is None),
                        )
                    )

        if evidence_rows:
            for row in evidence_rows:
                if isinstance(row, Mapping):
                    content = str(row.get("content") or "").strip()
                else:
                    content = str(getattr(row, "content", "") or "").strip()
                if content:
                    all_evidence_texts.append(content)

        return distilled_facts, raw_trajectories, all_evidence_texts

    def _check_role_title(
        self,
        query: str,
        facts: list[DistilledFact],
        trajectories: list[EntityAttributeTrajectory],
        evidence_texts: list[str],
        evaluated_at: datetime | None,
    ) -> PremiseMismatch | None:
        """Check if query presupposes a role/title that contradicts episodic records."""
        m = _ROLE_TITLE_RE.search(query)
        if not m:
            return None
        # "promoted to X" / "hired as X" presuppose a recorded event, which the
        # user's own event reports can refute even in past tense.
        event_premise = re.match(r"promot|hired", m.group(0), re.IGNORECASE) is not None
        past_tense = re.search(
            r"\b(?:did\s+I|was\s+I|when\s+I\s+was|former|previous|used\s+to)\b"
            r"|\b(?:what|which|who|where|when|why|how)\b[^.!?;]*?\b(?:did|was|were|had)\b",
            query,
            re.IGNORECASE,
        ) is not None
        if past_tense and not event_premise:
            # Past-tense questions need not put I after the auxiliary ("what
            # were my duties", "which tasks were assigned to me", etc.). A
            # query-time title cannot refute an unspecified historical role.
            return None

        presupposed_title = _clean_str(m.group("title"))
        presupposed_norm = presupposed_title.lower()

        # Collect eligible user titles, not the first role returned by retrieval.
        titles: set[str] = set()
        for traj in trajectories:
            if traj.entity.lower() in {"user", "self", "i"} and traj.attribute.lower() in {"title", "role", "position", "career"}:
                if past_tense:  # a past event may match any recorded title, not only the current one
                    titles.update(_clean_str(str(s.value)) for s in traj.steps if s.value)
                    continue
                curr = traj.as_of(evaluated_at) if evaluated_at else traj.current
                if curr and curr.value:
                    titles.add(_clean_str(str(curr.value)))

        for f in facts:
            if f.speaker_role.lower() != "user" or f.subject.lower() not in {"user", "self", "i"}:
                continue
            start, end = _utc(f.valid_from), _utc(f.valid_to)
            active = f.is_current if evaluated_at is None else (
                (start is None or start <= evaluated_at) and (end is None or evaluated_at < end)
            )
            if f.predicate.lower() in {"career_title", "job_title", "role", "position", "promoted_to"} and (active or past_tense) and f.value:
                titles.add(_clean_str(str(f.value)))

        # Raw self-reports can corroborate structured facts or expose ambiguity.
        if evidence_texts:
            title_pattern = re.compile(
                r"\b(?:[Pp]romoted\s+to|[Ss]tarted\s+(?:a\s+|my\s+)?(?:new\s+)?(?:role|position|job)\s+as|[Rr]ole\s+as|[Tt]itle\s+as|[Pp]osition\s+as|[Ww]orking\s+as|[Hh]ired\s+as|[Ss]erving\s+as)"
                r"\s+(?:a\s+|an\s+|the\s+)?"
                r"([A-Z][a-zA-Z0-9/&-]+(?:\s+(?:of|and|for|[A-Z][a-zA-Z0-9/&-]+)){0,5})"
                r"(?:[.,;!\n?]|\s+(?:at|in|for|since|recently|last|this|and|but|where|when)\b|$)"
            )
            for text in evidence_texts:
                for sentence in re.split(r"[.!?;\n]+", text):
                    for tm in title_pattern.finditer(sentence):
                        prefix = sentence[:tm.start()].strip()
                        # Only an affirmative self-report can refute a user premise.
                        # Third-party, hypothetical, negated, and former roles are
                        # not a current exclusive user title.
                        if not re.fullmatch(
                            r"(?:I(?:\s+(?:am|was|have|been|just|recently|currently|now|also))*|my)?",
                            prefix, re.IGNORECASE,
                        ):
                            continue
                        if re.search(r"\b(?:not|never|no longer|used to|formerly|if|would|might)\b", sentence, re.IGNORECASE):
                            continue
                        titles.add(_clean_str(tm.group(1)))
        # Multiple roles can describe a promotion, history, or concurrent jobs.
        # Retrieval order alone cannot establish a contradiction.
        if any(presupposed_norm == title.lower() for title in titles):
            return None
        actual_title = next(iter(titles)) if len(titles) == 1 else None

        if actual_title:
            actual_norm = actual_title.lower()
            # If the presupposed title contradicts the recorded title (e.g. Manager vs Senior Tech Lead)
            if presupposed_norm != actual_norm and not (
                presupposed_norm in actual_norm or actual_norm in presupposed_norm
            ):
                # Ensure it's genuinely different (e.g. "Software Engineer Manager" vs "Senior Tech Lead")
                return PremiseMismatch(
                    mismatch_type="role_title_conflict",
                    query_premise=f"role as {presupposed_title}",
                    factual_grounding=f"role as {actual_title}",
                    confidence=0.95,
                    candidate_unanswerability_signal=(
                        f"The chat history does not indicate you hold a {presupposed_title} role; "
                        f"your records refer to your role as {actual_title}."
                    ),
                )

        return None

    def _check_quoted_entity(
        self,
        query: str,
        evidence_texts: list[str],
    ) -> PremiseMismatch | None:
        """Check whether an explicitly double-quoted proper title/name in the query is absent from evidence."""
        if not evidence_texts:
            return None
        combined_lower = "\n".join(evidence_texts).lower()
        for m in _QUOTED_PREMISE_RE.finditer(query):
            quoted = _clean_str(m.group("quoted"))
            words = [w for w in re.findall(r"[A-Za-z0-9]+", quoted.lower()) if len(w) >= 3]
            if len(words) < 2:
                continue
            if quoted.lower() in combined_lower:
                continue
            if sum(1 for w in words if w in combined_lower) == 0:
                return PremiseMismatch(
                    mismatch_type="missing_entity",
                    query_premise=f'"{quoted}"',
                    factual_grounding=None,
                    confidence=0.88,
                    candidate_unanswerability_signal=(
                        f'The chat history does not mention "{quoted}".'
                    ),
                )
        return None
