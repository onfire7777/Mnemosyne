# Mnemosyne — Rollback Guidance & Anti-Patterns

> **Lane scope.** This document covers **when to decide a rollback, how to roll back safely on Mnemosyne's substrate, and what to never do.** It is a decision-and-pattern guide, not a procedure list.
>
> **What this lane does _not_ own (read those first):**
> - **Deployment & operations runbook** (Build Blueprint **§32**) — the mechanical steps to deploy/redeploy a binary, cut over infra, run a schema migration, or restart the consolidator/MCP fleet. This doc tells you *whether* to revert and *how to keep the revert safe*; the runbook tells you *which commands to run*.
> - **Validation / promotion-gate checklist** (Build Blueprint **§23.4, §33**) — the pre-promotion gate criteria and the final go/no-go checklist. This doc *consumes those criteria as rollback triggers* but does not redefine them.
>
> If a sentence here starts to read like a runbook step or a gate checkbox, it belongs in one of those lanes, not this one.

---

## 0. The one thing to internalize first

Mnemosyne is **not a stateless service**, and rollback here is **not "restore the last snapshot."** The substrate makes rollback structurally different from an ordinary stateful system:

- The **evidence ledger is append-only and content-addressed** (I3, I5). It is the thing you roll *back to* — never a thing you roll back.
- **Learned changes** (policies, procedures, lessons, consolidation passes) live on **branches**. Rollback = **discard the branch** — clean and transitive by construction (I3, §30.6).
- **Facts/beliefs** are **supersede-only** and justification-tracked (I2). A wrong belief is rolled back by a *forward* **revision or contraction** through the belief core — not by deletion.
- **Projections** (typed indexes, graph, embeddings) are **rebuildable** from the ledger. They are caches, not source of truth.

Almost every rollback anti-pattern below is a special case of forgetting one of these four facts and treating Mnemosyne like a normal stateful app.

---

## 1. Identify the rollback surface before anything else

There is no single "roll back Mnemosyne" action. Name the surface first — the safe pattern and the decision criteria differ per surface.

| # | Surface | What changed | Safe rollback primitive | Reversible by construction? |
|---|---------|--------------|--------------------------|-----------------------------|
| S1 | **Learned policy / procedure / lesson** (Phase 4–5) | A promoted candidate (routing weights, thresholds, workflow, skill) | **Discard the canary branch** (§30.6) | Yes — transitive |
| S2 | **Belief / fact** (semantic store) | A consolidation pass or ingest wrote/updated current truth incorrectly | **Forward revision / contraction** via TMS+AGM; cascade re-validates dependents | Yes — minimal-change, no orphans |
| S3 | **Consolidation / optimizer pass** | A warm-loop pass changed *what is true* (drift, confabulation) | Discard the pass's branch **and** trace its provenance edges to recompute affected projections | Yes, if pass ran on a branch |
| S4 | **Projection / index / embedding** | A rebuild produced a bad index | **Recompute from the ledger** (drop-and-rebuild) | Yes — caches are derived |
| S5 | **Code / binary / schema** | A deployment or migration | Conventional revert — **owned by the §32 runbook**; this doc only governs its *memory-state* implications (S2–S4) | Depends — see §4 |

> **Boundary note for S5.** Reverting the *binary* is a runbook action. The part this lane owns is the question the runbook can't answer: *did that binary or migration mutate the ledger, beliefs, or projections in a way that the code revert leaves stranded?* If yes, the real rollback is S2–S4, performed forward, not a code revert.

---

## 2. Decision criteria — when to roll back

Roll back on **soundness and integrity** signals, not on cosmetics. The triggers below are Mnemosyne-specific; the *thresholds* for them are defined in the validation lane (§23.4/§33), not here.

### 2.1 Roll back **immediately** (correctness, not quality)

These are correctness bugs by the blueprint's own framing (§3: "a consolidation pass that changes what is true is a correctness bug, not a quality trade-off"):

- **Soundness violation.** A pass or update changed *what is true* — observable drift, confabulation, or a justified belief whose justifications don't support it.
- **Integrity / tamper-evidence failure.** A content-address / Merkle mismatch, or a poisoning alarm (MINJA-style suite or anomaly detector) fires. Treat as a security incident as well as a rollback.
- **Protected-case regression.** Any regression on a protected case in the regression suite. By gate rule this should have blocked promotion; if it reached active, roll back the candidate now.
- **Safety-rail breach.** A change touched (or effectively bypassed) the reward / verifier / safety surface that is supposed to be outside the editable surface.

### 2.2 Roll back **after confirmation** (monitored regressions)

Post-promote monitoring (§33) is the trigger source; confirm the signal is real (not run-to-run noise) before acting:

- **Proxy-vs-true divergence tripwire** fires — the promoted policy's proxy reward is decoupling from true outcomes (reward-hacking signature).
- **Diversity / divergence collapse** — early model-collapse signature (tails thinning). Roll back the offending policy *and* freeze further auto-promotion until investigated.
- **Calibration regression** — ECE rises above target or abstention collapses into overconfidence after a change.
- **Contradiction backlog grows monotonically** — the belief core is manufacturing inconsistency faster than it resolves (distinct from healthy contested-belief surfacing — see §5).
- **Mutation-rate rail breach** — change volume exceeded the bounded mutation-rate guard.

### 2.3 **Do not** roll back — roll *forward* or hold

- A **contested belief surfacing as multi-hypothesis**, or **calibrated abstention**, is the system working as designed — not a regression (see anti-pattern A5).
- A bad **fact** is corrected by **forward supersession/revision** (S2), not by reverting the belief store to an earlier state.
- A **noise-level** metric wobble inside run-to-run variance is not a trigger; the gate already accounts for noise margin.

**Default disposition by surface:** S1 learned changes → *discard the branch and re-propose* (cheap; do not hot-patch a regressing policy in place). S2 beliefs → *forward revision*. S3 passes → *discard + recompute*. S4 projections → *rebuild*. S5 code → *runbook revert + check S2–S4*.

---

## 3. Safe rollback patterns

### P1 — Learned changes: discard the branch, don't edit `main`
A promoted candidate lived on a versioned branch and merged into `main` only after the gate. To reverse it, **discard at branch granularity** so the reversal is transitive (I3) — every dependent projection the change touched is reverted together. Never hand-revert a subset on `main`; that reintroduces the v1 "ratchet"/partial-rollback corruption.

### P2 — Beliefs: roll back *forward* through the core
Reverse a wrong fact with a **revision or contraction** operator (TMS+AGM), not a delete. The core propagates the retraction along provenance edges (cascade invalidation), so dependents are re-derived and nothing is orphaned. The earlier (correct) belief and the wrong one both remain in the audit trail with their valid/transaction times.

### P3 — Consolidation passes: discard, then recompute along provenance
Because passes are incremental views over the evidence log + provenance graph (§21), undoing one means discarding its branch and recomputing **only along the affected provenance edges** — not a full reindex. The raw episodes it read are untouched (consolidation never deletes raw evidence — §31).

### P4 — Projections: rebuild from the ledger
A bad index/embedding is dropped and recomputed from the immutable ledger. **Verify the ledger + recompute path is intact _before_ dropping** the projection (this check is the line between P4 and anti-pattern A1).

### P5 — On the way back, re-enter shadow-first
A previously rolled-back policy returns through **shadow mode → canary → active**, never straight to active. The rollback itself is a logged outcome; feed it back as evidence so the gate doesn't re-propose the same losing candidate (A7).

### P6 — Record the rollback as evidence
Every rollback writes its trigger, the offending candidate/pass id, and the observed outcome into the trajectory/audit log. Rollback/promote counts are a monitored signal (§33); the record is what makes the loop self-correcting instead of oscillating.

---

## 4. Schema & migration rollback (boundary with §32)

The **mechanical** revert of a schema or binary is the runbook's job. This lane governs only the memory-state consequences:

- **Additive / projection-only migrations** are safe to revert by P4 (rebuild) — projections are derived.
- **Migrations that touch the ledger or belief store** are *not* freely reversible by a code/schema revert. If the migration rewrote evidence or beliefs, the safe path is forward (P2/P3), and a naïve schema down-migration that drops those rows is destructive (A1).
- **Before** authorizing a schema rollback, confirm with the §33 path that the ledger is complete and projections can be rebuilt from it. If that can't be confirmed, **hold** — a stuck-but-intact ledger beats a clean-looking but truncated one.

> Everything about *how* to execute the migration up/down, ordering, and locking lives in §32. Do not restate it here.

---

## 5. Anti-patterns

Each is grounded in a Mnemosyne failure mode, not generic SRE advice.

- **A1 — Destructive restore of the evidence ledger.** Restoring memory from a snapshot that truncates the append-only log, or hard-deleting episodes to "undo." This wipes provenance, breaks tamper-evidence, and severs the only thing every projection can be rebuilt from. The ledger is rolled back *to*, never *back*.

- **A2 — Deleting a bad fact instead of superseding it.** Hard-deleting an incorrect belief bypasses TMS+AGM, orphans its justifications, and leaves dependents dangling — the exact silent corruption the belief core exists to prevent. Use P2.

- **A3 — Partial / manual rollback that breaks transitivity.** Hand-reverting some projections but not their dependents produces a half-rolled-back state that looks consistent and isn't. Roll back at **branch granularity** and let content-addressing make it transitive.

- **A4 — Editing `main` in place to "back out" a learned change.** If a regressing policy is on `main`, the fix is to discard its branch — not to patch `main`. Patching defeats the entire gated-promotion design and means `main` is accumulating ungated edits.

- **A5 — Treating contradiction or abstention as an incident.** Multi-hypothesis contested beliefs and calibrated "I don't know" are the system being *sound*. Rolling back the belief core because it "won't just answer" re-enables overconfident corruption. Tune calibration through the gate; don't roll back honesty.

- **A6 — Rolling back the safety rails / verifier to pass a gate.** The reward, verifier, and safety surfaces are deliberately outside the editable surface. Reverting them to unblock a promotion is reward-hacking-by-operator and removes the check that catches reward hacking.

- **A7 — Auto-rollback loops with no diversity/divergence guard.** An automated promote→regress→rollback→re-promote cycle that optimizes a proxy can hill-climb into collapse. A spike in rollback count is a **stop-and-investigate** signal, not a retry trigger; the rolled-back outcome must be fed back so the candidate isn't re-proposed.

- **A8 — Re-promoting a rolled-back change straight to active.** Skipping shadow mode on re-entry reintroduces the same regression with no observation window. Always shadow → canary → active (P5).

- **A9 — Rolling back without recording why.** Discarding a branch and moving on loses the outcome that justified it. That outcome is evidence; unrecorded, the loop re-learns the same mistake.

- **A10 — "Rolling back" projections without verifying the recompute path.** Dropping an index/embedding before confirming the ledger + recompute is intact turns a reversible cache-rebuild (P4) into data loss. Verify first.

---

## 6. Quick reference

```
Decide rollback?
 ├─ Soundness / integrity / protected-case / safety-rail broken ........ roll back NOW (§2.1)
 ├─ Proxy-vs-true / diversity / calibration / contradiction-backlog .... confirm, then roll back (§2.2)
 ├─ Contested belief or abstention surfacing ........................... NOT a rollback (§2.3)
 └─ Noise-level wobble ................................................. hold

Then, by surface:
 S1 learned change ...... discard the branch, re-propose (P1)        ── never edit main (A4)
 S2 belief / fact ....... forward revision/contraction (P2)          ── never delete (A2)
 S3 consolidation pass .. discard + recompute on provenance (P3)
 S4 projection / index .. rebuild from ledger (P4)                   ── verify recompute first (A10)
 S5 code / schema ....... §32 runbook revert + check S2–S4 (§4)      ── never truncate the ledger (A1)

Always: shadow-first on re-entry (P5) · record the rollback as evidence (P6)
Never:  roll back the verifier/safety rails to pass a gate (A6) · auto-loop without guards (A7)
```

---

## 7. Boundaries restated (so this lane stays scoped)

- **Deployment runbook (§32)** owns *how to execute* a deploy/redeploy/migration/restart. This lane owns *whether to revert and how to keep memory state sound while reverting*.
- **Validation / promotion-gate checklist (§23.4, §33)** owns the *pass/fail criteria and thresholds*. This lane *references those as triggers* (§2) and does not restate them.
- **This lane** owns: rollback decision criteria, the per-surface safe patterns, and the anti-patterns. New mechanical steps or new gate criteria discovered while using this doc belong in §32 or §33 respectively — link to them; don't copy them here.
