"""FR-21 parametric/LoRA scope checks — the INTENTIONALLY-LIMITED v1 bar.

Blueprint context (do NOT over-build):
  - FR-21 (§14, P2 "future considerations"): *Parametric tier (LoRA/test-time
    training of validated lessons), isolated + gated.*
  - Non-goal **N2** (§12): *Default weight-level fine-tuning — Learning lives in
    memory/prompts/skills. Why: avoids catastrophic forgetting and opacity;
    parametric learning is an optional advanced tier (§23.6), not the path.*
  - §23.6: *Test-time training into LoRA fast-weights / periodic LoRA distillation
    of VALIDATED lessons — gated by §23.3, isolated (LoRA/adapter) to bound
    catastrophic forgetting, never touching the base model or the invariant.*
  - §23.5 immutable outer invariant: reward signal, validator, regression suite,
    trust-tier logic, and mutation-rate rails live OUTSIDE the self-editable
    surface and are enforced STRUCTURALLY.

So the v1 BAR is NOT "a GPU trains a LoRA". It is strictly that the parametric
tier exists as a *correctly-fenced boundary*:

  (1) AUTH: the parametric tool surface (propose/evaluate/rollback) requires
      OPERATOR-grade authority + operator-tier source trust. A reader/agent, or
      an operator with sub-operator trust, is REFUSED.
  (2) RAILS (structural, local, no GPU): a proposed adapter is REJECTED if its
      self-reported metrics or provider metadata try to widen any §23.5/§31 rail
      — mutation-rate (supersession/prune), reward-signal (external_only),
      target-sink (untrusted->system_prompt forbidden), monotonic-trust, and the
      no-teaching-to-the-test rule.
  (3) GATE: promotion requires the protected regression suite to pass with margin
      above run-to-run noise; otherwise the artifact stays SHADOW (never promoted).
  (4) ROLLBACK: a promoted/rejected artifact is transitively reversible to a
      ``rolled_back`` state with a rollback ref + protected-suite evidence.
  (5) ISOLATION + NO-GPU: a real LoRA trainer is an injected ``ParametricTrainer``
      boundary (``CommandParametricTrainer`` runs a local subprocess, shell-free).
      The default tier needs NO trainer/GPU and stays shadow-only — exactly the
      "designed for, not built yet" P2 posture.

Everything beyond that bar (an actual LoRA/test-time-training run, GPU SLOs,
forgetting measurement on a served adapter) is correctly DEFERRED and recorded
in ``REAL_DEPLOYMENT_VALIDATION``.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from ._scope_harness import Check

# Public, intentionally-deferred validation surface (out of scope for v1).
REAL_DEPLOYMENT_VALIDATION: tuple[str, ...] = (
    "Real LoRA/test-time-training run: implement a ParametricTrainer (e.g. wrap a "
    "PEFT/LoRA fine-tune as a CommandParametricTrainer subprocess) and prove a "
    "validated-lesson adapter actually changes served behaviour. v1 ships only the "
    "boundary + a local shadow adapter; no weights are trained and no GPU is required.",
    "Catastrophic-forgetting bound: measure the protected-regression suite on the "
    "SERVED adapter over many promotion cycles (the §23.6 anti-forgetting claim). v1 "
    "only proves the gate refuses promotion on protected regressions in-process.",
    "Base-model isolation at serve time: prove the adapter never mutates base weights "
    "or the invariant in a real inference stack. v1 proves isolation structurally "
    "(separate artifact store + immutable rail labels), not at a live serving layer.",
    "GPU/throughput SLOs + distillation cadence: training cost, periodic-distillation "
    "scheduling, and adapter-store scale are unmeasured in v1.",
    "Operator credential separation as a SEPARATE service/credentials (§23.5): v1 "
    "enforces operator authority in-process via SecurityPolicy; production must split "
    "the rail-enforcing surface into its own credentialed service.",
)

_SRC_PARAMETRIC = Path(__file__).resolve().parents[3] / "src" / "mnemosyne" / "parametric.py"


def _tools(tmp: Path):
    """Build a real MemoryTools with a disk-backed parametric artifact store."""
    from mnemosyne.engine import LocalMemoryEngine
    from mnemosyne.mcp_tools import MemoryTools
    from mnemosyne.parametric import ParametricArtifactStore, ParametricTier
    from mnemosyne.security import SecurityPolicy

    engine = LocalMemoryEngine()
    tier = ParametricTier(ParametricArtifactStore(tmp / "parametric"))
    return MemoryTools(engine, security=SecurityPolicy(), parametric=tier)


def _seed_validated_lesson(tools) -> None:
    """Give the learning system one active lesson + procedure to propose from."""
    from mnemosyne.learning import Lesson, Procedure

    lesson = Lesson(
        tenant_id="t",
        lesson_type="corrective",
        failure_signature="sig-x",
        content="verify with tools before writing durable memory",
        status="active",
    )
    procedure = Procedure(
        tenant_id="t",
        kind="checklist",
        name="verify-then-write",
        body="1. detect 2. verify 3. correct 4. re-run protected cases",
        signature={"failure_signature": "sig-x"},
        status="active",
    )
    tools.learning.lessons[lesson.id] = lesson
    tools.learning.procedures[procedure.id] = procedure


# --- (1) AUTH: operator-grade authority required ------------------------------


def _check_propose_requires_operator_role() -> str | None:
    """A non-operator role is refused at parametric_propose (PermissionError)."""
    import tempfile

    from mnemosyne.security import TrustTier

    with tempfile.TemporaryDirectory(prefix="mnemo-scope-fr21-auth-") as tmp:
        tools = _tools(Path(tmp))
        _seed_validated_lesson(tools)
        for role in ("reader", "agent", "consolidator"):
            try:
                tools.parametric_propose("t", role=role, source_trust_tier=int(TrustTier.OPERATOR))
            except PermissionError as exc:
                assert "operator" in str(exc).lower()
                continue
            raise AssertionError(f"role={role} was NOT refused operator-only parametric_propose")
        return "reader/agent/consolidator all refused; parametric_propose is operator-only"


def _check_propose_requires_operator_trust_tier() -> str | None:
    """Even role=operator is refused below operator-tier SOURCE trust."""
    import tempfile

    from mnemosyne.security import TrustTier

    with tempfile.TemporaryDirectory(prefix="mnemo-scope-fr21-trust-") as tmp:
        tools = _tools(Path(tmp))
        _seed_validated_lesson(tools)
        # Trust is a LOWER-is-better scale; OPERATOR == 0 is the most-trusted tier.
        # min_policy_write_trust requires source_trust_tier <= OPERATOR(0). A
        # genuinely weaker source (NORMAL=3 > 0) must therefore be refused even
        # for role=operator — proving auth needs BOTH role AND source trust.
        below = int(TrustTier.NORMAL)
        assert below > int(TrustTier.OPERATOR), "expected a weaker-than-operator source tier"
        try:
            tools.parametric_propose("t", role="operator", source_trust_tier=below)
        except PermissionError as exc:
            assert "operator" in str(exc).lower()
            return "operator role + sub-operator source trust correctly refused"
        raise AssertionError("operator role with sub-operator source trust was NOT refused")


def _check_operator_can_propose_shadow_artifact() -> str | None:
    """The positive path: a true operator proposes an ISOLATED SHADOW artifact."""
    import tempfile

    from mnemosyne.security import TrustTier

    with tempfile.TemporaryDirectory(prefix="mnemo-scope-fr21-ok-") as tmp:
        tools = _tools(Path(tmp))
        _seed_validated_lesson(tools)
        artifact = tools.parametric_propose(
            "t", role="operator", source_trust_tier=int(TrustTier.OPERATOR)
        )
        assert artifact["status"] == "shadow", f"new artifact must be shadow, got {artifact['status']}"
        assert artifact["source_ids"], "artifact must carry validated source lesson/procedure ids"
        # Default tier needs NO GPU trainer; adapter is the local shadow stand-in.
        assert artifact["adapter_kind"] == "local-shadow-adapter"
        # The artifact is persisted to an ISOLATED store (not the main memory tree).
        assert str(artifact["artifact_uri"]).startswith("local-parametric://")
        assert artifact["security"]["allowed"] is True
        return "operator proposes isolated SHADOW local-shadow-adapter (no GPU)"


# --- (2) RAILS: structural rejection of rail-widening (no GPU) -----------------


def _check_rail_bounds_match_blueprint() -> str | None:
    """The structural rail constants equal the §23.5/§31 blueprint values."""
    from mnemosyne.parametric import ParametricInvariantRails

    rails = ParametricInvariantRails()
    assert rails.max_supersession_rate == 0.05
    assert rails.max_prune_fraction_per_pass == 0.02
    assert rails.max_source_mutation_rate == 0.05
    assert rails.reward_signal == "external_only"
    assert rails.monotonic_trust is True
    assert rails.untrusted_to_system_prompt == "forbidden"
    return "rail bounds = blueprint (superseding 0.05 / prune 0.02 / external_only / monotonic / sink-forbidden)"


def _check_rails_reject_each_widening_attempt() -> str | None:
    """Each rail-widening attempt is REFUSED by the proposal/metadata gate.

    Covers the four structural rail families named in the task: mutation-rate,
    reward, sink, and (gate-adjacent) trust/eval-overlap — all WITHOUT a GPU.
    """
    from mnemosyne.parametric import ParametricArtifact, ParametricInvariantRails

    rails = ParametricInvariantRails()

    def artifact(metrics=None):
        return ParametricArtifact(
            tenant_id="t",
            source_ids=["lesson-1"],
            adapter_kind="local-shadow-adapter",
            metrics=dict(metrics or {}),
        )

    breaches = {
        "mutation-rate(supersession)": (artifact({"supersession_rate": 0.051}), {}),
        "mutation-rate(prune)": (artifact({"prune_fraction": 0.021}), {}),
        "mutation-rate(source_mutation)": (artifact({"source_mutation_rate": 0.06}), {}),
        "reward(self_generated)": (artifact(), {"metadata": {"reward_signal": "self_generated"}}),
        "sink(system_prompt)": (artifact(), {"metadata": {"target_sink": "system_prompt"}}),
        "sink(untrusted_flag)": (artifact(), {"metadata": {"untrusted_to_system_prompt": True}}),
        "monotonic_trust(disabled)": (artifact(), {"metadata": {"monotonic_trust": False}}),
        "trust_tier(widened)": (artifact(), {"metadata": {"trust_tier_delta": -1}}),
        "teach-to-the-test(eval_overlap)": (artifact(), {"metadata": {"eval_source_overlap": True}}),
    }
    refused = []
    for label, (art, provider) in breaches.items():
        try:
            rails.proposal_report(art, provider)
        except ValueError:
            refused.append(label)
            continue
        raise AssertionError(f"rail-widening NOT refused: {label}")
    assert len(refused) == len(breaches)
    return f"all {len(refused)} rail-widening attempts structurally refused: {', '.join(sorted(refused))}"


def _check_at_limit_values_are_allowed() -> str | None:
    """Boundary sanity: at-limit (not over-limit) metrics are allowed (no false rejects)."""
    from mnemosyne.parametric import ParametricArtifact, ParametricInvariantRails

    rails = ParametricInvariantRails()
    art = ParametricArtifact(
        tenant_id="t",
        source_ids=["lesson-1"],
        adapter_kind="local-shadow-adapter",
        metrics={"supersession_rate": 0.05, "prune_fraction": 0.02},
    )
    report = rails.proposal_report(art, {"metadata": {"reward_signal": "external_only"}})
    assert report["bounds"]["max_supersession_rate"] == 0.05
    return "at-limit metrics + external_only reward allowed (rails are bounds, not zero-tolerance)"


# --- (3) GATE: protected regression suite + margin -----------------------------


def _check_promotion_blocked_on_protected_regression() -> str | None:
    """A gate that reports a protected regression keeps the artifact SHADOW."""
    import tempfile

    from mnemosyne.security import TrustTier

    with tempfile.TemporaryDirectory(prefix="mnemo-scope-fr21-gate-") as tmp:
        tools = _tools(Path(tmp))
        _seed_validated_lesson(tools)
        artifact = tools.parametric_propose(
            "t", role="operator", source_trust_tier=int(TrustTier.OPERATOR)
        )
        uri = artifact["artifact_uri"]
        decision = tools.parametric_evaluate(
            uri,
            role="operator",
            source_trust_tier=int(TrustTier.OPERATOR),
            protected_case_count=2,
            gate_promoted=False,
            protected_regressions=["parametric-protected-0"],
        )
        assert decision["promoted"] is False, "artifact promoted despite protected regression"
        assert decision["artifact"]["status"] in {"shadow", "rejected"}
        return f"protected regression -> NOT promoted (status={decision['artifact']['status']})"


def _check_promotion_clears_only_on_clean_protected_gate() -> str | None:
    """A clean gate (margin>noise, all protected pass) promotes inside the isolated tier."""
    import tempfile

    from mnemosyne.security import TrustTier

    with tempfile.TemporaryDirectory(prefix="mnemo-scope-fr21-promote-") as tmp:
        tools = _tools(Path(tmp))
        _seed_validated_lesson(tools)
        artifact = tools.parametric_propose(
            "t", role="operator", source_trust_tier=int(TrustTier.OPERATOR)
        )
        decision = tools.parametric_evaluate(
            artifact["artifact_uri"],
            role="operator",
            source_trust_tier=int(TrustTier.OPERATOR),
            protected_case_count=2,
            gate_promoted=True,
            protected_regressions=[],
        )
        assert decision["promoted"] is True, f"clean gate did not promote: {decision['reason']}"
        assert decision["artifact"]["status"] == "promoted"
        # Promotion is recorded WITH protected-suite evidence (the §23.3 gate).
        assert decision["protected_suite"]["protected_case_count"] == 2
        assert decision["gate_report"] is not None
        return "clean protected gate (2 cases, margin>noise) -> promoted in the ISOLATED tier"


# --- (4) ROLLBACK: transitive reversibility ------------------------------------


def _check_rollback_is_reversible_with_evidence() -> str | None:
    """A promoted artifact can be rolled back to a reversible state with a ref."""
    import tempfile

    from mnemosyne.security import TrustTier

    with tempfile.TemporaryDirectory(prefix="mnemo-scope-fr21-rollback-") as tmp:
        tools = _tools(Path(tmp))
        _seed_validated_lesson(tools)
        artifact = tools.parametric_propose(
            "t", role="operator", source_trust_tier=int(TrustTier.OPERATOR)
        )
        uri = artifact["artifact_uri"]
        tools.parametric_evaluate(
            uri, role="operator", source_trust_tier=int(TrustTier.OPERATOR),
            protected_case_count=1, gate_promoted=True,
        )
        rolled = tools.parametric_rollback(
            uri,
            reason="scope-conformance reversibility check",
            role="operator",
            source_trust_tier=int(TrustTier.OPERATOR),
            protected_case_count=1,
        )
        assert rolled["status"] == "rolled_back"
        assert rolled["rollback_ref"], "rollback must record a rollback ref"
        assert rolled["protected_suite"]["protected_case_count"] == 1
        return f"promoted -> rolled_back with ref={rolled['rollback_ref'][:18]}... + protected-suite evidence"


def _check_rollback_requires_operator_authority() -> str | None:
    """Rollback is destructive + operator-gated; a non-operator is refused."""
    import tempfile

    from mnemosyne.security import TrustTier

    with tempfile.TemporaryDirectory(prefix="mnemo-scope-fr21-rbauth-") as tmp:
        tools = _tools(Path(tmp))
        _seed_validated_lesson(tools)
        artifact = tools.parametric_propose(
            "t", role="operator", source_trust_tier=int(TrustTier.OPERATOR)
        )
        try:
            tools.parametric_rollback(
                artifact["artifact_uri"],
                reason="unauthorized",
                role="agent",
                source_trust_tier=int(TrustTier.OPERATOR),
            )
        except PermissionError:
            return "rollback refused for non-operator (destructive + operator-gated)"
        raise AssertionError("non-operator rollback was NOT refused")


# --- (5) ISOLATION + NO-GPU: command boundary, shadow-only default ------------


def _check_trainer_boundary_is_injected_subprocess_no_gpu() -> str | None:
    """A real LoRA trainer is an INJECTED boundary; the default tier needs none.

    CommandParametricTrainer is the shell-free subprocess seam where a real GPU
    trainer plugs in. We drive a tiny local stand-in 'trainer' (pure python, no
    GPU) to prove the boundary's propose/rollback contract — that is the whole
    v1 ask: the seam exists and is exercised, not that a LoRA is trained.
    """
    import shutil
    import sys

    from mnemosyne.parametric import CommandParametricTrainer, ParametricTier
    from mnemosyne.learning import Lesson, Procedure

    python = sys.executable or shutil.which("python3") or "python3"
    # Stand-in trainer 'model': reads JSON on stdin, emits adapter metadata.
    prog = (
        "import json,sys;"
        "json.load(sys.stdin);"
        "print(json.dumps({'adapter_kind':'stand-in-lora',"
        "'metrics':{'supersession_rate':0.0},"
        "'metadata':{'reward_signal':'external_only'},"
        "'artifact_ref':'stand-in://adapter'}))"
    )
    trainer = CommandParametricTrainer([python, "-c", prog], adapter_kind="stand-in-lora")
    assert trainer.adapter_kind == "stand-in-lora"
    tier = ParametricTier(trainer=trainer)
    lesson = Lesson(tenant_id="t", lesson_type="corrective", failure_signature="s",
                    content="c", status="active")
    procedure = Procedure(tenant_id="t", kind="checklist", name="p", body="b",
                          signature={"failure_signature": "s"}, status="active")
    artifact = tier.propose_from_lessons("t", [lesson], [procedure])
    # The injected trainer's adapter_kind + provider_invoked marker flow through.
    assert artifact.adapter_kind == "stand-in-lora"
    assert artifact.metrics.get("provider_invoked") == 1.0
    assert artifact.status == "shadow", "trainer-backed proposal is still shadow until gated"
    return "CommandParametricTrainer subprocess seam exercised (no GPU); proposal stays shadow"


def _check_default_tier_is_shadow_only_without_trainer() -> str | None:
    """With NO trainer + NO store, the tier is a pure shadow boundary (P2 posture)."""
    from mnemosyne.parametric import ParametricTier
    from mnemosyne.learning import Lesson, Procedure

    tier = ParametricTier()  # no trainer, no store
    assert tier.trainer is None
    lesson = Lesson(tenant_id="t", lesson_type="corrective", failure_signature="s",
                    content="c", status="active")
    procedure = Procedure(tenant_id="t", kind="checklist", name="p", body="b",
                          signature={"failure_signature": "s"}, status="active")
    artifact = tier.propose_from_lessons("t", [lesson], [procedure])
    assert artifact.status == "shadow"
    assert artifact.adapter_kind == "local-shadow-adapter"
    # Required immutable rail labels are attached so the downstream gate can demand them.
    required = set(tier.required_rails)
    assert required.issubset(set(artifact.immutable_rails))
    return "default ParametricTier() = shadow-only, no trainer/GPU, carries immutable rail labels"


def _check_artifact_store_is_path_isolated() -> str | None:
    """The adapter artifact store is path-fenced (can't escape its root)."""
    import tempfile

    from mnemosyne.parametric import ParametricArtifactStore

    with tempfile.TemporaryDirectory(prefix="mnemo-scope-fr21-store-") as tmp:
        store = ParametricArtifactStore(Path(tmp) / "store")
        for bad in ("../escape", "..", "a/b", "te\\nant"):
            try:
                store._validate_segment(bad, "tenant")
            except ValueError:
                continue
            raise AssertionError(f"store accepted unsafe segment: {bad!r}")
        return "ParametricArtifactStore rejects path-escape segments (isolated adapter store)"


CHECKS: list[Check] = [
    # (1) AUTH
    Check("FR-21", "propose_requires_operator_role",
          "v1 bar: parametric_propose is operator-only (reader/agent/consolidator refused).",
          _check_propose_requires_operator_role),
    Check("FR-21", "propose_requires_operator_trust_tier",
          "v1 bar: operator role still needs operator-tier SOURCE trust.",
          _check_propose_requires_operator_trust_tier),
    Check("FR-21", "operator_can_propose_shadow_artifact",
          "v1 bar: a true operator proposes an ISOLATED shadow adapter (no GPU).",
          _check_operator_can_propose_shadow_artifact),
    # (2) RAILS
    Check("FR-21", "rail_bounds_match_blueprint",
          "v1 bar: structural rail constants equal §23.5/§31 blueprint values.",
          _check_rail_bounds_match_blueprint),
    Check("FR-21", "rails_reject_each_widening_attempt",
          "v1 bar: mutation-rate/reward/sink/trust/eval-overlap widening all structurally refused.",
          _check_rails_reject_each_widening_attempt),
    Check("FR-21", "at_limit_values_allowed",
          "v1 bar: at-limit metrics allowed (rails are bounds, not false-positives).",
          _check_at_limit_values_are_allowed),
    # (3) GATE
    Check("FR-21", "promotion_blocked_on_protected_regression",
          "v1 bar: a protected regression keeps the adapter SHADOW (never promoted).",
          _check_promotion_blocked_on_protected_regression),
    Check("FR-21", "promotion_clears_only_on_clean_protected_gate",
          "v1 bar: promotion needs a clean protected gate with margin>noise.",
          _check_promotion_clears_only_on_clean_protected_gate),
    # (4) ROLLBACK
    Check("FR-21", "rollback_is_reversible_with_evidence",
          "v1 bar: a promoted adapter rolls back to a reversible state with ref + evidence.",
          _check_rollback_is_reversible_with_evidence),
    Check("FR-21", "rollback_requires_operator_authority",
          "v1 bar: rollback is destructive + operator-gated.",
          _check_rollback_requires_operator_authority),
    # (5) ISOLATION + NO-GPU
    Check("FR-21", "trainer_boundary_is_injected_subprocess_no_gpu",
          "v1 bar: real trainer is an injected shell-free subprocess seam (exercised, no GPU).",
          _check_trainer_boundary_is_injected_subprocess_no_gpu),
    Check("FR-21", "default_tier_is_shadow_only_without_trainer",
          "v1 bar: default tier is shadow-only with no trainer/GPU and carries rail labels.",
          _check_default_tier_is_shadow_only_without_trainer),
    Check("FR-21", "artifact_store_is_path_isolated",
          "v1 bar: adapter artifact store is path-fenced (isolated).",
          _check_artifact_store_is_path_isolated),
]
