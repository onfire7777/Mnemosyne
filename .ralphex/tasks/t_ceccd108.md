# W2 D4 secure deletion coordinator recovery

Authoritative base: `5677676758bfffa4d9920d86ec4409eab0728562`.

Rejected implementation evidence (read-only):
- branch `wt/t_ceccd108` at `4d7f0be64a857ab371e2b22a7feba19a1d194d52`
- worktree `/Users/admin/Mnemosyne/.worktrees/t_ceccd108-rejected-4d7f0be`
- do not copy its import monkeypatches, caller-controlled fences, substring scrubber, fake rollback, or unverified receipts

Allowed files:
- `src/mnemosyne/deletion.py`
- `tests/completion/security/test_deletion_residue.py`

Forbidden files:
- Local, SQLite, or PostgreSQL engine source files
- `src/mnemosyne/deletion_manifest.py` (D5 owns the durable SQLite ledger, signing, and semantic verifier)
- shared public harness, GSD state, protected evidence, dependencies, network calls, push, or merge
- skips, xfails, weakened assertions, global monkeypatches, caller-authorized legal deletion, raw payload substring scrubbing, or claims that synthetic probes are production evidence

### Task 1: Repair the RED contract and add rejection regressions

- [x] Correct only invalid test fixtures: use an existing working-memory kind, matching source/session provenance, an explicit `as_of` clock, and `Evidence.to_dict()` instead of a slots-incompatible `__dict__` assumption.
- [x] Replace the impossible cross-store rollback assertion with a forward-only resumable saga assertion: a verified deletion stays deleted, the engine remains until prerequisites verify, and retry skips verified surfaces.
- [x] Preserve the R05 security intent by requiring provenance-only cascade. Legal-blind derived payloads containing the deleted source must be absent; never accept raw substring replacement as recomputation.
- [x] Add literal regressions for same-operation/different-request conflict, forged high fence rejection, cross-tenant isolation, unknown branch rejection, delete-without-probe rejection, timeout-after-commit convergence, import side-effect absence, and concurrent same-operation serialization.
- [x] Extend the synthetic store with independent residue probing and explicit delete/probe fault modes. A successful delete return must never equal verified absence.

### Task 2: Implement the forward-only authenticated deletion saga

- [x] Add a small explicit coordinator with reusable protocols for deletion ledger, store delete/probe, and branch enumeration. Reuse `SessionIdentity`, `SecurityPolicy`, existing engine `forget`, and `erasure_ids`; add no dependency or parallel lifecycle framework.
- [x] Require a verified session identity and destructive-write authorization. Bind tenant ownership/legal override policy to that identity; validate UUID operation ID, nonempty deduplicated source refs, schema, mode, user, and exact `main|all` branch scope before effects.
- [x] Bind idempotency to a canonical request fingerprint. Same operation plus same request replays exactly; same operation plus any different tenant/user/source/branch/mode conflicts.
- [x] Use a shared ledger with lock/CAS semantics, tenant generation, per-surface `pending -> deleting -> deleted -> verified|failed` receipts, attempts, checkpoints, and honest `durable=false` for D4's in-memory implementation. D5 will supply the concrete durable SQLite ledger before final integration.
- [x] Run a forward-only resumable saga. Never resurrect a verified remote deletion. Persist every exception as incomplete, skip verified steps on retry, keep the engine until required external probes pass, and verify engine absence after its final step.
- [x] Derive cascade only from explicit CID provenance and existing engine erasure. Do not scan or rewrite unrelated strings and do not restore synthetic Evidence subclasses.
- [x] Produce keyed non-confirmable opaque references and truthful counts. Unknown, unavailable, unprobed, immutable, or failed surfaces remain incomplete; no payload, direct tenant/user/source identifier, URI, hash, canary, or fabricated precondition may appear.
- [x] Remove caller-authoritative generation checks from restore/write guards. Guard methods must query the shared ledger's current fence and require an internally issued capability; forged integers cannot authorize resurrection.

### Task 3: Adversarial review and cleanup

- [ ] Review all D4 changes against the independent rejection findings and the D4/D5/D6 ownership boundary.
- [ ] Prove import leaves engine allowlists and methods unchanged; prove unrelated same-tenant content and identical cross-tenant content remain byte-identical.
- [ ] Prove crashes/exceptions at each synthetic saga transition return or persist an incomplete resumable state rather than a success or a stuck unrecorded operation.
- [ ] Keep `.ralphex` control metadata ignored and untracked, document synthetic-only evidence boundaries in code/tests, and leave the worktree clean.

Validation:
- `python -m pytest -q tests/completion/security/test_deletion_residue.py -k 'r03 or r04 or r05 or r06 or r07 or r08 or r09 or r10 or r11 or r12 or r13 or r14 or r15 or r16 or r17 or r18 or r19 or r20 or r22 or r23 or r24 or replay_conflict or forged or import_side_effect or concurrent or probe or timeout'`
- `python -m pytest -q tests/test_working_memory.py tests/test_working_memory_api.py tests/test_working_memory_retrieval.py tests/test_sqlite_working_memory.py tests/test_sqlite_erasure.py`
- `ruff check --quiet src/mnemosyne/deletion.py tests/completion/security/test_deletion_residue.py`
- `git diff --check`

Run plan, task, review, fallback, and every auxiliary/reviewer role only with `gpt-5.6-sol:low`. Keep auto-completion disabled until a fresh independent Sol-low review accepts the exact head.
