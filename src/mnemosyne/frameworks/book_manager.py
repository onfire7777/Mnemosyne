import json
import os
import re
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .database import BookDatabase
from .reasoning import ReasoningEngine
from .mechanical_audit import run_mechanical_audit
from .phase4_metrics import log_phase4_iteration_metrics

log = logging.getLogger(__name__)


def _phase4_max_iterations() -> int:
    """Phase 4 (v2 §III): cap re-extract loops; default 2 passes total. Env PHASE4_MAX_ITERATIONS (1–5)."""
    raw = os.getenv("PHASE4_MAX_ITERATIONS", "2")
    try:
        n = int(raw)
    except ValueError:
        n = 2
    return max(1, min(n, 5))


MECHANICAL_AUDIT_REPAIR_ROUNDS = 5


# Framework generation uses ReasoningEngine.prepare_framework_nodes (includes run_definitive_fields_pass),
# then shared helpers below for edges + post-edge finalization — keep generate/regenerate in sync.

def _merge_mindmap_edge_lists(
    llm_edges: Optional[List[Dict[str, Any]]],
    dep_edges: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Dedupe by (from, to, type); LLM edges first, then deterministic dependency edges."""
    merged: List[Dict[str, Any]] = []
    seen: set = set()
    for e in (llm_edges or []) + (dep_edges or []):
        key = (e.get("from_node_id"), e.get("to_node_id"), e.get("edge_type"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(e)
    return merged


_PAGE_REF = re.compile(r"p{1,2}\.?\s*(\d+)(?:\s*[-\u2013\u2014]\s*(\d+))?", re.IGNORECASE)


def cited_units(page_ref: Optional[str]) -> set:
    """Source units a node cites: 'p.3', 'p.3-5' and 'pp. 2, p.7' all count."""
    units: set = set()
    for start, end in _PAGE_REF.findall(page_ref or ""):
        a, b = int(start), int(end or start)
        units.update(range(min(a, b), min(max(a, b), min(a, b) + 200) + 1))
    return units


def coverage_ledger(chunks: List[Dict[str, Any]], nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every source unit (page_number = unit) is represented, a duplicate, or unresolved.

    Inside Mnemosyne a skill's text is never summarised away: a unit no node cites is listed
    as unresolved (its full text stays in the chunks table) and drives another extract pass.
    """
    cited: Dict[int, List[str]] = {}
    for n in nodes:
        for u in cited_units(n.get("page_ref")):
            cited.setdefault(u, []).append(n.get("title") or "")
    seen: Dict[str, int] = {}
    units: List[Dict[str, Any]] = []
    for c in sorted(chunks, key=lambda c: (c.get("page_number") or 0, c.get("chunk_index") or 0)):
        unit = int(c.get("page_number") or 0)
        key = " ".join((c.get("chunk_text") or "").split()).lower()
        if unit in cited:
            units.append({"unit": unit, "status": "represented", "nodes": cited[unit]})
        elif key in seen:
            units.append({"unit": unit, "status": "duplicate", "of": seen[key]})
        else:
            units.append({"unit": unit, "status": "unresolved"})
        seen.setdefault(key, unit)
    unresolved = [u["unit"] for u in units if u["status"] == "unresolved"]
    return {"units": units, "unresolved": unresolved, "complete": not unresolved}


class BookManager:
    """Proper Thinking's framework pipeline over one SQLite file owned by Mnemosyne."""

    def __init__(self, db_path: str, vector_store: Any):
        self.db = BookDatabase(db_path)
        self.vector_store = vector_store
        self.reasoning = ReasoningEngine(self.db, self.vector_store)

    def _build_and_save_mindmap_edges(self, framework_id: int, log_tag: str = "") -> None:
        """
        Stage 2: LLM mindmap + deterministic deps + taxonomy + inferred uses_definition.
        log_tag: e.g. ' (regenerate)' for log lines only.
        """
        from . import framework as langchain_framework

        nodes_with_ids = self.db.get_framework_nodes(framework_id)
        llm_edges = langchain_framework.run_mindmap_edges(nodes_with_ids)
        dep_edges = langchain_framework.build_dependency_edges(nodes_with_ids)
        merged = _merge_mindmap_edge_lists(llm_edges, dep_edges)
        merged = langchain_framework.finalize_framework_edge_list(nodes_with_ids, merged)
        if merged:
            self.db.add_framework_edges(framework_id, merged)
            log.info(
                "Framework %s%s: saved %s mindmap edge(s) (LLM=%s, deps=%s).",
                framework_id,
                log_tag,
                len(merged),
                len(llm_edges or []),
                len(dep_edges or []),
            )
        else:
            log.info("Framework %s%s: no mindmap edges generated.", framework_id, log_tag)

    def _run_extraction_phase4_loop(
        self,
        book_id: int,
        framework_id: int,
        name: str,
        max_chunks: Optional[int],
        progress_callback: Optional[Callable[[str], None]],
    ) -> Dict[str, Any]:
        """
        Definitive_System_Feedback_v2 Section III: extract → edges → agents → mechanical,
        then judgment audit; optionally re-extract with instructions until cap or no warrant.

        Re-extraction requires **mechanical audit to pass**; if it fails, the loop stops even when
        judgment would warrant another extract pass.

        Retrieval trace (chunk assembly) logs: `langchain_framework` — search log lines
        ``Framework retrieval: raw=… after_dedup=…`` and ``trimmed to ~… chars``.
        Phase 0 metrics: ``Phase 4 metrics`` / ``Phase 4 metrics detail`` after each pass.
        """
        from . import framework as langchain_framework

        def _progress(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)

        max_it = _phase4_max_iterations()
        phase4_instructions: Optional[str] = None
        judgment_history: List[Dict[str, Any]] = []
        merged_audit: Dict[str, Any] = {}

        for iteration in range(max_it):
            tag = " [Phase 4 re-extract]" if phase4_instructions else ""
            _progress(f"Extracting structure (pass {iteration + 1}/{max_it})…{tag}")
            nodes = self.reasoning.prepare_framework_nodes(
                book_id,
                name,
                max_chunks=max_chunks,
                progress_callback=progress_callback,
                phase4_instructions=phase4_instructions,
            )
            if not nodes:
                raise ValueError(
                    "Framework nodes are empty. The model returned no usable structure. Please try again."
                )
            if iteration > 0:
                self.db.delete_framework_nodes(framework_id)
                self.db.delete_framework_edges(framework_id)
            self.db.add_framework_nodes(framework_id, nodes)

            _progress("Building mindmap edges…")
            try:
                self._build_and_save_mindmap_edges(
                    framework_id, log_tag="" if iteration == 0 else " (phase4)"
                )
            except Exception as exc:
                log.warning("Framework %s: mindmap edge generation failed: %s", framework_id, exc)

            _progress("Running quality checks (Logic Auditor, meta, scope)…")
            audit_result, _ = self._finalize_framework_after_edges(framework_id, book_id, name)
            final_audit = audit_result if isinstance(audit_result, dict) else {}

            fw = self.db.get_framework(framework_id)
            mech = fw.get("mechanical_audit_result") or {}
            mechanical_passed = bool(mech.get("passed"))

            nodes_f = fw.get("nodes") or []
            edges_f = fw.get("edges") or []
            digest = langchain_framework.FrameworkGraphDigest(nodes_f, edges_f or [])
            book_row = self.db.get_book_by_id(book_id) or {}
            judgment = langchain_framework.run_judgment_audit(
                nodes_f,
                edges_f,
                digest=digest,
                book_meta=book_row,
                logic_audit_result=final_audit,
            )
            log_phase4_iteration_metrics(
                framework_id,
                iteration,
                max_it,
                nodes_f,
                edges_f or [],
                judgment,
                tag=" [Phase 4]" if phase4_instructions else "",
            )
            judgment_history.append(
                {
                    "iteration": iteration + 1,
                    "warrants_reextract": judgment.get("warrants_reextract"),
                    "findings": judgment.get("findings") or [],
                }
            )

            coverage = coverage_ledger(self.db.get_chunks_by_book_id(book_id), nodes_f)
            merged_audit = dict(final_audit)
            merged_audit["coverage"] = coverage
            merged_audit["phase4"] = {
                "max_iterations": max_it,
                "completed_iterations": iteration + 1,
                "judgment_history": judgment_history,
                "last_judgment": judgment,
            }
            self.db.update_framework(
                framework_id,
                "",
                audit_result=merged_audit,
                claimed_scope=fw.get("claimed_scope"),
                evidenced_scope=fw.get("evidenced_scope"),
            )

            # Proper Thinking re-extracts only after a clean mechanical audit; source left
            # out of the framework is re-extracted regardless (coverage below).
            if not mechanical_passed and not coverage["unresolved"]:
                log.info(
                    "Phase 4: mechanical audit did not pass (pass %s); "
                    "stopping — re-extraction requires mechanical audit to pass.",
                    iteration + 1,
                )
                break

            missing = coverage["unresolved"]
            if not judgment.get("warrants_reextract") and not missing:
                log.info(
                    "Phase 4: judgment does not warrant re-extraction (pass %s).",
                    iteration + 1,
                )
                break

            if iteration >= max_it - 1:
                log.info("Phase 4: reached max iterations (%s).", max_it)
                break

            nxt = ((judgment.get("extractor_instructions") or "").strip()
                   if mechanical_passed and judgment.get("warrants_reextract") else "")
            if missing:
                # Mnemosyne's one change to Proper Thinking: nothing in the source may be dropped.
                nxt = (nxt + "\n\nCOVERAGE (mandatory): these sources are not represented by any node yet: "
                       + ", ".join(f"Page {u}" for u in missing)
                       + ". Represent every one of them with node(s) whose page_ref cites it, keeping all "
                       "nodes that already exist.").strip()
            if len(nxt) < 24:
                log.info("Phase 4: empty or short extractor instructions; stopping.")
                break
            phase4_instructions = nxt

        return merged_audit

    def _persisting_progress_callback(
        self,
        framework_id: int,
        progress_callback: Optional[Callable[[str], None]],
    ) -> Callable[[str], None]:
        def _progress(msg: str) -> None:
            try:
                self.db.set_framework_generation_progress(framework_id, msg)
            except Exception:
                log.exception(
                    "Failed to persist generation progress (framework_id=%s)", framework_id
                )
            if progress_callback:
                progress_callback(msg)

        return _progress

    def _execute_framework_generation_job(
        self,
        book_id: int,
        framework_id: int,
        name: str,
        max_chunks: Optional[int],
        progress_callback: Optional[Callable[[str], None]],
    ) -> Dict[str, Any]:
        """Run Phase 4 extraction loop and mark framework generation_status completed/failed."""
        progress = self._persisting_progress_callback(framework_id, progress_callback)
        try:
            audit_result = self._run_extraction_phase4_loop(
                book_id, framework_id, name, max_chunks, progress
            )
            self.db.mark_framework_generation_completed(framework_id)
            return audit_result
        except Exception as exc:
            self.db.mark_framework_generation_failed(framework_id, str(exc))
            raise
    def _finalize_framework_after_edges(
        self,
        framework_id: int,
        book_id: int,
        name: str,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Single canonical path: agents → persist scope/audit/epistemic → definitive document → mechanical audit.
        Returns (audit_result, definitive_md last written).
        """
        from . import framework as langchain_framework

        fw = self.db.get_framework(framework_id)
        nodes_with_ids = fw.get("nodes") or []
        edges = fw.get("edges") or []
        book_row = self.db.get_book_by_id(book_id) or {}
        nodes_updated, audit_result, scope_row, edges_out = self.reasoning.run_agents_over_graph(
            nodes_with_ids, edges, name, book_meta=book_row, book_id=book_id
        )
        if langchain_framework.framework_edge_signature(edges) != langchain_framework.framework_edge_signature(
            edges_out
        ):
            self.db.add_framework_edges(framework_id, edges_out)
        book_row = self.db.get_book_by_id(book_id) or book_row
        self.db.update_framework(
            framework_id,
            "",
            audit_result=audit_result,
            claimed_scope=scope_row.get("claimed_scope"),
            evidenced_scope=scope_row.get("evidenced_scope"),
        )
        overview_prose = scope_row.get("overview_prose") or {}
        try:
            self.db.set_framework_overview_prose_json(
                framework_id,
                json.dumps(overview_prose, ensure_ascii=False) if overview_prose else None,
            )
        except Exception as exc:
            log.warning("Framework %s: overview prose JSON persist failed: %s", framework_id, exc)
        self.db.update_framework_nodes_epistemic(framework_id, nodes_updated)

        definitive_md: Optional[str] = None
        try:
            fw_full = self.db.get_framework(framework_id)
            fw_full["claimed_scope"] = scope_row.get("claimed_scope")
            fw_full["evidenced_scope"] = scope_row.get("evidenced_scope")
            fw_full["overview_prose"] = overview_prose
            definitive_md = langchain_framework.render_definitive_document(fw_full, book_row)
            if definitive_md:
                self.db.set_framework_definitive_document(framework_id, definitive_md)
        except Exception as exc:
            log.warning(
                "Framework %s: definitive document generation failed: %s",
                framework_id,
                exc,
            )

        self._run_and_store_mechanical_audit(framework_id, book_id, definitive_md)
        return audit_result, definitive_md

    def _run_and_store_mechanical_audit(
        self,
        framework_id: int,
        book_id: int,
        definitive_md: Optional[str] = None,
    ) -> None:
        """Phase 3: mechanical audit, deterministic repair loop (links/quotes), up to 5 rounds; final audit stored."""
        from . import framework as langchain_framework
        from .mechanical_repair import apply_mechanical_repairs_for_audit

        try:
            book_row = self.db.get_book_by_id(book_id) or {}
            md: Optional[str] = definitive_md
            result: Dict[str, Any] = {"passed": True, "failures": [], "checks_run": []}

            for _ in range(MECHANICAL_AUDIT_REPAIR_ROUNDS):
                fw = self.db.get_framework(framework_id)
                if not fw:
                    return
                nodes = fw.get("nodes") or []
                edges = fw.get("edges") or []
                doc = (md if md is not None else (fw.get("definitive_document") or "")) or ""
                result = run_mechanical_audit(
                    nodes,
                    edges,
                    definitive_document=doc or None,
                    book_id=book_id,
                    db=self.db,
                )
                if result.get("passed"):
                    break
                _, _, changed = apply_mechanical_repairs_for_audit(nodes, edges, result)
                if not changed:
                    break
                self.db.sync_framework_nodes_graph_fields(framework_id, nodes)
                self.db.add_framework_edges(framework_id, edges)
                fw2 = self.db.get_framework(framework_id)
                md = langchain_framework.render_definitive_document(fw2, book_row)
                if md:
                    self.db.set_framework_definitive_document(framework_id, md)

            fw_final = self.db.get_framework(framework_id)
            if fw_final:
                doc_final = (md if md is not None else (fw_final.get("definitive_document") or "")) or ""
                result = run_mechanical_audit(
                    fw_final.get("nodes") or [],
                    fw_final.get("edges") or [],
                    definitive_document=doc_final or None,
                    book_id=book_id,
                    db=self.db,
                )
            self.db.set_framework_mechanical_audit(framework_id, result)
        except Exception as exc:
            log.warning("Framework %s: mechanical audit failed: %s", framework_id, exc)
