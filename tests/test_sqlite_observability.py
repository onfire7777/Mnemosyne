"""Phase-2 Task 12 — SqliteEngine emits the observability checklist §1-3 signals.

The engine writes directly into ``observability.MetricsRegistry`` (its
``engine.metrics``), so the four live signals the spec's Phase-2 exit requires are
produced by the engine itself, not only by MemoryTools/jobs wrappers:

* §1a evidence-durability — per-append ledger counter + journal fsync-lag sample,
  with the evidence-loss counter materialised (and held) at zero.
* §1b per-store rebuild-lag — projection watermark deltas gauged per projection.
* §3  security audit stream — a live per-write counter (each entry carries
  actor · source · trust-tier · diff in the audit_log record).
* §3  erasure / deletion-propagation — a traceable propagation signal counting the
  cache-purge and journal (tombstone/compaction) steps, distinct from the
  byte-parity ``propagated`` cascade dict.
"""

from __future__ import annotations

from pathlib import Path

from mnemosyne.models import Evidence, parse_dt
from mnemosyne.observability import MetricsRegistry
from mnemosyne.privacy import ErasureMode
from mnemosyne.sqlite_engine import SqliteEngine

FIXED_CREATED = parse_dt("2026-07-02T03:04:05.123456Z")


def _ev(**over) -> Evidence:
    base = dict(
        tenant_id="t",
        user_id="user-1",
        actor="user",
        source_type="chat",
        content="Observability note about the cobalt lighthouse.",
        trust_tier=2,
        capability_tags=["capA"],
        access_policy={"allow_principals": ["user-1"], "purpose": "assistant-memory"},
        created_at=FIXED_CREATED,
    )
    base.update(over)
    return Evidence(**base)


def test_engine_always_has_a_metrics_registry_with_loss_pinned_zero(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "store")
    snap = engine.metrics.snapshot()
    # Durability is the highest SLO (§15): the loss counter exists from
    # construction and reads zero.
    assert snap.counters.get("sqlite.evidence.durability.loss") == 0


def test_injected_metrics_registry_is_used(tmp_path: Path) -> None:
    registry = MetricsRegistry()
    engine = SqliteEngine(tmp_path / "store", metrics=registry)
    engine.append_evidence(_ev())
    assert registry.counters.get("sqlite.evidence.durability.appends") == 1


def test_evidence_durability_signal_counts_appends_and_journal_lag(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "store", journal_dir=tmp_path / "journal")
    engine.append_evidence(_ev(content="one"))
    engine.append_evidence(_ev(content="two"))
    snap = engine.metrics.snapshot()
    assert snap.counters.get("sqlite.evidence.durability.appends") == 2
    assert snap.counters.get("sqlite.evidence.durability.loss") == 0
    # Journal fsync lag is sampled (durability signal); with journal_dir set, both
    # appends contribute a sample and the p95 gauge materialises.
    assert len(snap.samples.get("sqlite.evidence.durability.journal_lag_ms", [])) == 2
    assert "sqlite.evidence.durability.journal_lag_ms.p95" in snap.gauges


def test_audit_stream_signal_increments_per_write(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "store")
    before = engine.metrics.snapshot().counters.get("sqlite.audit.writes", 0)
    engine.append_evidence(_ev())  # append_evidence writes one audit row
    after = engine.metrics.snapshot().counters.get("sqlite.audit.writes", 0)
    assert after > before


def test_rebuild_lag_signal_gauged_per_projection(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "store")
    engine.append_evidence(_ev())
    # First pass: projections are stale vs the new ledger row -> rebuild-lag > 0.
    engine.ensure_projections("t")
    lag = engine.metrics.snapshot().gauges
    assert lag.get("sqlite.projection.rebuild_lag.cached-ppr") == 1.0
    assert lag.get("sqlite.projection.rebuild_lag.evidence-fts") == 1.0
    assert engine.metrics.snapshot().counters.get("sqlite.projection.rebuilds", 0) >= 1
    # Second pass with no new writes: fresh -> lag drops to 0.0.
    engine.ensure_projections("t")
    assert engine.metrics.snapshot().gauges.get("sqlite.projection.rebuild_lag.cached-ppr") == 0.0


def test_erasure_propagation_signal_records_cache_and_journal_steps(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path / "store", journal_dir=tmp_path / "journal")
    cid = engine.append_evidence(_ev())
    result = engine.forget("t", cid, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)
    assert result["erased"] is True
    snap = engine.metrics.snapshot()
    assert snap.counters.get("sqlite.erasure.propagations") == 1
    # The propagation log covers the affected cids' cache purge + journal steps.
    assert snap.samples.get("sqlite.erasure.propagation.cache_purges", []) == [1.0]
    assert snap.samples.get("sqlite.erasure.propagation.journal_steps", []) == [1.0]
