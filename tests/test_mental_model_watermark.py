"""Tests for lightweight branch/tenant mutation watermark tracking and snapshot caching.

Verifies:
- Mutation watermark immediately advances on append, update, delete, legal erasure,
  privacy backfill, and branch merge.
- Repeated ready-answer reads on unchanged corpora skip full branch export & re-fingerprinting.
- Strict citation span verification runs on every single read.
"""

from __future__ import annotations

import pytest

from mnemosyne.answering import AnswerReadContext
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mental_models import MentalModelService
from mnemosyne.models import Evidence
from mnemosyne.providers.extractive_decomposer import ExtractiveQueryDecomposer
from mnemosyne.sqlite_engine import SqliteEngine

CTX = AnswerReadContext(tenant_id="t", user_id="u", role="agent", max_sensitivity=0)


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    inst = (
        LocalMemoryEngine(tmp_path / "store.json")
        if request.param == "local"
        else SqliteEngine(tmp_path / "store")
    )
    yield inst
    inst.close()


class SimpleProvider:
    def __init__(self):
        self.calls = 0
        self.disclosure = {
            "query_decomposer": {"model": "test"},
            "grounded_reader": {"model": "test"},
        }

    def decompose(self, payload):
        return ExtractiveQueryDecomposer().decompose(payload)

    def read(self, payload):
        self.calls += 1
        for row in payload["evidence"]:
            if "Friday" in row["content"]:
                return {
                    "claims": [{"spans": [{"cid": row["cid"], "quote": "Friday"}]}],
                    "unresolved": False,
                }
        return {"claims": [], "unresolved": True}


def add_evidence(engine, text="Project Zephyr launches Friday.", **kwargs):
    return engine.append_evidence(
        Evidence(
            tenant_id=kwargs.pop("tenant_id", "t"),
            user_id="u",
            actor="user",
            source_type="chat",
            content=text,
            access_policy=kwargs.pop(
                "access_policy", {"tenant": "t", "allow_principals": ["u"]}
            ),
            **kwargs,
        )
    )


def setup_ready_model(engine):
    cid = add_evidence(engine)
    provider = SimpleProvider()
    service = MentalModelService(engine, lambda: provider)
    mid = service.create(CTX, "Launch Model", "When does Project Zephyr launch?")["model_id"]
    result = service.refresh(CTX, mid)
    assert result["status"] == "ready", result
    return service, mid, cid


def test_watermark_advances_on_append(engine):
    service = MentalModelService(engine, SimpleProvider)
    wm_before = service.mutation_watermark(CTX)
    add_evidence(engine, "Extra notes.")
    wm_after = service.mutation_watermark(CTX)
    assert wm_before != wm_after, "Watermark must advance when new evidence is appended"


def test_watermark_advances_on_update_metadata(engine):
    service = MentalModelService(engine, SimpleProvider)
    cid = add_evidence(engine)
    wm_before = service.mutation_watermark(CTX)
    engine.update_evidence_metadata("t", cid, {"revision": "updated"})
    wm_after = service.mutation_watermark(CTX)
    assert wm_before != wm_after, "Watermark must advance when evidence metadata is updated"


def test_watermark_advances_on_delete(engine):
    service, mid, _ = setup_ready_model(engine)
    wm_before = service.mutation_watermark(CTX)
    service.delete(CTX, mid)
    wm_after = service.mutation_watermark(CTX)
    assert wm_before != wm_after, "Watermark must advance when a record is deleted"


def test_watermark_advances_and_invalidates_on_legal_erasure(engine):
    service, mid, cid = setup_ready_model(engine)
    view_before = service.get(CTX, mid)
    assert view_before["status"] == "ready"
    assert view_before["answer"] == "Friday"

    wm_before = service.mutation_watermark(CTX)
    engine.forget("t", cid)
    wm_after = service.mutation_watermark(CTX)
    assert wm_before != wm_after, "Watermark must advance on legal erasure (forget)"

    view_after = service.get(CTX, mid)
    assert view_after["status"] == "stale", "Mental model must immediately become stale upon erasure"
    assert view_after["answer"] == "", "Answer must be withheld when stale"


def test_watermark_advances_and_invalidates_on_privacy_backfill(engine):
    service, mid, cid = setup_ready_model(engine)
    view_before = service.get(CTX, mid)
    assert view_before["status"] == "ready"

    wm_before = service.mutation_watermark(CTX)
    engine.backfill_evidence_privacy("t", cid, ["classified"])
    wm_after = service.mutation_watermark(CTX)
    assert wm_before != wm_after, "Watermark must advance on privacy backfill"

    view_after = service.get(CTX, mid)
    assert view_after["status"] == "stale", "Mental model must become stale when privacy classification revokes access"
    assert view_after["answer"] == ""


def test_watermark_advances_on_branch_merge(engine):
    service = MentalModelService(engine, SimpleProvider)
    wm_main_before = service.mutation_watermark(CTX)

    engine.branch("feature", frm="main", tenant_id="t")
    add_evidence(engine, "Feature branch evidence", branch="feature")
    report = engine.merge("feature", into="main", tenant_id="t")
    assert report is not None

    wm_main_after = service.mutation_watermark(CTX)
    assert wm_main_before != wm_main_after, "Target branch watermark must advance after merging a feature branch"


def test_fast_path_read_skips_export_on_unchanged_corpora(engine, monkeypatch):
    service, mid, _ = setup_ready_model(engine)

    # Initial read establishes the ready-answer cache
    initial_view = service.get(CTX, mid)
    assert initial_view["status"] == "ready"
    assert initial_view["answer"] == "Friday"

    # Track calls to export_tenant_filtered
    export_counts = {"count": 0}
    original_export = engine.export_tenant_filtered

    def counted_export(*args, **kwargs):
        export_counts["count"] += 1
        return original_export(*args, **kwargs)

    monkeypatch.setattr(engine, "export_tenant_filtered", counted_export)

    # Perform 25 repeated reads on the unchanged branch
    for _ in range(25):
        view = service.get(CTX, mid)
        assert view["status"] == "ready"
        assert view["answer"] == "Friday"

    assert export_counts["count"] == 0, (
        f"Repeated ready-answer reads on unchanged corpora should skip full branch export (got {export_counts['count']})"
    )

    # Also verify service.list uses the fast path when all models are ready
    list_views = service.list(CTX)
    assert len(list_views) == 1
    assert list_views[0]["status"] == "ready"
    assert export_counts["count"] == 0, "service.list should also skip export on unchanged ready corpora"


def test_strict_citation_span_verification_runs_on_every_read(engine, monkeypatch):
    service, mid, cid = setup_ready_model(engine)

    # Warm the ready cache
    assert service.get(CTX, mid)["status"] == "ready"

    # Tamper with the saved claim span slice in the record directly
    row = engine.get_mental_model_record("t", mid)
    assert row is not None
    # Corrupt the slice sha256 of the quotation
    row["answer"]["claims"][0]["spans"][0]["slice_sha256"] = "0" * 64
    engine.save_mental_model_record("t", mid, row, expected_version=row["version"])

    # Even if watermark matches or snapshot was cached, strict citation span
    # verification must run on the read and reject the tampered claim
    view = service.get(CTX, mid)
    assert view["status"] == "stale", "Tampered citation span must be caught by strict span verification on read"
    assert view["answer"] == "", "Answer must be withheld for invalid citation span"


def test_clear_watermark_cache_invalidates_snapshot_cache(engine, monkeypatch):
    service, mid, _ = setup_ready_model(engine)
    assert service.get(CTX, mid)["status"] == "ready"

    export_counts = {"count": 0}
    original_export = engine.export_tenant_filtered

    def counted_export(*args, **kwargs):
        export_counts["count"] += 1
        return original_export(*args, **kwargs)

    monkeypatch.setattr(engine, "export_tenant_filtered", counted_export)

    # First read uses cache
    service.get(CTX, mid)
    assert export_counts["count"] == 0

    # Clear cache
    service.clear_watermark_cache()

    # Next read must re-export
    service.get(CTX, mid)
    assert export_counts["count"] == 1, "Clearing watermark cache must force a fresh snapshot export"
