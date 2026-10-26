# Anonymized technical field journal

A memory engine can authorize output text yet still leak older private derivatives through graph
facts, explanations and model prompts. Bind every reusable derivative to the exact readable text
and current disclosure policy. Cache keys based only on object IDs are insufficient.

Rank position scores must not inherit cosine-confidence metadata. Verify no-op and transformed paths.
Evaluation isolation must cover environment-configured sidecars as well as primary data paths.
Stage database and WAL bytes with stability checks before opening a private SQLite connection.
Even a read-only connection to an original WAL database can create SHM files beside it. Original
sources must remain unopened by SQLite when byte-preserving evaluation is required.

Published comparison rows require identity, configuration and outcome verification. Recomputing a
score is not a new evaluation, and a sixth chart position need not be an ordinal quality ranking.

Corpus-aware retrieval can lose its advantage when a later local fallback reranker replaces
all scores with common-word overlap. Check candidate survival through fusion, reranking and
selection, not only whether each search route found the evidence.

Expose existing grounded answer contracts through public interfaces before building a second
reflection engine. Preserve provider pins, fixed budgets, signed scope, exact-source replay and
abstention. Read-only reflection must not turn generated answers into supporting evidence.

For account-backed development inference, isolate reader and judge, disable external tools,
retain model/usage/prompt receipts, and reject malformed judgments. Freeze dataset and code
identity for resume. A successful small smoke test is not a performance ranking.

Summarization needs two distinct checks: source custody before model input and
again before derived writes. Traverse ancestor evidence, not only immediate
children; a stale public child cannot launder a now-private ancestor. Ordinary
reads also need lineage checks, because preventing new writes leaves old summaries.

Identity normalization must not erase every non-ASCII letter into the same key.
Keep legacy ASCII identities stable while giving distinct Unicode labels distinct
generated keys. Mutable return values and retained input containers must not alias
stored entity access rules or audit payloads.

Erasing one source of synthesized prose differs from removing one corroborating
source of a structured assertion. The remaining source cannot establish which
parts of an unchanged summary it supports. Preserve an explicit incomplete marker
and withhold the derived text; purge the row once the last source disappears.

Treat external lexical evidence results as rankings over registered evidence. Rebuild text
and custody from the authoritative row, because adapter caches can outlive deletion
or omit lineage metadata. Clock-based permission expiry must invalidate result
caches even without a write.

Maintained answers require corpus freshness, not only citation freshness: a new correction
can invalidate an answer while its old source still exists. Keep generated answers outside
the evidence plane, and preserve failed-refresh fallbacks only after current-source replay.
Snapshot validation and publication need the same transaction against other database
connections. Recheck implicit clocks after saving, since time may change without any write.
Imported cached records need the same history projection, trust, historical cutoff and
source-ID validation as newly generated answers.

Durable background jobs need separate display state and attempt outcome. A provider failure
is not a legitimate no-answer result, and a retained good answer does not imply a successful
refresh. Leases fence publication rather than promising exactly-once inference. Revalidate
authority after expensive preparation and immediately before final writes; authorization
callbacks that emit audits must remain outside transactions, with a pure validator inside.

Verify permissions with the actual non-superuser application and worker roles. Foreign-key
cascades execute with table-owner privileges, so a restrictive DELETE policy can prevent
an authorized operation even when the caller has permission. Grant only the documented
derived-record targets and test that evidence and audit deletion remain denied.

Secret filters need narrow structural exceptions for validated content identifiers. A valid
source CID redacted in one part of a provider request but retained in another can break
custody replay; preserving every hash-like string would instead expose unrelated secrets.

Comparison receipts must account for native extraction/consolidation separately from the
common reader and judge. Share the final context budget, keep source dates inside it, retain
whole histories, and pin the native model files as well as package names. A held-out pilot
with a configured provider bridge does not reproduce a vendor's published benchmark.

Attempt markers are not process locks. A second evaluator must not interpret active work
as a crashed attempt, and interruption must cancel queued work while preserving receipts
from admitted calls. Hold an OS-backed lock through recovery and final publication; never
delete a lock file while another process might still hold its inode.

An evidence CID can identify a rejected write. Verify a live post-write source before
launching dependent correction, extraction or indexing work, and distinguish that
observation from a transactional exactly-once receipt. A failed immediate disk commit
must restore the in-memory source and audit state; keep cache epochs monotonic and do
not roll back a committed store merely because a later journal append fails.

Protect PostgreSQL read/merge/write operations with a row lock at the read. An unrelated
DDL lock can accidentally serialize one pair of writers while leaving privacy backfill
races open. Run tests with the restricted runtime roles: superuser fixtures hide both
missing cascade grants and missing RLS tenant context. Retain unique test tenants until
the disposable database is removed rather than granting destructive cleanup rights.

Fixed-offset local datetimes do not carry historical daylight-saving rules. Resolve each
calendar boundary and compare source timestamps as UTC instants; protect explicit
chronology from later relevance-ranking stages. Test the basic graph-free configuration,
not only an optional advanced retrieval path. Normalize JSON mapping keys where runtime
policy lookups use integer trust tiers so a restart preserves effective behavior.

Source identity labels are not document ownership. Legacy content-addressed evidence can
be shared by distinct source envelopes, and erasure is permanent. Growing-document
replacement therefore needs a scoped version registry and distinct revision retirement,
not a source-label scan followed by deletion.

## Source integrity continuation

Review of document replacement found a separate live retrieval defect: after
erasure, an active assertion could retain only an incomplete summary as support
and still disclose its text. Validate current source custody for projections,
including adapter-returned IDs and cached canary views. Preserve independent
support; do not treat provenance validation as semantic proof of a claim.

Atomic source groups require different implementation from existing deferred
flushes. Local groups snapshot state, SQLite owns one immediate transaction,
and PostgreSQL borrows one pinned connection. Nested failures must poison the
outer transaction; a nested context must not silently commit it. Provider work
belongs before publication. Preserve unchanged legacy hashes when adding an
optional segment identity, and keep legacy tombstone replay checks.

The ledger commits before the journal. Attempt all queued erasure effects even
when an earlier journal operation fails, and report the error without undoing
committed ledger state. A tenant journal cannot erase a shared CID while a live
copy remains in another branch. A source created and erased within one group
must not emit plaintext during post-commit journal processing.

A document-wide sensitivity increase must protect reused chunks as well as newly
written text; reordered boundaries can form sensitive data that individual chunks
do not reveal. Treat source metadata as another disclosure surface. Retrieval
must not change behavior based on evaluation process flags. Reproducibility
compares repeated current runs; non-regression compares matching data partitions.

Whole-book coverage needs an explicit source ledger, not a model's claim of
completion. Treat page/spine inventory, publisher TOC and inferred chapters as
different evidence. Preserve each original contribution when merging concepts;
split audit views instead of truncating merged evidence. Recheck imported success
flags against source text, and never approve an original that only a validation
copy repaired. Source accounting and literal quotation checks do not prove
exhaustive semantic understanding.
