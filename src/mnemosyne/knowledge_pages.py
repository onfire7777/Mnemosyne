"""Living Knowledge Pages ("Wiki Projection") for Mnemosyne.

Knowledge Pages provide living, hierarchical wiki-style projections with markdown
rendering, inline citations, dynamic Sources & Grounding Ledgers, and strict
3-layer Acyclic Custody enforcement preventing self-fulfilling hallucination cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, Literal

from mnemosyne.ids import new_id
from mnemosyne.models import dt_to_json, parse_dt, utc_now

KnowledgePageStatus = Literal["active", "stale", "retired", "archived", "draft"]
EMPTY_PAGE_NOTICE = "No content yet."

_PATH_REGEX = re.compile(r"^[a-z0-9_-]+(?:/[a-z0-9_-]+)*$")
_FORBIDDEN_SOURCE_PREFIXES = (
    "kp-",
    "kp_",
    "page-",
    "page_",
    "mm-",
    "mm_",
    "model-",
    "model_",
)


class AcyclicCustodyViolation(ValueError):
    """Raised when a KnowledgePage cites another KnowledgePage or MentalModel as source evidence."""


# Alias for compatibility with varying caller conventions
AcyclicCustodyViolationError = AcyclicCustodyViolation


class CustodyInvalidError(ValueError):
    """Raised when a cited source has lost live custody or been retracted/erased."""


class CustodyNotFoundError(ValueError):
    """Raised when a cited source cannot be found."""


class KnowledgePageConflict(ValueError):
    """Raised on version/revision conflict updating a knowledge page."""


def validate_knowledge_page_path(path: str) -> str:
    """Validate and normalize a hierarchical knowledge page path.

    Format: [folder/]*slug
    Allowed characters: lowercase alphanumeric, '-', '_', '/'
    Forbids: leading/trailing '/', consecutive '//', '.', '..'
    """
    if not isinstance(path, str):
        raise ValueError("Knowledge page path must be a string")
    normalized = path.strip().lower()
    if not normalized:
        raise ValueError("Knowledge page path cannot be empty")
    if len(normalized) > 512:
        raise ValueError(f"Knowledge page path exceeds 512 characters: {len(normalized)}")

    segments = normalized.split("/")
    if len(segments) > 10:
        raise ValueError(f"Knowledge page path exceeds maximum segment depth of 10: {len(segments)}")
    for segment in segments:
        if not segment:
            raise ValueError("Knowledge page path contains empty segments or consecutive slashes")
        if len(segment) > 64:
            raise ValueError(f"Knowledge page path segment exceeds 64 characters: {segment!r}")
        if segment in (".", ".."):
            raise ValueError(f"Knowledge page path cannot contain relative segments: {segment!r}")

    if not _PATH_REGEX.match(normalized):
        raise ValueError(
            f"Invalid knowledge page path {normalized!r}: must match pattern '^[a-z0-9_-]+(?:/[a-z0-9_-]+)*$'"
        )
    return normalized


@dataclass(slots=True)
class KnowledgePage:
    """Living knowledge page representing an evolving wiki-style topic synthesis."""

    tenant_id: str
    path: str
    title: str
    content_markdown: str
    branch: str = "main"
    page_id: str = field(default_factory=lambda: f"kp-{new_id()[:8]}")
    user_id: str = ""
    source_observation_ids: list[str] = field(default_factory=list)
    source_assertion_ids: list[str] = field(default_factory=list)
    source_evidence_cids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    version: int = 1
    status: KnowledgePageStatus = "active"
    trust_tier: int = 0
    sensitivity: int = 0
    access_policy: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.path = validate_knowledge_page_path(self.path)
        if not self.title or not isinstance(self.title, str):
            raise ValueError("Knowledge page title must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "tenant_id": self.tenant_id,
            "branch": self.branch,
            "user_id": self.user_id,
            "path": self.path,
            "title": self.title,
            "content_markdown": self.content_markdown,
            "source_observation_ids": list(self.source_observation_ids),
            "source_assertion_ids": list(self.source_assertion_ids),
            "source_evidence_cids": list(self.source_evidence_cids),
            "tags": list(self.tags),
            "version": self.version,
            "status": self.status,
            "trust_tier": self.trust_tier,
            "sensitivity": self.sensitivity,
            "access_policy": dict(self.access_policy),
            "created_at": dt_to_json(self.created_at),
            "updated_at": dt_to_json(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgePage:
        copy_data = dict(data)
        copy_data["source_observation_ids"] = list(copy_data.get("source_observation_ids") or [])
        copy_data["source_assertion_ids"] = list(copy_data.get("source_assertion_ids") or [])
        copy_data["source_evidence_cids"] = list(copy_data.get("source_evidence_cids") or [])
        copy_data["tags"] = list(copy_data.get("tags") or [])
        copy_data["created_at"] = parse_dt(copy_data.get("created_at")) or utc_now()
        copy_data["updated_at"] = parse_dt(copy_data.get("updated_at")) or utc_now()
        return cls(**copy_data)


def verify_knowledge_page_acyclic_custody(
    page: KnowledgePage,
    engine: Any | None = None,
    branch: str = "main",
    *,
    get_observation: Any | None = None,
    get_evidence: Any | None = None,
    get_assertion: Any | None = None,
    **kwargs: Any,
) -> None:
    """Verify strict 3-layer Acyclic Custody for a KnowledgePage.

    A KnowledgePage can cite:
    - Layer 1: Observations (source_observation_ids)
    - Layer 1: Assertions (source_assertion_ids)
    - Layer 0: Raw Evidence (source_evidence_cids)

    A KnowledgePage can NEVER cite another KnowledgePage or MentalModel.
    All citations must resolve to live, un-erased Layer 0 evidence.
    """
    all_sources = (
        list(page.source_evidence_cids)
        + list(page.source_observation_ids)
        + list(page.source_assertion_ids)
    )

    # 1. Prohibit forbidden source prefixes
    for s in all_sources:
        s_lower = str(s).lower()
        if any(s_lower.startswith(prefix) for prefix in _FORBIDDEN_SOURCE_PREFIXES):
            raise AcyclicCustodyViolation(
                f"Knowledge page {page.path} violates acyclic custody: "
                f"cannot cite KnowledgePage or MentalModel ({s}) as source evidence."
            )

    if engine is None and get_observation is None and get_evidence is None:
        return

    # 2. Validate observation sources
    for obs_id in page.source_observation_ids:
        obs = None
        if get_observation is not None:
            obs = get_observation(obs_id)
        elif engine is not None and hasattr(engine, "observation_get"):
            obs = engine.observation_get(page.tenant_id, obs_id, branch=branch, validate_custody=False)
        elif engine is not None and hasattr(engine, "get_observation_record"):
            obs = engine.get_observation_record(page.tenant_id, obs_id, branch)
        elif callable(engine):
            obs = engine(obs_id)

        if obs is None:
            raise CustodyNotFoundError(f"Source observation {obs_id} does not exist.")
        obs_status = obs.get("status") if isinstance(obs, dict) else getattr(obs, "status", None)
        if obs_status in ("retracted", "quarantined"):
            raise CustodyInvalidError(f"Source observation {obs_id} is {obs_status}.")

        # Check observation's own sources
        obs_cids = obs.get("source_evidence_cids", []) if isinstance(obs, dict) else getattr(obs, "source_evidence_cids", [])
        for sub_cid in obs_cids:
            sub_lower = str(sub_cid).lower()
            if any(sub_lower.startswith(prefix) for prefix in _FORBIDDEN_SOURCE_PREFIXES):
                raise AcyclicCustodyViolation(
                    f"Observation {obs_id} has invalid recursive source {sub_cid}"
                )
            if get_evidence is not None:
                sub_ev = get_evidence(sub_cid)
                if sub_ev is None or getattr(sub_ev, "erased", False) or getattr(sub_ev, "retired_at", None) is not None:
                    raise CustodyInvalidError(
                        f"Source observation {obs_id} has lost live custody: evidence {sub_cid} was erased or retired."
                    )
            elif hasattr(engine, "evidence_is_erased") and engine.evidence_is_erased(
                page.tenant_id, sub_cid, branch
            ):
                raise CustodyInvalidError(
                    f"Source observation {obs_id} has lost live custody: evidence {sub_cid} was erased."
                )

    # 3. Validate assertion sources
    for ass_id in page.source_assertion_ids:
        ass = None
        if get_assertion is not None:
            ass = get_assertion(ass_id)
        elif hasattr(engine, "get_assertion"):
            ass = engine.get_assertion(page.tenant_id, ass_id, branch)
        elif ass is None and hasattr(engine, "assertions"):
            ass = engine.assertions.get((page.tenant_id, ass_id, branch))
        if ass is None:
            raise CustodyNotFoundError(f"Source assertion {ass_id} does not exist.")
        if getattr(ass, "status", None) in ("retracted", "quarantined"):
            raise CustodyInvalidError(f"Source assertion {ass_id} is missing or retracted.")

        for sub_cid in getattr(ass, "source_evidence_cids", []):
            if get_evidence is not None:
                sub_ev = get_evidence(sub_cid)
                if sub_ev is None or getattr(sub_ev, "erased", False) or getattr(sub_ev, "retired_at", None) is not None:
                    raise CustodyInvalidError(
                        f"Source assertion {ass_id} has lost live custody: evidence {sub_cid} was erased or retired."
                    )
            elif hasattr(engine, "evidence_is_erased") and engine.evidence_is_erased(
                page.tenant_id, sub_cid, branch
            ):
                raise CustodyInvalidError(
                    f"Source assertion {ass_id} has lost live custody: evidence {sub_cid} was erased."
                )

    # 4. Validate direct evidence CIDs
    for cid in page.source_evidence_cids:
        if get_evidence is not None:
            ev = get_evidence(cid)
            if ev is None or getattr(ev, "erased", False) or getattr(ev, "retired_at", None) is not None:
                raise CustodyInvalidError(f"Direct source evidence CID {cid} is missing, erased, or retired.")
        else:
            if hasattr(engine, "evidence_is_erased") and engine.evidence_is_erased(
                page.tenant_id, cid, branch
            ):
                raise CustodyInvalidError(f"Direct source evidence CID {cid} has been erased.")
            if hasattr(engine, "get_evidence"):
                ev = engine.get_evidence(page.tenant_id, cid, branch)
                if ev is None or getattr(ev, "erased", False) or getattr(ev, "retired_at", None) is not None:
                    raise CustodyInvalidError(f"Direct source evidence CID {cid} is missing, erased, or retired.")


def render_knowledge_page_markdown(
    page: KnowledgePage,
    engine: Any | None = None,
    branch: str = "main",
    *,
    include_frontmatter: bool = True,
    include_citations_ledger: bool = True,
    get_observation: Any | None = None,
    get_evidence: Any | None = None,
    **kwargs: Any,
) -> str:
    """Render a KnowledgePage into projected Markdown with frontmatter and citations ledger."""
    sections: list[str] = []

    # 1. Frontmatter
    if include_frontmatter:
        tag_lines = ""
        if page.tags:
            tag_lines = "\ntags:\n" + "\n".join(f'  - "{t}"' for t in page.tags)
        else:
            tag_lines = "\ntags: []"

        frontmatter = (
            f"---\n"
            f'id: "{page.page_id}"\n'
            f'type: "knowledge-page"\n'
            f'path: "{page.path}"\n'
            f'title: "{page.title}"\n'
            f"revision: {page.version}{tag_lines}\n"
            f'updated_at: "{dt_to_json(page.updated_at)}"\n'
            f"custody:\n"
            f'  status: "grounded"\n'
            f"  observations_count: {len(page.source_observation_ids)}\n"
            f"  assertions_count: {len(page.source_assertion_ids)}\n"
            f"  evidence_count: {len(page.source_evidence_cids)}\n"
            f"---"
        )
        sections.append(frontmatter)

    # 2. Main content
    body = page.content_markdown.strip() if page.content_markdown else ""
    if not body:
        body = EMPTY_PAGE_NOTICE
    sections.append(body)

    # 3. Grounding Ledger
    if include_citations_ledger:
        ledger_lines = ["## Sources & Grounding Ledger"]

        if page.source_observation_ids:
            ledger_lines.append("\n### Observations")
            for obs_id in page.source_observation_ids:
                obs = None
                if get_observation is not None:
                    obs = get_observation(obs_id)
                elif engine is not None and hasattr(engine, "observation_get"):
                    obs = engine.observation_get(page.tenant_id, obs_id, branch=branch, validate_custody=False)
                if obs is not None:
                    standing = getattr(obs, "standing", 0.51)
                    sources = getattr(obs, "independent_source_count", 1)
                    topic = getattr(obs, "topic", "General")
                    ledger_lines.append(
                        f"- **[obs:{obs_id}]**: *{topic}* (Standing: {standing:.2f}, Sources: {sources})"
                    )
                    for q in getattr(obs, "proof_quotes", []):
                        quote_text = getattr(q, "quote", "")
                        cid = getattr(q, "cid", "")
                        ledger_lines.append(f'  - Proof Quote: *"{quote_text}"* `[cid:{cid}]`')
                else:
                    ledger_lines.append(f"- **[obs:{obs_id}]**")

        if page.source_evidence_cids:
            ledger_lines.append("\n### Evidence")
            for cid in page.source_evidence_cids:
                ev = None
                if get_evidence is not None:
                    ev = get_evidence(cid)
                elif engine is not None and hasattr(engine, "get_evidence"):
                    ev = engine.get_evidence(page.tenant_id, cid, branch=branch)
                if ev is not None:
                    session = getattr(ev, "session_id", "default")
                    content_snippet = getattr(ev, "content", "")
                    if len(content_snippet) > 80:
                        content_snippet = content_snippet[:77] + "..."
                    ledger_lines.append(f"- **[cid:{cid}]**: Session `{session}`")
                    ledger_lines.append(f'  > "{content_snippet}"')
                else:
                    ledger_lines.append(f"- **[cid:{cid}]**")

        if not page.source_observation_ids and not page.source_evidence_cids:
            ledger_lines.append("\n*No sources cited.*")

        sections.append("\n".join(ledger_lines))

    return "\n\n".join(sections)
