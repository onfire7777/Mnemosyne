from __future__ import annotations

from mnemosyne.dreamer import SandboxedDreamer
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.providers import ProviderRegistry, SpecialistBudget, SpecialistModuleSpec
from mnemosyne.workspace import ShadowWorkspaceController, WorkspaceItem


def test_sandboxed_dreamer_generates_low_trust_candidates_without_mutating_engine() -> None:
    engine = LocalMemoryEngine()
    tenant = "tenant-dreamer"
    user = "user-dreamer"
    first = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="operator-evidence",
            content="Alpha planning evidence links consolidation priorities to durable recall.",
            access_policy={"tenant": tenant},
        )
    )
    second = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="operator-evidence",
            content="Omega runtime evidence links workspace focus to calibrated retrieval.",
            access_policy={"tenant": tenant},
        )
    )
    before = engine.export_tenant(tenant)

    report = SandboxedDreamer(max_candidates=2).dream(
        [engine.get_evidence(tenant, first), engine.get_evidence(tenant, second)],
        tenant_id=tenant,
    )
    after = engine.export_tenant(tenant)

    assert before == after
    assert report.shadow_only is True
    assert report.production_mutation is False
    assert report.critical_path is False
    assert report.promotion_gate_required is True
    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.reality_class == "self_generated"
    assert candidate.trust_tier == 5
    assert candidate.shadow_only is True
    assert candidate.promotion_required is True
    assert candidate.critical_path is False
    assert candidate.source_evidence_cids == (first, second)
    assert candidate.id.startswith("dream:")


def test_sandboxed_dreamer_requires_multiple_cid_backed_sources() -> None:
    report = SandboxedDreamer().dream(
        [
            {
                "cid": "cidv1:abc",
                "tenant_id": "tenant-dreamer",
                "access_policy": {"tenant": "tenant-dreamer"},
                "content": "single source evidence",
            }
        ],
        tenant_id="tenant-dreamer",
    )

    assert report.candidates == ()
    assert report.source_count == 1


def test_sandboxed_dreamer_rejects_cross_tenant_mapped_sources() -> None:
    report = SandboxedDreamer().dream(
        [
            {
                "cid": "cidv1:wrong-a",
                "tenant_id": "other-tenant",
                "access_policy": {"tenant": "other-tenant"},
                "content": "Wrong tenant replay source should not count.",
            },
            {
                "cid": "cidv1:wrong-b",
                "tenant_id": "other-tenant",
                "access_policy": {"tenant": "other-tenant"},
                "content": "Wrong tenant corroboration should not count.",
            },
        ],
        tenant_id="tenant-dreamer",
    )

    assert report.candidates == ()
    assert report.source_count == 0


def test_sandboxed_dreamer_rejects_forged_mapping_access_policy() -> None:
    report = SandboxedDreamer().dream(
        [
            {
                "cid": "cidv1:forged-a",
                "tenant_id": "tenant-dreamer",
                "access_policy": {"tenant": "other-tenant"},
                "content": "Forged tenant id must not bypass access policy.",
            },
            {
                "cid": "cidv1:forged-b",
                "tenant_id": "tenant-dreamer",
                "content": "Missing access policy must not count as retained custody.",
            },
        ],
        tenant_id="tenant-dreamer",
    )

    assert report.candidates == ()
    assert report.source_count == 0


def test_sandboxed_dreamer_rejects_evidence_without_explicit_access_policy() -> None:
    report = SandboxedDreamer().dream(
        [
            Evidence(
                tenant_id="tenant-dreamer",
                user_id="user-dreamer",
                actor="user",
                source_type="operator-evidence",
                content="Missing policy source A should not count.",
                cid="cidv1:missing-policy-a",
            ),
            Evidence(
                tenant_id="tenant-dreamer",
                user_id="user-dreamer",
                actor="user",
                source_type="operator-evidence",
                content="Missing policy source B should not count.",
                cid="cidv1:missing-policy-b",
            ),
        ],
        tenant_id="tenant-dreamer",
    )

    assert report.candidates == ()
    assert report.source_count == 0


def test_shadow_workspace_controller_recruits_dreamer_off_critical_path() -> None:
    report = ShadowWorkspaceController(max_workspace_items=1).run_shadow_cycle(
        tenant_id="tenant-workspace",
        items=[
            WorkspaceItem(id="low", priority=0.1, content="low priority"),
            WorkspaceItem(id="high", priority=0.9, content="high priority"),
        ],
        evidence=[
            {
                "cid": "cid-workspace-a",
                "tenant_id": "tenant-workspace",
                "access_policy": {"tenant": "tenant-workspace"},
                "content": "First retained source supports replay.",
            },
            {
                "cid": "cid-workspace-b",
                "tenant_id": "tenant-workspace",
                "access_policy": {"tenant": "tenant-workspace"},
                "content": "Second retained source supports gating.",
            },
        ],
    )
    payload = report.to_dict()
    invocation = payload["specialist_invocations"][0]
    output = invocation["output_summary"]

    assert payload["shadow_only"] is True
    assert payload["critical_path"] is False
    assert payload["production_mutation"] is False
    assert payload["selected_items"][0]["id"] == "high"
    assert invocation["name"] == "dreamer.shadow"
    assert invocation["role"] == "dreamer"
    assert invocation["shadow_only"] is True
    assert invocation["critical_path"] is False
    assert invocation["critical_path_allowed"] is False
    assert output["answer_authority"] is False
    assert output["answer_authority_allowed"] is False
    assert output["candidate_count"] == 1
    assert output["production_mutation"] is False
    assert output["promotion_gate_required"] is True
    assert output["candidate_reality_classes"] == ["self_generated"]
    assert output["candidate_trust_tiers"] == [5]
    promotion = output["promotion_evidence"]
    assert promotion["schema_version"] == "specialist-promotion-evidence.v1"
    assert promotion["specialist_name"] == "dreamer.shadow"
    assert promotion["specialist_role"] == "dreamer"
    assert promotion["shadow_only"] is True
    assert promotion["answer_authority"] is False
    assert promotion["answer_authority_allowed"] is False
    assert promotion["critical_path"] is False
    assert promotion["critical_path_allowed"] is False
    assert promotion["production_mutation"] is False
    assert promotion["promotion_gate_required"] is True
    assert promotion["promoted"] is False
    assert promotion["gate_result"] is None
    assert promotion["gate_result_present"] is False
    assert promotion["candidate_count"] == 1
    assert promotion["cid_backed_candidate_count"] == 1
    assert promotion["candidates"][0]["source_evidence_ref_count"] == 2
    assert all(ref.startswith("[cid-ref:") for ref in promotion["candidates"][0]["source_evidence_refs"])
    assert "First retained source" not in str(promotion)
    assert "Second retained source" not in str(promotion)
    assert "cid-workspace-a" not in str(promotion)


def test_shadow_workspace_controller_rejects_replaced_dreamer_factory() -> None:
    registry = ProviderRegistry()
    registry.register_specialist(
        SpecialistModuleSpec(
            name="dreamer.shadow",
            role="dreamer",
            factory=lambda _config: object(),
            budget=SpecialistBudget(
                critical_path_allowed=False,
                answer_authority_allowed=False,
                promotion_gate_required=True,
            ),
            input_contract="retained evidence rows with CIDs",
            output_contract="low-trust replay candidates requiring promotion gate",
        )
    )

    try:
        ShadowWorkspaceController(registry=registry).run_shadow_cycle(
            tenant_id="tenant-workspace",
            items=[WorkspaceItem(id="focus", priority=1.0, content="focus")],
            evidence=[
                {
                    "cid": "cid-workspace-a",
                    "tenant_id": "tenant-workspace",
                    "access_policy": {"tenant": "tenant-workspace"},
                    "content": "First retained source supports replay.",
                },
                {
                    "cid": "cid-workspace-b",
                    "tenant_id": "tenant-workspace",
                    "access_policy": {"tenant": "tenant-workspace"},
                    "content": "Second retained source supports gating.",
                },
            ],
        )
    except TypeError as exc:
        assert "SandboxedDreamer" in str(exc)
    else:
        raise AssertionError("replaced dreamer factory was accepted")
