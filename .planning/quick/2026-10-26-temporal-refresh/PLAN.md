---
phase: quick-temporal-refresh
plan: "01"
autonomous: true
requirements: [TR1, TR2, TR3, TR4]
---

# Temporal recall and refresh efficiency

Baseline: `0d947f5ce8eeb8884103080aa7d9364488cb2628`.
The preceding continuation delivered whole-book answering and runtime repairs.
This scoped continuation advances the ongoing memory-quality goal without
claiming leaderboard superiority or closing historical benchmark acceptance.

## Constraints and findings

Apply Karpathy's minimal-change guidance and the GSD plan, implementation,
independent review and verification loop. The user's latest restrictions exclude
full benchmarks and model-provider inference. Local deterministic regressions
and disposable PostgreSQL validation remain authorized. Preserve unrelated work
and the separation of Mnemosyne and Mnemetric. Push verified changes to main.

Read-only Local and SQLite reproductions found that event-window recall filters
recording timestamps instead of occurrence timestamps. Date-only source recall
can also abstain solely because framing words do not occur in the source.
Calendar parsing omits common historical expressions. Pending model views scan
the corpus even though they cannot return prose, and unchanged early-refresh
polls repeat the same expensive scan.

## Work and acceptance

1. **TR1 — Correct temporal axis.** Explicit conversation questions retain source
   time. Event questions use authorized event metadata and interval overlap;
   unknown event dates must not be presented as known occurrence dates. Preserve
   speaker preference, explicit first/last ordering and branch/tenant/redaction
   boundaries. A date-only match may satisfy broad recall without matching its
   framing words; topical questions still require topical evidence.
2. **TR2 — Calendar coverage.** Recognize exact ISO days, named historical years,
   last month and last year with caller-calendar/DST semantics. Invalid and
   out-of-range dates must fail safely. Separately inspect the known coarse-period
   timezone-scoring defect and fix only if its source projection can preserve the
   required information without a storage migration or policy bypass.
3. **TR3 — Avoid redundant scans.** Pending/error model views do not scan sources.
   Filter owner/scope before listing decides whether a snapshot is necessary.
   Coalesce only advisory early-change polling with a bounded monotonic cadence;
   due work, authorization on every poll, ready-answer freshness and publication
   checks remain fresh. Prove restart, failure and immediate erasure behavior.
4. **TR4 — Honest evidence and delivery.** Correct stale document-lifecycle and
   PostgreSQL comparison notes while retaining historical receipts and the pinned
   Hindsight review. Run focused local tests and independent code review, record
   exact source hashes and limitations, then commit and push reviewed changes.

Ownership: temporal pipeline/retrieval and their tests; mental-model service/
worker and their tests; documentation reconciliation are disjoint agent tasks.
The parent owns integration, any separately reviewed metadata projection repair,
planning artifacts, verification records and delivery.
