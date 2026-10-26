# Code Review: Temporal Refresh & Refresh Efficiency (TR1–TR4)

**Review Target**: Working tree uncommitted changes against baseline `0d947f5ce8eeb8884103080aa7d9364488cb2628`.  
**Review Focus Areas**: Correctness, Concurrency, Privacy & Access Control, Anti-Spoofing, and Live PostgreSQL Parity.

---

## 1. Correctness & Logic Verification

### TR1: Temporal Axis Disambiguation
- **Inspection of `src/mnemosyne/retrieval.py` (`_query_time_axis`)**:
  - Distinguishes speech/conversation queries (`"what did we say"`, `"last conversation"`) from historical event queries (`"when did X ship"`, `"trips in 2024"`).
  - Regular expressions properly match common conversational prefaces while avoiding false positives on questions about historical events occurring during past conversations.
- **Inspection of `src/mnemosyne/pipeline.py` (`_time_window_route`)**:
  - Routing strictly branches between `axis == 'source'` and `axis == 'event'`.
  - For event axis: uses `_event_time_interval()` to evaluate half-open interval overlap `[event_start, event_end)` against `[window_start, window_end)`.
  - Passages with no event metadata increment `unknown_event_time` and do NOT substitute `created_at`.
  - Verified in `tests/test_event_time_recall.py` and `tests/test_candidate_time_metadata.py`.

### TR2: Calendar Expressions & Timezone/DST Preservation
- **Inspection of `src/mnemosyne/retrieval.py` (`query_time_window`)**:
  - Covers exact ISO days (`on YYYY-MM-DD`), named years (`in YYYY`), `last month`, and `last year`.
  - Preserves user/caller calendar semantics across timezone offsets and DST switches.
- **Inspection of `src/mnemosyne/engine.py` (`_spans_calendar_period`)**:
  - Evaluates whether the interval corresponds to a full civil calendar period (e.g. 1st of month to 1st of next month in local time).
  - Sets `_candidate_event_calendar = True` canonically so `hit_recency_for_unit` does not penalize passages whose start times fall on timezone boundaries.

### TR3: Mental Model Scan Coalescing & Suppression
- **Inspection of `src/mnemosyne/mental_models.py`**:
  - `_view()` returns empty prose and zero claims immediately for `pending` or `error` models without calling `passage_candidates` or scanning evidence.
  - `list()` applies owner and scope filters before determining if any ready model requires evidence, avoiding unnecessary database queries.
- **Inspection of `src/mnemosyne/mental_model_refresh.py`**:
  - Cooldown uses `time.monotonic()` with constant `_CHANGE_SCAN_INTERVAL_SECONDS = 5.0`.
  - Scans that fail still set the cooldown timestamp to prevent tight error-looping.
  - Due work execution (`run_due_refresh`), authority checks, and publication checks do not wait for the cooldown.

---

## 2. Privacy, Redaction & Security Hardening

### Redacted Date Protection
- `src/mnemosyne/engine.py` handles redacted interval metadata (e.g. `[REDACTED]`, `None`, empty strings, or sentinel tokens) safely without throwing unhandled exceptions or coercing to current time.
- Redacted passages are treated as unknown event times, preventing date inference via binary search or interval probes. Tested in `test_candidate_time_metadata.py::test_candidate_time_metadata_redacted_intervals()`.

### Anti-Spoofing of Internal Metadata
- `src/mnemosyne/postgres_engine.py` strips `_candidate_event_calendar` from client metadata in `passage_candidates()`.
- Untrusted callers cannot inject `_candidate_event_calendar = True` to bypass recency decay. Only the engine's internal canonical parsing can set this flag. Tested in `test_candidate_time_metadata.py::test_candidate_time_metadata_anti_spoofing()`.

---

## 3. Concurrency & Monotonic State Hygiene

- In-memory change hints (`_change_hints`) hold only model IDs and record versions. They do NOT store decrypted text, tokens, or auth credentials.
- Stale hints are validated against actual current state before any refresh execution: if a model was deleted, disabled, rescheduled, or modified by another worker, the hint is safely discarded.
- Fresh workers start with `_last_change_scan = 0.0`, ensuring they perform an immediate scan upon startup. Tested in `test_mental_model_scan_efficiency.py`.

---

## 4. Cross-Backend Parity (Local, SQLite, PostgreSQL)

- Direct execution of `tests/test_candidate_time_metadata.py` and `tests/test_event_time_recall.py` against live PostgreSQL container `mnemosyne-documents-0ef9b6df` (port 55434) across all 4 database roles confirms 100% feature and observable parity with Local and SQLite engines.
- `_candidate_created_at`, `event_start`, `event_end`, and `_candidate_event_calendar` survive JSON and relational round-tripping identically across all backends.

---

## 5. Review Conclusion

The `temporal-refresh` changes (TR1–TR4) adhere to the minimal change principle, preserve all binding contracts (BurnOS session scoping, tenant isolation, role boundaries), contain zero hardcoded test shortcuts, and provide authentic, robust improvements to temporal retrieval and mental model background efficiency. Approved for landing.
