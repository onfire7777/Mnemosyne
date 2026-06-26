# Mnemosyne — Code-Completion Coordination & Task Map

**Date:** 2026-06-23
**Type:** Code-completion coordination for `src/` + `tests/` + `sql/`. **This is a CODING coordination plan** — distinct from `OPS-HANDOFF-AND-OWNERSHIP.md` (ops lanes A–G, markdown/deploy artifacts) and from the active **policy / indexing / lifecycle / docs** agents (markdown in `docs/` and `.planning/`).
**Owned by:** the Coordinator (this file). Read-only to all execution lanes; only the Coordinator + Sync lane edit it.
**Scope source (do not recompute):** `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`, `REVIEW.md` (status: `remediated`), `.planning/ROADMAP.md` Phase 6.

---

## 0. Operating constraints (enforced)

1. **No new agents or terminals.** Execution is done by **existing idle agents only**, one lane each.
2. **One area per agent. No overlapping edits.** A lane MAY *read* any file; a lane MUST NOT *write* a file outside its owned set.
3. **One Sync agent only.** Repo update + GitHub alignment is delegated to a single lane (§4), never spread across lanes.
4. **Code lanes never touch policy/doc artifacts** (the active agents own those); doc/policy lanes never touch `src/`. This is the primary cross-effort non-overlap guarantee.

---

## 1. Repo reality (verified 2026-06-23)

- Repo: `/Users/admin/Mnemosyne` → `origin = github.com/onfire7777/Mnemosyne`. Branch `main` is **in sync** with `origin/main` (no ahead/behind).
- Untracked WIP (belongs to sibling lanes — **their owners commit, not Sync, not code lanes**): `.planning/INDEXING-AND-RETRIEVAL-POLICY.md`, `CONFIG-DRIFT-CHECKS.md`, `Mnemosyne-Secret-Handling-Policy.md`.
- `REVIEW.md`: 9/9 findings remediated @ `fe72a66`. **Remaining = Phase 6 parity + production hardening**, not bug-fixing.
- Test gate: full local suite **354 passing + 63 skipped live-DB**. Run: `uv run pytest` (live-DB tests need `MNEMOSYNE_POSTGRES_DSN`).

---

## 2. Task map — code-completion lanes (one idle agent each)

Each lane owns a **disjoint** set of source files + the matching tests. The "Assigned agent" column is filled by the orchestrator when binding lanes to specific idle panes (see §6).

| Lane | Area | Owns (write scope) | Focus (remaining work) | Owns these tests | Assigned agent |
|---|---|---|---|---|---|
| **CC‑R** | Retrieval & providers | `src/mnemosyne/retrieval.py`, `src/mnemosyne/benchmarks.py`, **new** `src/mnemosyne/providers/**` | External embedding + cross-encoder reranker integration behind existing boundaries; lexical/dense/graph fusion polish; ParadeDB/BM25 adapter seam (CR‑06 residual) | retrieval-channel contract tests | _(unbound)_ |
| **CC‑PG** | Postgres backend & schema | `src/mnemosyne/postgres_engine.py`, `src/mnemosyne/postgres_runtime_state.py`, `sql/schema.sql` | Production pgvector + tenant-scoped `graph_ppr`, AGE/specialist graph adapter seam, branch/merge/discard edge cases, schema parity | `tests/test_postgres_engine_live.py`, Postgres side of `tests/test_shared_engine_contract.py` | _(unbound)_ |
| **CC‑RT** | Runtime surface (MCP / CLI / engine protocol) | `src/mnemosyne/mcp_server.py`, `src/mnemosyne/mcp_tools.py`, `src/mnemosyne/engine.py`, `src/mnemosyne/cli.py`, `src/mnemosyne/__init__.py` | Promote `RuntimeMemoryEngine` protocol + substitutability typing (WR‑03); MCP stdio lifecycle + real protocol tests (WR‑02) | `tests/test_runtime_surfaces.py`, `tests/test_engine_contract.py`, `tests/test_cli_runtime_tools.py` | _(unbound)_ |
| **CC‑BC** | Belief / calibration / consolidation / graph | `src/mnemosyne/belief.py`, `src/mnemosyne/calibration.py`, `src/mnemosyne/consolidation.py`, `src/mnemosyne/graph.py` | Phase 2/3 parity: RAPTOR/gist refresh, calibration tuning, consolidation society-of-roles polish | `tests/test_belief_and_calibration.py`, `tests/test_blueprint_later_phases.py` | _(unbound)_ |
| **CC‑LS** | Learning / self-optimization / policy / eval | `src/mnemosyne/self_optimization.py`, `src/mnemosyne/parametric.py`, `src/mnemosyne/policy.py`, `src/mnemosyne/eval.py` | Phase 4/5 residuals: shadow optimizer, policy-ops gates, regression-suite breadth controls, eval harness | `tests/test_self_optimization.py`, `tests/test_learning_and_attack_suite.py` | _(unbound)_ |
| **CC‑UPS** | User model / privacy / security / ingest | `src/mnemosyne/user_model.py`, `src/mnemosyne/privacy.py`, `src/mnemosyne/security.py`, `src/mnemosyne/source_truth.py`, `src/mnemosyne/attack_suite.py`, `src/mnemosyne/media.py`, `src/mnemosyne/ingestion.py` | Privacy erasure-path hardening (code side of the Privacy policy), user-model guards, capability/taint security, source-sync | `tests/test_user_model_and_guards.py`, `tests/test_nfrs_and_schema.py` | _(unbound)_ |

**Cross-effort boundary:** none of these lanes write `docs/**/*.md`, `.planning/*.md` (except their own test fixtures), or the ops A–G artifacts. CC‑UPS *reads* the Privacy policy doc but does not edit it; the policy lane owns the spec, CC‑UPS owns the code.

---

## 3. Shared / frozen files (coordinator-gated)

These are cross-cutting; uncontrolled edits here are the #1 merge-conflict source. **No lane edits them unilaterally.**

- `src/mnemosyne/models.py` — shared data model. **Frozen.** Need a field? File a change-request (§5.4); Sync applies it in a single serialized commit; all lanes rebase.
- `src/mnemosyne/engine.py` — owned by **CC‑RT** (protocol promotion is its job). Other lanes treat it **read-only** and request changes through CC‑RT.
- `src/mnemosyne/runtime_state.py`, `jobs.py`, `queue.py`, `observability.py` — infra shared by jobs/consolidation. **Frozen** unless a single lane is explicitly granted it by the Coordinator for a specific task.
- `pyproject.toml`, `uv.lock` — dependency changes go through **Sync only** (serialized), so the lockfile never conflicts.

---

## 4. Sync / Integration lane — **one agent, the only one that touches `origin` and `main`**

**Lane CC‑SYNC** (assign to exactly one idle agent). It does **not** author feature code. Responsibilities:

**4.1 Bring local up to date (run first, once):**
```
git -C /Users/admin/Mnemosyne fetch origin
git -C /Users/admin/Mnemosyne status -sb          # confirm: main...origin/main (in sync)
git -C /Users/admin/Mnemosyne switch main && git -C /Users/admin/Mnemosyne pull --ff-only origin main
```
Do **not** commit the 3 untracked sibling-lane files — ping their owners to commit on their own lanes.

**4.2 Per-lane integration (serialized, one lane at a time):**
```
# lane works on its own branch off latest main:
git switch -c lane/<CC-XX> origin/main
# ... lane commits only its owned files ...
# Sync integrates:
git fetch origin
git switch lane/<CC-XX> && git rebase origin/main      # rebase, keep history linear
uv run pytest                                          # GATE: 354 pass + 63 skip, no regression
gh pr create --base main --head lane/<CC-XX> --fill    # normal PR workflow
# after green CI + review:
gh pr merge --squash --delete-branch
```

**4.3 Cadence:** integrate in priority order (CC‑PG → CC‑RT → CC‑R → CC‑BC → CC‑LS → CC‑UPS) so backend/protocol land before dependents. One PR open to `main` at a time → zero concurrent-merge races.

**4.4 Commit this coordination file** on the Sync branch in its first pass.

---

## 5. Merge & conflict-avoidance plan

1. **Branch-per-lane.** Every lane works on `lane/<CC-XX>` off the latest `origin/main`. No lane commits to `main`.
2. **Disjoint file ownership (the lock contract).** §2 + §3 are the lock table. A lane editing a file it doesn't own is a protocol violation — revert and route through the owner. This makes most merges **textually conflict-free by construction**.
3. **Serialized integration to `main`.** Only CC‑SYNC merges, one PR at a time, **rebased on `main`** immediately before merge → linear history, no merge-commit tangles.
4. **Change-request protocol for shared/frozen files.** A lane needing a `models.py`/`engine.py`/infra change posts a one-line CR to the Coordinator (file + reason + proposed diff). Sync (or the owning lane, for `engine.py`) applies it in a dedicated serialized commit; all open lane branches `git rebase origin/main` before continuing.
5. **Test gate every merge.** `uv run pytest` must stay green (354 pass + 63 skipped live-DB; live-DB via compose DSN before a Postgres-touching merge). No merge that regresses the suite.
6. **Idle-collapse / scaling.** If fewer idle agents exist than lanes, merge adjacent lanes in this order and keep "one area per agent": `{CC‑R+CC‑PG}` → "retrieval+backend", `{CC‑BC+CC‑LS}` → "learning core", `{CC‑RT}`, `{CC‑UPS}`, plus CC‑SYNC. Minimum viable = **2 agents** (one combined code lane + CC‑SYNC). Never split one file across two agents.

---

## 6. Binding lanes to idle agents (orchestrator action)

This environment cannot enumerate the idle panes (no `tmux`; spawning is disallowed). To finalize, the orchestrator/user fills the **Assigned agent** column in §2 + §4 with the real pane handles (e.g., `pane-2 → CC‑PG`). Until bound, lanes are claimed first-come by idle agents reading this file, each editing only the **Assigned agent** cell of the single lane it claims (the one sanctioned edit to this file by a non-Coordinator).

---

## 7. Definition of done

- [ ] Every code-completion lane bound to exactly one idle agent (§2/§6), disjoint ownership confirmed.
- [ ] CC‑SYNC has run §4.1 and reports `main` in sync with `origin/main`.
- [ ] Each lane's branch merged via §4.2 with the test gate green; no cross-lane edits occurred.
- [ ] Phase 6 parity + hardening items closed against `STRICT-BLUEPRINT-PARITY-AUDIT.md`.

## 8. Flags for owners (not this lane's to fix)

- Duplicate audit artifact in `.planning/`: `v1.0-MILESTONE-AUDIT.md` **and** `vv1.0-MILESTONE-AUDIT.md` (likely typo). → docs lane.
- 3 untracked sibling-lane files (§1) are uncommitted. → their owning policy/indexing lanes should commit.
