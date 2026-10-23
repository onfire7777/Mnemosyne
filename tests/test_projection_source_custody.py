"""Facts cannot reveal text denied by their current evidence lineage."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import os
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Hit, Preference
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.retrieval import projection_sources_readable
from mnemosyne.sqlite_engine import SqliteEngine
from mnemosyne.text import hashing_embedding


QUERY = "secret launch code amber"


@pytest.fixture(params=["local", "sqlite", "postgres"])
def store(request: Any, tmp_path: Any, monkeypatch: Any):
    monkeypatch.setenv("MNEMOSYNE_RETRIEVAL_RESULT_CACHE_SIZE", "16")
    if request.param == "local":
        engine = LocalMemoryEngine()
    elif request.param == "sqlite":
        engine = SqliteEngine(tmp_path / "store")
    else:
        dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
        if not dsn:
            pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
        engine = PostgresEngine(dsn)
    tenant = f"projection-custody-{uuid4()}"
    yield engine, tenant
    # The restricted runtime role cannot delete tenants; disposable PG stores
    # retain these unique fixture scopes until their cluster is removed.
    close = getattr(engine, "close", None)
    if close:
        close()
    elif isinstance(engine, PostgresEngine):
        engine.close_connections()


def context(tenant: str, **kwargs: Any) -> dict[str, Any]:
    return {"tenant_id": tenant, "user_id": "reader", "role": "reader", "max_trust_tier": 5, **kwargs}


def source(store: Any, text: str = "The secret launch code is amber.", **kwargs: Any) -> str:
    engine, tenant = store
    branch = kwargs.pop("branch", "main")
    return engine.append_evidence(Evidence(
        tenant_id=tenant, user_id="author", actor="user", source_type="chat", content=text, **kwargs,
    ), branch=branch)


def summary(store: Any, cids: list[str], *, proposal: bool = False) -> str:
    engine, tenant = store
    metadata = {"provider_proposal": {"input_cids": cids}} if proposal else {
        "summary": {"source_evidence_cids": cids, "status": "active"},
    }
    return engine.append_evidence(Evidence(
        tenant_id=tenant, user_id="author", actor="system", content="The secret launch code is amber.",
        source_type="provider-proposal" if proposal else "consolidation-summary", metadata=metadata,
    ))


def assertion(store: Any, cids: list[str]) -> str:
    engine, tenant = store
    return engine.upsert_assertion(Assertion(
        tenant_id=tenant, user_id="author", subject="secret launch code", predicate="is", object="amber",
        confidence=0.95, source_evidence_cids=cids, status="active",
    ))


def read(store: Any, route: str, **kwargs: Any) -> list[Any]:
    engine, tenant = store
    filt = context(tenant, **kwargs)
    if route == "retrieve":
        return engine.retrieve(QUERY, tenant_id=tenant, filt=filt, record_access=False).hits
    return getattr(engine, route + "_search")(QUERY, 30, filt)


@pytest.mark.parametrize("route", ["lexical", "vector", "retrieve"])
@pytest.mark.parametrize("proposal", [False, True])
def test_partial_forget_withholds_fact_supported_only_by_incomplete_derived_prose(store, route, proposal):
    engine, tenant = store
    first = source(store)
    other = source(store, "The archive has a public reception desk.")
    derived = summary(store, [first, other], proposal=proposal)
    fact = assertion(store, [first, derived])
    assert fact in {hit.id for hit in read(store, route)}  # warm caches

    engine.forget(tenant, first)

    assert engine.get_evidence_for_read(tenant, derived, access_context=context(tenant)) is None
    assert fact not in {hit.id for hit in read(store, route)}
    # This is read-time denial, not destruction of the retained projection.
    retained = next(row for row in engine.export_tenant(tenant)["assertions"] if row["id"] == fact)
    assert retained["status"] == "active"
    assert retained["source_evidence_cids"] == [derived]


@pytest.mark.parametrize("route", ["lexical", "vector", "retrieve"])
def test_independently_supported_fact_remains_after_partial_forget(store, route):
    engine, tenant = store
    first = source(store)
    other = source(store, "A separate witness confirms the secret launch code is amber.")
    fact = assertion(store, [first, other])
    assert fact in {hit.id for hit in read(store, route)}
    engine.forget(tenant, first)
    assert fact in {hit.id for hit in read(store, route)}


@pytest.mark.parametrize("route", ["lexical", "vector", "retrieve"])
@pytest.mark.parametrize("nested", [False, True])
def test_source_privacy_change_withholds_warmed_fact(store, route, nested):
    engine, tenant = store
    original = source(store)
    cited = summary(store, [original]) if nested else original
    fact = assertion(store, [cited])
    assert fact in {hit.id for hit in read(store, route)}
    engine.backfill_evidence_privacy(tenant, original, ["secret"])
    assert fact not in {hit.id for hit in read(store, route)}


@pytest.mark.parametrize("route", ["lexical", "vector", "retrieve"])
@pytest.mark.parametrize("restriction", ["redaction", "expired", "missing", "foreign_tenant", "foreign_branch"])
def test_projection_does_not_bypass_source_scope_or_policy(store, route, restriction):
    engine, tenant = store
    if restriction == "missing":
        cited = "0" * 64
    elif restriction == "foreign_tenant":
        cited = source((engine, tenant + "-other"))
    elif restriction == "foreign_branch":
        source(store, "Initialize the main branch.")
        engine.branch("archive", tenant_id=tenant)
        cited = source(store, branch="archive")
    else:
        policy = ({"redact_fields": ["code"], "min_role_for_raw": "operator"}
                  if restriction == "redaction" else {"expires_at": "2000-01-01T00:00:00Z"})
        cited = source(store, access_policy=policy)
    fact = assertion(store, [cited])
    assert fact not in {hit.id for hit in read(store, route)}


def test_source_free_fact_keeps_existing_read_behavior(store):
    fact = assertion(store, [])
    assert fact in {hit.id for hit in read(store, "lexical")}


def test_source_expiry_invalidates_warm_candidates_and_results(store, monkeypatch):
    engine, _ = store
    expires = datetime.now(UTC) + timedelta(days=1)
    cited = source(store, access_policy={"expires_at": expires.isoformat()})
    fact = assertion(store, [cited])
    assert fact in {hit.id for hit in read(store, "retrieve")}

    class AfterExpiry(datetime):
        @classmethod
        def now(cls, tz=None):
            return (expires + timedelta(seconds=1)).astimezone(tz)

    monkeypatch.setattr("mnemosyne.access_policy.datetime", AfterExpiry)
    monkeypatch.setattr("mnemosyne.engine.utc_now", lambda: AfterExpiry.now(UTC))
    assert fact not in {hit.id for hit in read(store, "retrieve")}
    assert fact not in {hit.id for hit in read(store, "vector")}


def test_denied_fact_never_reaches_embedding_adapter(store):
    engine, tenant = store
    cited = source(store)
    fact = assertion(store, [cited])
    engine.backfill_evidence_privacy(tenant, cited, ["secret"])

    class Recorder:
        name = "projection-custody-recorder"
        dims = engine.adapters.embedding.dims

        def __init__(self):
            self.texts = []

        def embed(self, text):
            self.texts.append(text)
            return hashing_embedding(text, dims=self.dims)

    recorder = Recorder()
    engine.adapters = replace(engine.adapters, embedding=recorder)
    assert fact not in {hit.id for hit in read(store, "vector")}
    assert "secret launch code is amber" not in recorder.texts


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_preference_uses_the_same_source_gate(backend, tmp_path):
    engine = LocalMemoryEngine() if backend == "local" else SqliteEngine(tmp_path / "preferences")
    store = engine, "preference-custody"
    cited = source(store)
    preference = engine.add_preference(Preference(
        tenant_id=store[1], user_id="author", category="security", statement="The secret launch code is amber.",
        source_evidence_cids=[cited],
    ))
    assert preference in {hit.id for hit in read(store, "lexical")}
    engine.backfill_evidence_privacy(store[1], cited, ["secret"])
    assert preference not in {hit.id for hit in read(store, "lexical")}
    close = getattr(engine, "close", None)
    if close:
        close()


@pytest.mark.parametrize("sources", [None, "cid", [42], [""], [" cid "]])
def test_malformed_projection_lineage_fails_closed(sources):
    engine = LocalMemoryEngine()
    assert not projection_sources_readable(
        engine, sources, tenant_id="t", branch="main", filt=context("t"), policy=engine.policy,
    )


@pytest.mark.parametrize("mutation", ["retired", "malformed", "cycle"])
def test_derived_source_mutation_invalidates_warm_fact(store, mutation):
    engine, tenant = store
    original = source(store)
    derived = summary(store, [original])
    fact = assertion(store, [derived])
    assert fact in {hit.id for hit in read(store, "retrieve")}
    metadata = {"summary": {"source_evidence_cids": [original], "status": "retired"}}
    if mutation == "malformed":
        metadata = {"summary": {"source_evidence_cids": "not-a-list"}}
    elif mutation == "cycle":
        metadata = {"summary": {"source_evidence_cids": [derived]}}
    engine.update_evidence_metadata(tenant, derived, metadata)
    for route in ("lexical", "vector", "retrieve"):
        assert fact not in {hit.id for hit in read(store, route)}


class ProjectionAdapter:
    name = "test-projection-adapter"

    def __init__(self, tenant, item_id, kind="assertion"):
        self.tenant = tenant
        self.item_id = item_id
        self.kind = kind

    def search(self, *args, **kwargs):
        return [Hit(
            id=self.item_id, kind=self.kind, tenant_id=self.tenant, branch="main",
            text="FORGED or stale private projection text", score=0.8, channel="external",
            provenance=[], trust_tier=0, sensitivity=0,
            metadata={"confidence": 1.0, "reality_class": "grounded"},
        )]


@pytest.mark.parametrize("kind", ["assertion", "preference"])
def test_adapter_uses_current_projection_identity_text_and_custody(store, kind, monkeypatch):
    engine, tenant = store
    cited = source(store)
    item_id = assertion(store, [cited]) if kind == "assertion" else engine.add_preference(Preference(
        tenant_id=tenant, user_id="author", category="constraint",
        statement="The secret launch code is amber.", source_evidence_cids=[cited], explicit=True,
    ))
    adapter = ProjectionAdapter(tenant, item_id, kind)
    engine.adapters = replace(engine.adapters, lexical_retriever=adapter)

    def no_export(*args, **kwargs):
        raise AssertionError("adapter custody must use an indexed identity lookup, not a tenant export")

    monkeypatch.setattr(engine, "export_tenant", no_export)
    hit, = read(store, "lexical")
    assert hit.id == item_id and hit.provenance == [cited]
    assert hit.text in {"secret launch code is amber", "The secret launch code is amber."}
    assert hit.score == 0.8 and hit.metadata["confidence"] != 1.0
    engine.backfill_evidence_privacy(tenant, cited, ["secret"])
    assert read(store, "lexical") == []  # adapter's empty provenance cannot bypass the ledger


@pytest.mark.parametrize("identity", ["unknown", "foreign_tenant", "foreign_branch"])
def test_adapter_rejects_projection_outside_authoritative_scope(store, identity):
    engine, tenant = store
    if identity == "unknown":
        item_id = str(uuid4())
    elif identity == "foreign_tenant":
        other = (engine, tenant + "-other")
        item_id = assertion(other, [source(other)])
    else:
        source(store)
        engine.branch("archive", tenant_id=tenant)
        item_id = engine.upsert_assertion(Assertion(
            tenant_id=tenant, subject="secret launch code", predicate="is", object="amber", status="active",
        ), branch="archive")
    engine.adapters = replace(engine.adapters, lexical_retriever=ProjectionAdapter(tenant, item_id))
    assert read(store, "lexical") == []


@pytest.mark.parametrize("thin_canary", [False, True])
def test_shared_source_list_is_validated_once_per_candidate_scan(monkeypatch, thin_canary):
    from mnemosyne.cid_lists import intern_cids

    engine = LocalMemoryEngine()
    store = engine, "shared-source-list"
    cids = intern_cids([source(store, f"Independent launch source {i}") for i in range(12)])
    for i in range(20):
        engine.upsert_assertion(Assertion(
            tenant_id=store[1], subject=f"launch fact {i}", predicate="is", object="amber",
            source_evidence_cids=cids, status="active",
        ))
    reads = []
    raw_get = engine.get_evidence

    def counted_get(tenant, cid, branch="main"):
        reads.append(cid)
        return raw_get(tenant, cid, branch)

    monkeypatch.setattr(engine, "get_evidence", counted_get)
    if thin_canary:
        engine.branch("canary-custody", kind="canary", tenant_id=store[1])
        hits = engine._candidate_hits(context(store[1], branch="canary-custody"))
        assert engine._overlays  # preserve the optimization while bounding work
    else:
        hits = engine._candidate_hits_uncached(context(store[1]))
    assert len([hit for hit in hits if hit.kind == "assertion"]) == 20
    assert len(reads) == len(cids)


def test_thin_canary_cached_projection_obeys_source_expiry(monkeypatch):
    engine = LocalMemoryEngine()
    store = engine, "canary-source-expiry"
    expires = datetime.now(UTC) + timedelta(days=1)
    cited = source(store, access_policy={"expires_at": expires.isoformat()})
    fact = assertion(store, [cited])
    engine.branch("canary-custody", kind="canary", tenant_id=store[1])
    filt = context(store[1], branch="canary-custody")
    assert fact in {hit.id for hit in engine.lexical_search(QUERY, 30, filt)}

    class AfterExpiry(datetime):
        @classmethod
        def now(cls, tz=None):
            return (expires + timedelta(seconds=1)).astimezone(tz)

    monkeypatch.setattr("mnemosyne.access_policy.datetime", AfterExpiry)
    monkeypatch.setattr("mnemosyne.engine.utc_now", lambda: AfterExpiry.now(UTC))
    assert fact not in {hit.id for hit in engine.lexical_search(QUERY, 30, filt)}
    assert engine._overlays
