"""Source erasure removes project payloads from retained audit snapshots."""
import json
import os
from copy import deepcopy
from uuid import uuid4

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.erasure_ids import redact_source_audit_payload
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite", "postgres"])
def engine(request, tmp_path):
    if request.param == "local":
        store = LocalMemoryEngine()
    elif request.param == "sqlite":
        store = SqliteEngine(tmp_path / "memory")
    else:
        dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
        if not dsn:
            pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
        pytest.importorskip("psycopg")
        from mnemosyne.postgres_engine import PostgresEngine
        store = PostgresEngine(dsn)
    yield store
    if request.param == "postgres":
        store.close_connections()
    else:
        store.close()


@pytest.mark.parametrize("mode", ["tombstone_recompute", "hard_delete_legal"])
def test_observed_project_output_erased_from_audit_and_learning_copies(engine, mode):
    tenant = "audit-erasure-" + uuid4().hex
    marker = "erasure_probe_value"
    runtime = LearningRuntime(engine)
    observed = runtime.observe_turn(tenant, "owner", "session", "Inspect project configuration", "",
        tool_events=[{"name": "shell", "source": "tool", "command": "cat config.json", "cwd": "/work",
                      "call_id": "read-config", "check_id": "config", "exit_code": 0,
                      "output": json.dumps({"setting": marker}),
                      "experiment_environment": {"version": 1, "kind": "python", "files": {"config.py": marker}}}])
    before = engine.export_tenant(tenant)
    source = next(row for row in before["evidence"] if row["actor"] == "tool")
    assert marker in json.dumps(before)
    projections = [row for row in before["assertions"] if marker in json.dumps(row)]
    assert projections, "The runtime must actually form the observed project claim"
    projection_ids = {row["id"] for row in projections}
    audits = [row for row in before["audit_log"] if row.get("target_id") in projection_ids]
    assert audits
    result = engine.forget(tenant, source["cid"], requested_by="legal", erasure_mode=mode)
    assert result["erased"]
    after = engine.export_tenant(tenant)
    assert marker not in json.dumps(after)
    state = runtime.writer.read(tenant)
    assert marker not in json.dumps(state)
    assert state["episodes"][observed["episode_id"]]["status"] == "erased"
    for prior in audits:
        retained = next(row for row in after["audit_log"] if row["id"] == prior["id"])
        assert retained["op"] == prior["op"]
        assert retained["target_id"] == prior["target_id"]
        assert retained["diff"]["source_payload_erased"] is True


def test_audit_scrub_handles_nested_reinforcement_and_preserves_unrelated_branch():
    snapshot = {"before": {"calibration": {"verification_contract": {"source_cid": "deleted", "object": "private"}}},
                "after": {"statement": "private"}, "branch": "main", "source": "assertion"}
    original = deepcopy(snapshot)
    assert redact_source_audit_payload(snapshot, {"deleted"}) == {"source_payload_erased": True}
    assert snapshot == original
    assert redact_source_audit_payload(snapshot, {"unrelated"}) == snapshot
    assert redact_source_audit_payload({**snapshot, "branch": "other"}, {"deleted"}) == {**snapshot, "branch": "other"}
    assert redact_source_audit_payload({"statement": "legacy"}, {"deleted"}, target_affected=True) == {
        "source_payload_erased": True}


def test_an_erasure_on_a_second_branch_keeps_the_first_branchs_report(engine):
    """A forget's own audit row is its custody report; the next branch must not wipe it."""
    from mnemosyne.models import Assertion, Evidence

    tenant = "audit-erasure-" + uuid4().hex
    cid = engine.append_evidence(Evidence(
        tenant_id=tenant, user_id="owner", actor="user", source_type="note",
        content="The archive opens on Mondays.", access_policy={"tenant": tenant}))
    engine.upsert_assertion(Assertion(
        tenant_id=tenant, subject="archive", predicate="opens", object="Mondays", status="active",
        source_evidence_cids=[cid], access_policy={"tenant": tenant}))
    engine.branch("review", frm="main", tenant_id=tenant)
    assert engine.forget(tenant, cid, requested_by="owner", branch="main")["erased"]
    first = next(row for row in engine.export_tenant(tenant)["audit_log"] if row["op"] == "forget")
    assert first["diff"]["retracted_assertions"]
    assert engine.forget(tenant, cid, requested_by="owner", branch="review")["erased"]
    reports = [row for row in engine.export_tenant(tenant)["audit_log"] if row["op"] == "forget"]
    assert len(reports) == 2
    assert reports[0]["diff"] == first["diff"]
    assert all(row["diff"]["retracted_assertions"] for row in reports)
