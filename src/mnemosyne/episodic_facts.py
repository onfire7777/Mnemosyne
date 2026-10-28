"""Deterministic offline episodic-to-semantic fact and milestone indexing.

Extracts structured Assertions and Relations from conversational dialogue and
episodic narrative across 4 primary fact families:
1. Residence & Location (living, moving, residing, apartment/home purchases)
2. Family & Pets (children, spouse, parents, siblings, pets and breeds)
3. Expenses & Counts (expenditures, purchases, item counts)
4. Dated Milestones (graduations, education, career, life milestones)

All extracted facts preserve:
- source_evidence_cids: evidence IDs for cryptographic provenance and trust derivation.
- valid_from: explicit event timestamp or evidence creation time.
- trust_tier: inherited from source evidence or caller context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Sequence

from mnemosyne.models import Assertion, Relation, utc_now
from mnemosyne.security import TrustTier

MONTH_MAP: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

WORD_TO_NUM: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


@dataclass(slots=True)
class ExtractedFacts:
    """Container for assertions and relations extracted from episodic text."""

    assertions: list[Assertion] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)

    def __iter__(self):
        yield self.assertions
        yield self.relations

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int) -> list[Any]:
        if index == 0:
            return self.assertions
        elif index == 1:
            return self.relations
        raise IndexError("ExtractedFacts index out of range (0=assertions, 1=relations)")

    @property
    def all_items(self) -> list[Assertion | Relation]:
        return list(self.assertions) + list(self.relations)


def parse_explicit_date(date_str: str | None) -> datetime | None:
    """Parse an explicit date, month+year, or 4-digit year into a UTC datetime."""
    if not date_str:
        return None
    cleaned = date_str.strip().strip(",.;")
    if not cleaned:
        return None

    # 1. Full date: Month Day, Year (e.g. "May 4, 2018", "June 15 2020", "October 12, 2015")
    m_full = re.search(
        r"(?i)\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(19\d\d|20\d\d)\b",
        cleaned,
    )
    if m_full:
        month_name = m_full.group(1).lower()
        day = int(m_full.group(2))
        year = int(m_full.group(3))
        month = MONTH_MAP.get(month_name, 1)
        try:
            return datetime(year, month, day, 0, 0, 0, tzinfo=UTC)
        except ValueError:
            pass

    # 2. ISO date: YYYY-MM-DD
    m_iso = re.search(r"\b(19\d\d|20\d\d)-(\d{2})-(\d{2})\b", cleaned)
    if m_iso:
        try:
            return datetime(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)), 0, 0, 0, tzinfo=UTC)
        except ValueError:
            pass

    # 3. Month and Year: (e.g. "May 2018", "August 2023")
    m_my = re.search(
        r"(?i)\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(19\d\d|20\d\d)\b",
        cleaned,
    )
    if m_my:
        month_name = m_my.group(1).lower()
        year = int(m_my.group(2))
        month = MONTH_MAP.get(month_name, 1)
        return datetime(year, month, 1, 0, 0, 0, tzinfo=UTC)

    # 4. 4-digit Year: (e.g. "2021", "2024")
    m_yr = re.search(r"\b(19\d\d|20\d\d)\b", cleaned)
    if m_yr:
        year = int(m_yr.group(1))
        return datetime(year, 1, 1, 0, 0, 0, tzinfo=UTC)

    return None


def _clean_location(loc: str) -> str:
    cleaned = loc.strip().strip(",.;!? ")
    # Strip trailing "in 2024" or "now" or "today" or "recently"
    cleaned = re.sub(r"(?i)\s+(?:in\s+\d{4}|now|today|recently|currently|with\s+.*|and\s+.*)$", "", cleaned)
    return cleaned.strip()


def extract_episodic_facts(
    text: str,
    *,
    tenant_id: str = "default",
    user_id: str | None = None,
    branch: str = "main",
    evidence_ids: Sequence[str] | None = None,
    source_evidence_cids: Sequence[str] | None = None,
    evidence_cids: Sequence[str] | None = None,
    trust_tier: int = int(TrustTier.DIRECT_USER),
    access_policy: dict[str, Any] | None = None,
    created_at: datetime | None = None,
    valid_from: datetime | None = None,
    evaluated_at: datetime | None = None,
) -> ExtractedFacts:
    """Extract deterministic assertions and relations across the 4 fact families.

    Fact Families:
    1. Residence: "I moved to San Diego", "I live in Sacramento", "My apartment is in Shibuya"
       -> Assertion(subject="user", predicate="residence", object=loc) & Relation(source="user", predicate="lives_in", target=loc)
    2. Family/Pets: "My daughter Emily", "My dog Buster is a Golden Retriever"
       -> Assertion(subject="user", predicate="has_family"/"has_pet", object=name) & Relation(...)
    3. Expenses/Counts: "I spent $450 on bike repairs", "Total money spent on bike repairs was $450"
       -> Assertion(subject="user", predicate="expense", object="$450 on bike repairs") & Relation(...)
    4. Milestones: "In 2021, I graduated from Stanford", "In 2019, I started working at Google"
       -> Assertion(subject="user", predicate="education"/"milestone", object=institution, valid_from=...) & Relation(...)
    """
    cids = list(source_evidence_cids or evidence_ids or evidence_cids or [])
    base_valid_from = valid_from or evaluated_at or created_at or utc_now()
    policy = dict(access_policy or {})

    assertions: list[Assertion] = []
    relations: list[Relation] = []

    seen_assertions: set[tuple[str, str, str]] = set()
    seen_relations: set[tuple[str, str, str]] = set()

    def add_assertion(
        subject: str,
        predicate: str,
        obj: str,
        *,
        vf: datetime | None = None,
        scope: dict[str, Any] | None = None,
        confidence: float = 0.9,
    ) -> None:
        key = (subject, predicate, obj)
        if key in seen_assertions:
            return
        seen_assertions.add(key)
        a = Assertion(
            tenant_id=tenant_id,
            user_id=user_id,
            branch=branch,
            subject=subject,
            predicate=predicate,
            object=obj,
            scope=scope or {},
            confidence=confidence,
            valid_from=vf or base_valid_from,
            source_evidence_cids=cids,
            trust_tier=trust_tier,
            access_policy=policy,
            status="active",
        )
        assertions.append(a)

    def add_relation(
        source: str,
        predicate: str,
        target: str,
        *,
        vf: datetime | None = None,
        confidence: float = 0.9,
    ) -> None:
        key = (source, predicate, target)
        if key in seen_relations:
            return
        seen_relations.add(key)
        r = Relation(
            tenant_id=tenant_id,
            source=source,
            predicate=predicate,
            target=target,
            branch=branch,
            confidence=confidence,
            valid_from=vf or base_valid_from,
            source_evidence_cids=cids,
            access_policy=policy,
        )
        relations.append(r)

    # Split text into sentence/clause candidates while preserving context
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    if not sentences:
        sentences = [text.strip()]

    for sentence in sentences:
        # Check explicit date in this sentence
        sentence_date = parse_explicit_date(sentence)

        # ----------------------------------------------------------------------
        # 1. Residence & Location
        # ----------------------------------------------------------------------
        # Moves: "I moved to San Diego in 2024", "In 2024, I moved to San Diego", "I moved from Sacramento to San Diego"
        m_move = re.search(
            r"(?i)(?:(?:in|on)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+moved\s+(?:from\s+[A-Za-z0-9\s'.-]+?\s+to\s+|to\s+)([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|on)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s+with|\s+and|\s*$)",
            sentence,
        )
        if m_move:
            loc = _clean_location(m_move.group(2))
            dt = parse_explicit_date(m_move.group(1)) or parse_explicit_date(m_move.group(3)) or sentence_date
            if loc and len(loc) > 1 and not loc.lower().startswith(("a ", "an ", "the ", "my ")):
                add_assertion("user", "residence", loc, vf=dt, scope={})
                add_relation("user", "lives_in", loc, vf=dt)
                add_relation("user", "residence", loc, vf=dt)

        # Current residence: "I live in Sacramento", "I currently live in Sacramento", "I reside in Sacramento"
        m_live = re.search(
            r"(?i)(?:(?:in|since)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+(?:currently\s+)?(?:live|reside)\s+in\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|since)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s+with|\s+and|\s*$)",
            sentence,
        )
        if m_live:
            loc = _clean_location(m_live.group(2))
            dt = parse_explicit_date(m_live.group(1)) or parse_explicit_date(m_live.group(3)) or sentence_date
            if loc and len(loc) > 1 and not loc.lower().startswith(("a ", "an ", "the ", "my ")):
                add_assertion("user", "residence", loc, vf=dt, scope={})
                add_relation("user", "lives_in", loc, vf=dt)
                add_relation("user", "residence", loc, vf=dt)

        # "I am living in Shibuya", "I'm currently living in Shibuya"
        m_living = re.search(
            r"(?i)(?:I\s+am|I'm)\s+(?:currently\s+)?living\s+in\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|since)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s+with|\s+and|\s*$)",
            sentence,
        )
        if m_living:
            loc = _clean_location(m_living.group(1))
            dt = parse_explicit_date(m_living.group(2)) or sentence_date
            if loc and len(loc) > 1 and not loc.lower().startswith(("a ", "an ", "the ", "my ")):
                add_assertion("user", "residence", loc, vf=dt, scope={})
                add_relation("user", "lives_in", loc, vf=dt)
                add_relation("user", "residence", loc, vf=dt)

        # "My apartment is in Shibuya", "My current apartment is in Shibuya", "My house in Portland"
        m_apt = re.search(
            r"(?i)my\s+(?:current\s+)?(?:apartment|house|home|condo|place)\s+(?:is\s+)?in\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:[.,;]|\s+with|\s+and|\s*$)",
            sentence,
        )
        if m_apt:
            loc = _clean_location(m_apt.group(1))
            if loc and len(loc) > 1 and not loc.lower().startswith(("a ", "an ", "the ", "my ")):
                add_assertion("user", "residence", loc, vf=sentence_date, scope={})
                add_relation("user", "lives_in", loc, vf=sentence_date)
                add_relation("user", "residence", loc, vf=sentence_date)

        # "I bought a house in Portland", "I bought an apartment in Tokyo"
        m_bought_home = re.search(
            r"(?i)(?:I|we)\s+bought\s+(?:an?\s+)?(?:apartment|house|home|condo)\s+in\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:[.,;]|\s+with|\s+and|\s*$)",
            sentence,
        )
        if m_bought_home:
            loc = _clean_location(m_bought_home.group(1))
            if loc and len(loc) > 1 and not loc.lower().startswith(("a ", "an ", "the ", "my ")):
                add_assertion("user", "residence", loc, vf=sentence_date, scope={})
                add_relation("user", "lives_in", loc, vf=sentence_date)
                add_relation("user", "residence", loc, vf=sentence_date)

        # ----------------------------------------------------------------------
        # 2. Family & Pets
        # ----------------------------------------------------------------------
        # Family: "My daughter Emily", "My son Lucas", "My wife Sarah", "My husband John"
        for m_fam in re.finditer(
            r"(?i)\bmy\s+(daughter|son|wife|husband|mother|father|mom|dad|brother|sister)\s+([A-Z][a-z]+)\b",
            sentence,
        ):
            role = m_fam.group(1).lower()
            name = m_fam.group(2)
            add_assertion("user", "has_family", name, vf=sentence_date, scope={"relation": role})
            add_relation("user", "has_family", name, vf=sentence_date)
            add_relation("user", f"has_{role}", name, vf=sentence_date)

        # Family named: "I have a daughter named Emily", "I have a son named Lucas"
        for m_fam_named in re.finditer(
            r"(?i)(?:I\s+have|I've\s+got)\s+a\s+(daughter|son|wife|husband|brother|sister)\s+(?:named|called)\s+([A-Z][a-z]+)\b",
            sentence,
        ):
            role = m_fam_named.group(1).lower()
            name = m_fam_named.group(2)
            add_assertion("user", "has_family", name, vf=sentence_date, scope={"relation": role})
            add_relation("user", "has_family", name, vf=sentence_date)
            add_relation("user", f"has_{role}", name, vf=sentence_date)

        # Pets: "My dog Buster", "My cat Luna", "My pet dog Buster", "My pet hamster Coco"
        for m_pet in re.finditer(
            r"(?i)\bmy\s+(?:pet\s+)?(dog|cat|hamster|rabbit|parrot|puppy|kitten)\s+([A-Z][a-z]+)\b",
            sentence,
        ):
            species = m_pet.group(1).lower()
            name = m_pet.group(2)
            add_assertion("user", "has_pet", name, vf=sentence_date, scope={"species": species})
            add_relation("user", "has_pet", name, vf=sentence_date)
            add_relation("user", f"has_{species}", name, vf=sentence_date)
            add_relation(name, "is_a", species, vf=sentence_date)

        # Pets named: "I have a dog named Buster", "I have a pet cat named Luna"
        for m_pet_named in re.finditer(
            r"(?i)(?:I\s+have|I've\s+got)\s+an?\s+(?:pet\s+)?(dog|cat|hamster|rabbit|parrot)\s+(?:named|called)\s+([A-Z][a-z]+)\b",
            sentence,
        ):
            species = m_pet_named.group(1).lower()
            name = m_pet_named.group(2)
            add_assertion("user", "has_pet", name, vf=sentence_date, scope={"species": species})
            add_relation("user", "has_pet", name, vf=sentence_date)
            add_relation("user", f"has_{species}", name, vf=sentence_date)
            add_relation(name, "is_a", species, vf=sentence_date)

        # Pet breed / attribute: "My dog Buster is a Golden Retriever", "Buster is a Golden Retriever"
        m_breed = re.search(
            r"(?i)\b([A-Z][a-z]+)\s+is\s+an?\s+([A-Z][A-Za-z\s]+?)(?:[.,;]|\s*)$",
            sentence,
        )
        if m_breed:
            pet_name = m_breed.group(1)
            breed_str = m_breed.group(2).strip().strip(",.;")
            # If pet_name is already known or context suggests pet
            if any(a.predicate == "has_pet" and a.object == pet_name for a in assertions):
                add_assertion(pet_name, "breed", breed_str, vf=sentence_date)
                add_relation(pet_name, "breed", breed_str, vf=sentence_date)

        # ----------------------------------------------------------------------
        # 3. Expenses & Counts
        # ----------------------------------------------------------------------
        # Expenses: "I spent $450 on bike repairs", "I spent 120 dollars on groceries"
        m_spent = re.search(
            r"(?i)(?:(?:I|we)\s+spent|\$)\s*(\$?\d+(?:,\d+)*(?:\.\d+)?)\s*(?:dollars?)?\s+(?:on|for)\s+([a-zA-Z0-9\s'-]+?)(?:[.,;]|\s+in\s+\d{4}|\s*$)",
            sentence,
        )
        if m_spent:
            amt_raw = m_spent.group(1).replace("$", "").replace(",", "")
            item_raw = m_spent.group(2).strip().strip(",.;")
            try:
                amt_float = float(amt_raw)
                obj_str = f"${int(amt_float) if amt_float.is_integer() else amt_float} on {item_raw}"
                add_assertion("user", "expense", obj_str, vf=sentence_date, scope={"amount": amt_float, "item": item_raw})
                add_relation("user", "expense", item_raw, vf=sentence_date)
                add_relation("user", "spent_on", item_raw, vf=sentence_date)
            except ValueError:
                pass

        # "Total money spent on bike repairs was $450"
        m_total_spent = re.search(
            r"(?i)total\s+money\s+spent\s+on\s+([a-zA-Z0-9\s'-]+?)\s+(?:was|is)\s+\$?(\d+(?:,\d+)*(?:\.\d+)?)",
            sentence,
        )
        if m_total_spent:
            item_raw = m_total_spent.group(1).strip().strip(",.;")
            amt_raw = m_total_spent.group(2).replace(",", "")
            try:
                amt_float = float(amt_raw)
                obj_str = f"${int(amt_float) if amt_float.is_integer() else amt_float} on {item_raw}"
                add_assertion("user", "expense", obj_str, vf=sentence_date, scope={"amount": amt_float, "item": item_raw})
                add_relation("user", "expense", item_raw, vf=sentence_date)
                add_relation("user", "spent_on", item_raw, vf=sentence_date)
            except ValueError:
                pass

        # "I paid $80 for dinner"
        m_paid = re.search(
            r"(?i)(?:I|we)\s+paid\s+\$?(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:dollars?)?\s+(?:for|on)\s+([a-zA-Z0-9\s'-]+?)(?:[.,;]|\s*$)",
            sentence,
        )
        if m_paid:
            amt_raw = m_paid.group(1).replace(",", "")
            item_raw = m_paid.group(2).strip().strip(",.;")
            try:
                amt_float = float(amt_raw)
                obj_str = f"${int(amt_float) if amt_float.is_integer() else amt_float} on {item_raw}"
                add_assertion("user", "expense", obj_str, vf=sentence_date, scope={"amount": amt_float, "item": item_raw})
                add_relation("user", "expense", item_raw, vf=sentence_date)
            except ValueError:
                pass

        # Counts: "I bought 3 guitars", "I have 5 bicycles", "I own two cars"
        for m_count in re.finditer(
            r"(?i)\b(?:I|we)\s+(?:bought|purchased|have|own|got)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+([a-zA-Z0-9'-]+(?:\s+(?!and\b|or\b|with\b|in\s+\d{4}\b)[a-zA-Z0-9'-]+)*)",
            sentence,
        ):
            num_raw = m_count.group(1).lower()
            item_raw = m_count.group(2).strip().strip(",.;")
            count_val = int(num_raw) if num_raw.isdigit() else WORD_TO_NUM.get(num_raw, 1)
            # Avoid matching family or pets as generic counts (e.g. "I have a daughter" or "I have 2 dogs")
            if not any(w in item_raw.lower() for w in ("dog", "cat", "daughter", "son", "sister", "brother", "wife", "husband", "pet")):
                obj_str = f"{count_val} {item_raw}"
                add_assertion("user", "count", obj_str, vf=sentence_date, scope={"count": count_val, "item": item_raw})
                add_relation("user", "owns", item_raw, vf=sentence_date)

        # ----------------------------------------------------------------------
        # 4. Dated Milestones
        # ----------------------------------------------------------------------
        # Education: "In 2021, I graduated from Stanford", "I graduated from MIT in 2018"
        m_grad = re.search(
            r"(?i)(?:(?:in|on)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+graduated\s+from\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|on)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s+with|\s+and|\s*$)",
            sentence,
        )
        if m_grad:
            inst = m_grad.group(2).strip().strip(",.;")
            inst = re.sub(r"(?i)\s+(?:in\s+\d{4}|with\s+.*|and\s+.*)$", "", inst).strip()
            dt = parse_explicit_date(m_grad.group(1)) or parse_explicit_date(m_grad.group(3)) or sentence_date
            if inst and len(inst) > 1:
                # Add both education and milestone assertions/relations for high recall
                add_assertion("user", "education", inst, vf=dt, scope={"milestone": "graduation"})
                add_assertion("user", "milestone", f"graduated from {inst}", vf=dt, scope={"milestone": "graduation"})
                add_relation("user", "graduated_from", inst, vf=dt)
                add_relation("user", "education", inst, vf=dt)

        # Degrees: "I received my degree from UC Berkeley in 2020", "I got my PhD from Harvard in 2017"
        m_degree = re.search(
            r"(?i)(?:(?:in|on)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+(?:received|earned|got|completed)\s+(?:my|a|an)\s+(?:degree|bachelor'?s?|master'?s?|phd|doctorate)\s+from\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|on)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s*$)",
            sentence,
        )
        if m_degree:
            inst = m_degree.group(2).strip().strip(",.;")
            inst = re.sub(r"(?i)\s+(?:in\s+\d{4}|with\s+.*|and\s+.*)$", "", inst).strip()
            dt = parse_explicit_date(m_degree.group(1)) or parse_explicit_date(m_degree.group(3)) or sentence_date
            if inst and len(inst) > 1:
                add_assertion("user", "education", inst, vf=dt, scope={"milestone": "degree"})
                add_assertion("user", "milestone", f"degree from {inst}", vf=dt, scope={"milestone": "degree"})
                add_relation("user", "graduated_from", inst, vf=dt)
                add_relation("user", "education", inst, vf=dt)

        # Career milestones: "In 2019, I started working at Google", "In 2022, I joined Apple"
        m_career = re.search(
            r"(?i)(?:(?:in|on)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+(?:started\s+(?:working\s+at|at|my\s+job\s+at)|joined)\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|on)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s*$)",
            sentence,
        )
        if m_career:
            company = m_career.group(2).strip().strip(",.;")
            company = re.sub(r"(?i)\s+(?:in\s+\d{4}|as\s+.*|with\s+.*|and\s+.*)$", "", company).strip()
            dt = parse_explicit_date(m_career.group(1)) or parse_explicit_date(m_career.group(3)) or sentence_date
            if company and len(company) > 1:
                add_assertion("user", "milestone", f"started working at {company}", vf=dt, scope={"milestone": "employment"})
                add_relation("user", "works_at", company, vf=dt)
                add_relation("user", "employed_by", company, vf=dt)

        # Marriage: "In 2015, I got married", "On October 12, 2015, I got married to Sarah"
        m_married = re.search(
            r"(?i)(?:(?:in|on)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+got\s+married(?:\s+to\s+([A-Z][a-z]+))?(?:\s+(?:in|on)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s*$)",
            sentence,
        )
        if m_married:
            dt = parse_explicit_date(m_married.group(1)) or parse_explicit_date(m_married.group(3)) or sentence_date
            spouse = m_married.group(2)
            obj_str = f"got married to {spouse}" if spouse else "got married"
            add_assertion("user", "milestone", obj_str, vf=dt, scope={"milestone": "marriage"})
            if spouse:
                add_assertion("user", "has_family", spouse, vf=dt, scope={"relation": "spouse"})
                add_relation("user", "married_to", spouse, vf=dt)
                add_relation("user", "has_family", spouse, vf=dt)

    return ExtractedFacts(assertions=assertions, relations=relations)
