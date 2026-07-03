# ADR 0001 — SqliteEngine per-tenant file isolation

- **Status:** Accepted
- **Date:** 2026-07-03
- **Phase:** Native Acceleration Program, Phase 2 (SqliteEngine / C2)
- **Deciders:** Mnemosyne engine team (phase2/sqlite-engine)
- **Spec:** `docs/superpowers/specs/2026-07-01-native-acceleration-design.md` (commit `31c50a5`)
- **Plan:** `docs/superpowers/plans/2026-07-02-phase2-sqlite-engine.md` (Task 13)

## Context

`SqliteEngine` is the third `MemoryEngine` backend (after `LocalMemoryEngine`
and `PostgresEngine`), targeting local-first / embedded deployments. The
production topology remains **Postgres-only**: a SqliteEngine seen in a
production topology is environment drift (drift check D — spec §7 final bullet,
§4.2 note). This ADR records the tenant-isolation model that replaces
Postgres Row-Level Security (RLS) in the local deployment, the at-rest / KMS
posture for the tenant DB and journal files, and the open secret-handling
question (Q-SEC-1) that the isolation model is filed under.

The design is fixed by spec §3 ("Storage: stdlib `sqlite3`, one file per
tenant") and §4.2 ("One file per tenant (`.mnemosyne/tenants/<tenant>.db`;
WAL, `synchronous=FULL`, integrity-check on open). Isolation:
tenant-id→file-path binding (ADR documents the RLS-vs-file model). GDPR delete
= file delete."). This ADR is the referenced document.

## Decision

### 1. One SQLite file per tenant is the RLS analog (OS-level isolation)

Postgres enforces tenant isolation *inside* one shared database via RLS
policies keyed on `tenant_id`; every query is filtered by the policy predicate
and a policy bug or a missing `WHERE tenant_id = …` is a cross-tenant leak
surface. SqliteEngine instead gives **each tenant its own database file** under
`root_dir`, named via a shared `safe_tenant_filename(tenant_id, suffix)` helper
(factored into `journal.py` in Phase 2 Task 2, reused for both the `.db` file
and the CID journal). The isolation boundary is therefore the **operating
system's file-path boundary**, not an in-query predicate:

- A connection is opened against exactly one tenant's file
  (`SqliteEngine._connect(tenant_id)`); a query physically cannot observe rows
  belonging to another tenant because those rows live in a different file that
  the connection never attaches. There is no shared table for a predicate to
  fail to constrain.
- The `tenant_id` column is still stored and still part of every uniqueness
  key (evidence `UNIQUE(tenant_id,branch,cid)`, etc.), so exports and the
  cross-engine parity oracle stay byte-compatible with the RLS-scoped engines;
  but correctness of isolation does not *depend* on that column being filtered
  — it is defense-in-depth on top of the file boundary.
- Hostile tenant ids (path separators, `..`, absolute paths, reserved names)
  are neutralized by `safe_tenant_filename` before they ever touch the
  filesystem (tested with hostile ids in Task 2), so the tenant-id→file-path
  binding cannot be steered outside `root_dir`.
- **GDPR "delete a tenant" = delete the tenant's file** (spec §4.2). There is
  no cross-tenant vacuum or row sweep to get wrong.

The ops-check surface encodes this equivalence: `auth-ops-check` accepts
`tenant_isolation.sqlite_file_per_tenant: true` as the RLS-analog requirement
key (Phase 2 Task 12), profile-scoped so a **production** bundle asserting a
sqlite backend still FAILS (production stays Postgres+RLS; guard tests pin
this).

### 2. At-rest / KMS posture — local-first deviation documented and accepted

Spec §4.0 (CID journal) and §7 require that "journal and tenant DB files
participate in the deployment's at-rest encryption/KMS model so
`hard_delete_legal` can key-shred (or an ADR explicitly documents and accepts
the local-first deviation)."

**Decision:** for the local-first / embedded deployment, SqliteEngine does
**not** implement application-level at-rest encryption or KMS-backed
key-shredding of the tenant `.db` / journal files. We **accept the local-first
deviation**, on these grounds and with these compensating controls:

- **Boundary of custody.** In the local-first profile the files live on the
  operator's own machine; the at-rest confidentiality control is the host's
  full-disk / volume encryption (e.g. FileVault/LUKS), which is outside this
  engine's trust boundary and is the deployment's KMS-equivalent. When
  SqliteEngine is embedded in a managed deployment, the enclosing deployment is
  expected to place `root_dir` on an encrypted volume; that satisfies "files
  participate in the deployment's at-rest model" without the engine holding key
  custody.
- **`hard_delete_legal` still erases, without key-shred.** Because there is no
  per-tenant/per-record encryption key to destroy, legal deletion is performed
  by **physical row DELETE + journal purge** rather than by shredding a key:
  `hard_delete_legal` DELETEs the evidence rows, `CIDJournal.purge(cid)` drops
  the journal record, retained deletion/compaction/watermark records replace
  the erased CID with an HMAC/random placeholder (see §3 below), and the
  embedding-cache rows are purged. Post-erasure parity holds: ledger rebuild ≡
  journal rebuild in both modes (Task 9). The property the spec's key-shred was
  protecting — that no confirmable copy of erased content survives in engine
  artifacts — is met by exclusion, verified by the L4 poison corpus and
  privacy test class 13 (`sha256(guess)` finds no confirmation post-erasure).
- **Residual risk (accepted).** Without at-rest encryption, `.db`/journal
  bytes on an *unencrypted* volume are readable by anyone with filesystem
  access, and DELETE does not guarantee the bytes are overwritten in the SQLite
  page file / WAL (SQLite may leave freed pages until VACUUM). This is the
  explicit local-first deviation being accepted; the mitigation is host-level
  volume encryption + `VACUUM` on legal delete where the deployment requires
  media sanitization. A managed/production deployment does NOT rely on this —
  it uses Postgres, whose at-rest/KMS posture is unchanged by this ADR.

Privacy-ops-check-style shred verification (spec §4.0) is therefore scoped, in
the local profile, to **verifying exclusion** (row gone, journal purged, cache
purged, no honeytoken reappearance) rather than key destruction.

### 3. Secret-handling policy — Q-SEC-1 reference

The tenant-isolation and at-rest posture above sit under the open
secret-handling question **Q-SEC-1** (spec §4.4 line 132; Phase-5 ADR item
§8 line 187: "Q-SEC-1 custody posture"). Q-SEC-1 governs the secret-handling
taxonomy / custody classes (session-verifier custody held Python-side, the C4
loopback listener as a service-credential-class secret, "fingerprints only —
no content/secret logging" per secret-handling P4, spec §7 line 176). For
SqliteEngine specifically:

- The tenant `.db` files and CID journal are **content-at-rest**, not secrets
  in the credential sense; they are covered by the file-isolation + host at-rest
  model above, not by the session/credential custody path.
- Honeytoken leak canaries are seeded across the new boundaries (journal,
  embedding cache, benchmark output) per spec §7; appearance fires the privacy
  §10 alarm. Benchmark artifacts and journals are guarded (Phase 0 Task 12).
- Erased CIDs in retained records are replaced with HMAC/random ids via
  `erasure_ids.py` so retained deletion-log rows are not a `sha256(guess)`
  oracle — this is the deletion-log HMAC work that Q-SEC-1's "no confirmable
  residue" posture depends on (privacy invariant 13, §7 line 174).

The final Q-SEC-1 custody posture (which secret classes are custodied where,
across C3/C4) is resolved in the Phase-5 docs pass (spec §8) and in the C4 ADR;
this ADR references it and scopes only the SqliteEngine file/at-rest surface.

## Ledgered spec > shipped gaps (accepted, oracle-first)

Two places where the shipped SqliteEngine intentionally follows the
`LocalMemoryEngine` parity oracle rather than the spec's broader aspiration.
Both are recorded in `.superpowers/sdd/progress.md` and re-stated here so the
ADR is the durable home:

1. **Erase-all-branches (spec §4.2 / §7 "propagates to all branches" vs shipped
   single-branch-scoped).** Spec §4.2 says erasure "propagates to all branches
   in the tenant file." The shipped `forget` matches `LocalMemoryEngine`, which
   is **single-branch-scoped** (erases within the targeted branch). Phase 2
   Task 9 verified Local's cross-branch behavior first and matched it
   (oracle-first discipline: the parity oracle wins over the spec's aspiration
   to avoid diverging the third engine from the other two). The spec>shipped
   delta is accepted and ledgered; closing it to true all-branch propagation is
   a cross-engine change (Local + Postgres + Sqlite together) deferred to a
   future phase, not a silent SqliteEngine-only divergence.

2. **Async telemetry deferred — `_record_retrieval_access` is synchronous.**
   Spec's async-telemetry optimization for retrieval-access accounting is
   **not** implemented; SqliteEngine's `_record_retrieval_access` performs a
   **synchronous** write matching the shipped `LocalMemoryEngine` /
   `PostgresEngine` behavior (Phase 2 Task 7). Parity with the shipped engines
   wins; the async optimization is documented as deferred in the engine
   docstring and here.

## Consequences

- **Positive:** isolation correctness reduces to the OS file boundary (no RLS
  policy to misconfigure locally); GDPR tenant delete is an `rm`; the model is
  auditable via `auth-ops-check` `sqlite_file_per_tenant`.
- **Negative / accepted:** no engine-level at-rest encryption or key-shred in
  the local profile (host volume encryption is the compensating control);
  legal delete relies on row DELETE + journal purge + optional VACUUM, not key
  destruction; SQLite freed pages may retain bytes until VACUUM.
- **Production unaffected:** production remains Postgres + RLS with its existing
  at-rest/KMS posture; a sqlite backend in a production bundle still fails the
  ops-check guards (drift check D).

## References

- Spec §3 (decision record, lines 35, 103), §4.0 (CID journal + at-rest
  posture, line 85), §4.2 (C2 SqliteEngine, lines 101–118), §4.4 (Q-SEC-1
  reference, line 132), §7 (security & privacy invariants, lines 169–178),
  §8 Phase-5 (ADR deliverables, line 187).
- Plan `2026-07-02-phase2-sqlite-engine.md` Task 12 (ops-check RLS-analog key),
  Task 9 (erasure wiring, deletion-log HMAC), Task 13 (this ADR).
- `.superpowers/sdd/progress.md` — P2 Task 7 (synchronous `_record_retrieval_access`),
  Task 9 (branch-propagation matches Local single-branch; cross-engine
  deletion-log HMAC / invariant-13 fix `f363c7c`).
- `src/mnemosyne/erasure_ids.py` (salted-hash / HMAC placeholder producers).
