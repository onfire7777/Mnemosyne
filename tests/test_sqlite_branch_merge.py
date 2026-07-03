"""Phase-2 Task 6 — SqliteEngine branch / merge / discard and the durable
``SqliteQueue`` lease lane, pinned against the ``LocalMemoryEngine`` parity
oracle and the ``InProcessQueue`` surface.

Coverage:

* the cross-engine merge parity shapes ``test_parity_merge_branch_into_main``
  asserts — ``evidence_added`` / ``assertions_added`` / ``assertions_merged`` /
  ``relations_added`` / ``conflicts == []`` / ``merged_on_main`` — plus the
  MergeReport POSITIONAL field order (from_branch, into_branch, evidence_added,
  assertions_added, assertions_merged, relations_added, conflicts);
* the replay-upsert reinforce path (same-object merge → ``assertions_merged``);
* branch isolation vs Local (branch writes never leak to main and vice versa;
  evidence keeps its cid across branches, assertions/relations get fresh ids);
* discard removes ONLY that branch (registry + rows), leaving main and siblings;
* a ``PromotionGate``-against-SqliteEngine smoke through ``.branches`` /
  ``_reset_branch``;
* ``SqliteQueue`` lease priority order + complete/fail/dead lifecycle +
  visibility (a leased job is never re-leased) parity vs ``InProcessQueue``, and
  a ``QueueWorker`` drain;
* the T3-review handoff: a real-tenant merge audit (never ``"*"``) reconstructs
  ``export_tenant``'s merge_log identically to Local and never bleeds across
  tenant files.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import PromotionGate
from mnemosyne.models import Assertion, Evidence, MergeReport, Relation
from mnemosyne.queue import InProcessQueue, QueueWorker, SqliteQueue
from mnemosyne.sqlite_engine import SqliteEngine

TENANT = "tenant-topaz"
USER = "analyst"


def _engines(tmp_path: Path) -> tuple[SqliteEngine, LocalMemoryEngine]:
    # Deterministic HashingEmbeddingProvider + default policy on both, so every
    # derived field (cid, reality class, embedding) is byte-identical.
    return SqliteEngine(tmp_path / "root"), LocalMemoryEngine()


def _evidence(tenant: str, content: str) -> Evidence:
    return Evidence(
        tenant_id=tenant,
        user_id=USER,
        actor="user",
        source_type="chat",
        content=content,
        access_policy={"tenant": tenant},
    )


def _assertion(tenant: str, *, subject: str, object: str, branch: str, cids: list[str], trust_tier: int = 1) -> Assertion:
    return Assertion(
        tenant_id=tenant,
        user_id=USER,
        branch=branch,
        subject=subject,
        predicate="is",
        object=object,
        confidence=0.9,
        trust_tier=trust_tier,
        source_evidence_cids=cids,
        access_policy={"tenant": tenant},
        status="active",
    )


def _relation(tenant: str, *, branch: str, cids: list[str]) -> Relation:
    return Relation(
        tenant_id=tenant,
        branch=branch,
        source="beacon",
        predicate="emits",
        target="topaz glow",
        source_evidence_cids=cids,
        access_policy={"tenant": tenant},
    )


def _merge_scenario(engine, tenant: str) -> tuple[MergeReport, bool]:
    """The ``test_parity_merge_branch_into_main`` scenario: branch off empty
    main, write one evidence/assertion/relation on the branch, merge into main."""
    engine.branch("cand", frm="main", tenant_id=tenant)
    cid = engine.append_evidence(
        _evidence(tenant, "Branch merge evidence about the topaz beacon."), branch="cand"
    )
    engine.upsert_assertion(
        _assertion(tenant, subject="beacon", object="topaz", branch="cand", cids=[cid]), branch="cand"
    )
    engine.add_relation(_relation(tenant, branch="cand", cids=[cid]), branch="cand")
    report = engine.merge("cand", into="main", tenant_id=tenant)
    merged_on_main = engine.get_evidence(tenant, cid, branch="main") is not None
    return report, merged_on_main


# --- merge parity ------------------------------------------------------------


def test_merge_branch_into_main_shapes(tmp_path: Path) -> None:
    sqlite_engine, local = _engines(tmp_path)
    s_report, s_merged = _merge_scenario(sqlite_engine, TENANT)
    oracle_report, oracle_merged = _merge_scenario(local, TENANT)

    # The exact shapes test_parity_merge_branch_into_main asserts.
    assert s_report.evidence_added == 1
    assert s_report.assertions_added == 1
    assert s_report.assertions_merged == 0
    assert s_report.relations_added == 1
    assert s_report.conflicts == []
    assert s_report.from_branch == "cand"
    assert s_report.into_branch == "main"
    assert s_merged is True

    # Cross-engine: the whole MergeReport dict matches the Local oracle.
    assert s_report.to_dict() == oracle_report.to_dict()
    assert s_merged == oracle_merged


def test_merge_report_field_order_is_positional() -> None:
    # R1: MergeReport(frm, into, evidence_added, assertions_added,
    # assertions_merged, relations_added, conflicts) — positional field order.
    report = MergeReport("frm", "into", 1, 2, 3, 4, [])
    assert report.from_branch == "frm"
    assert report.into_branch == "into"
    assert report.evidence_added == 1
    assert report.assertions_added == 2
    assert report.assertions_merged == 3
    assert report.relations_added == 4
    assert report.conflicts == []
    assert list(report.to_dict()) == [
        "from_branch",
        "into_branch",
        "evidence_added",
        "assertions_added",
        "assertions_merged",
        "relations_added",
        "conflicts",
    ]


def test_merge_same_object_reinforces_as_merged(tmp_path: Path) -> None:
    # Replay-upsert semantics: a branch assertion whose (subject, predicate,
    # object) already exists active on main reinforces (no new row) → counts as
    # assertions_merged, not assertions_added — identical to Local.
    def scenario(engine, tenant):
        cid = engine.append_evidence(_evidence(tenant, "Main note about the beacon."))
        engine.upsert_assertion(_assertion(tenant, subject="beacon", object="topaz", branch="main", cids=[cid]))
        engine.branch("cand", frm="main", tenant_id=tenant)
        return engine.merge("cand", into="main", tenant_id=tenant)

    sqlite_engine, local = _engines(tmp_path)
    s = scenario(sqlite_engine, TENANT)
    oracle = scenario(local, TENANT)
    assert s.assertions_merged == 1
    assert s.assertions_added == 0
    assert s.to_dict() == oracle.to_dict()


# --- branch isolation --------------------------------------------------------


def test_branch_isolation_vs_local(tmp_path: Path) -> None:
    def observe(engine, tenant):
        base = engine.append_evidence(_evidence(tenant, "Shared base note on main."))
        engine.branch("cand", frm="main", tenant_id=tenant)
        cand_only = engine.append_evidence(_evidence(tenant, "Candidate-only note."), branch="cand")
        main_only = engine.append_evidence(_evidence(tenant, "Main-only note."))
        return {
            "base_on_main": engine.get_evidence(tenant, base, branch="main") is not None,
            "base_on_cand": engine.get_evidence(tenant, base, branch="cand") is not None,
            "cand_only_on_cand": engine.get_evidence(tenant, cand_only, branch="cand") is not None,
            "cand_only_leaked_to_main": engine.get_evidence(tenant, cand_only, branch="main") is not None,
            "main_only_on_main": engine.get_evidence(tenant, main_only, branch="main") is not None,
            "main_only_leaked_to_cand": engine.get_evidence(tenant, main_only, branch="cand") is not None,
        }

    sqlite_engine, local = _engines(tmp_path)
    s = observe(sqlite_engine, TENANT)
    oracle = observe(local, TENANT)
    assert s == oracle
    # Concrete isolation guarantees (the shape parity above pins them to Local).
    assert s["base_on_cand"] is True  # copied at branch time
    assert s["cand_only_on_cand"] is True
    assert s["cand_only_leaked_to_main"] is False
    assert s["main_only_on_main"] is True
    assert s["main_only_leaked_to_cand"] is False


def test_branch_keeps_evidence_cid_fresh_ids_for_assertions_relations(tmp_path: Path) -> None:
    sqlite_engine, _ = _engines(tmp_path)
    cid = sqlite_engine.append_evidence(_evidence(TENANT, "Main note about the beacon."))
    sqlite_engine.upsert_assertion(
        _assertion(TENANT, subject="beacon", object="topaz", branch="main", cids=[cid])
    )
    sqlite_engine.add_relation(_relation(TENANT, branch="main", cids=[cid]))
    sqlite_engine.branch("cand", frm="main", tenant_id=TENANT)

    export = sqlite_engine.export_tenant(TENANT)
    ev_by_branch = {(e["branch"], e["cid"]) for e in export["evidence"]}
    # evidence keeps its cid across branches (same cid on main and cand).
    assert ("main", cid) in ev_by_branch
    assert ("cand", cid) in ev_by_branch

    a_main = {a["id"] for a in export["assertions"] if a["branch"] == "main"}
    a_cand = {a["id"] for a in export["assertions"] if a["branch"] == "cand"}
    r_main = {r["id"] for r in export["relations"] if r["branch"] == "main"}
    r_cand = {r["id"] for r in export["relations"] if r["branch"] == "cand"}
    assert a_main and a_cand and a_main.isdisjoint(a_cand)  # fresh uuid4 ids
    assert r_main and r_cand and r_main.isdisjoint(r_cand)


def test_branch_is_idempotent(tmp_path: Path) -> None:
    sqlite_engine, _ = _engines(tmp_path)
    sqlite_engine.append_evidence(_evidence(TENANT, "Main note."))
    sqlite_engine.branch("cand", frm="main", tenant_id=TENANT)
    before = sqlite_engine.export_tenant(TENANT)
    sqlite_engine.branch("cand", frm="main", tenant_id=TENANT)  # no-op
    sqlite_engine.branch("main", frm="main", tenant_id=TENANT)  # name == frm no-op
    after = sqlite_engine.export_tenant(TENANT)
    assert len(before["evidence"]) == len(after["evidence"])
    assert sorted(sqlite_engine.branches) == ["cand", "main"]


# --- discard -----------------------------------------------------------------


def test_discard_removes_only_that_branch(tmp_path: Path) -> None:
    def observe(engine, tenant):
        cid = engine.append_evidence(_evidence(tenant, "Base note on main."))
        engine.branch("b1", frm="main", tenant_id=tenant)
        engine.branch("b2", frm="main", tenant_id=tenant)
        b1_cid = engine.append_evidence(_evidence(tenant, "b1-only note."), branch="b1")
        b2_cid = engine.append_evidence(_evidence(tenant, "b2-only note."), branch="b2")
        engine.discard("b1", tenant_id=tenant)
        return {
            "b1_gone": engine.get_evidence(tenant, b1_cid, branch="b1") is None,
            "b2_intact": engine.get_evidence(tenant, b2_cid, branch="b2") is not None,
            "main_intact": engine.get_evidence(tenant, cid, branch="main") is not None,
            "branches": sorted(getattr(engine, "branches", {})),
        }

    sqlite_engine, local = _engines(tmp_path)
    s = observe(sqlite_engine, TENANT)
    oracle = observe(local, TENANT)
    assert s == oracle
    assert s["b1_gone"] is True
    assert s["b2_intact"] is True
    assert s["main_intact"] is True
    assert s["branches"] == ["b2", "main"]


def test_branch_merge_discard_require_tenant_and_guard_main(tmp_path: Path) -> None:
    sqlite_engine, _ = _engines(tmp_path)
    with pytest.raises(ValueError, match="requires tenant_id"):
        sqlite_engine.branch("cand", tenant_id="")
    with pytest.raises(ValueError, match="requires tenant_id"):
        sqlite_engine.merge("cand", into="main", tenant_id=None)
    with pytest.raises(ValueError, match="requires tenant_id"):
        sqlite_engine.discard("cand", tenant_id="")
    with pytest.raises(ValueError, match="main branch cannot be discarded"):
        sqlite_engine.discard("main", tenant_id=TENANT)
    with pytest.raises(ValueError, match="unknown branch"):
        sqlite_engine.branch("cand", frm="ghost", tenant_id=TENANT)


# --- PromotionGate smoke -----------------------------------------------------


def test_promotion_gate_reset_branch_smoke(tmp_path: Path) -> None:
    sqlite_engine, _ = _engines(tmp_path)
    sqlite_engine.append_evidence(_evidence(TENANT, "Base note."))
    sqlite_engine.branch("cand", frm="main", tenant_id=TENANT)

    # .branches is dict-shaped exactly like LocalMemoryEngine's registry.
    branches = sqlite_engine.branches
    assert isinstance(branches, dict)
    assert set(branches["cand"]) == {"from", "kind", "created_at"}
    assert branches["cand"]["from"] == "main"

    gate = PromotionGate(sqlite_engine, cases=[])
    assert "cand" in sqlite_engine.branches
    gate._reset_branch("cand", TENANT)  # dict path → discards the stale branch
    assert "cand" not in sqlite_engine.branches
    # _reset_branch on an absent branch is a no-op (does not raise).
    gate._reset_branch("cand", TENANT)


# --- SqliteQueue lifecycle parity vs InProcessQueue --------------------------


def test_sqlite_queue_lease_priority_order_matches_inprocess(tmp_path: Path) -> None:
    priorities = [
        {"write_priority": {"effective_score": 0.2}},
        {"write_priority": {"effective_score": 0.9}},
        {"write_priority": {"score": 0.5}},
        {"other": "no-priority"},  # → 0.0
    ]

    def lease_order(queue):
        for payload in priorities:
            queue.enqueue("job", payload)
        seen = []
        while (job := queue.lease()) is not None:
            seen.append(_priority(job))
        return seen

    sqlite_queue = SqliteQueue(tmp_path / "q", "qt")
    inproc = InProcessQueue()
    sqlite_order = lease_order(sqlite_queue)
    inproc_order = lease_order(inproc)
    assert sqlite_order == inproc_order
    assert sqlite_order == [0.9, 0.5, 0.2, 0.0]  # strictly priority-desc


def _priority(job) -> float:
    wp = job.payload.get("write_priority") or {}
    return float(wp.get("effective_score", wp.get("score", 0.0)))


def test_sqlite_queue_visibility_and_lifecycle_parity(tmp_path: Path) -> None:
    def run(queue):
        job = queue.enqueue("job", {}, max_attempts=2)
        first = queue.lease()
        # Visibility: the leased job is 'running' and is NOT handed out again.
        assert first.id == job.id
        assert first.status == "running"
        assert first.attempts == 1
        assert queue.lease() is None
        queue.fail(job.id, "boom")  # attempts(1) < max(2) → retry, re-leasable
        after_first_fail = queue.snapshot()
        second = queue.lease()
        assert second.id == job.id
        assert second.attempts == 2
        queue.fail(job.id, "boom again")  # attempts(2) >= max(2) → dead
        # A second job that completes cleanly in the same queue.
        queue.enqueue("job", {})
        leased = queue.lease()
        queue.complete(leased.id)
        return after_first_fail, queue.snapshot()

    sqlite_queue = SqliteQueue(tmp_path / "q", "qt")
    inproc = InProcessQueue()
    s_retry, s_final = run(sqlite_queue)
    i_retry, i_final = run(inproc)
    assert s_retry == i_retry == {"retry": 1}
    assert s_final == i_final == {"dead": 1, "complete": 1}


def test_sqlite_queue_worker_drains_with_result(tmp_path: Path) -> None:
    queue = SqliteQueue(tmp_path / "q", "qt")
    queue.enqueue("echo", {"x": 7})
    worker = QueueWorker(queue, {"echo": lambda payload: {"echoed": payload["x"]}})
    drained = worker.drain(limit=5)
    assert [job.kind for job in drained] == ["echo"]
    assert drained[0].status == "complete"
    assert drained[0].result == {"echoed": 7}
    assert queue.snapshot() == {"complete": 1}
    # jobs property + list_jobs surface the durable row.
    assert set(queue.jobs) == {drained[0].id}
    assert queue.list_jobs()[0].result == {"echoed": 7}


def test_sqlite_queue_no_handler_fails_job(tmp_path: Path) -> None:
    def run(queue):
        queue.enqueue("mystery", {})
        worker = QueueWorker(queue, {})
        job = worker.run_once()  # no handler → single fail; attempts(1) < 3 → retry
        return job.status, queue.snapshot()

    sqlite_status, sqlite_snap = run(SqliteQueue(tmp_path / "q", "qt"))
    inproc_status, inproc_snap = run(InProcessQueue())
    assert sqlite_snap == inproc_snap == {"retry": 1}
    assert sqlite_status == inproc_status


# --- T3-review handoff: "*"-tenant merge audit does not diverge exports -------


def test_star_tenant_merge_audit_export_no_divergence(tmp_path: Path) -> None:
    def merge_on(engine, tenant):
        _merge_scenario(engine, tenant)

    sqlite_engine, local = _engines(tmp_path)
    merge_on(sqlite_engine, "tenant-A")
    merge_on(local, "tenant-A")
    # A second tenant with NO merges must reconstruct an EMPTY merge_log — the
    # export_tenant filter admits audits whose tenant_id ∈ {tenant, "*"}, and a
    # real-tenant merge audit (never "*") must not bleed into tenant-B.
    sqlite_engine.append_evidence(_evidence("tenant-B", "B has no merges."))
    local.append_evidence(_evidence("tenant-B", "B has no merges."))

    a_sqlite = sqlite_engine.export_tenant("tenant-A")
    a_local = local.export_tenant("tenant-A")
    assert a_sqlite["merge_log"] == a_local["merge_log"]
    assert len(a_sqlite["merge_log"]) == 1

    # The merge audit is recorded under the REAL tenant, not "*".
    merge_audits = [row for row in a_sqlite["audit_log"] if row.get("op") == "merge"]
    assert merge_audits and all(row["tenant_id"] == "tenant-A" for row in merge_audits)

    assert sqlite_engine.export_tenant("tenant-B")["merge_log"] == []
    assert local.export_tenant("tenant-B")["merge_log"] == []
