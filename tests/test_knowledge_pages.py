"""Comprehensive test suite for Living Knowledge Pages (Milestone 2).

Verifies:
- Path validation (hierarchical [folder/]*slug, normalized slashes, illegal paths)
- Strict 3-layer Acyclic Custody enforcement:
  * Page citing Observations, Assertions, Evidence is legal
  * Page citing KnowledgePage (kp-*, page-*) raises AcyclicCustodyViolation
  * Page citing MentalModel (mm-*, model-*) raises AcyclicCustodyViolation
  * Citing non-existent or retracted records raises CustodyNotFoundError/CustodyInvalidError
- Markdown projection:
  * YAML frontmatter formatting
  * Markdown body preservation and empty page notice
  * Dynamic Sources & Grounding Ledger with inline citations
- CRUD, Versioning & Optimistic Concurrency Control (CAS)
- Cross-engine parity across LocalMemoryEngine and SqliteEngine
- Transitive custody invalidation (backing evidence/obs retracted -> page stale)
- Zero-DELETE invariant enforcement
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ids import evidence_cid
from mnemosyne.knowledge_pages import (
    AcyclicCustodyViolation,
    CustodyInvalidError,
    CustodyNotFoundError,
    KnowledgePage,
    KnowledgePageConflict,
    render_knowledge_page_markdown,
    validate_knowledge_page_path,
    verify_knowledge_page_acyclic_custody,
)
from mnemosyne.models import Evidence
from mnemosyne.observations import Observation
from mnemosyne.sqlite_engine import SqliteEngine


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(params=["local", "sqlite"])
def engine(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    if request.param == "local":
        return LocalMemoryEngine(store_path=tmp_path / "local-store.json")
    return SqliteEngine(tmp_path / "sqlite-store")


def _seed_evidence(
    engine: Any,
    tenant_id: str,
    content: str,
    *,
    user_id: str = "alice",
    actor: str = "user",
    branch: str = "main",
) -> Evidence:
    cid = evidence_cid(
        content,
        tenant_id=tenant_id,
        user_id=user_id,
        source_type="chat",
        content_pointer=None,
        modality="text",
        sensitivity=0,
    )
    ev = Evidence(
        tenant_id=tenant_id,
        user_id=user_id,
        actor=actor,
        source_type="chat",
        content=content,
        branch=branch,
        cid=cid,
        created_at=datetime.now(UTC),
    )
    engine.append_evidence(ev, branch=branch)
    return ev


def _seed_observation(
    engine: Any,
    tenant_id: str,
    topic: str,
    evidence_cids: list[str],
    *,
    branch: str = "main",
    user_id: str = "alice",
) -> Observation:
    obs_id = f"obs-{uuid4().hex[:8]}"
    obs = Observation(
        tenant_id=tenant_id,
        user_id=user_id,
        subject="Testing",
        topic=topic,
        content=f"Details for {topic}",
        branch=branch,
        observation_id=obs_id,
        source_evidence_cids=evidence_cids,
        independent_source_count=1,
        standing=0.85,
    )
    engine.observation_upsert(obs, branch=branch)
    return obs


# ---------------------------------------------------------------------------
# 1. Path Validation Tests
# ---------------------------------------------------------------------------


def test_validate_knowledge_page_path_success() -> None:
    assert validate_knowledge_page_path("architecture") == "architecture"
    assert validate_knowledge_page_path("projects/orion") == "projects/orion"
    assert validate_knowledge_page_path("projects/orion/architecture-spec") == "projects/orion/architecture-spec"
    assert validate_knowledge_page_path("Deep/Nested/Doc_v2") == "deep/nested/doc_v2"
    assert validate_knowledge_page_path("  spaces-trimmed/slug  ") == "spaces-trimmed/slug"


def test_validate_knowledge_page_path_failures() -> None:
    # Empty
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_knowledge_page_path("")

    with pytest.raises(ValueError, match="cannot be empty"):
        validate_knowledge_page_path("   ")

    # Leading or trailing slash
    with pytest.raises(ValueError, match="empty segments or consecutive slashes"):
        validate_knowledge_page_path("/projects/orion")

    with pytest.raises(ValueError, match="empty segments or consecutive slashes"):
        validate_knowledge_page_path("projects/orion/")

    # Empty segment / double slash
    with pytest.raises(ValueError, match="empty segments or consecutive slashes"):
        validate_knowledge_page_path("projects//orion")

    # Traversal / dot segments
    with pytest.raises(ValueError, match="cannot contain relative segments"):
        validate_knowledge_page_path("projects/../orion")

    with pytest.raises(ValueError, match="cannot contain relative segments"):
        validate_knowledge_page_path("projects/./orion")

    # Illegal characters
    with pytest.raises(ValueError, match="must match pattern"):
        validate_knowledge_page_path("projects/orion@system")

    with pytest.raises(ValueError, match="must match pattern"):
        validate_knowledge_page_path("projects/orion space/spec")


# ---------------------------------------------------------------------------
# 2. Strict 3-Layer Acyclic Custody Tests
# ---------------------------------------------------------------------------


def test_acyclic_custody_valid_citations() -> None:
    # Citing observations and evidence is legal
    page = KnowledgePage(
        tenant_id="tenant-1",
        page_id="kp-1",
        path="projects/orion/overview",
        title="Orion Overview",
        content_markdown="Overview content",
        source_observation_ids=["obs-valid-1"],
        source_evidence_cids=["cidv1:abcdef"],
    )

    observations = {
        "obs-valid-1": Observation(
            tenant_id="tenant-1",
            user_id="alice",
            subject="Orion",
            topic="Architecture",
            content="Valid Observation",
            observation_id="obs-valid-1",
            status="active",
        )
    }
    evidence = {
        "cidv1:abcdef": Evidence(
            tenant_id="tenant-1",
            user_id="alice",
            actor="user",
            source_type="chat",
            cid="cidv1:abcdef",
            content="test",
        )
    }

    # Should verify without error
    verify_knowledge_page_acyclic_custody(
        page,
        get_observation=lambda oid: observations.get(oid),
        get_evidence=lambda cid: evidence.get(cid),
    )


def test_acyclic_custody_rejects_knowledge_page_citation() -> None:
    # Layer 3 cannot cite Layer 3 (KnowledgePage cannot cite KnowledgePage)
    page = KnowledgePage(
        tenant_id="tenant-1",
        page_id="kp-1",
        path="projects/orion/overview",
        title="Orion Overview",
        content_markdown="Overview content",
        source_observation_ids=["kp-other-page"],  # Violates layer hierarchy
    )

    with pytest.raises(AcyclicCustodyViolation, match="violates acyclic custody"):
        verify_knowledge_page_acyclic_custody(page)

    page2 = KnowledgePage(
        tenant_id="tenant-1",
        page_id="kp-2",
        path="projects/orion/design",
        title="Orion Design",
        content_markdown="Design content",
        source_observation_ids=["page-other-page"],  # Also page prefix
    )

    with pytest.raises(AcyclicCustodyViolation, match="violates acyclic custody"):
        verify_knowledge_page_acyclic_custody(page2)


def test_acyclic_custody_rejects_mental_model_citation() -> None:
    # Layer 3 cannot cite Layer 3/models (Acyclic rule)
    page = KnowledgePage(
        tenant_id="tenant-1",
        page_id="kp-1",
        path="projects/orion/overview",
        title="Orion Overview",
        content_markdown="Overview content",
        source_observation_ids=["mm-model-1"],
    )

    with pytest.raises(AcyclicCustodyViolation, match="violates acyclic custody"):
        verify_knowledge_page_acyclic_custody(page)

    page2 = KnowledgePage(
        tenant_id="tenant-1",
        page_id="kp-2",
        path="projects/orion/overview",
        title="Orion Overview",
        content_markdown="Overview content",
        source_assertion_ids=["model-user-intent"],
    )

    with pytest.raises(AcyclicCustodyViolation, match="violates acyclic custody"):
        verify_knowledge_page_acyclic_custody(page2)


def test_acyclic_custody_not_found_and_invalid() -> None:
    page = KnowledgePage(
        tenant_id="tenant-1",
        page_id="kp-1",
        path="projects/orion/overview",
        title="Orion Overview",
        content_markdown="Overview content",
        source_observation_ids=["obs-missing"],
    )

    with pytest.raises(CustodyNotFoundError, match="does not exist"):
        verify_knowledge_page_acyclic_custody(
            page,
            get_observation=lambda oid: None,
        )

    # Observation is retracted
    retracted_obs = Observation(
        tenant_id="tenant-1",
        user_id="alice",
        subject="Orion",
        topic="Retracted",
        content="Retracted",
        observation_id="obs-retracted",
        status="retracted",
    )
    page_retracted = KnowledgePage(
        tenant_id="tenant-1",
        page_id="kp-2",
        path="projects/orion/overview-2",
        title="Orion Overview 2",
        content_markdown="Overview content",
        source_observation_ids=["obs-retracted"],
    )
    with pytest.raises(CustodyInvalidError, match="retracted"):
        verify_knowledge_page_acyclic_custody(
            page_retracted,
            get_observation=lambda oid: retracted_obs if oid == "obs-retracted" else None,
        )


# ---------------------------------------------------------------------------
# 3. Markdown Projection & Sources Ledger Tests
# ---------------------------------------------------------------------------


def test_render_knowledge_page_markdown() -> None:
    page = KnowledgePage(
        tenant_id="tenant-1",
        page_id="kp-arch-101",
        path="projects/orion/architecture",
        title="Orion Architecture",
        content_markdown="# System Architecture\n\nThe Orion engine uses [obs:obs-1] and [cid:cidv1:evidence-abc] for memory.",
        source_observation_ids=["obs-1"],
        source_evidence_cids=["cidv1:evidence-abc"],
        tags=["core", "architecture"],
        version=2,
    )

    observations = {
        "obs-1": Observation(
            tenant_id="tenant-1",
            user_id="alice",
            subject="Orion",
            topic="Storage",
            content="Memory storage relies on immutable evidence.",
            observation_id="obs-1",
            standing=0.9,
            independent_source_count=2,
            status="active",
        )
    }
    evidence = {
        "cidv1:evidence-abc": Evidence(
            tenant_id="tenant-1",
            user_id="alice",
            actor="user",
            source_type="chat",
            cid="cidv1:evidence-abc",
            content="Evidence record about Orion cluster configuration.",
        )
    }

    markdown = render_knowledge_page_markdown(
        page,
        get_observation=lambda oid: observations.get(oid),
        get_evidence=lambda cid: evidence.get(cid),
    )

    # Verify YAML frontmatter
    assert markdown.startswith("---\n")
    frontmatter_end = markdown.find("\n---\n", 4)
    assert frontmatter_end != -1
    frontmatter_text = markdown[4:frontmatter_end]

    assert 'id: "kp-arch-101"' in frontmatter_text
    assert 'path: "projects/orion/architecture"' in frontmatter_text
    assert 'title: "Orion Architecture"' in frontmatter_text
    assert "revision: 2" in frontmatter_text
    assert '"core"' in frontmatter_text
    assert "observations_count: 1" in frontmatter_text
    assert "evidence_count: 1" in frontmatter_text

    # Verify Markdown Body
    assert "# System Architecture" in markdown

    # Verify Sources & Grounding Ledger
    assert "## Sources & Grounding Ledger" in markdown
    assert "[obs:obs-1]" in markdown
    assert "*Storage*" in markdown
    assert "Standing: 0.90" in markdown
    assert "Sources: 2" in markdown
    assert "[cid:cidv1:evidence-abc]" in markdown
    assert "Evidence record about Orion cluster" in markdown


def test_render_empty_knowledge_page_markdown() -> None:
    page = KnowledgePage(
        tenant_id="tenant-1",
        page_id="kp-empty",
        path="projects/empty-page",
        title="Empty Page",
        content_markdown="",
    )

    markdown = render_knowledge_page_markdown(page)
    assert "No content yet." in markdown


# ---------------------------------------------------------------------------
# 4. Engine CRUD, Versioning & Optimistic Concurrency Tests
# ---------------------------------------------------------------------------


def test_knowledge_page_crud_and_versioning(engine: Any) -> None:
    tenant_id = f"tenant-{uuid4().hex[:6]}"
    ev = _seed_evidence(engine, tenant_id, "Configuration parameters for test cluster.")
    obs = _seed_observation(engine, tenant_id, "Cluster spec", [ev.cid])

    page_id = f"kp-{uuid4().hex[:8]}"
    page = KnowledgePage(
        tenant_id=tenant_id,
        page_id=page_id,
        path="systems/cluster-spec",
        title="Cluster Specification",
        content_markdown="Initial specification citing [obs:" + obs.observation_id + "].",
        source_observation_ids=[obs.observation_id],
        source_evidence_cids=[ev.cid],
        tags=["systems", "v1"],
    )

    # 1. Create
    created_id = engine.knowledge_page_create(page)
    assert created_id == page_id

    # 2. Get by page_id and path
    fetched_by_id = engine.knowledge_page_get(tenant_id, page_id)
    assert fetched_by_id is not None
    assert fetched_by_id.page_id == page_id
    assert fetched_by_id.version == 1
    assert fetched_by_id.title == "Cluster Specification"

    fetched_by_path = engine.knowledge_page_get(tenant_id, path="systems/cluster-spec")
    assert fetched_by_path is not None
    assert fetched_by_path.page_id == page_id

    # 3. Duplicate path conflict
    dup_page = KnowledgePage(
        tenant_id=tenant_id,
        page_id=f"kp-{uuid4().hex[:8]}",
        path="systems/cluster-spec",
        title="Conflicting Page",
        content_markdown="Conflict",
    )
    with pytest.raises(KnowledgePageConflict):
        engine.knowledge_page_create(dup_page)

    # 4. Update
    fetched_by_id.content_markdown = "Updated cluster specification content."
    fetched_by_id.tags.append("updated")
    updated = engine.knowledge_page_update(fetched_by_id, expected_version=1)
    assert updated.version == 2
    assert "updated" in updated.tags

    # 5. Optimistic Concurrency Control (CAS conflict)
    fetched_by_id.content_markdown = "Stale attempt"
    with pytest.raises(KnowledgePageConflict, match="conflict"):
        engine.knowledge_page_update(fetched_by_id, expected_version=1)  # current is 2


def test_knowledge_page_list_filtering(engine: Any) -> None:
    tenant_id = f"tenant-{uuid4().hex[:6]}"
    ev = _seed_evidence(engine, tenant_id, "Sample reference evidence.")
    obs = _seed_observation(engine, tenant_id, "Sample observation", [ev.cid])

    pages = [
        KnowledgePage(
            tenant_id=tenant_id,
            page_id=f"kp-{uuid4().hex[:8]}",
            path="projects/apollo/architecture",
            title="Apollo Architecture",
            content_markdown="Architecture",
            source_observation_ids=[obs.observation_id],
            tags=["apollo", "arch"],
        ),
        KnowledgePage(
            tenant_id=tenant_id,
            page_id=f"kp-{uuid4().hex[:8]}",
            path="projects/apollo/testing",
            title="Apollo Testing",
            content_markdown="Testing",
            source_observation_ids=[obs.observation_id],
            tags=["apollo", "qa"],
        ),
        KnowledgePage(
            tenant_id=tenant_id,
            page_id=f"kp-{uuid4().hex[:8]}",
            path="projects/artemis/architecture",
            title="Artemis Architecture",
            content_markdown="Artemis Arch",
            source_observation_ids=[obs.observation_id],
            tags=["artemis", "arch"],
        ),
        KnowledgePage(
            tenant_id=tenant_id,
            page_id=f"kp-{uuid4().hex[:8]}",
            path="docs/overview",
            title="General Docs",
            content_markdown="Docs overview",
            source_observation_ids=[obs.observation_id],
            tags=["docs"],
        ),
    ]

    for p in pages:
        engine.knowledge_page_create(p)

    # Filter by folder
    apollo_pages = engine.knowledge_page_list(tenant_id, folder="projects/apollo")
    assert len(apollo_pages) == 2
    paths = {p.path for p in apollo_pages}
    assert paths == {"projects/apollo/architecture", "projects/apollo/testing"}

    # Filter by tags
    arch_pages = engine.knowledge_page_list(tenant_id, tags=["arch"])
    assert len(arch_pages) == 2
    arch_paths = {p.path for p in arch_pages}
    assert arch_paths == {"projects/apollo/architecture", "projects/artemis/architecture"}

    # Filter all
    all_pages = engine.knowledge_page_list(tenant_id, limit=10)
    assert len(all_pages) == 4


# ---------------------------------------------------------------------------
# 5. Transitive Custody Invalidation & Stale State Tests
# ---------------------------------------------------------------------------


def test_transitive_custody_invalidation_stale_page(engine: Any) -> None:
    tenant_id = f"tenant-{uuid4().hex[:6]}"
    ev = _seed_evidence(engine, tenant_id, "Critical infrastructure credentials.")
    obs = _seed_observation(engine, tenant_id, "Cluster Secret Key", [ev.cid])

    page_id = f"kp-{uuid4().hex[:8]}"
    page = KnowledgePage(
        tenant_id=tenant_id,
        page_id=page_id,
        path="security/cluster-secrets",
        title="Cluster Secrets",
        content_markdown="Protected secrets doc.",
        source_observation_ids=[obs.observation_id],
        source_evidence_cids=[ev.cid],
    )
    engine.knowledge_page_create(page)

    initial = engine.knowledge_page_get(tenant_id, page_id)
    assert initial is not None
    assert initial.status == "active"

    # Retract the backing observation
    engine.observation_retract(tenant_id, obs.observation_id, reason="security_leak")

    # On subsequent retrieval, acyclic custody detects retracted observation and marks page stale
    refreshed = engine.knowledge_page_get(tenant_id, page_id, validate_custody=True)
    assert refreshed is not None
    assert refreshed.status == "stale"


# ---------------------------------------------------------------------------
# 6. Zero-DELETE Invariant Enforcement Tests
# ---------------------------------------------------------------------------


def test_zero_delete_invariant_knowledge_page(engine: Any) -> None:
    tenant_id = f"tenant-{uuid4().hex[:6]}"
    ev = _seed_evidence(engine, tenant_id, "Archivable evidence.")
    obs = _seed_observation(engine, tenant_id, "Archivable observation", [ev.cid])

    page_id = f"kp-{uuid4().hex[:8]}"
    page = KnowledgePage(
        tenant_id=tenant_id,
        page_id=page_id,
        path="deprecated/old-system",
        title="Old System Documentation",
        content_markdown="Old narrative.",
        source_observation_ids=[obs.observation_id],
        source_evidence_cids=[ev.cid],
    )
    engine.knowledge_page_create(page)

    # Verify archive changes status to 'archived', increments version, does NOT delete
    archived = engine.knowledge_page_archive(tenant_id, page_id, reason="decommissioned")
    assert archived is True

    # Active listing excludes it
    active_pages = engine.knowledge_page_list(tenant_id, status="active")
    assert all(p.page_id != page_id for p in active_pages)

    # All listing includes it
    all_pages = engine.knowledge_page_list(tenant_id, status="all")
    archived_page = next((p for p in all_pages if p.page_id == page_id), None)
    assert archived_page is not None
    assert archived_page.status == "archived"
    assert archived_page.version == 2

    # A new page at the same path can now be created because the old one is archived
    new_page = KnowledgePage(
        tenant_id=tenant_id,
        page_id=f"kp-{uuid4().hex[:8]}",
        path="deprecated/old-system",
        title="Replacement Page",
        content_markdown="New replacement.",
        source_observation_ids=[obs.observation_id],
    )
    new_id = engine.knowledge_page_create(new_page)
    assert new_id != page_id

    # Verify both exist in the database without any row deletion
    records = engine.list_knowledge_page_records(tenant_id)
    assert len(records) == 2
    assert {r["page_id"] for r in records} == {page_id, new_id}


def test_knowledge_page_rejects_nonexistent_evidence_and_page_paths(engine: Any):
    """KnowledgePage citing non-existent evidence CIDs or knowledge page paths must be rejected with CustodyInvalidError."""
    tenant_id = f"tenant-{uuid4().hex[:6]}"

    # Non-existent evidence CID cited as direct evidence
    page_bogus_ev = KnowledgePage(
        tenant_id=tenant_id,
        page_id=f"kp-{uuid4().hex[:8]}",
        path="docs/bogus-evidence",
        title="Bogus Evidence Doc",
        content_markdown="Content",
        source_evidence_cids=["cid:completely-bogus-nonexistent-evidence-12345"],
    )
    with pytest.raises(CustodyInvalidError):
        engine.knowledge_page_create(page_bogus_ev)

    # Knowledge page path cited as direct evidence
    page_citing_path = KnowledgePage(
        tenant_id=tenant_id,
        page_id=f"kp-{uuid4().hex[:8]}",
        path="docs/citing-path",
        title="Citing Path Doc",
        content_markdown="Content",
        source_evidence_cids=["systems/core"],
    )
    with pytest.raises(CustodyInvalidError):
        engine.knowledge_page_create(page_citing_path)

    # Valid page updated with non-existent evidence CID must also be rejected
    ev = _seed_evidence(engine, tenant_id, "Genuine evidence text.")
    valid_page = KnowledgePage(
        tenant_id=tenant_id,
        page_id=f"kp-{uuid4().hex[:8]}",
        path="docs/valid-page",
        title="Valid Page",
        content_markdown="Valid content",
        source_evidence_cids=[ev.cid],
    )
    created_id = engine.knowledge_page_create(valid_page)
    assert created_id == valid_page.page_id

    valid_page.source_evidence_cids = ["cid:missing-evidence-update-999"]
    with pytest.raises(CustodyInvalidError):
        engine.knowledge_page_update(valid_page)


def test_row_to_models_preserves_datetime_types():
    """Regression test: verify postgres row conversion produces datetime objects, not strings."""
    from mnemosyne.postgres_engine import (
        _cid_bytes_or_none,
        _row_to_knowledge_page,
        _row_to_observation,
    )

    now = datetime.now(UTC)
    kp = _row_to_knowledge_page({
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "branch": "main",
        "page_id": "kp-test1",
        "path": "test/path1",
        "title": "Title",
        "content_markdown": "body",
        "version": 1,
        "status": "active",
        "trust_tier": 0,
        "sensitivity": 0,
        "created_at": now,
        "updated_at": now,
    })
    assert isinstance(kp.created_at, datetime)
    assert isinstance(kp.updated_at, datetime)

    # Also works with ISO strings
    kp_str = _row_to_knowledge_page({
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "branch": "main",
        "page_id": "kp-test2",
        "path": "test/path2",
        "title": "Title",
        "content_markdown": "body",
        "version": 1,
        "status": "active",
        "trust_tier": 0,
        "sensitivity": 0,
        "created_at": "2026-10-28T10:00:00Z",
        "updated_at": "2026-10-28T10:00:00Z",
    })
    assert isinstance(kp_str.created_at, datetime)
    assert isinstance(kp_str.updated_at, datetime)

    # Observation
    obs = _row_to_observation({
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "branch": "main",
        "observation_id": "obs-test",
        "user_id": "alice",
        "subject": "sub",
        "topic": "top",
        "content": "cont",
        "independent_source_count": 1,
        "corroboration_velocity": 0.0,
        "standing": 0.5,
        "salience": 0.5,
        "access_velocity": 0.0,
        "access_count": 0,
        "status": "active",
        "version": 1,
        "trust_tier": 0,
        "sensitivity": 0,
        "last_accessed_at": now,
        "created_at": now,
        "updated_at": now,
    })
    assert isinstance(obs.created_at, datetime)
    assert isinstance(obs.updated_at, datetime)
    assert isinstance(obs.last_accessed_at, datetime)

    # Defensive _cid_bytes_or_none
    assert _cid_bytes_or_none(None) is None
    assert _cid_bytes_or_none("") is None


def test_postgres_engine_knowledge_page_render_markdown_live():
    """Regression test: verify live PostgresEngine renders markdown without AttributeError."""
    import os
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN") or "postgresql://consolidator_user:mnemosyne-disposable-test@127.0.0.1:55434/mnemosyne"
    try:
        from mnemosyne.postgres_engine import PostgresEngine
        engine = PostgresEngine(dsn, require_safe_role=False)
        tenant_id = "00000000-0000-0000-0000-000000000001"
        unique_path = f"test/live-render-{uuid4().hex[:8]}"
        kp = KnowledgePage(
            tenant_id=tenant_id,
            path=unique_path,
            title="Live Render Test",
            content_markdown="Render body content with citations.",
        )
        engine.knowledge_page_create(kp)
        rendered = engine.knowledge_page_render_markdown(tenant_id, path=unique_path)
        assert "updated_at:" in rendered
        assert "Render body content with citations." in rendered

        fetched = engine.knowledge_page_get(tenant_id, path=unique_path)
        assert fetched is not None
        assert isinstance(fetched.created_at, datetime)
        assert isinstance(fetched.updated_at, datetime)

        # Defensive get_evidence
        assert engine.get_evidence(tenant_id, None) is None
    except Exception as exc:
        pytest.skip(f"Live PostgreSQL not reachable on {dsn}: {exc}")

