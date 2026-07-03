"""Phase-2 Task 7: ``SqliteEngine.retrieve()`` via the shared pipeline.

LocalMemoryEngine is the byte-parity ORACLE (spec §4.0/§4.2). These tests prove:

1. ``retrieve()``/``deep_search()`` produce a byte-identical ``RetrievalResult``
   vs LocalMemoryEngine on identical seeds — hits (kind, id, score bits,
   channel), confidence bits, abstention, note, token budget/usage, and the
   whole explain dict EXCEPT the ``adapters`` block's ``lexical_backend`` /
   ``graph_backend`` names (intentionally ``sqlite-*`` — the ONLY sanctioned
   divergence, R2/R6). Runs identically in native and ``MNEMOSYNE_PURE=1`` modes
   (the comparison is in-process, so both engines share the active kernel mode).

2. CANDIDATE-SET pushdown parity (the binding scale proof): across a matrix of
   filters, the SET AND ORDER of ``(kind, id)`` selected by SqliteEngine's
   SQL-predicate-pushdown ``_scan_oracle(filt)._candidate_hits(filt)`` equals
   LocalMemoryEngine's full-store ``_candidate_hits(filt)`` — and the pushdown
   demonstrably NARROWS the loaded row set (O(candidates), not O(tenant-rows)).

3. Mixed-precision bitemporal window parity on the ``graph_ppr`` path — the
   DATETIME HAZARD guard: a moment INSIDE a sub-second boundary is resolved via
   Python ``parse_dt`` (never a lexical ``dt_to_json`` TEXT compare), so the
   whole-second relation is correctly included and results byte-match Local.

4. A ConsolidationWorker smoke over ``SqliteQueue`` + ``SqliteEngine`` completes
   (the R3 duck-type contract: get_evidence/export_tenant/append_evidence/
   add_relation/update_evidence_metadata/set_evidence_embedding/register_entity/
   upsert_assertion/retrieve/``adapters``).
"""

from __future__ import annotations

from typing import Any

import pytest

from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB, ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Preference, Relation, RetrievalResult, parse_dt
from mnemosyne.queue import QueueWorker, SqliteQueue
from mnemosyne.sqlite_engine import SqliteEngine

TENANT = "tenant-retrieve"
USER = "user-retrieve"
T_WHOLE = parse_dt("2026-01-01T00:00:00Z")
T_SUB = parse_dt("2026-01-01T00:00:00.500000Z")
MOMENT = parse_dt("2026-01-01T00:00:00.250000Z")


# --------------------------------------------------------------------------- #
# Seeding helpers (byte-identical inputs into both engines).
# --------------------------------------------------------------------------- #
def _seed_basic(engine: Any, *, tenant: str = TENANT, user: str = USER) -> list[str]:
    """A small mixed store: evidence + one active assertion citing two of them."""
    cids = [
        engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id=user,
                actor="user",
                source_type="chat",
                content=f"memory evidence about vector graph tenant branch item {i}",
                trust_tier=0,
                access_policy={"tenant": tenant},
            )
        )
        for i in range(6)
    ]
    engine.upsert_assertion(
        Assertion(
            id="FIXED-ASSERTION-A",
            tenant_id=tenant,
            user_id=user,
            subject="vector",
            predicate="is",
            object="graph",
            confidence=0.9,
            source_evidence_cids=cids[:2],
            status="active",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    return cids


def _seed_matrix(engine: Any, *, tenant: str = TENANT, user: str = USER) -> None:
    """A candidate-filter stressor: spread of trust tiers/sensitivities, a
    quarantined row, a principal-scoped (may_read-gated) row, active + contested
    + superseded assertions, a second branch, preferences."""
    # Create the second branch FIRST (from an empty main) so it holds ONLY its
    # own directly-added evidence — branch() row-copies would otherwise carry
    # assertions with engine-divergent fresh uuids (a Task-6 semantic), which is
    # orthogonal to this Task-7 candidate-pushdown parity.
    engine.branch("feature", frm="main", tenant_id=tenant)
    engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="alpha beta feature-branch row",
            trust_tier=0,
            access_policy={"tenant": tenant},
        ),
        branch="feature",
    )
    # main-branch evidence across trust tiers and sensitivities
    for i in range(4):
        engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id=user,
                actor="user",
                source_type="chat",
                content=f"alpha beta gamma trust row {i}",
                trust_tier=i,  # 0,1,2,3
                access_policy={"tenant": tenant},
            )
        )
    for s in range(3):
        engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id=user,
                actor="user",
                source_type="chat",
                content=f"alpha beta sensitivity row {s}",
                trust_tier=0,
                sensitivity=s,
                access_policy={"tenant": tenant},
            )
        )
    # a quarantined evidence row (excluded unless include_quarantined)
    engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="external",
            source_type="web",
            content="alpha quarantined payload",
            trust_tier=1,
            access_policy={"tenant": tenant},
            metadata={"quarantine_reason": "poison_suspected"},
        )
    )
    # a principal-scoped row that a tenant-only read context cannot see
    # (may_read_item denies it app-side, identically in both engines)
    engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="alpha principal-scoped row",
            trust_tier=0,
            access_policy={"tenant": tenant, "allow_principals": ["user:someone-else"]},
        )
    )
    # assertions: active, contested, superseded (superseded must be excluded)
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="alpha assertion source",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    engine.upsert_assertion(
        Assertion(
            id="MX-ACTIVE",
            tenant_id=tenant,
            user_id=user,
            subject="alpha",
            predicate="rel",
            object="active-val",
            confidence=0.8,
            source_evidence_cids=[cid],
            status="active",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    engine.upsert_assertion(
        Assertion(
            id="MX-CONTESTED",
            tenant_id=tenant,
            user_id=user,
            subject="alpha",
            predicate="rel2",
            object="contested-val",
            confidence=0.5,
            source_evidence_cids=[cid],
            status="contested",
            trust_tier=1,
            access_policy={"tenant": tenant},
        )
    )
    engine.upsert_assertion(
        Assertion(
            id="MX-SUPERSEDED",
            tenant_id=tenant,
            user_id=user,
            subject="alpha",
            predicate="rel3",
            object="superseded-val",
            confidence=0.5,
            source_evidence_cids=[cid],
            status="superseded",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    # preferences: active + retracted (retracted excluded)
    engine.add_preference(
        Preference(
            id="PREF-STYLE",
            tenant_id=tenant,
            user_id=user,
            statement="alpha prefers concise summaries",
            category="style",
            status="active",
            explicit=True,
            access_policy={"tenant": tenant},
        )
    )


def _fresh_pair(seeder: Any) -> tuple[SqliteEngine, LocalMemoryEngine]:
    import tempfile

    sq = SqliteEngine(tempfile.mkdtemp())
    lo = LocalMemoryEngine()
    seeder(sq)
    seeder(lo)
    return sq, lo


# --------------------------------------------------------------------------- #
# RetrievalResult parity signature (adapters backend names are the sole
# sanctioned divergence and are normalised out).
# --------------------------------------------------------------------------- #
def _signature(result: RetrievalResult) -> dict[str, Any]:
    explain = dict(result.explain)
    adapters = dict(explain.get("adapters", {}))
    # The backend NAMES legitimately differ (sqlite-* vs local-*); every other
    # adapters key (embedding name/dims, reranker name) must still match.
    adapters.pop("lexical_backend", None)
    adapters.pop("graph_backend", None)
    explain["adapters"] = adapters
    return {
        "query": result.query,
        "hits": [
            (h.kind, h.id, h.score.hex(), h.channel, h.trust_tier, h.sensitivity, tuple(h.provenance))
            for h in result.hits
        ],
        "confidence": result.confidence.hex(),
        "abstained": result.abstained,
        "note": result.uncertainty_note,
        "token_budget": result.token_budget,
        "used_tokens": result.used_tokens,
        "explain": explain,
    }


@pytest.mark.parametrize("deep", [False, True])
def test_retrieve_explain_parity_vs_local(deep: bool) -> None:
    sq, lo = _fresh_pair(_seed_basic)
    rs = sq.retrieve("vector graph memory", tenant_id=TENANT, deep=deep)
    rl = lo.retrieve("vector graph memory", tenant_id=TENANT, deep=deep)
    assert _signature(rs) == _signature(rl)
    # The sanctioned divergence is present and is ONLY the backend names.
    assert rs.explain["adapters"]["lexical_backend"] == "sqlite-fts5"
    assert rs.explain["adapters"]["graph_backend"] == "sqlite-cached-ppr"
    assert rl.explain["adapters"]["lexical_backend"] != "sqlite-fts5"


def test_deep_search_equals_retrieve_deep() -> None:
    sq, lo = _fresh_pair(_seed_basic)
    # deep_search must equal retrieve(deep=True) structurally vs Local; use a
    # fresh pair per call because retrieve() writes access marks on read.
    ds = sq.deep_search("vector graph memory", tenant_id=TENANT)
    dl = lo.deep_search("vector graph memory", tenant_id=TENANT)
    assert _signature(ds) == _signature(dl)


def test_retrieve_records_assertion_access_synchronously() -> None:
    # R7 collision note: _record_retrieval_access is a SYNCHRONOUS write-on-read;
    # read_marks must be populated in the SAME call (the shared contract asserts
    # read_marks["assertions"] >= 1 synchronously).
    sq = SqliteEngine(__import__("tempfile").mkdtemp())
    _seed_basic(sq)
    result = sq.retrieve("vector graph memory", tenant_id=TENANT, deep=True)
    assert result.explain["read_marks"]["assertions"] >= 1
    assert result.explain["read_marks"]["evidence"] >= 1
    # And the write actually landed: a second retrieve sees a bumped access_count
    # on the assertion (last_accessed/access_count persisted to SQLite).
    export = sq.export_tenant(TENANT)
    accessed = [a for a in export["assertions"] if a["id"] == "FIXED-ASSERTION-A"]
    assert accessed and accessed[0]["access_count"] >= 1


# --------------------------------------------------------------------------- #
# Candidate-SET pushdown parity (the binding scale proof).
# --------------------------------------------------------------------------- #
_FILTER_MATRIX: list[dict[str, Any]] = [
    {"tenant_id": TENANT, "branch": "main"},
    {"tenant_id": TENANT, "branch": "main", "include_quarantined": True},
    {"tenant_id": TENANT, "branch": "main", "include_quarantined": False},
    {"tenant_id": TENANT, "branch": "main", "max_trust_tier": 0},
    {"tenant_id": TENANT, "branch": "main", "max_trust_tier": 1},
    {"tenant_id": TENANT, "branch": "main", "max_trust_tier": 2},
    {"tenant_id": TENANT, "branch": "main", "max_trust_tier": 3},
    # legacy min_trust_tier fallback key (must be honored identically to Local)
    {"tenant_id": TENANT, "branch": "main", "min_trust_tier": 1},
    {"tenant_id": TENANT, "branch": "main", "max_trust_tier": 3, "include_quarantined": True},
    {"tenant_id": TENANT, "branch": "main", "max_sensitivity": 0},
    {"tenant_id": TENANT, "branch": "main", "max_sensitivity": 1},
    {"tenant_id": TENANT, "branch": "feature"},
    {"tenant_id": TENANT, "branch": "feature", "include_quarantined": True},
    # a read context that names the scoping principal (unlocks the principal-
    # scoped row via may_read_item — must unlock identically in both engines)
    {"tenant_id": TENANT, "branch": "main", "allow_principals": ["user:someone-else"]},
]


def _local_candidate_ids(engine: LocalMemoryEngine, filt: dict[str, Any]) -> list[tuple[str, str]]:
    return [(h.kind, h.id) for h in engine._candidate_hits(dict(filt))]


def _sqlite_candidate_ids(engine: SqliteEngine, filt: dict[str, Any]) -> list[tuple[str, str]]:
    oracle = engine._scan_oracle(dict(filt))
    return [(h.kind, h.id) for h in oracle._candidate_hits(dict(filt))]


@pytest.mark.parametrize("filt", _FILTER_MATRIX, ids=lambda f: "+".join(f"{k}={v}" for k, v in f.items()))
def test_candidate_set_pushdown_parity(filt: dict[str, Any]) -> None:
    sq, lo = _fresh_pair(_seed_matrix)
    expected = _local_candidate_ids(lo, filt)
    actual = _sqlite_candidate_ids(sq, filt)
    # SET and ORDER must match exactly — the pushed-down SQL predicate selects
    # exactly the superset _candidate_hits iterates, in the same rowid order.
    assert actual == expected


def test_pushdown_narrows_loaded_rows() -> None:
    # Proof the pushdown is O(candidates), not O(tenant-rows): a restrictive
    # trust ceiling must hydrate strictly fewer evidence rows than the whole
    # tenant/branch holds, while a permissive ceiling hydrates all of them.
    sq = SqliteEngine(__import__("tempfile").mkdtemp())
    _seed_matrix(sq)
    conn = sq._connect(TENANT)
    total_main_evidence = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE tenant_id = ? AND branch = 'main' AND erased = 0",
        (TENANT,),
    ).fetchone()[0]
    restrictive = sq._scan_oracle({"tenant_id": TENANT, "branch": "main", "max_trust_tier": 0})
    permissive = sq._scan_oracle(
        {"tenant_id": TENANT, "branch": "main", "max_trust_tier": 3, "include_quarantined": True}
    )
    # A restrictive trust ceiling hydrates strictly fewer rows than the whole
    # tenant/branch holds AND fewer than a permissive ceiling — proving the
    # candidate load is O(candidates), not O(tenant-rows).
    assert len(restrictive.evidence) < total_main_evidence
    assert len(restrictive.evidence) < len(permissive.evidence)


# --------------------------------------------------------------------------- #
# Mixed-precision bitemporal window parity (DATETIME HAZARD guard).
# --------------------------------------------------------------------------- #
def _seed_graph(engine: Any) -> None:
    src = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="chat",
            content="alpha relates to beta grounded source",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    # whole-second valid_from → dt_to_json emits NO fractional part; a lexical
    # TEXT compare vs a fractional moment ("...00.250000Z") would MISORDER it
    # ('Z' > '.'), wrongly excluding it. Python parse_dt keeps it correct.
    engine.add_relation(
        Relation(
            id="REL-BETA",
            tenant_id=TENANT,
            source="alpha",
            predicate="relates_to",
            target="beta",
            valid_from=T_WHOLE,
            valid_to=None,
            source_evidence_cids=[src],
            access_policy={"tenant": TENANT},
        )
    )
    # sub-second valid_from strictly AFTER the query moment → excluded by both.
    engine.add_relation(
        Relation(
            id="REL-GAMMA",
            tenant_id=TENANT,
            source="alpha",
            predicate="relates_to",
            target="gamma",
            valid_from=T_SUB,
            valid_to=None,
            source_evidence_cids=[src],
            access_policy={"tenant": TENANT},
        )
    )


def test_graph_ppr_mixed_precision_window_parity() -> None:
    sq, lo = _fresh_pair(_seed_graph)
    filt = {"tenant_id": TENANT, "branch": "main"}
    hs = sq.graph_ppr(["alpha"], 8, as_of=MOMENT, tenant_id=TENANT, branch="main", filt=filt)
    hl = lo.graph_ppr(["alpha"], 8, as_of=MOMENT, tenant_id=TENANT, branch="main", filt=filt)
    sig_s = [(h.kind, h.id, h.text, h.score.hex(), h.channel) for h in hs]
    sig_l = [(h.kind, h.id, h.text, h.score.hex(), h.channel) for h in hl]
    assert sig_s == sig_l
    # The whole-second relation WAS included at the sub-second moment (proving no
    # lexical dt compare dropped it); the strictly-later sub-second one was not.
    targets = {h.metadata.get("target") for h in hs}
    assert "beta" in targets
    assert "gamma" not in targets


# --------------------------------------------------------------------------- #
# Consolidation duck-type smoke over SqliteQueue + SqliteEngine.
# --------------------------------------------------------------------------- #
def test_consolidation_worker_smoke_completes(tmp_path: Any) -> None:
    engine = SqliteEngine(tmp_path / "engine")
    tenant, user = "consolidate-tenant", "consolidate-user"
    source_cids = [
        engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id=user,
                actor="user",
                source_type="chat",
                content=f"Consolidation source {i} preserves raw evidence provenance for summary.",
                trust_tier=0,
                access_policy={"tenant": tenant},
            )
        )
        for i in range(4)
    ]
    cworker = ConsolidationWorker(engine, gate_cases=[])
    queue = SqliteQueue(tmp_path / "queue", tenant)
    queue.enqueue(
        CONSOLIDATE_EVIDENCE_JOB,
        {
            "tenant_id": tenant,
            "branch": "main",
            "source_evidence_cids": source_cids,
            "passes": ["summarizer"],
        },
    )
    qworker = QueueWorker(
        queue,
        {CONSOLIDATE_EVIDENCE_JOB: lambda payload: cworker.run_queue_payload(payload)},
    )
    job = qworker.run_once(CONSOLIDATE_EVIDENCE_JOB)
    assert job is not None
    # The job leased, ran the consolidation pass against the SqliteEngine
    # duck-type, and COMPLETED (not failed, not skipped-for-missing-method).
    assert queue.snapshot().get("complete", 0) == 1
    summarizer = next(item for item in (job.result or {})["pass_results"] if item["name"] == "summarizer")
    assert summarizer["status"] == "complete"
    # The summary pass wrote back through the engine duck-type (append_evidence +
    # add_relation): the tenant now holds a consolidation-summary evidence row.
    exported = engine.export_tenant(tenant)
    assert any(item["source_type"] == "consolidation-summary" for item in exported["evidence"])
    engine.close()
