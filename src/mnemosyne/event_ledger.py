"""Multi-session event ledger and set-aggregation synthesis engine.

Compiles distinct user actions, purchases, activities, and counts across
multiple conversational sessions. Provides canonical deduplication and dual
category set aggregation (strict core items vs. inclusive/accessory items)
to decisively answer multi-session aggregation questions.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

# Regular expressions for expense and purchase extraction
_CURRENCY_AMOUNT_RE = re.compile(
    r"(?P<curr>[\$€£]|USD\s*|EUR\s*|GBP\s*)?\s*(?P<amt>\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?P<curr_suffix>dollars?|bucks?|euros?|pounds?|USD|EUR|GBP)?",
    re.IGNORECASE,
)
_EXPENSE_PHRASE_RE = re.compile(
    r"(?:(?:\b(?:bought|purchased|ordered|picked\s+up|paid|spent|cost|and)\b|,(?!\s*(?:i\b|we\b|you\b|they\b|he\b|she\b|bought\b|purchased\b|ordered\b|picked\b|paid\b|spent\b|cost\b)))\s*(?:a\s+|an\s+|the\s+)?|(?:\b(?:a|an|the)\s+))"
    r"(?P<item>[a-zA-Z0-9\s\-]+?)\s+(?:for|at|costing|\$)\s*"
    r"(?P<cost>[\$€£]\s*\d+(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:,\d{3})*(?:\.\d{1,2})?\s*(?:dollars?|bucks?|USD|EUR|GBP))",
    re.IGNORECASE,
)
_EXPENSE_INVERSE_RE = re.compile(
    r"(?:spent|paid)\s+(?P<cost>[\$€£]?\s*\d+(?:\.\d{1,2})?(?:\s*(?:dollars?|bucks?|USD))?)\s+(?:on|for)\s+(?:a\s+|an\s+|the\s+)?(?P<item>[a-zA-Z0-9\s\-]+?)(?=\s+and\s+(?:paid|spent|bought|picked|cost)|[.,;!\n\(\)]|$)",
    re.IGNORECASE,
)
_COST_IS_RE = re.compile(
    r"(?:the\s+)?(?P<item>[a-zA-Z0-9\s\-]+?)\s+(?:cost|was|came\s+out\s+to)\s+(?P<cost>[\$€£]\s*\d+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

# Number word mapping for count extraction
_NUMBER_WORDS: dict[str, int] = {
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
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}
_COUNT_PHRASE_RE = re.compile(
    r"(?<![\.\$€£])\b(?P<qty>[1-9]\d*|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
    r"(?P<item>(?!and\b|or\b|for\b|of\b|at\b|to\b)[a-zA-Z\-]+(?:\s+[a-zA-Z\-]+){0,2})\b",
    re.IGNORECASE,
)

# Activity verbs
_ACTIVITY_VERB_RE = re.compile(
    r"\b(?:played|learned|started\s+learning|cooked|made|tried|enrolled\s+in|completed|finished|visited|built|assembled|practiced)\s+"
    r"(?P<item>[a-zA-Z0-9\s\-]+?)(?:[.,;!\n]|\s+and|\s+with|\s+at|\s+in|\s+for|$)",
    re.IGNORECASE,
)

# ISO date pattern
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_YEAR_MONTH_RE = re.compile(r"\b(\d{4}-\d{2})\b")


def _normalize_text(text: str) -> str:
    """Normalize text for consistent canonical entity matching."""
    return " ".join(unicodedata.normalize("NFKC", text).split()).strip()


def _term_matches_text(term: str, text: str) -> bool:
    """Check if keyword/alias matches text, using word boundaries for short tokens with optional plural 's'."""
    t_clean = text.lower()
    term_clean = term.lower()
    if len(term_clean) <= 2:
        return bool(re.search(rf"\b{re.escape(term_clean)}s?\b", t_clean))
    if len(term_clean) == 3 and term_clean.endswith("s"):
        return bool(re.search(rf"\b{re.escape(term_clean)}\b", t_clean))
    return term_clean in t_clean


def _normalize_entity(entity: str) -> str:
    """Strip conjunctions, verbs, articles, possessives, and lower-case entity name."""
    s = entity.lower().strip()
    s = re.sub(
        r"^(?:(?:and|or|also)\s+)?(?:i\s+)?(?:bought|purchased|ordered|picked\s+up|paid\s+(?:for)?|spent\s+(?:on)?)\s+",
        "",
        s,
    )
    s = re.sub(r"^(?:a|an|the|my|our|some|new)\s+", "", s)
    s = re.sub(r"['’]s\b", "", s)
    s = re.sub(r"[^\w\s\-]", "", s)
    return " ".join(s.split())


@dataclass(frozen=True, slots=True)
class EventLedgerEntry:
    """An atomic verified user event, item, purchase, or activity in the ledger."""

    entry_id: str
    session_id: str
    session_date: str
    event_date: str | None
    speaker_role: str
    action: str  # "purchase", "expense", "activity", "sport", "cuisine", "course", "creation", "item"
    entity: str  # Clean display entity name
    canonical_key: str  # Deduplication key (normalized_entity + temporal_window)
    value: float | None  # Monetary cost or numeric count
    unit: str | None  # "USD", "items", "hours", etc.
    category_tags: tuple[str, ...]
    is_borderline: bool
    borderline_reason: str | None
    evidence_cid: str
    quote_span: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SetAggregationResult:
    """Decisive dual-set aggregation result over ledger entries."""

    query: str
    target_category: str
    total_entries_found: int
    strict_entries: tuple[EventLedgerEntry, ...]
    borderline_entries: tuple[EventLedgerEntry, ...]
    strict_count: int
    inclusive_count: int
    strict_sum: float | None
    inclusive_sum: float | None
    unit: str | None
    synthesis_text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Category taxonomy rules mapping target categories to strict vs borderline keywords.
# Empty: the previous table was tuned on benchmark questions; without an entry the
# category comes from the query and every match counts as strict.
_TAXONOMY: dict[str, dict[str, tuple[tuple[str, ...], tuple[str, ...], str]]] = {}


class EventLedger:
    """Extracts, deduplicates, and aggregates multi-session user events and items."""

    def __init__(self, entries: Sequence[EventLedgerEntry] = ()) -> None:
        self._entries: list[EventLedgerEntry] = list(entries)

    @property
    def entries(self) -> tuple[EventLedgerEntry, ...]:
        return tuple(self._entries)

    def add_entry(self, entry: EventLedgerEntry) -> None:
        self._entries.append(entry)

    def extract_from_evidence(
        self,
        evidence_rows: Sequence[Mapping[str, Any] | Any],
    ) -> list[EventLedgerEntry]:
        """Extract user event, purchase, count, and activity candidates from evidence rows."""
        extracted: list[EventLedgerEntry] = []

        for row in evidence_rows:
            if isinstance(row, Mapping):
                content = str(row.get("content") or "")
                cid = str(row.get("cid") or "")
                session_id = str(row.get("session_id") or "")
                created_at = row.get("created_at") or row.get("valid_from") or ""
                speaker = (
                    str(row.get("speaker_role") or row.get("speaker") or "")
                    .strip()
                    .lower()
                )
            else:
                content = str(getattr(row, "content", "") or "")
                cid = str(getattr(row, "cid", "") or "")
                session_id = str(getattr(row, "session_id", "") or "")
                created_at = getattr(row, "created_at", "") or ""
                speaker = str(getattr(row, "speaker_role", "") or "").strip().lower()

            if not content.strip():
                continue

            # Identify speaker turns within content if conversational transcript
            turns = self._split_turns(content, default_speaker=speaker or "user")

            # Determine session date
            session_date = ""
            date_m = _DATE_RE.search(str(created_at)) or _DATE_RE.search(content)
            if date_m:
                session_date = date_m.group(1)

            for turn_speaker, turn_text in turns:
                if turn_speaker in {"assistant", "agent", "bot", "ai", "model"}:
                    continue  # strictly user events

                turn_entries = self._extract_from_text(
                    turn_text,
                    session_id=session_id,
                    session_date=session_date,
                    evidence_cid=cid,
                )
                extracted.extend(turn_entries)

        # Deduplicate extracted entries across sessions
        deduped = self._deduplicate(extracted)
        self._entries.extend(deduped)
        return deduped

    def _split_turns(self, text: str, default_speaker: str) -> list[tuple[str, str]]:
        """Split text into speaker turns (User: ... / Assistant: ...)."""
        turn_pattern = re.compile(
            r"^(User|Assistant|Human|AI):\s*", re.MULTILINE | re.IGNORECASE
        )
        splits = list(turn_pattern.finditer(text))
        if not splits:
            return [(default_speaker, text)]

        results: list[tuple[str, str]] = []
        for i, match in enumerate(splits):
            spk = match.group(1).lower()
            start = match.end()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            body = text[start:end].strip()
            if body:
                results.append((spk, body))
        return results

    def _parse_currency_amount(self, text: str) -> float | None:
        """Parse currency number from string."""
        m = _CURRENCY_AMOUNT_RE.search(text)
        if not m:
            return None
        raw_amt = m.group("amt").replace(",", "")
        try:
            return float(raw_amt)
        except ValueError:
            return None

    def _extract_from_text(
        self,
        text: str,
        session_id: str,
        session_date: str,
        evidence_cid: str,
    ) -> list[EventLedgerEntry]:
        """Extract candidate items, purchases, and activities from a user utterance."""
        entries: list[EventLedgerEntry] = []
        event_date = session_date
        date_m = _DATE_RE.search(text)
        if date_m:
            event_date = date_m.group(1)

        # 1. Purchase / Expense patterns
        for m in _EXPENSE_PHRASE_RE.finditer(text):
            item_raw = m.group("item").strip()
            item_raw = re.sub(
                r"^(?:(?:and|or|also)\s+)?(?:i\s+|we\s+)?(?:bought|purchased|ordered|picked\s+up|paid\s+(?:for)?|spent\s+(?:on)?)\s*(?:a|an|the)?\s*",
                "",
                item_raw,
                flags=re.IGNORECASE,
            ).strip()
            item_raw = re.sub(
                r"^(?:bought|purchased|ordered|picked\s+up|paid\s+(?:for)?|spent\s+(?:on)?)\s*(?:a|an|the)?\s*",
                "",
                item_raw,
                flags=re.IGNORECASE,
            ).strip()
            item_raw = re.sub(
                r"^(?:(?:and|or|also)\s+)?(?:a|an|the)\s+",
                "",
                item_raw,
                flags=re.IGNORECASE,
            ).strip()
            cost_raw = m.group("cost").strip()
            val = self._parse_currency_amount(cost_raw)
            clean_ent = _normalize_text(item_raw)
            clean_ent = re.sub(
                r"^(?:(?:and|or|also)\s+)?(?:i\s+|we\s+)?(?:bought|purchased|ordered|picked\s+up|paid\s+(?:for)?|spent\s+(?:on)?)\s*(?:a|an|the)?\s*",
                "",
                clean_ent,
                flags=re.IGNORECASE,
            ).strip()
            clean_ent = re.sub(
                r"^(?:a|an|the)\s+", "", clean_ent, flags=re.IGNORECASE
            ).strip()
            if clean_ent and len(clean_ent) >= 2 and val is not None:
                norm_ent = _normalize_entity(clean_ent)
                temp_key = event_date[:7] if event_date else "nodate"
                canonical_key = f"{norm_ent}_{temp_key}"
                entries.append(
                    EventLedgerEntry(
                        entry_id=f"exp_{evidence_cid}_{m.start()}",
                        session_id=session_id,
                        session_date=session_date,
                        event_date=event_date,
                        speaker_role="user",
                        action="purchase",
                        entity=clean_ent,
                        canonical_key=canonical_key,
                        value=val,
                        unit="USD",
                        category_tags=self._tag_entity(clean_ent),
                        is_borderline=False,
                        borderline_reason=None,
                        evidence_cid=evidence_cid,
                        quote_span=m.group(0),
                    )
                )

        for m in _EXPENSE_INVERSE_RE.finditer(text):
            cost_raw = m.group("cost").strip()
            item_raw = m.group("item").strip()
            val = self._parse_currency_amount(cost_raw)
            clean_ent = _normalize_text(item_raw)
            if clean_ent and len(clean_ent) >= 2 and val is not None:
                norm_ent = _normalize_entity(clean_ent)
                temp_key = event_date[:7] if event_date else "nodate"
                canonical_key = f"{norm_ent}_{temp_key}"
                entries.append(
                    EventLedgerEntry(
                        entry_id=f"exp_inv_{evidence_cid}_{m.start()}",
                        session_id=session_id,
                        session_date=session_date,
                        event_date=event_date,
                        speaker_role="user",
                        action="purchase",
                        entity=clean_ent,
                        canonical_key=canonical_key,
                        value=val,
                        unit="USD",
                        category_tags=self._tag_entity(clean_ent),
                        is_borderline=False,
                        borderline_reason=None,
                        evidence_cid=evidence_cid,
                        quote_span=m.group(0),
                    )
                )

        for m in _COST_IS_RE.finditer(text):
            item_raw = m.group("item").strip()
            cost_raw = m.group("cost").strip()
            val = self._parse_currency_amount(cost_raw)
            clean_ent = _normalize_text(item_raw)
            if clean_ent and len(clean_ent) >= 2 and val is not None:
                norm_ent = _normalize_entity(clean_ent)
                temp_key = event_date[:7] if event_date else "nodate"
                canonical_key = f"{norm_ent}_{temp_key}"
                entries.append(
                    EventLedgerEntry(
                        entry_id=f"cost_{evidence_cid}_{m.start()}",
                        session_id=session_id,
                        session_date=session_date,
                        event_date=event_date,
                        speaker_role="user",
                        action="purchase",
                        entity=clean_ent,
                        canonical_key=canonical_key,
                        value=val,
                        unit="USD",
                        category_tags=self._tag_entity(clean_ent),
                        is_borderline=False,
                        borderline_reason=None,
                        evidence_cid=evidence_cid,
                        quote_span=m.group(0),
                    )
                )

        # 2. Activity / Accomplishment / Cuisine / Sport patterns
        for m in _ACTIVITY_VERB_RE.finditer(text):
            act_item = m.group("item").strip()
            clean_ent = _normalize_text(act_item)
            if clean_ent and len(clean_ent) >= 2:
                norm_ent = _normalize_entity(clean_ent)
                temp_key = event_date[:7] if event_date else "nodate"
                canonical_key = f"{norm_ent}_{temp_key}"
                entries.append(
                    EventLedgerEntry(
                        entry_id=f"act_{evidence_cid}_{m.start()}",
                        session_id=session_id,
                        session_date=session_date,
                        event_date=event_date,
                        speaker_role="user",
                        action="activity",
                        entity=clean_ent,
                        canonical_key=canonical_key,
                        value=1.0,
                        unit="event",
                        category_tags=self._tag_entity(clean_ent),
                        is_borderline=False,
                        borderline_reason=None,
                        evidence_cid=evidence_cid,
                        quote_span=m.group(0),
                    )
                )

        # 3. Item count patterns
        for m in _COUNT_PHRASE_RE.finditer(text):
            qty_raw = m.group("qty").lower()
            qty_val = _NUMBER_WORDS.get(qty_raw)
            if qty_val is None:
                try:
                    qty_val = int(qty_raw)
                except ValueError:
                    qty_val = 1
            item_raw = m.group("item").strip()
            clean_ent = _normalize_text(item_raw)
            if clean_ent and len(clean_ent) >= 2:
                norm_ent = _normalize_entity(clean_ent)
                temp_key = event_date[:7] if event_date else "nodate"
                canonical_key = f"{norm_ent}_{temp_key}"
                entries.append(
                    EventLedgerEntry(
                        entry_id=f"qty_{evidence_cid}_{m.start()}",
                        session_id=session_id,
                        session_date=session_date,
                        event_date=event_date,
                        speaker_role="user",
                        action="item",
                        entity=clean_ent,
                        canonical_key=canonical_key,
                        value=float(qty_val),
                        unit="items",
                        category_tags=self._tag_entity(clean_ent),
                        is_borderline=False,
                        borderline_reason=None,
                        evidence_cid=evidence_cid,
                        quote_span=m.group(0),
                    )
                )

        return entries

    def _tag_entity(self, entity: str) -> tuple[str, ...]:
        """Attach domain tags to an entity based on taxonomy keywords."""
        tags: list[str] = []
        norm = entity.lower()
        for cat_key, tax in _TAXONOMY.items():
            aliases = tax["aliases"][0]
            strict_words = tax["rules"][0]
            borderline_words = tax["rules"][1]
            if (
                any(_term_matches_text(a, norm) for a in aliases)
                or any(_term_matches_text(w, norm) for w in strict_words)
                or any(_term_matches_text(w, norm) for w in borderline_words)
            ):
                tags.append(cat_key)
        return tuple(tags)

    def _deduplicate(
        self, entries: Sequence[EventLedgerEntry]
    ) -> list[EventLedgerEntry]:
        """Deduplicate entries across sessions by canonical key and cross-session entity matching."""
        result: list[EventLedgerEntry] = []
        for entry in entries:
            norm = _normalize_entity(entry.entity)
            matched_idx: int | None = None
            for idx, existing in enumerate(result):
                if entry.canonical_key == existing.canonical_key:
                    matched_idx = idx
                    break
                existing_norm = _normalize_entity(existing.entity)
                if norm == existing_norm:
                    both_monetary = (
                        entry.unit in {"USD", "$"}
                        and existing.unit in {"USD", "$"}
                        and entry.value is not None
                        and existing.value is not None
                    )
                    if both_monetary and round(entry.value, 2) == round(
                        existing.value, 2
                    ):
                        matched_idx = idx
                        break
                    one_monetary = (
                        entry.unit in {"USD", "$"} and entry.value is not None
                    ) != (existing.unit in {"USD", "$"} and existing.value is not None)
                    if one_monetary:
                        matched_idx = idx
                        break
                    if (
                        entry.unit not in {"USD", "$"}
                        and existing.unit not in {"USD", "$"}
                        and entry.value == existing.value
                    ):
                        matched_idx = idx
                        break

            if matched_idx is None:
                result.append(entry)
            else:
                existing = result[matched_idx]
                existing_is_monetary = (
                    existing.unit in {"USD", "$"} and existing.value is not None
                )
                entry_is_monetary = (
                    entry.unit in {"USD", "$"} and entry.value is not None
                )
                if entry_is_monetary and not existing_is_monetary:
                    result[matched_idx] = entry
                elif not entry_is_monetary and existing_is_monetary:
                    pass
                elif len(entry.quote_span) > len(existing.quote_span):
                    result[matched_idx] = entry
        return result

    def _resolve_target_category(
        self, query: str, explicit_cat: str | None = None
    ) -> str:
        """Infer target category from query if not explicitly passed."""
        if explicit_cat and explicit_cat.strip():
            return explicit_cat.strip().lower()
        q_norm = query.lower()
        for cat_key, tax in _TAXONOMY.items():
            aliases = tax["aliases"][0]
            strict_words = tax["rules"][0]
            if any(_term_matches_text(a, q_norm) for a in aliases) or any(
                _term_matches_text(w, q_norm) for w in strict_words
            ):
                return cat_key
        # Fallback noun heuristic from query
        m = re.search(
            r"\b(?:spend\s+on|bought|cost\s+of|count\s+of|how\s+many)\s+([a-zA-Z\s]+?)(?:\?|\bfor\b|\sin\b|$)",
            q_norm,
        )
        if m:
            return m.group(1).strip()
        return "items"

    def aggregate(
        self,
        query: str,
        target_category: str | None = None,
    ) -> SetAggregationResult:
        """Perform dual strict vs. inclusive set aggregation over ledger entries."""
        category = self._resolve_target_category(query, target_category)

        strict_entries: list[EventLedgerEntry] = []
        borderline_entries: list[EventLedgerEntry] = []

        tax_info = _TAXONOMY.get(category)
        strict_kw: tuple[str, ...] = tax_info["rules"][0] if tax_info else (category,)
        borderline_kw: tuple[str, ...] = tax_info["rules"][1] if tax_info else ()
        borderline_reason: str = (
            tax_info["rules"][2]
            if tax_info
            else f"related or accessory item to {category}"
        )

        for entry in self._entries:
            ent_norm = entry.entity.lower()
            quote_norm = entry.quote_span.lower()

            # Check borderline first as borderline keywords are specific accessories/apparel
            is_borderline = any(
                _term_matches_text(w, ent_norm) or _term_matches_text(w, quote_norm)
                for w in borderline_kw
            )
            is_strict = any(
                _term_matches_text(w, ent_norm) or _term_matches_text(w, quote_norm)
                for w in strict_kw
            )

            if is_borderline:
                # Mark as borderline with reason
                b_entry = EventLedgerEntry(
                    entry_id=entry.entry_id,
                    session_id=entry.session_id,
                    session_date=entry.session_date,
                    event_date=entry.event_date,
                    speaker_role=entry.speaker_role,
                    action=entry.action,
                    entity=entry.entity,
                    canonical_key=entry.canonical_key,
                    value=entry.value,
                    unit=entry.unit,
                    category_tags=entry.category_tags,
                    is_borderline=True,
                    borderline_reason=borderline_reason,
                    evidence_cid=entry.evidence_cid,
                    quote_span=entry.quote_span,
                )
                borderline_entries.append(b_entry)
            elif is_strict:
                strict_entries.append(entry)
            elif category in entry.category_tags:
                strict_entries.append(entry)

        strict_count = len(strict_entries)
        inclusive_count = strict_count + len(borderline_entries)

        # Calculate sums if values are present
        has_monetary = any(e.unit == "USD" for e in strict_entries + borderline_entries)
        strict_sum: float | None = None
        inclusive_sum: float | None = None
        unit: str | None = "items"

        if has_monetary:
            s_sum = sum(
                e.value
                for e in strict_entries
                if e.value is not None and e.unit in {"USD", "$"}
            )
            b_sum = sum(
                e.value
                for e in borderline_entries
                if e.value is not None and e.unit in {"USD", "$"}
            )
            strict_sum = round(s_sum, 2)
            inclusive_sum = round(s_sum + b_sum, 2)
            unit = "USD"
        elif any(e.value is not None for e in strict_entries + borderline_entries):
            s_sum = sum(e.value for e in strict_entries if e.value is not None)
            b_sum = sum(e.value for e in borderline_entries if e.value is not None)
            strict_sum = s_sum
            inclusive_sum = s_sum + b_sum

        # Generate synthesis text according to dual reporting protocol
        synthesis_text = self._format_synthesis(
            category=category,
            strict_entries=strict_entries,
            borderline_entries=borderline_entries,
            strict_count=strict_count,
            inclusive_count=inclusive_count,
            strict_sum=strict_sum,
            inclusive_sum=inclusive_sum,
            unit=unit,
        )

        return SetAggregationResult(
            query=query,
            target_category=category,
            total_entries_found=strict_count + len(borderline_entries),
            strict_entries=tuple(strict_entries),
            borderline_entries=tuple(borderline_entries),
            strict_count=strict_count,
            inclusive_count=inclusive_count,
            strict_sum=strict_sum,
            inclusive_sum=inclusive_sum,
            unit=unit,
            synthesis_text=synthesis_text,
        )

    def _format_item_list(
        self, entries: Sequence[EventLedgerEntry], is_monetary: bool
    ) -> str:
        """Format a list of entries with optional item costs."""
        items: list[str] = []
        for e in entries:
            if is_monetary and e.value is not None and e.unit in {"USD", "$"}:
                items.append(f"{e.entity} (${e.value:.2f})")
            else:
                items.append(e.entity)
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return f"{', '.join(items[:-1])}, and {items[-1]}"

    def _format_synthesis(
        self,
        category: str,
        strict_entries: Sequence[EventLedgerEntry],
        borderline_entries: Sequence[EventLedgerEntry],
        strict_count: int,
        inclusive_count: int,
        strict_sum: float | None,
        inclusive_sum: float | None,
        unit: str | None,
    ) -> str:
        """Synthesize decisive singular or dual reporting answer."""
        is_monetary = unit == "USD" and strict_sum is not None

        if inclusive_count == 0:
            return f"No records found for {category} in your history."

        strict_breakdown = self._format_item_list(strict_entries, is_monetary)

        # Single total when strict_count == inclusive_count
        if strict_count == inclusive_count:
            if is_monetary and strict_sum is not None:
                return f"You spent ${strict_sum:.2f} across {strict_count} {category} items: {strict_breakdown}."
            return f"You have {strict_count} {category} items: {strict_breakdown}."

        # Dual reporting when borderline items exist
        borderline_breakdown = self._format_item_list(borderline_entries, is_monetary)
        if is_monetary and strict_sum is not None and inclusive_sum is not None:
            return (
                f"Strictly for core {category} equipment and maintenance, you spent ${strict_sum:.2f} "
                f"across {strict_count} items ({strict_breakdown}). When including accessories and related gear "
                f"({borderline_breakdown}), the inclusive total is ${inclusive_sum:.2f} across {inclusive_count} items."
            )

        return (
            f"Strictly speaking, you have {strict_count} {category} items ({strict_breakdown}). "
            f"When including accessories and related items ({borderline_breakdown}), the inclusive total is "
            f"{inclusive_count} items."
        )
