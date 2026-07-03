"""DST / chaos fault-injection for SqliteEngine (Phase-2 Task 11, spec §4.0/§8).

Fault classes:
  (i)   torn journal writes (byte truncation) — reuses the ``test_journal_properties``
        tear pattern; asserts records()/verify_against recover a torn TAIL, mid-file
        corruption RAISES, and repair-before-append (Task 9) lets a later append succeed.
  (ii)  kill -9 mid-transaction — a subprocess runs a scripted op sequence, is SIGKILLed
        while an explicit write transaction is open; on reopen the tenant file passes
        ``PRAGMA integrity_check`` (WAL rolls the uncommitted txn back — no partial row)
        and ledger ≡ journal (torn-tail aware).
  (iii) projection resilience — a corrupted/deleted projection sidecar triggers
        rebuild-on-mismatch (fingerprint mismatch → rebuild, never silent stale).
  (iv)  honeytoken cross-tenant isolation UNDER the chaos workload — tenant-A's leak
        canaries never surface in tenant-B's db / journal / projection artifacts.

Plus LANE INVARIANTS (Phase-0 deferral): cheap predicates over the ledger + audit
log — (a) append-only-ness / cid immutability, (b) a contested item is never
improperly closed. Scope is documented inline. Chaos-found failures ratchet into
``PINNED_REGRESSION_SEEDS``.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _chaos_harness as H  # noqa: E402

from mnemosyne.consolidation import ROLE_NAMES  # noqa: E402
from mnemosyne.journal import CIDJournal, journal_filename, safe_tenant_filename  # noqa: E402
from mnemosyne.models import Assertion, Evidence, parse_dt  # noqa: E402
from mnemosyne.sqlite_engine import SqliteEngine  # noqa: E402
from mnemosyne.honeytokens import honeytoken, scan_for_foreign_honeytokens  # noqa: E402

SEEDS = list(range(30))
PINNED_REGRESSION_SEEDS: list[int] = []  # append seeds that once failed (with a fix)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _ev(tenant: str, content: str, **over) -> Evidence:
    base = dict(
        tenant_id=tenant, user_id="u", actor="user", source_type="chat",
        content=content, trust_tier=1, access_policy={"tenant": tenant},
    )
    base.update(over)
    return Evidence(**base)


def _all_evidence_cids(engine: SqliteEngine, tenant: str) -> set[str]:
    """Every ledger cid for the tenant across all branches (tombstoned rows kept)."""
    conn = engine._connect(tenant)
    return {row["cid"] for row in conn.execute("SELECT cid FROM evidence WHERE tenant_id = ?", (tenant,))}


# --------------------------------------------------------------------------- #
# (i) torn journal writes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("seed", SEEDS + PINNED_REGRESSION_SEEDS)
def test_torn_journal_tail_recovers_and_repair_before_append(tmp_path: Path, seed: int) -> None:
    import random

    rng = random.Random(seed)
    root = tmp_path / "root"
    jdir = tmp_path / "journal"
    tenant = "t-torn"
    engine = SqliteEngine(root, journal_dir=jdir)

    n = rng.randint(3, 8)
    cids = [engine.append_evidence(_ev(tenant, f"torn-{seed}-{i} record about the beacon")) for i in range(n)]

    jpath = jdir / journal_filename(tenant)
    body = jpath.read_bytes()
    assert body.endswith(b"\n")
    lines = body[:-1].split(b"\n")
    assert len(lines) == n

    # Tear the FINAL line at an arbitrary mid-line byte offset (unfsynced crash torn tail).
    last = lines[-1]
    cut = 1 + (rng.randrange(len(last) - 1) if len(last) > 1 else 0)
    torn = b"\n".join(lines[:-1])
    if lines[:-1]:
        torn += b"\n"
    torn += last[:cut]  # no trailing newline -> torn tail
    jpath.write_bytes(torn)

    j = CIDJournal(jpath)
    # records() yields the intact prefix; the torn record is dropped, not corrupted.
    assert [r["cid"] for r in j.records()] == cids[:-1]
    div = j.verify_against(set(cids))
    assert div.torn_tail is True
    assert div.missing_from_journal == [cids[-1]]
    assert div.journal_only == []
    assert div.diverged

    # repair-before-append (Task 9): a later append truncates the torn fragment,
    # then appends cleanly — the torn tail can never wedge subsequent writes.
    new_cid = engine.append_evidence(_ev(tenant, f"torn-{seed}-post repair record"))
    after = [r["cid"] for r in CIDJournal(jpath).records()]
    assert after[:-1] == cids[:-1]
    assert after[-1] == new_cid

    # Ledger stays authoritative: the DB row for the torn cid survived its commit,
    # so ledger ≡ journal except the torn (never re-journaled) cid.
    ledger = _all_evidence_cids(engine, tenant)
    div2 = CIDJournal(jpath).verify_against(ledger)
    assert div2.torn_tail is False
    assert div2.journal_only == []
    assert div2.missing_from_journal == [cids[-1]]


def test_mid_file_journal_corruption_raises(tmp_path: Path) -> None:
    root = tmp_path / "root"
    jdir = tmp_path / "journal"
    tenant = "t-midcorrupt"
    engine = SqliteEngine(root, journal_dir=jdir)
    for i in range(4):
        engine.append_evidence(_ev(tenant, f"mid-{i} record"))

    jpath = jdir / journal_filename(tenant)
    lines = jpath.read_bytes()[:-1].split(b"\n")
    lines[1] = b'{"cid": "broken'  # invalid JSON on a NON-final line == real corruption
    jpath.write_bytes(b"\n".join(lines) + b"\n")

    with pytest.raises(json.JSONDecodeError):
        list(CIDJournal(jpath).records())


# --------------------------------------------------------------------------- #
# (ii) kill -9 mid-transaction
# --------------------------------------------------------------------------- #
_KILL_WORKER = r'''
import os, sys, time
root, jdir, tenant, n, sentinel = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
from mnemosyne.sqlite_engine import SqliteEngine
from mnemosyne.models import Evidence
eng = SqliteEngine(root, journal_dir=jdir)
for i in range(n):
    eng.append_evidence(
        Evidence(tenant_id=tenant, user_id="u", actor="user", source_type="chat",
                 content="kill-%d record" % i, trust_tier=1, access_policy={"tenant": tenant}),
        branch="main",
    )
# Open an explicit write transaction and leave it UNCOMMITTED, then advertise
# that we are mid-transaction. WAL must discard this on SIGKILL (no partial row).
conn = eng._connect(tenant)
conn.isolation_level = None
conn.execute("BEGIN IMMEDIATE")
conn.execute("UPDATE evidence SET trust_tier = trust_tier + 7")
with open(sentinel, "w") as fh:
    fh.write("mid-txn"); fh.flush(); os.fsync(fh.fileno())
while True:
    time.sleep(0.05)
'''


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_kill9_mid_transaction_rolls_back_and_ledger_equals_journal(tmp_path: Path, seed: int) -> None:
    import random

    rng = random.Random(seed)
    root = tmp_path / "root"
    jdir = tmp_path / "journal"
    tenant = "t-kill"
    n = rng.randint(3, 9)
    sentinel = tmp_path / "sentinel"

    proc = subprocess.Popen(
        [sys.executable, "-c", _KILL_WORKER, str(root), str(jdir), tenant, str(n), str(sentinel)],
        cwd=str(_REPO_ROOT),
        env=os.environ.copy(),
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if sentinel.exists():
                break
            if proc.poll() is not None:  # child died before reaching mid-txn
                err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
                pytest.fail(f"kill worker exited early (rc={proc.returncode}):\n{err}")
            time.sleep(0.05)
        else:
            pytest.fail("kill worker never reached the mid-transaction sentinel")
        os.kill(proc.pid, signal.SIGKILL)
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    # Reopen the tenant file in a FRESH engine (WAL recovery on connect).
    engine = SqliteEngine(root, journal_dir=jdir)
    conn = engine._connect(tenant)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    # The n committed appends survived; the uncommitted UPDATE rolled back cleanly
    # (every trust_tier is the appended value 1, never 8 => no partial row).
    rows = conn.execute("SELECT trust_tier FROM evidence WHERE tenant_id = ?", (tenant,)).fetchall()
    assert len(rows) == n
    assert all(row["trust_tier"] == 1 for row in rows)

    # ledger ≡ journal (torn-tail aware): journaling happens AFTER each commit and
    # before the manual txn, so both hold exactly the n committed cids.
    ledger = _all_evidence_cids(engine, tenant)
    div = CIDJournal(jdir / journal_filename(tenant)).verify_against(ledger)
    assert not div.diverged, (div.missing_from_journal, div.journal_only, div.torn_tail)
    assert len(ledger) == n


# --------------------------------------------------------------------------- #
# (iii) projection resilience — rebuild-on-mismatch, never silent stale
# --------------------------------------------------------------------------- #
def _seed_projection_state(engine: SqliteEngine, tenant: str) -> None:
    from mnemosyne.models import Relation

    c1 = engine.append_evidence(_ev(tenant, "proj alpha grounding about the orchid"))
    c2 = engine.append_evidence(_ev(tenant, "proj beta grounding about the harbor"))
    engine.add_relation(
        Relation(tenant_id=tenant, source="orchid", predicate="near", target="harbor",
                 source_evidence_cids=[c1, c2], access_policy={"tenant": tenant}, id="rel-proj-1")
    )


def test_projection_sidecar_corruption_and_deletion_trigger_rebuild(tmp_path: Path) -> None:
    root = tmp_path / "root"
    tenant = "t-proj"
    engine = SqliteEngine(root)
    _seed_projection_state(engine, tenant)

    first = engine.ensure_projections(tenant)
    assert first["cached-ppr"] is True and first["evidence-fts"] is True  # first-ever build
    assert engine.ensure_projections(tenant)["evidence-fts"] is False  # control: no silent rebuild

    proj_path = root / safe_tenant_filename(tenant, ".proj") / "projections.json"
    assert proj_path.exists()

    # (a) CORRUPT: valid JSON, WRONG fingerprint -> mismatch -> rebuild (not stale).
    stored = json.loads(proj_path.read_text(encoding="utf-8"))
    for name in stored:
        stored[name]["fingerprint"] = "0" * 64
    proj_path.write_text(json.dumps(stored), encoding="utf-8")

    engine_b = SqliteEngine(root)  # fresh registry cache (simulated restart)
    rebuilt = engine_b.ensure_projections(tenant)
    assert rebuilt["cached-ppr"] is True and rebuilt["evidence-fts"] is True  # fingerprint mismatch -> rebuild
    assert engine_b.ensure_projections(tenant)["evidence-fts"] is False  # fresh again

    # (b) DELETE the sidecar entirely -> rebuild-from-ledger, never silent stale.
    proj_path.unlink()
    engine_c = SqliteEngine(root)
    again = engine_c.ensure_projections(tenant)
    assert again["cached-ppr"] is True and again["evidence-fts"] is True


# --------------------------------------------------------------------------- #
# (iv) honeytoken cross-tenant isolation UNDER the chaos workload
# --------------------------------------------------------------------------- #
def _tenant_artifact_text(root: Path, jdir: Path, tenant: str) -> str:
    """All on-disk bytes attributable to ``tenant`` (db + wal/shm, projection
    sidecar, journal), decoded loss-lessly for substring/honeytoken scanning."""
    chunks: list[bytes] = []
    db_name = safe_tenant_filename(tenant, ".db")
    for path in sorted(root.glob(db_name + "*")):  # .db, .db-wal, .db-shm
        chunks.append(path.read_bytes())
    proj_dir = root / safe_tenant_filename(tenant, ".proj")
    if proj_dir.exists():
        for path in sorted(proj_dir.rglob("*")):
            if path.is_file():
                chunks.append(path.read_bytes())
    jpath = jdir / journal_filename(tenant)
    if jpath.exists():
        chunks.append(jpath.read_bytes())
    return b"".join(chunks).decode("latin-1")


@pytest.mark.parametrize("seed", SEEDS[:10] + PINNED_REGRESSION_SEEDS)
def test_honeytoken_cross_tenant_isolation_under_chaos(tmp_path: Path, seed: int) -> None:
    root = tmp_path / "root"
    jdir = tmp_path / "journal"
    engine = SqliteEngine(root, journal_dir=jdir)

    tenant_a, tenant_b = "tenant-A", "tenant-B"
    # honeytoken class is a sensitivity band "S0".."S4"; the tenant is mixed into
    # the hash, so same-class tokens from different tenants are still cross-detectable.
    mark_a = honeytoken("S3", tenant_a)
    mark_b = honeytoken("S3", tenant_b)

    H.apply_workload(engine, H.build_workload(seed, tenant=tenant_a, honeytoken_marker=mark_a))
    H.apply_workload(engine, H.build_workload(seed + 1000, tenant=tenant_b, honeytoken_marker=mark_b))
    engine.ensure_projections(tenant_a)
    engine.ensure_projections(tenant_b)

    # Stir tenant-A's journal with a torn-tail fault + repair (the "chaos" of it),
    # then confirm nothing bled into tenant-B.
    jpath_a = jdir / journal_filename(tenant_a)
    if jpath_a.exists():
        raw = jpath_a.read_bytes()
        if raw.endswith(b"\n") and len(raw) > 2:
            jpath_a.write_bytes(raw[:-2])  # tear final newline + a byte
        engine.append_evidence(_ev(tenant_a, f"chaos-{seed} post-tear record"), branch="main")

    text_a = _tenant_artifact_text(root, jdir, tenant_a)
    text_b = _tenant_artifact_text(root, jdir, tenant_b)

    # Control (non-vacuous): each tenant's OWN canary IS present in its artifacts.
    assert mark_a in text_a
    assert mark_b in text_b

    # Isolation: no FOREIGN honeytoken in either tenant's artifacts — literal and via scan.
    assert mark_a not in text_b
    assert mark_b not in text_a
    assert scan_for_foreign_honeytokens(text_b, own_tenant_id=tenant_b) == []
    assert scan_for_foreign_honeytokens(text_a, own_tenant_id=tenant_a) == []


# --------------------------------------------------------------------------- #
# Lane invariants (Phase-0 deferral) — cheap predicates over ledger + audit log.
#
# SCOPE: full lifecycle machinery (ConsolidationWorker / the ``lifecycle_forgetter``
# lane in ``consolidation.ROLE_NAMES``) is NOT driven by this unit harness, so the
# lifecycle lane authors no audit rows here. The two predicates the spec names are
# therefore asserted STRUCTURALLY over the ledger + audit log the seeded workload
# does produce; a lifecycle-authored violation would be caught the moment such a
# row appears (and would ratchet into PINNED_REGRESSION_SEEDS).
# --------------------------------------------------------------------------- #
_LIFECYCLE_ROLES = set(ROLE_NAMES.values())


@pytest.mark.parametrize("seed", SEEDS + PINNED_REGRESSION_SEEDS)
def test_lane_invariant_ledger_append_only_cid_immutable(tmp_path: Path, seed: int) -> None:
    tenant = "t-lane-append"
    engine = SqliteEngine(tmp_path / "root", journal_dir=tmp_path / "journal")
    log = H.apply_workload(engine, H.build_workload(seed, tenant=tenant))
    appended = set(log["appended_cids"])

    conn = engine._connect(tenant)
    rows = conn.execute("SELECT cid, content, erased FROM evidence WHERE tenant_id = ?", (tenant,)).fetchall()
    stored = {row["cid"] for row in rows}

    # (a) append-only-ness: no appended cid is ever lost (tombstone keeps the row),
    # and no cid appears that was never appended (provenance).
    assert appended <= stored, sorted(appended - stored)
    assert stored <= appended, sorted(stored - appended)

    # (b) cid immutability under erasure: an erased row keeps its cid and merely
    # blanks content / sets erased=1 (it IS the replay blocklist).
    for row in rows:
        if row["erased"]:
            assert row["cid"] in appended
            assert row["content"] == ""

    # (c) the ledger journal never rewrites a live cid to a different value.
    journal = CIDJournal((tmp_path / "journal") / journal_filename(tenant))
    live = {r["cid"] for r in journal.records() if not r.get("erased")}
    assert live <= appended, sorted(live - appended)


@pytest.mark.parametrize("seed", SEEDS + PINNED_REGRESSION_SEEDS)
def test_lane_invariant_contested_item_never_improperly_closed(tmp_path: Path, seed: int) -> None:
    tenant = "t-lane-contest"
    engine = SqliteEngine(tmp_path / "root", journal_dir=tmp_path / "journal")

    # Deterministic contest: same subject/predicate, DIFFERENT object, EQUAL
    # valid_from + EQUAL trust => both assertions become "contested" (shipped
    # upsert contract). Give it a grounding cid so it is a real lifecycle citizen.
    t0 = parse_dt("2026-01-01T00:00:00Z")
    cid = engine.append_evidence(_ev(tenant, f"contest-{seed} grounding about the beacon"))
    engine.upsert_assertion(
        Assertion(tenant_id=tenant, user_id="u", subject="beacon", predicate="is", object="topaz",
                  confidence=0.7, trust_tier=1, valid_from=t0, status="active",
                  source_evidence_cids=[cid], id=f"contest-{seed}-a")
    )
    engine.upsert_assertion(
        Assertion(tenant_id=tenant, user_id="u", subject="beacon", predicate="is", object="onyx",
                  confidence=0.7, trust_tier=1, valid_from=t0, status="active",
                  source_evidence_cids=[cid], id=f"contest-{seed}-b")
    )

    # Then run the noisy seeded workload (forget/merge/branch/upsert) around it.
    H.apply_workload(engine, H.build_workload(seed, tenant=tenant))

    export = engine.export_tenant(tenant)
    contested = [a for a in export["assertions"] if a["status"] == "contested"]
    # Non-vacuous: the constructed pair really did contest.
    assert any(a["id"].startswith(f"contest-{seed}-") for a in contested)

    # Predicate: a contested item is never force-closed — it keeps valid_to=None
    # (an open, live window) and a non-superseded status.
    for a in contested:
        assert a["valid_to"] is None, f"contested {a['id']} was closed (valid_to set)"
        assert a["superseded_by"] is None, f"contested {a['id']} was superseded"

    # Predicate: no LIFECYCLE-lane audit row closed a contested item. (Vacuous +
    # structural in the unit harness — no lifecycle actor is driven here.)
    contested_ids = {a["id"] for a in contested}
    for row in export["audit_log"]:
        if row.get("actor") in _LIFECYCLE_ROLES and row.get("target_id") in contested_ids:
            assert row.get("op") not in {"forget", "retire", "supersede"}, row


def test_gate_env_marker_present() -> None:
    """Sanity: this file only runs under the MNEMOSYNE_CHAOS gate."""
    assert os.environ.get("MNEMOSYNE_CHAOS") == "1"
