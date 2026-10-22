"""Evidence metadata mutation races against real PostgreSQL transactions."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import PostgresEngine


@pytest.fixture(params=[True, False], ids=["pooled", "fresh"])
def metadata_engines(request):
    pytest.importorskip("psycopg")
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    first, second = PostgresEngine(dsn), PostgresEngine(dsn)
    first._conn_reuse = second._conn_reuse = request.param
    tenant = f"metadata-race-{uuid4().hex}"
    cid = first.append_evidence(Evidence(
        tenant_id=tenant, user_id="owner", actor="user", source_type="document",
        content="Evidence metadata updates must preserve independently written fields.",
        metadata={"original": "retained"},
    ))
    try:
        yield first, second, tenant, cid
    finally:
        first.close_connections()
        second.close_connections()


@pytest.mark.parametrize(("first_operation", "second_operation"), [
    ("metadata", "metadata"), ("privacy", "metadata"),
    ("metadata", "privacy"), ("privacy_strict", "privacy"),
])
def test_concurrent_metadata_patches_preserve_both_updates(
    metadata_engines, monkeypatch, first_operation, second_operation,
):
    first, second, tenant, cid = metadata_engines
    first_updated = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    pids = []
    second_pids = []
    real_audit = first._audit
    real_set_tenant = second._set_tenant

    def hold_first_transaction(cur, *args, **kwargs):
        real_audit(cur, *args, **kwargs)
        cur.execute("SELECT pg_backend_pid()")
        pids.append(cur.fetchone()["pg_backend_pid"])
        first_updated.set()
        if not release_first.wait(10):
            raise RuntimeError("test timed out waiting to release first metadata writer")

    monkeypatch.setattr(first, "_audit", hold_first_transaction)

    def identify_second_writer(cur, *args, **kwargs):
        real_set_tenant(cur, *args, **kwargs)
        cur.execute("SELECT pg_backend_pid()")
        second_pids.append(cur.fetchone()["pg_backend_pid"])
        second_started.set()

    monkeypatch.setattr(second, "_set_tenant", identify_second_writer)
    with ThreadPoolExecutor(max_workers=2) as executor:
        if first_operation.startswith("privacy"):
            one = executor.submit(
                first.backfill_evidence_privacy, tenant, cid, ["email"],
                pii_sensitivity=4 if first_operation == "privacy_strict" else 3,
            )
        else:
            one = executor.submit(first.update_evidence_metadata, tenant, cid, {"revision": 2})
        try:
            assert first_updated.wait(10), "first writer never reached its pending commit"
            if second_operation == "privacy":
                two = executor.submit(second.backfill_evidence_privacy, tenant, cid, ["email"])
            else:
                two = executor.submit(second.update_evidence_metadata, tenant, cid, {"indexed": True})
            assert second_started.wait(10), "second writer never started its transaction"
            # Observe the actual second transaction waiting on the first, rather
            # than relying on scheduling or a fixed delay. Before the fix it
            # waits in UPDATE after reading stale metadata; afterward its SELECT
            # waits and reads the newly committed metadata before merging.
            deadline = time.monotonic() + 10
            with first._psycopg.connect(first.dsn) as observer:
                while True:
                    blocked = observer.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE pid = %s AND %s = ANY(pg_blocking_pids(pid)))",
                        (second_pids[0], pids[0]),
                    ).fetchone()[0]
                    if blocked:
                        break
                    assert not two.done(), "second writer finished without the intended lock conflict"
                    assert time.monotonic() < deadline, "second writer did not wait for the first"
                    time.sleep(0.01)
        finally:
            release_first.set()
        assert one.result(timeout=10) is True
        assert two.result(timeout=10) is True
    evidence = first.get_evidence(tenant, cid)
    metadata = evidence.metadata
    assert metadata["original"] == "retained"
    if first_operation.startswith("privacy") or second_operation == "privacy":
        assert metadata["privacy"]["pii_tags"] == ["email"]
        assert metadata["privacy"]["backfilled"] is True
        assert evidence.sensitivity == (4 if first_operation == "privacy_strict" else 3)
    if first_operation == "metadata":
        assert metadata["revision"] == 2
    if second_operation == "metadata":
        assert metadata["indexed"] is True


def test_failed_metadata_audit_rolls_back_and_releases_row_lock(metadata_engines, monkeypatch):
    first, second, tenant, cid = metadata_engines

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected metadata audit failure")

    monkeypatch.setattr(first, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="injected metadata audit failure"):
        first.update_evidence_metadata(tenant, cid, {"revision": 2})
    assert "revision" not in second.get_evidence(tenant, cid).metadata
    assert second.update_evidence_metadata(tenant, cid, {"indexed": True}) is True
    assert second.get_evidence(tenant, cid).metadata["indexed"] is True


def test_metadata_patch_does_not_revive_erased_evidence(metadata_engines):
    first, second, tenant, cid = metadata_engines
    assert first.forget(tenant, cid)["erased"] is True
    assert second.update_evidence_metadata(tenant, cid, {"revision": 2}) is False
    assert second.get_evidence(tenant, cid) is None
