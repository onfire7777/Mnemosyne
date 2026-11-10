# Memory effectiveness implementation

This implements the six runtime milestones in the accompanying plan. It does
not establish the plan's proposed improvement percentages or a competitive win
over an Anthropic product. The full suite and broad acceptance matrix were not
run; implementation and focused integration checks were prioritized.

| Milestone | Implemented path |
| --- | --- |
| Dependable delivery | Process-bounded prompt hooks, local custody-preserving fallback, per-session locks, explicit return markers, current capability manifests, authenticated working/prospective selectors, independent transcript recovery |
| Shared context budget | One composer for retrieval, profiles, knowledge, learned behavior and review requests; whole claims, qualifiers, source handles, explicit required overflow; receipts contain admitted items only |
| Semantic and temporal memory | Versioned exact-span proposals, named entities and conservative coreference, attributed beliefs, normalized relative dates, unresolved ambiguity, source-backed commitment changes, previewable direct-source backfill |
| Verified dreaming | Typed source-versioned review jobs, leases/retries, source-supported factual repair, bounded isolated pure-expression experiments, real output records, unchanged behavioral promotion gates |
| Maintained knowledge | Automatic topic discovery, source-linked claim views, persistent bounded cursors, deduplication and link repair, native publication guards, version checks, correction/expiry validation and erasure scrubbing |
| Transfer and utility | Versioned applicability contracts, validated provider role proposals, immutable historic task identities, exact-use outcome credit, randomized exposure records, guarded utility in selection before response, rollback retained |

The local host also uses atomic three-way merging for profile side-state and
commutative advisory metrics. Independent callers no longer need a global lock
that spans provider requests. Concurrent edits to the same profile value fail
instead of silently overwriting a correction or erasure.

## Evidence boundaries

Focused checks cover all new modules and the modified host/runtime seams,
including unauthorized/expired sources, intact negation, a 100-entry profile,
actual checker attribution, cross-session isolation, interrupted work, SQLite
publication concurrency and side-state merges. PostgreSQL SQL/guard behavior is
covered by focused repository checks; a live PostgreSQL deployment was not run.

The macOS rollout retains the original database/scripts in a private backup,
previews and applies eligible source backfill, records real hook return timing,
and checks the maintenance worker. Provider failure is recorded as degraded
local recall, not successful provider retrieval. Empty eligible backfill and
insufficient outcome evidence remain empty/insufficient; no facts, pages, trials
or success grades are manufactured to populate dashboards.

Existing long-running stdio clients need to reconnect to load changed modules.
The deployed hook and worker start fresh package processes. The JSON receipt
marks preparation, the host return marker proves the response was flushed, and
only an explicit bound use report proves acknowledgement/application. None of
these is a substitute for a successful real task outcome.

A future comparison should use the plan's matched real task streams. The
proposed p95 latency, delayed-success and repeat-error targets remain targets
until measured on those streams.

## Local rollout record

The combined focused result is 215 passing cases, with original failed-run
receipts retained and corrected cases rerun. One adjacent benchmark-style
fixture, `test_frozen_common_pretraining_serves_acquired_behavior_without_updates`,
expects an acquired procedure from synthetic `inspect` events without a command
or action. It was left unchanged, and the real-action requirement was preserved.

The actual current-turn hook replay returned 3,990 UTF-8 bytes in 9.876 seconds
using the degraded local path. This is a single observed delivery, not a p95
measurement. The direct-source backfill reviewed/applied all 11 eligible
retained sources and created zero new claims. Topic discovery completed without
inventing pages. Learning remains enabled with all 22 components active and no
open guard defects; the current retained data has not established new measured
behavioral improvements.

The old MCP stdio connection in this chat retained the retired global lock.
After stopping that stale process, the app reported `Transport closed` rather
than reconnecting automatically. The deployed fresh-process host and maintenance
worker are operational; this chat's native MCP connection requires a reconnect.

A separate fresh MCP stdio connection passed initialization, learning status,
and bounded preparation: 3,940 context bytes in 9.378 seconds on the local
fallback. This verifies the newly deployed MCP server; it does not claim the
older connection in this chat reconnected. An installed wheel also passed an
isolated SQLite capture/retrieval check with four source-backed claims.
