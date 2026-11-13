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
    r"\b(?:role|position|job|title|promotion|promoted\s+to|working\s+as|lead\s+as)\s+(?:as\s+)?(?P<title>[A-Za-z][A-Za-z\s]{2,40}?)"
    r"(?:\?|,|\.|\s+how|\s+when|\s+where|\s+what|\s+in\s+my|\s+at|$)",
    re.IGNORECASE,
)


def _clean_str(val: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", val).split()).strip()


class PremiseConsistencyVerifier:
    """Verifies query presuppositions against episodic memory and trajectories."""

    def verify(
        self,
        query: str,
        facts: Sequence[Assertion | DistilledFact] | EpisodicUserDigest | None = None,
        evidence_rows: Sequence[Mapping[str, Any] | Any] | None = None,
        trajectories: Sequence[EntityAttributeTrajectory] | None = None,
    ) -> PremiseVerificationResult:
        """Deconstruct and verify query premises, returning structured mismatches and clean abstention."""
        mismatches: list[PremiseMismatch] = []

        # 1. Gather all fact records and evidence text
        distilled_facts, raw_trajectories, all_evidence_texts = self._normalize_inputs(
            facts=facts,
            evidence_rows=evidence_rows,
            trajectories=trajectories,
        )

        # 2. Check Role / Title presuppositions
        role_mismatch = self._check_role_title(
            query, distilled_facts, raw_trajectories, all_evidence_texts
        )
        if role_mismatch is not None:
            mismatches.append(role_mismatch)

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
    ) -> PremiseMismatch | None:
        """Check if query presupposes a role/title that contradicts episodic records."""
        m = _ROLE_TITLE_RE.search(query)
        if not m:
            return None

        presupposed_title = _clean_str(m.group("title"))
        presupposed_norm = presupposed_title.lower()

        # Find authoritative user roles in trajectories or facts
        actual_title: str | None = None
        for traj in trajectories:
            if traj.attribute.lower() in {"title", "role", "position", "career"}:
                curr = traj.current
                if curr and curr.value:
                    actual_title = str(curr.value)
                    break

        if not actual_title:
            for f in facts:
                if (
                    f.predicate.lower()
                    in {"career_title", "job_title", "role", "position", "promoted_to"}
                    and f.is_current
                ):
                    actual_title = str(f.value)
                    break

        # Check evidence text for actual title if not yet found
        if not actual_title:
            title_pattern = re.compile(
                r"\b(?:promoted\s+to|role\s+as|title\s+as|position\s+as|working\s+as)\s+(?:a\s+|an\s+|the\s+)?([A-Z][a-zA-Z\s]{2,30}?)(?:[.,;!\n]|\s+at|\s+in|\s+for|$)",
                re.IGNORECASE,
            )
            for text in evidence_texts:
                tm = title_pattern.search(text)
                if tm:
                    actual_title = _clean_str(tm.group(1))
                    break

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
