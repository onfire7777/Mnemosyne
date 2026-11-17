"""Multi-granularity conversational retrieval and deterministic temporal-epistemic memory compiler.

Compiles raw multi-session chat histories into a high-SNR, chronologically anchored memory
representation without calling external LLMs or accessing benchmark ground-truth labels:

1. **Multi-Granularity + Temporal-Coordinate Hybrid Retrieval** (``rank_sessions_and_rounds``):
   Fuses complementary retrieval signals over authorized session evidence:
   - Whole-session dense similarity (via ``QuantizedVectorIndex`` / exact float32 cosine)
   - Multi-granularity BM25 (``PassageIndex.multi_granularity_scores`` combining session,
     user-only stem postings, round MaxP, and turn MaxP)
   - Facet sub-query round matching for multi-entity comparisons
   - **Temporal Coordinate Channel**: resolves relative/explicit temporal targets in the query
     (e.g. ``5 days ago``, ``yesterday``, ``last Saturday``, ``on May 12``) against ``evaluated_at``
     and matches both session ``created_at`` dates and resolved inline event dates inside user turns!
   - Optional Cross-Encoder / similarity reranking.

2. **Tiered High-SNR Turn Window Selection** (``select_compiled_turn_windows``):
   - Tier 1 (Core ``core_top_k`` sessions, default 7): 100% verbatim user and assistant turns.
   - Tier 2 (Extended ``ranks core_top_k+1 .. total_k``, default up to 16 total sessions):
     100% of all user turns in the session PLUS full verbatim assistant replies for the top
     query-matching rounds (``±1`` neighbor round), expanding recall from 10 to 16 sessions while
     reducing total prompt tokens vs. 10 raw full sessions.

3. **Deterministic Temporal & Epistemic Memory Index** (``compile_memory``):
   - Exact session-to-query calendar deltas via ``compute_calendar_delta``
   - Deterministic resolution of inline relative temporal phrases anchored to each session's date
   - Chronological speaker-attributed ``[USER]`` self-report ledger separating user facts from
     assistant suggestions/estimates and highlighting ``[MOST RECENT USER STATEMENT IN INDEX]``
   - ``PremiseConsistencyVerifier`` presupposition checks.
"""

from __future__ import annotations

import calendar
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional runtime extra
    np = None  # type: ignore[assignment]

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, Hit
from mnemosyne.passages import PassageIndex, _stem_passage_token
from mnemosyne.pipeline import _extract_query_facets
from mnemosyne.policy import OperatingPolicy
from mnemosyne.premise_verifier import PremiseConsistencyVerifier
from mnemosyne.retrieval import (
    EmbeddingProvider,
    HashingEmbeddingProvider,
    Reranker,
    compute_calendar_delta,
    embed_query,
)
from mnemosyne.text import TAXONOMIC_EXPANSIONS, tokenize

_NUMBER_WORDS: dict[str, int] = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "couple": 2,
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
    "thirty": 30,
}

_WEEKDAY_MAP: dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_MONTH_MAP: dict[str, int] = {
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

_WEEKDAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_STOP_QUERY_STEMS: frozenset[str] = frozenset(
    _stem_passage_token(w)
    for w in (
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "many",
        "much",
        "long",
        "often",
        "did",
        "does",
        "do",
        "was",
        "were",
        "is",
        "are",
        "am",
        "been",
        "have",
        "has",
        "had",
        "will",
        "would",
        "could",
        "should",
        "can",
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "these",
        "those",
        "into",
        "about",
        "between",
        "before",
        "after",
        "during",
        "since",
        "until",
        "ago",
        "last",
        "next",
        "past",
        "few",
        "recent",
        "recently",
        "currently",
        "now",
        "still",
        "latest",
        "first",
        "most",
        "more",
        "less",
        "than",
        "instead",
        "total",
        "all",
        "mention",
        "mentioned",
        "tell",
        "told",
        "say",
        "said",
        "ask",
        "asked",
        "give",
        "gave",
        "get",
        "got",
        "take",
        "took",
        "make",
        "made",
        "use",
        "used",
        "new",
        "old",
        "good",
        "best",
        "great",
        "same",
        "other",
        "help",
        "need",
        "want",
        "think",
        "know",
        "start",
        "started",
        "just",
        "way",
        "time",
        "times",
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "year",
        "years",
    )
)

_MULTI_OR_TEMPORAL_CUE_RE = re.compile(
    r"\b(?:how\s+many|how\s+much|how\s+long|total|combined|all\s+the|across|"
    r"between|before|after|first|last|order|chronological|days?|weeks?|months?|"
    r"ago|since|now|currently|latest|most\s+recent|still|anymore|instead|compare|difference)\b",
    re.IGNORECASE,
)

_STATE_UPDATE_CUE_RE = re.compile(
    r"\b(?:now|currently|latest|most\s+recent|still|anymore|updated?|new\s+role|new\s+job)\b",
    re.IGNORECASE,
)

_REL_AGO_RE = re.compile(
    r"\b(?P<num>\d{1,3}|a\s+couple(?:\s+of)?|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|a|an)"
    r"\s+(?P<unit>days?|weeks?|months?|years?)\s+(?P<dir>ago|earlier|before\s+that|prior)\b",
    re.IGNORECASE,
)
_REL_AHEAD_RE = re.compile(
    r"\b(?:in\s+(?P<in_num>\d{1,3}|a\s+couple(?:\s+of)?|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|fourteen|fifteen|twenty|thirty|a|an)\s+(?P<in_unit>days?|weeks?|months?|years?)"
    r"|(?P<lat_num>\d{1,3}|a\s+couple(?:\s+of)?|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s+(?P<lat_unit>days?|weeks?|months?)\s+(?:later|after(?:\s+that)?))\b",
    re.IGNORECASE,
)
_YESTERDAY_TOMORROW_RE = re.compile(
    r"\b(?P<kw>the\s+day\s+before\s+yesterday|yesterday|tomorrow|the\s+day\s+after\s+tomorrow)\b",
    re.IGNORECASE,
)
_LAST_NEXT_WEEKDAY_RE = re.compile(
    r"\b(?P<mod>this\s+past|last|this\s+coming|next)\s+"
    r"(?P<wd>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
    re.IGNORECASE,
)
_LAST_WEEK_MONTH_RE = re.compile(
    r"\b(?P<mod>last|this\s+past)\s+(?P<unit>week|weekend|month|year)\b",
    re.IGNORECASE,
)
_ON_WEEKDAY_RE = re.compile(
    r"\bon\s+(?P<wd>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
    re.IGNORECASE,
)
_MONTH_NAME_DATE_RE = re.compile(
    r"(?:\b(?P<full_month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(?P<f_day>\d{1,2})(?:st|nd|rd|th)?(?:,\s*(?P<f_year>20\d{2}|19\d{2}))?\b"
    r"|\b(?:(?P<ab_prep>on|since|from|until|by|before|after|around)\s+)?(?P<ab_month>Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+"
    r"(?P<ab_day>\d{1,2})(?:(?P<ab_ord>st|nd|rd|th)|,\s*(?P<ab_year>20\d{2}|19\d{2}))?\b)",
    re.IGNORECASE,
)
_ISO_OR_SLASH_DATE_RE = re.compile(
    r"(?:\b(?P<iso_y>20\d{2})-(?P<iso_m>0[1-9]|1[0-2])-(?P<iso_d>0[1-9]|[12]\d|3[01])\b"
    r"|\b(?P<sl_pre>on\s+|since\s+|from\s+|around\s+|by\s+)(?P<sl_m>0?[1-9]|1[0-2])/(?P<sl_d>0?[1-9]|[12]\d|3[01])(?:/(?P<sl_y>20\d{2}|\d{2}))?\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SessionInput:
    """Sanitized conversational session input (never contains oracle labels or IDs)."""

    index: int
    raw_date: str
    timestamp: datetime
    turns: tuple[tuple[str, str], ...]  # (role, content)


@dataclass(frozen=True, slots=True)
class ResolvedTemporalAnchor:
    """A resolved inline temporal expression inside a conversational turn."""

    session_index: int
    turn_index: int
    speaker: str
    expression: str
    resolved_date: date
    days_to_query_date: int
    note: str
    snippet: str


@dataclass(frozen=True, slots=True)
class CompiledMemoryPlan:
    """Output of multi-granularity retrieval and deterministic context compilation."""

    ranked_session_indices: list[int]
    core_session_indices: list[int]
    extended_session_indices: list[int]
    chunks: dict[int, list[int]]
    compiled_history_text: str
    temporal_anchors: list[ResolvedTemporalAnchor]
    premise_alert: str | None


def _parse_num_word(raw: str) -> int | None:
    cleaned = " ".join(raw.lower().split())
    if cleaned.isdigit():
        return int(cleaned)
    if cleaned.startswith("a couple"):
        return 2
    return _NUMBER_WORDS.get(cleaned)


def _shift_months(base: date, months_delta: int) -> date:
    total_m = (base.year * 12 + (base.month - 1)) + months_delta
    y, m0 = divmod(total_m, 12)
    m = m0 + 1
    max_d = calendar.monthrange(y, m)[1]
    return date(y, m, min(base.day, max_d))


def _format_date_with_wd(d: date) -> str:
    return f"{d.isoformat()} ({_WEEKDAY_ABBR[d.weekday()]})"


def _format_days_to_current(target: date, query_date: date) -> str:
    diff = (query_date - target).days
    if diff == 0:
        return "0 days (same date as Current Date)"
    if diff > 0:
        weeks, rem = divmod(diff, 7)
        if weeks >= 1:
            w_part = f"{weeks}w" if rem == 0 else f"{weeks}w {rem}d"
            return f"{diff} days before Current Date ({w_part})"
        return f"{diff} day{'s' if diff != 1 else ''} before Current Date"
    ahead = -diff
    return f"{ahead} day{'s' if ahead != 1 else ''} after Current Date"


def _rounds_of_turns(turns: Sequence[tuple[str, str]]) -> list[list[int]]:
    rounds: list[list[int]] = []
    for idx, (role, _) in enumerate(turns):
        if role == "user" or not rounds:
            rounds.append([idx])
        else:
            rounds[-1].append(idx)
    return rounds


def _snippet_around(text: str, start: int, end: int, radius: int = 75) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    s = " ".join(text[lo:hi].split())
    if lo > 0:
        s = "..." + s
    if hi < len(text):
        s = s + "..."
    return s


def resolve_inline_temporal_expressions(
    text: str,
    *,
    session_index: int,
    turn_index: int,
    speaker: str,
    anchor_date: date,
    query_date: date,
) -> list[ResolvedTemporalAnchor]:
    """Deterministically resolve relative and explicit calendar expressions inside a turn."""
    if not text:
        return []
    if len(text) > 12000:
        text = text[:12000]
    found: list[ResolvedTemporalAnchor] = []
    seen_keys: set[tuple[str, date]] = set()

    def _add(expr: str, res_d: date, note: str, span: tuple[int, int]) -> None:
        key = (expr.lower().strip(), res_d)
        if key in seen_keys:
            return
        seen_keys.add(key)
        found.append(
            ResolvedTemporalAnchor(
                session_index=session_index,
                turn_index=turn_index,
                speaker=speaker,
                expression=expr.strip(),
                resolved_date=res_d,
                days_to_query_date=(query_date - res_d).days,
                note=note,
                snippet=_snippet_around(text, span[0], span[1]),
            )
        )

    for m in _YESTERDAY_TOMORROW_RE.finditer(text):
        kw = " ".join(m.group("kw").lower().split())
        if kw == "yesterday":
            d = anchor_date - timedelta(days=1)
        elif kw == "the day before yesterday":
            d = anchor_date - timedelta(days=2)
        elif kw == "tomorrow":
            d = anchor_date + timedelta(days=1)
        else:
            d = anchor_date + timedelta(days=2)
        _add(m.group(0), d, f"relative to {_format_date_with_wd(anchor_date)}", m.span())

    for m in _REL_AGO_RE.finditer(text):
        n = _parse_num_word(m.group("num"))
        if n is None or n <= 0 or n > 3650:
            continue
        unit = m.group("unit").lower()
        if unit.startswith("day"):
            d = anchor_date - timedelta(days=n)
        elif unit.startswith("week"):
            d = anchor_date - timedelta(days=7 * n)
        elif unit.startswith("month"):
            d = _shift_months(anchor_date, -n)
        else:
            d = _shift_months(anchor_date, -12 * n)
        _add(m.group(0), d, f"{n} {unit} before {_format_date_with_wd(anchor_date)}", m.span())

    for m in _REL_AHEAD_RE.finditer(text):
        raw_n = m.group("in_num") or m.group("lat_num") or ""
        unit = (m.group("in_unit") or m.group("lat_unit") or "").lower()
        n = _parse_num_word(raw_n)
        if n is None or n <= 0 or n > 3650 or not unit:
            continue
        if unit.startswith("day"):
            d = anchor_date + timedelta(days=n)
        elif unit.startswith("week"):
            d = anchor_date + timedelta(days=7 * n)
        elif unit.startswith("month"):
            d = _shift_months(anchor_date, n)
        else:
            d = _shift_months(anchor_date, 12 * n)
        _add(m.group(0), d, f"{n} {unit} after {_format_date_with_wd(anchor_date)}", m.span())

    for m in _LAST_NEXT_WEEKDAY_RE.finditer(text):
        mod = " ".join(m.group("mod").lower().split())
        wd_name = m.group("wd")
        target_wd = _WEEKDAY_MAP[wd_name.lower()]
        if mod in {"last", "this past"}:
            days_back = (anchor_date.weekday() - target_wd) % 7
            if days_back == 0:
                days_back = 7
            d = anchor_date - timedelta(days=days_back)
            _add(
                m.group(0),
                d,
                f"preceding {wd_name} before {_format_date_with_wd(anchor_date)}",
                m.span(),
            )
        else:
            days_fwd = (target_wd - anchor_date.weekday()) % 7
            if days_fwd == 0:
                days_fwd = 7
            d = anchor_date + timedelta(days=days_fwd)
            _add(
                m.group(0),
                d,
                f"upcoming {wd_name} after {_format_date_with_wd(anchor_date)}",
                m.span(),
            )

    for m in _ON_WEEKDAY_RE.finditer(text):
        if speaker != "user":
            continue
        wd_name = m.group("wd")
        target_wd = _WEEKDAY_MAP[wd_name.lower()]
        ctx_before = text[max(0, m.start() - 50) : m.start()].lower()
        is_future = bool(
            re.search(r"\b(?:will|going\s+to|plan(?:ning)?\s+to|scheduled\s+for|this\s+coming)\b", ctx_before)
        )
        if is_future:
            days_fwd = (target_wd - anchor_date.weekday()) % 7
            d = anchor_date + timedelta(days=days_fwd)
            _add(m.group(0), d, f"upcoming {wd_name} from {_format_date_with_wd(anchor_date)}", m.span())
        else:
            days_back = (anchor_date.weekday() - target_wd) % 7
            if days_back > 0:
                d = anchor_date - timedelta(days=days_back)
                _add(m.group(0), d, f"preceding {wd_name} in week of {_format_date_with_wd(anchor_date)}", m.span())

    for m in _MONTH_NAME_DATE_RE.finditer(text):
        if m.group("full_month"):
            mon_name = m.group("full_month")
            day_num = int(m.group("f_day"))
            yr_raw = m.group("f_year")
        else:
            # Abbreviated month requires a preposition, ordinal suffix, or explicit 4-digit year
            # so OCR chart axis ticks ("Jul 22 Aug 22 Sep 22") are never misparsed as day-of-month.
            if not (m.group("ab_prep") or m.group("ab_ord") or m.group("ab_year")):
                continue
            mon_name = m.group("ab_month")
            day_num = int(m.group("ab_day"))
            yr_raw = m.group("ab_year")
        mon = _MONTH_MAP.get(mon_name.lower().rstrip("."))
        if mon is None or not (1 <= day_num <= 31):
            continue
        if yr_raw:
            yr = int(yr_raw)
        else:
            yr = anchor_date.year
            try:
                try_curr = date(yr, mon, day_num)
                if (try_curr - anchor_date).days > 120:
                    yr -= 1
            except ValueError:
                pass
        try:
            d = date(yr, mon, day_num)
        except ValueError:
            continue
        _add(m.group(0).strip(), d, "explicit calendar date", m.span())

    for m in _ISO_OR_SLASH_DATE_RE.finditer(text):
        if m.group("iso_y"):
            yr, mon, day_num = int(m.group("iso_y")), int(m.group("iso_m")), int(m.group("iso_d"))
            expr = m.group(0)
        else:
            mon, day_num = int(m.group("sl_m")), int(m.group("sl_d"))
            raw_y = m.group("sl_y")
            yr = (int(raw_y) + (2000 if len(raw_y) == 2 else 0)) if raw_y else anchor_date.year
            expr = m.group(0).strip()
        try:
            d = date(yr, mon, day_num)
        except ValueError:
            continue
        _add(expr, d, "explicit date", m.span())

    return found


def extract_query_temporal_windows(question: str, query_date: date) -> list[tuple[date, date]]:
    """Extract target calendar windows ``(start_date, end_date)`` implied by temporal expressions in ``question``."""
    windows: list[tuple[date, date]] = []
    anchors = resolve_inline_temporal_expressions(
        question,
        session_index=0,
        turn_index=0,
        speaker="user",
        anchor_date=query_date,
        query_date=query_date,
    )
    for a in anchors:
        expr_low = a.expression.lower()
        if "week" in expr_low:
            windows.append((a.resolved_date - timedelta(days=3), a.resolved_date + timedelta(days=3)))
        elif "month" in expr_low:
            windows.append((a.resolved_date - timedelta(days=10), a.resolved_date + timedelta(days=10)))
        else:
            # Allow ±1 day tolerance for timezone / off-by-one phrasing around exact day targets
            windows.append((a.resolved_date - timedelta(days=1), a.resolved_date + timedelta(days=1)))

    for m in _LAST_WEEK_MONTH_RE.finditer(question):
        unit = m.group("unit").lower()
        if unit == "week":
            windows.append((query_date - timedelta(days=10), query_date - timedelta(days=4)))
        elif unit == "weekend":
            # Preceding Saturday..Sunday
            days_since_sun = (query_date.weekday() - 6) % 7
            last_sun = query_date - timedelta(days=days_since_sun or 7)
            windows.append((last_sun - timedelta(days=1), last_sun))
        elif unit == "month":
            prev_m = _shift_months(query_date, -1)
            last_d = calendar.monthrange(prev_m.year, prev_m.month)[1]
            windows.append((date(prev_m.year, prev_m.month, 1), date(prev_m.year, prev_m.month, last_d)))
    return windows


def _query_content_stems(query: str) -> set[str]:
    base_toks = [t for t in tokenize(query) if len(t) >= 2 and not t.isdigit()]
    stems: set[str] = set()
    for t in base_toks:
        st = _stem_passage_token(t)
        if st and st not in _STOP_QUERY_STEMS and len(st) >= 3:
            stems.add(st)
            for exp in TAXONOMIC_EXPANSIONS.get(t, ()):
                stems.add(_stem_passage_token(exp))
            for exp in TAXONOMIC_EXPANSIONS.get(st, ()):
                stems.add(_stem_passage_token(exp))
    return stems


def sanitize_sessions(
    raw_sessions: Sequence[Sequence[Mapping[str, Any]]],
    raw_dates: Sequence[str],
    parsed_timestamps: Sequence[datetime],
) -> list[SessionInput]:
    """Strip any non-(role, content) fields so oracle metadata can never enter the compiler."""
    if not (len(raw_sessions) == len(raw_dates) == len(parsed_timestamps)):
        raise ValueError("sessions, raw_dates, and parsed_timestamps must have identical length")
    out: list[SessionInput] = []
    for idx, (sess, rdate, ts) in enumerate(zip(raw_sessions, raw_dates, parsed_timestamps, strict=True)):
        clean_turns: list[tuple[str, str]] = []
        for turn in sess:
            role = str(turn.get("role") or "user").strip()
            content = str(turn.get("content") or "")
            clean_turns.append((role, content))
        ts_utc = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
        out.append(
            SessionInput(
                index=idx,
                raw_date=str(rdate),
                timestamp=ts_utc,
                turns=tuple(clean_turns),
            )
        )
    return out


class MemoryContextCompiler:
    """Multi-granularity + temporal-coordinate conversational retriever and memory compiler."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: Reranker | None = None,
        core_top_k: int = 6,
        extended_max_extra: int = 10,
        extended_token_budget: int = 11500,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.reranker = reranker
        self.core_top_k = max(1, int(core_top_k))
        self.extended_max_extra = max(0, int(extended_max_extra))
        self.extended_token_budget = max(0, int(extended_token_budget))
        self._premise_verifier = PremiseConsistencyVerifier()

    def rank_sessions_and_rounds(
        self,
        question: str,
        evaluated_at: datetime,
        sessions: Sequence[SessionInput],
        *,
        preloaded_engine: LocalMemoryEngine | None = None,
        preloaded_cid_to_index: Mapping[str, int] | None = None,
        tenant_id: str = "compiler:session",
    ) -> tuple[list[int], dict[int, list[int]], dict[int, float]]:
        """Rank sessions using dense/pipeline + multi-granularity BM25 + temporal coordinate matching."""
        if not sessions:
            return [], {}, {}

        eval_utc = (
            evaluated_at.replace(tzinfo=UTC)
            if evaluated_at.tzinfo is None
            else evaluated_at.astimezone(UTC)
        )
        query_d = eval_utc.date()

        valid_sessions: list[SessionInput] = []
        full_texts: list[str] = []
        for sess in sessions:
            full_text = "\n".join(f"{r}: {c}" for r, c in sess.turns)
            if not full_text:
                continue
            valid_sessions.append(sess)
            full_texts.append(full_text)

        if not valid_sessions:
            return [], {}, {}

        fused_scores: dict[int, float] = {s.index: 0.0 for s in valid_sessions}

        emb_provider = self.embedding_provider or HashingEmbeddingProvider()
        is_hashing = isinstance(emb_provider, HashingEmbeddingProvider)

        if is_hashing:
            # Pure-CPU mode: anchor on Mnemosyne's full RetrievalPipeline (HippoRAG-2 PassageGraph,
            # spreading activation, taxonomic expansion, facet diversification, temporal bucket spread)
            eng = preloaded_engine
            cid_map: dict[str, int] = dict(preloaded_cid_to_index or {})
            if eng is None:
                eng = LocalMemoryEngine(
                    policy=OperatingPolicy(top_k=max(24, len(valid_sessions)), token_budget=262_144)
                )
                cid_map = {}
                for sess, full_text in zip(valid_sessions, full_texts, strict=True):
                    cid = eng.append_evidence(
                        Evidence(
                            tenant_id=tenant_id,
                            user_id="user",
                            actor="user",
                            source_type="conversation:session",
                            source_identity=f"sess-{sess.index}",
                            content=full_text,
                            created_at=sess.timestamp,
                            access_policy={"tenant": tenant_id},
                        )
                    )
                    cid_map.setdefault(cid, sess.index)
            pipe_res = eng.retrieve(
                question,
                tenant_id=tenant_id,
                filt={
                    "role": "reader",
                    "evaluated_at": eval_utc.isoformat(),
                    "query_timezone": "UTC",
                    "query_mode": "passages",
                },
                record_access=False,
            )
            seen_s: set[int] = set()
            rank_p = 0
            for h in pipe_res.hits:
                s_idx = cid_map.get(h.id)
                if s_idx is not None and s_idx not in seen_s:
                    seen_s.add(s_idx)
                    rank_p += 1
                    fused_scores[s_idx] += 0.72 * (1.0 / (16.0 + rank_p)) + 0.015 * max(0.0, float(h.score))
            bm25_rrf_w = 0.10
            user_rrf_w = 0.12
            mg_rrf_w = 0.06
        else:
            # Neural dense mode: fast QuantizedVectorIndex scan over dense embeddings
            q_vec = embed_query(emb_provider, question)
            embed_many_fn = getattr(emb_provider, "embed_many", None)
            if callable(embed_many_fn):
                doc_vecs = embed_many_fn(full_texts)
            else:
                doc_vecs = [emb_provider.embed(t) for t in full_texts]

            if np is not None:
                from mnemosyne.quantized_vectors import QuantizedVectorIndex

                q_index = QuantizedVectorIndex.from_vectors(
                    [str(s.index) for s in valid_sessions],
                    np.asarray(doc_vecs, dtype=np.float32),
                )
                dense_ranked = q_index.search(q_vec, k=len(valid_sessions), mode="auto", min_score=-1.0)
            else:
                from mnemosyne.text import cosine

                dense_ranked = sorted(
                    ((str(s.index), float(cosine(q_vec, v))) for s, v in zip(valid_sessions, doc_vecs, strict=True)),
                    key=lambda pair: (-pair[1], pair[0]),
                )
            for rank, (sid_str, d_score) in enumerate(dense_ranked, 1):
                s_idx = int(sid_str)
                fused_scores[s_idx] += 0.72 * (1.0 / (20.0 + rank)) + 0.038 * max(0.0, d_score)
            bm25_rrf_w = 0.12
            user_rrf_w = 0.10
            mg_rrf_w = 0.06

        # Channel 2: Whole-session + multi-granularity PassageIndex
        p_index = PassageIndex(
            full_texts, session_ids=[str(s.index) for s in valid_sessions]
        )
        sess_bm25 = p_index.scores(question)
        bm25_ranked = sorted(
            ((valid_sessions[pos].index, sc) for pos, sc in sess_bm25.items() if sc > 0),
            key=lambda item: (-item[1], item[0]),
        )
        for rank, (s_idx, _) in enumerate(bm25_ranked, 1):
            fused_scores[s_idx] += bm25_rrf_w * (1.0 / (20.0 + rank))

        # Channel 3: Pure user-turns-only BM25 (eliminates assistant-length dilution on side-remarks)
        user_docs = [
            (sess.index, "\n".join(c for r, c in sess.turns if r == "user" and c.strip()))
            for sess in valid_sessions
        ]
        user_docs = [(idx, txt) for idx, txt in user_docs if txt]
        if user_docs:
            u_index = PassageIndex(
                [txt for _, txt in user_docs],
                session_ids=[str(idx) for idx, _ in user_docs],
            )
            u_scores = u_index.scores(question)
            u_ranked = sorted(
                ((user_docs[pos][0], sc) for pos, sc in u_scores.items() if sc > 0),
                key=lambda item: (-item[1], item[0]),
            )
            for rank, (s_idx, _) in enumerate(u_ranked, 1):
                fused_scores[s_idx] += user_rrf_w * (1.0 / (18.0 + rank))

        mg = p_index.multi_granularity_scores(question, alpha=0.65, beta=0.35)
        mg_ranked = sorted(
            (
                (valid_sessions[pos].index, float(info.get("fused_score", 0.0)))
                for pos, info in mg.items()
                if float(info.get("fused_score", 0.0)) > 0
            ),
            key=lambda item: (-item[1], item[0]),
        )
        for rank, (s_idx, _) in enumerate(mg_ranked, 1):
            fused_scores[s_idx] += mg_rrf_w * (1.0 / (20.0 + rank))

        # Track best round indices per session for Tier-2 windowing
        best_rounds_by_sess: dict[int, list[int]] = {}
        for pos, info in mg.items():
            s_idx = valid_sessions[pos].index
            br = info.get("best_round_index")
            if isinstance(br, int) and br >= 0:
                best_rounds_by_sess[s_idx] = [br]

        # Facet sub-queries for multi-entity comparisons ('A' vs 'B')
        facets = _extract_query_facets(question)
        if len(facets) >= 2:
            for facet in facets[:4]:
                facet_q = (
                    facet
                    if isinstance(facet, str)
                    else " ".join(sorted(str(tok) for tok in facet))
                ).strip()
                if not facet_q:
                    continue
                f_mg = p_index.multi_granularity_scores(facet_q)
                f_ranked = sorted(
                    (
                        (
                            valid_sessions[pos].index,
                            float(info.get("fused_score", 0.0)),
                            info.get("best_round_index"),
                        )
                        for pos, info in f_mg.items()
                        if float(info.get("fused_score", 0.0)) > 0
                    ),
                    key=lambda item: (-item[1], item[0]),
                )[:8]
                for rank, (s_idx, _, br) in enumerate(f_ranked, 1):
                    fused_scores[s_idx] += 0.06 * (1.0 / (15.0 + rank))
                    if isinstance(br, int) and br >= 0:
                        cur = best_rounds_by_sess.setdefault(s_idx, [])
                        if br not in cur:
                            cur.append(br)

        # Channel 4: Topically-Gated Temporal Coordinate Tie-Break!
        # Boosts only topically plausible sessions whose timestamp or inline user event date matches
        # a relative/explicit date window in the question (never promoting unrelated same-day filler).
        q_windows = extract_query_temporal_windows(question, query_d)
        if q_windows and fused_scores:
            top_base = max(fused_scores.values())
            temporal_matches: list[tuple[int, int]] = []
            for sess in valid_sessions:
                if fused_scores.get(sess.index, 0.0) < 0.42 * top_base:
                    continue
                s_date = sess.timestamp.date()
                best_dist: int | None = None
                for lo_d, hi_d in q_windows:
                    if lo_d <= s_date <= hi_d:
                        mid_d = lo_d + (hi_d - lo_d) // 2
                        dist = abs((s_date - mid_d).days)
                        best_dist = dist if best_dist is None else min(best_dist, dist)
                for ti, (role, content) in enumerate(sess.turns):
                    if role != "user" or not content:
                        continue
                    for anc in resolve_inline_temporal_expressions(
                        content,
                        session_index=sess.index,
                        turn_index=ti,
                        speaker=role,
                        anchor_date=s_date,
                        query_date=query_d,
                    ):
                        for lo_d, hi_d in q_windows:
                            if lo_d <= anc.resolved_date <= hi_d:
                                mid_d = lo_d + (hi_d - lo_d) // 2
                                dist = abs((anc.resolved_date - mid_d).days)
                                best_dist = dist if best_dist is None else min(best_dist, dist)
                if best_dist is not None:
                    temporal_matches.append((best_dist, sess.index))

            temporal_matches.sort(key=lambda pair: (pair[0], -fused_scores.get(pair[1], 0.0), pair[1]))
            for rank, (dist, s_idx) in enumerate(temporal_matches[:3], 1):
                exact_bonus = 0.0045 if dist == 0 else 0.0025
                fused_scores[s_idx] += 0.04 * (1.0 / (12.0 + rank)) + exact_bonus

        # Optional Reranker hook when explicitly provided
        if self.reranker is not None:
            prelim = sorted(fused_scores, key=lambda idx: (-fused_scores[idx], idx))[:24]
            sess_by_idx = {s.index: s for s in valid_sessions}
            ce_hits: list[Hit] = []
            for s_idx in prelim:
                sess = sess_by_idx[s_idx]
                u_lines = " | ".join(c.strip() for r, c in sess.turns if r == "user" and c.strip())[:1000]
                ce_hits.append(
                    Hit(
                        id=str(s_idx),
                        kind="evidence",
                        tenant_id="compiler",
                        branch="main",
                        text=u_lines or "empty",
                        score=fused_scores[s_idx],
                        channel="hybrid",
                        provenance=[str(s_idx)],
                    )
                )
            try:
                reranked = self.reranker.rerank(question, ce_hits, k=len(ce_hits))
                for rank, rh in enumerate(reranked, 1):
                    fused_scores[int(rh.id)] += 0.10 * (1.0 / (18.0 + rank))
            except Exception:
                pass

        # State-update recency tie-breaker
        if _STATE_UPDATE_CUE_RE.search(question) and valid_sessions:
            max_sc = max(fused_scores.values())
            sess_by_idx = {s.index: s for s in valid_sessions}
            min_ts = min(s.timestamp.timestamp() for s in valid_sessions)
            span_ts = max(1.0, max(s.timestamp.timestamp() for s in valid_sessions) - min_ts)
            for s_idx, sc in list(fused_scores.items()):
                if sc >= 0.45 * max_sc:
                    rec_frac = (sess_by_idx[s_idx].timestamp.timestamp() - min_ts) / span_ts
                    fused_scores[s_idx] = sc + 0.0025 * rec_frac

        ranked_indices = sorted(fused_scores, key=lambda idx: (-fused_scores[idx], idx))
        return ranked_indices, best_rounds_by_sess, fused_scores

    def select_compiled_turn_windows(
        self,
        question: str,
        sessions: Sequence[SessionInput],
        ranked_indices: Sequence[int],
        top_rounds_map: Mapping[int, Sequence[int]],
        fused_scores: Mapping[int, float],
    ) -> tuple[list[int], list[int], dict[int, list[int]]]:
        """Select Tier-1 full core sessions + Tier-2 extended user+matched-round windows."""
        sess_by_idx = {s.index: s for s in sessions}
        core = [idx for idx in ranked_indices[: self.core_top_k] if idx in sess_by_idx]
        chunks: dict[int, list[int]] = {
            idx: list(range(len(sess_by_idx[idx].turns))) for idx in core
        }

        if self.extended_max_extra <= 0 or self.extended_token_budget <= 0 or not ranked_indices:
            return core, [], chunks

        top_score = max(fused_scores.get(ranked_indices[0], 0.0), 1e-6)
        is_broad = bool(_MULTI_OR_TEMPORAL_CUE_RE.search(question))
        score_floor = (0.28 if is_broad else 0.34) * top_score
        max_extra = self.extended_max_extra if is_broad else max(5, self.extended_max_extra - 2)

        extended: list[int] = []
        used_tokens = 0
        for idx in ranked_indices[self.core_top_k : self.core_top_k + max_extra + 6]:
            if len(extended) >= max_extra:
                break
            if fused_scores.get(idx, 0.0) < score_floor:
                continue
            sess = sess_by_idx.get(idx)
            if sess is None or not sess.turns:
                continue
            r_groups = _rounds_of_turns(sess.turns)
            matched_r = list(top_rounds_map.get(idx, ()))[:2]
            if not matched_r and r_groups:
                matched_r = [0]

            selected_turns: set[int] = set()
            # Always include 100% of user turns in extended sessions
            for ti, (role, _) in enumerate(sess.turns):
                if role == "user":
                    selected_turns.add(ti)
            # Plus full user+assistant turns for matched rounds and immediate neighbors
            for r_idx in matched_r:
                for neighbor in (r_idx - 1, r_idx, r_idx + 1):
                    if 0 <= neighbor < len(r_groups):
                        selected_turns.update(r_groups[neighbor])

            ordered_t = sorted(selected_turns)
            est_tokens = sum(len(sess.turns[ti][1]) + 28 for ti in ordered_t) // 4 + 24
            if used_tokens + est_tokens > self.extended_token_budget:
                # Even if assistant replies exceed budget, still fit pure user turns if small
                user_only_t = [ti for ti, (role, _) in enumerate(sess.turns) if role == "user"]
                u_est = sum(len(sess.turns[ti][1]) + 28 for ti in user_only_t) // 4 + 24
                if user_only_t and used_tokens + u_est <= self.extended_token_budget:
                    ordered_t = user_only_t
                    est_tokens = u_est
                else:
                    continue
            chunks[idx] = ordered_t
            extended.append(idx)
            used_tokens += est_tokens

        return core, extended, chunks

    def compile_memory(
        self,
        question: str,
        raw_question_date: str,
        evaluated_at: datetime,
        sessions: Sequence[SessionInput],
        *,
        include_digest: bool = True,
        annotate_session_headers: bool = True,
    ) -> CompiledMemoryPlan:
        """Rank, window, and compile structured chronological memory context."""
        eval_utc = (
            evaluated_at.replace(tzinfo=UTC)
            if evaluated_at.tzinfo is None
            else evaluated_at.astimezone(UTC)
        )
        query_d = eval_utc.date()
        ranked_indices, top_rounds_map, fused_scores = self.rank_sessions_and_rounds(
            question, eval_utc, sessions
        )
        core, extended, chunks = self.select_compiled_turn_windows(
            question, sessions, ranked_indices, top_rounds_map, fused_scores
        )

        sess_by_idx = {s.index: s for s in sessions}
        ordered_selected = sorted(
            chunks.keys(),
            key=lambda idx: (sess_by_idx[idx].timestamp, sess_by_idx[idx].raw_date, idx),
        )

        all_anchors: list[ResolvedTemporalAnchor] = []
        raw_user_candidates: list[tuple[datetime, int, int, int, str]] = []
        user_evidence_rows: list[dict[str, str]] = []
        q_stems = _query_content_stems(question)
        top6_set = set(ranked_indices[:6])

        for disp_num, s_idx in enumerate(ordered_selected, 1):
            sess = sess_by_idx[s_idx]
            s_date = sess.timestamp.date()
            turn_indices = chunks[s_idx]
            sess_anchors: list[ResolvedTemporalAnchor] = []
            for ti in turn_indices:
                role, content = sess.turns[ti]
                if not content.strip():
                    continue
                t_stems = {_stem_passage_token(w) for w in tokenize(content)}
                overlap = len(q_stems & t_stems)
                if role == "user":
                    user_evidence_rows.append({"cid": f"s{disp_num}:t{ti}", "content": f"User: {content}"})

                # Extract inline date anchors from top-ranked sessions or query-matching turns (capped at 4/session)
                if (s_idx in top6_set or overlap >= 1) and len(sess_anchors) < 4:
                    anchors = resolve_inline_temporal_expressions(
                        content,
                        session_index=disp_num,
                        turn_index=ti,
                        speaker=role,
                        anchor_date=s_date,
                        query_date=query_d,
                    )
                    for a in anchors:
                        if len(sess_anchors) < 4:
                            sess_anchors.append(a)

                if role == "user":
                    has_num = bool(re.search(r"(?:\$\d+|\b\d+(?:,\d{3})*(?:\.\d+)?\b)", content))
                    if overlap >= 1 or (not q_stems and has_num):
                        clean_u = " ".join(content.split())
                        if len(clean_u) > 520:
                            clean_u = clean_u[:517] + "..."
                        score_u = overlap * 3 + (1 if has_num else 0) + (2 if s_idx in top6_set else 0)
                        raw_user_candidates.append((sess.timestamp, disp_num, overlap, score_u, clean_u))
            all_anchors.extend(sess_anchors)

        # Prefer high-specificity user statements (overlap >= 2 when multi-term query has enough hits)
        strong_user = [
            (ts_u, dn, sc_u, txt_u)
            for ts_u, dn, ov, sc_u, txt_u in raw_user_candidates
            if ov >= 2
        ]
        if len(q_stems) >= 3 and len(strong_user) >= 2:
            user_excerpts = strong_user
        else:
            user_excerpts = [(ts_u, dn, sc_u, txt_u) for ts_u, dn, _, sc_u, txt_u in raw_user_candidates]

        premise_res = self._premise_verifier.verify(question, evidence_rows=user_evidence_rows)
        premise_alert = (
            premise_res.clean_abstention_text
            if (not premise_res.is_consistent and premise_res.abstention_recommended)
            else None
        )

        blocks: list[str] = []
        if include_digest and ordered_selected:
            digest_lines: list[str] = [
                f"### Compiled Memory Index (Current Date: {_format_date_with_wd(query_d)}, Raw: {raw_question_date})",
                "Note: Machine-compiled chronological index of retrieved sessions, exact calendar day deltas, "
                "resolved relative dates, and verbatim [USER] statements. Full session transcripts follow below.",
                "",
                "#### 1. Session Calendar & Exact Elapsed Time to Current Date:",
            ]
            for disp_num, s_idx in enumerate(ordered_selected, 1):
                sess = sess_by_idx[s_idx]
                cal_delta = compute_calendar_delta(eval_utc, sess.timestamp)
                tier_tag = "" if s_idx in core else " [extended user+matched-round window]"
                digest_lines.append(
                    f"- Session {disp_num}: {sess.raw_date} ({_format_date_with_wd(sess.timestamp.date())}) "
                    f"| {_format_days_to_current(sess.timestamp.date(), query_d)} "
                    f"(calendar delta: {cal_delta.delta_days}d / {cal_delta.delta_months}m){tier_tag}"
                )

            if all_anchors:
                sorted_anchors = sorted(
                    all_anchors,
                    key=lambda a: (0 if a.speaker == "user" else 1, a.resolved_date, a.session_index),
                )[:20]
                sorted_anchors.sort(key=lambda a: (a.resolved_date, a.session_index, a.turn_index))
                digest_lines.append("")
                digest_lines.append("#### 2. Resolved Inline Dates & Relative Time Expressions (Chronological by Event Date):")
                for a in sorted_anchors:
                    digest_lines.append(
                        f"- Event Date {_format_date_with_wd(a.resolved_date)} "
                        f"[{_format_days_to_current(a.resolved_date, query_d)}] "
                        f"<- Session {a.session_index} ({a.speaker}) phrase \"{a.expression}\" ({a.note}): {a.snippet}"
                    )

            if user_excerpts:
                if len(user_excerpts) > 22:
                    top_pool = sorted(user_excerpts, key=lambda item: (-item[2], item[0]))[:22]
                else:
                    top_pool = list(user_excerpts)
                top_pool.sort(key=lambda item: (item[0], item[1]))
                digest_lines.append("")
                digest_lines.append(
                    "#### 3. Query-Relevant [USER] Self-Reports (Chronological Oldest -> Most Recent; "
                    "user statements reflect actual user facts over assistant suggestions/estimates):"
                )
                for idx_u, (ts_u, disp_num, _, text_u) in enumerate(top_pool):
                    latest_tag = " [MOST RECENT USER STATEMENT IN INDEX]" if idx_u == len(top_pool) - 1 else ""
                    digest_lines.append(
                        f"- [Session {disp_num} | {ts_u.strftime('%Y-%m-%d %H:%M')} | USER]{latest_tag}: {text_u}"
                    )

            if premise_alert:
                digest_lines.append("")
                digest_lines.append(
                    f"#### 4. Premise Consistency Check:\n- [ALERT]: {premise_alert}"
                )

            blocks.append("\n".join(digest_lines) + "\n")

        for disp_num, s_idx in enumerate(ordered_selected, 1):
            sess = sess_by_idx[s_idx]
            turn_indices = chunks[s_idx]
            turns_payload = [
                {"role": sess.turns[ti][0], "content": sess.turns[ti][1]}
                for ti in turn_indices
            ]
            if annotate_session_headers:
                date_line = (
                    f"{sess.raw_date} "
                    f"[{_format_date_with_wd(sess.timestamp.date())} | "
                    f"{_format_days_to_current(sess.timestamp.date(), query_d)}]"
                )
            else:
                date_line = sess.raw_date
            blocks.append(
                f"\n### Session {disp_num}:\n"
                f"Session Date: {date_line}\n"
                f"Session Content:\n\n{json.dumps(turns_payload)}\n"
            )

        return CompiledMemoryPlan(
            ranked_session_indices=ranked_indices,
            core_session_indices=core,
            extended_session_indices=extended,
            chunks=chunks,
            compiled_history_text="".join(blocks),
            temporal_anchors=all_anchors,
            premise_alert=premise_alert,
        )
