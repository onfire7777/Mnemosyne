"""Phase-2 Task 3 — SqliteEngine ledger surface, compared against the
LocalMemoryEngine oracle.

Every behaviour is pinned to Local: the same inputs into ``SqliteEngine`` and
``LocalMemoryEngine`` must yield equal ``export_tenant`` / ``export_all`` output
(normalising only the documented format deltas — volatile audit ``id``/``at`` and
the branch ``created_at`` serialiser). Also pins the three CRITICAL handoffs:
(a) hostile/unknown branch raises ``ValueError`` before the FK fires;
(b) the erased-replay blocklist reproduces BOTH probes (scoped replay + legacy
unscoped) with the ``append_evidence.blocked_erased_replay`` audit op; and
(c) the CID journal appends AFTER commit, success-path only, exactly once
(dedup / blocked paths are journal-free).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ids import evidence_cid, evidence_unscoped_cid
from mnemosyne.journal import journal_filename
from mnemosyne.models import Evidence, parse_dt
from mnemosyne.sqlite_engine import SqliteEngine

FIXED_CREATED = parse_dt("2026-07-02T03:04:05.123456Z")


def _ev(**over) -> Evidence:
    base = dict(
        tenant_id="t",
        user_id="user-1",
        actor="user",
        source_type="chat",
        content="Ledger note about the cobalt lighthouse.",
        source_identity="mailto:user@example.com",
        session_id="sess-1",
        metadata={"topic": "lighthouse"},
        modality="text",
        embedding=[0.125, -3.75, 1.0],
        trust_tier=2,
        capability_tags=["capA"],
        sensitivity=1,
        access_policy={"allow_principals": ["user-1"], "purpose": "assistant-memory"},
        created_at=FIXED_CREATED,
    )
    base.update(over)
    return Evidence(**base)


# --- export normalisation (documented deltas only) --------------------------


def _strip_audit(records: list[dict]) -> list[dict]:
    out = []
    for record in records:
        cleaned = dict(record)
        cleaned.pop("id", None)  # random uuid
        cleaned.pop("at", None)  # wall-clock timestamp
        out.append(cleaned)
    return out


def _normalise_export(export: dict) -> dict:
    export = copy.deepcopy(export)
    if "audit_log" in export:
        export["audit_log"] = _strip_audit(export["audit_log"])
    if "branches" in export:
        for branch in export["branches"]:
            branch.pop("created_at", None)  # dt_to_json (sqlite) vs isoformat (local)
    if "tenants" in export:
        export["tenants"] = [_normalise_export(item) for item in export["tenants"]]
    for key, value in export.items():
        if isinstance(value, list):
            export[key] = sorted(value, key=lambda item: json.dumps(item, sort_keys=True))
    return export


def _apply_ledger_ops(engine, tenant: str) -> tuple[str, str]:
    ev1 = _ev(tenant_id=tenant, content="Grounded note about the cobalt lighthouse.", sensitivity=1)
    c1 = engine.append_evidence(ev1)
    ev2 = _ev(
        tenant_id=tenant,
        actor="assistant",
        source_type="analysis-summary",
        content="Self summary of the topaz beacon.",
        sensitivity=0,
        embedding=None,
    )
    c2 = engine.append_evidence(ev2)
    engine.update_evidence_metadata(tenant, c1, {"salience_note": "keep"})
    engine.set_evidence_embedding(tenant, c1, [0.5, -0.25, 0.75])
    engine.backfill_evidence_privacy(tenant, c2, ["email"], pii_sensitivity=3)
    return c1, c2


def test_append_and_mutations_export_parity_vs_local(tmp_path: Path):
    local = LocalMemoryEngine()
    sqlite = SqliteEngine(tmp_path / "root")

    local_cids = _apply_ledger_ops(local, "t-parity")
    sqlite_cids = _apply_ledger_ops(sqlite, "t-parity")
    assert local_cids == sqlite_cids  # deterministic evidence_cid on both engines

    assert _normalise_export(sqlite.export_tenant("t-parity")) == _normalise_export(
        local.export_tenant("t-parity")
    )
    assert _normalise_export(sqlite.export_all()) == _normalise_export(local.export_all())


def test_export_tenant_filtered_matches_local(tmp_path: Path):
    local = LocalMemoryEngine()
    sqlite = SqliteEngine(tmp_path / "root")
    _apply_ledger_ops(local, "t-filt")
    _apply_ledger_ops(sqlite, "t-filt")
    context = {"role": "member", "user_id": "user-1"}
    assert _normalise_export(sqlite.export_tenant_filtered("t-filt", context)) == _normalise_export(
        local.export_tenant_filtered("t-filt", context)
    )


def test_get_evidence_hides_erased_returns_stored_otherwise(tmp_path: Path):
    sqlite = SqliteEngine(tmp_path / "root")
    ev = _ev(tenant_id="t-get")
    cid = sqlite.append_evidence(ev)
    got = sqlite.get_evidence("t-get", cid)
    assert got is not None and got.cid == cid
    assert sqlite.get_evidence("t-get", "0" * 64) is None


def test_update_metadata_rejects_access_policy_patch(tmp_path: Path):
    sqlite = SqliteEngine(tmp_path / "root")
    local = LocalMemoryEngine()
    cid = sqlite.append_evidence(_ev(tenant_id="t-up"))
    local.append_evidence(_ev(tenant_id="t-up"))
    with pytest.raises(ValueError, match="metadata_patch.access_policy cannot shadow evidence.access_policy"):
        sqlite.update_evidence_metadata("t-up", cid, {"access_policy": {}})
    with pytest.raises(ValueError, match="metadata_patch.access_policy cannot shadow evidence.access_policy"):
        local.update_evidence_metadata("t-up", cid, {"access_policy": {}})


# --- CRITICAL handoff (a): hostile/unknown branch → ValueError before FK -----


def test_hostile_branch_raises_valueerror_before_fk(tmp_path: Path):
    sqlite = SqliteEngine(tmp_path / "root")
    with pytest.raises(ValueError, match="unknown branch: ghost-branch"):
        sqlite.append_evidence(_ev(tenant_id="t-hostile"), branch="ghost-branch")
    conn = sqlite._connect("t-hostile")
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0

    local = LocalMemoryEngine()
    with pytest.raises(ValueError, match="unknown branch: ghost-branch"):
        local.append_evidence(_ev(tenant_id="t-hostile"), branch="ghost-branch")


# --- CRITICAL handoff (c): journal after commit, success-path exactly-once ---


def test_journal_appends_once_after_commit(tmp_path: Path):
    jdir = tmp_path / "journals"
    sqlite = SqliteEngine(tmp_path / "root", journal_dir=jdir)
    cid = sqlite.append_evidence(_ev(tenant_id="t-journal"))
    lines = _journal_lines(jdir, "t-journal")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["cid"] == cid
    assert record["kind"] == "evidence"
    assert record["tenant_id"] == "t-journal"


def test_dedup_reingest_single_journal_line(tmp_path: Path):
    jdir = tmp_path / "journals"
    sqlite = SqliteEngine(tmp_path / "root", journal_dir=jdir)
    c1 = sqlite.append_evidence(_ev(tenant_id="t-dedup"))
    c2 = sqlite.append_evidence(_ev(tenant_id="t-dedup"))  # identical content → dedup no-op
    assert c1 == c2
    assert len(_journal_lines(jdir, "t-dedup")) == 1  # dedup path is journal-free
    conn = sqlite._connect("t-dedup")
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    ops = [json.loads(row[0])["op"] for row in conn.execute("SELECT record FROM audit_log ORDER BY seq")]
    assert ops == ["append_evidence", "append_evidence.noop_dedup"]


def _journal_lines(jdir: Path, tenant: str) -> list[str]:
    path = jdir / journal_filename(tenant)
    if not path.exists():
        return []
    return [line for line in path.read_text().splitlines() if line.strip()]


# --- CRITICAL handoff (b): erased-replay blocklist, BOTH probes -------------


def _seed_erased(engine, *, kind: str, tenant: str, cid: str, user_id: str, sensitivity: int) -> None:
    """Directly seed an erased tombstone row (full forget() lands in Task 9):
    SQL insert for SqliteEngine, direct dict for the Local oracle. The erased row
    IS the blocklist, so this exercises the exact probe without forget()."""
    erased = Evidence(
        tenant_id=tenant,
        user_id=user_id,
        actor="external",
        source_type="web",
        content="",
        content_pointer=None,
        modality="text",
        sensitivity=sensitivity,
        cid=cid,
        branch="main",
        erased=True,
    )
    if kind == "sqlite":
        engine._connect(tenant)  # seed the protected main branch row
        engine._insert_evidence(erased)
    else:
        engine.evidence[engine._evidence_key(tenant, "main", cid)] = erased


CONTENT = "ghost beacon over the northern harbor"


def _run_blocked_replay(tmp_path: Path, tenant: str, seed_cid: str, seed_sensitivity: int, fresh: Evidence):
    jdir = tmp_path / "journals"
    sqlite = SqliteEngine(tmp_path / "root", journal_dir=jdir)
    local = LocalMemoryEngine()
    _seed_erased(sqlite, kind="sqlite", tenant=tenant, cid=seed_cid, user_id="seed-user", sensitivity=seed_sensitivity)
    _seed_erased(local, kind="local", tenant=tenant, cid=seed_cid, user_id="seed-user", sensitivity=seed_sensitivity)

    sqlite_cid = sqlite.append_evidence(copy.deepcopy(fresh))
    local_cid = local.append_evidence(copy.deepcopy(fresh))

    # both engines reuse the tombstone cid and refuse to un-erase it
    assert sqlite_cid == local_cid == seed_cid
    assert sqlite.get_evidence(tenant, seed_cid) is None
    assert local.get_evidence(tenant, seed_cid) is None

    # blocked path is journal-free and adds no new row
    assert _journal_lines(jdir, tenant) == []
    conn = sqlite._connect(tenant)
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1

    sqlite_ops = [json.loads(r[0])["op"] for r in conn.execute("SELECT record FROM audit_log ORDER BY seq")]
    local_ops = [row["op"] for row in local.audit_log]
    assert sqlite_ops == ["append_evidence.blocked_erased_replay"]
    assert local_ops == ["append_evidence.blocked_erased_replay"]


def test_blocked_erased_replay_scoped_cross_user_probe(tmp_path: Path):
    # scoped probe: incoming user differs, the recomputed replay_cid (using the
    # tombstone's user_id + sensitivity) still collides → blocked.
    seed_cid = evidence_cid(
        CONTENT,
        tenant_id="t-scoped",
        user_id="seed-user",
        source_type="web",
        content_pointer=None,
        modality="text",
        sensitivity=3,
    )
    fresh = Evidence(
        tenant_id="t-scoped",
        user_id="mallory",
        actor="external",
        source_type="web",
        content=CONTENT,
        modality="text",
        sensitivity=3,
    )
    _run_blocked_replay(tmp_path, "t-scoped", seed_cid, seed_sensitivity=3, fresh=fresh)


def test_blocked_erased_replay_legacy_unscoped_probe(tmp_path: Path):
    # legacy probe: tombstone cid is the unscoped (pre-subject-scoping) CID; the
    # scoped replay_cid does NOT match, only the evidence_unscoped_cid branch does.
    seed_cid = evidence_unscoped_cid(
        CONTENT,
        tenant_id="t-legacy",
        source_type="web",
        content_pointer=None,
        modality="text",
    )
    fresh = Evidence(
        tenant_id="t-legacy",
        user_id="bob",
        actor="external",
        source_type="web",
        content=CONTENT,
        modality="text",
        sensitivity=3,  # scoped fresh cid differs from the unscoped tombstone
    )
    _run_blocked_replay(tmp_path, "t-legacy", seed_cid, seed_sensitivity=3, fresh=fresh)
