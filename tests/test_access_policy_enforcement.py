from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.access_policy import AccessDecision, apply_text_redactions, merge_access_policies
from mnemosyne.consolidation import ConsolidationJob, ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Assertion, Evidence, Preference, Relation
from mnemosyne.prefetch import AnticipatoryPrefetcher, PrefetchCandidate
from mnemosyne.workspace import ShadowWorkspaceController, WorkspaceItem


TENANT = "tenant-access-policy"
USER = "user-access-policy"


def _append(
    engine: LocalMemoryEngine,
    content: str,
    *,
    sensitivity: int = 0,
    access_policy: dict[str, object] | None = None,
    trust_tier: int = 0,
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="policy-test",
            content=content,
            trust_tier=trust_tier,
            sensitivity=sensitivity,
            access_policy=access_policy or {"tenant": TENANT},
        )
    )


def test_role_ceiling_defaults_to_reader_and_agent_reads_s2() -> None:
    engine = LocalMemoryEngine()
    _append(engine, "Policy secret alpha belongs to the agent support memory.", sensitivity=2)

    default_reader = engine.retrieve("policy secret alpha", TENANT)
    agent = engine.retrieve("policy secret alpha", TENANT, filt={"role": "agent"})

    assert default_reader.hits == []
    assert [hit.text for hit in agent.hits] == ["Policy secret alpha belongs to the agent support memory."]
    assert agent.hits[0].metadata["privacy"]["effective_max_sensitivity"] == 2


def test_access_policy_purpose_role_capability_and_expiry_narrow_reads() -> None:
    engine = LocalMemoryEngine()
    _append(
        engine,
        "Purpose-bound beta support record.",
        sensitivity=2,
        access_policy={
            "tenant": TENANT,
            "allow_roles": ["agent"],
            "require_capabilities": ["pii:read"],
            "purpose": ["support"],
        },
    )
    _append(
        engine,
        "Expired gamma support record.",
        sensitivity=1,
        access_policy={
            "tenant": TENANT,
            "purpose": ["support"],
            "expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        },
    )
    _append(
        engine,
        "Residency lambda support record.",
        sensitivity=1,
        access_policy={"tenant": TENANT, "residency": "us"},
    )
    _append(
        engine,
        "Lawful-basis mu support record.",
        sensitivity=1,
        access_policy={"tenant": TENANT, "purpose": ["support"], "lawful_basis": ["consent"]},
    )
    _append(
        engine,
        "Transfer nu support record.",
        sensitivity=1,
        access_policy={
            "tenant": TENANT,
            "residency": "us",
            "allowed_residency_transfers": ["eu"],
        },
    )
    _append(
        engine,
        "No-transfer xi support record.",
        sensitivity=1,
        access_policy={
            "tenant": TENANT,
            "residency": "us",
            "allowed_residency_transfers": ["eu"],
            "cross_region_transfer": False,
        },
    )

    missing_cap = engine.retrieve("Purpose-bound beta", TENANT, filt={"role": "agent", "purpose": "support"})
    wrong_purpose = engine.retrieve(
        "Purpose-bound beta",
        TENANT,
        filt={"role": "agent", "purpose": "analytics", "capability_tags": ["pii:read"]},
    )
    wrong_role = engine.retrieve(
        "Purpose-bound beta",
        TENANT,
        filt={"role": "consolidator", "purpose": "support", "capability_tags": ["pii:read"]},
    )
    allowed = engine.retrieve(
        "Purpose-bound beta",
        TENANT,
        filt={"role": "agent", "purpose": "support", "capability_tags": ["pii:read"]},
    )
    expired = engine.retrieve("Expired gamma", TENANT, filt={"role": "agent", "purpose": "support"})
    wrong_residency = engine.retrieve("Residency lambda", TENANT, filt={"role": "agent", "residency": "eu"})
    right_residency = engine.retrieve("Residency lambda", TENANT, filt={"role": "agent", "residency": "us"})
    missing_basis = engine.retrieve("Lawful-basis mu", TENANT, filt={"role": "agent", "purpose": "support"})
    matching_basis = engine.retrieve(
        "Lawful-basis mu",
        TENANT,
        filt={"role": "agent", "purpose": "support", "lawful_basis": "consent"},
    )
    allowed_transfer = engine.retrieve("Transfer nu", TENANT, filt={"role": "agent", "runtime_residency": "eu"})
    denied_transfer = engine.retrieve("Transfer nu", TENANT, filt={"role": "agent", "runtime_residency": "apac"})
    no_transfer = engine.retrieve("No-transfer xi", TENANT, filt={"role": "agent", "runtime_residency": "eu"})

    assert missing_cap.hits == []
    assert wrong_purpose.hits == []
    assert wrong_role.hits == []
    assert [hit.text for hit in allowed.hits] == ["Purpose-bound beta support record."]
    assert expired.hits == []
    assert wrong_residency.hits == []
    assert [hit.text for hit in right_residency.hits] == ["Residency lambda support record."]
    assert missing_basis.hits == []
    assert [hit.text for hit in matching_basis.hits] == ["Lawful-basis mu support record."]
    assert [hit.text for hit in allowed_transfer.hits] == ["Transfer nu support record."]
    assert denied_transfer.hits == []
    assert no_transfer.hits == []


def test_redact_fields_masks_raw_text_below_min_role_for_raw() -> None:
    engine = LocalMemoryEngine()
    _append(
        engine,
        "Support ticket delta includes ssn: 123-45-6789 for follow-up.",
        sensitivity=2,
        access_policy={
            "tenant": TENANT,
            "redact_fields": ["ssn"],
            "min_role_for_raw": "operator",
        },
    )

    result = engine.retrieve("Support ticket delta follow-up", TENANT, filt={"role": "agent"})

    assert len(result.hits) == 1
    assert "123-45-6789" not in result.hits[0].text
    assert "[REDACTED:ssn]" in result.hits[0].text
    assert result.hits[0].metadata["privacy"]["redacted"] is True


def test_redacted_callers_do_not_rank_against_raw_stored_embedding() -> None:
    engine = LocalMemoryEngine()
    cid = _append(
        engine,
        "Support ticket vector-redaction includes ssn: 123-45-6789 for follow-up.",
        sensitivity=2,
        access_policy={
            "tenant": TENANT,
            "redact_fields": ["ssn"],
            "min_role_for_raw": "operator",
            "break_glass": True,
        },
    )
    raw_vector_only_query = "raw-vector-only-omega"
    vector = engine.adapters.embedding.embed(raw_vector_only_query)

    assert engine.set_evidence_embedding(TENANT, cid, vector) is True

    redacted_hits = engine.vector_search(
        raw_vector_only_query,
        5,
        {"tenant_id": TENANT, "branch": "main", "role": "agent"},
    )
    raw_hits = engine.vector_search(
        raw_vector_only_query,
        5,
        {"tenant_id": TENANT, "branch": "main", "role": "operator", "break_glass": True},
    )

    assert redacted_hits == []
    assert [hit.id for hit in raw_hits] == [cid]
    assert raw_hits[0].metadata["stored_embedding_used"] is True
    assert raw_hits[0].metadata["embedding_partition"] == "private"


def test_redact_fields_masks_json_and_dotted_paths_below_raw_role() -> None:
    engine = LocalMemoryEngine()
    _append(
        engine,
        json.dumps(
            {
                "ticket": "structured-json-delta",
                "profile": {"name": "Ada", "ssn": "123-45-6789"},
                "dob": "2000-01-01",
                "notes": [{"ssn": "987-65-4321"}],
            }
        ),
        sensitivity=2,
        access_policy={
            "tenant": TENANT,
            "redact_fields": ["profile.ssn", "dob"],
            "min_role_for_raw": "operator",
        },
    )

    result = engine.retrieve("structured-json-delta", TENANT, filt={"role": "agent"})

    assert len(result.hits) == 1
    assert "123-45-6789" not in result.hits[0].text
    assert "2000-01-01" not in result.hits[0].text
    assert "[REDACTED:profile.ssn]" in result.hits[0].text
    assert "[REDACTED:dob]" in result.hits[0].text
    assert result.hits[0].metadata["privacy"]["redaction_mode"] == "structured"


def test_redact_fields_missing_json_path_fails_closed() -> None:
    engine = LocalMemoryEngine()
    _append(
        engine,
        json.dumps({"ticket": "structured-json-missing", "profile": {"ssn": "123-45-6789"}}),
        sensitivity=2,
        access_policy={
            "tenant": TENANT,
            "redact_fields": ["profile.mrn"],
            "min_role_for_raw": "operator",
        },
    )

    result = engine.retrieve("profile.mrn", TENANT, filt={"role": "agent"})

    assert len(result.hits) == 1
    assert result.hits[0].text == "[REDACTED fields: profile.mrn]"
    assert "123-45-6789" not in result.hits[0].text
    assert result.hits[0].metadata["privacy"]["redaction_mode"] == "placeholder"
    assert result.hits[0].metadata["privacy"]["missing_redact_fields"] == ["profile.mrn"]


def test_assertion_structured_field_masking_hides_object() -> None:
    engine = LocalMemoryEngine()
    engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            subject="structured assertion",
            predicate="stores",
            object="MRN 12345",
            status="active",
            sensitivity=2,
            access_policy={
                "tenant": TENANT,
                "redact_fields": ["object"],
                "min_role_for_raw": "operator",
            },
        )
    )

    result = engine.retrieve("structured assertion", TENANT, filt={"role": "agent"})

    assert len(result.hits) == 1
    assert result.hits[0].text == "structured assertion stores [REDACTED:object]"
    assert "MRN 12345" not in result.hits[0].text
    assert result.hits[0].metadata["privacy"]["redaction_mode"] == "structured"


def test_relation_structured_field_masking_hides_text_and_metadata() -> None:
    engine = LocalMemoryEngine()
    cid = _append(engine, "Relation masking source evidence.")
    engine.add_relation(
        Relation(
            tenant_id=TENANT,
            source="relation masking subject",
            predicate="links_to",
            target="MRN 888 target",
            source_evidence_cids=[cid],
            access_policy={
                "tenant": TENANT,
                "redact_fields": ["target"],
                "min_role_for_raw": "operator",
            },
        )
    )

    [hit] = engine.graph_ppr(
        ["relation masking subject", "MRN 888 target"],
        1,
        tenant_id=TENANT,
        filt={"role": "agent"},
    )

    assert hit.text == "relation masking subject links_to [REDACTED:target]"
    assert hit.metadata["target"] == "[REDACTED:target]"
    assert "MRN 888" not in hit.text
    assert "MRN 888" not in hit.metadata["target"]
    assert hit.metadata["privacy"]["redaction_mode"] == "structured"


def test_required_redaction_without_fields_fails_closed() -> None:
    text, metadata = apply_text_redactions(
        "Unfielded raw sensitive value.",
        {"tenant": TENANT},
        AccessDecision(True, "allowed", "agent", 2, redacted=True),
    )

    assert text == "[REDACTED fields: unspecified]"
    assert metadata["redacted"] is True
    assert metadata["redaction_mode"] == "placeholder"
    assert metadata["missing_redact_fields"] == []


def test_denied_relation_policy_does_not_bridge_graph_traversal() -> None:
    engine = LocalMemoryEngine()
    cid = _append(engine, "Denied relation bridge source evidence.")
    engine.add_relation(
        Relation(
            tenant_id=TENANT,
            source="denied bridge alpha",
            predicate="links_to",
            target="denied bridge beta",
            source_evidence_cids=[cid],
            access_policy={"tenant": TENANT, "allow_roles": ["operator"]},
        )
    )
    engine.add_relation(
        Relation(
            tenant_id=TENANT,
            source="denied bridge beta",
            predicate="links_to",
            target="denied bridge gamma",
            source_evidence_cids=[cid],
            access_policy={"tenant": TENANT},
        )
    )

    hits = engine.graph_ppr(["denied bridge alpha"], 5, tenant_id=TENANT, filt={"role": "agent"})

    assert hits == []


def test_operator_raw_s2_requires_item_and_request_break_glass() -> None:
    engine = LocalMemoryEngine()
    _append(
        engine,
        "Operator epsilon break-glass record.",
        sensitivity=2,
        access_policy={"tenant": TENANT, "break_glass": True},
    )

    ordinary = engine.retrieve("Operator epsilon", TENANT, filt={"role": "operator"})
    break_glass = engine.retrieve("Operator epsilon", TENANT, filt={"role": "operator", "break_glass": True})

    assert ordinary.hits == []
    assert [hit.text for hit in break_glass.hits] == ["Operator epsilon break-glass record."]


def test_public_export_get_and_timeline_are_filtered_by_default() -> None:
    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    cid = _append(engine, "Filtered export public facade S2 secret.", sensitivity=2)
    engine.add_relation(
        Relation(
            tenant_id=TENANT,
            source="filtered facade subject",
            predicate="mentions",
            target="filtered facade target",
            source_evidence_cids=[cid],
            access_policy={"tenant": TENANT},
        )
    )

    reader_export = tools.export(TENANT)
    agent_export = tools.export(TENANT, role="agent")
    reader_timeline = tools.graph_timeline(TENANT, "filtered facade subject")
    agent_timeline = tools.graph_timeline(TENANT, "filtered facade subject", role="agent")

    assert reader_export["evidence"] == []
    assert reader_export["disclosure"]["omitted"]["evidence"] == 1
    assert "Filtered export public facade" not in json.dumps(reader_export)
    assert [item["content"] for item in agent_export["evidence"]] == ["Filtered export public facade S2 secret."]
    with pytest.raises(KeyError):
        tools.get(TENANT, cid)
    assert tools.get(TENANT, cid, role="agent")["record"]["content"] == "Filtered export public facade S2 secret."
    assert reader_timeline["events"] == []
    assert [event["record"]["target"] for event in agent_timeline["events"]] == ["filtered facade target"]


def test_unknown_access_policy_keys_are_rejected_at_write_time() -> None:
    engine = LocalMemoryEngine()
    policy = {"tenant": TENANT, "vendor_flag": True}

    with pytest.raises(ValueError, match="vendor_flag"):
        _append(engine, "Unknown evidence policy key.", sensitivity=1, access_policy=policy)
    with pytest.raises(ValueError, match="vendor_flag"):
        engine.upsert_assertion(
            Assertion(
                tenant_id=TENANT,
                subject="unknown policy assertion",
                predicate="has",
                object="unsupported guard",
                access_policy=policy,
            )
        )
    with pytest.raises(ValueError, match="vendor_flag"):
        engine.add_relation(
            Relation(
                tenant_id=TENANT,
                source="unknown policy source",
                predicate="links_to",
                target="unknown policy target",
                access_policy=policy,
            )
        )
    with pytest.raises(ValueError, match="vendor_flag"):
        engine.add_preference(
            Preference(
                tenant_id=TENANT,
                user_id=USER,
                category="workflow",
                statement="unknown policy preference",
                access_policy=policy,
            )
        )
    with pytest.raises(ValueError, match="vendor_flag"):
        engine.register_entity(TENANT, "Unknown Policy Entity", access_policy=policy)


def test_metadata_shadow_access_policy_is_rejected() -> None:
    engine = LocalMemoryEngine()
    cid = _append(engine, "Metadata shadow policy should not be accepted.")

    with pytest.raises(ValueError, match="cannot shadow"):
        engine.update_evidence_metadata(cid=cid, tenant_id=TENANT, metadata_patch={"access_policy": {"tenant": TENANT}})


def test_assertion_reinforcement_merges_access_policy_restrictively() -> None:
    engine = LocalMemoryEngine()
    first_id = engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            subject="policy reinforcement",
            predicate="has",
            object="same object",
            access_policy={"tenant": TENANT},
        )
    )
    second_id = engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            subject="policy reinforcement",
            predicate="has",
            object="same object",
            confidence=0.95,
            access_policy={"tenant": TENANT, "allow_roles": ["consolidator"]},
        )
    )
    [stored] = list(engine.assertions.values())

    assert second_id == first_id
    assert stored.access_policy == {"tenant": TENANT, "allow_roles": ["consolidator"]}


def test_entity_rewrite_validates_existing_legacy_access_policy() -> None:
    engine = LocalMemoryEngine()
    row = engine.register_entity(TENANT, "Legacy Policy Entity", access_policy={"tenant": TENANT})
    engine.entities[(TENANT, "Legacy Policy Entity")]["access_policy"] = {"tenant": TENANT, "vendor_flag": True}

    with pytest.raises(ValueError, match="vendor_flag"):
        engine.register_entity(TENANT, row["canonical"], alias="legacy policy alias")


def test_derived_access_policy_merge_rejects_unknown_source_keys() -> None:
    with pytest.raises(ValueError, match="vendor_flag"):
        merge_access_policies([{"tenant": TENANT, "vendor_flag": True}], tenant_id=TENANT)


def test_workspace_metadata_access_policy_rejects_unknown_keys() -> None:
    controller = ShadowWorkspaceController(max_workspace_items=1, max_cycles=1)

    with pytest.raises(ValueError, match="vendor_flag"):
        controller.run_shadow_stream(
            tenant_id=TENANT,
            item_ticks=[
                [
                    WorkspaceItem(
                        id="unknown-policy",
                        priority=1.0,
                        content="unknown workspace policy",
                        metadata={"access_policy": {"tenant": TENANT, "vendor_flag": True}},
                    )
                ]
            ],
        )


def test_consolidation_candidate_unknown_access_policy_fails_closed() -> None:
    engine = LocalMemoryEngine()
    result = ConsolidationWorker(engine, []).run_job(
        ConsolidationJob(
            tenant_id=TENANT,
            signature="unknown-policy-candidate",
            query="unknown policy candidate",
            candidate_subject="unknown policy candidate",
            candidate_predicate="has",
            candidate_object="unsupported guard",
            source_evidence_cids=[],
            access_policy={"tenant": TENANT, "vendor_flag": True},
        )
    )

    assert result.promoted is False
    assert result.failed_cases == ["unknown consolidation access_policy keys: vendor_flag"]
    assert engine.assertions == {}


def test_s4_and_legacy_unknown_access_policy_keys_fail_closed() -> None:
    engine = LocalMemoryEngine()
    _append(engine, "S4 zeta secret pointer.", sensitivity=4, access_policy={"tenant": TENANT, "break_glass": True})
    legacy_cid = _append(engine, "Unknown eta policy key.", sensitivity=1, access_policy={"tenant": TENANT})
    legacy = next(item for item in engine.evidence.values() if item.cid == legacy_cid)
    legacy.access_policy = {"tenant": TENANT, "vendor_flag": True}

    s4 = engine.retrieve("S4 zeta", TENANT, filt={"role": "operator", "break_glass": True})
    unknown = engine.retrieve("Unknown eta", TENANT, filt={"role": "agent"})

    assert s4.hits == []
    assert unknown.hits == []


def test_prefetch_uses_same_access_context_as_retrieval() -> None:
    engine = LocalMemoryEngine()
    _append(engine, "Prefetch theta sensitive support context.", sensitivity=2)
    prefetcher = AnticipatoryPrefetcher(engine)

    [result] = prefetcher.prefetch(
        TENANT,
        [PrefetchCandidate("Prefetch theta sensitive", 0.95, "likely next query")],
        access_context={"role": "reader"},
    )
    warmed = prefetcher.get_warmed(TENANT, "Prefetch theta sensitive")

    assert result.executed is True
    assert warmed is not None
    assert warmed.hits == []


def test_derived_access_policy_merge_is_most_restrictive() -> None:
    merged = merge_access_policies(
        [
            {
                "tenant": TENANT,
                "allow_roles": ["agent", "consolidator"],
                "require_capabilities": ["pii:read"],
                "purpose": ["support", "analytics"],
                "redact_fields": ["ssn"],
                "min_role_for_raw": "agent",
                "expires_at": "2026-12-31T00:00:00Z",
                "break_glass": True,
            },
            {
                "tenant": TENANT,
                "allow_roles": ["consolidator"],
                "require_capabilities": ["phi:read"],
                "purpose": ["support"],
                "redact_fields": ["dob"],
                "min_role_for_raw": "operator",
                "expires_at": "2026-01-01T00:00:00Z",
            },
        ],
        tenant_id=TENANT,
    )

    assert merged["allow_roles"] == ["consolidator"]
    assert merged["require_capabilities"] == ["phi:read", "pii:read"]
    assert merged["purpose"] == ["support"]
    assert merged["redact_fields"] == ["dob", "ssn"]
    assert merged["min_role_for_raw"] == "operator"
    assert merged["expires_at"] == "2026-01-01T00:00:00Z"
    assert "break_glass" not in merged
