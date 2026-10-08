"""Batched promotion gate: capture-batch --consolidation-gate-batch (blueprint §17.4 / §23.3)."""

from __future__ import annotations

import json
import random
import zlib
from pathlib import Path
from typing import Any

import pytest

from eval.perf import golden_equivalence as g
from mnemosyne import consolidation
from mnemosyne.cid_lists import CidList, intern_cids, shared_map
from mnemosyne.engine import _ASSERTION_TIMES, LocalMemoryEngine, _row_snapshot, _union_sorted_sources
from mnemosyne.gate import Candidate, PromotionGate, RegressionCase
from mnemosyne.models import Assertion


def _run_growth(run_dir: Path, extra: list[str]) -> tuple[Path, list[Any]]:
    """Every capture batch of the golden growth scenario, gate rejections reported."""
    run_dir.mkdir()
    spec = g.scenario("synthetic-growth", None)
    store = run_dir / "store.json"
    outputs = []
    with g.deterministic_runtime():
        g._cli(g._gate_case_argv(store, spec["gate_content"]))
        for index, step in enumerate(spec["steps"]):
            if "capture" not in step:
                continue
            path = run_dir / f"batch-{index}.jsonl"
            path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in step["capture"]),
                            encoding="utf-8")
            outputs.append(g._cli(["--backend", "local", "--store", str(store), "capture-batch",
                                   "--input-jsonl", str(path), "--consolidate",
                                   "--consolidation-rejections", "report", *extra]))
    return store, outputs


def _without(text: str, run_dir: Path) -> Any:
    return json.loads(text.replace(json.dumps(str(run_dir))[1:-1], "RUN"))


def test_the_default_gate_batch_is_sixty_four(tmp_path: Path) -> None:
    store_a, out_a = _run_growth(tmp_path / "a", [])
    store_b, out_b = _run_growth(tmp_path / "b", ["--consolidation-gate-batch", "64"])
    assert _without(store_a.read_text(encoding="utf-8"), tmp_path / "a") == _without(
        store_b.read_text(encoding="utf-8"), tmp_path / "b"
    )
    assert _without(json.dumps(out_a), tmp_path / "a") == _without(json.dumps(out_b), tmp_path / "b")


def _poisoned(candidate_id: str) -> bool:
    return zlib.crc32(candidate_id.encode("utf-8")) % 5 == 0


def test_groups_merge_only_after_a_passing_run_and_rejections_are_per_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A protected case that fails on any branch carrying a 'poisoned' candidate.

    Every poisoned candidate must be rejected with the per-candidate verdict, nothing poisoned
    may reach main, each merge must follow a passing run on that branch, and no trial branch
    may be left behind.
    """
    applied: dict[str, set[str]] = {}
    last_run_ok: dict[str, bool] = {}
    merges: list[str] = []
    original_apply = consolidation._PreparedFact.apply
    original_branch = LocalMemoryEngine.branch
    original_retrieve = LocalMemoryEngine.retrieve
    original_merge = LocalMemoryEngine.merge

    def apply(self: Any, engine: Any, branch: str) -> None:
        applied.setdefault(branch, set()).add(self.candidate.id)
        original_apply(self, engine, branch)

    def branch(self: Any, name: str, *args: Any, **kwargs: Any) -> Any:
        applied.pop(name, None)
        last_run_ok.pop(name, None)
        return original_branch(self, name, *args, **kwargs)

    def retrieve(self: Any, query: str, tenant_id: str, branch: str = "main", *args: Any, **kwargs: Any) -> Any:
        result = original_retrieve(self, query, tenant_id, branch, *args, **kwargs)
        if any(_poisoned(candidate) for candidate in applied.get(branch, ())):
            result.abstained = True
        last_run_ok[branch] = not result.abstained
        return result

    def merge(self: Any, frm: str, *args: Any, **kwargs: Any) -> Any:
        assert last_run_ok.get(frm) is True, f"merged {frm} without a passing gate run"
        merges.append(frm)
        return original_merge(self, frm, *args, **kwargs)

    monkeypatch.setattr(consolidation._PreparedFact, "apply", apply)
    monkeypatch.setattr(LocalMemoryEngine, "branch", branch)
    monkeypatch.setattr(LocalMemoryEngine, "retrieve", retrieve)
    monkeypatch.setattr(LocalMemoryEngine, "merge", merge)
    store, outputs = _run_growth(tmp_path / "run", ["--consolidation-gate-batch", "4"])

    rejected: dict[str, dict[str, Any]] = {}
    evaluated: list[str] = []
    group_runs = 0
    for out in outputs:
        for item in out["consolidation"]["rejected_candidates"]:
            rejected[item["candidate_id"]] = item
        for job in out["consolidation"]["jobs"]:
            for result in job["result"]["candidate_results"]:
                evaluated.append(result["candidate_id"])
            for item in job["result"]["pass_results"]:
                if item["name"] == "promotion_gate" and item["status"] == "complete":
                    assert item["details"]["gate_mode"] == "batch" and item["details"]["batch_size"] == 4
                    group_runs += item["details"]["group_evaluations"]
    poisoned = {candidate for candidate in evaluated if _poisoned(candidate)}
    assert poisoned and group_runs and any(name.startswith("canary-batch-") for name in merges)
    # Every poisoned candidate is rejected, a failed case with the per-candidate gate's verdict.
    case_failures = 0
    for candidate in poisoned:
        item = rejected[candidate]
        if any(str(case).startswith("eval-consolidation-") for case in item["failed_cases"]):
            assert item["failed_cases"] == item["protected_regressions"]
            case_failures += 1
    assert case_failures
    engine = LocalMemoryEngine(store_path=store, read_only=True)
    assert not [name for name, meta in engine.branches.items() if (meta or {}).get("kind") == "canary"]
    promoted = {f"candidate-{row.subject} {row.predicate} {row.object}".lower()
                for row in engine.assertions.values() if row.branch == "main" and row.status == "active"}
    assert not promoted & {candidate.lower() for candidate in poisoned}


def test_group_cases_are_the_union_in_suite_order_and_ineligible_candidates_go_alone() -> None:
    engine = LocalMemoryEngine()
    cases = [
        RegressionCase("core-x", "alpha topic", "alpha?", "alpha", tier="core"),
        RegressionCase("smoke", "anything", "q", "e", tier="smoke"),
        RegressionCase("core-y", "beta topic", "beta?", "beta", tier="core"),
    ]
    gate = PromotionGate(engine, cases)
    a = Candidate("a", "lesson", "alpha thing", "", "canary-a", [])
    b = Candidate("b", "lesson", "beta thing", "", "canary-b", [])
    assert [case.id for case in gate.group_relevant_cases([b, a])] == ["core-x", "smoke", "core-y"]
    assert [case.id for case in gate.group_relevant_cases([a])] == [case.id for case in gate.relevant_cases(a)]
    lonely = PromotionGate(engine, [RegressionCase("core-x", "alpha topic", "alpha?", "alpha", tier="core")])
    assert lonely.group_eligible(a) and not lonely.group_eligible(b)  # b has no relevant case
    assert gate.supports_group_evaluation()
    gate.require_ignition = True
    assert not gate.supports_group_evaluation()


def test_batch_size_is_validated() -> None:
    from mnemosyne import cli

    assert consolidation._promotion_gate_batch_size({}) == 1
    assert consolidation._promotion_gate_batch_size({"promotion_gate_batch_size": 64}) == 64
    for bad in (0, -1, True, 2.0, "8"):
        with pytest.raises(ValueError):
            consolidation._promotion_gate_batch_size({"promotion_gate_batch_size": bad})
    args = cli.build_parser().parse_args(["capture-batch", "--input-jsonl", "x.jsonl", "--consolidate"])
    assert args.consolidation_gate_batch == 64


def test_sorted_source_union_matches_the_plain_expression() -> None:
    rng = random.Random(11)
    pool = [f"cid-{i:03d}" for i in range(60)]
    lists = [intern_cids(rng.sample(pool, rng.randint(0, 40))) for _ in range(30)]
    plain = [rng.sample(pool, rng.randint(0, 40)) for _ in range(30)]
    for _ in range(400):
        left = rng.choice(lists + plain)
        right = rng.choice(lists + plain)
        expected = sorted(set(list(left) + list(right)))
        result = _union_sorted_sources(left, right)
        assert result == expected and type(result) is CidList
        assert result is intern_cids(expected)
    with pytest.raises(TypeError):
        _union_sorted_sources([["unhashable"]], [])


def test_audit_snapshots_equal_to_dict_and_keep_shared_values_shared() -> None:
    rng = random.Random(5)
    for _ in range(50):
        cids = intern_cids([f"c{i}" for i in rng.sample(range(100), rng.randint(0, 30))])
        row = Assertion(tenant_id="t", subject="s", predicate="p", object="o", source_evidence_cids=cids,
                        scope={"k": [1, {"n": 2}]},
                        calibration={"reality_monitoring": {"source_classes": shared_map({c: "grounded" for c in cids})}})
        snapshot = _row_snapshot(row, _ASSERTION_TIMES)
        assert snapshot == row.to_dict()
        assert json.dumps(snapshot, sort_keys=True) == json.dumps(row.to_dict(), sort_keys=True)
        assert snapshot["source_evidence_cids"] is cids
        # The snapshot is a copy: later changes to the row do not reach it.
        row.scope["k"].append(3)
        assert snapshot["scope"] == {"k": [1, {"n": 2}]}
