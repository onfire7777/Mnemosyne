# Source identity and atomic updates

The three native engines provide `source_transaction(tenant_id, branch="main")`
for a small group of source operations. It supports `append_evidence`,
`get_evidence`, `update_evidence_metadata` and branch-local `forget`. The group
commits once, or rolls back its source rows, derived erasure changes and audit
records together. A failure in a nested operation aborts the whole group even
when its immediate exception is caught.

```python
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence

with LocalMemoryEngine("memory.json") as engine:
    with engine.source_transaction("example"):
        cid = engine.append_evidence(Evidence(
            tenant_id="example", user_id="owner", actor="user",
            source_type="document", content="The observatory opens on Tuesday.",
            document_segment_id="document-42/generation-1/segment-1",
        ))
        if engine.get_evidence("example", cid) is None:
            raise RuntimeError("Source admission was rejected")
        engine.update_evidence_metadata("example", cid, {"reviewed": True})
```

A returned CID alone is not an admission receipt: self-generation limits and
erased-source replay protection can reject a write. Check the authoritative row
before publishing related state. Nested transactions must use the same tenant
and branch. Ingestion pipelines, queues, branch management, other engine
mutators and mental-model publication guards are outside this boundary.
Prepare provider results before entering it. PostgreSQL permits its local
hashing embedder or a supplied vector, and rejects calling an external embedding
provider inside the transaction.

Local storage holds its engine lock, snapshots the affected state, and publishes
one atomic file replacement. SQLite uses `BEGIN IMMEDIATE`; PostgreSQL pins one
connection and takes the existing tenant advisory lock. Ordinary callers using
other PostgreSQL operations do not automatically participate in that advisory
lock. A transaction does not replace application-level revision validation.

Journals are secondary copies. Their updates occur after the ledger commits,
and a journal I/O error does not undo a committed ledger. Recovery must reconcile
the journal against that ledger. Local erasure now tombstones or purges journal
records as well; creating and erasing a source in one group does not publish its
plaintext to the journal.

## Optional immutable segment identity

`Evidence.document_segment_id` identifies a particular segment generation. It
is a caller-assigned optional string of 1–256 ASCII identifier characters: letters, digits,
period, underscore, colon, slash and hyphen, starting with a letter or digit.
Use an opaque value, not source text or a secret. It participates in the CID
together with the owner, even for nonsensitive content. Equal text in different
segments with distinct IDs or under different owners therefore receives different CIDs.

When omitted, the legacy CID payload and serialized evidence shape remain
unchanged. The engine preserves the identity across persistence and branch
copies; metadata edits cannot replace it. A tombstoned segment blocks identical
content/CID replay for that generation and owner; changed text under the same
identifier can produce a different CID. No generation registry enforces content
stability yet. Existing legacy tombstones still block replay
through a newly supplied identity.

SQLite applies an additive column migration when opening a writable database;
legacy read-only databases remain readable. Existing PostgreSQL installations
need an administrator to apply the additive migration in `sql/schema.sql`
before further appends, including appends without a segment ID:

```sql
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS document_segment_id TEXT;
```

## Remaining document lifecycle work

These are storage primitives, not a finished document synchronization service.
There is no document registry, append/replace MCP tool, revision CAS, durable
operation receipt, document-level deletion marker or automatic delta extraction
in this layer. The caller remains responsible for source ownership and policy.

Permanent `forget` is an erasure operation, not revision retirement. A complete
growing-document service still needs active revision membership, nondestructive
retirement, shared-support revalidation, branch merge rules and coordinated
extraction/index jobs. A fresh segment ID must never be used to bypass a future
document deletion marker.
