"""Broadened local<->Postgres cross-engine portability suite (G8 / NFR portability).

Blueprint refs: G8 (engine portability), NFR portability, FR-2/3/8/10.

WHAT THIS ADDS BEYOND ``tests/test_shared_engine_contract.py``
--------------------------------------------------------------
The existing shared contract is *parametrized*: each test runs against ONE engine
(``params=["local", "postgres"]``) and proves each engine independently satisfies the
contract. It never instantiates both engines in the same test, so it cannot prove that
the two backends produce the *same observable result* for the same inputs.

This suite is *cross-engine*: every case builds BOTH a ``LocalMemoryEngine`` and (when
``MNEMOSYNE_POSTGRES_DSN`` is set) a ``PostgresEngine`` with the SAME string tenant/user
IDs, runs the SAME operations, and asserts their normalized observable outputs are
identical. The local half always runs now; the Postgres half is gated on the DSN env var
(documented in this directory's README.md).

Coverage target: the 26 public methods common to both engines. Each method below has at
least one cross-engine parity case. Methods already deeply covered by the parametrized
suite are still re-exercised here in *cross-engine* mode, which is the new guarantee.

SECURITY: every content string here is inert test data constructed as a literal. No file,
corpus, or command output is read or executed by this suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mnemosyne.models import (
    Assertion,
    Contradiction,
    Evidence,
    Justification,
    Preference,
    Relation,
)
from mnemosyne.calibration import CalibrationSet

from _portability import ParityHarness, normalize


# --------------------------------------------------------------------------- helpers


def _evidence(tenant: str, user: str, content: str, **kw: Any) -> Evidence:
    base = dict(
        tenant_id=tenant,
        user_id=user,
        actor="user",
        source_type="chat",
        content=content,
        trust_tier=0,
        access_policy={"tenant": tenant},
    )
    base.update(kw)
    return Evidence(**base)


def _harness(name: str) -> ParityHarness:
    # Fixed (non-random) tenant/user ids so local and postgres receive identical inputs.
    return ParityHarness(tenant=f"tenant-port-{name}", user=f"user-port-{name}")


# --------------------------------------------------------------------- evidence CRUD


def test_parity_append_get_and_export_evidence() -> None:
    harness = _harness("evidence-crud")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(
            _evidence(tenant, user, "Portability evidence about the amber lantern.")
        )
        recalled = engine.get_evidence(tenant, cid)
        exported = next(
            item for item in engine.export_tenant(tenant)["evidence"] if item["cid"] == cid
        )
        return {"cid": cid, "recalled": recalled.to_dict(), "exported": exported}

    local = harness.run("append+get+export evidence", scenario)
    assert local["cid"]
    assert local["recalled"]["content"] == "Portability evidence about the amber lantern."
    assert local["exported"]["cid"] == local["cid"]


def test_parity_set_evidence_embedding() -> None:
    from mnemosyne.text import hashing_embedding

    harness = _harness("embedding")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(
            _evidence(
                tenant,
                user,
                "",
                actor="tool",
                source_type="embedding-contract",
                content_pointer="objects/port/embedding.txt",
                trust_tier=1,
            )
        )
        dims = int(
            getattr(getattr(getattr(engine, "adapters", None), "embedding", None), "dims", 256)
        )
        vector = hashing_embedding("portability embedding contract", dims=dims)
        updated = engine.set_evidence_embedding(tenant, cid, vector)
        recalled = engine.get_evidence(tenant, cid)
        return {
            "updated": updated,
            "embedding_len": len(recalled.embedding) if recalled.embedding else None,
            "embedding": [round(v, 6) for v in (recalled.embedding or [])],
        }

    local = harness.run("set_evidence_embedding", scenario)
    assert local["updated"] is True
    assert local["embedding_len"]


def test_parity_update_evidence_metadata() -> None:
    harness = _harness("metadata")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(
            _evidence(
                tenant,
                user,
                "Portability metadata update target.",
                source_type="metadata-contract",
                metadata={"existing": "kept"},
            )
        )
        updated = engine.update_evidence_metadata(
            tenant,
            cid,
            {"lifecycle": {"tier": "abstractive_gist", "must_keep": True, "successful_rehearsals": 2}},
        )
        recalled = engine.get_evidence(tenant, cid)
        audit = [
            row
            for row in engine.export_tenant(tenant)["audit_log"]
            if row["op"] == "update_evidence_metadata"
        ]
        return {
            "updated": updated,
            "metadata": recalled.metadata,
            "audit_source": audit[-1]["source"] if audit else None,
            "audit_diff": audit[-1]["diff"] if audit else None,
        }

    local = harness.run("update_evidence_metadata", scenario)
    assert local["updated"] is True
    assert local["metadata"]["existing"] == "kept"
    assert local["metadata"]["lifecycle"]["tier"] == "abstractive_gist"


# --------------------------------------------------------------- assertions / TMS


def test_parity_upsert_assertion_and_export() -> None:
    harness = _harness("assertion")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(_evidence(tenant, user, "Portability assertion backing evidence."))
        assertion_id = engine.upsert_assertion(
            Assertion(
                tenant_id=tenant,
                user_id=user,
                subject="lantern",
                predicate="emits",
                object="amber light",
                confidence=0.95,
                source_evidence_cids=[cid],
                trust_tier=0,
                access_policy={"tenant": tenant},
            )
        )
        row = next(
            item for item in engine.export_tenant(tenant)["assertions"] if item["id"] == assertion_id
        )
        return {"assertion": row}

    local = harness.run("upsert_assertion", scenario)
    assert local["assertion"]["subject"] == "lantern"
    assert local["assertion"]["object"] == "amber light"
    assert local["assertion"]["status"] == "active"


def test_parity_add_justification_and_contradiction() -> None:
    harness = _harness("tms")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(_evidence(tenant, user, "Portability TMS support evidence."))
        first = engine.upsert_assertion(
            Assertion(
                tenant_id=tenant,
                user_id=user,
                subject="conflict",
                predicate="has_answer",
                object="alpha",
                confidence=0.7,
                source_evidence_cids=[cid],
                access_policy={"tenant": tenant},
            )
        )
        second = engine.upsert_assertion(
            Assertion(
                tenant_id=tenant,
                user_id=user,
                subject="conflict",
                predicate="has_answer",
                object="beta",
                confidence=0.6,
                source_evidence_cids=[cid],
                access_policy={"tenant": tenant},
            )
        )
        engine.add_justification(
            Justification(
                tenant_id=tenant,
                assertion_id=first,
                evidence_cids=[cid],
                dependency_ids=[second],
                rule="portability-support-rule",
                kind="support",
                label={"contract": "portability"},
                hypothesis_prob=0.7,
            )
        )
        engine.add_contradiction(Contradiction(tenant_id=tenant, a=first, b=second))
        # Idempotency: reversed pair must collapse to the same contradiction.
        engine.add_contradiction(Contradiction(tenant_id=tenant, a=second, b=first))
        exported = engine.export_tenant(tenant)
        return {
            "justifications": exported["justifications"],
            "contradictions": exported["contradictions"],
        }

    local = harness.run("add_justification+add_contradiction", scenario)
    assert len(local["justifications"]) == 1
    assert local["justifications"][0]["rule"] == "portability-support-rule"
    assert len(local["contradictions"]) == 1  # reversed duplicate collapsed
    assert local["contradictions"][0]["status"] == "open"


def test_parity_bitemporal_as_of() -> None:
    harness = _harness("as-of")
    anchor = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid_a = engine.append_evidence(_evidence(tenant, user, "Bitemporal alpha source."))
        cid_b = engine.append_evidence(_evidence(tenant, user, "Bitemporal beta source."))
        engine.upsert_assertion(
            Assertion(
                tenant_id=tenant,
                user_id=user,
                subject="weather",
                predicate="is",
                object="alpha",
                confidence=0.9,
                valid_from=anchor,
                source_evidence_cids=[cid_a],
                status="active",
                access_policy={"tenant": tenant},
            )
        )
        engine.upsert_assertion(
            Assertion(
                tenant_id=tenant,
                user_id=user,
                subject="weather",
                predicate="is",
                object="beta",
                confidence=0.92,
                valid_from=anchor + timedelta(minutes=5),
                source_evidence_cids=[cid_b],
                status="active",
                access_policy={"tenant": tenant},
            )
        )
        past = engine.as_of("weather", "is", anchor + timedelta(minutes=1), tenant_id=tenant)
        current = engine.as_of("weather", "is", anchor + timedelta(minutes=10), tenant_id=tenant)
        return {
            "past": sorted(a.object for a in past),
            "current": sorted(a.object for a in current),
        }

    local = harness.run("as_of", scenario)
    assert local["past"] == ["alpha"]
    assert local["current"] == ["beta"]


# ------------------------------------------------------------- relations / graph


def test_parity_add_relation_and_graph_ppr() -> None:
    harness = _harness("relation")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(_evidence(tenant, user, "Portability relation backing evidence."))
        rel_id = engine.add_relation(
            Relation(
                tenant_id=tenant,
                source="beacon seed",
                predicate="points_to",
                target="beacon target",
                source_evidence_cids=[cid],
                access_policy={"tenant": tenant},
            )
        )
        graph = engine.graph_ppr(["beacon seed"], 5, tenant_id=tenant, branch="main")
        return {
            "relation_in_graph": rel_id in {hit.id for hit in graph},
            "graph_targets": sorted(hit.metadata.get("target") for hit in graph if hit.metadata.get("target")),
            "tenants": sorted({hit.tenant_id for hit in graph}),
            "branches": sorted({hit.branch for hit in graph}),
        }

    local = harness.run("add_relation+graph_ppr", scenario)
    assert local["relation_in_graph"] is True
    assert "beacon target" in local["graph_targets"]
    assert local["tenants"] == [harness.tenant]


def test_parity_graph_ppr_skips_expired_relations() -> None:
    harness = _harness("relation-temporal")
    now = datetime(2026, 6, 10, tzinfo=UTC)

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        seed = "temporal seed"
        engine.add_relation(
            Relation(
                tenant_id=tenant,
                source=seed,
                predicate="expired_edge",
                target="expired target",
                valid_from=now - timedelta(days=3),
                valid_to=now - timedelta(days=2),
                access_policy={"tenant": tenant},
            )
        )
        engine.add_relation(
            Relation(
                tenant_id=tenant,
                source=seed,
                predicate="active_edge",
                target="active target",
                valid_from=now - timedelta(days=1),
                access_policy={"tenant": tenant},
            )
        )
        current = engine.graph_ppr([seed], 10, tenant_id=tenant, branch="main")
        historical = engine.graph_ppr(
            [seed], 10, as_of=now - timedelta(days=2, hours=-1), tenant_id=tenant, branch="main"
        )
        return {
            "current_predicates": sorted(
                hit.metadata.get("predicate") for hit in current if hit.metadata.get("predicate")
            ),
            "historical_predicates": sorted(
                hit.metadata.get("predicate") for hit in historical if hit.metadata.get("predicate")
            ),
        }

    local = harness.run("graph_ppr temporal", scenario)
    assert "active_edge" in local["current_predicates"]
    assert "expired_edge" not in local["current_predicates"]


# ------------------------------------------------------------ direct primitives


def test_parity_lexical_and_vector_search() -> None:
    harness = _harness("primitives")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(
            _evidence(tenant, user, "Portability primitive search stores the garnet needle phrase.")
        )
        engine.upsert_assertion(
            Assertion(
                tenant_id=tenant,
                user_id=user,
                subject="primitive",
                predicate="finds",
                object="garnet needle",
                confidence=0.92,
                source_evidence_cids=[cid],
                access_policy={"tenant": tenant},
            )
        )
        filt = {"tenant_id": tenant, "branch": "main", "max_trust_tier": 3, "max_sensitivity": 2}
        lexical = engine.lexical_search("garnet needle", 10, filt)
        dense = engine.vector_search("garnet needle", 10, filt)
        return {
            "cid_in_lexical": cid in {hit.id for hit in lexical},
            "cid_in_dense": cid in {hit.id for hit in dense},
            "lexical_tenants": sorted({hit.tenant_id for hit in lexical}),
            "dense_tenants": sorted({hit.tenant_id for hit in dense}),
            "lexical_kinds": sorted({hit.kind for hit in lexical}),
        }

    local = harness.run("lexical_search+vector_search", scenario)
    assert local["cid_in_lexical"] is True
    assert local["cid_in_dense"] is True
    assert local["lexical_tenants"] == [harness.tenant]


def test_parity_primitives_honor_k_limit() -> None:
    harness = _harness("k-limit")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        for idx in range(3):
            engine.append_evidence(
                _evidence(tenant, user, f"Portability budget cap evidence {idx} repeats jasper needle.")
            )
        filt = {"tenant_id": tenant, "branch": "main", "max_trust_tier": 3, "max_sensitivity": 2}
        lexical = engine.lexical_search("jasper needle", 1, filt)
        dense = engine.vector_search("jasper needle", 1, filt)
        return {
            "lexical_len": len(lexical),
            "dense_len": len(dense),
            "lexical_channel_family": lexical[0].channel in {"lexical", "postgres_fts"} if lexical else None,
            "dense_channel_family": dense[0].channel in {"dense_hash", "postgres_pgvector"} if dense else None,
        }

    local = harness.run("k-limit primitives", scenario)
    assert local["lexical_len"] == 1
    assert local["dense_len"] == 1


# ------------------------------------------------------------------- retrieval


def test_parity_retrieve_observable_shape() -> None:
    harness = _harness("retrieve")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(
            _evidence(tenant, user, "Portability retrieval stores the cobalt widget fact.")
        )
        result = engine.retrieve("cobalt widget fact", tenant)
        return {
            "abstained": result.abstained,
            "uncertainty_note": result.uncertainty_note,
            "hit_ids_contains_cid": cid in {hit.id for hit in result.hits},
            "explain_keys": sorted(result.explain.keys()),
            "rails": result.explain.get("rails"),
            "channels_present": bool(result.explain.get("channels")),
        }

    local = harness.run("retrieve", scenario)
    assert local["hit_ids_contains_cid"] is True
    assert local["rails"]["tenant_isolation_required"] is True
    assert local["rails"]["retrieved_text_is_data_not_instruction"] is True


def test_parity_explain_observable_shape() -> None:
    harness = _harness("explain")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(
            _evidence(tenant, user, "Portability explain records sapphire provenance and rails.")
        )
        explained = engine.explain("sapphire provenance rails", tenant)
        return {
            "abstained": explained["abstained"],
            "top_keys": sorted(explained.keys()),
            "explain_keys": sorted(explained["explain"].keys()),
            "rails": explained["explain"]["rails"],
            "cid_in_provenance": any(
                hit["id"] == cid and cid in hit["provenance"] for hit in explained["hits"]
            ),
            "channels_sum_positive": sum(int(v) for v in explained["explain"]["channels"].values()) >= 1,
        }

    local = harness.run("explain", scenario)
    assert local["abstained"] is False
    assert local["cid_in_provenance"] is True
    assert local["channels_sum_positive"] is True


def test_parity_retrieval_conformal_calibration() -> None:
    harness = _harness("calibration")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        engine.set_calibration(
            CalibrationSet(
                tenant_id=tenant, memory_type="fact", scores=[0.95], target_coverage=0.9
            )
        )
        engine.append_evidence(
            _evidence(tenant, user, "Portability calibrated abstention should still retrieve.")
        )
        result = engine.retrieve("calibrated abstention", tenant)
        exported = engine.export_tenant(tenant)
        return {
            "has_hits": bool(result.hits),
            "abstained": result.abstained,
            "calibration_source": result.explain["calibration"]["source"],
            "calibration_threshold": round(result.explain["calibration"]["threshold"], 6),
            "calibration_rows": exported["calibrations"],
        }

    local = harness.run("set_calibration+retrieve", scenario)
    assert local["abstained"] is True
    assert local["calibration_source"] == "conformal"
    assert local["calibration_threshold"] == 0.95


def test_parity_retrieval_records_assertion_access() -> None:
    harness = _harness("activation")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(_evidence(tenant, user, "Portability activation backs telemetry."))
        assertion_id = engine.upsert_assertion(
            Assertion(
                tenant_id=tenant,
                user_id=user,
                subject="activation",
                predicate="requires",
                object="read telemetry",
                confidence=0.95,
                source_evidence_cids=[cid],
                access_policy={"tenant": tenant},
            )
        )

        def access_count() -> int:
            row = next(
                item
                for item in engine.export_tenant(tenant)["assertions"]
                if item["id"] == assertion_id
            )
            return row["access_count"]

        before = access_count()
        result = engine.retrieve("activation requires read telemetry", tenant)
        after = access_count()
        return {
            "before": before,
            "after": after,
            "activation_applied": result.explain["activation"]["applied"],
            "read_marks_assertions_positive": result.explain["read_marks"]["assertions"] >= 1,
        }

    local = harness.run("retrieve activation/read-marks", scenario)
    assert local["before"] == 0
    assert local["after"] == 1
    assert local["activation_applied"] is True


# ------------------------------------------------------------------ deep_search


def test_parity_deep_search_tenant_and_branch() -> None:
    harness = _harness("deep-search")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(
            _evidence(tenant, user, "Portability deep search anchor about the deep graph.")
        )
        engine.add_relation(
            Relation(
                tenant_id=tenant,
                source="deep graph",
                predicate="links",
                target="deep target",
                source_evidence_cids=[cid],
                access_policy={"tenant": tenant},
            )
        )
        result = engine.deep_search("deep graph", tenant)
        return {
            "has_hits": bool(result.hits),
            "all_tenant_scoped": all(hit.tenant_id == tenant for hit in result.hits),
            "all_branch_main": all(hit.branch == "main" for hit in result.hits),
            "kinds": sorted({hit.kind for hit in result.hits}),
        }

    local = harness.run("deep_search", scenario)
    assert local["has_hits"] is True
    assert local["all_tenant_scoped"] is True
    assert local["all_branch_main"] is True


# ------------------------------------------------- preferences / correction


def test_parity_add_preference() -> None:
    harness = _harness("preference")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(_evidence(tenant, user, "Portability preference backing evidence."))
        engine.add_preference(
            Preference(
                tenant_id=tenant,
                user_id=user,
                category="ui",
                statement="prefers dark mode",
                scope={"area": "theme"},
                confidence=0.8,
                explicit=True,
                exceptions=[],
                source_evidence_cids=[cid],
            )
        )
        exported = engine.export_tenant(tenant)
        return {"preferences": exported["preferences"]}

    local = harness.run("add_preference", scenario)
    assert len(local["preferences"]) == 1
    pref = local["preferences"][0]
    assert pref["category"] == "ui"
    assert pref["statement"] == "prefers dark mode"
    assert pref["explicit"] is True


def test_parity_correct_adds_assertion() -> None:
    harness = _harness("correct")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        engine.append_evidence(_evidence(tenant, user, "Portability correction seed evidence."))
        assertion_id = engine.correct(
            tenant, user, "theme", "prefers", "dark", "Actually I prefer light mode now."
        )
        row = next(
            item for item in engine.export_tenant(tenant)["assertions"] if item["id"] == assertion_id
        )
        return {"assertion": row}

    local = harness.run("correct", scenario)
    assert local["assertion"]["subject"] == "theme"
    assert local["assertion"]["predicate"] == "prefers"
    assert local["assertion"]["source_evidence_cids"]


# ------------------------------------------------------------ entity registry


def test_parity_register_entity() -> None:
    harness = _harness("entity")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(_evidence(tenant, user, "Portability entity registry evidence."))
        entity = engine.register_entity(
            tenant,
            "portability-entity",
            alias="Portability Entity",
            summary="Portability Entity has durable registry state.",
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
        exported = engine.export_tenant(tenant)["entities"]
        return {"entity": entity, "exported": exported}

    local = harness.run("register_entity", scenario)
    assert local["entity"]["canonical"] == "portability-entity"
    assert "Portability Entity" in local["entity"]["aliases"]
    assert local["exported"][0]["canonical"] == "portability-entity"


# ---------------------------------------------------------- branch lifecycle


def test_parity_branch_append_get_and_discard() -> None:
    harness = _harness("branch")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        engine.branch("candidate", frm="main", tenant_id=tenant)
        cid = engine.append_evidence(
            _evidence(tenant, user, "Candidate branch portability fact."), branch="candidate"
        )
        on_candidate = engine.get_evidence(tenant, cid, branch="candidate") is not None
        on_main = engine.get_evidence(tenant, cid, branch="main") is None
        engine.discard("candidate", tenant_id=tenant)
        gone = engine.get_evidence(tenant, cid, branch="candidate") is None
        return {"on_candidate": on_candidate, "isolated_from_main": on_main, "discarded": gone}

    local = harness.run("branch+discard", scenario)
    assert local["on_candidate"] is True
    assert local["isolated_from_main"] is True
    assert local["discarded"] is True


def test_parity_merge_branch_into_main() -> None:
    harness = _harness("merge")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        engine.branch("cand", frm="main", tenant_id=tenant)
        cid = engine.append_evidence(
            _evidence(tenant, user, "Branch merge evidence about the topaz beacon."), branch="cand"
        )
        engine.upsert_assertion(
            Assertion(
                tenant_id=tenant,
                user_id=user,
                branch="cand",
                subject="beacon",
                predicate="is",
                object="topaz",
                confidence=0.9,
                source_evidence_cids=[cid],
                access_policy={"tenant": tenant},
                status="active",
            ),
            branch="cand",
        )
        engine.add_relation(
            Relation(
                tenant_id=tenant,
                branch="cand",
                source="beacon",
                predicate="emits",
                target="topaz glow",
                source_evidence_cids=[cid],
                access_policy={"tenant": tenant},
            ),
            branch="cand",
        )
        report = engine.merge("cand", into="main", tenant_id=tenant)
        merged_on_main = engine.get_evidence(tenant, cid, branch="main") is not None
        return {
            "evidence_added": report.evidence_added,
            "assertions_added": report.assertions_added,
            "relations_added": report.relations_added,
            "conflicts": report.conflicts,
            "from_branch": report.from_branch,
            "into_branch": report.into_branch,
            "merged_on_main": merged_on_main,
        }

    local = harness.run("merge", scenario)
    assert local["evidence_added"] == 1
    assert local["assertions_added"] == 1
    assert local["relations_added"] == 1
    assert local["conflicts"] == []
    assert local["merged_on_main"] is True


# ---------------------------------------------------------------- erasure


def test_parity_forget_evidence() -> None:
    harness = _harness("forget")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(_evidence(tenant, user, "Portability forget target evidence."))
        result = engine.forget(tenant, cid)
        still_present = engine.get_evidence(tenant, cid) is not None
        in_export = any(
            item["cid"] == cid for item in engine.export_tenant(tenant)["evidence"]
        )
        return {
            "erased": result["erased"],
            "still_present": still_present,
            "in_export": in_export,
        }

    local = harness.run("forget", scenario)
    assert local["erased"] is True
    assert local["still_present"] is False
    assert local["in_export"] is False


# ------------------------------------------------------- whole-store export


def test_parity_export_all_and_to_json() -> None:
    import json

    harness = _harness("export-all")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(_evidence(tenant, user, "Portability export-all evidence."))
        engine.set_calibration(
            CalibrationSet(tenant_id=tenant, memory_type="fact", scores=[0.91], target_coverage=0.9)
        )
        engine.register_entity(
            tenant,
            "export-all-entity",
            alias="Export All Entity",
            summary="Export-all includes entity registry rows.",
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
        exported = engine.export_all()
        parsed = json.loads(engine.to_json())
        return {
            "export_keys": sorted(exported.keys()),
            "json_keys": sorted(parsed.keys()),
            "policy_top_k": exported["policy"]["top_k"],
            "json_policy_top_k": parsed["policy"]["top_k"],
            "evidence_has_cid": any(item["cid"] == cid for item in exported["evidence"]),
            "json_evidence_has_cid": any(item["cid"] == cid for item in parsed["evidence"]),
        }

    local = harness.run("export_all+to_json", scenario)
    expected = {
        "policy",
        "branches",
        "evidence",
        "assertions",
        "relations",
        "preferences",
        "justifications",
        "contradictions",
        "calibrations",
        "entities",
        "audit_log",
        "deletion_log",
        "merge_log",
        "tenants",
    }
    assert expected <= set(local["export_keys"])
    assert expected <= set(local["json_keys"])
    assert local["policy_top_k"] == local["json_policy_top_k"]
    assert local["evidence_has_cid"] is True


# ------------------------------------------------------- DSN gate visibility


def test_postgres_half_runs_when_dsn_present() -> None:
    """Make the DSN gate observable: skip (don't silently pass) when Postgres is off.

    This does not assert parity itself; it documents/encodes that the Postgres half of
    every other test in this module is gated on ``MNEMOSYNE_POSTGRES_DSN``. When the DSN
    is set this test exercises a real round-trip against the live backend so operators get
    a clear signal that the cross-engine half actually ran.
    """

    harness = _harness("dsn-gate")
    if not harness.dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set; Postgres parity half is gated off")

    def scenario(engine: Any, tenant: str, user: str) -> dict[str, Any]:
        cid = engine.append_evidence(_evidence(tenant, user, "DSN gate round-trip evidence."))
        recalled = engine.get_evidence(tenant, cid)
        return {"cid": cid, "content": recalled.content}

    local = harness.run("dsn-gate round-trip", scenario)
    assert local["content"] == "DSN gate round-trip evidence."
    assert harness.postgres_ran is True
