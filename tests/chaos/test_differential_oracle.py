"""Differential oracle (Phase-2 Task 11, spec §4.0/§8).

The strongest parity check in the suite: the SAME seeded workload is replayed
onto a ``LocalMemoryEngine`` (the canonical parity oracle) and a
``SqliteEngine``; their ``export_tenant`` / ``export_all`` outputs must be EQUAL
after normalising ONLY the documented deltas (see ``_chaos_harness.py`` for the
exhaustive, per-key rationale):

  1. branch ``created_at`` — ``isoformat`` (Local) vs ``dt_to_json`` ``Z`` (SQLite);
  2. engine-generated non-deterministic ids / wall-clock stamps
     (audit/deletion ``id``/``at``, ``transaction_time``, ``justification_id``, …),
     the same volatile set the shipped oracles (``test_sqlite_ledger``,
     ``test_sqlite_assertions``) scrub.

A THIRD documented difference is handled by workload SCOPING, not normalisation:
``SqliteEngine.branch`` regenerates assertion/relation ids on clone
(shipped/intentional — ``test_branch_keeps_evidence_cid_fresh_ids_for_assertions_relations``)
whereas ``LocalMemoryEngine`` preserves them; merge reinforcement matches on id,
so branching + merging assertions yields divergent (each internally-correct)
supersession outcomes no id-scrub can reconcile. The oracle therefore tests two
disjoint, well-defined slices (see ``_chaos_harness.build_workload``): slice A =
assertions/relations/forget on ``main`` (no branch/merge); slice B = evidence +
branch + merge + forget (cid-stable, no assertions). Together they cover every op.

If a seed diverges beyond that normalisation, it is a REAL SqliteEngine bug:
fix the engine and PIN the seed here (see ``PINNED_REGRESSION_SEEDS``). Ran clean
across ``SEEDS`` at authoring time — zero divergences.

Deletion-record non-deterministic ids (documented delta #2) get a dedicated test
below: hard-delete's HMAC deletion-record id is non-recomputable BY DESIGN
(spec §7 invariant 13), so it is normalised out, while the forget return dict
(which keeps real cids) stays byte-equal across engines.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _chaos_harness as H  # noqa: E402

from mnemosyne.engine import LocalMemoryEngine  # noqa: E402
from mnemosyne.models import Assertion, Evidence  # noqa: E402
from mnemosyne.privacy import ErasureMode  # noqa: E402
from mnemosyne.sqlite_engine import SqliteEngine  # noqa: E402

# >=25 seeds (spec gate). This range IS the ratchet corpus: any chaos-found
# divergence appends its seed to PINNED_REGRESSION_SEEDS so it runs forever.
SEEDS = list(range(40))
PINNED_REGRESSION_SEEDS: list[int] = []  # append seeds that once diverged (with a fix)
ALL_SEEDS = SEEDS + PINNED_REGRESSION_SEEDS


@pytest.mark.parametrize("seed", ALL_SEEDS)
def test_export_parity_assertions_main(tmp_path: Path, seed: int) -> None:
    """Slice A — assertions / relations / forget on ``main`` (no branch/merge).

    Exercises the full supersession / contest / reinforce / erasure-cascade matrix
    with deterministic pinned ids, so cross-engine equality is exact modulo the
    documented normalisation.
    """
    tenant = "t-oracle-a"
    ops = H.build_workload(seed, tenant=tenant, allow_branches=False, allow_assertions=True)

    local = LocalMemoryEngine()
    sqlite = SqliteEngine(tmp_path / "root")
    H.apply_workload(local, ops)
    H.apply_workload(sqlite, ops)

    local_export = local.export_tenant(tenant)
    sqlite_export = sqlite.export_tenant(tenant)

    # (a) full ledger equality modulo the documented normalisation.
    assert H.normalise_export(sqlite_export) == H.normalise_export(local_export), f"seed={seed}"

    # (b) targeted, UN-scrubbed projections re-validate the load-bearing content
    # the scrub drops (pinned ids, supersession outcome, content-addressed cids).
    assert H.assertion_identity(sqlite_export) == H.assertion_identity(local_export), f"seed={seed}"
    assert H.relation_identity(sqlite_export) == H.relation_identity(local_export), f"seed={seed}"
    assert H.evidence_identity(sqlite_export) == H.evidence_identity(local_export), f"seed={seed}"


@pytest.mark.parametrize("seed", ALL_SEEDS)
def test_export_parity_evidence_branches(tmp_path: Path, seed: int) -> None:
    """Slice B — evidence + branch + merge + forget (no assertions/relations).

    Evidence keeps its content-addressed cid across branches, so branch/merge/forget
    stay deterministic. Covers ``export_tenant`` AND ``export_all`` (policy, the
    branch ``created_at`` format delta, the tenants list, cross-branch collections).

    Single tenant on purpose: ``LocalMemoryEngine`` keys ``branches`` GLOBALLY by
    name, so two tenants sharing a scratch-branch name would alias ``from_branch``
    on Local but not on the per-tenant SQLite files — a Local quirk, not a SQLite
    bug. Multi-tenant isolation is proven by the honeytoken chaos test instead.
    """
    tenant = "t-oracle-b"
    ops = H.build_workload(seed, tenant=tenant, allow_branches=True, allow_assertions=False)

    local = LocalMemoryEngine()
    sqlite = SqliteEngine(tmp_path / "root")
    H.apply_workload(local, ops)
    H.apply_workload(sqlite, ops)

    assert H.normalise_export(sqlite.export_tenant(tenant)) == H.normalise_export(
        local.export_tenant(tenant)
    ), f"seed={seed}"
    assert H.evidence_identity(sqlite.export_tenant(tenant)) == H.evidence_identity(
        local.export_tenant(tenant)
    ), f"seed={seed}"
    assert H.normalise_export(sqlite.export_all()) == H.normalise_export(local.export_all()), f"seed={seed}"


def _sorted_propagated(propagated: dict) -> dict:
    return {k: (sorted(v) if isinstance(v, list) else v) for k, v in propagated.items()}


def test_hard_delete_deletion_record_id_is_documented_non_deterministic(tmp_path: Path) -> None:
    """Documented delta #2: the hard-delete deletion-record id is a fresh, discarded-key
    HMAC (spec §7 invariant 13) — non-recomputable and independent per engine, hence
    normalised out. The forget RETURN dict keeps real cids and stays byte-equal."""
    tenant = "t-hard"

    def _seed(engine) -> str:
        cid = engine.append_evidence(
            Evidence(tenant_id=tenant, user_id="u", actor="user", source_type="chat",
                     content="Orchid grounding fact for legal erasure.", access_policy={"tenant": tenant})
        )
        engine.upsert_assertion(
            Assertion(tenant_id=tenant, user_id="u", subject="orchid", predicate="is", object="rare",
                      confidence=0.9, status="active", source_evidence_cids=[cid], id="as-hard-1")
        )
        return cid

    local = LocalMemoryEngine()
    sqlite = SqliteEngine(tmp_path / "root")
    cl = _seed(local)
    cs = _seed(sqlite)
    assert cl == cs  # content-addressed cid identical across engines

    rl = local.forget(tenant, cl, requested_by="legal", erasure_mode=ErasureMode.HARD_DELETE_LEGAL)
    rs = sqlite.forget(tenant, cs, requested_by="legal", erasure_mode=ErasureMode.HARD_DELETE_LEGAL)

    # Return dict keeps REAL cids -> deterministic across engines.
    assert rs["erased"] == rl["erased"]
    assert rs["cid"] == rl["cid"]
    assert rs["erasure_mode"] == rl["erasure_mode"] == ErasureMode.HARD_DELETE_LEGAL.value
    assert _sorted_propagated(rs["propagated"]) == _sorted_propagated(rl["propagated"])

    ds = sqlite.export_tenant(tenant)["deletion_log"][-1]
    dl = local.export_tenant(tenant)["deletion_log"][-1]
    assert ds["erasure_mode"] == dl["erasure_mode"] == ErasureMode.HARD_DELETE_LEGAL.value
    # The retained deletion-record id (evidence_cid) is a 64-hex HMAC and DIFFERS
    # across the two engines — exactly why the oracle must normalise it, not compare it.
    assert len(ds["evidence_cid"]) == 64 and len(dl["evidence_cid"]) == 64
    assert ds["evidence_cid"] != dl["evidence_cid"]
    # The retained deletion record's ``propagated`` is also invariant-13 redacted
    # with a per-erasure, non-recomputable placeholder map (random per engine), so
    # it too is normalised out. After dropping the volatile id + evidence_cid +
    # propagated, the remaining scalar fields (tenant_id, requested_by, erasure_mode)
    # are equal — the only cross-engine deltas are the documented non-deterministic ids.
    extra = frozenset({"evidence_cid", "propagated"})
    assert H.normalise_export({"deletion_log": [ds]}, extra=extra) == H.normalise_export(
        {"deletion_log": [dl]}, extra=extra
    )


def test_workload_is_deterministic_by_seed() -> None:
    """Replay guard: the generator is a pure function of its seed."""
    a = H.build_workload(7, tenant="t")
    b = H.build_workload(7, tenant="t")
    c = H.build_workload(8, tenant="t")
    assert a == b
    assert a != c


def test_gate_env_marker_present() -> None:
    """Sanity: this file only runs under the MNEMOSYNE_CHAOS gate."""
    assert os.environ.get("MNEMOSYNE_CHAOS") == "1"
