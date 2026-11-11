"""A SQLite assertion write reads its own group, and must write what a whole-branch read writes.

``SqliteEngine.upsert_assertion`` runs the in-memory engine's upsert over an oracle hydrated from
SQL. Hydrating the tenant's whole branch made every write cost the size of the store. The oracle
now holds only what one upsert can read or write: the current facts of the incoming fact's group
(same subject and semantic predicate), a row already stored under its id, the evidence those
facts cite and, when there is a fact to supersede, the relations named after the subject.

Each case drives two stores through the same seeded writes. One hydrates the scoped oracle, the
other the whole branch (the reference). Their exports must be equal apart from wall-clock stamps
and generated ids. The mix spells attributes several ways, gives facts different owners and
scopes, re-upserts stored ids (also under another subject), names explicit replacement targets,
cites missing evidence and keeps relations whose source differs from the subject only in case
or padding, which the supersession sync still closes.
"""

from __future__ import annotations

import random
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from mnemosyne.models import Assertion, Evidence, Relation, parse_dt
from mnemosyne.sqlite_engine import SqliteEngine

TENANT = "scope-prop"
START = parse_dt("2026-01-01T00:00:00Z")
SUBJECTS = ["S0", "S1", "S2"]
PREDICATES = ["lives_in", "residence", "resides_in", "likes", "like", "does_not_like", "is", "owns"]
OBJECTS = ["red", "blue", "green"]
VOLATILE = {"transaction_time", "last_accessed", "justification_id", "at", "created_at", "recorded_at"}


class WholeBranchOracle(SqliteEngine):
    """The reference: every upsert hydrates the tenant's whole branch."""

    def _assertion_oracle(self, conn, tenant_id, branch, incoming=None):  # type: ignore[override]
        return super()._assertion_oracle(conn, tenant_id, branch)


def _scrub(value: Any, *, audit: bool = False) -> Any:
    if isinstance(value, dict):
        return {key: _scrub(item, audit=audit or key == "audit_log") for key, item in value.items()
                if key not in VOLATILE and not (audit and key == "id")}
    if isinstance(value, list):
        return [_scrub(item, audit=audit) for item in value]
    return value


def _drive(engine: SqliteEngine, seed: int) -> tuple[list[Any], dict[str, Any]]:
    rng = random.Random(seed)
    cids = [
        engine.append_evidence(Evidence(
            tenant_id=TENANT, user_id="u1", actor=actor, source_type="chat", content=f"source {index}",
            metadata={"reality_class": reality}, trust_tier=tier, access_policy={"tenant": TENANT},
            created_at=START,
        ))
        for index, (actor, reality, tier) in enumerate([
            ("user", "grounded", 0), ("user", "grounded", 1), ("assistant", "self_generated", 5),
            ("tool", "external", 3), ("user", "simulated", 2),
        ])
    ] + ["missing-evidence"]
    for index in range(rng.randint(4, 10)):
        subject = rng.choice(SUBJECTS)
        engine.add_relation(Relation(
            id=f"r{index}", tenant_id=TENANT,
            source=rng.choice([subject, subject.lower(), f" {subject} "]),
            predicate=rng.choice(PREDICATES), target=rng.choice(OBJECTS + ["RED "]),
            valid_from=START, source_evidence_cids=rng.sample(cids[:5], rng.randint(0, 2)),
        ))
    outcomes: list[Any] = []
    stored: list[str] = []
    for index in range(rng.randint(30, 60)):
        reuse = stored and rng.random() < 0.15
        calibration: dict[str, Any] = {}
        if stored and rng.random() < 0.1:
            calibration["replaces_assertion_id"] = rng.choice(stored)
        fact = Assertion(
            id=rng.choice(stored) if reuse else f"a{index}",
            tenant_id=TENANT, user_id=rng.choice([None, None, "u1", "u2"]),
            subject=rng.choice(SUBJECTS), predicate=rng.choice(PREDICATES), object=rng.choice(OBJECTS),
            scope=rng.choice([{}, {}, {"workspace": "/w"}]), calibration=calibration,
            confidence=rng.choice([0.5, 0.7, 0.9]), trust_tier=rng.randint(0, 2),
            status=(status := rng.choice(["active", "active", "candidate", "contested", "retracted", "superseded"])),
            valid_from=START + timedelta(days=rng.randint(0, 6)),
            valid_to=START + timedelta(days=rng.randint(1, 8)) if status == "superseded" and rng.random() < 0.7 else None,
            source_evidence_cids=rng.sample(cids, rng.randint(0, 3)), access_policy={"tenant": TENANT},
        )
        try:
            outcomes.append(engine.upsert_assertion(fact))
            if fact.id not in stored:
                stored.append(fact.id)
        except ValueError as error:
            outcomes.append(str(error))
    return outcomes, _scrub(engine.export_tenant(TENANT))


@pytest.mark.parametrize("seed", range(30))
def test_scoped_upsert_writes_exactly_what_a_whole_branch_read_writes(seed: int, tmp_path: Path) -> None:
    scoped = SqliteEngine(tmp_path / "scoped")
    reference = WholeBranchOracle(tmp_path / "reference")
    try:
        outcomes, export = _drive(scoped, seed)
        expected_outcomes, expected = _drive(reference, seed)
    finally:
        scoped.close()
        reference.close()
    assert outcomes == expected_outcomes
    assert any(row["status"] == "superseded" for row in expected["assertions"]), "the mix must supersede"
    for name in expected:
        assert export[name] == expected[name], f"seed {seed}: {name} differs from the whole-branch reference"


def test_a_write_does_not_read_the_rest_of_the_store(tmp_path: Path) -> None:
    """One subject with many attributes: the cost of a write must not follow the store's size."""
    engine = SqliteEngine(tmp_path / "store")

    def write(count: int, offset: int) -> float:
        started = time.perf_counter()
        for index in range(offset, offset + count):
            engine.upsert_assertion(Assertion(
                tenant_id=TENANT, user_id="u1", subject="Atlas", predicate=f"configuration.key_{index}",
                object=str(index), status="active", valid_from=START, access_policy={"tenant": TENANT},
            ))
        return time.perf_counter() - started

    try:
        first = write(150, 0)
        write(1500, 150)
        last = write(150, 1650)
    finally:
        engine.close()
    # Whole-branch hydration made the last batch about eleven times the first.
    assert last < first * 4
