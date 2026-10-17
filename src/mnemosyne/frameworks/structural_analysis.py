"""
Structural analysis (v2 Rule 35) — TOC / chapter hints and exclusions from chunked text.

Deterministic heuristics only (no extra LLM): runs after upload when chunks exist, stored on `books.structural_analysis`.
Used as guidance for framework extraction and for honest §10 coverage notes.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

STRUCTURAL_ANALYSIS_VERSION = 1

_EXCLUSION_PHRASES = (
    "acknowledgment",
    "acknowledgement",
    "about the author",
    "table of contents",
    "contents",
    "index",
    "bibliography",
    "references",
    "notes",
    "copyright",
    "dedication",
)

_CHAPTER_LINE = re.compile(
    r"^\s*(?:chapter|ch\.?)\s+([0-9IVXLC]+|[0-9]+)\s*[.:]?\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DOT_LEADER_TOC = re.compile(
    r"^(.{2,120}?)\s*\.{3,}\s*(\d{1,4})\s*$",
    re.MULTILINE,
)
_NUM_HEADING = re.compile(
    r"^\s*(\d+(?:\.\d+){0,3})\s+([A-Z][^\n]{2,100})\s*$",
    re.MULTILINE,
)


def _sorted_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        chunks or [],
        key=lambda c: (int(c.get("page_number") or 0), int(c.get("chunk_index") or 0)),
    )


def _early_window_text(chunks: List[Dict[str, Any]], max_pages: int = 40) -> Tuple[str, int]:
    """Concatenate text from chunks in early pages; return (text, last_page_included)."""
    parts: List[str] = []
    last_p = 0
    for c in _sorted_chunks(chunks):
        pn = int(c.get("page_number") or 0)
        if pn > max_pages:
            break
        t = (c.get("chunk_text") or "").strip()
        if t:
            parts.append(t)
            last_p = max(last_p, pn)
    return "\n\n".join(parts), last_p


def _detect_toc(early_text: str) -> bool:
    s = early_text[:50000].lower()
    return "table of contents" in s or re.search(r"\bcontents\b", s) is not None


def _chapters_from_dot_toc(early_text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in _DOT_LEADER_TOC.finditer(early_text[:80000]):
        title = m.group(1).strip()
        try:
            pg = int(m.group(2))
        except ValueError:
            continue
        if len(title) < 3 or len(title) > 120:
            continue
        low = title.lower()
        if any(low.startswith(p) for p in ("page ", "chapter ", "part ", "figure ", "table ")):
            continue
        out.append(
            {
                "title": title,
                "start_page": pg,
                "end_page": None,
                "source": "toc_dot_leader",
            }
        )
    # Dedupe by (title, page)
    seen: Set[Tuple[str, int]] = set()
    deduped: List[Dict[str, Any]] = []
    for ch in out:
        k = (ch["title"].lower()[:80], int(ch["start_page"]))
        if k in seen:
            continue
        seen.add(k)
        deduped.append(ch)
    return deduped[:80]


def _chapters_from_heading_lines(early_text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in _CHAPTER_LINE.finditer(early_text[:60000]):
        num, rest = m.group(1), (m.group(2) or "").strip()
        title = f"Chapter {num}: {rest}" if rest else f"Chapter {num}"
        out.append({"title": title[:160], "start_page": None, "end_page": None, "source": "heading_chapter"})
    return out[:40]


def _numbered_section_headings(early_text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in _NUM_HEADING.finditer(early_text[:50000]):
        title = (m.group(2) or "").strip()
        if len(title) < 6:
            continue
        out.append({"title": title[:120], "start_page": None, "end_page": None, "source": "numbered_heading"})
    return out[:50]


def _infer_end_pages(chapters: List[Dict[str, Any]], total_pages: Optional[int]) -> None:
    """Fill end_page from next chapter's start_page - 1 when contiguous."""
    if not chapters:
        return
    sorted_ch = sorted(
        [c for c in chapters if c.get("start_page") is not None],
        key=lambda x: int(x["start_page"]),
    )
    for i, ch in enumerate(sorted_ch):
        sp = int(ch["start_page"])
        nxt = None
        for j in range(i + 1, len(sorted_ch)):
            if sorted_ch[j].get("start_page") is not None:
                nxt = int(sorted_ch[j]["start_page"])
                break
        if nxt is not None and nxt > sp:
            ch["end_page"] = nxt - 1
        elif total_pages and total_pages > sp:
            ch["end_page"] = min(total_pages, sp + 40)


def _suggested_exclusions(early_text: str) -> List[str]:
    found: List[str] = []
    seen: Set[str] = set()
    for line in early_text.splitlines()[:400]:
        t = line.strip()
        if len(t) < 6 or len(t) > 100:
            continue
        low = t.lower()
        for ph in _EXCLUSION_PHRASES:
            if ph in low and low.index(ph) < 15:
                key = ph[:40]
                if key not in seen:
                    seen.add(key)
                    found.append(t[:80])
                break
    return found[:25]


def _quartile_chapters(total_pages: int) -> List[Dict[str, Any]]:
    """Fallback when no TOC: coarse page regions for coverage heuristics."""
    if total_pages < 8:
        return []
    q = max(1, total_pages // 4)
    out: List[Dict[str, Any]] = []
    for i, (a, b) in enumerate([(1, q), (q + 1, 2 * q), (2 * q + 1, 3 * q), (3 * q + 1, total_pages)]):
        out.append(
            {
                "title": f"Book region {i + 1} (pages ~{a}–{b})",
                "start_page": a,
                "end_page": b,
                "source": "quartile_fallback",
            }
        )
    return out


def build_structural_analysis(
    chunks: List[Dict[str, Any]],
    total_pages: Optional[int],
) -> Dict[str, Any]:
    """
    Produce a JSON-serializable structural analysis dict (Rule 35 baseline).

    Does not require embeddings; uses chunk text and optional total_pages from PDF metadata.
    """
    sc = _sorted_chunks(chunks)
    max_chunk_page = 0
    for c in sc:
        try:
            max_chunk_page = max(max_chunk_page, int(c.get("page_number") or 0))
        except (TypeError, ValueError):
            pass
    tp = int(total_pages) if total_pages is not None and str(total_pages).strip() != "" else None
    if tp is None or tp < 1:
        tp = max_chunk_page if max_chunk_page > 0 else None

    early_text, _ = _early_window_text(sc, max_pages=45)
    toc_detected = _detect_toc(early_text)

    chapters = _chapters_from_dot_toc(early_text)
    if not chapters:
        chapters = _chapters_from_heading_lines(early_text)
    if not chapters:
        chapters = _numbered_section_headings(early_text)
    if not chapters and tp:
        chapters = _quartile_chapters(tp)

    if tp:
        _infer_end_pages(chapters, tp)

    exclusions = _suggested_exclusions(early_text)

    return {
        "version": STRUCTURAL_ANALYSIS_VERSION,
        "total_pages": tp,
        "max_page_in_chunks": max_chunk_page or None,
        "toc_detected": toc_detected,
        "chapters": chapters,
        "suggested_exclusions": exclusions,
        "page_numbering_note": (
            "PDF page indices are used as printed pages when no offset is detected; "
            "verify against the physical book if citations must match print edition exactly."
        ),
    }


def parse_structural_analysis(raw: Any) -> Optional[Dict[str, Any]]:
    """Parse DB JSON string or dict into a dict, or None."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw if raw.get("version") or raw.get("chapters") is not None else None
    if isinstance(raw, str) and raw.strip():
        try:
            d = json.loads(raw)
            return d if isinstance(d, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def format_structural_hint_for_extraction(analysis: Dict[str, Any], max_chars: int = 4500) -> str:
    """Compact block appended to the framework extraction prompt (Rule 35 → extractor)."""
    lines: List[str] = [
        "STRUCTURAL ANALYSIS (use as navigation only; extract only from SOURCES below):",
        f"- Detected TOC-like structure: {analysis.get('toc_detected', False)}",
    ]
    tp = analysis.get("total_pages")
    if tp:
        lines.append(f"- Approximate book length: {tp} pages (from upload metadata or chunk span).")
    chs = analysis.get("chapters") or []
    if isinstance(chs, list) and chs:
        lines.append("- Chapter / section titles (approximate start pages when listed):")
        for c in chs[:60]:
            if not isinstance(c, dict):
                continue
            title = (c.get("title") or "").strip()
            if not title:
                continue
            sp, ep = c.get("start_page"), c.get("end_page")
            pg = ""
            if sp is not None:
                pg = f" p.{sp}" + (f"–{ep}" if ep is not None else "")
            lines.append(f"  • {title}{pg}")
    excl = analysis.get("suggested_exclusions") or []
    if isinstance(excl, list) and excl:
        lines.append("- Sections often non-core (skim / lower priority unless sources contradict):")
        for x in excl[:20]:
            if isinstance(x, str) and x.strip():
                lines.append(f"  • {x.strip()[:120]}")
    note = analysis.get("page_numbering_note")
    if isinstance(note, str) and note.strip():
        lines.append(f"- Note: {note.strip()}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n[Structural analysis truncated.]"
    return text


def coverage_note_section_10(
    analysis: Optional[Dict[str, Any]],
    cited_pages: List[int],
    total_pages_meta: Optional[int],
) -> str:
    """§10C narrative: evidence spread + optional chapter-level heuristic when structural analysis exists."""
    if not cited_pages:
        base = "No page numbers were parsed from node `page_ref` fields; citation footprint unknown."
        if analysis:
            base += " Structural analysis (Rule 35) is on file; node citations are still missing."
        return base

    n_cited = len(cited_pages)
    cited_set = set(cited_pages)
    if total_pages_meta and total_pages_meta > 0:
        span = (
            f"Nodes cite **{n_cited}** distinct page numbers; upload metadata reports **{total_pages_meta}** pages "
            f"(citation footprint only—not full topical coverage)."
        )
    else:
        span = (
            f"Nodes cite **{n_cited}** distinct page numbers (upload page total unavailable)."
        )

    if not analysis:
        return span + " _Chapter-level coverage needs a structural-analysis artifact (Rule 35)._"

    chs = analysis.get("chapters") or []
    if not isinstance(chs, list) or not chs:
        return span + " Structural analysis did not yield a chapter list; regional coverage is not mapped."

    regions_hit = 0
    regions_with_pages = 0
    for c in chs:
        if not isinstance(c, dict):
            continue
        sp, ep = c.get("start_page"), c.get("end_page")
        if sp is None:
            continue
        regions_with_pages += 1
        try:
            a, b = int(sp), int(ep) if ep is not None else int(sp)
        except (TypeError, ValueError):
            continue
        if a > b:
            a, b = b, a
        if any(a <= p <= b for p in cited_set):
            regions_hit += 1

    chap_note = (
        f" Chapter/region overlap (Rule 35 heuristic): **{regions_hit}** of **{regions_with_pages or len(chs)}** "
        f"page-bounded regions include at least one cited page."
    )
    return span + chap_note
