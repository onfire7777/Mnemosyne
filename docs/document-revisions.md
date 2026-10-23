# Atomic document revisions

`mnemosyne.documents.DocumentService` keeps a private, growing text document
current without losing history or leaving stale derived memories in recall. It
runs on the Local, SQLite and PostgreSQL engines and never calls an embedding or
model provider during publication.

```python
from mnemosyne.answering import AnswerReadContext
from mnemosyne.documents import DocumentService

ctx = AnswerReadContext(tenant_id="t1", user_id="alice", role="agent")
docs = DocumentService(engine)
r1 = docs.create(ctx, "handbook", "Always use amber.\n\nDelivery is Friday.\n\n", operation_id="op-1")
r2 = docs.replace(ctx, "handbook", "Always use amber.\n\nDelivery is Monday.\n\n",
                  operation_id="op-2", expected_revision=r1.revision)
r3 = docs.append(ctx, "handbook", "New office opens in May.", operation_id="op-3",
                 expected_revision=r2.revision)
view = docs.get(ctx, "handbook")  # DocumentView(revision=3, content=..., segment_cids=...)
```

The service accepts an already authenticated `AnswerReadContext`; it is not an
authentication boundary. There is no MCP tool for documents yet.

## Semantics

- **Lossless segmentation.** Text is split into paragraph segments (blank-line
  separators belong to the preceding paragraph; long paragraphs split at exact
  code-point boundaries). Concatenating the segments reproduces the input.
- **Occurrence reuse.** An unchanged paragraph keeps its source CID across
  revisions; duplicates are matched once each. Changed or removed segments are
  **retired** (`Evidence.retired_at`), not erased: they leave current recall
  (lexical, vector, `retrieve`, `graph_as_of` and summary capture) along with
  derived facts and summaries that depend on them, while staying in the ledger
  for audit. Returning to old text creates a fresh occurrence; a retired
  source is never reactivated.
- **Atomic publication.** Source admission, revision CAS, retirement and the
  operation receipt commit inside one native `source_transaction`. A failure at
  any step rolls back all new sources and retirements.
- **Revision CAS and idempotency.** `replace`/`append` require
  `expected_revision`. The most recent `operation_id` can be retried exactly and
  returns the same receipt; any earlier or mismatched reuse is rejected. Request
  hashes of superseded operations are dropped to avoid a private-text oracle.
- **Exact append.** `append` concatenates the suffix with no separator.
- **Owner scope.** Documents are keyed by tenant, branch, owner and document ID.
  Source identity labels cannot impersonate an owner. Readers cannot write;
  break-glass and historical (`as_of`) contexts are refused.
- **Trust and privacy.** A lower-trust writer cannot replace or extend a document
  created with stronger trust (no trust laundering). Tier-5 writers' segments
  are tagged `data-only`/`no-write-authority`. PII raises the document and new
  segments to sensitivity 3, monotonically; content whose sensitivity would exceed
  the writer's own read ceiling is refused before any source is written.
- **Bounds.** Content length (`max_content_chars`, default 2,000,000), segment,
  retired-segment and receipt counts (100,000 each) are checked before writes.
  Stored manifests validate setting types and ranges.
- **Reads re-check custody.** `get` re-reads the manifest and every source after
  assembly; a concurrent edit, retirement or quarantine raises `DocumentConflict`
  instead of returning revoked plaintext.
- **Erasure.** `forget` remains permanent erasure. Erasing a document's sources
  scrubs their CIDs from the manifest; once no active segment remains the
  document is marked deleted and cannot be recreated under the same ID.

## Migration

SQLite migrates itself. Existing PostgreSQL deployments need an administrator to
apply the additive changes in `sql/schema.sql` and `infra/postgres/roles.sql`:

```sql
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS retired_at TIMESTAMPTZ;
-- plus the `documents` table, its RLS policy, and:
GRANT DELETE ON documents TO mnemosyne_app;
```

## Not yet implemented

Automatic model extraction of facts from new segments needs a durable,
crash-safe job queue and is intentionally out of scope. Branch merge rules for
documents and an MCP transport are also pending.
