"""FIX lane: candidate-scan memo must not outlive ``access_policy.expires_at``.

Adversarial-review finding (verified by live repro on both engines): the B2
candidate memo — and the sqlite scan-oracle memo, which serves scans through
the hydrated oracle's own candidate memo — keyed staleness purely on write
fingerprints. ``may_read_item`` is time-dependent through ``expires_at``, so a
scan cached pre-expiry kept serving an item after its deadline passed with no
intervening write: memo-on ``retrieve()`` returned evidence a fresh scan
denies. Entries now carry the earliest future expiry in scope and are treated
as stale once the clock crosses it (engine.py ``_candidate_hits`` /
``_candidate_memo_deadline``); the fix is proven here on the Local memo, the
sqlite scan-oracle path, and end-to-end ``retrieve()``.
"""
from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import pytest

from mnemosyne.access_policy import expiry_deadline
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, utc_now
from mnemosyne.sqlite_engine import SqliteEngine

TENANT = "t-expiry"

# Short-lived policy: long enough that append + first scan land pre-expiry
# even on a slow runner, short enough to keep the test fast.
EXPIRY_SECONDS = 1.2
SLEEP_SECONDS = 1.8


def _expiring_evidence(expires_in: float = EXPIRY_SECONDS) -> Evidence:
    expires = (utc_now() + timedelta(seconds=expires_in)).isoformat()
    return Evidence(
        tenant_id=TENANT,
        user_id="u1",
        actor="user",
        source_type="chat",
        content="helios deadline secret fact",
        access_policy={"tenant": TENANT, "expires_at": expires},
    )


def test_expiry_deadline_parses_only_flippable_values() -> None:
    aware = expiry_deadline("2999-01-02T03:04:05+00:00")
    assert aware is not None and aware.tzinfo is not None
    assert expiry_deadline("2999-01-02T03:04:05Z") == aware
    # Naive values are pinned to UTC, matching _expired.
    assert expiry_deadline("2999-01-02T03:04:05") == aware
    # Absent never expires; unparseable is permanently expired — neither can
    # flip a decision later, so neither imposes a deadline.
    assert expiry_deadline(None) is None
    assert expiry_deadline("") is None
    assert expiry_deadline("not-a-date") is None


def test_local_memo_entry_goes_stale_at_policy_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "1")
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(_expiring_evidence())
    filt = {"tenant_id": TENANT, "branch": "main"}

    scans = 0
    real_scan = LocalMemoryEngine._candidate_hits_uncached

    def counting_scan(self: LocalMemoryEngine, f: dict) -> list:
        nonlocal scans
        scans += 1
        return real_scan(self, f)

    monkeypatch.setattr(LocalMemoryEngine, "_candidate_hits_uncached", counting_scan)

    pre = engine._candidate_hits(dict(filt))
    assert cid in {hit.id for hit in pre}
    # Pre-deadline repeats still HIT the memo — expiry awareness must not
    # degrade the memo into a per-call rescan.
    assert {hit.id for hit in engine._candidate_hits(dict(filt))} == {cid}
    assert scans == 1

    time.sleep(SLEEP_SECONDS)  # cross expires_at; NO writes in between

    post = engine._candidate_hits(dict(filt))
    assert post == []
    assert scans == 2  # stale entry was discarded and rescanned
    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "0")
    assert engine._candidate_hits(dict(filt)) == []  # parity with uncached


def test_local_memo_without_expiries_still_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "1")
    engine = LocalMemoryEngine()
    engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id="u1",
            actor="user",
            source_type="chat",
            content="a durable fact with no expiry",
            access_policy={"tenant": TENANT},
        )
    )
    filt = {"tenant_id": TENANT, "branch": "main"}

    scans = 0
    real_scan = LocalMemoryEngine._candidate_hits_uncached

    def counting_scan(self: LocalMemoryEngine, f: dict) -> list:
        nonlocal scans
        scans += 1
        return real_scan(self, f)

    monkeypatch.setattr(LocalMemoryEngine, "_candidate_hits_uncached", counting_scan)

    first = engine._candidate_hits(dict(filt))
    second = engine._candidate_hits(dict(filt))
    assert scans == 1
    assert [hit.to_dict() for hit in first] == [hit.to_dict() for hit in second]


def test_sqlite_scan_oracle_respects_policy_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "1")
    engine = SqliteEngine(tmp_path / "root")
    try:
        cid = engine.append_evidence(_expiring_evidence())
        filt = {"tenant_id": TENANT, "branch": "main"}

        oracle1 = engine._scan_oracle(dict(filt))
        assert cid in {hit.id for hit in oracle1._candidate_hits(dict(filt))}

        time.sleep(SLEEP_SECONDS)  # cross expires_at; NO writes in between

        oracle2 = engine._scan_oracle(dict(filt))
        # The finding's exact shape: the memo hands back the SAME hydrated
        # oracle (no write happened) — its internal scan must still re-gate.
        assert oracle2 is oracle1
        assert oracle2._candidate_hits(dict(filt)) == []

        monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "0")
        assert engine._scan_oracle(dict(filt))._candidate_hits(dict(filt)) == []
    finally:
        engine.close()


def test_retrieve_never_serves_expired_item_from_memo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "1")
    engine = LocalMemoryEngine()
    engine.append_evidence(_expiring_evidence())

    # Prime the memo with a query matching nothing: zero hits means no access
    # bookkeeping persists, so no version bump evicts the entry for us.
    assert engine.retrieve("zzz qqq nomatch", TENANT).hits == []

    time.sleep(SLEEP_SECONDS)  # cross expires_at; NO writes in between

    memo_on = engine.retrieve("helios deadline", TENANT)
    assert memo_on.hits == []
    monkeypatch.setenv("MNEMOSYNE_CANDIDATE_MEMO", "0")
    assert engine.retrieve("helios deadline", TENANT).hits == []
