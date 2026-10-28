from __future__ import annotations

from datetime import UTC, datetime

from mnemosyne.answering import (
    AnswerReadContext,
    ReflectDisposition,
    adaptive_synthesize,
    detect_synthesis_intent,
    resolve_hierarchical_evidence,
)
from mnemosyne.consolidation import ContextualEntityResolver, unmerge_entity
from mnemosyne.documents import DocumentService, extract_changed_segments
from mnemosyne.dreamer import SandboxedDreamer
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.episodic_facts import (
    classify_epistemic_fact,
    extract_episodic_facts,
    extract_open_domain_facts,
    parse_relative_or_prose_date,
)
from mnemosyne.ingestion import IngestionPipeline, IngestRequest, scrub_secrets_and_pii
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.mental_models import (
    MentalModelService,
    extract_model_dependencies,
    is_affected_by_evidence,
)
from mnemosyne.models import Evidence, Hit
from mnemosyne.observations import Observation, ProofQuote, reconcile_observation
from mnemosyne.passages import PassageGraph, PassageRecord
from mnemosyne.pipeline import deduplicate_observation_preferred
from mnemosyne.prefetch import AnticipatoryPrefetcher, PredictabilityGate
from mnemosyne.retrieval import precision_aware_recency_score, spread_temporal_buckets
from mnemosyne.self_optimization import AdaptiveRouteWeighter
from mnemosyne.storage import LocalObjectStore
from mnemosyne.user_model import (
    UserModelEntry,
    corroborate_entry,
    detect_preference_drift,
    effective_authority,
)


def test_r1_1_dynamic_passage_graph_pmi_synonyms_and_embeddings() -> None:
    graph = PassageGraph()
    docs = [
        ("c1", "We migrated the distributed ledger consensus engine to Raft protocol."),
        ("c2", "The distributed ledger consensus cluster uses Raft replication for durability."),
        ("c3", "Our distributed ledger consensus nodes elected a new Raft leader."),
        ("c4", "The consensus protocol handles distributed ledger state machine transitions."),
        ("c5", "Frontend CSS styling uses Tailwind utility classes for layout."),
        ("c6", "Mobile UI components render responsive layouts on iOS and Android."),
    ]
    for pid, text in docs:
        graph.add_passage(PassageRecord(passage_id=pid, text=text, tenant_id="t1"))

    # Bigram PMI discovery
    pmi = graph.compute_bigram_pmi("distributed", "ledger")
    assert pmi > 0.0
    phrases = graph.high_pmi_phrases("distributed ledger consensus", min_pmi=0.1)
    assert any((w1, w2) == ("distributed", "ledger") for w1, w2, _score in phrases)

    # PPMI synonym / co-occurrence induction
    synonyms = graph.discover_corpus_synonyms("raft", top_k=10, min_pmi=0.05)
    assert len(synonyms) > 0
    assert any(term in {"distributed", "ledger", "consensus", "protocol", "replication", "leader"} for term, _ppmi in synonyms)

    # Contextual vector embedding
    vec_raft = graph.corpus_contextual_embedding("raft", dims=64)
    vec_consensus = graph.corpus_contextual_embedding("consensus", dims=64)
    assert len(vec_raft) == 64
    dot = sum(a * b for a, b in zip(vec_raft, vec_consensus, strict=True))
    assert dot > 0.0


def test_r1_2_epistemic_classification_prose_dates_and_open_domain_facts() -> None:
    assert classify_epistemic_fact("I noticed the latency spiked during peak hours.", "user") == "observation"
    assert classify_epistemic_fact("I updated the configuration file and restarted nginx.", "assistant") == "agent_experience"
    assert classify_epistemic_fact("I love hiking in the Pacific Northwest.", "user") == "user_experience"
    assert classify_epistemic_fact("PostgreSQL 16 supports incremental sort and SIMD JSON parsing.", "user") == "world_fact"

    ref = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    start_q, end_q, prec_q = parse_relative_or_prose_date("We launched the beta in Q2 2025.", reference_time=ref)
    assert prec_q == "quarter"
    assert start_q is not None and start_q.year == 2025 and start_q.month == 4
    assert end_q is not None and end_q.year == 2025 and end_q.month == 6

    start_rel, _end_rel, prec_rel = parse_relative_or_prose_date("I visited the dentist 3 days ago.", reference_time=ref)
    assert prec_rel == "day"
    assert start_rel is not None and start_rel.day == 25

    ev = Evidence(
        tenant_id="t1",
        user_id="u1",
        actor="user",
        source_type="chat",
        content="Alice prefers dark mode. We deployed the payment service on Kubernetes in Q1 2025.",
        created_at=ref,
    )
    open_facts = extract_open_domain_facts(ev)
    assert len(open_facts.assertions) >= 1
    assert len(open_facts.relations) >= 1

    assertions, _rels = extract_episodic_facts(ev)
    assert any("epistemic_class" in a.qualifiers for a in assertions)


def test_r1_3_contextual_entity_resolution_and_reversible_unmerge() -> None:
    resolver = ContextualEntityResolver()
    res_disambig = resolver.resolve(
        "t1",
        [
            {"id": "e1", "name": "Alex (Engineering, NYC)", "source_evidence_cids": ["cid-nyc"]},
            {"id": "e2", "name": "Alex (Finance, London)", "source_evidence_cids": ["cid-lon"]},
        ],
    )
    cands = res_disambig["candidates"]
    assert cands[0]["entity_key"] != cands[1]["entity_key"]

    res_exact = resolver.resolve(
        "t1",
        [
            {"id": "m1", "name": "Mercury", "source_evidence_cids": ["cid-m1"]},
            {"id": "m2", "name": "mercury-v2", "source_evidence_cids": ["cid-m2"]},
        ],
        exact_name=True,
    )
    assert res_exact["candidates"][0]["entity_key"] != res_exact["candidates"][1]["entity_key"]

    # Merge two compatible mentions and then unmerge
    res_merged = resolver.resolve(
        "t1",
        [
            {"id": "r1", "name": "Elena Rostova", "context": {"role": "researcher"}, "source_evidence_cids": ["cid-1"]},
            {"id": "r2", "name": "Elena_Rostova", "context": {"role": "researcher"}, "source_evidence_cids": ["cid-2"]},
        ],
    )
    assert res_merged["candidates"][0]["entity_key"] == res_merged["candidates"][1]["entity_key"]
    merged_id = res_merged["candidates"][0]["entity_key"]
    assert len(resolver.merge_history) >= 1

    unmerged = unmerge_entity(resolver, merged_id)
    assert unmerged.get("status") == "unmerged" or unmerged.get("unmerged") is True


def test_r2_temporal_spreading_observation_dedup_and_adaptive_route_bandit() -> None:
    # R2.1 Precision-aware recency and bucket spreading
    day_score = precision_aware_recency_score(5.0, precision="day")
    year_score = precision_aware_recency_score(5.0, precision="year")
    assert day_score != year_score

    hits = [
        Hit(id="h_oct1", kind="evidence", tenant_id="t", branch="main", text="Oct 1", score=10.0, channel="lexical", metadata={"created_at": "2026-10-01T10:00:00+00:00"}),
        Hit(id="h_oct2", kind="evidence", tenant_id="t", branch="main", text="Oct 2", score=9.5, channel="lexical", metadata={"created_at": "2026-10-02T10:00:00+00:00"}),
        Hit(id="h_Aug", kind="evidence", tenant_id="t", branch="main", text="Aug 15", score=8.0, channel="lexical", metadata={"created_at": "2026-08-15T10:00:00+00:00"}),
        Hit(id="h_may", kind="evidence", tenant_id="t", branch="main", text="May 10", score=7.5, channel="lexical", metadata={"created_at": "2026-05-10T10:00:00+00:00"}),
    ]
    spread = spread_temporal_buckets(hits, k=3, bucket_granularity="month")
    assert [h.id for h in spread] == ["h_oct1", "h_Aug", "h_may"]

    # R2.2 Observation-preferred deduplication with independent source expansion budget
    obs_hit = Hit(
        id="obs-1",
        kind="observation",
        tenant_id="t",
        branch="main",
        text="Synthesized observation about deployment.",
        score=1.0,
        channel="semantic",
        provenance=("raw-1",),
        metadata={"memory_type": "observation", "source_evidence_cids": ["raw-1"]},
    )
    raw_covered = Hit(
        id="raw-1",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="Raw chunk 1 about deployment.",
        score=0.9,
        channel="lexical",
    )
    raw_uncovered = Hit(
        id="raw-2",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="Raw chunk 2 about monitoring.",
        score=0.8,
        channel="lexical",
    )
    deduped, report = deduplicate_observation_preferred(
        [obs_hit, raw_covered, raw_uncovered],
        fact_budget_tokens=100,
        source_expansion_budget_tokens=100,
    )
    assert report["primary_count"] == 2
    assert report["covered_source_count"] == 1
    assert report["expanded_source_count"] == 1
    assert [h.id for h in deduped] == ["obs-1", "raw-2", "raw-1"]

    # R2.3 Adaptive route weighter online MWU bandit
    weighter = AdaptiveRouteWeighter(learning_rate=0.25, min_weight=0.05)
    initial_graph_w = weighter.get_weights("t1")["graph"]
    for _ in range(5):
        weighter.record_outcome("t1", {"graph": 1.0, "lexical": 0.1, "semantic": 0.1})
    updated_graph_w = weighter.get_weights("t1")["graph"]
    assert updated_graph_w > initial_graph_w


def test_r3_reflect_disposition_hierarchical_evidence_and_adaptive_synthesis() -> None:
    engine = LocalMemoryEngine()
    q1 = "On 2026-01-10 we used Redis 6 for session caching."
    q2 = "On 2026-06-15 we switched from Redis 6 to DragonflyDB for session caching."
    c1 = engine.append_evidence(Evidence(
        tenant_id="t_ref",
        user_id="u1",
        actor="user",
        source_type="session",
        content=q1,
    ))
    c2 = engine.append_evidence(Evidence(
        tenant_id="t_ref",
        user_id="u1",
        actor="user",
        source_type="session",
        content=q2,
    ))
    obs = Observation(
        tenant_id="t_ref",
        user_id="u1",
        subject="caching",
        topic="migration",
        content="Session caching migrated from Redis 6 to DragonflyDB.",
        branch="main",
        proof_quotes=[
            ProofQuote(
                cid=c1,
                quote=q1,
                start=0,
                end=len(q1),
            ),
            ProofQuote(
                cid=c2,
                quote=q2,
                start=0,
                end=len(q2),
            ),
        ],
        source_evidence_cids=[c1, c2],
        independent_source_count=2,
        standing=0.85,
    )
    engine.observation_upsert(obs)

    ctx = AnswerReadContext(tenant_id="t_ref", user_id="u1", role="operator")
    disp = ReflectDisposition(skepticism=0.8, conciseness=0.8, mission="caching migration")
    hier = resolve_hierarchical_evidence(engine, "How did session caching change?", ctx, disposition=disp)
    rows = hier["evidence_rows"]
    assert len(rows) >= 1

    assert detect_synthesis_intent("How many times did we deploy?") == "count"
    assert detect_synthesis_intent("What is the timeline of caching changes?") == "timeline"
    assert detect_synthesis_intent("How did our session caching change?") == "state_diff"
    assert detect_synthesis_intent("Compare Redis 6 versus DragonflyDB.") == "comparison"

    synth = adaptive_synthesize("How did our session caching change?", rows, disposition=disp)
    assert synth["intent"] == "state_diff"
    assert not synth["abstained"]
    assert len(synth["claims"]) >= 1


def test_r4_mental_model_delta_refresh_documents_and_pre_persistence_defense(tmp_path) -> None:
    engine = LocalMemoryEngine()
    ctx = AnswerReadContext(tenant_id="t_doc", user_id="u1", role="operator")

    # R4.1 Mental model dependencies & delta refresh
    deps = extract_model_dependencies(
        "What database does the billing service use?",
        "The billing service uses PostgreSQL 16.",
        ["cid-db-1"],
    )
    assert "billing" in deps["dependent_entities"] or "billing" in deps["dependent_predicates"]
    model_dict = {
        "question": "What database does the billing service use?",
        "answer": {"answer": "The billing service uses PostgreSQL 16."},
        "source_evidence_cids": ["cid-db-1"],
    }
    assert is_affected_by_evidence(model_dict, "We upgraded the billing database to PostgreSQL 17.")
    assert not is_affected_by_evidence(model_dict, "I bought a new pair of running shoes.")

    mm_service = MentalModelService(engine)
    c_init = engine.append_evidence(Evidence(
        tenant_id="t_doc",
        user_id="u1",
        actor="user",
        source_type="doc",
        content="The billing service runs on PostgreSQL 16 in production.",
    ))
    created_mm = mm_service.create(ctx, "mm-billing", "What does the billing service run on?")
    mm_id = created_mm["model_id"]
    assert mm_id
    delta_res = mm_service.delta_refresh(ctx, mm_id, [c_init])
    assert "affected" in delta_res

    # R4.2 Document changed-segment extraction & branch reconciliation + MCP parity
    doc_service = DocumentService(engine)
    create_res = doc_service.create(
        ctx,
        "arch-spec",
        "The auth service uses Ed25519 tokens.\n\nRate limiting is set to 500 rps.",
        operation_id="op-create-1",
        auto_extract=True,
    )
    assert create_res.extracted is not None
    assert create_res.extracted["extracted_count"] == 2

    replace_res = doc_service.replace(
        ctx,
        "arch-spec",
        "The auth service uses Ed25519 tokens.\n\nRate limiting is set to 1000 rps.",
        expected_revision=1,
        operation_id="op-replace-2",
    )
    ext_delta = extract_changed_segments(replace_res, engine)
    assert ext_delta["extracted_count"] == 1
    assert ext_delta["skipped_unchanged_count"] == 1

    # Branch reconciliation via MemoryTools
    engine.branch("staging")
    tools = MemoryTools(engine)
    reconcile_res = tools.document_reconcile_branch(
        tenant_id="t_doc",
        user_id="u1",
        source_branch="main",
        target_branch="staging",
        role="operator",
    )
    assert reconcile_res["reconciled_count"] >= 1

    # R4.3 Multimodal ProofQuote and Pre-Persistence Secret/PII Scrubbing
    pq = ProofQuote(
        cid=c_init,
        quote="The billing service runs on PostgreSQL 16",
        start=0,
        end=41,
        block_index=2,
        modality="image_ocr",
        attachment_cid="att-img-001",
    )
    pq_roundtrip = ProofQuote.from_dict(pq.to_dict())
    assert pq_roundtrip.block_index == 2
    assert pq_roundtrip.modality == "image_ocr"
    assert pq_roundtrip.attachment_cid == "att-img-001"
    obs_base = Observation(
        tenant_id="t_doc",
        user_id="u1",
        subject="billing",
        topic="database",
        content="Billing runs on PG 16",
        branch="main",
        proof_quotes=[pq],
        source_evidence_cids=[c_init],
    )
    reconciled_obs, _is_contra = reconcile_observation(obs_base, obs_base)
    assert reconciled_obs.proof_quotes[0].block_index == 2

    scrubbed_text, counts = scrub_secrets_and_pii(
        "Contact alice@example.com or SSN 123-45-6789 with token sk-abcdefgh1234567890abcdefgh1234567890"
    )
    assert "alice@example.com" not in scrubbed_text
    assert "123-45-6789" not in scrubbed_text
    assert counts.get("total_redactions", counts.get("redaction_total", 0)) >= 2

    pipeline = IngestionPipeline(engine, LocalObjectStore(tmp_path / "objs"), pre_persistence_scrub=True)
    ing_res = pipeline.ingest(IngestRequest(
        tenant_id="t_doc",
        user_id="u1",
        actor="user",
        source_type="note",
        content="My email is secret_user@example.com and my SSN is 123-45-6789.",
    ))
    stored_ev = engine.get_evidence("t_doc", ing_res.cid)
    assert stored_ev is not None
    assert "secret_user@example.com" not in stored_ev.content
    assert "123-45-6789" not in stored_ev.content
    assert stored_ev.metadata.get("pre_persistence_scrubbed") is True


def test_r5_autonomous_prefetch_dreamer_structural_holes_and_user_model_graduation() -> None:
    engine = LocalMemoryEngine()
    ev1 = Evidence(
        tenant_id="t_cog",
        user_id="u1",
        actor="user",
        source_type="doc",
        content="Project Chronos uses Rust and WebAssembly for edge workers.",
        access_policy={"tenant": "t_cog"},
    )
    ev2 = Evidence(
        tenant_id="t_cog",
        user_id="u1",
        actor="user",
        source_type="doc",
        content="Project Chronos is deployed disabled in production across all regions.",
        access_policy={"tenant": "t_cog"},
    )
    ev3 = Evidence(
        tenant_id="t_cog",
        user_id="u1",
        actor="user",
        source_type="doc",
        content="Project Chronos is deployed enabled in production across all regions.",
        access_policy={"tenant": "t_cog"},
    )
    c_cog_1 = engine.append_evidence(ev1)
    c_cog_2 = engine.append_evidence(ev2)
    c_cog_3 = engine.append_evidence(ev3)
    stored_evs = [
        engine.get_evidence("t_cog", c_cog_1),
        engine.get_evidence("t_cog", c_cog_2),
        engine.get_evidence("t_cog", c_cog_3),
    ]

    # R5.1 Autonomous Prefetch
    gate = PredictabilityGate(min_probability=0.5)
    assert 0.25 <= gate.adaptive_threshold(context_uncertainty=0.3, cache_hit_rate=0.8) <= 0.95
    prefetcher = AnticipatoryPrefetcher(engine, gate=PredictabilityGate(min_probability=0.3))
    prefetcher.record_query_transition("t_cog", "What is Project Chronos?", "How is Project Chronos deployed?")
    prefetcher.record_query_transition("t_cog", "What is Project Chronos?", "How is Project Chronos deployed?")
    preds = prefetcher.predict_candidates_from_context("t_cog", "What is Project Chronos?")
    assert len(preds) >= 1
    auto_results = prefetcher.autonomous_prefetch("t_cog", "What is Project Chronos?")
    assert len(auto_results) >= 1

    # R5.2 Sandboxed Dreamer structural holes & contradiction detection
    dreamer = SandboxedDreamer()
    contradictions = dreamer.detect_contradictions(stored_evs, tenant_id="t_cog")
    assert len(contradictions) >= 1
    assert all(c.shadow_only and c.trust_tier == 5 and c.reality_class == "self_generated" for c in contradictions)

    holes = dreamer.discover_structural_holes(stored_evs, tenant_id="t_cog")
    assert all(h.shadow_only and h.trust_tier == 5 for h in holes)

    # R5.3 User Model confidence graduation & preference drift
    entry = UserModelEntry(
        id="um-1",
        tenant_id="t_cog",
        user_id="u1",
        kind="inferred_preference",
        statement="prefers vim for editing",
        confidence=0.55,
    )
    entry = corroborate_entry(entry, "cid-s1", session_id="s1")
    entry = corroborate_entry(entry, "cid-s2", session_id="s2")
    entry = corroborate_entry(entry, "cid-s3", session_id="s3", auto_graduate=True)
    assert entry.confidence >= 0.85
    assert effective_authority(entry) >= 3.0

    pre_drift_conf = entry.confidence
    drifts = detect_preference_drift([entry], "I switched to neovim for editing", new_evidence_cid="cid-s4")
    assert len(drifts) >= 1
    assert entry.confidence < pre_drift_conf
