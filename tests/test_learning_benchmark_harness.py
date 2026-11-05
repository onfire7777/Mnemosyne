from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from eval.learning.families import (
    NAMES,
    REQUIRED,
    generate,
    verify_action,
    verify_family,
)
from eval.learning.metrics import learning_metrics, paired_interval
from eval.learning.runner import load_manifest, reserve_sealed_run
from eval.learning.simulator import ScriptedAgent
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.lifecycle import FidelityTier, LifecycleState, decayed_salience
from mnemosyne.models import Evidence, Hit
from mnemosyne.observations import compute_dynamic_salience, compute_dynamic_standing
from mnemosyne.policy import OperatingPolicy
from mnemosyne.retrieval import apply_activation_scores
from mnemosyne.sqlite_engine import SqliteEngine

ROOT = Path(__file__).resolve().parents[1]


def test_all_families_seeded_and_gold_not_in_query():
    assert len(NAMES) == 26
    for family in range(1, 27):
        stream = generate(family, 13)
        assert stream == generate(family, 13)
        assert stream != generate(family, 14)
        assert all(task.expected not in task.query for task in stream)
        assert all(verify_action(task, task.expected).passed for task in stream)
        assert all(not verify_action(task, "invalid").passed for task in stream)


@pytest.mark.parametrize("family", range(1, 27))
def test_family_cannot_pass_without_required_measurements(family):
    verdict = verify_family(family, {"guard_detections": 0})
    assert not verdict.supported
    assert not verdict.passed
    evidence = {key: float("nan") for key in REQUIRED[family]}
    evidence["guard_detections"] = 0
    assert not verify_family(family, evidence).passed


def test_fault_injection_is_detected_by_f23_verifier():
    evidence = {key: 0 for key in REQUIRED[23]}
    evidence["guard_detections"] = 0
    assert verify_family(23, evidence).passed
    for key in REQUIRED[23]:
        faulty = {**evidence, key: 0.05}
        assert not verify_family(23, faulty).passed
    assert not verify_family(23, {**evidence, "guard_detections": 1}).passed


def test_agent_is_stateless_and_uses_surfaced_procedure():
    task = generate(2, 13)[0]
    agent = ScriptedAgent(5)
    action, skills, lessons = agent.act(
        task, {"procedures": [{"id": "p", "steps": [task.expected]}]}
    )
    assert action == task.expected
    assert skills == ["p"]
    assert lessons == []
    assert not hasattr(agent, "learned")


def test_metrics_are_seed_paired_and_frozen_curve_is_flat():
    frozen = learning_metrics([False, True] * 20, [1] * 40)
    assert frozen["final_window_success"] == 0.5
    assert paired_interval([0.6, 0.8], [0.4, 0.6])["mean"] == pytest.approx(0.2)
    flat = learning_metrics([True] * 40, [1] * 40)
    assert flat["slope"] == 0
    with pytest.raises(ValueError):
        paired_interval([1], [1, 2])


def test_manifest_and_sealed_claim_are_checked(tmp_path):
    manifest = load_manifest()
    assert len(manifest["families"]) == 26
    assert len([a for a in manifest["arms"] if a.startswith("without_")]) == 25
    assert set(manifest["splits"]["dev"]["seeds"]).isdisjoint(
        manifest["splits"]["sealed"]["seeds"]
    )
    reserve_sealed_run(tmp_path, "a" * 40)
    with pytest.raises(FileExistsError):
        reserve_sealed_run(tmp_path, "a" * 40)
    with pytest.raises(ValueError):
        reserve_sealed_run(tmp_path, "unknown")


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_f23_reads_leave_rank_salience_confidence_unchanged(tmp_path, backend):
    engine = (
        LocalMemoryEngine() if backend == "local" else SqliteEngine(tmp_path / "db")
    )
    tenant = "f23"
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="u",
            actor="user",
            content="The calibration device is called Helios.",
            source_type="note",
            metadata={
                "lifecycle": {"salience": 0.5, "importance": 0.2, "access_count": 0}
            },
            access_policy={"tenant": tenant},
        )
    )
    first = engine.retrieve("calibration device Helios", tenant, record_access=False)
    before = engine.get_evidence(tenant, cid).metadata["lifecycle"].copy()
    for _ in range(15):
        engine.retrieve("calibration device Helios", tenant)
    last = engine.retrieve("calibration device Helios", tenant, record_access=False)
    after = engine.get_evidence(tenant, cid).metadata["lifecycle"]
    assert after["access_count"] >= 15
    assert before["salience"] == after["salience"]
    assert [(h.id, h.score) for h in first.hits] == [(h.id, h.score) for h in last.hits]
    assert first.confidence == last.confidence
    if hasattr(engine, "close"):
        engine.close()


def test_access_cannot_raise_observation_standing_or_salience():
    assert compute_dynamic_standing(
        2, contradiction_count=1, access_velocity=0
    ) == compute_dynamic_standing(2, contradiction_count=1, access_velocity=999)
    now = datetime.now(UTC)
    before = compute_dynamic_salience(
        0.6, 0, now - timedelta(days=5), now - timedelta(days=5), now
    )
    after = compute_dynamic_salience(0.6, 500, now - timedelta(days=5), now, now)
    assert before[0] == after[0]
    assert after[1] > before[1]


def test_access_cannot_raise_forgetting_utility_or_activation():
    now = datetime.now(UTC)
    state = LifecycleState(
        "e", FidelityTier.VERBATIM, 0.1, 0, 0, now - timedelta(days=120)
    )
    assert decayed_salience(state, now) == decayed_salience(
        replace(state, access_count=500, last_accessed=now), now
    )
    hit = Hit(
        "e", "evidence", "t", "main", "x", 0.5, "lexical", metadata={"access_count": 0}
    )
    policy = OperatingPolicy()
    base = apply_activation_scores([hit], policy, now=now)[0]
    hit.metadata.update(
        access_count=500, last_accessed=now.isoformat(), demand_count=500
    )
    used = apply_activation_scores([hit], policy, now=now)[0]
    assert base.score == used.score
    hit.metadata.update(demand_outcome_count=2)
    earned = apply_activation_scores([hit], policy, now=now)[0]
    assert earned.metadata["activation"]["components"]["base_level"] > 0


@pytest.mark.parametrize("name", ["ingestion", "prefetch", "gate", "self_optimization"])
def test_internal_retrievals_explicitly_disable_audit_writes(name):
    tree = ast.parse((ROOT / "src" / "mnemosyne" / f"{name}.py").read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "retrieve"
    ]
    assert calls
    for call in calls:
        option = next(
            (kw.value for kw in call.keywords if kw.arg == "record_access"), None
        )
        assert isinstance(option, ast.Constant) and option.value is False


@pytest.mark.parametrize("name", ["engine", "postgres_engine", "canary_overlay"])
def test_read_mark_implementations_cannot_write_salience(name):
    tree = ast.parse((ROOT / "src" / "mnemosyne" / f"{name}.py").read_text())
    bodies = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name in {"_record_retrieval_access", "_overlay_record_access"}
    ]
    assert bodies
    for body in bodies:
        source = ast.unparse(body)
        assert "['salience'] =" not in source


def test_quality_gate_queries_do_not_write_access():
    tree = ast.parse((ROOT / "eval" / "run_quality_gate.py").read_text())
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "retrieve"
    ]
    assert calls
    assert all(
        any(
            kw.arg == "record_access"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is False
            for kw in call.keywords
        )
        for call in calls
    )
