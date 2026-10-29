"""Dynamic premise-consistency and counterfactual verifier for conversational memory.

Deconstructs query presuppositions (target entities, roles/titles, locations,
and comparative timelines) and verifies them against episodic facts, entity
state trajectories, and authorized evidence.

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
_LODGING_LOCATION_RE = re.compile(
    r"\b(?P<activity>airbnb|hotel|vacation\s+rental|stay|trip|cabin|resort|booking)\s+(?:in|at|for)\s+(?P<location>[A-Z][a-zA-Z\s]{2,30}?)(?:\?|,|\.|\s+for|\s+in\s+\d|\s+during|$)",
    re.IGNORECASE,
)
_ACTION_IN_LOCATION_RE = re.compile(
    r"\b(?:what\s+did\s+i\s+(?:buy|purchase|order|eat|visit))\s+(?:in|at)\s+(?P<location>[A-Z][a-zA-Z\s]{2,30}?)(?:\?|,|\.|$)",
    re.IGNORECASE,
)
_PET_ENTITY_RE = re.compile(
    r"\b(?:my|our)\s+(?:pet\s+)?(?P<pet>hamster|cat|dog|ferret|iguana|parrot|chinchilla|rabbit|guinea\s+pig|lizard|goldfish|turtle)\b",
    re.IGNORECASE,
)
_COMPARATIVE_FIRST_RE = re.compile(
    r"\bwho\s+(?P<predicate>became\s+a\s+parent|had\s+a\s+baby|got\s+married|graduated|moved|bought\s+a\s+house|retired|started\s+a\s+company|joined|promoted)\s+"
    r"(?:first|earlier|before)\s*,?\s*(?P<entity_a>[A-Z][a-z]+)\s+or\s+(?P<entity_b>[A-Z][a-z]+)\b",
    re.IGNORECASE,
)
_COMPARATIVE_FIRST_INV_RE = re.compile(
    r"\bbetween\s+(?P<entity_a>[A-Z][a-z]+)\s+and\s+(?P<entity_b>[A-Z][a-z]+)\s*,?\s*who\s+"
    r"(?P<predicate>became\s+a\s+parent|had\s+a\s+baby|got\s+married|graduated|moved|bought\s+a\s+house|retired)\s+first\b",
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

        # 3. Check Location presuppositions (e.g. Airbnb in Sacramento vs San Diego)
        location_mismatch = self._check_location(
            query, distilled_facts, all_evidence_texts
        )
        if location_mismatch is not None:
            mismatches.append(location_mismatch)

        # 4. Check Missing Entity presuppositions (e.g. pet hamster when only dog Buster exists)
        pet_mismatch = self._check_missing_pet_or_entity(
            query, distilled_facts, all_evidence_texts
        )
        if pet_mismatch is not None:
            mismatches.append(pet_mismatch)

        # 5. Check Comparative Counterfactual presuppositions (e.g. Who became parent first, Tom or Alex?)
        comp_mismatch = self._check_comparative_timeline(
            query, distilled_facts, all_evidence_texts
        )
        if comp_mismatch is not None:
            mismatches.append(comp_mismatch)

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

    def _check_location(
        self,
        query: str,
        facts: list[DistilledFact],
        evidence_texts: list[str],
    ) -> PremiseMismatch | None:
        """Check for lodging or action location mismatches (e.g. Sacramento vs San Diego)."""
        # 1. Lodging / Airbnb pattern
        m_lodge = _LODGING_LOCATION_RE.search(query)
        if m_lodge:
            queried_loc = _clean_str(m_lodge.group("location"))
            queried_loc_norm = queried_loc.lower()
            activity = m_lodge.group("activity")

            # Search facts / evidence for actual lodging location
            actual_loc: str | None = None
            lodge_pattern = re.compile(
                r"\b(?:airbnb|hotel|vacation\s+rental|booked|stayed|cabin)\s+(?:in|at)\s+([A-Z][a-zA-Z\s]{2,30}?)(?:[.,;!\n]|\s+for|\s+in\s+\d|$)",
                re.IGNORECASE,
            )
            for text in evidence_texts:
                lm = lodge_pattern.search(text)
                if lm:
                    found_loc = _clean_str(lm.group(1))
                    if found_loc.lower() != queried_loc_norm:
                        actual_loc = found_loc
                        break

            if actual_loc and actual_loc.lower() != queried_loc_norm:
                return PremiseMismatch(
                    mismatch_type="location_conflict",
                    query_premise=f"{activity} in {queried_loc}",
                    factual_grounding=f"{activity} in {actual_loc}",
                    confidence=0.95,
                    candidate_unanswerability_signal=(
                        f"The records do not show an {activity} booking in {queried_loc}. "
                        f"You previously discussed booking an {activity} in {actual_loc}."
                    ),
                )

        # 2. General action in location pattern (e.g. "What did I buy in Sacramento?")
        m_act = _ACTION_IN_LOCATION_RE.search(query)
        if m_act:
            queried_loc = _clean_str(m_act.group("location"))
            loc_norm = queried_loc.lower()
            # Check if location is mentioned at all in evidence
            has_mention = any(loc_norm in text.lower() for text in evidence_texts)
            if not has_mention:
                return PremiseMismatch(
                    mismatch_type="location_conflict",
                    query_premise=f"activity in {queried_loc}",
                    factual_grounding=None,
                    confidence=0.95,
                    candidate_unanswerability_signal=(
                        f"The records do not contain any purchases or activities in {queried_loc}."
                    ),
                )

        return None

    def _check_missing_pet_or_entity(
        self,
        query: str,
        facts: list[DistilledFact],
        evidence_texts: list[str],
    ) -> PremiseMismatch | None:
        """Check if query presupposes a pet or entity that was never mentioned."""
        m = _PET_ENTITY_RE.search(query)
        if not m:
            return None

        queried_pet = m.group("pet").lower()

        # Check if this pet is mentioned anywhere in user facts or evidence
        mentioned_in_facts = any(
            queried_pet in str(f.value).lower() or queried_pet in f.predicate.lower()
            for f in facts
        )
        mentioned_in_text = any(
            re.search(rf"\b{re.escape(queried_pet)}s?\b", text, re.IGNORECASE)
            for text in evidence_texts
        )

        if not mentioned_in_facts and not mentioned_in_text:
            # Check if user has other pets recorded (e.g. dog Buster)
            other_pets: list[str] = []
            for f in facts:
                if f.category in {"family_pet", "pet"}:
                    other_pets.append(f"{f.predicate}: {f.value}")
            factual_context = (
                f"Recorded pets: {', '.join(other_pets)}" if other_pets else None
            )

            return PremiseMismatch(
                mismatch_type="missing_entity",
                query_premise=f"pet {queried_pet}",
                factual_grounding=factual_context,
                confidence=0.95,
                candidate_unanswerability_signal=(
                    f"The chat history does not contain any mention of a pet {queried_pet} or a {queried_pet}'s name."
                ),
            )

        return None

    def _check_comparative_timeline(
        self,
        query: str,
        facts: list[DistilledFact],
        evidence_texts: list[str],
    ) -> PremiseMismatch | None:
        """Check comparative counterfactual questions (e.g. Who did X first, A or B?)."""
        m = _COMPARATIVE_FIRST_RE.search(query) or _COMPARATIVE_FIRST_INV_RE.search(
            query
        )
        if not m:
            return None

        ent_a = _clean_str(m.group("entity_a"))
        ent_b = _clean_str(m.group("entity_b"))
        predicate = _clean_str(m.group("predicate"))

        # Look for evidence that either A or B participated in predicate
        a_events: list[str] = []
        b_events: list[str] = []

        # Key terms from predicate
        pred_terms = [t for t in predicate.lower().split() if len(t) > 3]
        if not pred_terms:
            pred_terms = [t for t in predicate.lower().split() if len(t) >= 2]

        for text in evidence_texts:
            sentences = re.split(r"[.!;?\n]+", text)
            for sent in sentences:
                s_low = sent.lower()
                if ent_a.lower() in s_low and any(term in s_low for term in pred_terms):
                    a_events.append(sent.strip())
                if ent_b.lower() in s_low and any(term in s_low for term in pred_terms):
                    b_events.append(sent.strip())

        # If neither entity has recorded evidence of the predicate event
        if not a_events and not b_events:
            return PremiseMismatch(
                mismatch_type="counterfactual_comparison",
                query_premise=f"Comparison of who {predicate} first, {ent_a} or {ent_b}",
                factual_grounding=None,
                confidence=0.95,
                candidate_unanswerability_signal=(
                    f"Neither {ent_a} nor {ent_b} is recorded as having {predicate} in the provided history."
                ),
            )

        # If only one entity has recorded evidence
        if a_events and not b_events:
            return PremiseMismatch(
                mismatch_type="counterfactual_comparison",
                query_premise=f"Comparison of who {predicate} first, {ent_a} or {ent_b}",
                factual_grounding=f"{ent_a} has record of {predicate}; {ent_b} does not",
                confidence=0.90,
                candidate_unanswerability_signal=(
                    f"{ent_a} is recorded as having {predicate}, but there is no record of {ent_b} having done so."
                ),
            )

        if b_events and not a_events:
            return PremiseMismatch(
                mismatch_type="counterfactual_comparison",
                query_premise=f"Comparison of who {predicate} first, {ent_a} or {ent_b}",
                factual_grounding=f"{ent_b} has record of {predicate}; {ent_a} does not",
                confidence=0.90,
                candidate_unanswerability_signal=(
                    f"{ent_b} is recorded as having {predicate}, but there is no record of {ent_a} having done so."
                ),
            )

        return None
