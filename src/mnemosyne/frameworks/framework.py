# Phase C: Framework extraction via LangChain (retrieve + Extract + Logic Auditor + Governor).
# Produces node-based structure; Logic Auditor checks for contradictions/gaps; Governor approves.
# Retrieval uses multi-query, multi-bucket approach per docs/retrieval_spec.md.

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import contextvars
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from .definitive_style_markers import (
    FW_EPISTEMIC_BEGIN,
    FW_EPISTEMIC_END,
    fw_heading_marker,
    wrap_fw_block,
)
from .structural_analysis import parse_structural_analysis
from .logic_audit_normalize import normalize_logic_audit_result
from .edge_taxonomy import CORE_RELATION_TYPES, normalize_tension_edges, validate_and_remap_edges
from .field_completion_policy import (
    CONSTRAINT_MITIGATION_GAP_CANONICAL,
    DEFINITION_SOURCE_GAP_CANONICAL,
    OPERATIONAL_TEST_GAP_CANONICAL,
    SOURCE_QUOTE_MAX_WORDS,
    STEP_ACTION_GAP_CANONICAL,
    STEP_DONE_WHEN_GAP_CANONICAL,
    WARNING_SYMPTOMS_GAP_CANONICAL,
    ensure_constraint_mitigation_or_gap,
    ensure_definition_fields_or_gap,
    ensure_step_action_done_when_or_gap,
    ensure_warning_symptoms_or_gap,
    enforce_source_quote_word_limit,
    is_template_acknowledged_gap_sentence,
)
from .placeholder_policy import (
    effective_definition_source,
    effective_done_when,
    effective_mitigation,
    effective_operational_test,
    filter_reference_list_items,
    format_depends_on_display,
    format_requires_display,
    in_practice_has_substance,
    should_omit_highest_risk_or_affects,
    should_omit_optional_prose_block,
)
from .app_config import OPENROUTER_BASE_URL, resolve_model_for_task

log = logging.getLogger(__name__)

# Proper Thinking ran on LangChain. These plain stand-ins keep every one of its call sites
# unchanged and add no dependency: one OpenRouter chat completion per invoke().
VectorStore = Any  # anything with search(book_id, query, top_k) -> [{chunk_id, page_number, chunk_index, text}]


@dataclass
class Document:
    page_content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class SystemMessage:
    role = "system"

    def __init__(self, content: str) -> None:
        self.content = content


class HumanMessage(SystemMessage):
    role = "user"


class _Reply:
    def __init__(self, content: str, response_metadata: Dict[str, Any]) -> None:
        self.content = content
        self.response_metadata = response_metadata


class ChatOpenAI:
    def __init__(self, model: str, max_tokens: int, temperature: float = 0,
                 openai_api_base: str = OPENROUTER_BASE_URL) -> None:
        self.model, self.max_tokens, self.temperature = model, max_tokens, temperature
        self.base = openai_api_base.rstrip("/")

    def invoke(self, messages: List[SystemMessage]) -> _Reply:
        key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        if not key.strip():
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        request = urllib.request.Request(
            self.base + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {key.strip()}", "Content-Type": "application/json"},
        )
        started = datetime.now()
        with urllib.request.urlopen(request, timeout=600) as response:
            data = json.loads(response.read().decode("utf-8"))
        usage = data.get("usage") or {}
        log.info("framework call %s on %s: %.1f s, %s tokens in, %s out", getattr(self, "task", "?"), self.model,
                 (datetime.now() - started).total_seconds(), usage.get("prompt_tokens"), usage.get("completion_tokens"))
        if data.get("error"):
            raise RuntimeError(f"OpenRouter error: {data['error']}")
        choice = (data.get("choices") or [{}])[0]
        return _Reply(
            (choice.get("message") or {}).get("content") or "",
            {"finish_reason": choice.get("finish_reason"), "usage": data.get("usage") or {},
             "model_name": data.get("model")},
        )


def _chat_llm_for_task(task_name: str, max_tokens: int) -> ChatOpenAI:
    llm = ChatOpenAI(
        model=resolve_model_for_task(task_name),
        max_tokens=max_tokens,
        temperature=0,
        openai_api_base=os.getenv("OPENAI_BASE_URL", OPENROUTER_BASE_URL),
    )
    llm.task = task_name
    return llm


def definitive_context_excerpt(
    context: Optional[str],
    content: Optional[str],
    max_len: int = 1500,
) -> str:
    """
    Book excerpt slice for definitive LLM prompts. Full text is stored on the node; prompts cap size.
    When context is longer than max_len, center the window on text that overlaps node content so the
    model sees evidence aligned with the item (not only an unrelated prefix of the page window).
    """
    text = (context or "").strip()
    if not text or len(text) <= max_len:
        return text
    body = (content or "").strip()
    idx = -1
    if len(body) >= 8:
        for needle_len in (min(100, len(body)), min(60, len(body)), min(40, len(body)), min(24, len(body))):
            if needle_len < 8:
                continue
            needle = body[:needle_len]
            pos = text.lower().find(needle.lower())
            if pos != -1:
                idx = pos
                break
    if idx == -1:
        for w in re.findall(r"\w{5,}", body.lower())[:10]:
            pos = text.lower().find(w)
            if pos != -1:
                idx = pos
                break
    if idx == -1:
        return text[:max_len]
    half = max_len // 2
    start = max(0, idx - half)
    if start + max_len > len(text):
        start = max(0, len(text) - max_len)
    return text[start : start + max_len]


# Multi-bucket queries per retrieval_spec.md (bucket_name, query, per_bucket top_k)
FRAMEWORK_RETRIEVAL_BUCKETS: List[Tuple[str, str, int]] = [
    (
        "framework_core",
        "Main definitions, rules, principles, step-by-step processes, methods, constraints, "
        "and warnings described in this book.",
        20,
    ),
    (
        "warnings",
        "Risks, failures, mistakes, warnings, constraints, dangers, pitfalls, and what to avoid discussed in this book.",
        10,
    ),
    (
        "philosophy",
        "Why the approach works; theory, arguments, justification, philosophy, assumptions, and debates in this book.",
        10,
    ),
    (
        "ethics",
        "Ethics, harm, injustice, fairness, responsibility, abuse, misuse, and moral limits in this book.",
        8,
    ),
    (
        "examples",
        "Key examples, case studies, stories, and concrete illustrations of the main ideas in this book.",
        10,
    ),
]

# Sum of per-bucket top_k max = 58; cap merged list after dedupe/sort.
DEFAULT_MAX_FRAMEWORK_CHUNKS = 58
DEFAULT_MAX_CONTEXT_CHARS = 68_000


def retrieve_chunks_for_framework(
    vector_store: VectorStore,
    book_id: int,
    db: Optional[Any] = None,
    max_chunks: int = DEFAULT_MAX_FRAMEWORK_CHUNKS,
    max_context_chars: Optional[int] = DEFAULT_MAX_CONTEXT_CHARS,
    expand_neighbors: bool = True,
) -> List[Document]:
    """
    Multi-query, multi-bucket retrieval for framework extraction (per docs/retrieval_spec.md).
    Runs five bucket queries, deduplicates by chunk_id or (page_number, chunk_index),
    optionally expands with same-page neighbors, then sorts and caps to max_chunks / max_context_chars.
    Returns Document list compatible with existing framework extraction context building.
    """
    # Step 1: Multi-query fetch
    raw_by_bucket: Dict[str, List[Dict[str, Any]]] = {}
    for bucket_name, query, top_k in FRAMEWORK_RETRIEVAL_BUCKETS:
        results = vector_store.search(book_id, query, top_k)
        raw_by_bucket[bucket_name] = [
            {**r, "bucket": bucket_name}
            for r in results
        ]
    total_raw = sum(len(v) for v in raw_by_bucket.values())
    for name, hits in raw_by_bucket.items():
        log.debug("Framework retrieval bucket %s: %s hits", name, len(hits))

    # Merge in bucket order (framework_core first, then warnings, philosophy, ethics, examples)
    # and deduplicate by chunk identity (chunk_id if present, else (page_number, chunk_index))
    seen: Dict[Tuple[Any, ...], bool] = {}
    merged: List[Dict[str, Any]] = []
    for bucket_name, _, _ in FRAMEWORK_RETRIEVAL_BUCKETS:
        for r in raw_by_bucket.get(bucket_name, []):
            chunk_id = r.get("chunk_id")
            page_number = r.get("page_number")
            chunk_index = r.get("chunk_index")
            key = (chunk_id,) if chunk_id is not None else (page_number, chunk_index)
            if key in seen:
                continue
            seen[key] = True
            merged.append(r)
    after_dedup = len(merged)
    log.info(
        "Framework retrieval: raw=%s after_dedup=%s (book_id=%s)",
        total_raw, after_dedup, book_id,
    )

    # Step 3: Optional neighbor expansion (same page, chunk_index ± 1)
    if expand_neighbors and db is not None and merged:
        get_chunks = getattr(db, "get_chunks_by_book_id", None)
        if callable(get_chunks):
            all_chunks = get_chunks(book_id)
            by_key = {(c["page_number"], c["chunk_index"]): c for c in all_chunks}
            existing_keys = {(r.get("page_number"), r.get("chunk_index")) for r in merged}
            to_append: List[Dict[str, Any]] = []
            for r in merged:
                pn, ci = r.get("page_number"), r.get("chunk_index")
                if pn is None or ci is None:
                    continue
                for delta in (-1, 1):
                    neighbor_key = (pn, ci + delta)
                    if neighbor_key in existing_keys or neighbor_key not in by_key:
                        continue
                    neighbor = by_key[neighbor_key]
                    existing_keys.add(neighbor_key)
                    to_append.append({
                        "chunk_id": neighbor.get("id"),
                        "page_number": neighbor.get("page_number"),
                        "chunk_index": neighbor.get("chunk_index"),
                        "text": neighbor.get("chunk_text", ""),
                        "bucket": "neighbor",
                    })
            merged = merged + to_append
            log.info(
                "Framework retrieval: after_neighbors=%s (added %s)",
                len(merged), len(to_append),
            )
            # Deduplicate again by chunk identity (in case neighbor was already in merged)
            seen2: Dict[Tuple[Any, ...], bool] = {}
            deduped: List[Dict[str, Any]] = []
            for r in merged:
                cid, pn, ci = r.get("chunk_id"), r.get("page_number"), r.get("chunk_index")
                key = (cid,) if cid is not None else (pn, ci)
                if key in seen2:
                    continue
                seen2[key] = True
                deduped.append(r)
            merged = deduped

    # Step 4: Sort by (page_number, chunk_index), trim to max_chunks and optionally max_context_chars
    merged.sort(key=lambda r: (r.get("page_number") or 0, r.get("chunk_index") or 0))
    if len(merged) > max_chunks:
        merged = merged[:max_chunks]
        log.info("Framework retrieval: trimmed to max_chunks=%s", max_chunks)
    if max_context_chars is not None:
        total = 0
        for i, r in enumerate(merged):
            total += len(r.get("text") or "")
            if total > max_context_chars:
                merged = merged[:i]
                log.info("Framework retrieval: trimmed to ~%s chars (max_context_chars=%s)", total - len(r.get("text") or ""), max_context_chars)
                break

    # Step 5: Output as Document list for Stage 1
    docs: List[Document] = []
    for r in merged:
        meta = {
            "page_number": r.get("page_number"),
            "chunk_index": r.get("chunk_index"),
            "book_id": book_id,
        }
        if r.get("chunk_id") is not None:
            meta["chunk_id"] = r["chunk_id"]
        if r.get("bucket") is not None:
            meta["bucket"] = r["bucket"]
        docs.append(
            Document(
                page_content=(r.get("text") or "").strip(),
                metadata=meta,
            )
        )
    return docs


def _lc_message_content_to_str(content: Any) -> str:
    """
    Normalize AIMessage.content to a single string.
    Chat Completions return str; Responses / some models return a list of blocks
    (e.g. [{'type': 'text', 'text': '...'}]), which must not be passed to .strip() directly.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
                elif isinstance(block.get("content"), str):
                    parts.append(block["content"])
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def _raw_nodes_from_llm_response(raw: str) -> List[Dict[str, Any]]:
    """Parse LLM response to extract nodes array; strip markdown fence if present."""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Model returned empty content.")
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1).strip()
    data = json.loads(raw)
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or len(nodes) == 0:
        raise ValueError("Model did not return a non-empty \"nodes\" array.")
    return nodes


def run_framework_extraction(
    vector_store: VectorStore,
    book_id: int,
    name: str,
    max_chunks: Optional[int] = None,
    total_chunks: Optional[int] = None,
    max_completion_tokens: int = 16384,
    db: Optional[Any] = None,
    structural_hint: Optional[str] = None,
    phase4_instructions: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Run framework extraction: multi-bucket retrieval then one LLM call for JSON nodes.
    Returns raw list of node dicts (caller should run _normalize_framework_nodes).
    """
    if max_chunks is None:
        max_chunks = min((total_chunks or DEFAULT_MAX_FRAMEWORK_CHUNKS), DEFAULT_MAX_FRAMEWORK_CHUNKS)

    docs = retrieve_chunks_for_framework(
        vector_store,
        book_id,
        db=db,
        max_chunks=max_chunks,
        max_context_chars=DEFAULT_MAX_CONTEXT_CHARS,
        expand_neighbors=True,
    )

    # Phase 0 instrumentation: confirm what we actually retrieved before the (failing) LLM call.
    # Keep this lightweight; it should not affect behavior.
    try:
        _docs_count = len(docs or [])
        _total_chars = 0
        _bucket_counts: Dict[str, int] = {}
        _page_numbers: set[Any] = set()
        for d in docs or []:
            text = getattr(d, "page_content", "") or ""
            _total_chars += len(text)
            meta = getattr(d, "metadata", {}) or {}
            b = meta.get("bucket")
            if b:
                _bucket_counts[str(b)] = _bucket_counts.get(str(b), 0) + 1
            pn = meta.get("page_number")
            if pn is not None:
                _page_numbers.add(pn)
        _bucket_preview = sorted(_bucket_counts.items(), key=lambda x: (-x[1], x[0]))[:5]
        log.info(
            "Phase 0 debug (after retrieval): book_id=%s name=%s docs=%s total_chars=%s buckets_top=%s pages_count=%s structural_hint_present=%s phase4_instructions_present=%s max_chunks=%s",
            book_id,
            name,
            _docs_count,
            _total_chars,
            _bucket_preview,
            len(_page_numbers),
            bool((structural_hint or "").strip()),
            bool((phase4_instructions or "").strip()),
            max_chunks,
        )
    except Exception as exc:
        log.debug("Phase 0 debug after retrieval failed (non-fatal): %s", exc)

    if not docs:
        log.warning("LangChain framework: no docs for book_id=%s", book_id)
        raise ValueError("Not enough source material to generate a framework.")

    context_lines = []
    for idx, doc in enumerate(docs, 1):
        meta = getattr(doc, "metadata", {}) or {}
        page = meta.get("page_number")
        chunk_index = meta.get("chunk_index")
        bucket = meta.get("bucket")
        text = getattr(doc, "page_content", "") or ""
        header = f"[Source {idx}] Page {page}, Chunk {chunk_index}"
        if bucket:
            header += f" (bucket={bucket})"
        context_lines.append(header)
        context_lines.append(text)
        context_lines.append("")
    context_text = "\n".join(context_lines)
    num_chunks = len(docs)
    max_words = min(400 + 20 * num_chunks, 4000)

    system_prompt = (
        "You are a disciplined reasoning engine. Output ONLY valid JSON, no other text.\n\n"
        "Output a single JSON object with one key: \"nodes\" (array of objects). Each node:\n"
        "- parent_index: null for root section headers, or 0-based index of parent in the nodes array.\n"
        "- sort_order: 0-based order among siblings.\n"
        "- type: one of \"section\", \"definition\", \"principle\", \"step\", \"warning\", \"constraint\", \"case\", \"example\".\n"
        "- title: short label (5–60 characters; e.g. \"Definitions\", \"Step 1: Gather Data\", \"Constraint: Single Source Only\"). "
        "For definition nodes use exactly one term or short phrase per node (one key concept per definition), not multiple terms combined.\n"
        "- content: 1–3 short paragraphs (quote or explanation; you may include brief examples). "
        "Write in clear, regular sentences; do NOT force a \"WHEN/DO/BECAUSE\" template.\n"
        "- page_ref: null or string like \"p.12\" or \"p.12–13\" based on the main supporting source.\n"
        "- depends_on_index: null or 0-based index of another node this logically or procedurally depends on.\n\n"
        "Rules:\n"
        "1) Use ONLY the provided sources. No outside knowledge.\n"
        "2) Always create a small set of top-level section nodes (parent_index=null, type=\"section\") first, such as "
        "\"Definitions\", \"Core Principles\", \"Procedures\", \"Warnings & Pitfalls\", \"Constraints & Assumptions\", "
        "and \"Examples & Cases\". All non-section nodes must have a non-null parent_index.\n"
        "3) Use node types precisely and avoid conflating roles:\n"
        "   - \"definition\" nodes introduce and fix the meaning of terms or distinctions (what X is).\n"
        "   - For definitions only: create exactly ONE node per term or concept. Do NOT combine multiple terms in a single definition.\n"
        "     Example: do NOT create one node titled \"Concept A and Concept B\"; create two separate definition nodes, one per concept, each with its own content and page_ref. Apply this to any combined terms: split into one definition per term.\n"
        "   - \"principle\" nodes state general causal or normative claims (what tends to cause what, or what should be done).\n"
        "   - \"step\" nodes describe concrete actions or procedures (what to do in practice).\n"
        "   - \"case\" / \"example\" nodes are concrete illustrations, case studies, or stories that exemplify a principle or step; use these types for evidence and examples, not for methodological rules. Do not label case content as principle or step.\n"
        "   - \"warning\" / \"constraint\" nodes describe limits, edge cases, and risks; prefer titles prefixed "
        "\"Warning:\" or \"Constraint:\" when the source reads as caution vs required condition (feedback v2 Rule 23).\n"
        "   - \"section\" nodes are purely organizational labels.\n"
        "   Do not mix definitions, principles, steps, and cases inside a single node; create separate nodes instead.\n"
        "4) Order nodes so parents appear before children, and use sort_order to reflect logical reading order among siblings.\n"
        "5) Use sources marked bucket=warnings or bucket=ethics mainly for 'warning' or 'constraint' nodes; use bucket=philosophy "
        "mainly for deep 'principle' and 'constraint' nodes; use bucket=examples to enrich content with concrete cases.\n"
        "6) Use depends_on_index when a step, warning, or constraint clearly relies on a specific principle or step.\n"
        "7) Do NOT include epistemic_type or epistemic_note fields; other agents will add those later.\n"
        "8) Use key terms consistently with their definitions; avoid equivocation, category errors, false equivalences, and "
        "word–concept fallacies (do not infer meaning from a term's wording; use the sources instead).\n"
        "9) Prefer fewer, more informative nodes over many tiny or redundant ones. "
        "Total content across nodes should be under " + str(max_words) + " words."
    )
    hint_block = ""
    if (structural_hint or "").strip():
        hint_block = "\n\n" + structural_hint.strip() + "\n"

    phase4_block = ""
    if (phase4_instructions or "").strip():
        phase4_block = (
            "\n\n---\nPHASE 4 RE-EXTRACTION (mandatory): A prior pass flagged judgment gaps. "
            "Apply the instructions below when structuring nodes and dependencies. "
            "You must still use ONLY the provided excerpts as evidence—do not invent facts.\n\n"
            + (phase4_instructions or "").strip()
            + "\n"
        )

    user_prompt = (
        f"Framework name: {name}\n\n"
        f"Sources ({num_chunks} excerpts, each labeled with page, chunk, and optional bucket such as "
        "framework_core, warnings, philosophy, ethics, examples, neighbor):\n"
        f"{context_text}"
        f"{hint_block}"
        f"{phase4_block}\n"
        "Using ONLY these sources, output valid JSON with a \"nodes\" array following the schema and rules above. "
        "Root section nodes (parent_index: null, type=\"section\") must come first, then their children. "
        "If STRUCTURAL ANALYSIS is provided above, use it only to prioritize reading order and scope—not as a source of facts unless the excerpts support them."
    )

    llm = _chat_llm_for_task("framework_extraction", max_completion_tokens)
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    content = ""
    for attempt in range(2):
        try:
            response = llm.invoke(messages)
        except Exception as e:
            log.exception("LangChain framework LLM invoke failed")
            raise RuntimeError(f"OpenAI call failed: {e}") from e
        content = _lc_message_content_to_str(getattr(response, "content", None))
        if content.strip():
            break
        meta = getattr(response, "response_metadata", None) or {}
        finish_reason = meta.get("finish_reason", "unknown")
        usage = meta.get("usage", {})
        model = meta.get("model_name") or meta.get("model", "unknown")
        log.warning(
            "Framework extraction: empty LLM response (attempt %s) finish_reason=%s model=%s usage=%s",
            attempt + 1,
            finish_reason,
            model,
            usage,
        )
        if attempt == 1:
            raise ValueError(
                "The AI model returned no content. This can happen due to API limits, "
                "content filtering, or transient errors. Please try again in a moment."
            )
    raw_nodes = _raw_nodes_from_llm_response(content)
    log.info("LangChain framework: book_id=%s name=%s nodes=%s", book_id, name, len(raw_nodes))
    return raw_nodes


def framework_summary_from_nodes(nodes: List[Dict[str, Any]]) -> str:
    """Build a readable text summary of nodes (0-based indices). Used when edges not available."""
    lines = []
    for i, n in enumerate(nodes):
        t = n.get("type") or n.get("node_type") or "section"
        title = n.get("title", "")
        content = n.get("content", "")
        page_ref = n.get("page_ref", "")
        lines.append(f"[{i}] {t}: {title}")
        if content:
            lines.append(f"    {content}")
        if page_ref:
            lines.append(f"    (ref: {page_ref})")
        lines.append("")
    return "\n".join(lines)


class FrameworkGraphDigest:
    """
    Phase G2: serialize nodes once per snapshot; slice for each agent without re-walking the node list.

    Point B optimization: epistemic, logic audit, and meta share one digest in run_agents_over_graph.
    Point A: format_scope_framework_block() feeds scope/audience LLMs with full graph context.
    """

    __slots__ = ("nodes", "edges", "_node_block_full")

    def __init__(self, nodes: List[Dict[str, Any]], edges: Optional[List[Dict[str, Any]]] = None) -> None:
        self.nodes = nodes
        self.edges = edges or []
        self._node_block_full: Optional[str] = None

    def _node_block_full_text(self) -> str:
        if self._node_block_full is None:
            lines: List[str] = []
            for i, n in enumerate(self.nodes):
                t = n.get("type") or n.get("node_type") or "section"
                title = n.get("title", "")
                content = n.get("content", "")
                page_ref = n.get("page_ref", "")
                lines.append(f"[{i}] {t}: {title}")
                if content:
                    lines.append(f"    {content}")
                if page_ref:
                    lines.append(f"    (ref: {page_ref})")
                lines.append("")
            self._node_block_full = "\n".join(lines)
        return self._node_block_full

    def slice(
        self,
        node_block_max_chars: Optional[int] = None,
        edge_block_max_chars: Optional[int] = None,
        edge_type_filter: Optional[Set[str]] = None,
        edge_node_filter: Optional[Set[Any]] = None,
    ) -> Tuple[str, str]:
        """Same semantics as build_graph_summary (truncation + filters)."""
        node_block = self._node_block_full_text()
        if node_block_max_chars and len(node_block) > node_block_max_chars:
            node_block = node_block[:node_block_max_chars] + "\n\n[Node block truncated for length.]"

        edge_block = ""
        nodes = self.nodes
        if self.edges and len(self.edges) > 0:
            id_to_idx: Dict[int, int] = {n.get("id"): i for i, n in enumerate(nodes) if n.get("id") is not None}
            id_to_title: Dict[int, str] = {n.get("id"): (n.get("title") or "") for n in nodes if n.get("id") is not None}
            edge_lines: List[str] = []
            for e in self.edges:
                etype = (e.get("edge_type") or "").strip().lower()
                if edge_type_filter is not None and etype not in edge_type_filter:
                    continue
                from_id = e.get("from_node_id")
                to_id = e.get("to_node_id")
                if edge_node_filter is not None and from_id not in edge_node_filter and to_id not in edge_node_filter:
                    continue
                if from_id not in id_to_idx or to_id not in id_to_idx:
                    continue
                from_idx = id_to_idx[from_id]
                to_idx = id_to_idx[to_id]
                from_title = (id_to_title.get(from_id) or "")[:60]
                to_title = (id_to_title.get(to_id) or "")[:60]
                why = (e.get("why") or "").strip()[:200]
                edge_lines.append(f"- Node {from_idx} ({from_title}) -> Node {to_idx} ({to_title}) [{etype}]: {why}")
            edge_block = "\n".join(edge_lines) if edge_lines else ""
            if edge_block_max_chars and len(edge_block) > edge_block_max_chars:
                edge_block = edge_block[:edge_block_max_chars] + "\n\n[Edge block truncated.]"
        return node_block, edge_block

    def format_scope_framework_block(self, node_chars: int = 18000, edge_chars: int = 9000) -> str:
        """Rich graph text for scope / target_audience LLMs when book prose lacks explicit audience lines."""
        nb, eb = self.slice(node_chars, edge_chars, None, None)
        parts: List[str] = [
            "=== FRAMEWORK GRAPH (extracted structure; use for applicability/audience when book text is implicit) ===\n",
            nb,
        ]
        if eb:
            parts.append("\n=== RELATIONSHIPS ===\n")
            parts.append(eb)
        return "".join(parts)


def build_graph_summary(
    nodes: List[Dict[str, Any]],
    edges: Optional[List[Dict[str, Any]]] = None,
    node_block_max_chars: Optional[int] = None,
    edge_block_max_chars: Optional[int] = None,
    edge_type_filter: Optional[set] = None,
    edge_node_filter: Optional[set] = None,
) -> Tuple[str, str]:
    """
    Build node_block and edge_block for agents (per docs/agent_input_spec.md).
    Nodes use 0-based indices. Edges are shown as Node i (from_title) -> Node j (to_title) [type]: why.
    edge_type_filter: include only these edge_type strings. edge_node_filter: include only edges where from_node_id or to_node_id in set.
    Returns (node_block: str, edge_block: str). edge_block is empty if edges is None/empty.
    """
    return FrameworkGraphDigest(nodes, edges).slice(
        node_block_max_chars,
        edge_block_max_chars,
        edge_type_filter,
        edge_node_filter,
    )


# Retrieval queries for intro / audience / scope-of-applicability language (framework-time, one shared gather).
_AUDIENCE_SCOPE_RETRIEVAL_QUERIES: List[str] = [
    "who is this book for intended reader audience",
    "preface introduction foreword how to use this book",
    "assumptions about the reader prerequisites",
]


def gather_excerpts_for_audience_scope(
    vector_store: VectorStore,
    book_id: int,
    db: Any,
    max_chars: int = 11000,
    early_chunk_pages_max: int = 18,
    early_chunk_count_max: int = 28,
) -> str:
    """
    Collect deduplicated book text for target-audience extraction and claimed-scope grounding.
    Combines semantic hits (when embeddings exist) with early chunks by page order.
    """
    seen: set = set()
    pieces: List[str] = []

    def _add_chunk(cid: Any, page: Any, text: str) -> None:
        text = (text or "").strip()
        if len(text) < 40:
            return
        key = (cid, page, text[:80])
        if key in seen:
            return
        seen.add(key)
        label = f"p.{page}" if page is not None else "p.?"
        pieces.append(f"--- Excerpt ({label}) ---\n{text}")

    if db is not None and hasattr(db, "get_embeddings_status") and db.get_embeddings_status(book_id):
        for q in _AUDIENCE_SCOPE_RETRIEVAL_QUERIES:
            try:
                for r in vector_store.search(book_id, q, top_k=5):
                    cid = r.get("chunk_id")
                    page = r.get("page_number")
                    raw_text = (r.get("text") or "").strip()
                    _add_chunk(cid, page, raw_text)
            except Exception as e:
                log.warning("gather_excerpts search failed (%s): %s", q[:40], e)

    if db is not None and hasattr(db, "get_chunks_by_book_id"):
        try:
            all_chunks = db.get_chunks_by_book_id(book_id)
            all_chunks.sort(key=lambda c: (c.get("page_number") or 0, c.get("chunk_index") or 0))
            early_added = 0
            for c in all_chunks:
                pn = c.get("page_number")
                if pn is not None and pn > early_chunk_pages_max:
                    continue
                _add_chunk(c.get("id"), pn, c.get("chunk_text") or "")
                early_added += 1
                if early_added >= early_chunk_count_max:
                    break
        except Exception as e:
            log.warning("gather_excerpts early chunks failed: %s", e)

    out = "\n\n".join(pieces)
    if len(out) > max_chars:
        out = out[:max_chars] + "\n\n[Excerpts truncated for length.]"
    return out


def build_mini_framework_hint(
    nodes: List[Dict[str, Any]],
    name: str,
    max_chars: int = 3200,
    digest: Optional[FrameworkGraphDigest] = None,
) -> str:
    """Short node listing for audience inference when book excerpts lack explicit reader statements."""
    if digest is not None:
        nb, eb = digest.slice(min(max_chars * 2, 9000), 2500, None, None)
        parts: List[str] = [f"Framework name: {name}\n\n", nb]
        if eb:
            parts.append("\n\nRelationships (summary):\n")
            parts.append(eb)
        out = "".join(parts)
        if len(out) > max_chars * 2 + 400:
            out = out[: max_chars * 2 + 400]
        return out
    node_block, _ = build_graph_summary(
        nodes, None, node_block_max_chars=max_chars, edge_block_max_chars=0
    )
    return f"Framework name: {name}\n\n{node_block}"


def _target_audience_placeholder(s: Optional[str]) -> bool:
    t = (s or "").strip().lower()
    if len(t) < 4:
        return True
    return t in (
        "not stated in source",
        "unknown",
        "n/a",
        "not stated",
        "none",
        "n/a.",
    )


def run_extract_target_audience(
    excerpt_block: str,
    book_title: str,
    existing_target_audience: Optional[str],
    framework_hint: str,
    max_tokens: int = 768,
    framework_graph_summary: Optional[str] = None,
) -> Optional[str]:
    """
    One LLM call: target readership. Primary signal: extracted framework graph (Point A); excerpts supplement.

    Returns a string to persist on books.target_audience, or None to keep DB unchanged.
    """
    existing = (existing_target_audience or "").strip()
    ex = (excerpt_block or "").strip()
    fh = (framework_hint or "").strip()
    fgs = (framework_graph_summary or "").strip()
    if not ex and not fh and not fgs:
        return existing if not _target_audience_placeholder(existing) else None

    system = (
        "You determine the book's target audience for library metadata.\n"
        "Output ONLY valid JSON: {\"target_audience\": string|null, \"basis\": string}.\n"
        "basis must be one of: explicit_in_text, inferred_from_intro, inferred_from_framework, none.\n\n"
        "Rules:\n"
        "1) Prefer explicit_in_text when BOOK_EXCERPTS contain explicit who-the-book-is-for language (quote or paraphrase, 1-3 sentences).\n"
        "2) Use inferred_from_intro when BOOK_EXCERPTS imply readers from tone/preface but do not name them literally.\n"
        "3) Use inferred_from_framework when FRAMEWORK_GRAPH / FRAMEWORK_STRUCTURE show who the method is for (steps, cases, principles, "
        "warnings) even if the book never says 'target audience' — infer practitioner type conservatively.\n"
        "4) If FRAMEWORK_GRAPH is provided, it is authoritative for (3) over weak or empty excerpts.\n"
        "5) If you cannot justify (1)-(3), set target_audience to null and basis to none.\n"
        "6) Do not invent demographic details absent from excerpts or framework content.\n"
        "7) Non-null target_audience must be standalone readable prose (not 'see page 5')."
    )
    user_parts = [
        f"BOOK_TITLE: {book_title or '(unknown)'}",
        f"EXISTING_METADATA_AUDIENCE (PDF upload; may be wrong; framework inference may override): {existing or '(empty)'}",
    ]
    if fgs:
        user_parts.append(f"FRAMEWORK_GRAPH (primary for inference when excerpts lack audience language):\n{fgs[:12000]}")
    user_parts.append(f"FRAMEWORK_STRUCTURE_HINT:\n{fh[:4000]}")
    if ex:
        user_parts.append(f"BOOK_EXCERPTS (supplementary grounding):\n{ex[:7000]}")
    else:
        user_parts.append("BOOK_EXCERPTS: (none or minimal — rely on FRAMEWORK_GRAPH when present.)")
    user = "\n\n".join(user_parts)

    data = _llm_json_call(system=system, user=user, max_tokens=max_tokens, task_name="target_audience")
    if not isinstance(data, dict):
        return existing if not _target_audience_placeholder(existing) else None
    ta = data.get("target_audience")
    basis = (data.get("basis") or "").strip().lower()
    if not isinstance(ta, str):
        ta = None
    else:
        ta = ta.strip()
        if not ta or len(ta) < 12:
            ta = None
        elif _target_audience_placeholder(ta):
            ta = None

    if ta:
        if basis in ("explicit_in_text", "inferred_from_intro", "inferred_from_framework"):
            return ta[:600]
        if basis == "none":
            pass
        else:
            return ta[:600]

    return existing if not _target_audience_placeholder(existing) else None


def _build_claimed_scope_draft(
    purpose_txt: str,
    assumptions_txt: str,
    target_audience: str,
    book_title: str,
) -> Optional[str]:
    """Deterministic minimum for claimed applicability: plain prose only (no Source / audience labels)."""
    _ = (book_title or "").strip()  # title stays in book_block for the LLM; not echoed into draft labels
    purpose_txt = (purpose_txt or "").strip()
    assumptions_txt = (assumptions_txt or "").strip()
    ta = (target_audience or "").strip()
    chunks: List[str] = []
    if not _target_audience_placeholder(ta):
        chunks.append(ta[:450].strip().rstrip("."))
    if len(purpose_txt) >= 12:
        chunks.append(purpose_txt[:950].strip().rstrip("."))
    if len(assumptions_txt) >= 12:
        chunks.append(assumptions_txt[:550].strip().rstrip("."))
    if not chunks:
        return None
    out = ". ".join(c for c in chunks if c) + "."
    out = " ".join(out.split())
    return out if len(out) >= 12 else None


def _strip_claimed_scope_labels(text: str) -> str:
    """Remove catalog-style prefixes from stored/model output; keep applicability prose only."""
    t = (text or "").strip()
    if not t or _is_not_stated_scope(t):
        return t
    original = t
    if re.search(r"(?i)Readership\s*/\s*audience\s*:", t):
        tail = re.split(r"(?i)Readership\s*/\s*audience\s*:", t)[-1].strip()
        if tail:
            t = tail
    elif re.match(r"(?is)^Source\s*:\s*", t):
        rest = re.sub(r"(?is)^Source\s*:\s*", "", t, count=1).strip()
        dot_sp = rest.find(". ")
        if dot_sp >= 0:
            t = rest[dot_sp + 2 :].strip()
        else:
            t = ""
    t = re.sub(r"(?i)^(?:Audience|Target\s+audience|Framework\s+purpose|Assumptions\s+and\s+limits)\s*:\s*", "", t)
    t = re.sub(
        r"(?i)\s*(?:Framework\s+purpose|Assumptions\s+and\s+limits)\s*:\s*",
        " ",
        t,
    )
    t = " ".join(t.split()).strip()
    if not t:
        t = re.sub(r"(?is)^Source\s*:\s*", "", original).strip()
        t = " ".join(t.split())
    return t


def _is_not_stated_scope(s: str) -> bool:
    t = (s or "").strip().lower()
    return not t or t == "not stated in source" or t.startswith("not stated")


# Scope strings: single-line, safe for markdown table cells and DB text fields.
_SCOPE_TABLE_MAX_LEN = 1200
_SCOPE_EVIDENCE_SNIPPET = 240

_GARBAGE_EVIDENCE_RE = re.compile(
    r"\[Case\s*Context\]|anything\?\s+For example|o&ered|di&erent|\[Step In Practice Case\]",
    re.IGNORECASE,
)


def sanitize_definitive_scope_text(
    text: str, max_len: int = _SCOPE_TABLE_MAX_LEN, *, sentence_boundary: bool = False
) -> str:
    """
    Normalize claimed/evidenced scope for storage and Overview table cells:
    collapse newlines, strip pipe characters that break markdown tables, trim length.
    If sentence_boundary=True (recommended for Overview scope cells), cut at last full sentence under max_len.
    """
    if not text:
        return ""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = " ".join(t.split())
    t = t.replace("|", " — ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"[-–—]\s*$", "", t).strip()
    if len(t) > max_len:
        if sentence_boundary:
            t = _truncate_scope_at_sentence_boundary(t, max_len)
        else:
            cut = t[:max_len]
            t = cut.rsplit(" ", 1)[0] + "…" if " " in cut else cut + "…"
    return t


def _evidenced_output_unreliable(text: str) -> bool:
    """True if LLM/draft evidenced text is too long, multi-sentence spam, or matches garbage heuristics."""
    if not (text or "").strip():
        return True
    s = text.strip()
    if "\n" in s:
        return True
    if len(s) > 950:
        return True
    if _GARBAGE_EVIDENCE_RE.search(s):
        return True
    # Long rhetorical "what if" book dumps
    if s.lower().count("?") >= 3 and len(s) > 400:
        return True
    if _is_mid_sentence_fragment_body(s[:220]):
        return True
    return False


def _is_mid_sentence_fragment_body(body: str) -> bool:
    """True if text likely starts mid-sentence (bad for evidenced scope sourcing)."""
    s = (body or "").strip()
    if len(s) < 8:
        return True
    if s[0] in ",;'\"(":
        return True
    if re.match(r"^(ing|ed)\s+", s, re.IGNORECASE):
        return True
    if re.match(r"^\$[\d,]", s) or re.match(r"^\d{1,2},\d{3}\b", s):
        return True
    return False


def _snippet_evidence_body(raw: str, max_len: int = _SCOPE_EVIDENCE_SNIPPET) -> str:
    """Short, first-chunk snippet; avoids dumping full In Practice paragraphs."""
    s = " ".join((raw or "").split())
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    # Prefer first sentence if reasonable
    m = re.match(r"^(.{12,}?[.!?])\s", s)
    if m and len(m.group(1)) <= max_len + 40:
        return m.group(1).strip()
    # Skip leading fragment: find first ". " then take following sentence start
    dot = s.find(". ")
    if dot >= 8 and dot + 2 < len(s):
        tail = s[dot + 2 :].lstrip()
        if tail and not _is_mid_sentence_fragment_body(tail[: min(80, len(tail))]):
            m2 = re.match(r"^(.{12,}?[.!?])(?:\s|$)", tail)
            if m2 and len(m2.group(1)) <= max_len + 40:
                return m2.group(1).strip()
            if len(tail) <= max_len:
                return tail
    cut = s[: max_len]
    sp = cut.rfind(" ")
    if sp >= 24:
        return cut[:sp].rstrip() + "…"
    return s[: max_len - 1].rstrip() + "…"


def _filter_evidence_lines_for_scope(raw_lines: List[str]) -> List[str]:
    """Drop placeholder/noisy lines; return short snippets suitable for deterministic evidenced text."""
    out: List[str] = []
    seen: set[str] = set()
    for line in raw_lines:
        if not line or len(line) > 3000:
            continue
        body = line.split("] ", 1)[-1].strip() if "] " in line else line.strip()
        if len(body) < 16:
            continue
        if _GARBAGE_EVIDENCE_RE.search(line) or _GARBAGE_EVIDENCE_RE.search(body):
            continue
        if _is_mid_sentence_fragment_body(body):
            continue
        sn = _snippet_evidence_body(body)
        if len(sn) < 24:
            continue
        if _is_mid_sentence_fragment_body(sn):
            continue
        key = sn[:100].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(sn)
        if len(out) >= 10:
            break
    return out


def _deterministic_evidenced_from_lines(lines: List[str], max_chars: int = 600) -> Optional[str]:
    """
    Build concise evidenced scope from filtered snippets.
    Targets 1-3 short sentences instead of semicolon-heavy dumps.
    """
    snippets = _filter_evidence_lines_for_scope(lines)
    if not snippets:
        return None
    chosen = snippets[:3]
    text = " ".join(chosen)
    text = sanitize_definitive_scope_text(text, max_len=max_chars, sentence_boundary=True)
    if len(text) < 80:
        return None
    return text


_SCOPE_MIN_CLAIMED = 90
_SCOPE_MAX_CLAIMED = 500
_SCOPE_MIN_EVIDENCED = 120
_SCOPE_MAX_EVIDENCED = 600


def _truncate_scope_at_sentence_boundary(text: str, max_len: int) -> str:
    """Trim to max_len without ending mid-phrase: prefer last sentence end (. ! ?) then last space."""
    t = (text or "").strip()
    if not t or len(t) <= max_len:
        return t
    window = t[:max_len]
    best = -1
    for m in re.finditer(r"[.!?](?:\s+|$)", window):
        best = m.end()
    if best >= _SCOPE_MIN_CLAIMED:
        return window[:best].strip()
    sp = window.rfind(" ")
    if sp >= 40:
        return window[:sp].rstrip("-–—") + "…"
    return window.rstrip("-–—") + "…"


def _scope_sentence_count(text: str) -> int:
    s = (text or "").strip()
    if not s:
        return 0
    parts = [p for p in re.split(r"(?<=[.!?])\s+", s) if p.strip()]
    return len(parts)


def _scope_token_overlap_ratio(a: str, b: str) -> float:
    ta = {t for t in re.findall(r"[a-z0-9]{3,}", (a or "").lower())}
    tb = {t for t in re.findall(r"[a-z0-9]{3,}", (b or "").lower())}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(tb))


def _scope_contains_any(text: str, terms: List[str]) -> bool:
    low = (text or "").lower()
    return any(t in low for t in terms)


def _scope_contains_applicability_signal(text: str) -> bool:
    return _scope_contains_any(
        text,
        [
            "audience",
            "entrepreneur",
            "manager",
            "team",
            "organization",
            "startup",
            "company",
            "sector",
            "domain",
            "applies",
            "uncertainty",
            "context",
            "setting",
        ],
    )


def _scope_contains_situation_signal(text: str) -> bool:
    return _scope_contains_any(
        text,
        [
            "situation",
            "context",
            "case",
            "example",
            "when",
            "under",
            "in practice",
            "customers",
            "experiment",
            "mvp",
            "metric",
            "iteration",
        ],
    )


def _validate_claimed_scope(candidate: str, target_audience: str) -> List[str]:
    s = (candidate or "").strip()
    issues: List[str] = []
    if _is_not_stated_scope(s):
        issues.append("not_stated_or_empty")
        return issues
    if len(s) < _SCOPE_MIN_CLAIMED:
        issues.append("too_short")
    if len(s) > _SCOPE_MAX_CLAIMED:
        issues.append("too_long")
    sc = _scope_sentence_count(s)
    if sc < 1 or sc > 3:
        issues.append("sentence_count_out_of_range")
    if _scope_token_overlap_ratio(s, target_audience or "") >= 0.90:
        issues.append("too_similar_to_target_audience")
    if not _scope_contains_applicability_signal(s):
        issues.append("missing_applicability_signal")
    low = s.lower()
    if low.startswith("applicability as reflected") or low.startswith("target audience and applicability"):
        issues.append("fallback_wrapper_phrase")
    if not re.search(r"(?:[.!?]|…)\s*$", s):
        issues.append("incomplete_sentence_ending")
    if re.search(r"[-–—]\s*$", s):
        issues.append("trailing_incomplete_compound")
    return issues


def _validate_evidenced_scope(candidate: str, evidence_lines: List[str]) -> List[str]:
    s = (candidate or "").strip()
    issues: List[str] = []
    if _is_not_stated_scope(s):
        issues.append("not_stated_or_empty")
        return issues
    if len(s) < _SCOPE_MIN_EVIDENCED:
        issues.append("too_short")
    if len(s) > _SCOPE_MAX_EVIDENCED:
        issues.append("too_long")
    sc = _scope_sentence_count(s)
    if sc < 1 or sc > 3:
        issues.append("sentence_count_out_of_range")
    if s.count("\n") > 0:
        issues.append("contains_newline")
    if s.count(";") > 2:
        issues.append("semicolon_list_dump")
    if _evidenced_output_unreliable(s):
        issues.append("shape_unreliable")
    if not _scope_contains_situation_signal(s):
        issues.append("missing_situation_signal")
    if _is_mid_sentence_fragment_body(s[:220]):
        issues.append("evidenced_opens_with_fragment")
    ev_terms = set()
    for ln in _filter_evidence_lines_for_scope(evidence_lines)[:8]:
        ev_terms.update(re.findall(r"[a-z0-9]{4,}", ln.lower()))
    out_terms = set(re.findall(r"[a-z0-9]{4,}", s.lower()))
    overlap = len(ev_terms & out_terms)
    if ev_terms and overlap < 2:
        issues.append("low_evidence_affinity")
    return issues


def _repair_scope_with_llm(
    kind: str,
    candidate: str,
    issues: List[str],
    evidence_block: str,
    book_block: str,
    claimed_draft: str,
    excerpts_user: str,
    max_tokens: int,
) -> Optional[str]:
    if not issues:
        return candidate
    if kind == "claimed":
        system = (
            "You are a strict editor for claimed scope. Fix ONLY formatting/relevance issues while staying faithful to source input.\n"
            "Rules: 1-3 sentences, 90-500 chars, plain applicability prose only. "
            "No labels: 'Source:', 'Readership / audience:', 'Audience:', 'Framework purpose:', etc.\n"
            "Not just target audience copy alone; no boilerplate wrappers.\n"
            "The text MUST end with a complete sentence (. or ! or ?). Never end mid-phrase or with a trailing hyphen "
            "(e.g. not 'Build-Measure-').\n"
            "Do not invent facts. Output JSON only: {\"claimed_scope\": str|null}."
        )
        user = (
            f"BOOK BLOCK:\n{book_block}\n\n"
            f"BOOK_EXCERPTS:\n{excerpts_user}\n\n"
            f"CLAIMED_SCOPE_DRAFT:\n{claimed_draft or '(none)'}\n\n"
            f"CURRENT_CANDIDATE:\n{candidate}\n\n"
            f"VALIDATION_FAILURES:\n- " + "\n- ".join(issues)
        )
        data = _llm_json_call(
            system=system,
            user=user,
            max_tokens=max_tokens,
            task_name="scope_pass",
        ) or {}
        return (data.get("claimed_scope") or "").strip() or None
    system = (
        "You are a strict editor for evidenced scope. Fix ONLY formatting/relevance issues while keeping evidence-grounded meaning.\n"
        "Rules: 1-3 sentences, 120-600 chars, no bullet/list dump, no semicolon chain, situation/context-focused.\n"
        "Start with a proper sentence (capital letter); never begin with mid-sentence fragments (e.g. not 'ing a...').\n"
        "Use evidence lines only; do not invent facts. Output JSON only: {\"evidenced_scope\": str|null}."
    )
    user = (
        f"EVIDENCE LINES:\n{evidence_block}\n\n"
        f"BOOK_EXCERPTS:\n{excerpts_user}\n\n"
        f"CURRENT_CANDIDATE:\n{candidate}\n\n"
        f"VALIDATION_FAILURES:\n- " + "\n- ".join(issues)
    )
    data = _llm_json_call(
        system=system,
        user=user,
        max_tokens=max_tokens,
        task_name="scope_pass",
    ) or {}
    return (data.get("evidenced_scope") or "").strip() or None


# Max chars for framework summary sent to Logic Auditor.
# High limit so the auditor sees the full framework; truncation would lose contradictions/gaps.
_LOGIC_AUDIT_SUMMARY_MAX_CHARS = 50000

# Logic Auditor: check framework for contradictions, gaps, assumptions; split graph vs logic vs hybrid.
_GRAPH_REPAIR_ALLOWED_TYPES = frozenset(t.lower() for t in CORE_RELATION_TYPES)


def finalize_framework_edge_list(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Canonical post-process for stored framework edges: remap forbidden patterns, normalize tension pairs,
    then append inferred uses_definition edges (deduped). Same semantics as BookManager mindmap pipeline.
    """
    e = validate_and_remap_edges(nodes, list(edges or []))
    e = normalize_tension_edges(e)
    inferred = infer_uses_definition_edges(nodes, e)
    if not inferred:
        return e
    seen = {
        (int(x["from_node_id"]), int(x["to_node_id"]), (x.get("edge_type") or "").strip().lower())
        for x in e
        if x.get("from_node_id") is not None and x.get("to_node_id") is not None
    }
    for x in inferred:
        try:
            a, b = int(x["from_node_id"]), int(x["to_node_id"])
        except (TypeError, ValueError, KeyError):
            continue
        et = (x.get("edge_type") or "").strip().lower()
        k = (a, b, et)
        if k in seen:
            continue
        seen.add(k)
        e.append(dict(x))
    return e


def _graph_repair_max_iterations() -> int:
    raw = os.getenv("GRAPH_REPAIR_MAX_ITERATIONS", "2")
    try:
        n = int(raw)
    except ValueError:
        n = 2
    return max(0, min(n, 5))


def _edge_set_signature(edges: List[Dict[str, Any]]) -> frozenset:
    sig: set = set()
    for e in edges or []:
        try:
            a, b = int(e.get("from_node_id")), int(e.get("to_node_id"))
        except (TypeError, ValueError):
            continue
        sig.add((a, b, (e.get("edge_type") or "").strip().lower()))
    return frozenset(sig)


def framework_edge_signature(edges: Optional[List[Dict[str, Any]]]) -> frozenset:
    """Stable frozenset key for comparing edge lists (order-insensitive)."""
    return _edge_set_signature(edges or [])


def _edge_endpoints_match(e: Dict[str, Any], fid: int, tid: int, et: str) -> bool:
    try:
        a, b = int(e.get("from_node_id")), int(e.get("to_node_id"))
    except (TypeError, ValueError):
        return False
    return a == fid and b == tid and (e.get("edge_type") or "").strip().lower() == et


def _apply_graph_edge_operations(
    edges: List[Dict[str, Any]],
    operations: List[Dict[str, Any]],
    valid_ids: Set[int],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = [dict(e) for e in (edges or [])]
    for op in (operations or [])[:45]:
        kind = (op.get("op") or "").strip().lower()
        try:
            fid = int(op.get("from_node_id"))
            tid = int(op.get("to_node_id"))
        except (TypeError, ValueError):
            continue
        if fid not in valid_ids or tid not in valid_ids:
            continue
        et = (op.get("edge_type") or "").strip().lower()
        if et not in _GRAPH_REPAIR_ALLOWED_TYPES:
            continue
        if kind == "remove":
            kept: List[Dict[str, Any]] = []
            for e in out:
                try:
                    ef, eb = int(e.get("from_node_id")), int(e.get("to_node_id"))
                except (TypeError, ValueError):
                    kept.append(e)
                    continue
                if ef == fid and eb == tid and (e.get("edge_type") or "").strip().lower() == et:
                    continue
                kept.append(e)
            out = kept
        elif kind == "add":
            if any(
                _edge_endpoints_match(e, fid, tid, et)
                for e in out
            ):
                continue
            why = op.get("why")
            w = why.strip()[:500] if isinstance(why, str) else None
            out.append({"from_node_id": fid, "to_node_id": tid, "edge_type": et, "why": w})
    return out


def run_graph_edge_repair_llm(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    graph_critical: List[str],
    digest: Optional[FrameworkGraphDigest] = None,
    max_tokens: int = 4096,
) -> Optional[List[Dict[str, Any]]]:
    """
    Propose edge add/remove operations to address graph-only auditor findings.
    Returns a new edge list, or None if the model returns nothing usable.
    """
    if not nodes:
        return None
    valid_ids: Set[int] = set()
    node_lines: List[str] = []
    for n in nodes:
        nid = n.get("id")
        if nid is None:
            continue
        try:
            nid_i = int(nid)
        except (TypeError, ValueError):
            continue
        valid_ids.add(nid_i)
        nt = (n.get("node_type") or n.get("type") or "").strip().lower()
        title = (n.get("title") or "").strip()[:120]
        node_lines.append(f"- id {nid_i} type={nt} title={title!r}")

    if digest is not None:
        _, edge_block = digest.slice(12000, 12000, None, None)
    else:
        _, edge_block = build_graph_summary(nodes, edges, node_block_max_chars=12000, edge_block_max_chars=12000)

    issues_block = ""
    if graph_critical:
        issues_block += "GRAPH CRITICAL:\n" + "\n".join(f"- {s}" for s in graph_critical[:24]) + "\n"

    allowed = ", ".join(sorted(_GRAPH_REPAIR_ALLOWED_TYPES))
    system = (
        "You repair framework graph edges only (not node text). "
        "Given current edges and graph-structure issues, output operations to fix missing/wrong links or types.\n"
        "Allowed edge_type values (lowercase): "
        + allowed
        + ".\n"
        "Operations: only \"add\" or \"remove\". Direction must match taxonomy (e.g. warning→step [warns], "
        "step→step [leads_to], principle→step [implemented_by], step→definition [uses_definition]).\n"
        "Output ONLY valid JSON: { \"operations\": [ { \"op\": \"add\"|\"remove\", \"from_node_id\": int, "
        "\"to_node_id\": int, \"edge_type\": string, \"why\": string } ] }. "
        "Use at most 35 operations; prefer minimal changes."
    )
    user = (
        "NODES:\n"
        + "\n".join(node_lines[:400])
        + "\n\nCURRENT EDGES (from -> to [type]):\n"
        + (edge_block or "(none)")
        + "\n\n"
        + issues_block
        + "\nOutput JSON with operations array (may be empty if no safe fix)."
    )
    data = _llm_json_call(
        system=system,
        user=user,
        max_tokens=max_tokens,
        task_name="graph_edge_repair",
    )
    if not data or not isinstance(data.get("operations"), list):
        return None
    patched = _apply_graph_edge_operations(edges, data["operations"], valid_ids)
    return finalize_framework_edge_list(nodes, patched)


def run_graph_repair_loop(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    digest_factory: Any,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    """
    Re-audit and optionally repair edges when graph bucket reports issues.
    Returns (final_edges, final_logic_audit_dict, graph_repair_meta_dict).
    When GRAPH_REPAIR_MAX_ITERATIONS is 0, runs a single Logic Auditor pass and skips repair attempts.
    """
    max_gr = _graph_repair_max_iterations()
    meta: Dict[str, Any] = {"max_iterations": max_gr, "attempts": []}
    edges_list = list(edges or [])
    audit: Dict[str, Any] = {}

    for attempt in range(max_gr + 1):
        digest = digest_factory(edges_list)
        audit = run_logic_audit(nodes, edges_list, digest=digest)
        if audit.get("approved_graph"):
            meta["attempts"].append({"iteration": attempt + 1, "outcome": "approved_graph"})
            break
        gc = audit.get("graph_critical_issues") or []
        if not gc:
            # e.g. hybrid-only or logic-only findings — edge repair cannot address those
            meta["attempts"].append({"iteration": attempt + 1, "outcome": "no_graph_bucket_findings"})
            break
        if attempt >= max_gr:
            meta["attempts"].append({"iteration": attempt + 1, "outcome": "max_iterations_reached"})
            break
        sig_before = _edge_set_signature(edges_list)
        repaired = run_graph_edge_repair_llm(
            nodes,
            edges_list,
            graph_critical=[str(x) for x in gc],
            digest=digest,
        )
        if not repaired:
            meta["attempts"].append({"iteration": attempt + 1, "outcome": "repair_llm_empty"})
            break
        sig_after = _edge_set_signature(repaired)
        if sig_after == sig_before:
            meta["attempts"].append({"iteration": attempt + 1, "outcome": "no_edge_change"})
            break
        edges_list = repaired
        meta["attempts"].append({"iteration": attempt + 1, "outcome": "edges_updated"})

    audit["graph_repair"] = meta
    return edges_list, audit, meta


# Logic Auditor: check framework for contradictions, gaps, assumptions.
def run_logic_audit(
    nodes: List[Dict[str, Any]],
    edges: Optional[List[Dict[str, Any]]] = None,
    max_completion_tokens: int = 16384,
    digest: Optional[FrameworkGraphDigest] = None,
) -> Dict[str, Any]:
    if digest is not None:
        node_block, edge_block = digest.slice(
            _LOGIC_AUDIT_SUMMARY_MAX_CHARS,
            15000,
            None,
            None,
        )
    else:
        node_block, edge_block = build_graph_summary(
            nodes,
            edges,
            node_block_max_chars=_LOGIC_AUDIT_SUMMARY_MAX_CHARS,
            edge_block_max_chars=15000,
        )
    if len(node_block) >= _LOGIC_AUDIT_SUMMARY_MAX_CHARS:
        log.info(
            "Logic Auditor: node block truncated to %s chars; some content not audited",
            _LOGIC_AUDIT_SUMMARY_MAX_CHARS,
        )
    framework_summary = node_block
    if edge_block:
        framework_summary = framework_summary + "\n\nRelationships (Node i -> Node j [type]):\n" + edge_block
    system_prompt = (
        "You are a Logic Auditor. Classify every finding into exactly one bucket:\n"
        "- GRAPH: wrong/missing edges, wrong edge_type for the node types, direction errors, procedural loop closure "
        "that can be fixed by adding/removing/changing links only (no new node text).\n"
        "- LOGIC: contradictions in node content, unstated assumptions in prose, undefined terms that need new or "
        "clearer definition nodes, terminology misuse, category errors in how ideas are stated.\n"
        "- HYBRID: needs both new/merged nodes or substantive rewrites AND graph changes (e.g. missing concept as node).\n\n"
        "Analyze for: (1) contradictions, (2) gaps, (3) assumptions, (4) terminology/category consistency.\n\n"
        "Reply with valid JSON ONLY, exactly this shape:\n"
        "{ \"graph_critical_issues\": [strings], "
        "\"logic_critical_issues\": [strings], \"logic_warnings\": [strings], "
        "\"hybrid_critical_issues\": [strings], \"hybrid_warnings\": [strings], "
        "\"reasoning_quality_note\": \"optional one-line summary\" }\n\n"
        "Rules: Use [] for empty arrays. Put all graph-structure issues in graph_critical_issues only (no separate graph warnings). "
        "critical_* are serious; warnings are minor. "
        "Do not duplicate the same issue in multiple buckets—pick the best bucket. "
        "Do not invent relation types not used in the Relationships section."
    )
    user_prompt = (
        f"Framework summary (nodes with indices, then relationships):\n{framework_summary}\n\n"
        "Output JSON with graph_critical_issues, logic_*, hybrid_* arrays and optional reasoning_quality_note."
    )
    llm = _chat_llm_for_task("logic_audit", max_completion_tokens)
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    raw = ""
    for attempt in range(2):
        try:
            response = llm.invoke(messages)
        except Exception as e:
            log.exception("Logic Auditor LLM invoke failed")
            raise RuntimeError(f"Logic Auditor failed: {e}") from e
        raw = _lc_message_content_to_str(getattr(response, "content", None)).strip()
        if raw:
            break
        meta = getattr(response, "response_metadata", None) or {}
        finish_reason = meta.get("finish_reason", "unknown")
        usage = meta.get("usage", {})
        model = meta.get("model_name") or meta.get("model", "unknown")
        log.warning(
            "Logic Auditor: empty LLM response (attempt %s) finish_reason=%s model=%s usage=%s",
            attempt + 1,
            finish_reason,
            model,
            usage,
        )
        if attempt == 1:
            log.warning("Logic Auditor: giving up after 2 empty responses, treating as not approved")
            return normalize_logic_audit_result(
                {
                    "logic_critical_issues": ["Logic Auditor returned no response"],
                    "logic_warnings": [],
                }
            )
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        preview = raw[:500] + ("..." if len(raw) > 500 else "")
        log.warning(
            "Logic Auditor returned invalid JSON, treating as not approved. "
            "parse_error=%s raw_preview=%r",
            str(e),
            preview,
        )
        return normalize_logic_audit_result(
            {"logic_critical_issues": ["Audit returned invalid response"], "logic_warnings": []}
        )
    result = normalize_logic_audit_result(data)
    ci = result.get("critical_issues") or []
    gc = len(result.get("graph_critical_issues") or [])
    log.info(
        "Logic Auditor: approved=%s approved_logic=%s approved_graph=%s total_critical=%s graph_crit=%s",
        result.get("approved"),
        result.get("approved_logic"),
        result.get("approved_graph"),
        len(ci),
        gc,
    )
    for i, issue in enumerate(ci, 1):
        log.info("  Logic Auditor critical[%s]: %s", i, issue)
    for i, w in enumerate(result.get("warnings") or [], 1):
        log.info("  Logic Auditor warning[%s]: %s", i, w)
    return result


# Phase 4 (Definitive_System_Feedback_v2 §K judgment + Section III): structured judgment for re-extract loop.
_JUDGMENT_AUDIT_SUMMARY_MAX_CHARS = 32000


def run_judgment_audit(
    nodes: List[Dict[str, Any]],
    edges: Optional[List[Dict[str, Any]]] = None,
    digest: Optional[FrameworkGraphDigest] = None,
    book_meta: Optional[Dict[str, Any]] = None,
    logic_audit_result: Optional[Dict[str, Any]] = None,
    max_completion_tokens: int = 6144,
) -> Dict[str, Any]:
    """
    Judgment-only audit (v2 §K): coverage, proportionality, epistemic fit, redundancy, operational self-test.
    Returns structured fields used by BookManager to optionally re-run extraction with instructions.
    """
    edges_list = edges or []
    if digest is not None:
        node_block, edge_block = digest.slice(
            _JUDGMENT_AUDIT_SUMMARY_MAX_CHARS,
            12000,
            None,
            None,
        )
    else:
        node_block, edge_block = build_graph_summary(
            nodes,
            edges_list,
            node_block_max_chars=_JUDGMENT_AUDIT_SUMMARY_MAX_CHARS,
            edge_block_max_chars=12000,
        )
    framework_summary = node_block
    if edge_block:
        framework_summary = framework_summary + "\n\nRelationships (Node i -> Node j [type]):\n" + edge_block

    sa_snip = ""
    if book_meta:
        raw_sa = book_meta.get("structural_analysis")
        if raw_sa:
            s = str(raw_sa).strip()
            if len(s) > 6000:
                s = s[:6000] + "…"
            sa_snip = f"\n\nBOOK_STRUCTURAL_ANALYSIS (Rule 35, excerpt):\n{s}\n"

    logic_blob = ""
    if logic_audit_result and isinstance(logic_audit_result, dict):
        lar = logic_audit_result
        logic_blob = (
            "\n\nLOGIC_AUDITOR_PRIOR_OUTPUT (for consistency; do not duplicate):\n"
            f"approved: {lar.get('approved')}\n"
            f"approved_logic: {lar.get('approved_logic')}\n"
            f"approved_graph: {lar.get('approved_graph')}\n"
            f"graph_critical_issues: {lar.get('graph_critical_issues')}\n"
            f"logic_critical_issues: {lar.get('logic_critical_issues')}\n"
            f"logic_warnings: {lar.get('logic_warnings')}\n"
            f"hybrid_critical_issues: {lar.get('hybrid_critical_issues')}\n"
            f"hybrid_warnings: {lar.get('hybrid_warnings')}\n"
        )

    system_prompt = (
        "You are the Phase 4 Judgment Auditor (Definitive System Feedback v2, Section K judgment checks). "
        "Mechanical delivery checks are handled elsewhere. Your job is to decide whether the framework graph "
        "warrants a full re-extraction pass with specific instructions for the extractor.\n\n"
        "Consider:\n"
        "- Coverage vs book structure: likely omission of central ideas implied by structural analysis or sparse areas.\n"
        "- Proportionality (Rule 12): Peripheral nodes outweighing Core; lopsided node counts without justification.\n"
        "- Epistemic consistency: ES/EC/CT/CN vs quoted evidence (light check).\n"
        "- Redundancy: warning/constraint pairs with >70% conceptual overlap.\n"
        "- Operational self-test: could a reader execute steps on a novel case from the graph alone? If not, why.\n\n"
        "Reply with valid JSON ONLY, exactly this shape:\n"
        "{ \"warrants_reextract\": bool,\n"
        '  "extractor_instructions": string,\n'
        "  \"findings\": [ string ],\n"
        "  \"coverage_notes\": [ string ],\n"
        "  \"proportionality_notes\": [ string ],\n"
        "  \"epistemic_notes\": [ string ],\n"
        "  \"redundancy_notes\": [ string ],\n"
        "  \"self_test_notes\": [ string ]\n"
        "}\n\n"
        "extractor_instructions: If warrants_reextract is true, give concrete, source-grounded instructions: "
        "which themes/chapters to emphasize, which node types to add or merge, what gaps to fill. "
        "If warrants_reextract is false, use an empty string. "
        "Do not ask the extractor to violate 'only use provided sources'."
    )
    user_prompt = (
        f"{framework_summary}{sa_snip}{logic_blob}\n\n"
        "Output JSON with warrants_reextract, extractor_instructions, findings, and the note arrays "
        "(use [] when none)."
    )
    llm = _chat_llm_for_task("judgment_audit", max_completion_tokens)
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    raw = ""
    response = None
    try:
        for attempt in range(2):
            response = llm.invoke(messages)
            raw = _lc_message_content_to_str(getattr(response, "content", None)).strip()
            if raw:
                break
            meta = getattr(response, "response_metadata", None) or {}
            finish_reason = meta.get("finish_reason", "unknown")
            usage = meta.get("usage", {})
            log.warning(
                "Phase 4 Judgment Auditor: empty response (attempt %s) finish_reason=%s model=%s usage=%s",
                attempt + 1,
                finish_reason,
                meta.get("model_name") or meta.get("model", resolve_model_for_task("judgment_audit")),
                usage,
            )
            if attempt == 1:
                log.warning(
                    "Phase 4 Judgment Auditor: giving up after 2 empty responses",
                )
    except Exception as e:
        log.exception("Phase 4 Judgment Auditor LLM invoke failed: %s", e)
        return {
            "warrants_reextract": False,
            "extractor_instructions": "",
            "findings": [f"Judgment audit failed: {e}"],
            "coverage_notes": [],
            "proportionality_notes": [],
            "epistemic_notes": [],
            "redundancy_notes": [],
            "self_test_notes": [],
        }
    if not raw:
        log.warning("Phase 4 Judgment Auditor: empty response after retries; metadata may be incomplete")
        return {
            "warrants_reextract": False,
            "extractor_instructions": "",
            "findings": ["Phase 4 Judgment Auditor returned no usable response after retries."],
            "coverage_notes": [],
            "proportionality_notes": [],
            "epistemic_notes": [],
            "redundancy_notes": [],
            "self_test_notes": [],
        }
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("Phase 4 Judgment Auditor: invalid JSON (%s)", e)
        return {
            "warrants_reextract": False,
            "extractor_instructions": "",
            "findings": ["Judgment audit returned invalid JSON"],
            "coverage_notes": [],
            "proportionality_notes": [],
            "epistemic_notes": [],
            "redundancy_notes": [],
            "self_test_notes": [],
        }

    def _sl(key: str) -> List[str]:
        v = data.get(key)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    warrants = bool(data.get("warrants_reextract"))
    instr = (data.get("extractor_instructions") or "").strip()
    if warrants and len(instr) < 24:
        log.info("Phase 4: warrants_reextract true but instructions short; disabling re-extract.")
        warrants = False
        instr = ""

    out = {
        "warrants_reextract": warrants,
        "extractor_instructions": instr,
        "findings": _sl("findings"),
        "coverage_notes": _sl("coverage_notes"),
        "proportionality_notes": _sl("proportionality_notes"),
        "epistemic_notes": _sl("epistemic_notes"),
        "redundancy_notes": _sl("redundancy_notes"),
        "self_test_notes": _sl("self_test_notes"),
    }
    log.info(
        "Phase 4 Judgment Auditor: warrants_reextract=%s findings=%s",
        out["warrants_reextract"],
        len(out["findings"]),
    )
    return out


def run_governor_check(audit_result: Dict[str, Any]) -> None:
    """
    Governor: log audit result but do NOT reject. Frameworks are always saved;
    critical_issues and warnings are surfaced in the UI for user visibility.
    """
    if not audit_result.get("approved"):
        log.info("Governor: framework not approved by Logic Auditor logic/hybrid bucket (informational only)")
    if not audit_result.get("approved_graph", True):
        log.info("Governor: graph bucket still has critical findings after repair pass (informational only)")
    critical = audit_result.get("critical_issues") or []
    if critical:
        log.info("Governor: %s total critical issue(s) logged for UI display", len(critical))


# --- Phase 1 agents: Epistemic, Ethics, Meta, Pragmatic (non-blocking) ---


def _text_looks_like_gap_placeholder(s: Any) -> bool:
    """True if value is empty or reads like an acknowledged-gap / not-specified filler."""
    raw = str(s) if s is not None else ""
    if is_template_acknowledged_gap_sentence(raw):
        return False
    sl = raw.strip().lower()
    if not sl:
        return True
    # Template-allowed explicit mitigation (Section 7 / 9C) — not a lazy gap.
    if "no mitigation provided" in sl or "mitigation for this condition" in sl:
        return False
    if sl.startswith("the book does not"):
        return True
    if sl in ("not stated in source", "not stated"):
        return True
    if re.search(
        r"does not specify|not specified|provided excerpt|excerpt does not|no classification",
        sl,
    ):
        return True
    return False


# Phase 1: shared ES/EC/CT/CN + Tag justifications instructions (definitions, principles, steps, warnings, constraints).
EPISTEMIC_TAG_ENUM_PROMPT = (
    "For ES, EC, CT, CN you MUST output exactly one allowed label each (not prose): "
    "ES ∈ {Demonstrated, Argued, Asserted, Assumed}; "
    "EC ∈ {Verbatim, Synthesized, Inferred}; "
    "CT ∈ {Descriptive, Prescriptive, Evaluative}; "
    "CN ∈ {Core, Supporting, Peripheral}. "
    "Infer from how the excerpt presents the content; the book will not name these labels explicitly. "
    'Provide \"Tag justifications\" as one sentence per tag (ES, EC, CT, CN), citing the Source Quote or excerpt. '
    "Do not use placeholder gap wording for these tags or their justifications; use the closest valid label."
)

# Definitive_System_Feedback_v2 — concise contract appended to definitive batch prompts (pre–Phase 4 Workstream B).
_V2_DEF_FIELDS = (
    "\n\nFeedback v2 (Definitions, Rules 14–16): Include Boundary when the excerpt supports it. "
    "Definition Source must be exactly \"Author-defined\" or \"Framework-derived\" when the excerpt supports either; "
    "otherwise set it to EXACTLY this string (verbatim):\n"
    + json.dumps(DEFINITION_SOURCE_GAP_CANONICAL)
    + "\nOperational Test must be checkable from the text; if impossible, set it to EXACTLY:\n"
    + json.dumps(OPERATIONAL_TEST_GAP_CANONICAL)
    + "\n"
)
_V2_REQUIRES_FIELD = (
    "\n\nRule 2 (Requires): Output \"Requires\" as a JSON array of strings. "
    "Each string must be the exact title of another definition from this framework that this term depends on "
    "(logical prerequisite). Use [] if there are no such prerequisites. "
    "Do not use sentences, disclaimers, or \"The book does not specify…\" in \"Requires\" — only titles or [].\n"
)
_V2_STEP_FIELDS = (
    "\n\nFeedback v2 (Steps, Rules 17–20): Action must be imperative; if the excerpt supports no action, set Action to EXACTLY:\n"
    + json.dumps(STEP_ACTION_GAP_CANONICAL)
    + "\nDone When must state observable completion criteria; if unsupported, set to EXACTLY:\n"
    + json.dumps(STEP_DONE_WHEN_GAP_CANONICAL)
    + "\nCommon Mistakes: 2–3 concrete anti-patterns when inferable, else []. In Practice: Outcome must name a metric or state \"qualitative only\".\n"
)
_V2_WARN_FIELDS = (
    "\n\nFeedback v2 (Warnings, Rules 21 & 23): \"Symptoms\" is mandatory (never omit the key). "
    "Prefer a JSON array of 2–4 short strings describing observable signs of the error. "
    "If the excerpt cannot support 2–4 distinct symptoms, set \"Symptoms\" to a one-element array; "
    "the single string must match EXACTLY (verbatim, including punctuation):\n"
    + json.dumps(WARNING_SYMPTOMS_GAP_CANONICAL)
    + "\nUse title wording consistent with prefix \"Warning:\" when the source is a caution (Rule 23).\n"
)
_V2_CONSTRAINT_FIELDS = (
    "\n\nFeedback v2 (Constraints, Rules 22 & 23): Mitigation is mandatory — when the excerpt offers none, "
    "set \"Mitigation\" to EXACTLY (verbatim):\n"
    + json.dumps(CONSTRAINT_MITIGATION_GAP_CANONICAL)
    + "\nUse title wording consistent with prefix \"Constraint:\" when the source is a required condition.\n"
)


def _merge_llm_source_quote_and_epistemic(target: Dict[str, Any], oi: Dict[str, Any]) -> None:
    """Merge optional source_quote + ES/EC/CT/CN + tag_justifications from repair JSON into definitive_fields."""
    sq_in = oi.get("source_quote") or oi.get("Source Quote")
    if isinstance(sq_in, dict):
        q = (sq_in.get("Quote") or "").strip()
        cs = (sq_in.get("Core_Sentence") or sq_in.get("Core Sentence") or "").strip()
        prev_sq = target.get("Source Quote") if isinstance(target.get("Source Quote"), dict) else {}
        prev_q = (prev_sq.get("Quote") or "").strip() if isinstance(prev_sq, dict) else ""
        if q and len(prev_q) < 12:
            target["Source Quote"] = {"Quote": q[:2000], "Core Sentence": cs[:800] if cs else q[:800]}
        elif q and len(prev_q) >= 12 and len(q) > len(prev_q) and len(prev_q) < 24:
            target["Source Quote"] = {
                "Quote": q[:2000],
                "Core Sentence": cs[:800] if cs else (prev_sq.get("Core Sentence") or "")[:800],
            }
    for key in ("ES", "EC", "CT", "CN"):
        v = oi.get(key)
        if isinstance(v, str) and v.strip():
            target[key] = v.strip()[:120]
    tj = oi.get("tag_justifications")
    if isinstance(tj, dict):
        merged = (
            dict(target.get("Tag justifications") or {})
            if isinstance(target.get("Tag justifications"), dict)
            else {}
        )
        for k in ("ES", "EC", "CT", "CN"):
            if isinstance(tj.get(k), str) and tj[k].strip():
                merged[k] = tj[k].strip()[:300]
        if merged:
            target["Tag justifications"] = merged


def run_definition_tag_repair_pass(nodes: List[Dict[str, Any]]) -> None:
    """
    Re-run a focused LLM pass for definitions when the main batch left Source Quote empty/short or
    ES/EC/CT/CN / Tag justifications look like gap placeholders. Uses definition body + context (and
    any existing quote) only—same enum discipline as principles.
    """
    if not nodes:
        return

    def _body_len(n: Dict[str, Any]) -> int:
        return len(((n.get("content") or "") + "\n" + (n.get("context") or "")).strip())

    repair_items: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if (n.get("node_type") or "").strip().lower() != "definition":
            continue
        if _body_len(n) < 40:
            continue
        df = n.get("definitive_fields")
        sq: Dict[str, Any] = {}
        if isinstance(df, dict):
            raw_sq = df.get("Source Quote")
            if isinstance(raw_sq, dict):
                sq = raw_sq
        quote = (sq.get("Quote") or "").strip()
        es = ec = ct = cn = None
        tj: Dict[str, Any] = {}
        if isinstance(df, dict):
            es, ec, ct, cn = df.get("ES"), df.get("EC"), df.get("CT"), df.get("CN")
            tj = df.get("Tag justifications") if isinstance(df.get("Tag justifications"), dict) else {}
        tags_all_gap = all(_text_looks_like_gap_placeholder(x) for x in (es, ec, ct, cn))
        tj_all_gap = all(_text_looks_like_gap_placeholder(tj.get(k)) for k in ("ES", "EC", "CT", "CN"))
        quote_weak = len(quote) < 12
        needs = quote_weak or tags_all_gap or tj_all_gap or not isinstance(df, dict)
        if not needs:
            continue
        repair_items.append(
            {
                "index": i,
                "title": (n.get("title") or "").strip(),
                "definition_body": (n.get("content") or "")[:1500],
                "context": definitive_context_excerpt(n.get("context"), n.get("content")),
                "existing_quote": quote[:500] if quote else "",
            }
        )

    if not repair_items:
        return

    system = (
        "You fill definitive-framework fields for DEFINITIONS using ONLY the provided title, "
        "definition_body, context, and existing_quote (if any).\n"
        "Output JSON only.\n"
        "If existing_quote is empty or too short, set source_quote with Quote (<=60 words, from body/context) "
        "and Core_Sentence (one sentence, must appear inside Quote).\n"
        "If existing_quote is already good, you may omit source_quote or repeat it unchanged.\n"
        "ES must be EXACTLY one of: Demonstrated, Argued, Asserted, Assumed.\n"
        "EC must be EXACTLY one of: Verbatim, Synthesized, Inferred.\n"
        "CT must be EXACTLY one of: Descriptive, Prescriptive, Evaluative.\n"
        "CN must be EXACTLY one of: Core, Supporting, Peripheral.\n"
        "Infer tags from how the definition is presented in the excerpt; the book will not name these labels.\n"
        "tag_justifications: one short sentence per key ES, EC, CT, CN tied to the quote or definition.\n"
        "Do NOT output 'not specified', 'not stated', or 'the book does not specify' for tags or justifications.\n"
        'Schema: { "items": [ { "index": int, '
        '"source_quote": { "Quote": str, "Core_Sentence": str } (optional), '
        '"ES": str, "EC": str, "CT": str, "CN": str, '
        '"tag_justifications": { "ES": str, "EC": str, "CT": str, "CN": str } } ] }'
    )

    def _batch(items: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
        return [items[k : k + size] for k in range(0, len(items), size)]

    for chunk in _batch(repair_items, 5):
        user = f"Definitions to repair:\n{json.dumps(chunk, ensure_ascii=False)}\n\nReturn JSON items only."
        data = _llm_json_call(system=system, user=user, max_tokens=6144)
        if not data or not isinstance(data.get("items"), list):
            continue
        for oi in data["items"]:
            idx = oi.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(nodes):
                continue
            target = nodes[idx].setdefault("definitive_fields", {})
            if not isinstance(target, dict):
                continue
            _merge_llm_source_quote_and_epistemic(target, oi)


def run_principle_tag_repair_pass(nodes: List[Dict[str, Any]]) -> None:
    """
    Re-run a small LLM pass for principles whose Source Quote exists but ES/EC/CT/CN were left as
    'not specified' placeholders. Tags are template enums inferred from Statement + Quote + context.
    """
    if not nodes:
        return

    repair_items: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if (n.get("node_type") or "").strip().lower() != "principle":
            continue
        df = n.get("definitive_fields")
        if not isinstance(df, dict):
            continue
        sq = df.get("Source Quote") if isinstance(df.get("Source Quote"), dict) else {}
        quote = (sq.get("Quote") or "").strip()
        if len(quote) < 12:
            continue
        es, ec, ct, cn = df.get("ES"), df.get("EC"), df.get("CT"), df.get("CN")
        if not all(_text_looks_like_gap_placeholder(x) for x in (es, ec, ct, cn)):
            continue
        repair_items.append(
            {
                "index": i,
                "title": (n.get("title") or "").strip(),
                "statement": (df.get("Statement") or n.get("content") or "")[:1200],
                "quote": quote[:500],
                "context": definitive_context_excerpt(n.get("context"), n.get("content")),
            }
        )

    if not repair_items:
        return

    system = (
        "You assign definitive-framework tags to principles using ONLY the provided Statement, Quote, and context.\n"
        "Output JSON only.\n"
        "ES must be EXACTLY one of: Demonstrated, Argued, Asserted, Assumed (pick the best fit from the quote's epistemic strength).\n"
        "EC must be EXACTLY one of: Verbatim, Synthesized, Inferred.\n"
        "CT must be EXACTLY one of: Descriptive, Prescriptive, Evaluative.\n"
        "CN must be EXACTLY one of: Core, Supporting, Peripheral.\n"
        "Also output tag_justifications: one short sentence per tag key ES, EC, CT, CN citing the quote or statement.\n"
        "Do NOT output 'not specified' or 'the book does not specify'; choose the closest allowed label.\n"
        'Schema: { "items": [ { "index": int, "ES": str, "EC": str, "CT": str, "CN": str, '
        '"tag_justifications": { "ES": str, "EC": str, "CT": str, "CN": str } } ] }'
    )

    def _batch(items: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
        return [items[k : k + size] for k in range(0, len(items), size)]

    for chunk in _batch(repair_items, 6):
        user = f"Principles to tag:\n{json.dumps(chunk, ensure_ascii=False)}\n\nReturn JSON items only."
        data = _llm_json_call(system=system, user=user, max_tokens=4096)
        if not data or not isinstance(data.get("items"), list):
            continue
        for oi in data["items"]:
            idx = oi.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(nodes):
                continue
            target = nodes[idx].setdefault("definitive_fields", {})
            if not isinstance(target, dict):
                continue
            _merge_llm_source_quote_and_epistemic(target, oi)


def run_step_warning_constraint_epistemic_repair_pass(nodes: List[Dict[str, Any]]) -> None:
    """
    Repair Source Quote + ES/EC/CT/CN + Tag justifications for steps, warnings, and constraints when
    the main batch left weak quotes or gap-like tags (same discipline as definitions).
    """
    if not nodes:
        return

    types_ok = frozenset({"step", "warning", "constraint"})

    def _primary_excerpt(n: Dict[str, Any], ntype: str, df: Any) -> str:
        content = (n.get("content") or "").strip()
        ctx = definitive_context_excerpt(n.get("context"), n.get("content"))
        if isinstance(df, dict):
            if ntype == "step":
                bits = [
                    str(df.get("Action") or ""),
                    content,
                    ctx,
                ]
            elif ntype == "warning":
                bits = [str(df.get("The error") or ""), content, ctx]
            else:
                bits = [str(df.get("The condition") or ""), content, ctx]
            return "\n".join(b for b in bits if b).strip()
        return (content + "\n" + ctx).strip()

    repair_items: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        ntype = (n.get("node_type") or "").strip().lower()
        if ntype not in types_ok:
            continue
        df = n.get("definitive_fields")
        excerpt = _primary_excerpt(n, ntype, df)
        if len(excerpt) < 40:
            continue
        sq: Dict[str, Any] = {}
        if isinstance(df, dict):
            raw_sq = df.get("Source Quote")
            if isinstance(raw_sq, dict):
                sq = raw_sq
        quote = (sq.get("Quote") or "").strip()
        es = ec = ct = cn = None
        tj: Dict[str, Any] = {}
        if isinstance(df, dict):
            es, ec, ct, cn = df.get("ES"), df.get("EC"), df.get("CT"), df.get("CN")
            tj = df.get("Tag justifications") if isinstance(df.get("Tag justifications"), dict) else {}
        tags_all_gap = all(_text_looks_like_gap_placeholder(x) for x in (es, ec, ct, cn))
        tj_all_gap = all(_text_looks_like_gap_placeholder(tj.get(k)) for k in ("ES", "EC", "CT", "CN"))
        quote_weak = len(quote) < 12
        needs = quote_weak or tags_all_gap or tj_all_gap or not isinstance(df, dict)
        if not needs:
            continue
        repair_items.append(
            {
                "index": i,
                "node_type": ntype,
                "title": (n.get("title") or "").strip(),
                "primary_text": excerpt[:1800],
                "existing_quote": quote[:500] if quote else "",
            }
        )

    if not repair_items:
        return

    system = (
        "You fill definitive-framework epistemic fields for nodes of type step, warning, or constraint.\n"
        "Use ONLY primary_text, title, existing_quote, and node_type. Output JSON only.\n"
        "If existing_quote is empty or too short, include source_quote with Quote (<=60 words from primary_text) "
        "and Core_Sentence (one sentence contained in Quote).\n"
        "If existing_quote is adequate, you may omit source_quote.\n"
        "ES must be EXACTLY one of: Demonstrated, Argued, Asserted, Assumed.\n"
        "EC must be EXACTLY one of: Verbatim, Synthesized, Inferred.\n"
        "CT must be EXACTLY one of: Descriptive, Prescriptive, Evaluative.\n"
        "CN must be EXACTLY one of: Core, Supporting, Peripheral.\n"
        "tag_justifications: one short sentence per ES, EC, CT, CN tied to the quote or primary_text.\n"
        "Do NOT output 'not specified', 'not stated', or 'the book does not specify' for tags or justifications.\n"
        'Schema: { "items": [ { "index": int, "node_type": str, '
        '"source_quote": { "Quote": str, "Core_Sentence": str } (optional), '
        '"ES": str, "EC": str, "CT": str, "CN": str, '
        '"tag_justifications": { "ES": str, "EC": str, "CT": str, "CN": str } } ] }'
    )

    def _batch(items: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
        return [items[k : k + size] for k in range(0, len(items), size)]

    for chunk in _batch(repair_items, 5):
        user = f"Nodes to repair:\n{json.dumps(chunk, ensure_ascii=False)}\n\nReturn JSON items only."
        data = _llm_json_call(system=system, user=user, max_tokens=6144)
        if not data or not isinstance(data.get("items"), list):
            continue
        for oi in data["items"]:
            idx = oi.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(nodes):
                continue
            target = nodes[idx].setdefault("definitive_fields", {})
            if not isinstance(target, dict):
                continue
            _merge_llm_source_quote_and_epistemic(target, oi)


def infer_uses_definition_edges(
    nodes: List[Dict[str, Any]],
    existing_edges: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Add uses_definition edges when a definition's title appears in a step/warning/constraint's text.
    Direction: consumer (step|warning|constraint) -> definition. Framework-agnostic (no book-specific terms).
    """
    if not nodes:
        return []

    def _nt(n: Dict[str, Any]) -> str:
        return (n.get("node_type") or n.get("type") or "").strip().lower()

    id_to_node: Dict[int, Dict[str, Any]] = {}
    for n in nodes:
        nid = n.get("id")
        if nid is not None:
            try:
                id_to_node[int(nid)] = n
            except (TypeError, ValueError):
                pass

    definitions: List[Tuple[int, str]] = []
    for n in nodes:
        if _nt(n) != "definition":
            continue
        nid = n.get("id")
        if nid is None:
            continue
        title = (n.get("title") or "").strip()
        if len(title) < 2:
            continue
        try:
            definitions.append((int(nid), title))
        except (TypeError, ValueError):
            continue

    # Longer titles first to prefer specific multi-word terms.
    definitions.sort(key=lambda x: len(x[1]), reverse=True)

    existing: set[Tuple[int, int, str]] = set()
    for e in existing_edges or []:
        try:
            a, b = int(e.get("from_node_id")), int(e.get("to_node_id"))
            et = (e.get("edge_type") or "").strip().lower()
            existing.add((a, b, et))
            if et == "uses_definition":
                existing.add((b, a, et))
        except (TypeError, ValueError):
            continue

    def _haystack(n: Dict[str, Any]) -> str:
        parts = [
            n.get("title") or "",
            n.get("content") or "",
            n.get("context") or "",
        ]
        df = n.get("definitive_fields")
        if isinstance(df, dict):
            parts.append(str(df.get("Action") or ""))
            parts.append(str(df.get("The error") or ""))
            parts.append(str(df.get("The condition") or ""))
            ip = df.get("In Practice")
            if isinstance(ip, dict):
                for k in ("Case", "Context", "Action", "Outcome", "Lesson"):
                    parts.append(str(ip.get(k) or ""))
        return " \n ".join(parts).lower()

    def _title_mentioned(title: str, text_lower: str) -> bool:
        t = (title or "").strip()
        if len(t) < 2:
            return False
        tl = t.lower()
        if len(tl) <= 4 and " " not in tl:
            return bool(re.search(r"(?<!\w)" + re.escape(tl) + r"(?!\w)", text_lower))
        return tl in text_lower

    out: List[Dict[str, Any]] = []
    consumers = [n for n in nodes if _nt(n) in ("step", "warning", "constraint") and n.get("id") is not None]
    for cons in consumers:
        try:
            cid = int(cons["id"])
        except (TypeError, ValueError):
            continue
        hay = _haystack(cons)
        for did, title in definitions:
            if did == cid:
                continue
            if not _title_mentioned(title, hay):
                continue
            key = (cid, did, "uses_definition")
            if key in existing:
                continue
            existing.add(key)
            out.append(
                {
                    "from_node_id": cid,
                    "to_node_id": did,
                    "edge_type": "uses_definition",
                    "why": "Term appears in consumer text (inferred link).",
                }
            )
    if out:
        log.info("infer_uses_definition_edges: added %s edge(s) from text overlap.", len(out))
    return out


def _llm_json_call(
    system: str,
    user: str,
    max_tokens: int = 4096,
    task_name: str = "definitive_fields",
) -> Optional[Dict[str, Any]]:
    """Single LLM call returning parsed JSON or None on failure."""
    llm = _chat_llm_for_task(task_name, max_tokens)
    try:
        response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        raw = _lc_message_content_to_str(getattr(response, "content", None)).strip()
        if not raw:
            return None
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        if match:
            raw = match.group(1).strip()
        return json.loads(raw)
    except Exception as e:
        log.warning("Phase 1 agent LLM call failed: %s", e)
        return None


def normalize_definition_requires_and_reorder(nodes: List[Dict[str, Any]]) -> None:
    """
    v2 Rule 2: Requires holds prerequisite definition titles only (no gap prose).
    After definitive_fields fill, strip invalid entries, resolve titles, topologically sort
    definition nodes, assign sort_order 0..n-1 among definitions, and drop any Requires
    edges that would still violate render order (e.g. cycles).
    """
    from .mechanical_audit import _norm_title_key

    def_indices = sorted(
        [
            i
            for i, n in enumerate(nodes)
            if (n.get("node_type") or "").strip().lower() == "definition"
        ],
        key=lambda i: (nodes[i].get("sort_order", 0), nodes[i].get("id", 0)),
    )
    if not def_indices:
        return

    dcount = len(def_indices)
    # First wins on duplicate normalized titles (deterministic).
    key_to_local: Dict[str, int] = {}
    for local, gi in enumerate(def_indices):
        raw_t = (nodes[gi].get("title") or "").strip()
        k = _norm_title_key(raw_t)
        if len(k) >= 2 and k not in key_to_local:
            key_to_local[k] = local

    def _resolve_term_to_local(term: str) -> Optional[int]:
        kt = _norm_title_key((term or "").strip())
        if len(kt) < 2:
            return None
        return key_to_local.get(kt)

    prereq_locals: List[List[int]] = [[] for _ in range(dcount)]

    for local, gi in enumerate(def_indices):
        df = nodes[gi].get("definitive_fields")
        if not isinstance(df, dict):
            continue
        raw_req = df.get("Requires")
        cleaned = filter_reference_list_items(raw_req)
        seen_local: Set[int] = set()
        resolved_titles: List[str] = []
        for c in cleaned:
            jl = _resolve_term_to_local(c)
            if jl is None or jl == local:
                continue
            if jl in seen_local:
                continue
            seen_local.add(jl)
            canon = (nodes[def_indices[jl]].get("title") or "").strip()
            if not canon:
                continue
            resolved_titles.append(canon)
            prereq_locals[local].append(jl)
        df["Requires"] = resolved_titles

    if dcount == 1:
        nodes[def_indices[0]]["sort_order"] = 0
        return

    forward: Dict[int, List[int]] = {i: [] for i in range(dcount)}
    in_deg = [0] * dcount
    for i in range(dcount):
        for j in prereq_locals[i]:
            if j == i:
                continue
            forward[j].append(i)
            in_deg[i] += 1

    remaining: Set[int] = set(range(dcount))
    topo_order: List[int] = []
    in_work = list(in_deg)

    while remaining:
        ready = sorted(
            [i for i in remaining if in_work[i] == 0],
            key=lambda i: (nodes[def_indices[i]].get("sort_order", 0), nodes[def_indices[i]].get("id", 0)),
        )
        if not ready:
            log.warning(
                "normalize_definition_requires_and_reorder: cycle in definition Requires; "
                "appending remaining nodes in stable order"
            )
            leftovers = sorted(
                remaining,
                key=lambda i: (nodes[def_indices[i]].get("sort_order", 0), nodes[def_indices[i]].get("id", 0)),
            )
            topo_order.extend(leftovers)
            break
        pick = ready[0]
        topo_order.append(pick)
        remaining.remove(pick)
        for succ in forward[pick]:
            in_work[succ] -= 1

    pos = {local: r for r, local in enumerate(topo_order)}

    for local, gi in enumerate(def_indices):
        df = nodes[gi].get("definitive_fields")
        if not isinstance(df, dict):
            continue
        kept: List[str] = []
        seen_t: Set[str] = set()
        for jl in prereq_locals[local]:
            if pos.get(jl, -1) < pos.get(local, 1_000_000):
                canon = (nodes[def_indices[jl]].get("title") or "").strip()
                if canon and canon not in seen_t:
                    seen_t.add(canon)
                    kept.append(canon)
        df["Requires"] = kept

    for rank, local in enumerate(topo_order):
        nodes[def_indices[local]]["sort_order"] = rank


def run_definitive_fields_pass(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Phase 1: attach template-aligned definitive_fields per node.

    - Multi-pass by node_type: definitions -> principles -> steps -> warnings/constraints -> cases/examples
    - Adds only `node["definitive_fields"]` (as a dict); does NOT mutate node content/title.
    - Uses context/content as evidence source; when the book excerpt lacks details, fills with explicit
      "The book does not specify ..." text (so Phase 2 can treat it as acknowledged gaps).
    """
    if not nodes:
        return nodes

    def _dep_title(dep_idx: Optional[int]) -> str:
        if dep_idx is None:
            return ""
        if not isinstance(dep_idx, int) or dep_idx < 0 or dep_idx >= len(nodes):
            return ""
        return (nodes[dep_idx].get("title") or "").strip()

    def _dep_type(dep_idx: Optional[int]) -> str:
        if dep_idx is None:
            return ""
        if not isinstance(dep_idx, int) or dep_idx < 0 or dep_idx >= len(nodes):
            return ""
        return (nodes[dep_idx].get("node_type") or "").strip().lower()

    # Precompute step-related dependency lookup using extraction-level depends_on_index.
    step_index_to_warnings: Dict[int, List[str]] = {}
    step_index_to_constraints: Dict[int, List[str]] = {}
    step_index_to_cases: Dict[int, List[str]] = {}
    for i, n in enumerate(nodes):
        ntype = (n.get("node_type") or "").strip().lower()
        dep_idx = n.get("depends_on_index")
        if isinstance(dep_idx, int):
            if ntype == "warning":
                step_index_to_warnings.setdefault(dep_idx, []).append((n.get("title") or "").strip())
            elif ntype == "constraint":
                step_index_to_constraints.setdefault(dep_idx, []).append((n.get("title") or "").strip())
            elif ntype in ("case", "example"):
                step_index_to_cases.setdefault(dep_idx, []).append((n.get("title") or "").strip())

    def _batch(items: List[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
        return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

    # Generic system: forbid node invention; only fill requested fields.
    base_system = (
        "You are generating definitive template-aligned fields for a thinking framework.\n"
        "Rules:\n"
        "1) You must output ONLY valid JSON.\n"
        "2) Use ONLY the provided node title/content/context and any provided dependency titles.\n"
        "3) Do NOT invent new concepts, terms, or nodes.\n"
        "4) For definition nodes ONLY, the \"Requires\" field is a JSON array of prerequisite **definition titles** "
        "(exact strings matching other definitions in the batch). Use [] when there are no prerequisite terms. "
        "Never put gap prose, explanations, or \"The book does not specify…\" strings inside \"Requires\".\n"
        "5) For other fields, if the excerpt does not provide enough detail, set the value to an explicit string like:\n"
        "   \"The book does not specify <field> for this item.\" (or omit in JSON if allowed by schema), "
        "unless a feedback v2 note on that node type requires the field anyway (then infer conservatively from the excerpt).\n"
        "6) The \"context\" field is raw BOOK TEXT from the page window (may include line breaks or minor OCR noise). "
        "For Source Quote and close paraphrases, use wording that actually appears in content or context; "
        "do not fabricate sentences not supported by those strings.\n"
    )

    def _process_type(
        node_type: str,
        items: List[Dict[str, Any]],
        system_suffix: str,
        user_suffix: str,
        max_tokens: int,
        batch_size: int = 6,
    ) -> None:
        if not items:
            return
        for chunk in _batch(items, batch_size):
            system = base_system + "\n" + system_suffix
            user = (
                f"Node type: {node_type}\n\n"
                f"Items:\n{json.dumps(chunk, ensure_ascii=False)}\n\n"
                + user_suffix
            )
            pending.append(pool.submit(contextvars.copy_context().run, _llm_json_call,
                                       system=system, user=user, max_tokens=max_tokens))

    # Mnemosyne: every batch of every node type is sent at once - each reads only node text,
    # never another batch's fields - and the answers are applied in order once all are back.
    pool = ThreadPoolExecutor(max_workers=8)
    pending: List[Any] = []

    def _apply(resp: Optional[Dict[str, Any]]) -> None:
        out_items = (resp or {}).get("items") or []
        if not isinstance(out_items, list):
            return
        for oi in out_items:
            idx = oi.get("index")
            fields = oi.get("definitive_fields")
            if isinstance(idx, int) and 0 <= idx < len(nodes) and isinstance(fields, dict):
                nodes[idx]["definitive_fields"] = fields

    # 1) Definitions
    def_items: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if (n.get("node_type") or "").strip().lower() != "definition":
            continue
        def_items.append(
            {
                "index": i,
                "title": (n.get("title") or "").strip(),
                "page_ref": n.get("page_ref"),
                "content": n.get("content") or "",
                "context": definitive_context_excerpt(n.get("context"), n.get("content")),
                "depends_on_index": n.get("depends_on_index"),
                "requires_title": _dep_title(n.get("depends_on_index")),
                "requires_type": _dep_type(n.get("depends_on_index")),
            }
        )
    def_system_suffix = (
        "Return schema:\n"
        "{ \"items\": [ { \"index\": int, \"definitive_fields\": {"
        "  \"Boundary\": str,\n"
        "  \"Requires\": [str],\n"
        "  \"Definition Source\": str,\n"
        "  \"Operational Test\": str,\n"
        "  \"ES\": str,\n"
        "  \"EC\": str,\n"
        "  \"CT\": str,\n"
        "  \"CN\": str,\n"
        "  \"Tag justifications\": { \"ES\": str, \"EC\": str, \"CT\": str, \"CN\": str },\n"
        "  \"Source Quote\": { \"Quote\": str, \"Core Sentence\": str }\n"
        "} } ] }\n"
    )
    def_user_suffix = (
        "Fill all fields using only the excerpt (content + context). Keep \"Source Quote\" Quote <= 60 words; "
        "Quote must be copied or tightly paraphrased from the excerpt when any supporting text exists. "
        "Pick the single most evidential sentence as Core Sentence (must be contained within Quote).\n"
        + EPISTEMIC_TAG_ENUM_PROMPT
        + _V2_DEF_FIELDS
        + _V2_REQUIRES_FIELD
    )
    _process_type("definition", def_items, def_system_suffix, def_user_suffix, max_tokens=8192, batch_size=4)
    run_definition_tag_repair_pass(nodes)

    # 2) Principles
    pr_items: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if (n.get("node_type") or "").strip().lower() != "principle":
            continue
        pr_items.append(
            {
                "index": i,
                "title": (n.get("title") or "").strip(),
                "page_ref": n.get("page_ref"),
                "content": n.get("content") or "",
                "context": definitive_context_excerpt(n.get("context"), n.get("content")),
                "depends_on_index": n.get("depends_on_index"),
                "depends_title": _dep_title(n.get("depends_on_index")),
                "depends_type": _dep_type(n.get("depends_on_index")),
            }
        )
    pr_system_suffix = (
        "Return schema:\n"
        "{ \"items\": [ { \"index\": int, \"definitive_fields\": {"
        "  \"Statement\": str,\n"
        "  \"Tier\": str,\n"
        "  \"Governs\": str,\n"
        "  \"Argument Chain\": str,\n"
        "  \"ES\": str,\n"
        "  \"EC\": str,\n"
        "  \"CT\": str,\n"
        "  \"CN\": str,\n"
        "  \"Tag justifications\": { \"ES\": str, \"EC\": str, \"CT\": str, \"CN\": str },\n"
        "  \"Source Quote\": { \"Quote\": str, \"Core Sentence\": str }\n"
        "} } ] }\n"
    )
    pr_user_suffix = (
        "Classify Tier as \"Governing\" or \"Operational\". "
        "If the principle appears to apply broadly from the excerpt, set Governs to \"All steps\"; "
        "otherwise set Governs to the most specific applicable description available from content. "
        "Keep \"Source Quote\" Quote <= 60 words total. "
        + EPISTEMIC_TAG_ENUM_PROMPT
    )
    _process_type("principle", pr_items, pr_system_suffix, pr_user_suffix, max_tokens=8192)
    run_principle_tag_repair_pass(nodes)

    # 3) Steps
    step_items: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if (n.get("node_type") or "").strip().lower() != "step":
            continue
        dep_idx = n.get("depends_on_index")
        step_items.append(
            {
                "index": i,
                "title": (n.get("title") or "").strip(),
                "page_ref": n.get("page_ref"),
                "content": n.get("content") or "",
                "context": definitive_context_excerpt(n.get("context"), n.get("content")),
                "depends_on_index": dep_idx,
                "depends_title": _dep_title(dep_idx),
                "depends_type": _dep_type(dep_idx),
                "watch_for_warnings": step_index_to_warnings.get(i, []),
                "constrained_by_constraints": step_index_to_constraints.get(i, []),
                "in_practice_cases": step_index_to_cases.get(i, []),
            }
        )
    step_system_suffix = (
        "Return schema:\n"
        "{ \"items\": [ { \"index\": int, \"definitive_fields\": {"
        "  \"Action\": str,\n"
        "  \"Depends on\": str,\n"
        "  \"Governed by\": [str],\n"
        "  \"Watch for\": [str],\n"
        "  \"Constrained by\": [str],\n"
        "  \"Done When\": str,\n"
        "  \"Common Mistakes\": [str],\n"
        "  \"In Practice\": {"
        "      \"Case\": str,\n"
        "      \"Context\": str,\n"
        "      \"Action\": str,\n"
        "      \"Outcome\": str,\n"
        "      \"Lesson\": str,\n"
        "      \"Tag\": str"
        "  },\n"
        "  \"Source Quote\": { \"Quote\": str, \"Core Sentence\": str },\n"
        "  \"ES\": str,\n"
        "  \"EC\": str,\n"
        "  \"CT\": str,\n"
        "  \"CN\": str,\n"
        "  \"Tag justifications\": { \"ES\": str, \"EC\": str, \"CT\": str, \"CN\": str }\n"
        "} } ] }\n"
    )
    step_user_suffix = (
        "Action must be imperative (the procedure). Omit inapplicable keys entirely; never use the token \"N/A\".\n"
        "If there are no in_practice_cases, omit the \"In Practice\" key entirely (same as when no case exists).\n"
        "When watch_for_warnings and constrained_by_constraints are both empty, set \"Watch for\" and \"Constrained by\" "
        "to [] — do not add sentences claiming the book omitted warnings or constraints.\n"
        "When those lists provide titles, each array entry should be \"<Title> — <one-sentence risk/limit>\" "
        "grounded in the excerpt; if no extra detail exists, you may use the title alone.\n"
        "Done When: observable completion criteria; if truly absent, set to EXACTLY (verbatim): "
        + json.dumps(STEP_DONE_WHEN_GAP_CANONICAL)
        + ". "
        "Common Mistakes: 2–3 anti-patterns when inferable; otherwise [].\n"
        "Keep \"Source Quote\" Quote <= 60 words from the excerpt; Core Sentence must appear inside Quote.\n"
        + EPISTEMIC_TAG_ENUM_PROMPT
        + _V2_STEP_FIELDS
    )
    _process_type("step", step_items, step_system_suffix, step_user_suffix, max_tokens=8192, batch_size=4)

    # 4) Warnings
    warn_items: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if (n.get("node_type") or "").strip().lower() != "warning":
            continue
        dep_idx = n.get("depends_on_index")
        warn_items.append(
            {
                "index": i,
                "title": (n.get("title") or "").strip(),
                "page_ref": n.get("page_ref"),
                "content": n.get("content") or "",
                "context": definitive_context_excerpt(n.get("context"), n.get("content")),
                "depends_on_index": dep_idx,
                "highest_risk_step_title": _dep_title(dep_idx) if _dep_type(dep_idx) == "step" else "",
            }
        )
    warn_system_suffix = (
        "Return schema:\n"
        "{ \"items\": [ { \"index\": int, \"definitive_fields\": {"
        "  \"The error\": str,\n"
        "  \"Consequence\": str,\n"
        "  \"Symptoms\": [str],\n"
        "  \"Highest risk at\": str,\n"
        "  \"Tension pair\": str,\n"
        "  \"ES\": str,\n"
        "  \"EC\": str,\n"
        "  \"CT\": str,\n"
        "  \"CN\": str,\n"
        "  \"Tag justifications\": { \"ES\": str, \"EC\": str, \"CT\": str, \"CN\": str },\n"
        "  \"Source Quote\": { \"Quote\": str, \"Core Sentence\": str }\n"
        "} } ] }\n"
    )
    warn_user_suffix = (
        "Keep \"Source Quote\" Quote <= 60 words; Core Sentence must appear inside Quote.\n"
        "If highest_risk_step_title is non-empty, set \"Highest risk at\" to that step label; "
        "if empty, use \"The book does not specify the associated step for this warning.\"\n"
        "Omit Consequence or Tension pair only when unsupported by the excerpt. "
        "Do not omit Symptoms (Rule 21): output 2–4 observable strings, or the single canonical gap string from the v2 block.\n"
        + EPISTEMIC_TAG_ENUM_PROMPT
        + _V2_WARN_FIELDS
    )
    _process_type("warning", warn_items, warn_system_suffix, warn_user_suffix, max_tokens=8192, batch_size=4)

    # 5) Constraints
    cons_items: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if (n.get("node_type") or "").strip().lower() != "constraint":
            continue
        dep_idx = n.get("depends_on_index")
        cons_items.append(
            {
                "index": i,
                "title": (n.get("title") or "").strip(),
                "page_ref": n.get("page_ref"),
                "content": n.get("content") or "",
                "context": definitive_context_excerpt(n.get("context"), n.get("content")),
                "depends_on_index": dep_idx,
                "affects_step_title": _dep_title(dep_idx) if _dep_type(dep_idx) == "step" else "",
            }
        )
    cons_system_suffix = (
        "Return schema:\n"
        "{ \"items\": [ { \"index\": int, \"definitive_fields\": {"
        "  \"The condition\": str,\n"
        "  \"If absent\": str,\n"
        "  \"Mitigation\": str,\n"
        "  \"Affects\": str,\n"
        "  \"Tension pair\": str,\n"
        "  \"ES\": str,\n"
        "  \"EC\": str,\n"
        "  \"CT\": str,\n"
        "  \"CN\": str,\n"
        "  \"Tag justifications\": { \"ES\": str, \"EC\": str, \"CT\": str, \"CN\": str },\n"
        "  \"Source Quote\": { \"Quote\": str, \"Core Sentence\": str }\n"
        "} } ] }\n"
    )
    cons_user_suffix = (
        "\"If absent\" must describe what breaks or fails if the condition is missing — infer from "
        "\"The condition\" and the excerpt; do not default to generic 'the book does not specify' unless "
        "the excerpt truly gives no basis.\n"
        "If the book gives no mitigation, set Mitigation to "
        "\"The book does not provide a mitigation for this condition.\" "
        "If the template would use \"No mitigation provided\" for Section 9C, you may use that exact phrase instead.\n"
        "Set \"Affects\" from affects_step_title when provided; otherwise state that the associated step is not specified.\n"
        "Keep \"Source Quote\" Quote <= 60 words; Core Sentence inside Quote.\n"
        "Omit Tension pair when not supported by the excerpt.\n"
        + EPISTEMIC_TAG_ENUM_PROMPT
        + _V2_CONSTRAINT_FIELDS
    )
    _process_type("constraint", cons_items, cons_system_suffix, cons_user_suffix, max_tokens=8192, batch_size=4)
    run_step_warning_constraint_epistemic_repair_pass(nodes)

    # 6) Cases / Examples (In Practice sub-structure)
    case_items: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if (n.get("node_type") or "").strip().lower() not in ("case", "example"):
            continue
        case_items.append(
            {
                "index": i,
                "node_type": (n.get("node_type") or "").strip().lower(),
                "title": (n.get("title") or "").strip(),
                "page_ref": n.get("page_ref"),
                "content": n.get("content") or "",
                "context": definitive_context_excerpt(n.get("context"), n.get("content")),
                "depends_on_index": n.get("depends_on_index"),
                "related_step_title": _dep_title(n.get("depends_on_index")),
            }
        )
    case_system_suffix = (
        "Return schema:\n"
        "{ \"items\": [ { \"index\": int, \"definitive_fields\": {"
        "  \"Context\": str,\n"
        "  \"Action\": str,\n"
        "  \"Outcome\": str,\n"
        "  \"Lesson\": str,\n"
        "  \"Tag\": str\n"
        "} } ] }\n"
    )
    case_user_suffix = (
        "Outcome must name a specific metric or explicitly state 'qualitative only'. "
        "Tag as 'First-hand' if the excerpt indicates the author was involved; otherwise 'Second-hand'."
    )
    _process_type("case/example", case_items, case_system_suffix, case_user_suffix, max_tokens=8192)
    for future in pending:
        _apply(future.result())
    pool.shutdown()

    n_sym_gap = ensure_warning_symptoms_or_gap(nodes)
    if n_sym_gap:
        log.info(
            "Field completion (Rule 21): Symptoms gap or normalization applied to %s warning node(s).",
            n_sym_gap,
        )

    n_def = ensure_definition_fields_or_gap(nodes)
    if n_def:
        log.info(
            "Field completion (Rules 14–16): Definition Source / Operational Test gap applied to %s definition node(s).",
            n_def,
        )

    n_step = ensure_step_action_done_when_or_gap(nodes)
    n_con_mit = ensure_constraint_mitigation_or_gap(nodes)
    if n_step:
        log.info(
            "Field completion (Rules 17–19): Action / Done When gap applied to %s step node(s).",
            n_step,
        )
    if n_con_mit:
        log.info(
            "Field completion (Rule 22): Mitigation gap applied to %s constraint node(s).",
            n_con_mit,
        )

    n_q = enforce_source_quote_word_limit(nodes, max_words=SOURCE_QUOTE_MAX_WORDS)
    if n_q:
        log.info(
            "Field completion (Rule 26): Source Quote trimmed to ≤%s words on %s node(s).",
            SOURCE_QUOTE_MAX_WORDS,
            n_q,
        )

    normalize_definition_requires_and_reorder(nodes)

    return nodes


def run_epistemic_pass(
    nodes: List[Dict[str, Any]],
    edges: Optional[List[Dict[str, Any]]] = None,
    digest: Optional[FrameworkGraphDigest] = None,
) -> List[Dict[str, Any]]:
    """Label key claims as fact / interpretation / assumption; add epistemic_note. Non-blocking."""
    if digest is not None:
        node_block, edge_block = digest.slice(None, 4000, None, None)
    else:
        node_block, edge_block = build_graph_summary(nodes, edges, edge_block_max_chars=4000)
    summary = node_block
    if edge_block:
        summary = summary + "\n\nRelationships (for context):\n" + edge_block
    system = (
        "You are an Epistemic analyst. For each framework item that states a key claim (definitions, principles, steps), "
        "classify it as: fact (directly from source), interpretation (inference from source), or assumption (unstated premise). "
        "Output ONLY valid JSON: { \"items\": [ { \"index\": 0-based node index, \"epistemic_type\": \"fact\"|\"interpretation\"|\"assumption\", "
        "\"epistemic_note\": \"optional one-line note e.g. Direct quote\" } ] }. "
        "Only include items that are definition, principle, or step; skip section headers. Use the index from the node block ([0], [1], ...). Do not hallucinate indices."
    )
    user = f"Framework summary (index in brackets):\n{summary}\n\nOutput JSON with items array."
    data = _llm_json_call(system, user, task_name="epistemic_pass")
    if not data or not isinstance(data.get("items"), list):
        return nodes
    for item in data["items"]:
        idx = item.get("index")
        if idx is None or not isinstance(idx, int) or idx < 0 or idx >= len(nodes):
            continue
        t = (item.get("epistemic_type") or "").strip().lower()
        if t in ("fact", "interpretation", "assumption"):
            nodes[idx]["epistemic_type"] = t
        note = item.get("epistemic_note")
        if isinstance(note, str) and note.strip():
            nodes[idx]["epistemic_note"] = note.strip()[:200]
    return nodes


def run_meta_pass(
    nodes: List[Dict[str, Any]],
    name: str,
    edges: Optional[List[Dict[str, Any]]] = None,
    digest: Optional[FrameworkGraphDigest] = None,
) -> Dict[str, Optional[str]]:
    """Produce purpose and assumptions_limits (slightly detailed, practitioner-focused). Non-blocking."""
    _meta_edge_filter: Set[str] = {"supports", "implemented_by", "refined_into", "exposes_problem_in", "drives_step"}
    if digest is not None:
        node_block, edge_block = digest.slice(8000, 4000, _meta_edge_filter, None)
    else:
        node_block, edge_block = build_graph_summary(
            nodes,
            edges,
            node_block_max_chars=8000,
            edge_block_max_chars=4000,
            edge_type_filter=_meta_edge_filter,
        )
    summary = node_block
    if edge_block:
        summary = summary + "\n\nRelationships:\n" + edge_block
    system = (
        "You are a Meta analyst. Use the structure of the graph (nodes and relationships) to infer what the framework is about. "
        "Write for a practitioner who wants to quickly understand why this framework exists and where it applies.\n"
        "Produce:\n"
        "1) purpose: 3-6 sentences on what this framework is for, who should use it, and what central problem(s) it helps solve in practice.\n"
        "2) assumptions_limits: 3-6 sentences on key assumptions, preconditions, and what it does not cover (use constraint/warning nodes and obvious gaps in the graph).\n"
        "Avoid literary analysis language; describe use in real situations.\n"
        "Output ONLY valid JSON: { \"purpose\": \"...\", \"assumptions_limits\": \"...\" }."
    )
    user = f"Framework name: {name}\n\nFramework summary:\n{summary}\n\nOutput JSON with purpose and assumptions_limits."
    data = _llm_json_call(system, user, max_tokens=1024, task_name="meta_pass")
    if not data:
        return {"purpose": None, "assumptions_limits": None}
    return {
        "purpose": (data.get("purpose") or "").strip()[:1500] or None,
        "assumptions_limits": (data.get("assumptions_limits") or "").strip()[:1500] or None,
    }


def run_scope_pass(
    nodes: List[Dict[str, Any]],
    purpose: Optional[str],
    assumptions_limits: Optional[str],
    book_meta: Optional[Dict[str, Any]] = None,
    book_excerpt_block: Optional[str] = None,
    max_completion_tokens: int = 1536,
    graph_digest: Optional[FrameworkGraphDigest] = None,
) -> Dict[str, Optional[str]]:
    """
    Extract claimed_scope and evidenced_scope for the definitive Overview table.

    Uses: meta purpose/limits, book row (title, target_audience), optional BOOK_EXCERPTS,
    structured fields from nodes, and optional graph_digest (full framework graph for Point A).
    """
    book_meta = book_meta or {}
    purpose_txt = (purpose or "").strip()
    assumptions_txt = (assumptions_limits or "").strip()
    book_title = (book_meta.get("title") or "").strip()
    target_audience = (book_meta.get("target_audience") or "").strip()
    excerpts = (book_excerpt_block or "").strip()

    def _nt(n: Dict[str, Any]) -> str:
        return (n.get("node_type") or n.get("type") or "").strip().lower()

    # Capped slices: long In Practice blobs are summarized later via snippets (do not feed 700+ char lines to the LLM).
    _IP_MAX = 360
    _PR_MAX = 280

    evidence_steps: List[str] = []
    evidence_cases: List[str] = []
    case_titles: List[str] = []
    principle_scope_hints: List[str] = []

    for n in nodes:
        t = _nt(n)
        df = n.get("definitive_fields") or {}
        if not isinstance(df, dict):
            df = {}

        if t == "step":
            ip = df.get("In Practice")
            if isinstance(ip, dict):
                # Context + Action only for scope evidence (Outcome/Case often mid-sentence $ blurbs).
                for key in ("Context", "Action"):
                    s = (ip.get(key) or "").strip()
                    if s and len(s) > 8:
                        evidence_steps.append(f"[Step In Practice {key}] {s[:_IP_MAX]}")
        elif t in ("case", "example"):
            title = (n.get("title") or "").strip()
            if title:
                case_titles.append(title[:200])
            ctx = (df.get("Context") or "").strip()
            if ctx:
                evidence_cases.append(f"[{t.title()} Context] {ctx[:_IP_MAX]}")
            elif title:
                evidence_cases.append(f"[{t.title()} title-only] {title[:180]}")
        elif t == "principle":
            stmt = (df.get("Statement") or n.get("content") or "").strip()
            gov = (df.get("Governs") or "").strip()
            if stmt and len(stmt) > 20:
                principle_scope_hints.append(f"[Principle] {stmt[:_PR_MAX]}")
            if gov:
                principle_scope_hints.append(f"[Principle Governs] {gov[:260]}")

    seen_ev: set[str] = set()
    uniq_ctx: List[str] = []
    for c in principle_scope_hints + evidence_steps + evidence_cases:
        key = c[:140]
        if key in seen_ev:
            continue
        seen_ev.add(key)
        uniq_ctx.append(c)
        if len(uniq_ctx) >= 24:
            break

    case_titles_uniq: List[str] = []
    seen_titles: set[str] = set()
    for tt in case_titles:
        tl = tt.lower()
        if tl in seen_titles:
            continue
        seen_titles.add(tl)
        case_titles_uniq.append(tt)
        if len(case_titles_uniq) >= 14:
            break

    evidence_block = (
        "\n".join(f"- {c}" for c in uniq_ctx)
        if uniq_ctx
        else "(no step/case/principle context lines collected)"
    )
    cases_block = (
        "\n".join(f"- {t}" for t in case_titles_uniq)
        if case_titles_uniq
        else "(no case/example titles)"
    )
    book_block_lines: List[str] = []
    if book_title:
        book_block_lines.append(f"BOOK_TITLE: {book_title}")
    if not _target_audience_placeholder(target_audience):
        book_block_lines.append(f"TARGET_AUDIENCE (from book metadata / extraction): {target_audience}")
    book_block = "\n".join(book_block_lines) if book_block_lines else "(no book metadata fields)"

    claimed_draft = _build_claimed_scope_draft(
        purpose_txt, assumptions_txt, target_audience, book_title
    )
    excerpts_user = excerpts[:6500] if excerpts else "(no book excerpts provided)"
    # Explicitly unused; scope flow is evidence-led and stable without graph inference.
    _ = graph_digest

    def _norm(v: Any) -> Optional[str]:
        if not isinstance(v, str):
            return None
        s = v.strip()
        return s if s else None

    # -------- Pass 1: primary extraction --------
    claimed_system = (
        "Extract ONLY claimed_scope. Output JSON only.\n"
        "Claimed scope = where/for whom the book says the method applies (audience, setting, domain).\n"
        "Output plain prose only (1-3 sentences). Do not use prefixes like 'Source:', "
        "'Readership / audience:', 'Audience:', or the book title as a citation line.\n"
        "Each pass must end with a complete sentence (. ! or ?); do not stop mid-phrase or with a trailing hyphen.\n"
        "Use BOOK metadata/excerpts and CLAIMED_SCOPE_DRAFT. Do not include examples list.\n"
        "Return JSON: {\"claimed_scope\": str|null}."
    )
    claimed_user = (
        f"{book_block}\n\n"
        + f"BOOK_EXCERPTS:\n{excerpts_user}\n\n"
        + "CLAIMED_SCOPE_DRAFT:\n"
        + (claimed_draft or "(none)")
    )
    claimed_data = _llm_json_call(
        system=claimed_system,
        user=claimed_user,
        max_tokens=max(450, min(max_completion_tokens, 900)),
        task_name="scope_pass",
    ) or {}

    evidenced_system = (
        "Extract ONLY evidenced_scope. Output JSON only.\n"
        "Evidenced scope = situations actually instantiated in evidence lines (cases/contexts).\n"
        "Rules: 1-3 short sentences, max 600 chars, no long quote dumps, no list-only output.\n"
        "Start with a capital letter and a full sentence; never begin with mid-sentence fragments.\n"
        "Return JSON: {\"evidenced_scope\": str|null}."
    )
    evidenced_user = (
        f"CASE / EXAMPLE TITLES (secondary):\n{cases_block}\n\n"
        + f"EVIDENCE LINES (primary):\n{evidence_block}\n\n"
        + f"BOOK_EXCERPTS:\n{excerpts_user}"
    )
    evidenced_data = _llm_json_call(
        system=evidenced_system,
        user=evidenced_user,
        max_tokens=max(550, min(max_completion_tokens, 1000)),
        task_name="scope_pass",
    ) or {}

    claimed_scope = _norm(claimed_data.get("claimed_scope")) or "Not stated in source"
    evidenced_scope = _norm(evidenced_data.get("evidenced_scope")) or "Not stated in source"

    # -------- Validate pass 1 --------
    claimed_issues = _validate_claimed_scope(claimed_scope, target_audience)
    evidenced_issues = _validate_evidenced_scope(evidenced_scope, uniq_ctx)

    # -------- Pass 2: repair if invalid --------
    if claimed_issues:
        repaired = _repair_scope_with_llm(
            kind="claimed",
            candidate=claimed_scope,
            issues=claimed_issues,
            evidence_block=evidence_block,
            book_block=book_block,
            claimed_draft=claimed_draft or "",
            excerpts_user=excerpts_user,
            max_tokens=max(350, min(max_completion_tokens, 800)),
        )
        if repaired:
            candidate = repaired
            post_issues = _validate_claimed_scope(candidate, target_audience)
            if not post_issues:
                claimed_scope = candidate
                claimed_issues = []

    if evidenced_issues:
        repaired = _repair_scope_with_llm(
            kind="evidenced",
            candidate=evidenced_scope,
            issues=evidenced_issues,
            evidence_block=evidence_block,
            book_block=book_block,
            claimed_draft=claimed_draft or "",
            excerpts_user=excerpts_user,
            max_tokens=max(420, min(max_completion_tokens, 900)),
        )
        if repaired:
            candidate = repaired
            post_issues = _validate_evidenced_scope(candidate, uniq_ctx)
            if not post_issues:
                evidenced_scope = candidate
                evidenced_issues = []

    # -------- Last-resort deterministic fallback --------
    if claimed_issues:
        if claimed_draft and len(claimed_draft) >= _SCOPE_MIN_CLAIMED:
            claimed_scope = _truncate_scope_at_sentence_boundary(claimed_draft, _SCOPE_MAX_CLAIMED)
        elif not _target_audience_placeholder(target_audience):
            claimed_scope = (
                "The method is positioned for practitioners operating under high uncertainty, "
                f"including: {target_audience[:320]}"
            )
        else:
            claimed_scope = "Not stated in source"

    if evidenced_issues:
        det_ev = _deterministic_evidenced_from_lines(uniq_ctx, max_chars=_SCOPE_MAX_EVIDENCED)
        evidenced_scope = det_ev or "Not stated in source"

    # Final strip catalog labels, sanitize + hard cap (sentence-safe trim for table cells)
    claimed_scope = _strip_claimed_scope_labels(claimed_scope)
    claimed_scope = sanitize_definitive_scope_text(
        claimed_scope, max_len=_SCOPE_MAX_CLAIMED, sentence_boundary=True
    )
    evidenced_scope = sanitize_definitive_scope_text(
        evidenced_scope, max_len=_SCOPE_MAX_EVIDENCED, sentence_boundary=True
    )

    return {
        "claimed_scope": claimed_scope,
        "evidenced_scope": evidenced_scope,
    }


# --- Mindmap (Stage 2) edges generation ---

_MIN_EDGES_PER_FRAMEWORK = 0
_MAX_EDGES_PER_FRAMEWORK = 200


def run_mindmap_edges(nodes: List[Dict[str, Any]], max_completion_tokens: int = 4096) -> List[Dict[str, Any]]:
    """
    Generate mindmap edges between framework nodes.

    Input nodes must include: id, node_type, title, content.
    Output: list of edges { from_node_id, to_node_id, edge_type, why }.
    Non-blocking: on failure, returns [].
    """
    if not nodes:
        log.info("Mindmap edges: no nodes provided, returning empty edges.")
        return []

    # Build concise node descriptions for the LLM
    lines = []
    for n in nodes:
        nid = n.get("id")
        if nid is None:
            continue
        node_type = (n.get("node_type") or n.get("type") or "section").strip().lower()
        title = (n.get("title") or "").strip()
        content = (n.get("content") or "").strip().replace("\n", " ")
        if len(content) > 260:
            content = content[:260] + "..."
        lines.append(f"- id: {nid}, type: {node_type}, title: {title!r}, summary: {content!r}")
    if not lines:
        log.info("Mindmap edges: nodes had no valid IDs, returning empty edges.")
        return []

    node_block = "\n".join(lines)
    system = (
        "You are building a conceptual mindmap over an existing framework.\n"
        "Given a list of nodes (id, type, title, summary), you must propose relationships between them.\n\n"
        "Allowed edge types and their correct use:\n"
        "- supports: evidence or case underpins a step or principle. Use case/example → step or case/example → principle [supports]. Direction: evidence → claim. Do NOT use step → case.\n"
        "- implemented_by: a general rule is put into practice by a concrete step. Use ONLY for principle → step. NEVER use for step → step.\n"
        "- leads_to: one step leads to the next in sequence. Use for step → step (earlier step leads_to later step).\n"
        "- uses_definition: a step or principle uses a definition. Use for step → definition or principle → definition.\n"
        "- constrains: a constraint limits or contextualizes a step. Use for constraint → step [constrains]. Do NOT use step → constraint.\n"
        "- warns: a warning cautions about a step. Use for warning → step [warns]. Do NOT use step → warning.\n"
        "- feeds_back_to: the last step of a cycle feeds back to the first step. Use when the framework describes a repeatable loop (e.g. a decide/repeat step feeds back to the initial step).\n"
        "- refined_into: a concrete case is generalized into an abstract rule (case/definition → principle).\n"
        "- exposes_problem_in: a case reveals a failure mode in a naive approach.\n"
        "- drives_step: a principle directly motivates a procedural step (principle → step).\n"
        "- tension (Rule 24): two nodes are opposing failure modes of the same decision (e.g. \"too slow\" vs \"too fast\"). "
        "Use ONLY between warning↔warning, constraint↔constraint, or warning↔constraint when the summaries support opposing poles. "
        "Set from_node_id to the lower numeric id and to_node_id to the higher id for consistency. "
        "**why** must be one sentence naming the balance point the practitioner must hold.\n"
        "- opposes: alias of tension (same rules); prefer **tension** in output.\n\n"
        "Structural guidance:\n"
        "- Where the method describes a sequence or cycle, emit step→step edges so the full procedural order is explicit (e.g. step 1 → step 2 → step 3 …).\n"
        "- For each step (and where relevant each principle), add uses_definition to definition nodes it relies on, and add constrains/warns from constraint/warning nodes that apply to that step.\n\n"
        "Rules:\n"
        "1) Only use the provided node IDs; do NOT invent new nodes.\n"
        "2) Use the allowed edge types with correct direction as above.\n"
        f"3) Prefer quality over quantity; at most {_MAX_EDGES_PER_FRAMEWORK} edges in total.\n"
        "4) If unsure about a relationship, omit it.\n"
        "5) Output ONLY valid JSON: { \"edges\": [ { \"from_node_id\": int, \"to_node_id\": int, "
        "\"edge_type\": \"supports|implemented_by|leads_to|uses_definition|constrains|warns|feeds_back_to|refined_into|exposes_problem_in|drives_step|tension|opposes\", "
        "\"why\": \"short justification\" } ] }.\n"
    )
    user = (
        "Framework nodes:\n"
        f"{node_block}\n\n"
        "Using ONLY these nodes, propose meaningful edges following the rules above. "
        "Return JSON with an 'edges' array. If there are no clear edges, return {\"edges\":[]}."
    )

    llm = _chat_llm_for_task("mindmap_edges", max_completion_tokens)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    raw = ""
    try:
        response = llm.invoke(messages)
        raw = _lc_message_content_to_str(getattr(response, "content", None)).strip()
    except Exception as e:
        log.warning("Mindmap edges LLM call failed: %s", e)
        log.warning("Mindmap edges: empty LLM response, returning no edges.")
        return []
    if not raw:
        return []
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        preview = raw[:400] + ("..." if len(raw) > 400 else "")
        log.warning("Mindmap edges: invalid JSON, ignoring. error=%s preview=%r", e, preview)
        return []
    edges_raw = data.get("edges")
    if not isinstance(edges_raw, list):
        log.info("Mindmap edges: JSON had no 'edges' array, returning empty edges.")
        return []
    edges: List[Dict[str, Any]] = []
    valid_ids = {n.get("id") for n in nodes if n.get("id") is not None}
    for e in edges_raw:
        try:
            from_id = int(e.get("from_node_id"))
            to_id = int(e.get("to_node_id"))
        except (TypeError, ValueError):
            continue
        if from_id not in valid_ids or to_id not in valid_ids:
            continue
        edge_type = (e.get("edge_type") or "").strip().lower()
        if edge_type not in (
            "supports",
            "implemented_by",
            "leads_to",
            "uses_definition",
            "constrains",
            "warns",
            "feeds_back_to",
            "refined_into",
            "exposes_problem_in",
            "drives_step",
            "tension",
            "tension_pair",
            "opposes",
        ):
            continue
        why = e.get("why")
        if isinstance(why, str):
            why = why.strip()[:500]
        else:
            why = None
        edges.append(
            {
                "from_node_id": from_id,
                "to_node_id": to_id,
                "edge_type": edge_type,
                "why": why,
            }
        )
        if len(edges) >= _MAX_EDGES_PER_FRAMEWORK:
            break
    log.info("Mindmap edges: built %s edge(s) from %s nodes.", len(edges), len(nodes))
    return edges


def build_dependency_edges(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deterministic edges from depends_on_node_id in nodes.
    Uses taxonomy: step->step -> leads_to, step->definition -> uses_definition,
    step->principle -> implemented_by, warning/constraint->step -> constrains, else supports.
    """
    if not nodes:
        return []
    id_to_node: Dict[int, Dict[str, Any]] = {}
    for n in nodes:
        nid = n.get("id")
        if nid is not None:
            id_to_node[int(nid)] = n

    def _type(n: Dict[str, Any]) -> str:
        t = (n.get("node_type") or n.get("type") or "section").strip().lower()
        return t if t else "section"

    edges: List[Dict[str, Any]] = []
    for n in nodes:
        nid = n.get("id")
        depends_id = n.get("depends_on_node_id")
        if nid is None or depends_id is None:
            continue
        try:
            depends_id = int(depends_id)
        except (TypeError, ValueError):
            continue
        if depends_id not in id_to_node:
            continue
        dep_node = id_to_node[depends_id]
        node_type = _type(n)
        dep_type = _type(dep_node)
        # Edge direction matches mechanical audit + taxonomy: prerequisite -> dependent; step uses_definition -> definition;
        # warning|constraint -> step for warns|constrains.
        if node_type == "step" and dep_type == "step":
            edge_type = "leads_to"
            frm, to = depends_id, nid
        elif node_type == "step" and dep_type == "definition":
            edge_type = "uses_definition"
            frm, to = nid, depends_id
        elif node_type == "step" and dep_type == "principle":
            edge_type = "implemented_by"
            frm, to = depends_id, nid
        elif node_type == "warning" and dep_type == "step":
            edge_type = "warns"
            frm, to = nid, depends_id
        elif node_type == "constraint" and dep_type == "step":
            edge_type = "constrains"
            frm, to = nid, depends_id
        else:
            edge_type = "supports"
            frm, to = depends_id, nid
        edges.append(
            {
                "from_node_id": frm,
                "to_node_id": to,
                "edge_type": edge_type,
                "why": None,
            }
        )
    log.info("Mindmap dependency edges: built %s deterministic edge(s).", len(edges))
    return edges


# Definitive doc export (v2): overview sentence budget + consistent field placeholders
_OVERVIEW_MAX_SENTENCES = 3
_RENDER_PLACEHOLDER = "—"


def _split_into_sentences(text: str) -> List[str]:
    t = (text or "").strip()
    if not t:
        return []
    parts = re.split(r"(?<=[.!?])\s+", t)
    return [p.strip() for p in parts if p.strip()]


def _clip_sentences(text: str, max_sentences: int = _OVERVIEW_MAX_SENTENCES) -> str:
    parts = _split_into_sentences(text)
    if not parts:
        return (text or "").strip()
    return " ".join(parts[: max(1, int(max_sentences))])


def _sanitize_overview_prose_block(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(r"^#+\s+", "", t)
    t = re.sub(r"\s+#+\s+", " ", t)
    return _clip_sentences(t, _OVERVIEW_MAX_SENTENCES)


def _fixed_document_structure_prose() -> str:
    """Definitive_Framework_Template_Fina.md §2 — fixed inventory; not LLM-generated."""
    return (
        "This document has a fixed set of sections, in this order: Metadata, "
        "Overview, Definitions, Principles, Steps, Warnings, Constraints, Dependency Map, Scope & Limits, "
        "and Coverage Report."
    )


def _neutral_fallback_overview(book_title: str, framework_name: str) -> Dict[str, str]:
    """Deterministic Overview text when the LLM pass fails — no step-action boilerplate."""
    bt = (book_title or "").strip() or "the source"
    fn = (framework_name or "").strip() or "This framework"
    return {
        "problem": _clip_sentences(
            f"{fn} organizes guidance from «{bt}» for situations where the right move is not obvious."
        ),
        "core_argument": _clip_sentences(
            "The central idea is that explicit definitions, governing principles, and ordered steps reduce execution error compared with ad hoc judgment alone."
        ),
        "method": _clip_sentences(
            "Mechanisms include precise terms, principle-level rules, sequenced steps, and explicit warnings and constraints where the source marks risk or limits."
        ),
    }


def _overview_prose_from_llm_payload(data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    keys = ("problem", "core_argument", "method")
    out: Dict[str, str] = {}
    for k in keys:
        raw = data.get(k)
        if raw is None:
            return None
        s = raw.strip() if isinstance(raw, str) else str(raw).strip()
        out[k] = _sanitize_overview_prose_block(s)
        if not out[k]:
            return None
    return out


def _with_fixed_document_structure(three_blocks: Dict[str, str]) -> Dict[str, str]:
    return {**three_blocks, "document_structure": _fixed_document_structure_prose()}


def run_overview_prose_pass(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    name: str,
    purpose: Optional[str],
    assumptions_limits: Optional[str],
    claimed_scope: str,
    evidenced_scope: str,
    book_meta: Optional[Dict[str, Any]] = None,
    graph_digest: Optional[FrameworkGraphDigest] = None,
    max_completion_tokens: int = 1536,
) -> Dict[str, str]:
    """
    One structured LLM call for §2 Overview (Problem, Core Argument, Method).

    Document Structure is template-fixed (not from the LLM). Scope rows are supplied verbatim.
    On failure, returns neutral deterministic prose for the three blocks plus fixed structure.
    """
    book_meta = book_meta or {}
    book_title = (book_meta.get("title") or "").strip() or "Unknown book"
    fn = (name or "").strip() or "Framework"

    if not nodes:
        log.info("Overview prose pass: no nodes; using neutral fallback.")
        return _with_fixed_document_structure(_neutral_fallback_overview(book_title, fn))

    purpose_txt = (purpose or "").strip()
    assumptions_txt = (assumptions_limits or "").strip()
    claimed = (claimed_scope or "").strip() or "Not stated in source"
    evidenced = (evidenced_scope or "").strip() or "Not stated in source"

    if graph_digest is not None:
        node_block, edge_block = graph_digest.slice(10000, 6000, None, None)
    else:
        node_block, edge_block = build_graph_summary(
            nodes, edges, node_block_max_chars=10000, edge_block_max_chars=6000
        )
    summary = node_block
    if edge_block:
        summary = summary + "\n\nRelationships:\n" + edge_block

    system = (
        "You write part of the Overview section of a practitioner-facing framework document.\n"
        "Output ONLY valid JSON with exactly these string keys: "
        '"problem", "core_argument", "method".\n\n'
        "Rules (Definitive template + Rule 4 style):\n"
        "- Each value is plain prose, at most 3 sentences, no markdown headings inside the string.\n"
        "- problem: the situational pressure or failure mode this framework addresses; plain language only — "
        "do not use defined technical terms from the framework as if the reader already knows them.\n"
        "- core_argument: the central claim about why this structure improves decisions (still avoid undefined jargon).\n"
        "- method: name mechanisms at a high level only (e.g. definitions, principles, ordered steps, warnings, constraints). "
        "Do NOT quote step Action lines, do NOT say 'starting with Step 1', do NOT paste procedural detail.\n"
        "- Treat Claimed Scope and Evidenced Scope (provided below) as authoritative for audience and reach; do not contradict them.\n"
    )
    user = (
        f"Framework name: {fn}\n"
        f"Book title: {book_title}\n\n"
        f"Meta purpose:\n{purpose_txt or '(none)'}\n\n"
        f"Meta assumptions / limits:\n{assumptions_txt or '(none)'}\n\n"
        f"Claimed Scope (authoritative):\n{claimed}\n\n"
        f"Evidenced Scope (authoritative):\n{evidenced}\n\n"
        f"Framework graph (node index in brackets):\n{summary}\n\n"
        "Return JSON only."
    )
    data = _llm_json_call(system, user, max_tokens=max_completion_tokens, task_name="overview_prose")
    if data and isinstance(data, dict):
        parsed = _overview_prose_from_llm_payload(data)
        if parsed:
            log.info("Overview prose pass: LLM returned valid three-block prose.")
            return _with_fixed_document_structure(parsed)
    log.warning("Overview prose pass: LLM missing or invalid; using neutral fallback.")
    return _with_fixed_document_structure(_neutral_fallback_overview(book_title, fn))


def _resolve_overview_prose_for_render(
    framework: Dict[str, Any],
    book_title: str,
    framework_name: str,
) -> Dict[str, str]:
    """Load stored overview prose for three LLM blocks; Document Structure is always template-fixed."""
    keys3 = ("problem", "core_argument", "method")
    fixed_ds = _fixed_document_structure_prose()

    def _merge_three(d: Dict[str, Any]) -> Optional[Dict[str, str]]:
        candidate = {k: _sanitize_overview_prose_block(d.get(k)) for k in keys3}
        if all(candidate[k] for k in keys3):
            return {**candidate, "document_structure": fixed_ds}
        return None

    raw = framework.get("overview_prose")
    if isinstance(raw, dict):
        merged = _merge_three(raw)
        if merged:
            return merged
    opj = framework.get("overview_prose_json")
    if isinstance(opj, str) and opj.strip():
        try:
            parsed = json.loads(opj)
            if isinstance(parsed, dict):
                merged = _merge_three(parsed)
                if merged:
                    return merged
        except json.JSONDecodeError:
            pass
    return _with_fixed_document_structure(_neutral_fallback_overview(book_title, framework_name))


def _distinct_page_numbers_from_nodes(nodes: List[Dict[str, Any]]) -> List[int]:
    """Collect plausible page numbers from node page_ref strings (citation footprint)."""
    found: set[int] = set()
    for n in nodes or []:
        pr = (n.get("page_ref") or "").strip()
        for m in re.finditer(r"\b(\d{1,4})\b", pr):
            try:
                p = int(m.group(1))
            except ValueError:
                continue
            if 1 <= p <= 32000:
                found.add(p)
    return sorted(found)


def _definitive_field_as_list(v: Any) -> List[str]:
    """Coerce a definitive_fields list-like value to clean strings (shared §9 gap scan + render)."""
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        parts = [p.strip() for p in re.split(r"[;,]", v) if p.strip()]
        return parts if parts else ([v.strip()] if v.strip() else [])
    s = str(v).strip()
    return [s] if s else []


def _filter_placeholder_list_strings(v: Any) -> List[str]:
    """Drop gap-style fillers from list fields (Symptoms, Watch for, …)."""
    return [x for x in _definitive_field_as_list(v) if not _text_looks_like_gap_placeholder(x)]


def _coverage_report_rows_template(
    book_meta: Dict[str, Any],
    cited_pages: List[int],
    book_title_fallback: str,
) -> List[List[str]]:
    """
    §10 Coverage Report table rows (template shape). Used by debug tooling; the
    definitive document export omits §10 until the client confirms coverage design.
    (#, Chapter/Section, Status, Notes). Uses structural analysis when present.
    """
    cited_set = set(cited_pages or [])
    sa = parse_structural_analysis(book_meta.get("structural_analysis"))
    chs = sa.get("chapters") if isinstance(sa, dict) else None
    rows: List[List[str]] = []

    def _clean_chapter_title(raw: Any) -> str:
        t = " ".join(str(raw or "").split()).strip()
        if not t:
            return ""
        # Remove common OCR/TOC noise artifacts while preserving true titles.
        t = re.sub(r"\.{3,}\s*\d{1,4}\s*$", "", t).strip()  # dot leaders + page
        t = re.sub(r"^\d+\s*[:.)-]\s*", "", t).strip()  # leading list index
        t = re.sub(r"\s{2,}", " ", t).strip(" -:;,.")
        # If title is clearly corrupted punctuation, treat as empty.
        alnum = sum(ch.isalnum() for ch in t)
        if len(t) < 4 or alnum < 3:
            return ""
        return t[:200]

    def _range_hit_count(a: int, b: int) -> int:
        if not cited_set:
            return 0
        return sum(1 for p in cited_set if a <= p <= b)
    if not isinstance(chs, list) or not chs:
        n = len(cited_set)
        note = (
            f"Citation footprint: {n} distinct page number(s) on nodes."
            if n
            else "No page numbers parsed from node citations; chapter mapping unavailable."
        )
        rows.append(["1", (book_title_fallback or "Book").strip() or "Book", "Partial", note])
        return rows
    idx = 0
    seen_titles: set[str] = set()
    for c in chs[:200]:
        if not isinstance(c, dict):
            continue
        title = _clean_chapter_title(c.get("title"))
        if not title:
            continue
        tkey = title.lower()
        if tkey in seen_titles:
            continue
        seen_titles.add(tkey)
        idx += 1
        sp, ep = c.get("start_page"), c.get("end_page")
        status = "Partial"
        notes = ""
        if sp is not None:
            try:
                a = int(sp)
                b = int(ep) if ep is not None else int(sp)
            except (TypeError, ValueError):
                a, b = 0, 0
            if a > b:
                a, b = b, a
            hit_count = _range_hit_count(a, b)
            if hit_count >= 2:
                status = "Extracted"
                notes = f"{hit_count} cited page(s) overlap this chapter region."
            elif hit_count == 1:
                status = "Partial"
                notes = "One cited page overlaps this chapter region."
            else:
                status = "Omitted"
                notes = "No cited pages in this region in extracted nodes."
        else:
            # Keep conservative status when page range is unknown.
            status = "Partial" if cited_set else "Omitted"
            notes = "Chapter page range unavailable in structural analysis."
        rows.append([str(idx), title[:200], status, notes[:280]])
    if not rows:
        rows.append(
            [
                "1",
                (book_title_fallback or "Book").strip() or "Book",
                "Partial",
                "Structural analysis listed no usable chapters.",
            ]
        )
    return rows


def render_definitive_document(framework: Dict[str, Any], book_meta: Optional[Dict[str, Any]] = None) -> str:
    """
    Phase 2 renderer: fixed 10-section document + dependency map tables.

    This renderer is deterministic: it uses node/edge structure and each node's `definitive_fields` (Phase 1).
    It does not change the mindmap nodes/edges; it only builds a markdown document for export.
    """
    book_meta = book_meta or {}
    nodes: List[Dict[str, Any]] = framework.get("nodes") or []
    edges: List[Dict[str, Any]] = framework.get("edges") or []

    node_by_id: Dict[int, Dict[str, Any]] = {}
    for n in nodes:
        nid = n.get("id")
        if nid is not None:
            try:
                node_by_id[int(nid)] = n
            except (TypeError, ValueError):
                continue

    def _node_type(n: Dict[str, Any]) -> str:
        return (n.get("node_type") or n.get("type") or "").strip().lower()

    def _page_ref(n: Dict[str, Any]) -> str:
        pr = (n.get("page_ref") or "").strip()
        return pr

    def _clean_title(t: str) -> str:
        return (t or "").strip()

    def _strip_step_prefix(title: str) -> str:
        # e.g. "Step 1: Foo" -> "Foo"
        s = (title or "").strip()
        s = re.sub(r"^step\s*\d+\s*:\s*", "", s, flags=re.IGNORECASE).strip()
        return s or title.strip()

    def _strip_warning_prefix(title: str) -> str:
        s = (title or "").strip()
        s = re.sub(r"^warning\s*:\s*", "", s, flags=re.IGNORECASE).strip()
        return s or title.strip()

    def _strip_constraint_prefix(title: str) -> str:
        s = (title or "").strip()
        s = re.sub(r"^constraint\s*:\s*", "", s, flags=re.IGNORECASE).strip()
        return s or title.strip()

    def _get_def_fields(n: Dict[str, Any]) -> Dict[str, Any]:
        df = n.get("definitive_fields")
        return df if isinstance(df, dict) else {}

    def _get_field(df: Dict[str, Any], key: str, default: str = "") -> Any:
        v = df.get(key)
        if v is None:
            return default
        return v

    def _append_italic_source_epistemic_block(parts: List[str], df: Dict[str, Any], page: str) -> None:
        """Sections 4–7 template: _Source, ES/EC/CT/CN, Tag justifications (non-definition nodes)."""
        es = _get_field(df, "ES", "") or "Not stated in source"
        ec = _get_field(df, "EC", "") or "Not stated in source"
        ct = _get_field(df, "CT", "") or "Not stated in source"
        cn = _get_field(df, "CN", "") or "Not stated in source"
        tj = df.get("Tag justifications") if isinstance(df.get("Tag justifications"), dict) else {}
        sq = df.get("Source Quote") if isinstance(df.get("Source Quote"), dict) else {}
        quote = (sq.get("Quote") or "").strip()
        core_sentence = (sq.get("Core Sentence") or "").strip()
        quote_md = quote
        if quote and core_sentence and core_sentence in quote:
            quote_md = quote.replace(core_sentence, f"**{core_sentence}**", 1)
        parts.append(FW_EPISTEMIC_BEGIN)
        if quote_md:
            parts.append(f"**_Source ({page}):_** {quote_md}")
        else:
            parts.append(f"**_Source ({page}):_** Not stated in source")
        parts.append(f"**ES:** {es} **EC:** {ec} **CT:** {ct} **CN:** {cn}")
        parts.append(
            f"**Tag justifications:** ES: {tj.get('ES') or 'Not stated in source'}; "
            f"EC: {tj.get('EC') or 'Not stated in source'}; "
            f"CT: {tj.get('CT') or 'Not stated in source'}; "
            f"CN: {tj.get('CN') or 'Not stated in source'}"
        )
        parts.append(FW_EPISTEMIC_END)

    # ---------- dependency analysis ----------
    step_nodes = [n for n in nodes if _node_type(n) == "step" and n.get("id") is not None]
    step_ids = {int(n["id"]) for n in step_nodes}
    step_sort: Dict[int, int] = {}
    for n in step_nodes:
        try:
            step_sort[int(n["id"])] = int(n.get("sort_order") or 0)
        except (TypeError, ValueError):
            step_sort[int(n.get("id"))] = 0

    leads_to_edges: List[Tuple[int, int]] = []
    for e in edges:
        et = (e.get("edge_type") or "").strip().lower()
        if et != "leads_to":
            continue
        try:
            a = int(e.get("from_node_id"))
            b = int(e.get("to_node_id"))
        except (TypeError, ValueError):
            continue
        if a in step_ids and b in step_ids:
            leads_to_edges.append((a, b))

    # Topological order for sequential steps; fallback to sort_order if needed.
    adj: Dict[int, List[int]] = {sid: [] for sid in step_ids}
    indeg: Dict[int, int] = {sid: 0 for sid in step_ids}
    for a, b in leads_to_edges:
        adj.setdefault(a, []).append(b)
        indeg[b] = indeg.get(b, 0) + 1

    # Kahn's algorithm (deterministic tie-break by sort_order then id).
    order: List[int] = []
    ready = sorted([sid for sid, d in indeg.items() if d == 0], key=lambda x: (step_sort.get(x, 0), x))
    indeg_copy = dict(indeg)
    while ready:
        cur = ready.pop(0)
        order.append(cur)
        for nxt in sorted(adj.get(cur, []), key=lambda x: (step_sort.get(x, 0), x)):
            indeg_copy[nxt] -= 1
            if indeg_copy[nxt] == 0:
                ready.append(nxt)
        ready.sort(key=lambda x: (step_sort.get(x, 0), x))

    if len(order) != len(step_ids) or not order:
        order = sorted(list(step_ids), key=lambda x: (step_sort.get(x, 0), x))

    step_rank: Dict[int, int] = {sid: i + 1 for i, sid in enumerate(order)}

    reverse_adj: Dict[int, List[int]] = {sid: [] for sid in step_ids}  # predecessor lists
    for a, b in leads_to_edges:
        reverse_adj.setdefault(b, []).append(a)

    def _immediate_predecessor(to_sid: int) -> Optional[int]:
        preds = reverse_adj.get(to_sid, [])
        if not preds:
            return None
        # Choose the predecessor with the highest rank (closest prior step).
        return sorted(preds, key=lambda x: step_rank.get(x, 0), reverse=True)[0]

    def _required_before(to_sid: int) -> List[int]:
        # All predecessors (transitive), excluding itself.
        seen: set[int] = set()
        stack = list(reverse_adj.get(to_sid, []))
        while stack:
            cur = stack.pop()
            if cur in seen or cur == to_sid:
                continue
            seen.add(cur)
            stack.extend(reverse_adj.get(cur, []))
        return sorted(list(seen), key=lambda x: step_rank.get(x, 0))

    # Helpers to build canonical display names consistent across sections.
    def _step_display(sid: int) -> str:
        sn = node_by_id.get(sid) or {}
        verb = _strip_step_prefix(_clean_title(sn.get("title")))
        return f"Step {step_rank.get(sid, 0)}: {verb}"

    def _principle_display(n: Dict[str, Any]) -> str:
        t = _clean_title(n.get("title"))
        return t

    def _warning_display(n: Dict[str, Any]) -> str:
        t = _strip_warning_prefix(_clean_title(n.get("title")))
        return f"Warning: {t}"

    def _constraint_display(n: Dict[str, Any]) -> str:
        t = _strip_constraint_prefix(_clean_title(n.get("title")))
        return f"Constraint: {t}"

    def _case_display(n: Dict[str, Any]) -> str:
        return _clean_title(n.get("title"))

    # Index edges for dependency map
    definition_ids: set[int] = {
        int(n.get("id"))
        for n in nodes
        if _node_type(n) == "definition" and n.get("id") is not None
    }
    used_in_steps_by_def: Dict[int, List[int]] = {did: [] for did in definition_ids}
    used_in_warnings_by_def: Dict[int, List[int]] = {did: [] for did in definition_ids}
    used_in_constraints_by_def: Dict[int, List[int]] = {did: [] for did in definition_ids}

    warnings_to_step: Dict[int, List[int]] = {sid: [] for sid in step_ids}
    constraints_to_step: Dict[int, List[int]] = {sid: [] for sid in step_ids}
    cases_to_step: Dict[int, List[int]] = {sid: [] for sid in step_ids}
    principles_to_step: Dict[int, List[int]] = {sid: [] for sid in step_ids}
    governing_principles_to_step: Dict[int, List[int]] = {sid: [] for sid in step_ids}
    operational_principles_to_step: Dict[int, List[int]] = {sid: [] for sid in step_ids}

    for e in edges:
        et = (e.get("edge_type") or "").strip().lower()
        try:
            a = int(e.get("from_node_id"))
            b = int(e.get("to_node_id"))
        except (TypeError, ValueError):
            continue
        # Used in (definition -> step/warning/constraint)
        if et == "uses_definition":
            if a in node_by_id and _node_type(node_by_id[a]) == "definition" and b in node_by_id:
                def_id = a
                consumer_id = b
            elif b in node_by_id and _node_type(node_by_id[b]) == "definition" and a in node_by_id:
                def_id = b
                consumer_id = a
            else:
                continue

            ctype = _node_type(node_by_id.get(consumer_id) or {})
            if ctype == "step" and def_id in used_in_steps_by_def:
                used_in_steps_by_def[def_id].append(consumer_id)
            elif ctype == "warning" and def_id in used_in_warnings_by_def:
                used_in_warnings_by_def[def_id].append(consumer_id)
            elif ctype == "constraint" and def_id in used_in_constraints_by_def:
                used_in_constraints_by_def[def_id].append(consumer_id)
            continue

        if b not in step_ids:
            continue
        if et == "warns" and a in node_by_id and _node_type(node_by_id[a]) == "warning":
            warnings_to_step[b].append(a)
        elif et == "constrains" and a in node_by_id and _node_type(node_by_id[a]) == "constraint":
            constraints_to_step[b].append(a)
        elif et in ("implemented_by", "drives_step") and a in node_by_id and _node_type(node_by_id[a]) == "principle":
            principles_to_step[b].append(a)
            tier = (_get_field(_get_def_fields(node_by_id[a]), "Tier", "") or "").strip().lower()
            if "govern" in tier:
                governing_principles_to_step[b].append(a)
            elif "operational" in tier:
                operational_principles_to_step[b].append(a)
            else:
                # If Tier is missing, treat as operational by default to keep both columns populated.
                operational_principles_to_step[b].append(a)
        elif et == "supports" and a in node_by_id and _node_type(node_by_id[a]) == "principle" and b in step_ids:
            # Rule 30: Governing / principle linkage may appear as supports(principle→step) in some LLM outputs.
            principles_to_step[b].append(a)
            tier = (_get_field(_get_def_fields(node_by_id[a]), "Tier", "") or "").strip().lower()
            if "govern" in tier:
                governing_principles_to_step[b].append(a)
            elif "operational" in tier:
                operational_principles_to_step[b].append(a)
            else:
                operational_principles_to_step[b].append(a)
        elif et == "supports" and a in node_by_id and _node_type(node_by_id[a]) in ("case", "example"):
            cases_to_step[b].append(a)

    def _dedupe_preserve_order(ids: List[int]) -> List[int]:
        seen: set[int] = set()
        out: List[int] = []
        for i in ids:
            if i in seen:
                continue
            seen.add(i)
            out.append(i)
        return out

    for _dmap in (used_in_steps_by_def, used_in_warnings_by_def, used_in_constraints_by_def):
        for _k in list(_dmap.keys()):
            _dmap[_k] = _dedupe_preserve_order(_dmap[_k])

    for sid in step_ids:
        principles_to_step[sid] = _dedupe_preserve_order(principles_to_step[sid])
        governing_principles_to_step[sid] = _dedupe_preserve_order(governing_principles_to_step[sid])
        operational_principles_to_step[sid] = _dedupe_preserve_order(operational_principles_to_step[sid])
        warnings_to_step[sid] = _dedupe_preserve_order(warnings_to_step[sid])
        constraints_to_step[sid] = _dedupe_preserve_order(constraints_to_step[sid])
        cases_to_step[sid] = _dedupe_preserve_order(cases_to_step[sid])

    # ---------- render helpers ----------
    def _md_table(headers: List[str], rows: List[List[str]]) -> str:
        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        row_lines = []
        for r in rows:
            # Ensure all cells are strings and don't contain newlines.
            cells = [(str(c).replace("\n", " ").strip() if c is not None else "") for c in r]
            row_lines.append("| " + " | ".join(cells) + " |")
        return "\n".join([header_line, sep_line] + row_lines)

    # ---------- Section 1: Metadata ----------
    book_title = _clean_title(book_meta.get("title") or "Unknown book")
    author = _clean_title(book_meta.get("author") or "Not stated in source")
    edition_isbn = _clean_title(book_meta.get("edition_isbn") or "Not stated in source")
    page_numbering_basis = _clean_title(book_meta.get("page_numbering_basis") or "Digital")
    target_audience = _clean_title(book_meta.get("target_audience") or "Not stated in source")
    framework_version = "v1"
    generation_date = datetime.now().strftime("%Y-%m-%d")

    # §1 Metadata — Definitive_Framework_Template_Fina.md (no separate "Framework Name" row).
    metadata_table = "\n".join(
        [
            f"| **Book Title** | {book_title} |",
            "| --- | --- |",
            f"| **Author** | {author} |",
            f"| **Edition / ISBN** | {edition_isbn} |",
            f"| **Page Numbering Basis** | {page_numbering_basis} |",
            f"| **Target Audience** | {target_audience} |",
            f"| **Framework Version** | {framework_version} |",
            f"| **Generation Date** | {generation_date} |",
        ]
    )

    # ---------- Section 2: Overview ----------
    # Rendered later after we classify nodes and compute step order.
    overview_block: str = ""

    # ---------- classify nodes ----------
    definitions = sorted([n for n in nodes if _node_type(n) == "definition"], key=lambda x: (x.get("sort_order", 0), x.get("id", 0)))
    principles = sorted([n for n in nodes if _node_type(n) == "principle"], key=lambda x: (x.get("sort_order", 0), x.get("id", 0)))
    warnings_nodes = sorted([n for n in nodes if _node_type(n) == "warning"], key=lambda x: (x.get("sort_order", 0), x.get("id", 0)))
    constraints_nodes = sorted([n for n in nodes if _node_type(n) == "constraint"], key=lambda x: (x.get("sort_order", 0), x.get("id", 0)))
    # Case/example nodes are embedded in Steps (In Practice) when possible; we do not render separately.

    governing_principles = []
    operational_principles = []
    for p in principles:
        df = _get_def_fields(p)
        tier = (df.get("Tier") or "").strip().lower()
        if "govern" in tier:
            governing_principles.append(p)
        else:
            operational_principles.append(p)

    steps_in_order = [node_by_id[sid] for sid in order if sid in node_by_id]

    core_principle = governing_principles[0] if governing_principles else (principles[0] if principles else None)
    core_principle_stmt = _get_field(_get_def_fields(core_principle or {}), "Statement", "") if core_principle else ""

    claimed_scope = sanitize_definitive_scope_text(
        _strip_claimed_scope_labels(
            _clean_title(framework.get("claimed_scope") or "Not stated in source")
        ),
        max_len=_SCOPE_MAX_CLAIMED,
        sentence_boundary=True,
    )
    evidenced_scope = sanitize_definitive_scope_text(
        _clean_title(framework.get("evidenced_scope") or "Not stated in source"),
        max_len=_SCOPE_MAX_EVIDENCED,
        sentence_boundary=True,
    )

    fw_name = _clean_title(framework.get("name") or "Framework")
    ov = _resolve_overview_prose_for_render(framework, book_title, fw_name)
    problem_sentence = ov["problem"]
    core_argument_sentence = ov["core_argument"]
    method_sentence = ov["method"]
    doc_struct_sentence = ov["document_structure"]

    overview_block = "\n".join(
        [
            "### The Problem",
            problem_sentence,
            "",
            "### The Core Argument",
            core_argument_sentence,
            "",
            "| Scope | Applicability |",
            "| --- | --- |",
            "| Claimed Scope | " + claimed_scope + " |",
            "| Evidenced Scope | " + evidenced_scope + " |",
            "",
            "### The Method",
            method_sentence,
            "",
            "### Document Structure",
            doc_struct_sentence,
        ]
    ).strip()

    # Order warnings/constraints by step rank they attach to (via definitive_fields or depends_on_node_id).
    def _best_step_rank_for_node(n: Dict[str, Any]) -> int:
        dep_sid = n.get("depends_on_node_id")
        try:
            if dep_sid is not None:
                dep_sid = int(dep_sid)
                return step_rank.get(dep_sid, 10_000)
        except (TypeError, ValueError):
            pass
        return 10_000

    warnings_nodes_sorted = sorted(warnings_nodes, key=lambda x: _best_step_rank_for_node(x))
    constraints_nodes_sorted = sorted(constraints_nodes, key=lambda x: _best_step_rank_for_node(x))

    # ---------- render node sections ----------
    def _render_definition(n: Dict[str, Any]) -> str:
        df = _get_def_fields(n)
        term = _clean_title(n.get("title"))
        page = _page_ref(n)
        header = f"**{term}**" + (f" ({page})" if page else "")
        boundary = _get_field(df, "Boundary", "") or ""
        requires_display = format_requires_display(_get_field(df, "Requires", []))
        def_src = effective_definition_source(str(_get_field(df, "Definition Source", "") or ""))
        op_test = effective_operational_test(str(_get_field(df, "Operational Test", "") or ""))
        es = _get_field(df, "ES", "")
        ec = _get_field(df, "EC", "")
        ct = _get_field(df, "CT", "")
        cn = _get_field(df, "CN", "")
        es = es or "Not stated in source"
        ec = ec or "Not stated in source"
        ct = ct or "Not stated in source"
        cn = cn or "Not stated in source"
        tj = (
            df.get("Tag justifications")
            if isinstance(df.get("Tag justifications"), dict)
            else (df.get("Tag Justifications") if isinstance(df.get("Tag Justifications"), dict) else {})
        )
        sq = (
            df.get("Source Quote")
            if isinstance(df.get("Source Quote"), dict)
            else (df.get("Source") if isinstance(df.get("Source"), dict) else {})
        )
        quote = (sq.get("Quote") or "").strip()
        core_sentence = (sq.get("Core Sentence") or "").strip()
        quote_md = quote
        if quote and core_sentence and core_sentence in quote:
            # Bold the core sentence inside the quote.
            quote_md = quote.replace(core_sentence, f"**{core_sentence}**", 1)

        definition_text = (n.get("content") or "").strip()
        parts = [fw_heading_marker("definition"), header]
        if definition_text:
            parts.append(f"**Definition:** {definition_text}")
        if not should_omit_optional_prose_block(boundary):
            parts.append(f"**Boundary:** {boundary.strip()}")
        parts.append(f"**Requires:** {requires_display}")
        parts.append(f"**Definition Source:** {def_src}")
        parts.append(f"**Operational Test:** {op_test}")

        parts.append(FW_EPISTEMIC_BEGIN)
        if quote_md:
            parts.append(f"**_Source ({page}):_** {quote_md}")
        else:
            parts.append(f"**_Source ({page}):_** Not stated in source")

        # v2 Rule 28: same epistemic line shape for every definition.
        parts.append(
            f"**ES:** {es or _RENDER_PLACEHOLDER}  **EC:** {ec or _RENDER_PLACEHOLDER}  "
            f"**CT:** {ct or _RENDER_PLACEHOLDER}  **CN:** {cn or _RENDER_PLACEHOLDER}"
        )

        # Tag justifications (one sentence per tag, aligned with ES/EC/CT/CN).
        parts.append(
            f"**Tag justifications:** ES: {tj.get('ES') or 'Not stated in source'}; "
            f"EC: {tj.get('EC') or 'Not stated in source'}; "
            f"CT: {tj.get('CT') or 'Not stated in source'}; "
            f"CN: {tj.get('CN') or 'Not stated in source'}"
        )
        parts.append(FW_EPISTEMIC_END)

        # Used in: computed deterministically from typed `uses_definition` edges.
        # No per-group headings (Steps:/Warning:/Constraint:) — each item already carries its type label.
        nid = n.get("id")
        used_parts: List[str] = []
        if isinstance(nid, int) and nid in used_in_steps_by_def:
            used_steps = used_in_steps_by_def.get(nid) or []
            used_warnings = used_in_warnings_by_def.get(nid) or []
            used_constraints = used_in_constraints_by_def.get(nid) or []
            if used_steps:
                used_parts.append(", ".join([_step_display(sid) for sid in used_steps]))
            if used_warnings:
                used_parts.append(", ".join([_warning_display(node_by_id[w]) for w in used_warnings if w in node_by_id]))
            if used_constraints:
                used_parts.append(", ".join([_constraint_display(node_by_id[c]) for c in used_constraints if c in node_by_id]))

        if used_parts:
            parts.append("**Used in:** " + "; ".join(used_parts))

        return wrap_fw_block("definition", "\n".join(parts).strip())

    def _render_principle(n: Dict[str, Any]) -> str:
        df = _get_def_fields(n)
        statement = _get_field(df, "Statement", "") or (n.get("content") or "").strip()
        governs = _get_field(df, "Governs", "")
        arg_chain = _get_field(df, "Argument Chain", "")
        page = _page_ref(n)
        header = f"**{_clean_title(n.get('title'))}**" + (f" ({page})" if page else "")
        parts = [fw_heading_marker("principle"), header]
        if statement.strip():
            parts.append(f"**Statement:** {statement.strip()}")
        if governs.strip() and not should_omit_optional_prose_block(governs):
            parts.append(f"**Governs:** {governs.strip()}")
        if arg_chain.strip() and not should_omit_optional_prose_block(arg_chain):
            parts.append(f"**Argument Chain:** {arg_chain.strip()}")
        _append_italic_source_epistemic_block(parts, df, page)
        return wrap_fw_block("principle", "\n".join(parts).strip())

    def _render_in_practice_table(step_df: Dict[str, Any]) -> str:
        ip = step_df.get("In Practice")
        if not in_practice_has_substance(ip):
            return ""
        ip = ip if isinstance(ip, dict) else {}
        case = str(ip.get("Case") or "").strip()
        ctx = str(ip.get("Context") or "").strip()
        action = str(ip.get("Action") or "").strip()
        outcome = str(ip.get("Outcome") or "").strip()
        lesson = str(ip.get("Lesson") or "").strip()
        tag = str(ip.get("Tag") or "").strip()
        # Keep table cells plain (avoid inline markdown) for DOCX compatibility.
        rows = [
            ["Case", case],
            ["Context", ctx],
            ["Action", action],
            ["Outcome", outcome],
            ["Lesson", lesson],
            ["Tag", tag],
        ]
        return _md_table(["Field", "Value"], rows)

    def _render_step(n: Dict[str, Any], step_num: int) -> str:
        df = _get_def_fields(n)
        verb = _strip_step_prefix(_clean_title(n.get("title")))
        page = _page_ref(n)
        header = f"**Step {step_num}: {verb}**" + (f" ({page})" if page else "")
        action = _get_field(df, "Action", "") or (n.get("content") or "").strip()
        dep_raw = (_get_field(df, "Depends on", "") or "").strip()
        dep_sid = n.get("depends_on_node_id")
        derived_dep = ""
        if isinstance(dep_sid, int) and dep_sid in step_rank:
            derived_dep = _step_display(int(dep_sid))
        depends_on_line = format_depends_on_display(dep_raw, derived_step_label=derived_dep)
        governed_by = filter_reference_list_items(_get_field(df, "Governed by", []))
        watch_for = filter_reference_list_items(_get_field(df, "Watch for", []))
        constrained_by = filter_reference_list_items(_get_field(df, "Constrained by", []))
        done_when = effective_done_when(str(_get_field(df, "Done When", "") or ""))
        common_mistakes = filter_reference_list_items(_get_field(df, "Common Mistakes", []))
        parts = [fw_heading_marker("step"), header]
        if action.strip():
            parts.append(f"**Action:** {action.strip()}")
        parts.append(f"**Depends on:** {depends_on_line}")
        if governed_by:
            parts.append("**Governed by:** " + ", ".join(governed_by))
        if watch_for:
            parts.append("**Watch for:** " + ", ".join(watch_for))
        if constrained_by:
            parts.append("**Constrained by:** " + ", ".join(constrained_by))
        parts.append(f"**Done When:** {done_when}")
        if common_mistakes:
            parts.append("**Common Mistakes:**")
            for i, cm in enumerate(common_mistakes, 1):
                parts.append(f"{i}. {cm}")
        in_practice_table = _render_in_practice_table(df)
        if in_practice_table:
            parts.append("**In Practice**")
            parts.append(in_practice_table)
        _append_italic_source_epistemic_block(parts, df, page)
        return wrap_fw_block("step", "\n".join(parts).strip())

    def _render_warning(n: Dict[str, Any]) -> str:
        df = _get_def_fields(n)
        name = _strip_warning_prefix(_clean_title(n.get("title")))
        page = _page_ref(n)
        header = f"**Warning: {name}**" + (f" ({page})" if page else "")
        parts = [fw_heading_marker("warning"), header]
        err = (_get_field(df, "The error", "") or "").strip()
        if not err:
            err = (n.get("content") or "").strip().split("\n")[0][:220] if n.get("content") else ""
        parts.append(f"**The error:** {err}")
        conseq = (_get_field(df, "Consequence", "") or "").strip()
        if conseq and _text_looks_like_gap_placeholder(conseq):
            conseq = ""
        if conseq.strip() and not should_omit_optional_prose_block(conseq):
            parts.append(f"**Consequence:** {conseq.strip()}")
        symptoms = filter_reference_list_items(_get_field(df, "Symptoms", []))
        if symptoms:
            parts.append("**Symptoms:**")
            for s in symptoms:
                parts.append(f"- {s}")
        highest_at = (_get_field(df, "Highest risk at", "") or "").strip()
        if not should_omit_highest_risk_or_affects(highest_at):
            parts.append(f"**Highest risk at:** {highest_at.strip()}")
        tension_pair = (_get_field(df, "Tension pair", "") or "").strip()
        if tension_pair and _text_looks_like_gap_placeholder(tension_pair):
            tension_pair = ""
        if tension_pair.strip() and not should_omit_optional_prose_block(tension_pair):
            parts.append(f"**Tension pair:** {tension_pair.strip()}")
        _append_italic_source_epistemic_block(parts, df, page)
        return wrap_fw_block("warning", "\n".join(parts).strip())

    def _render_constraint(n: Dict[str, Any]) -> str:
        df = _get_def_fields(n)
        name = _strip_constraint_prefix(_clean_title(n.get("title")))
        page = _page_ref(n)
        header = f"**Constraint: {name}**" + (f" ({page})" if page else "")
        parts = [fw_heading_marker("constraint"), header]
        cond = (_get_field(df, "The condition", "") or "").strip()
        if not cond:
            cond = (n.get("content") or "").strip().split("\n")[0][:220] if n.get("content") else ""
        parts.append(f"**The condition:** {cond}")
        if_absent = (_get_field(df, "If absent", "") or "").strip()
        if if_absent and _text_looks_like_gap_placeholder(if_absent):
            if_absent = ""
        if if_absent.strip() and not should_omit_optional_prose_block(if_absent):
            parts.append(f"**If absent:** {if_absent.strip()}")
        mitigation = effective_mitigation(str(_get_field(df, "Mitigation", "") or ""))
        parts.append(f"**Mitigation:** {mitigation}")
        affects = (_get_field(df, "Affects", "") or "").strip()
        if not should_omit_highest_risk_or_affects(affects):
            parts.append(f"**Affects:** {affects.strip()}")
        tension_pair = (_get_field(df, "Tension pair", "") or "").strip()
        if tension_pair and _text_looks_like_gap_placeholder(tension_pair):
            tension_pair = ""
        if tension_pair.strip() and not should_omit_optional_prose_block(tension_pair):
            parts.append(f"**Tension pair:** {tension_pair.strip()}")
        _append_italic_source_epistemic_block(parts, df, page)
        return wrap_fw_block("constraint", "\n".join(parts).strip())

    def _map_element_label(nid: int) -> str:
        n = node_by_id.get(int(nid))
        if not n:
            return f"Node {nid}"
        nt = _node_type(n)
        if nt == "definition":
            return _clean_title(n.get("title"))
        if nt == "principle":
            return _principle_display(n)
        if nt == "step" and int(nid) in step_rank:
            return _step_display(int(nid))
        if nt == "warning":
            return _warning_display(n)
        if nt == "constraint":
            return _constraint_display(n)
        return _clean_title(n.get("title"))

    # ---------- Section 8: Dependency Map ----------
    sequential_rows: List[List[str]] = []
    for sid in order:
        step_name = _step_display(sid)
        pred = _immediate_predecessor(sid)
        depends_on_name = _step_display(pred) if pred is not None else ""
        required = [_step_display(x) for x in _required_before(sid)]
        sequential_rows.append([step_name, depends_on_name, ", ".join(required)])
    sequential_table = _md_table(["Step", "Depends On", "Required Before"], sequential_rows)

    governing_rows: List[List[str]] = []
    for sid in order:
        step_name = _step_display(sid)
        gov_princs = [_principle_display(node_by_id[p]) for p in governing_principles_to_step.get(sid, [])]
        op_princs = [_principle_display(node_by_id[p]) for p in operational_principles_to_step.get(sid, [])]
        warn_names = [_warning_display(node_by_id[w]) for w in warnings_to_step.get(sid, [])]
        cons_names = [_constraint_display(node_by_id[c]) for c in constraints_to_step.get(sid, [])]
        case_names = [_case_display(node_by_id[cs]) for cs in cases_to_step.get(sid, [])]
        governing_rows.append(
            [
                step_name,
                ", ".join(gov_princs),
                ", ".join(op_princs),
                ", ".join(warn_names),
                ", ".join(cons_names),
                ", ".join(case_names),
            ]
        )
    governing_table = _md_table(
        ["Step", "Gov. Princ.", "Op. Princ.", "Warnings", "Constraints", "Cases"], governing_rows
    )

    tension_rows: List[List[str]] = []
    tension_keys: set[Tuple[str, str, str]] = set()

    def _norm_map_key(s: str) -> str:
        return " ".join((s or "").split()).strip().lower()

    def _tension_key(cols: List[str]) -> Tuple[str, str, str]:
        a = _norm_map_key(cols[0]) if len(cols) > 0 else ""
        b = _norm_map_key(cols[1]) if len(cols) > 1 else ""
        c = _norm_map_key(cols[2]) if len(cols) > 2 else ""
        pair = tuple(sorted([a, b])) if a and b else (a, b)
        return (pair[0], pair[1], c)

    # v2 §G: tension from explicit edges (mindmap / taxonomy may emit these types).
    for e in edges:
        et = (e.get("edge_type") or "").strip().lower()
        if et not in ("tension", "tension_pair", "opposes"):
            continue
        try:
            a = int(e.get("from_node_id"))
            b = int(e.get("to_node_id"))
        except (TypeError, ValueError):
            continue
        if a not in node_by_id or b not in node_by_id:
            continue
        la, lb = _map_element_label(a), _map_element_label(b)
        why = (e.get("why") or "").strip()
        if should_omit_optional_prose_block(why):
            why = ""
        row3 = [la, lb, why]
        tk = _tension_key(row3)
        if tk in tension_keys:
            continue
        tension_keys.add(tk)
        tension_rows.append(row3)

    # Tension pair strings on nodes (often "A | B | balance").
    for n in nodes:
        df = _get_def_fields(n)
        tp = (_get_field(df, "Tension pair", "") or "").strip()
        if not tp or _text_looks_like_gap_placeholder(tp):
            continue
        segs = [s.strip() for s in re.split(r"\s*\|\s*", tp) if s.strip()]
        if len(segs) < 3 and len(segs) == 1 and re.search(r"\s+-\s+", tp):
            dash_segs = [s.strip() for s in re.split(r"\s+-\s+", tp) if s.strip()]
            if len(dash_segs) >= 2:
                segs = dash_segs[:3]
        if len(segs) >= 3:
            row3 = [segs[0], segs[1], segs[2]]
        elif len(segs) == 2:
            row3 = [segs[0], segs[1], ""]
        else:
            nt = _node_type(n)
            if nt == "warning":
                label = _warning_display(n)
            elif nt == "constraint":
                label = _constraint_display(n)
            else:
                label = _clean_title(n.get("title"))
            row3 = [label, "", segs[0]]
        tk = _tension_key(row3)
        if tk in tension_keys:
            continue
        tension_keys.add(tk)
        tension_rows.append(row3)

    if not tension_rows:
        tension_rows = [["", "", ""]]
    tension_table = _md_table(["Element A", "Element B", "Balance Point"], tension_rows)

    # §8 Dependency Map — template has 8A–8C only (definitional uses live in §3 **Used in:**).
    dependency_map_md = "\n".join(
        [
            "### 8A Sequential Dependencies",
            sequential_table,
            "",
            "### 8B Governing Relationships",
            governing_table,
            "",
            "### 8C Tension Pairs",
            tension_table,
        ]
    ).strip()

    # ---------- Section 9 & 10 (v2 §I / §J — scope, limits, gaps, coverage) ----------
    def _gather_acknowledged_gaps() -> List[str]:
        """§9C: aggregate gap signals from definitive_fields (Rules 14–16, 21–22, 31)."""
        out: List[str] = []
        seen: set[str] = set()

        def add_gap(msg: str) -> None:
            k = " ".join(msg.split()).lower()[:280]
            if k in seen or len(out) >= 40:
                return
            seen.add(k)
            out.append(msg)

        for n in nodes:
            title = (n.get("title") or "").strip()
            if not title:
                continue
            df = _get_def_fields(n)
            if not df:
                continue
            nt = _node_type(n)

            explicit_gap = False
            for v in df.values():
                if isinstance(v, str):
                    low = v.lower().strip()
                    if low.startswith("the book does not specify") or low.startswith("the book does not provide"):
                        explicit_gap = True
                        break
            if explicit_gap:
                add_gap(
                    f"**{title}** — excerpt uses explicit “book does not specify / provide” wording for at least one template field."
                )

            if nt == "warning":
                sym_ok = _filter_placeholder_list_strings(_get_field(df, "Symptoms", []))
                if len(sym_ok) < 2:
                    add_gap(
                        f"**{title}** (warning) — fewer than two substantive **Symptoms** grounded in the source (v2 Rule 21)."
                    )

            if nt == "constraint":
                mit = (_get_field(df, "Mitigation", "") or "").strip()
                if _text_looks_like_gap_placeholder(mit):
                    add_gap(
                        f"**{title}** (constraint) — **Mitigation** missing or not evidenced (v2 Rule 22)."
                    )

            if nt == "definition":
                op_test = (_get_field(df, "Operational Test", "") or "").strip()
                if _text_looks_like_gap_placeholder(op_test):
                    add_gap(
                        f"**{title}** (definition) — **Operational Test** is missing or not checkable from the excerpt."
                    )

            if nt == "step":
                dw = (_get_field(df, "Done When", "") or "").strip()
                if _text_looks_like_gap_placeholder(dw):
                    add_gap(
                        f"**{title}** (step) — **Done When** is missing or not expressed as observable completion criteria."
                    )

        if not out:
            out.append(
                "No per-node gap flags were detected in definitive fields; the excerpt may still omit content outside the retrieval window."
            )
        return out

    acknowledged_gaps = _gather_acknowledged_gaps()

    scope_conditions = _clip_sentences(core_principle_stmt) or (
        "Scope applies when the governing principles’ conditions are met in the practitioner’s context."
    )

    methodological_limits_parts: List[str] = [
        "_What can go wrong with the method itself._",
        "",
        "Execution is unsafe when **Warnings**’ **Symptoms** appear, when **Constraints** are violated, or when **Steps** are skipped; use **§8** to trace dependencies.",
        "This artifact is excerpt-limited: it reflects retrieved spans, not necessarily the entire book.",
    ]

    internal_tensions_md = "\n".join(
        [
            "| **Claim A (p.__)** | **Claim B (p.__)** | **Resolution** |",
            "| --- | --- | --- |",
            "",
            "No internal tensions identified.",
        ]
    ).strip()

    scope_md = "\n".join(
        [
            "### 9A Scope conditions",
            scope_conditions,
            "",
            "### 9B Methodological limits",
            *methodological_limits_parts,
            "",
            "### 9C Acknowledged gaps",
            "_Concepts named but not operationalized (from definitions, steps, constraints, and coverage)._",
            "",
            *[f"- {g}" for g in acknowledged_gaps],
            "",
            "### 9D Internal tensions",
            internal_tensions_md,
        ]
    ).strip()

    # ---------- Assemble full document ----------
    # §10 Coverage Report is on hold (export is sections 1–9 only) pending client input.
    parts: List[str] = []
    parts.extend(
        [
            "## 1. Metadata",
            metadata_table,
            "",
            "## 2. Overview",
            overview_block,
            "",
            "## 3. Definitions",
            *([_render_definition(d) for d in definitions] if definitions else ["_No definitions extracted._"]),
            "",
            "## 4. Principles",
            "### 4A Governing Principles",
            *([_render_principle(p) for p in governing_principles] if governing_principles else ["_No governing principles extracted._"]),
            "",
            "### 4B Operational Principles",
            *([_render_principle(p) for p in operational_principles] if operational_principles else ["_No operational principles extracted._"]),
            "",
            "## 5. Steps",
            *([_render_step(sid_node, step_rank.get(int(sid_node.get('id')), 0)) for sid_node in steps_in_order] if steps_in_order else ["_No steps extracted._"]),
            "",
            "## 6. Warnings",
            *([_render_warning(w) for w in warnings_nodes_sorted] if warnings_nodes_sorted else ["_No warnings extracted._"]),
            "",
            "## 7. Constraints",
            *([_render_constraint(c) for c in constraints_nodes_sorted] if constraints_nodes_sorted else ["_No constraints extracted._"]),
            "",
            "## 8. Dependency Map",
            dependency_map_md,
            "",
            "## 9. Scope and Limits",
            scope_md,
        ]
    )
    return "\n".join(parts).strip()
