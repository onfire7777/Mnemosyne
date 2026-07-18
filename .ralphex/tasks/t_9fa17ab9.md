# t_9fa17ab9 — Local working-memory implementation

Authoritative requirement: `docs/superpowers/plans/2026-07-15-W3-taxonomy-completion-plan.md:88-100` and the frozen contract in the parent handoff. Implement only the Local working-memory model/protocol/store/TTL/audit/provenance behavior and focused Local tests.

Allowed write set:
- `src/mnemosyne/engine.py`
- `tests/test_working_memory.py`

Forbidden/shared files:
- All other repository files, including `src/mnemosyne/models.py`, `src/mnemosyne/gate.py`, SQL/schema files, retrieval/pipeline files, planning state, and documentation.
- Do not implement Phase 4 retrieval integration or alter existing durable-memory behavior except the required working-memory erasure cascade/persistence compatibility.

Acceptance criteria:
- Add `WorkingMemoryItem`, Protocol methods `put_working`, `get_working`, `list_working`, and `expire_working` with composite tenant/session/item identity.
- Enforce explicit aware UTC clocks, half-open TTL with inclusive 24-hour cap, detached returns, deterministic ordering, monotonic logical expiry, exact-once deterministic audits, and atomic rollback on audit/persistence failures.
- Enforce tenant/user/session/provenance/trust/capability/access-policy rails; no auto-promotion; preserve explicit existing PromotionGate-only promotion semantics and regression denial behavior.
- Persist/load Local working items and cascade erasure of sole provenance without leaking erased provenance.

Validation commands:
- `git diff --check`
- `.venv/bin/ruff check --quiet src/mnemosyne/engine.py tests/test_working_memory.py`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_working_memory.py tests/test_prospective_memory.py`

### Task 1: Implement Local model and protocol
- [x] Add validated `WorkingMemoryItem` and Local composite-key storage with persistence/load support.
- [x] Add exact working-memory methods to `MemoryEngine` and `LocalMemoryEngine`.

### Task 2: Implement rails and lifecycle
- [ ] Add provenance validation, effective trust/capability/sensitivity/access-policy derivation, deterministic TTL visibility/expiry, audit custody, and rollback.
- [ ] Integrate working-item erasure cascade without changing the existing durable-memory contract.

### Task 3: Verify focused behavior
- [ ] Add focused regression tests covering model validation, TTL boundaries, isolation, detached values, audit idempotency, rollback, erasure, and no auto-promotion.
- [ ] Run the focused validation commands and reconcile the final lease-clean diff.
