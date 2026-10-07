"""Thin canaries must leave main exactly as full canary branches do.

Each case drives two in-memory engines through the same seeded sequence of promotion-gate
cycles (canary from main, candidate upserts and relations on it, merge or discard), mixed with
direct writes to main that leave retracted, superseded and differently trusted facts behind.
One engine runs with thin canaries, the other with ``MNEMOSYNE_THIN_CANARIES=0`` (the legacy
full branches). Their main branches must be identical after canonical relabelling, excluding
only the bookkeeping the golden harness documents (merged canaries, per-merge replay rows).

The mix deliberately produces unstable groups - a retracted, more trusted fact next to the
active one, whose replays supersede and restore it at every merge - which is where replaying a
live row instead of the canary's copy goes wrong.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from eval.perf.golden_equivalence import (
    BOOKKEEPING_OPS,
    MERGE_REPLAY_KEYS,
    REPLAY_MARK,
    canonical,
    deterministic_runtime,
    diff,
)
from mnemosyne.canary_overlay import THIN_CANARIES_ENV

TENANT = "overlay-prop"
SUBJECTS = ["S0", "S1", "S2", "S3"]
OBJECTS = ["red", "blue", "green", "amber"]


def _ops(seed: int) -> list[tuple[Any, ...]]:
    rng = random.Random(seed)
    ops: list[tuple[Any, ...]] = []

    def main_write(statuses: list[str]) -> tuple[Any, ...]:
        return ("main", rng.choice(SUBJECTS), rng.choice(OBJECTS), rng.randint(0, 2), rng.choice(statuses), rng.random() < 0.7)

    for _ in range(rng.randint(2, 7)):
        ops.append(main_write(["candidate", "candidate", "retracted", "superseded"]))
    for cycle in range(rng.randint(8, 22)):
        writes = [(rng.choice(SUBJECTS), rng.choice(OBJECTS), rng.randint(0, 2), rng.random() < 0.7)
                  for _ in range(rng.randint(1, 3))]
        relations = [(rng.choice(SUBJECTS), rng.choice(["links", "owns"]), rng.choice(SUBJECTS))
                     for _ in range(rng.randint(0, 2))]
        # What the gate does on a canary before deciding: retrieve, recording access.
        read = (rng.choice(SUBJECTS), rng.random() < 0.5) if rng.random() < 0.85 else None
        ops.append(("gate", f"canary-prop-{cycle}", writes, relations, rng.random() < 0.8, read))
        if rng.random() < 0.12:
            ops.append(main_write(["candidate", "retracted"]))
    return ops


def _run(ops: list[tuple[Any, ...]], thin: bool, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, Any]]:
    monkeypatch.setenv(THIN_CANARIES_ENV, "1" if thin else "0")
    with deterministic_runtime() as clock:
        from mnemosyne.engine import LocalMemoryEngine
        from mnemosyne.models import Assertion, Relation

        engine = LocalMemoryEngine()

        def fact(subject: str, obj: str, tier: int, status: str = "candidate") -> Any:
            return Assertion(tenant_id=TENANT, subject=subject, predicate="is", object=obj, trust_tier=tier,
                             status=status)

        reads: list[Any] = []
        for op in ops:
            if op[0] == "main":
                _, subject, obj, tier, status, tick = op
                if tick:
                    clock.tick()
                engine.upsert_assertion(fact(subject, obj, tier, status))
                continue
            _, name, writes, relations, merge, read = op
            clock.tick()
            engine.branch(name, frm="main", kind="canary", tenant_id=TENANT)
            for subject, obj, tier, tick in writes:
                if tick:
                    clock.tick()
                engine.upsert_assertion(fact(subject, obj, tier), branch=name)
            for source, predicate, target in relations:
                engine.add_relation(Relation(tenant_id=TENANT, source=source, predicate=predicate, target=target),
                                    branch=name)
            if read is not None:
                # The canary reads main as the previous merges left it: deferred replays must be
                # invisible here, exactly as if every merge had replayed everything.
                clock.tick()
                subject, deep = read
                reads.append(engine.retrieve(f"what is {subject}", tenant_id=TENANT, branch=name, deep=deep).to_dict())
            clock.tick()
            if merge:
                engine.merge(name, "main", tenant_id=TENANT)
            else:
                engine.discard(name, tenant_id=TENANT)

        stats = dict(engine.overlay_stats)
        state = {
            "assertions": [a.to_dict() for a in engine.assertions.values() if a.branch == "main"],
            "relations": [r.to_dict() for r in engine.relations.values() if r.branch == "main"],
            "justifications": [j.to_dict() for j in engine.justifications.values()],
            "contradictions": [c.to_dict() for c in engine.contradictions.values()],
            "audit": [row for row in engine.audit_log
                      if row.get("op") not in BOOKKEEPING_OPS and not row.get(REPLAY_MARK)],
            "merges": [{k: v for k, v in row.items() if k not in MERGE_REPLAY_KEYS} for row in engine.merge_log],
        }
        return canonical({"state": {TENANT: state}, "reads": reads}), stats


@pytest.mark.parametrize("seed", range(40))
def test_thin_canaries_leave_main_exactly_as_full_branches(seed: int, monkeypatch: pytest.MonkeyPatch) -> None:
    ops = _ops(seed)
    thin, stats = _run(ops, True, monkeypatch)
    full, legacy_stats = _run(ops, False, monkeypatch)
    assert legacy_stats["created"] == 0, "the legacy run must not use overlays"
    gates = [op for op in ops if op[0] == "gate"]
    assert stats["created"] == len(gates)
    assert stats["merged"] == sum(1 for op in gates if op[4])
    problems = diff(full, thin)
    assert not problems, f"seed {seed}: thin canaries drifted from full branches:\n" + "\n".join(problems)


def test_retracted_trusted_fact_is_replayed_from_the_canary_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression the golden conflicts scenario caught: a retracted tier-0 fact and an active
    tier-1 fact in one group. Each merge replays the retracted copy (which supersedes the active
    fact) and then the active fact's own copy (which restores it); the active fact must survive."""
    ops: list[tuple[Any, ...]] = [
        ("main", "S0", "red", 0, "retracted", True),
        ("gate", "canary-a", [("S0", "blue", 1, True)], [], True, None),
        ("gate", "canary-b", [("S1", "green", 0, True)], [], True, ("S0", False)),
        ("gate", "canary-c", [("S2", "amber", 0, True)], [], True, ("S0", True)),
    ]
    thin, _ = _run(ops, True, monkeypatch)
    full, _ = _run(ops, False, monkeypatch)
    assert not diff(full, thin)
    statuses = {row["object"]: row["status"] for row in thin["state"][TENANT]["assertions"]}
    assert statuses["blue"] == "active" and statuses["red"] == "retracted"
