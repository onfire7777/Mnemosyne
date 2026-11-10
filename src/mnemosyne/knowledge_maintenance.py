"""Bounded, source-grounded topic discovery and incremental knowledge views.

Pages are disposable projections of active assertions. Discovery keeps identifiers
only, never a second copy of source prose. Publication is fenced by the native
source guard and page version; every read rechecks current sources and claims.
"""
from __future__ import annotations

import copy
from contextlib import ExitStack
import os
from pathlib import Path
import hashlib
import json
import math
import re
import shlex
import threading
import unicodedata
from collections import defaultdict
from dataclasses import asdict
from datetime import timedelta
from time import monotonic
from typing import Any

from mnemosyne._file_lock import exclusive_file_lock
from mnemosyne.access_policy import may_read_item, merge_access_policies, vector_partition_for_item
from mnemosyne.answering import AnswerReadContext
from mnemosyne.knowledge_pages import KnowledgePage, KnowledgePageConflict, scrub_automatic_pages
from mnemosyne.models import parse_dt, utc_now
from mnemosyne.retrieval import HashingEmbeddingProvider, projection_sources_readable
from mnemosyne.security import SecurityPolicy

SCHEMA = "mnemosyne.automatic-knowledge/v1"
_TAG = "automatic-knowledge"
_PRONOUNS = {"i", "me", "my", "we", "our", "you", "your", "it", "this", "that", "they", "he", "she"}
_SECTIONS = ("Decisions", "Preferences and constraints", "Known failure modes", "Pending commitments",
             "Established facts", "Observed configuration", "Observed facts",
             "Observed command outcomes", "Resolved commitments", "Uncertainty")
_STOP_WORDS = set("a an the what which who where when how is are was were do does did my our your we i it this that about know tell me more of for to in on with and or".split())
_TERM_EQUIVALENTS = {"runs": "run", "running": "run", "operates": "run", "operating": "run",
                     "hosts": "host", "hosting": "host", "hosted": "host", "deployed": "deploy",
                     "deployment": "deploy", "deploys": "deploy", "repository": "repo", "repositories": "repo",
                     "depends": "dependency", "dependencies": "dependency", "uses": "use", "using": "use"}


def _terms(text: str) -> set[str]:
    return {_TERM_EQUIVALENTS.get(term, term) for term in re.findall(r"\w+", _normal(text).replace("_", " "))
            if term not in _STOP_WORDS and len(term) > 1}


def _durable_role(predicate: str) -> str | None:
    terms = set(re.findall(r"\w+", predicate.casefold().replace("_", " ")))
    if terms & {"decided", "decision", "chose", "chosen", "rationale"}:
        return "Decisions"
    if terms & {"prefer", "prefers", "preference", "requires", "constraint", "must", "prohibits"}:
        return "Preferences and constraints"
    if terms & {"failure", "fails", "failed", "pitfall", "workaround", "avoid"}:
        return "Known failure modes"
    return None


def _claim_priority(claim: dict[str, Any], demand_terms: set[str] | None = None) -> float:
    """Useful durable facts beat incidental fresh observations, with source custody unchanged."""
    role = _durable_role(str(claim.get("predicate", ""))) or claim.get("section")
    base = {"Decisions": 4.0, "Preferences and constraints": 4.0, "Known failure modes": 4.0,
            "Pending commitments": 3.8, "Established facts": 2.5, "Observed configuration": 2.0,
            "Observed facts": 2.0, "Uncertainty": 1.5, "Resolved commitments": 0.8,
            "Observed command outcomes": 0.5}.get(role, 2.0)
    terms = _terms(" ".join(str(claim.get(k, "")) for k in ("subject", "predicate", "object", "text")))
    demand = len(terms & (demand_terms or set())) / max(1, len(demand_terms or ()))
    support = min(1.0, math.log2(max(1, len(set(claim.get("source_evidence_cids") or [])))) / 2)
    return base + 5 * demand + support


def _ordered_claims(claims: list[dict[str, Any]], demand_terms: set[str] | None = None):
    """Diversify sections and predicate families without inventing or merging claims."""
    # Only the diversity bonus changes between picks; usefulness is fixed.
    remaining = [(_claim_priority(claim, demand_terms),
                  str(claim.get("predicate", "")).split(".", 1)[0], claim) for claim in claims]
    sections: dict[str, int] = defaultdict(int)
    families: dict[str, int] = defaultdict(int)
    while remaining:
        def score(row):
            priority, family, claim = row
            return (priority + 1 / (1 + sections[claim["section"]]) + 1 / (1 + families[family]),
                    claim.get("observed_at") or "", claim["assertion_id"])
        selected = max(remaining, key=score)
        remaining.remove(selected)
        sections[selected[2]["section"]] += 1
        families[selected[1]] += 1
        yield selected[2]


def _embedding_identity(engine) -> str:
    provider = getattr(getattr(engine, "adapters", None), "embedding", None)
    return _digest([getattr(provider, name, None) for name in ("name", "dims", "model", "model_revision", "url")])


def _embedding(engine, text: str, *, query=False) -> list[float]:
    provider = getattr(getattr(engine, "adapters", None), "embedding", None)
    if provider is None:
        return []
    try:
        # Topic pages and queries belong to an owner. Do not place their text
        # or derived vectors in a provider's shared/durable cache.
        if query and callable(getattr(provider, "embed_query_sensitive", None)):
            vector = list(provider.embed_query_sensitive(text))
        elif type(provider) is HashingEmbeddingProvider:
            from mnemosyne.text import _hashing_embedding_pure
            vector = list(_hashing_embedding_pure(text, provider.dims))
        elif callable(getattr(provider, "embed_sensitive", None)):
            if query and getattr(provider, "query_prefix", None):
                text = provider.query_prefix + text
            vector = list(provider.embed_sensitive(text))
        else:
            return []  # Unknown providers must expose a cache-bypassing path.
        if not vector or len(vector) > 16384 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
            return []
        return vector
    except Exception:
        return []  # Lexical recall continues through a provider outage.


def _cosine(a, b) -> float:
    if not a or not isinstance(b, list) or len(a) != len(b):
        return 0.0
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in b):
        return 0.0
    denominator = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / denominator if denominator else 0.0


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    default=str, separators=(",", ":")).encode()).hexdigest()


def _normal(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).strip(" .?!\"'").casefold()


def _topic(value: Any, owner: str) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    title = " ".join(value.split()).strip(" .?!\"'")
    key = _normal(title)
    if (len(key) < 2 or len(title) > 80 or len(title.split()) > 8
            or key in _PRONOUNS or key == _normal(owner) or "\n" in value):
        return None
    return key, title


def _topics(row: dict[str, Any], owner: str) -> dict[str, str]:
    meta = row.get("calibration") or {}
    values = [row.get("subject")]
    if meta.get("entity_kind") in {"project", "asset", "person", "organization"}:
        values.append(row.get("object"))
    values.extend(meta.get("entity_mentions") or [])
    result = {}
    for value in values:
        if isinstance(value, dict):
            value = value.get("name") or value.get("text")
        found = _topic(value, owner)
        if found:
            result[found[0]] = found[1]
    return result


def _path(owner: str, key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:42] or "topic"
    return f"topics/{_digest(owner)[:12]}/{slug}-{_digest(key)[:10]}"


def _source_rows(engine: Any, context: AnswerReadContext, ids: list[str]) -> list[dict[str, Any]]:
    return engine.knowledge_source_batch(context.tenant_id, context.branch,
                                         ids=ids, limit=min(4096, max(1, len(ids))))


def _claim(engine: Any, context: AnswerReadContext, row: dict[str, Any]) -> dict[str, Any] | None:
    """Admit an existing assertion, preserving its exact evidence and epistemic class."""
    now = utc_now()
    if (row.get("tenant_id") != context.tenant_id or row.get("branch") != context.branch
            or row.get("user_id") != context.user_id or row.get("status") not in {"active", "contested"}
            or row.get("superseded_by") or row.get("expired_at")
            or (parse_dt(row.get("valid_to")) is not None and parse_dt(row["valid_to"]) <= now)
            or (parse_dt(row.get("valid_from")) is not None and parse_dt(row["valid_from"]) > now)):
        return None
    filt = context.to_filter()
    decision = may_read_item(item_tenant_id=context.tenant_id, sensitivity=int(row.get("sensitivity", 0)),
                             access_policy=row.get("access_policy") or {}, context=filt,
                             policy_max_sensitivity=engine.policy.max_sensitivity,
                             status=row.get("status", "active"), erased=False)
    if not decision.allowed or decision.redacted:
        return None
    if int(row.get("trust_tier", 0)) > (context.max_trust_tier if context.max_trust_tier is not None else engine.policy.max_trust_tier):
        return None
    meta = row.get("calibration") or {}
    epistemic = meta.get("epistemic_class", "direct_user" if meta.get("projection_kind") == "direct_user" else "")
    if epistemic not in {"direct_user", "reported_belief", "observed_tool", "consolidated_evidence"}:
        return None
    cids = list(dict.fromkeys(row.get("source_evidence_cids") or []))
    if not cids or not projection_sources_readable(engine, cids, tenant_id=context.tenant_id,
                                                   branch=context.branch, filt=filt, policy=engine.policy):
        return None
    sources = {cid: engine.get_evidence(context.tenant_id, cid, context.branch) for cid in cids}
    if any(source is None or source.user_id != context.user_id for source in sources.values()):
        return None
    spans = []
    supplied = meta.get("source_spans") or []
    # Legacy direct-user assertions may have a single exact quote without offsets.
    if not supplied and isinstance(meta.get("source_quote"), str):
        quote = meta["source_quote"]
        supplied = [{"cid": cid, "start": source.content.find(quote),
                     "end": source.content.find(quote) + len(quote), "quote": quote}
                    for cid, source in sources.items() if quote and quote in source.content]
    for span in supplied:
        cid, start, end = span.get("cid"), span.get("start"), span.get("end")
        source = sources.get(cid)
        if (source is None or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(source.content)):
            return None
        quote = source.content[start:end]
        if not quote.strip() or quote != span.get("quote") or len(quote) > 1200:
            return None
        spans.append({"cid": cid, "start": start, "end": end, "quote": quote})
    if not spans or set(cids) - {span["cid"] for span in spans}:
        return None
    # Exact source spans are shown, so inferred wording never becomes asserted fact.
    statement = " ".join(dict.fromkeys(span["quote"].strip() for span in spans))
    contract = meta.get("verification_contract") or {}
    if (meta.get("projection_kind") == "project_observation" and meta.get("observation_kind") == "command_outcome"
            and contract.get("kind") == "command_observation"):
        if (not isinstance(contract.get("argv"), list) or not contract["argv"]
                or not all(isinstance(part, str) for part in contract["argv"])
                or type(contract.get("expected_exit_code")) is not int):
            return None
        statement = f"{shlex.join(contract['argv'])} returned exit code {contract['expected_exit_code']}"
    elif meta.get("entailment_review", {}).get("entailed") is True:
        statement = f"{row['subject']} {row['predicate'].replace('_', ' ')} {row['object']}"
    predicate = _normal(str(row.get("predicate", "")))
    if epistemic == "reported_belief" or row["status"] == "contested":
        section = "Uncertainty"
    elif _durable_role(predicate):
        section = _durable_role(predicate)
    elif epistemic in {"observed_tool", "consolidated_evidence"}:
        section = {"configuration": "Observed configuration", "command_outcome": "Observed command outcomes"}.get(meta.get("observation_kind"), "Observed facts")
    elif meta.get("commitment_state") in {"completed", "cancelled"}:
        section = "Resolved commitments"
    elif any(word in predicate for word in ("plan", "goal", "commit", "intend", "deadline", "remind")):
        section = "Pending commitments"
    elif any(word in predicate for word in ("decid", "chose", "chosen", "decision")):
        section = "Decisions"
    else:
        section = "Established facts"
    stable = {key: value for key, value in row.items() if key not in {"last_accessed", "access_count"}}
    source_state = [{"cid": cid, "content": _digest(source.content), "metadata": source.metadata,
                     "access_policy": source.access_policy, "trust_tier": source.trust_tier,
                     "sensitivity": source.sensitivity} for cid, source in sources.items()]
    access = merge_access_policies([row.get("access_policy") or {}, *[s.access_policy for s in sources.values()]],
                                  tenant_id=context.tenant_id)
    sensitivity = max([int(row.get("sensitivity", 0))] + [s.sensitivity for s in sources.values()])
    return {"assertion_id": row["id"], "version": row.get("version", 1), "text": statement,
            "subject": row["subject"], "predicate": row["predicate"], "object": row["object"],
            "scope": row.get("scope") or {}, "commitment_state": meta.get("commitment_state"),
            "verification_contract": meta.get("verification_contract"),
            "access_policy": access, "embedding_allowed": vector_partition_for_item(
                sensitivity=sensitivity, access_policy=access) != "none",
            "epistemic_class": epistemic, "section": section, "spans": spans,
            "source_evidence_cids": cids, "observed_at": meta.get("observed_at", row.get("transaction_time")),
            "event_time": meta.get("event_time"), "fingerprint": _digest([stable, source_state]),
            "trust_tier": max([int(row.get("trust_tier", 0))] + [s.trust_tier for s in sources.values()]),
            "sensitivity": sensitivity}


def automatic_page_current(engine: Any, page: KnowledgePage, context: AnswerReadContext | None = None) -> bool:
    """Fail closed for invalidated, corrected, expired, or differently scoped views."""
    meta = page.maintenance
    if meta.get("schema") != SCHEMA:
        return True
    try:
        saved_context = AnswerReadContext(**meta["context"])
        if context is None:
            context = saved_context
        if page.user_id != context.user_id or page.tenant_id != context.tenant_id or page.branch != context.branch:
            return False
        claims = meta.get("claims") or []
        if not claims:
            return False
        if not projection_sources_readable(engine, page.source_evidence_cids, tenant_id=context.tenant_id,
                branch=context.branch, filt=context.to_filter(), policy=engine.policy):
            return False
        rows = {row["id"]: row for row in _source_rows(engine, context, [c["assertion_id"] for c in claims])}
        for old in claims:
            row = rows.get(old["assertion_id"])
            current = _claim(engine, context, row) if row else None
            if current is None or _digest(current) != _digest(old):
                return False
        if _normal(page.title) != meta.get("topic_key"):
            return False
        if not any(meta["topic_key"] in _topics(row, context.user_id or "") for row in rows.values()):
            return False
        if page.content_markdown != _render(page.title, claims, meta.get("related_topics") or []):
            return False
        for link in meta.get("related_topics") or []:
            target = engine.knowledge_page_get(context.tenant_id, branch=context.branch,
                                               path=link["path"], validate_custody=False)
            if (target is None or target.status != "active" or target.user_id != context.user_id
                    or target.title != link["title"] or not projection_sources_readable(engine,
                        target.source_evidence_cids, tenant_id=context.tenant_id, branch=context.branch,
                        filt=context.to_filter(), policy=engine.policy)):
                return False
        return True
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def _render(title: str, claims: list[dict[str, Any]], links: list[dict[str, Any]]) -> str:
    lines = [f"# {title}"]
    # Synthesize an entity view from independently grounded propositions.
    # This resolves pronouns and combines complementary facts without adding
    # an uncited model-generated conclusion or erasing uncertainty/negation.
    grouped = defaultdict(list)
    for claim in claims:
        if claim["section"] not in {"Uncertainty", "Observed command outcomes"} and claim.get("subject"):
            grouped[(claim["subject"], claim.get("epistemic_class"))].append(claim)
    if grouped:
        lines += ["", "## Overview"]
        for (subject, epistemic), facts in sorted(grouped.items()):
            properties = []
            for claim in facts[:3]:
                relation = claim["predicate"].replace("_", " ")
                value = claim["object"]
                scope = ", ".join(f"{key}: {value}" for key, value in sorted(claim.get("scope", {}).items())
                                  if key not in {"commitment_id", "epistemic_class"})
                citations = " ".join(f"[source:{span['cid']}:{span['start']}-{span['end']}]" for span in claim["spans"])
                properties.append(f"{relation}: {value}" + (f" ({scope})" if scope else "") + " " + citations)
            label = "Observed " if epistemic in {"observed_tool", "consolidated_evidence"} else ""
            lines.append(f"- {label}{subject} — " + "; ".join(properties))
    for section in _SECTIONS:
        items = [claim for claim in claims if claim["section"] == section]
        if not items:
            continue
        lines += ["", f"## {section}"]
        for claim in items:
            citations = " ".join(f"[source:{span['cid']}:{span['start']}-{span['end']}]" for span in claim["spans"])
            observed = f" (observed {claim['observed_at']})" if claim.get("epistemic_class") in {"observed_tool", "consolidated_evidence"} and claim.get("observed_at") else ""
            lines.append(f"- {claim['text']}{observed} {citations}")
    if links:
        lines += ["", "## Related topics"]
        lines += [f"- [{link['title']}]({link['path']})" for link in links]
    return "\n".join(lines)


def read_knowledge_context(engine: Any, context: AnswerReadContext, query: str, *,
                           max_pages: int = 3, max_tokens: int = 1200) -> list[dict[str, Any]]:
    """Return bounded useful topic views with fresh exact-span provenance."""
    if not hasattr(engine, "knowledge_page_list") or not context.user_id or max_tokens <= 0 or max_pages <= 0:
        return []
    terms = _terms(query)
    if not terms:
        return []
    pages = engine.knowledge_page_list(context.tenant_id, context.branch, tags=[_TAG], status="all", limit=1000)
    identity = _embedding_identity(engine)
    vector = _embedding(engine, query, query=True) if any(p.maintenance.get("embedding_identity") == identity
             and p.maintenance.get("embedding") and p.user_id == context.user_id for p in pages) else []
    scored = []
    for page in pages:
        if page.user_id != context.user_id or page.status != "active":
            continue
        content = " ".join(str(c.get(key, "")) for c in page.maintenance.get("claims", [])
                           for key in ("subject", "predicate", "object", "text"))
        overlap = len(terms & _terms(content + " " + page.title)) / len(terms)
        title_overlap = len(terms & _terms(page.title)) / len(terms)
        semantic = _cosine(vector, page.maintenance.get("embedding")) if page.maintenance.get("embedding_identity") == identity else 0.0
        if overlap or semantic >= 0.35:
            scored.append((-(overlap + 0.5 * title_overlap + max(0.0, semantic)), page.path, page))
    output = []
    remaining = max_tokens * 4
    for _, _, page in sorted(scored)[:max_pages * 3]:
        with engine.mental_model_guard(context.tenant_id):
            current = engine.knowledge_page_get(context.tenant_id, page.page_id, context.branch,
                                                validate_custody=False)
            if current is None or current.version != page.version or not automatic_page_current(engine, current, context):
                continue
        claims = []
        for claim in _ordered_claims(page.maintenance.get("claims", []), terms):
            candidate = claims + [copy.deepcopy(claim)]
            if len(_render(page.title, candidate, []).encode("utf-8")) <= remaining:
                claims = candidate
        if not claims:
            continue
        remaining -= len(_render(page.title, claims, []).encode("utf-8"))
        output.append({"page_id": page.page_id, "version": page.version, "title": page.title,
                       "path": page.path, "text": _render(page.title, claims, []), "claims": claims,
                       "source_evidence_cids": sorted({cid for claim in claims for cid in claim["source_evidence_cids"]})})
        if len(output) >= max_pages:
            break
    return output


class KnowledgeMaintenanceWorker:
    """One owner, one synchronous publication at a time, bounded per-tick work.

    Retain the worker between ticks: keyset discovery advances over large stores.
    Only IDs and topic names are cached, and all claims are reread before use.
    The time budget stops admission of work; an in-flight, provider-timeout-
    bounded embedding may finish its guarded publication before the tick exits.
    """
    def __init__(self, engine: Any, context: AnswerReadContext, *, max_batch: int = 6,
                 max_seconds: float = 2.0, max_claims: int = 24, max_tokens: int = 2400,
                 scan_batch: int = 256, checkpoint_path: str | Path | None = None):
        if not context.user_id or context.role == "reader" or context.as_of is not None or context.break_glass:
            raise ValueError("knowledge maintenance requires a current owner-scoped writer")
        if not 1 <= max_batch <= 100 or not 0 < max_seconds <= 60 or not 1 <= max_claims <= 100:
            raise ValueError("invalid knowledge maintenance budget")
        if not 100 <= max_tokens <= 20000 or not 1 <= scan_batch <= 4096:
            raise ValueError("invalid knowledge scan/token budget")
        self.engine, self.context = engine, context
        self.max_batch, self.max_seconds, self.max_claims = max_batch, max_seconds, max_claims
        self.max_tokens, self.scan_batch = max_tokens, scan_batch
        self._lock = threading.Lock()
        self._cursor = ""
        self._index: dict[str, dict[str, str]] = {}
        self._discovering: dict[str, dict[str, str]] = {}
        self._last_revision: Any = None
        self._scan_revision: Any = None
        self._scanning = False
        self._offset = 0
        self._checkpoint_path = Path(checkpoint_path) if checkpoint_path is not None else None
        self._collection = "assertions"
        self._requests: dict[str, list[str]] = {}
        self._discovering_requests: dict[str, list[str]] = {}
        self._load_checkpoint()

    def _load_checkpoint(self) -> None:
        if self._checkpoint_path is None or not self._checkpoint_path.exists():
            return
        try:
            if self._checkpoint_path.stat().st_size > 10_000_000:
                return
            data = json.loads(self._checkpoint_path.read_text())
            if data.get("schema") != SCHEMA or data.get("scope") != _digest(asdict(self.context)):
                return
            for name in ("cursor", "index", "discovering", "last_revision", "scan_revision",
                         "scanning", "offset", "collection", "requests", "discovering_requests"):
                if name in data:
                    setattr(self, "_" + name, data[name])
        except (OSError, ValueError, TypeError):
            return  # Checkpoints are scheduling hints, never source authority.

    def _save_checkpoint(self) -> None:
        if self._checkpoint_path is None:
            return
        data = {"schema": SCHEMA, "scope": _digest(asdict(self.context))}
        for name in ("cursor", "index", "discovering", "last_revision", "scan_revision",
                     "scanning", "offset", "collection", "requests", "discovering_requests"):
            data[name] = getattr(self, "_" + name)
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._checkpoint_path.with_suffix(self._checkpoint_path.suffix + f".{os.getpid()}.tmp")
        try:
            with temporary.open("w") as stream:
                os.chmod(temporary, 0o600)
                json.dump(data, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._checkpoint_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _revision(self) -> Any:
        method = getattr(self.engine, "mental_model_source_revision", None)
        return method(self.context.tenant_id) if callable(method) else None

    def _coalesce(self, pages: list[KnowledgePage], deadline: float) -> tuple[dict[str, KnowledgePage], int]:
        """Canonical topic identity merges duplicate automatic views only."""
        grouped: dict[str, list[KnowledgePage]] = defaultdict(list)
        for page in pages:
            meta = page.maintenance
            if meta.get("merged_into"):
                continue
            key = meta.get("topic_hash") or (_digest(meta["topic_key"]) if meta.get("topic_key") else None)
            if key:
                grouped[key].append(page)
        result = {}
        merged = 0
        for key, group in grouped.items():
            # An explicit archive remains authoritative, including after a restart.
            group.sort(key=lambda p: (p.status not in {"archived", "retired"}, p.page_id))
            result[key] = primary = group[0]
            for duplicate in group[1:]:
                if merged >= self.max_batch or monotonic() >= deadline:
                    break
                scrubbed = KnowledgePage.from_dict(scrub_automatic_pages([duplicate.to_dict()])[0])
                scrubbed.status = "archived"
                scrubbed.maintenance["merged_into"] = primary.page_id
                try:
                    with self.engine.mental_model_guard(self.context.tenant_id):
                        self.engine.knowledge_page_update(scrubbed, branch=self.context.branch,
                                                          expected_version=duplicate.version)
                    merged += 1
                except KnowledgePageConflict:
                    continue
        return result, merged

    def _discover(self, deadline: float) -> bool:
        revision = self._revision()
        if not self._scanning and revision is not None and revision == self._last_revision:
            return True
        if not self._scanning:
            self._scanning, self._scan_revision = True, revision
            self._cursor, self._discovering = "", {}
            self._collection, self._discovering_requests = "assertions", {}
        remaining = self.scan_batch
        while remaining > 0 and monotonic() < deadline:
            rows = self.engine.knowledge_source_batch(self.context.tenant_id, self.context.branch,
                collection=self._collection, after=self._cursor, limit=remaining)
            for row in rows:
                if row.get("user_id") == self.context.user_id:
                    if self._collection == "assertions" and row.get("status") in {"active", "contested"}:
                        found = _topics(row, self.context.user_id or "")
                        if found:
                            self._discovering[row["id"]] = {_digest(key): "" for key in found}
                    elif (self._collection == "evidence" and row.get("actor") == "user"
                          and int(row.get("trust_tier", 5)) <= 1 and not row.get("erased")
                          and "?" in str(row.get("content", "")) and projection_sources_readable(
                              self.engine, [row["cid"]], tenant_id=self.context.tenant_id,
                              branch=self.context.branch, filt=self.context.to_filter(), policy=self.engine.policy)):
                        # Repeated named questions add demand, never factual content.
                        text = str(row.get("content", ""))[:4000]
                        for name in re.findall(r"\b[A-Z][\w-]*(?: +[A-Z][\w-]*)*", text):
                            key = _digest(_normal(name))
                            self._discovering_requests.setdefault(key, []).append(row["cid"])
                self._cursor = row["id" if self._collection == "assertions" else "cid"]
                if monotonic() >= deadline:
                    return False
            if len(rows) == remaining:
                return False
            remaining -= len(rows)
            if self._collection == "assertions":
                self._collection, self._cursor = "evidence", ""
            else:
                self._index, self._requests = self._discovering, self._discovering_requests
                self._discovering, self._discovering_requests = {}, {}
                self._scanning = False
                self._last_revision = self._scan_revision
                return True
        return False

    def run_once(self) -> dict[str, Any]:
        report: dict[str, Any] = {"created": 0, "updated": 0, "unchanged": 0, "invalidated": 0,
                                  "conflicts": 0, "discovery_complete": False, "tokens": 0}
        if not self._lock.acquire(blocking=False):
            return {**report, "busy": True}
        locks = ExitStack()
        try:
            if self._checkpoint_path is not None:
                self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    locks.enter_context(exclusive_file_lock(self._checkpoint_path.with_suffix(
                        self._checkpoint_path.suffix + ".lock"), timeout=0))
                except TimeoutError:
                    return {**report, "busy": True}
                self._load_checkpoint()
            decision = SecurityPolicy().authorize_write(operation="mental_model_refresh", role=self.context.role,
                source_trust_tier=self.context.source_trust_tier if self.context.source_trust_tier is not None else 1,
                target_sink="belief")
            if not decision.allowed:
                raise PermissionError("knowledge worker requires trusted write authority")
            deadline = monotonic() + self.max_seconds
            report["discovery_complete"] = self._discover(deadline)
            pages = [p for p in self.engine.knowledge_page_list(self.context.tenant_id, self.context.branch,
                      tags=[_TAG], status="all", limit=1000) if p.user_id == self.context.user_id]
            existing, report["merged"] = self._coalesce(pages, deadline)
            topics: dict[str, list[str]] = defaultdict(list)
            titles = {}
            for aid, named in self._index.items():
                for key in named:
                    topics[key].append(aid)
            # Existing views are also revisited after their final source disappears.
            for key, page in existing.items():
                if key and page.status not in {"archived", "retired"}:
                    if not report["discovery_complete"] and key not in topics:
                        topics[key] = page.maintenance.get("assertion_ids") or [c["assertion_id"] for c in page.maintenance.get("claims", [])]
                    else:
                        topics.setdefault(key, [])
                    titles.setdefault(key, page.title)
            ordered = sorted(topics, key=lambda k: (0 if k in existing and existing[k].status == "stale" else 1,
                                                      -len(topics[k]) - len(set(self._requests.get(k, []))), k))
            if ordered:
                self._offset %= len(ordered)
                ordered = ordered[self._offset:] + ordered[:self._offset]
            processed = report["merged"]
            for key in ordered:
                if processed >= self.max_batch or monotonic() >= deadline or report["tokens"] >= self.max_tokens:
                    break
                previous = existing.get(key)
                if previous and previous.status in {"archived", "retired"}:
                    continue  # An explicit deletion is a regeneration tombstone.
                revision = self._revision()
                rows = _source_rows(self.engine, self.context, topics[key][:4096])
                claims = []
                canonical_key = previous.maintenance.get("topic_key") if previous else None
                for row in rows:
                    for named_key, title in _topics(row, self.context.user_id or "").items():
                        if _digest(named_key) == key:
                            canonical_key, titles[key] = named_key, title
                if canonical_key is None:
                    continue
                demand_terms = set()
                for cid in self._requests.get(key, [])[-32:]:
                    source = self.engine.get_evidence(self.context.tenant_id, cid, self.context.branch)
                    if source is not None and source.user_id == self.context.user_id and projection_sources_readable(
                            self.engine, [cid], tenant_id=self.context.tenant_id, branch=self.context.branch,
                            filt=self.context.to_filter(), policy=self.engine.policy):
                        demand_terms.update(_terms(source.content[:4000]) - _terms(titles[key]))
                seen = set()
                page_tokens = 0
                admitted = []
                for row in sorted(rows, key=lambda r: (_claim_priority(r, demand_terms), r.get("transaction_time", ""), r["id"]), reverse=True):
                    if monotonic() >= deadline:
                        break
                    claim = _claim(self.engine, self.context, row)
                    if claim is None:
                        continue
                    admitted.append(claim)
                for claim in _ordered_claims(admitted, demand_terms):
                    text_key = _normal(claim["text"])
                    if text_key in seen:
                        continue
                    combined_tokens = (len(_render(titles[key], claims + [claim], []).encode("utf-8")) + 3) // 4
                    if len(claims) >= self.max_claims:
                        break
                    if combined_tokens > self.max_tokens:
                        continue
                    seen.add(text_key)
                    claims.append(claim)
                    page_tokens = combined_tokens
                processed += 1
                if report["tokens"] + page_tokens > self.max_tokens:
                    break
                report["tokens"] += page_tokens
                if monotonic() >= deadline:
                    break
                cids = sorted({cid for claim in claims for cid in claim["source_evidence_cids"]})
                # Two independently captured facts justify a topic; an explicit goal
                # or decision can justify immediate creation from one source.
                useful = len(cids) >= 2 or len(set(self._requests.get(key, []))) >= 2 or any(c["section"] in {"Pending commitments", "Decisions", "Observed configuration"} for c in claims)
                if not previous and not useful:
                    continue
                if not claims and not previous:
                    continue
                neighbors = {other for aid in topics[key] for other in self._index.get(aid, {}) if other != key}
                links = [{"path": existing[n].path, "title": existing[n].title,
                          "source_evidence_cids": existing[n].source_evidence_cids} for n in sorted(neighbors)
                         if n in existing and existing[n].status == "active" and projection_sources_readable(
                             self.engine, existing[n].source_evidence_cids, tenant_id=self.context.tenant_id,
                             branch=self.context.branch, filt=self.context.to_filter(), policy=self.engine.policy)][:12]
                cids = sorted(set(cids).union(*(link["source_evidence_cids"] for link in links)))
                identity = _embedding_identity(self.engine)
                fingerprint = _digest([[c["fingerprint"] for c in claims], links, identity, 3])
                embedding_allowed = bool(claims) and all(c["embedding_allowed"] for c in claims)
                if previous and previous.status == "active" and previous.maintenance.get("fingerprint") == fingerprint:
                    retry_at = parse_dt(previous.maintenance.get("embedding_retry_at"))
                    if previous.maintenance.get("embedding") or not embedding_allowed or retry_at and retry_at > utc_now():
                        report["unchanged"] += 1
                        continue
                embedding = _embedding(self.engine, titles[key] + "\n" + "\n".join(
                    f"{c['subject']} {c['predicate'].replace('_', ' ')} {c['object']}" for c in claims)) if embedding_allowed else []
                page = KnowledgePage(tenant_id=self.context.tenant_id, user_id=self.context.user_id or "",
                    branch=self.context.branch, path=_path(self.context.user_id or "", canonical_key), title=titles[key],
                    page_id=previous.page_id if previous else "kp-auto-" + _digest([self.context.tenant_id,
                        self.context.branch, self.context.user_id, canonical_key])[:24],
                    content_markdown=_render(titles[key], claims, links) if claims else "",
                    source_evidence_cids=cids, source_assertion_ids=[], tags=[_TAG],
                    trust_tier=max((c["trust_tier"] for c in claims), default=1),
                    sensitivity=max((c["sensitivity"] for c in claims), default=0),
                    access_policy=merge_access_policies([{"allow_principals": [self.context.user_id]},
                        *[c["access_policy"] for c in claims]], tenant_id=self.context.tenant_id),
                    status="active" if claims else "stale",
                    maintenance={"schema": SCHEMA, "topic_key": canonical_key, "context": asdict(self.context),
                                 "claims": claims, "fingerprint": fingerprint, "related_topics": links,
                                 "derivation_version": 3, "embedding": embedding, "embedding_identity": identity,
                                 "embedding_retry_at": (utc_now() + timedelta(seconds=60)).isoformat() if embedding_allowed and not embedding else None})
                if not claims:
                    if previous is None or (previous.status == "stale" and not previous.content_markdown):
                        report["unchanged"] += 1
                        continue
                    page = KnowledgePage.from_dict(scrub_automatic_pages([previous.to_dict()])[0])
                try:
                    with self.engine.mental_model_guard(self.context.tenant_id):
                        # A source change, newer writer, or revocation wins over this build.
                        if revision != self._revision():
                            report["conflicts"] += 1
                            continue
                        current = self.engine.knowledge_page_get(self.context.tenant_id, page.page_id,
                                                                 self.context.branch, validate_custody=False)
                        if (current.version if current else None) != (previous.version if previous else None):
                            report["conflicts"] += 1
                            continue
                        if claims and not automatic_page_current(self.engine, page, self.context):
                            report["conflicts"] += 1
                            continue
                        if previous:
                            page.created_at = previous.created_at
                            self.engine.knowledge_page_update(page, branch=self.context.branch, expected_version=previous.version)
                            report["updated" if claims else "invalidated"] += 1
                        else:
                            self.engine.knowledge_page_create(page, branch=self.context.branch)
                            report["created"] += 1
                        existing[key] = page
                except KnowledgePageConflict:
                    report["conflicts"] += 1
            self._offset += processed
            self._save_checkpoint()
            return report
        finally:
            locks.close()
            self._lock.release()
