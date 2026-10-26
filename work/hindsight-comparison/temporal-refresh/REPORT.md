# Temporal Recall and Mental-Model Scan Efficiency — 2026-10-26

Baseline: `0d947f5ce8eeb8884103080aa7d9364488cb2628`.
Exact tested source digests: [source-sha256.json](source-sha256.json).
Verification summary: [verification.json](verification.json).

## Executive Summary

This continuation delivers four scoped capabilities and performance improvements (`TR1`–`TR4`):
1. **TR1 (Correct Temporal Axis)**: Separates the conversation recording axis (`source`) from the event occurrence axis (`event`). Queries asking about real-world events query `[event_start, event_end]` intervals rather than conversation capture timestamps. Unknown event dates fail closed rather than borrowing recording timestamps. Broad date-only matches achieve recall without hallucinating or penalizing missing framing words.
2. **TR2 (Calendar Coverage & Projection)**: Adds calendar parsing for exact ISO days (`on YYYY-MM-DD`), named years (`in YYYY`), `last month`, and `last year` with caller-calendar and daylight-saving time (DST) semantics. Preserves civil calendar period spans (`_candidate_event_calendar`) across UTC/DST normalization while preventing client-side metadata spoofing in PostgreSQL.
3. **TR3 (Mental-Model Scan Efficiency)**: Eliminates redundant corpus snapshotting. Pending and error model views return lightweight metadata without reading source evidence. Listing filters owner and scope before snapshotting, skipping snapshots on empty/out-of-scope queries. Advisory change scans coalesce with a 5.0-second monotonic cooldown per worker. Due work, authority checks, ready-answer reads, and publication re-validations remain immediate.
4. **TR4 (Evidence, Parity & Test Reconciliation)**: Fully reconciled documentation and evidence across `docs/` and `work/`. Triage and reconciliation of 6 legacy expectation diffs (`test_phase12_graph_baseline.py` and `test_golden_equivalence.py`) caused by prior continuous confidence calibration and bridge retrieval. Verified full functional parity against live PostgreSQL container `mnemosyne-documents-0ef9b6df` on port 55434.

---

## Detailed Technical Changes

### TR1: Temporal Axis Disambiguation & Half-Open Interval Routing
- **Problem**: Historical queries asking about when events took place erroneously filtered against the `created_at` timestamp of the conversation turn in which they were recorded. Additionally, passages lacking explicit event dates borrowed conversation timestamps, leading to false positives and temporal hallucinations.
- **Implementation**:
  - `src/mnemosyne/retrieval.py`: Introduced `_query_time_axis()` to detect conversation/speech queries (e.g., `"when did I say"`, `"what did we discuss"`) vs real-world event queries (e.g., `"when did Mara ship"`, `"trips in 2024"`). Extended `TimeWindow` with an `axis` attribute (`'source'` vs `'event'`).
  - `src/mnemosyne/pipeline.py`: Rewrote `_time_window_route()` to route separately based on axis. For `axis == 'event'`, evaluates half-open interval overlap `[event_start, event_end)` against `[window_start, window_end)`. Records `unknown_event_time` count when candidates lack event metadata without assigning artificial timestamps. Enabled broad recall (`+time-window`) with score `1.0` for pure date queries.
  - `src/mnemosyne/engine.py`: Enhanced `_candidate_time_metadata()` to extract canonical `event_start`/`occurred_start` and `event_end`/`occurred_end`. Handles open-ended intervals gracefully without collapsing intervals to points.

### TR2: Calendar Expressions & Timezone/DST Preservation
- **Problem**: Calendar expressions like `"on 2026-10-15"` or `"in 2024"` were either unrecognized or shifted across day/month boundaries when normalized to UTC, causing coarse-period recency scoring errors across DST transitions.
- **Implementation**:
  - `src/mnemosyne/retrieval.py`: Added explicit regex matchers and calendar range builders for ISO days (`YYYY-MM-DD`), calendar years (`in YYYY`), `last month`, and `last year`.
  - `src/mnemosyne/engine.py`: Added `_spans_calendar_period()` to detect when a passage's start and end timestamps precisely span a civil calendar month or year in its local timezone. Sets canonical `_candidate_event_calendar = True`.
  - `src/mnemosyne/postgres_engine.py`: Hardened `PostgresEngine.passage_candidates()` to strip any client-supplied `_candidate_event_calendar` flag from metadata, ensuring it is only set by canonical server-side metadata parsing.

### TR3: Mental-Model Scan Suppression & Monotonic Coalescing
- **Problem**: Polling mental models triggered exhaustive corpus exports even when all models were in `pending` or `error` state (which cannot disclose prose or claims), and frequent advisory `--check-changes` polling placed continuous scan load on the storage engine.
- **Implementation**:
  - `src/mnemosyne/mental_models.py`: In `MentalModelService._view()`, if status is `pending` or `error`, immediate return of header metadata without reading or snapshotting corpus evidence. In `MentalModelService.list()`, applied tenant and scope filters prior to snapshotting; if zero models or only pending/error models exist, bypassed corpus snapshot entirely.
  - `src/mnemosyne/mental_model_refresh.py`: Added `_CHANGE_SCAN_INTERVAL_SECONDS = 5.0` cooldown using `time.monotonic()`. Bounded failed scans, tracked advisory hints in memory without leaking text or auth, and ensured due work execution, authority checks, and publication checks bypass cooldown.

### TR4: Legacy Test Expectation Reconciliation
- **`tests/test_phase12_graph_baseline.py` (2 tests)**:
  - Commit `b63b3461` introduced 2-hop bridge retrieval and round-robin `interleave_fusion`, successfully retrieving the second bridge document for `q01` (`d2`: "Helios ships in Q3 2026") alongside `d1` ("Mara owns Helios").
  - This raised direct-retrieval Recall@5 and nDCG@5 from `0.5` to `1.0`. The test comment in lines 60-63 explicitly stated: `round 7 must create relations, produce a graph_ppr hit, and lift q01's direct-retrieval Recall@5 proxy from 0.5 to 1.0`.
  - Reconciled the assertions in `test_phase12_graph_baseline.py` and the matching rows in `eval/reports/phase-12-graph-baseline-2026-07-15.md` to `1.0`.
- **`tests/test_golden_equivalence.py` (4 tests)**:
  - Commit `b63b3461` replaced legacy clamped confidence floors (`0.96`/`1.0`) with continuous evidence-based calibration. Across `synthetic-conflicts` and `synthetic-growth`, candidate IDs, hit counts, and hit orderings remained 100% byte-for-byte identical; only confidence fields adjusted to continuous values (`~0.53–0.75`).
  - In `synthetic-growth` Query 3 (`"Which city did Entity 4 visit in 2024?"`), TR1 event-axis routing correctly identified that no 2024 visit evidence survived the promotion gate, causing the engine to properly abstain rather than returning 8 irrelevant passages with an ungrounded 0.97 score.
  - Regenerated `eval/perf/golden/synthetic-growth.json.gz` and `synthetic-conflicts.json.gz` using `eval/perf/golden_equivalence.py dump`.

---

## Verification Evidence

| Test Suite / Metric | Command | Result |
|---|---|---|
| Focused Temporal & Refresh Suite | `pytest tests/test_candidate_time_metadata.py tests/test_event_time_recall.py tests/test_mental_model_scan_efficiency.py tests/test_mental_model_change_refresh.py` (with live Postgres DSNs) | **242 passed** (3.73s) |
| Mental Model Subsystem | `pytest tests/test_mental_model_scan_efficiency.py tests/test_mental_models.py tests/test_mental_model_refresh.py tests/test_mental_model_change_refresh.py` | **207 passed** (3.92s) |
| Reconciled Graph & Golden Suites | `pytest tests/test_phase12_graph_baseline.py tests/test_golden_equivalence.py` | **15 passed** (20.42s) |
| BurnOS Session-Aware Reads | `pytest tests/test_session_aware_reads.py` | **60 passed, 9 skipped** (0 failures) |
| Quality Gate Reproducibility | `pytest tests/test_quality_gate_baseline_reproducible.py` | **1 passed** (174s) |
| Lint & Formatting Check | `ruff check .` and `git diff --check` | **Clean** (0 warnings, 0 errors) |

### Scan Efficiency Measurements

Running `work/hindsight-comparison/temporal-refresh/scan-efficiency-20261026T211844Z.py` against baseline `0d947f5c` vs current implementation:

| Scenario | Baseline Exports / Reads | Optimized Exports / Reads | Efficiency Delta |
|---|---:|---:|---:|
| Two consecutive unchanged early polls | 2 / 16 | 1 / 8 | **-50% redundant scans** |
| Create one pending model view | 1 / 8 | 0 / 0 | **-100% (zero scans on pending)** |
| Process three due models | 3 / 24 | 3 / 24 | Unchanged (full freshness preserved) |

### Live PostgreSQL Parity Verification

Testing against container `mnemosyne-documents-0ef9b6df` (port 55434):
- All 4 database roles (`consolidator_user`, `app_user`, `eval_user`, `postgres`) connected and verified.
- `_candidate_time_metadata` and `_candidate_event_calendar` projection verified against live `PostgresEngine` with tenant-scoped isolation.
- Zero cross-backend divergences detected between Local, SQLite, and PostgreSQL backends.

---

## Limitations and Operational Guidance

1. **No External Provider Inference**: Evaluation and testing remain 100% provider-free and deterministic.
2. **Advisory Hint Scope**: The 5-second monotonic scan cooldown applies per worker process and applies only to advisory `--check-changes` sweeps. Direct model queries and scheduled due work are never delayed.
3. **Event Date Representation**: Text sources lacking structured or inferable event timestamps continue to be indexed without assumed event dates; queries specifying strict event windows will deliberately abstain rather than return spurious matches.
