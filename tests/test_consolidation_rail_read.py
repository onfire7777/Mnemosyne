"""The supersession rail reads the candidate branch without copying the tenant.

``capture-batch --consolidate`` sends every fact candidate through the promotion gate, and
the gate's pre-merge check used to export the whole tenant (``export_tenant`` ->
``dataclasses.asdict`` on every memory) once per candidate. The store grows with every
document, so batch ingest went quadratic. The rail now reads only the active facts it
budgets. These tests pin that the answer, every gate decision and the rail budget are
exactly what the export path produced, and that the check no longer scales with the
number of documents in the store.
"""

from __future__ import annotations

import random
import time
from datetime import timedelta
from typing import Any

import pytest

from eval.g0.write_gating import _BudgetExtractor, _append, _budget_case, _worker
from mnemosyne import models
from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, utc_now
from mnemosyne.security import TrustTier

TENANT = "rail-read-tenant"
OTHER = "rail-read-other-tenant"


def _legacy_rail_read(
    self: ConsolidationWorker, tenant_id: str, budget: Any, candidate_branch: str
) -> set[str]:
    """The pre-fix behaviour: deep-copy the tenant and filter the export."""
    return budget.branch_superseded_ids(self._export_snapshot(tenant_id), candidate_branch)


def _fact(tenant: str, subject: str, obj: str, cid: str, *, trust_tier: int, valid_from: Any = None) -> Assertion:
    kwargs: dict[str, Any] = {}
    if valid_from is not None:
        kwargs["valid_from"] = valid_from
    return Assertion(
        tenant_id=tenant,
        subject=subject,
        predicate="value is",
        object=obj,
        source_evidence_cids=[cid],
        status="active",
        trust_tier=trust_tier,
        access_policy={"tenant": tenant},
        **kwargs,
    )


# --------------------------------------------------------------------------- differential


def test_rail_read_equals_the_export_snapshot_on_random_branch_states() -> None:
    """Fast read == export filter, across tenants, branches and every supersession outcome."""
    non_empty = 0
    for seed in range(12):
        rng = random.Random(seed)
        engine = LocalMemoryEngine()
        worker = ConsolidationWorker(engine, [_budget_case()], consolidation_min_steps=0)
        subjects: dict[str, int] = {}
        for tenant in (TENANT, OTHER):
            subjects[tenant] = rng.randint(3, 9)
            for index in range(subjects[tenant]):
                cid = _append(engine, tenant, f"Entity {index} value is alpha.")
                engine.upsert_assertion(_fact(tenant, f"Entity {index}", "alpha", cid, trust_tier=int(TrustTier.NORMAL)))
        budget = worker._new_mutation_rail_budget(TENANT, "main")
        assert budget.active_fact_ids, "the budget must see active facts to make the check meaningful"

        branches: dict[str, set[str]] = {TENANT: {"main"}, OTHER: {"main"}}
        for step in range(rng.randint(8, 20)):
            tenant = rng.choice((TENANT, OTHER))
            if rng.random() < 0.3:
                name = f"canary-{rng.randint(0, 3)}"
                engine.branch(name, frm="main", kind="canary", tenant_id=tenant)
                branches[tenant].add(name)
                continue
            branch = rng.choice(sorted(branches[tenant]))
            index = rng.randrange(subjects[tenant])
            cid = _append(engine, tenant, f"Entity {index} value is step {step}.")
            outcome = rng.choice(("trust_supersede", "trust_rejected", "recency_supersede", "historical", "reinforce"))
            if outcome == "trust_supersede":
                fact = _fact(tenant, f"Entity {index}", f"v{step}", cid, trust_tier=int(TrustTier.DIRECT_USER))
            elif outcome == "trust_rejected":
                fact = _fact(tenant, f"Entity {index}", f"v{step}", cid, trust_tier=int(TrustTier.UNTRUSTED_EXTERNAL))
            elif outcome == "recency_supersede":
                fact = _fact(tenant, f"Entity {index}", f"v{step}", cid, trust_tier=int(TrustTier.NORMAL),
                             valid_from=utc_now() + timedelta(days=1 + step))
            elif outcome == "historical":
                fact = _fact(tenant, f"Entity {index}", f"v{step}", cid, trust_tier=int(TrustTier.NORMAL),
                             valid_from=utc_now() - timedelta(days=365))
            else:
                fact = _fact(tenant, f"Entity {index}", "alpha", cid, trust_tier=int(TrustTier.NORMAL))
            engine.upsert_assertion(fact, branch=branch)

        snapshot = worker._export_snapshot(TENANT)
        for name in sorted(branches[TENANT] | branches[OTHER] | {"no-such-branch"}):
            fast = worker._branch_superseded_fact_ids(TENANT, budget, name)
            assert fast == budget.branch_superseded_ids(snapshot, name), (seed, name)
            non_empty += bool(fast)
    assert non_empty >= 5, "the random states never superseded a budgeted fact - the test would prove nothing"


# --------------------------------------------------------------------------- end to end


def _scenario(rate: float | None, count: int) -> tuple[LocalMemoryEngine, Any]:
    """``count`` active alpha facts, then corroborated beta candidates that supersede them."""
    engine = LocalMemoryEngine()
    replacements: list[str] = []
    for index in range(count):
        cid = _append(engine, TENANT, f"Entity {index} value is alpha.")
        engine.upsert_assertion(_fact(TENANT, f"Entity {index}", "alpha", cid, trust_tier=int(TrustTier.NORMAL)))
        replacements.append(
            _append(engine, TENANT, f"Entity {index} value is beta.", metadata={"consolidation": {"prediction_error": 1.0}})
        )
        replacements.append(
            _append(
                engine,
                TENANT,
                f"Independent note: Entity {index} value is beta.",
                metadata={"consolidation": {"prediction_error": 1.0}},
                source_type="note",
            )
        )
    worker = _worker(
        engine,
        max_supersession_rate=rate,
        gate_cases=[_budget_case()],
        candidate_extractor=_BudgetExtractor(count),
    )
    run = worker.run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": replacements,
            "prediction_error": {"score": 1.0},
            "passes": ["extractor", "resolver", "belief_reviser", "promotion_gate"],
        }
    )
    return engine, run


def _normalized(engine: LocalMemoryEngine, run: Any) -> dict[str, Any]:
    """Everything the gate decided, with random assertion ids replaced by their statements."""
    statements = {item.id: f"{item.subject} {item.predicate} {item.object}" for item in engine.assertions.values()}
    rails = dict(next(item["details"] for item in run.pass_results if item["name"] == "mutation_rails"))
    rails["superseded_fact_ids"] = sorted(statements[item] for item in rails["superseded_fact_ids"])
    main = sorted(
        (item.subject, item.predicate, item.object, item.status)
        for item in engine.assertions.values()
        if item.tenant_id == TENANT and item.branch == "main"
    )
    return {"candidates": list(run.candidate_results), "rails": rails, "main": main, "skipped": list(run.skipped)}


def _count_exports(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls = [0]
    original = LocalMemoryEngine.export_tenant

    def counted(self: LocalMemoryEngine, tenant_id: str) -> dict[str, Any]:
        calls[0] += 1
        return original(self, tenant_id)

    monkeypatch.setattr(LocalMemoryEngine, "export_tenant", counted)
    return calls


@pytest.mark.parametrize("rate", [0.0, 0.25, 0.5, 1.0, None])
@pytest.mark.parametrize("count", [4, 6])
def test_gate_decisions_are_identical_to_the_export_snapshot_path(
    monkeypatch: pytest.MonkeyPatch, rate: float | None, count: int
) -> None:
    exports = _count_exports(monkeypatch)
    engine_new, run_new = _scenario(rate, count)
    new_exports = exports[0]

    monkeypatch.setattr(ConsolidationWorker, "_branch_superseded_fact_ids", _legacy_rail_read)
    exports[0] = 0
    engine_old, run_old = _scenario(rate, count)
    old_exports = exports[0]

    new, old = _normalized(engine_new, run_new), _normalized(engine_old, run_old)
    assert new == old
    # Every candidate reached the rail on the old path (one export each); none export now.
    assert old_exports - new_exports == count
    if rate == 0.0:
        assert new["rails"]["violations"], "rate 0 must trip the supersession rail"
        assert not any(item["promoted"] for item in new["candidates"])
    if rate == 1.0:
        assert not new["rails"]["violations"]
        assert all(item["promoted"] for item in new["candidates"])
        assert len(new["rails"]["superseded_fact_ids"]) == count
    if rate == 0.5:
        promoted = sum(bool(item["promoted"]) for item in new["candidates"])
        assert 0 < promoted < count, "a half budget must promote some candidates and stop the rest"


def test_rail_exports_no_longer_grow_with_the_number_of_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    exports = _count_exports(monkeypatch)
    seen = {}
    for count in (3, 12):
        exports[0] = 0
        _, run = _scenario(1.0, count)
        assert all(item["promoted"] for item in run.candidate_results)
        seen[count] = exports[0]
    assert seen[3] == seen[12], seen


# --------------------------------------------------------------------------- scaling


def _store(docs: int, facts: int) -> tuple[ConsolidationWorker, Any, str]:
    engine = LocalMemoryEngine()
    for index in range(docs):
        _append(engine, TENANT, f"Corpus document {index} about subject {index % 97}.")
    for index in range(facts):
        cid = _append(engine, TENANT, f"Entity {index} value is alpha.")
        engine.upsert_assertion(_fact(TENANT, f"Entity {index}", "alpha", cid, trust_tier=int(TrustTier.NORMAL)))
    worker = ConsolidationWorker(engine, [_budget_case()], consolidation_min_steps=0)
    budget = worker._new_mutation_rail_budget(TENANT, "main")
    branch = "canary-scaling"
    engine.branch(branch, frm="main", kind="canary", tenant_id=TENANT)
    cid = _append(engine, TENANT, "Entity 0 value is beta.")
    engine.upsert_assertion(_fact(TENANT, "Entity 0", "beta", cid, trust_tier=int(TrustTier.DIRECT_USER)), branch=branch)
    return worker, budget, branch


def test_rail_check_cost_does_not_grow_with_the_corpus_250_vs_2000_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    copies = [0]
    for cls in (models.Evidence, models.Assertion, models.Relation):
        original = cls.to_dict

        def counted(self: Any, _original: Any = original) -> dict[str, Any]:
            copies[0] += 1
            return _original(self)

        monkeypatch.setattr(cls, "to_dict", counted)

    fast_copies, legacy_copies, fast_seconds = {}, {}, {}
    for docs in (250, 2000):
        worker, budget, branch = _store(docs, facts=40)
        copies[0] = 0
        fast = worker._branch_superseded_fact_ids(TENANT, budget, branch)
        fast_copies[docs] = copies[0]
        copies[0] = 0
        legacy = _legacy_rail_read(worker, TENANT, budget, branch)
        legacy_copies[docs] = copies[0]
        superseded_entity_0 = {
            item.id
            for item in worker.engine.assertions.values()
            if item.branch == "main" and item.subject == "Entity 0" and item.object == "alpha"
        }
        assert fast == legacy == superseded_entity_0
        best = float("inf")
        for _ in range(7):
            start = time.perf_counter()
            worker._branch_superseded_fact_ids(TENANT, budget, branch)
            best = min(best, time.perf_counter() - start)
        fast_seconds[docs] = best

    # The fix copies nothing, whatever the corpus size ...
    assert fast_copies == {250: 0, 2000: 0}
    # ... while the export it replaces copied every document of the tenant.
    assert legacy_copies[2000] > 4 * legacy_copies[250], legacy_copies
    # Only the 40 budgeted facts are looked up, so 8x the documents costs about the same.
    assert fast_seconds[2000] < 3 * fast_seconds[250] + 0.002, fast_seconds
