import re
import logging
from typing import Callable, List, Dict, Any, Optional, Tuple

from .database import BookDatabase
from . import framework as langchain_framework

# Node types for structured framework (Option B)
FRAMEWORK_NODE_TYPES = (
    "section",
    "definition",
    "principle",
    "step",
    "warning",
    "constraint",
    "case",
    "example",
)

# Main node types that get context (and epistemic labels)
MAIN_NODE_TYPES = ("definition", "principle", "step", "warning", "constraint", "case", "example")
CONTEXT_MAX_CHARS = 500
# Max chars for contiguous page-window excerpt stored on each node (raw book text; definitive pass refines)
CONTEXT_WINDOW_MAX_CHARS = 3500


def _normalize_book_excerpt(text: str) -> str:
    """Light cleanup for stored raw excerpt: no LLM. Preserves wording; normalizes whitespace and control chars."""
    if not text:
        return ""
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    s = "".join(c for c in s if c == "\n" or c == "\t" or ord(c) >= 32)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# Canonical persisted framework pipeline (see BookManager.generate_framework / regenerate_framework):
#   prepare_framework_nodes (extract + definitive_fields) → DB nodes → mindmap edges →
#   run_agents_over_graph → definitive document → mechanical audit → (Phase 4) judgment audit → optional re-extract loop.
# Do not reintroduce a parallel path that skips run_definitive_fields_pass or edge-aware agents.

# Handles question answering and framework extraction logic
class ReasoningEngine:
    
    # Initialize reasoning engine with database, vector store, and LLM client
    def __init__(self, db: BookDatabase, vector_store: Any):
        self.db = db
        self.vector_store = vector_store
    
    def _structural_hint_for_book(self, book_id: int) -> Optional[str]:
        """Rule 35: load or build structural analysis and return extractor prompt block."""
        try:
            from .structural_analysis import (
                build_structural_analysis,
                format_structural_hint_for_extraction,
                parse_structural_analysis,
            )

            book = self.db.get_book_by_id(book_id)
            if not book:
                return None
            sa = parse_structural_analysis(book.get("structural_analysis"))
            if not sa:
                ch = self.db.get_chunks_by_book_id(book_id)
                sa = build_structural_analysis(ch, book.get("total_pages"))
                if sa:
                    self.db.set_book_structural_analysis(book_id, sa)
            if sa:
                return format_structural_hint_for_extraction(sa)
        except Exception:
            return None
        return None

    # Prepare framework nodes only (extraction + normalize + enrich). No agents. Used when pipeline runs agents after edges.
    def prepare_framework_nodes(
        self,
        book_id: int,
        name: str,
        max_chunks: Optional[int] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        phase4_instructions: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract, normalize, enrich context, definitive fields. Caller saves nodes, builds edges, then runs run_agents_over_graph."""
        def _progress(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)

        book = self.db.get_book_by_id(book_id)
        if not book:
            raise ValueError(f"Book with ID {book_id} not found")
        if not self.db.get_embeddings_status(book_id):
            raise ValueError(f"Embeddings not generated for book {book_id}. Run 'embed' command first.")
        total_chunks = self.db.get_chunk_count(book_id) if max_chunks is None else None
        structural_hint = self._structural_hint_for_book(book_id)

        _progress("Retrieving excerpts…")
        raw_nodes = langchain_framework.run_framework_extraction(
            self.vector_store,
            book_id,
            name,
            max_chunks=max_chunks,
            total_chunks=total_chunks,
            db=self.db,
            structural_hint=structural_hint,
            phase4_instructions=phase4_instructions,
        )
        _progress("Extracting structure…")
        normalized = self._normalize_framework_nodes(raw_nodes)
        if not normalized:
            raise ValueError("No valid framework nodes after validation. Please try again.")
        normalized = self._split_compounded_definitions(normalized)
        _progress("Attaching raw book excerpts…")
        normalized = self._enrich_context(book_id, normalized)
        _progress("Enriching definitive fields…")
        normalized = langchain_framework.run_definitive_fields_pass(normalized)
        return normalized

    # Run agents over the graph (nodes + edges). Call after nodes are saved and edges built. Returns scope_row for DB (claimed/evidenced only).
    def run_agents_over_graph(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        name: str,
        book_meta: Optional[Dict[str, Any]] = None,
        book_id: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
        """Epistemic, graph repair + Logic Auditor, Meta, Scope, Overview prose, Governor. scope_row includes claimed_scope, evidenced_scope, overview_prose."""
        edges_list = list(edges or [])
        digest = langchain_framework.FrameworkGraphDigest(nodes, edges_list)
        nodes = langchain_framework.run_epistemic_pass(nodes, edges_list, digest=digest)

        def _digest_factory(el: List[Dict[str, Any]]) -> langchain_framework.FrameworkGraphDigest:
            return langchain_framework.FrameworkGraphDigest(nodes, el)

        edges_list, audit_result, _ = langchain_framework.run_graph_repair_loop(
            nodes, edges_list, _digest_factory
        )
        digest = langchain_framework.FrameworkGraphDigest(nodes, edges_list)
        meta_out = langchain_framework.run_meta_pass(nodes, name, edges_list, digest=digest)

        excerpt_block = ""
        if book_id is not None and self.db.get_embeddings_status(book_id):
            try:
                excerpt_block = langchain_framework.gather_excerpts_for_audience_scope(
                    self.vector_store, book_id, self.db
                )
            except Exception as exc:
                logging.warning("gather_excerpts_for_audience_scope failed: %s", exc)
                excerpt_block = ""

        book_row = dict(book_meta or {})
        if book_id is not None:
            framework_hint = langchain_framework.build_mini_framework_hint(nodes, name, digest=digest)
            framework_graph_for_audience = digest.format_scope_framework_block(14000, 7000)
            new_audience = langchain_framework.run_extract_target_audience(
                excerpt_block=excerpt_block,
                book_title=(book_row.get("title") or "").strip(),
                existing_target_audience=book_row.get("target_audience"),
                framework_hint=framework_hint,
                framework_graph_summary=framework_graph_for_audience,
            )
            persist_audience_ok = False
            if new_audience and len(new_audience.strip()) >= 12:
                try:
                    self.db.update_book_target_audience(book_id, new_audience.strip()[:600])
                    persist_audience_ok = True
                except Exception as exc:
                    logging.warning("update_book_target_audience failed: %s", exc)
            book_row = self.db.get_book_by_id(book_id) or book_row
            if new_audience and len(new_audience.strip()) >= 12 and not persist_audience_ok:
                book_row = {**book_row, "target_audience": new_audience.strip()[:600]}

        scope_out = langchain_framework.run_scope_pass(
            nodes,
            purpose=meta_out.get("purpose"),
            assumptions_limits=meta_out.get("assumptions_limits"),
            book_meta=book_row,
            book_excerpt_block=excerpt_block or None,
            graph_digest=digest,
        )
        overview_prose = langchain_framework.run_overview_prose_pass(
            nodes,
            edges_list,
            name=name,
            purpose=meta_out.get("purpose"),
            assumptions_limits=meta_out.get("assumptions_limits"),
            claimed_scope=scope_out.get("claimed_scope") or "",
            evidenced_scope=scope_out.get("evidenced_scope") or "",
            book_meta=book_row,
            graph_digest=digest,
        )
        langchain_framework.run_governor_check(audit_result)
        scope_row = {
            "claimed_scope": scope_out.get("claimed_scope"),
            "evidenced_scope": scope_out.get("evidenced_scope"),
            "overview_prose": overview_prose,
        }
        return nodes, audit_result, scope_row, edges_list

    # Validate and normalize node dicts for storage (parent_index, sort_order, type, title, content, page_ref, depends_on_index).
    def _normalize_framework_nodes(
        self, nodes: List[Any]
    ) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        n = len(nodes)
        for i, item in enumerate(nodes):
            if not isinstance(item, dict):
                continue
            parent_index = item.get("parent_index")
            if parent_index is not None:
                try:
                    parent_index = int(parent_index)
                except (TypeError, ValueError):
                    parent_index = None
                if parent_index is not None and (parent_index < 0 or parent_index >= n):
                    parent_index = None
            sort_order = item.get("sort_order", i)
            try:
                sort_order = int(sort_order)
            except (TypeError, ValueError):
                sort_order = i
            node_type = (item.get("type") or item.get("node_type") or "section").strip().lower()
            if node_type not in FRAMEWORK_NODE_TYPES:
                node_type = "section"
            title = (item.get("title") or "").strip() or f"Item {i + 1}"
            content = (item.get("content") or "").strip()
            page_ref = item.get("page_ref")
            if page_ref is not None:
                page_ref = str(page_ref).strip() or None
            depends_on_index = item.get("depends_on_index")
            if depends_on_index is not None:
                try:
                    depends_on_index = int(depends_on_index)
                except (TypeError, ValueError):
                    depends_on_index = None
                if depends_on_index is not None and (depends_on_index < 0 or depends_on_index >= n):
                    depends_on_index = None
            result.append({
                "parent_index": parent_index,
                "sort_order": sort_order,
                "node_type": node_type,
                "title": title,
                "content": content,
                "page_ref": page_ref,
                "depends_on_index": depends_on_index,
            })
        return result

    def _split_compounded_definitions(self, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Split definition nodes that combine multiple terms (e.g. 'X and Y') into one node per term. Remaps parent_index and depends_on_index."""
        if not nodes:
            return nodes
        new_list: List[Dict[str, Any]] = []
        index_map: Dict[int, List[int]] = {}  # old index -> list of new indices

        def _terms_from_title(title: str) -> List[str]:
            parts: List[str] = []
            for segment in re.split(r"\s+and\s+", title, flags=re.IGNORECASE):
                for part in re.split(r",\s*", segment):
                    p = part.strip()
                    if p:
                        parts.append(p)
            return parts if len(parts) > 1 else [title]

        for i, node in enumerate(nodes):
            node_type = (node.get("node_type") or "section").strip().lower()
            title = (node.get("title") or "").strip()
            if node_type == "definition" and title and (" and " in title or "," in title):
                terms = _terms_from_title(title)
                if len(terms) <= 1:
                    new_list.append(dict(node))
                    index_map[i] = [len(new_list) - 1]
                else:
                    base_sort = node.get("sort_order", i)
                    for k, term in enumerate(terms):
                        new_node = {
                            "parent_index": node.get("parent_index"),
                            "sort_order": base_sort + k,
                            "node_type": "definition",
                            "title": term,
                            "content": node.get("content") or "",
                            "page_ref": node.get("page_ref"),
                            "depends_on_index": node.get("depends_on_index"),
                        }
                        new_list.append(new_node)
                    index_map[i] = list(range(len(new_list) - len(terms), len(new_list)))
            else:
                new_list.append(dict(node))
                index_map[i] = [len(new_list) - 1]

        n_old = len(nodes)
        for j, node in enumerate(new_list):
            for key in ("parent_index", "depends_on_index"):
                val = node.get(key)
                if val is not None and isinstance(val, int) and 0 <= val < n_old:
                    node[key] = index_map[val][0]
        if len(new_list) > n_old:
            logging.info(
                "Split compounded definitions: %d nodes -> %d nodes",
                n_old,
                len(new_list),
            )
        return new_list

    def _parse_page_ref(self, page_ref: Optional[str]) -> Optional[int]:
        """Parse page_ref (e.g. 'p.12', 'p. 42') to page number, or None."""
        if not page_ref or not isinstance(page_ref, str):
            return None
        s = page_ref.strip()
        m = re.search(r"p\.?\s*(\d+)", s, re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _is_main_node(self, node: Dict[str, Any], index: int, nodes: List[Dict[str, Any]]) -> bool:
        """True if node should get context: root section or type in definition/principle/step/warning/constraint."""
        node_type = (node.get("node_type") or "section").strip().lower()
        if node_type in MAIN_NODE_TYPES:
            return True
        if node_type == "section" and node.get("parent_index") is None:
            return True
        return False

    def _enrich_context(self, book_id: int, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Attach raw book excerpt per main node (page window). No LLM — definitive passes consume this text."""
        chunks = self.db.get_chunks_by_book_id(book_id)
        if not chunks:
            return nodes
        by_page: Dict[int, List[Dict]] = {}
        for c in chunks:
            p = c.get("page_number")
            if p not in by_page:
                by_page[p] = []
            by_page[p].append(c)
        for p in by_page:
            by_page[p].sort(key=lambda x: (x.get("chunk_index", 0), x.get("id", 0)))

        for i, node in enumerate(nodes):
            if not self._is_main_node(node, i, nodes):
                continue
            page_ref = node.get("page_ref")
            page_num = self._parse_page_ref(page_ref)
            if page_num is None:
                continue
            content = (node.get("content") or "").strip()
            ordered: List[Dict] = []
            for p in (page_num - 1, page_num):
                if p > 0 and p in by_page:
                    ordered.extend(by_page[p])
            if not ordered:
                continue
            content_words = set(re.findall(r"\w+", content.lower())) if content else set()
            best_idx = 0
            if content_words:
                best_score = 0
                for idx, c in enumerate(ordered):
                    chunk_text = (c.get("chunk_text") or "").lower()
                    chunk_words = set(re.findall(r"\w+", chunk_text))
                    overlap = len(content_words & chunk_words)
                    if overlap > best_score:
                        best_score = overlap
                        best_idx = idx
            window = self._build_context_window(ordered, best_idx, CONTEXT_WINDOW_MAX_CHARS)
            raw_fallback = self._raw_context_fallback(ordered, best_idx)
            raw = window or raw_fallback
            if not raw:
                continue
            excerpt = _normalize_book_excerpt(raw)
            if len(excerpt) < 12:
                continue
            nodes[i]["context"] = excerpt
        return nodes

    def _build_context_window(
        self, ordered: List[Dict], best_idx: int, max_chars: int
    ) -> str:
        """Build a window of text around best_idx (up to max_chars) from ordered chunks."""
        if not ordered or best_idx < 0 or best_idx >= len(ordered):
            return ""
        # Contiguous window: extend left and right from best_idx until we reach max_chars
        start = best_idx
        end = best_idx + 1
        total = len((ordered[best_idx].get("chunk_text") or "").strip())
        while total < max_chars and (start > 0 or end < len(ordered)):
            if start > 0:
                start -= 1
                total += len((ordered[start].get("chunk_text") or "").strip())
            if total >= max_chars:
                break
            if end < len(ordered):
                total += len((ordered[end].get("chunk_text") or "").strip())
                end += 1
        parts = [
            (ordered[i].get("chunk_text") or "").strip()
            for i in range(start, end)
        ]
        joined = " ".join(p for p in parts if p)
        if len(joined) > max_chars:
            joined = joined[:max_chars].rsplit(maxsplit=1)[0]
        return joined.strip()

    def _raw_context_fallback(self, ordered: List[Dict], best_idx: int) -> str:
        """Previous behavior: one chunk or first paragraph, capped at CONTEXT_MAX_CHARS."""
        if best_idx > 0:
            prev_chunk = ordered[best_idx - 1]
            context = (prev_chunk.get("chunk_text") or "").strip()
        else:
            curr_chunk = ordered[best_idx]
            context = (curr_chunk.get("chunk_text") or "").strip()
            first_para = context.split("\n\n")[0] if "\n\n" in context else context
            context = first_para[:CONTEXT_MAX_CHARS] if len(first_para) > CONTEXT_MAX_CHARS else first_para
        return context.strip()[:CONTEXT_MAX_CHARS] if context else ""

