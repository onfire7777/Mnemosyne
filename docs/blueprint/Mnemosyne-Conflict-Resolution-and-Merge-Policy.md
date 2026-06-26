# Mnemosyne — Conflict Resolution & Merge Policy

**Status:** draft (lane deliverable)
**Date:** 2026-06-23
**Aligns with:** `Mnemosyne-v2-Build-Blueprint.md` (§5, §6, §8.3, §10, §11, §17, §19, §20, §21, §24; innovations I2, I3, I5, I8, I11) and `Mnemosyne-Rollback-Guidance.md`.
**Scope of authority:** This document specifies *how conflicting memory updates are detected and merged into current truth* — both single-store assertion conflicts (the §6.3 / §21 belief-reviser path) and git-like branch merges (I3) — using **one precedence engine**. It defines **detection**, **precedence**, **tie-breakers**, **versioning expectations**, and the **branch-merge procedure**.

> **It deliberately does not redefine** key schemas (§19), retrieval (§7, §22), the memory lifecycle (decay/forgetting/RTBF, §10), or privacy/erasure mechanics (§10.5, §17.3, §11.4). Those fields and rules are **read-only inputs and hand-off boundaries** here. Where this policy needs one, it cites the owning section and treats its output as authoritative.

---

## 1. Position in the architecture

The blueprint already supplies the *machinery* of conflict handling but leaves the *decision contract* implicit and scattered. This policy makes that contract explicit and total.

| Existing machinery | Where | What this policy adds |
|---|---|---|
| Write-decision operators `ADD/UPDATE/SUPERSEDE/NOOP/RETRACT/QUARANTINE` | §6.3, Appendix B.2 | The deterministic rule that **selects** the operator |
| Belief-reviser pass (TMS + AGM) | §21, I2 | The explicit **epistemic-entrenchment order** AGM requires |
| Contradiction flag + "retain both" | §10.3 | The **detection predicate** and the **hand-off** to lifecycle |
| Branch / commit / merge (Merkle DAG) | I3, §17.7 | The concrete **N-way merge precedence** ("belief core resolves via AGM") |
| Bitemporal facts + why-provenance | I5, §19 | The **resolution record** appended to provenance |
| Calibrated confidence + multi-hypothesis | I8 | The `CONTEST` outcome and where confidence sits in the order |
| Trust tiers + capabilities | §11, I11, §20 | Trust tier as the **primary** entrenchment axis |

**One source of truth.** The evidence ledger (Store 2, append-only) never has conflicts; conflict resolution operates **only on the rebuildable projections** (Stores 3–7). Resolution is therefore always **recomputable from evidence** and never mutates the ledger (§17.7).

---

## 2. Definitions

- **Item.** A projection record in a conflict-bearing store, carrying the common meta-envelope (§19): `id, cid, tenant_id, user_id, memory_type, branch, source_evidence_ids[], justification_id, trust_tier, confidence, fidelity, valid_from, valid_to, txn_time (created), expired_at`. All fields below are **read** from the envelope; none are redefined.
- **Trust tier.** Integer `0…5` (§20): `0` = direct user / human assertion, `1` = first-party agent action/tool result, `2` = corroborated derivation, `3` = single-source derivation, `4` = third-party import, `5` = untrusted-external. **Lower = more entrenched.** ("Human always wins" = tier-0 outranks all machine inferences — §6.3, §17.7.)
- **Corroboration count.** `|distinct independent source_evidence_ids|` supporting the item's current justification (I5 how-provenance).
- **Active item.** `valid_to IS NULL AND expired_at IS NULL AND erased = false` on the branch under consideration.
- **Conflict.** Two active items that the **conflict predicate** (§3) declares mutually incompatible.

---

## 3. Conflict detection (the predicate)

Detection is **per-store** and **deterministic** — a pure boolean over recorded fields, no model judgement at decision time (an LLM may *propose* candidates upstream in §21, but the predicate that *fires* resolution is rule-based and replayable).

Two active items `A`, `B` (same `tenant_id`, same `branch`) **conflict** iff they match the store's identity key **and** their values are incompatible **and** their valid-time intervals overlap:

| Store | Identity key (must match) | Incompatible when | Overlap test |
|---|---|---|---|
| 3 — Semantic assertions | `(subject, predicate)` | `object` differs **and** predicate is single-valued (cardinality-1, e.g. `employer`, `manager`) | `[valid_from,valid_to)` intervals intersect |
| 4 — Entity graph edges | `(src, predicate, dst-class)` for cardinality-1 predicates | distinct `dst` for a 1:1 edge | edge valid-time intervals intersect (→ **edge-invalidation**, §5.4/§6.4, not delete) |
| 6 — Preferences | `(category, scope)` | different `value`/`override` | both currently in-scope |
| 5 — Procedures | `signature` | different `body`/`params` for same signature | both `active` |
| 7 — Lessons | `failure_signature` | contradictory `lesson_type`/remediation | both `active` |

**Cardinality matters.** Multi-valued predicates (e.g. `speaks_language`, `tagged_with`) **never conflict** — both values coexist; this is *expansion* (AGM), not *revision*. Only cardinality-constrained facts can conflict. Cardinality is a property of the predicate ontology (§5.4), not invented here.

**Entity identity is a precondition, not a conflict.** Duplicate-entity / alias resolution is the §6.4 Resolver pass and runs **before** this engine. A merge of two nodes found to be the same entity is *entity resolution*; reconciling their *contradictory edges afterward* is this engine's job.

---

## 4. The precedence ladder (epistemic entrenchment order)

When the predicate fires, the winner is chosen by a **strict lexicographic total order** over the two items. Compare axis 1; if tied, axis 2; and so on. The final axis guarantees a unique winner, so **every conflict is decidable**.

```
E0  ERASURE / LEGAL HOLD      (privacy lane, §10.5/§17.3) — short-circuit, see §7
E1  TRUST TIER                lower tier number wins            (primary; "human always wins")
E2  EXPLICIT > INFERRED       within same tier, a hard/explicit user item (§24)
                              outranks an inferred/latent one
E3  VALID-TIME RECENCY        later valid_from wins             (the SUPERSEDE signal, B.2)
E4  CALIBRATED CONFIDENCE     higher confidence wins            (I8)
E5  CORROBORATION COUNT       more independent sources wins     (I5)
E6  TRANSACTION-TIME RECENCY  later txn_time (known-to-system) wins
E7  DETERMINISTIC TIE-BREAK   lexicographically smallest cid (content hash) wins
```

**Why this order (and not recency-first).** "Human always wins" is a structural invariant of the system (§6.3, §17.7, §24), so **trust must dominate recency**: a fresh tier-5 scrape cannot silently overwrite a tier-0 human fact. Recency is decisive **only within a trust tier** — which is exactly the §6.3 / B.2 behaviour (SUPERSEDE keys on `valid_time` among like-trust facts). Confidence (E4) sits **below** recency, not above it, because a stale-but-confident belief should still yield to a newer same-trust observation; confidence only separates items that are otherwise indistinguishable in authority and time. E7 (content hash) makes the order **total**, which is what gives determinism and merge-commutativity (§6, §8).

**Cross-tier conflicts do not auto-overwrite — they `CONTEST`.** When the *lower-entrenched* item is newer (the classic "stale human fact vs. fresh external correction"), the engine does **not** let trust silently bury a possibly-true update. The higher-trust item **remains active** (E1 wins), and the lower-trust newer item is stored as a **competing hypothesis** (`CONTEST`, I8 multi-hypothesis) with a contradiction flag handed to lifecycle/consolidation for re-examination or user confirmation (§5, §9.A). This is how "trust wins" and "contradictions are never silently dropped" (§10.3) coexist.

**Tier-0 fast path.** A direct user correction (tier 0) is applied **immediately** as an active supersession in the same turn (§20 step 7) — it wins E1 outright and skips the gated warm loop. Only *derived/inferred* items take the candidate → promotion-gate path (§8.3).

---

## 5. Resolution operators (precedence outcome → action)

The ladder's outcome maps to exactly one operator. Operators are the **existing** §6.3 / B.2 set; this policy only fixes *when each fires*.

| Outcome | Operator | Effect |
|---|---|---|
| Incoming wins, same identity, newer valid-time | **SUPERSEDE** | Close loser's interval (`valid_to`, `expired_at` set); insert winner; link `superseded_by` |
| Incoming wins, value refinement (not a time change) | **UPDATE** | New version of the record; link prior version |
| Incoming loses to an active item | **NOOP** | Drop incoming as redundant/inferior; record why |
| Incoming conflicts with **higher-trust** active item, and is newer/plausible | **CONTEST** | Keep both as multi-hypothesis (I8); raise `contradictions` flag (→ lifecycle) |
| Incoming is low-trust / unresolved / taint-flagged | **QUARANTINE** | Store `status=quarantined`; no influence on context until cleared (§11) |
| Explicit user retraction / git deletion | **RETRACT** | Append tier-0 retraction event; cascade-invalidate dependents (TMS, I2) |
| No active conflict | **ADD** | Insert (expansion); `candidate` if derived (gate §8.3) |

Edges (Store 4) use **edge-invalidation** for SUPERSEDE/RETRACT (§5.4/§6.4) — never row deletion.

**Cascade.** Because beliefs carry justifications (I2/TMS), SUPERSEDE/RETRACT of a premise triggers **cascade invalidation** of dependents, and the affected projections are recomputed incrementally (I6). Cascade is mechanism, owned by the belief core; this policy only specifies that the *triggering decision* is the ladder's.

---

## 6. Branch merge policy (I3)

Branch merge is **N-way conflict resolution using the same ladder** — no second rule set. Merging branch `S` (source) into `T` (target):

1. **Merge base.** Compute the common ancestor commit `B` in the Merkle DAG (lowest common ancestor). Merge is **three-way** per item: `(B, T, S)`.
2. **Per-item classification** by stable identity key (§3):
   - **Unchanged on one side** → take the changed side. (Fast-forward of that item.)
   - **Changed on both sides to the same value** → no conflict; take it.
   - **Changed on both sides to incompatible values** → **run the §4 ladder** between `T`'s and `S`'s heads for that item. The ladder picks the winner; the loser is recorded as `superseded_by` (or `CONTEST` if it would cross-tier-bury per §4).
   - **Deleted on one side, modified on the other** → a tier-0 RETRACT (human deletion) wins by E1; otherwise modification wins and the delete is recorded as a competing hypothesis for re-examination.
3. **Merge commit.** The result is a **new commit with two parents** (`T`, `S`); each resolved item's provenance gains a **resolution record** (§8) naming the deciding axis. Nothing is mutated in place; the pre-merge heads remain reachable.
4. **Reversibility.** Rollback of a merge = **discard the merge commit / branch** (transitive by construction, I3; see `Mnemosyne-Rollback-Guidance.md`). No partial-rollback "ratchet" is possible.
5. **Determinism & commutativity.** Because the ladder is a **total order independent of side labels** (it reads only envelope fields, never "ours/theirs"), `merge(T,S)` and `merge(S,T)` produce the **same resolved values** (the merge-commit parent order may differ, but truth content is identical). Re-running a merge over the same `(B,T,S)` is idempotent.

**Canary / speculative branches.** Cold-loop policy candidates run on canary branches and merge back only through the **promotion gate** (§8.3); a derived item that fails the regression suite is never merged into the trunk. Merge does not bypass gating.

---

## 7. Privacy & lifecycle short-circuits (consumed, not defined here)

These take precedence over the ladder and are **owned by other lanes**. This engine reads their flags and must never override them.

- **E0 — Erasure (privacy lane, §10.5 / §17.3 / §11.4).** An item with `erased = true` (crypto-shredded) is **removed from candidacy entirely** — it can neither win nor lose a conflict, and it is not a valid merge participant. If erasure of a source invalidates a projection, recompute-or-drop is the §17.2 replay mechanism's job, not this engine's.
- **E0 — Legal hold.** An item under legal hold **may not be superseded, retracted, or merged away**; a conflicting incoming item is forced to `CONTEST` (both retained) until the hold clears. This engine surfaces the conflict; it does not lift holds.
- **Decay/salience (§10.1) never resolves a conflict.** A low-salience but still-`active` item participates in the ladder at full standing. Salience gates *pruning*, which is lifecycle's decision, applied **after** and **independently of** truth resolution. An item that lost a conflict (superseded) is the only thing this engine "removes," and only by closing its validity interval — the record persists for as-of-time queries (I5).

---

## 8. Versioning & audit expectations

Every resolution is **append-only and self-documenting**, so the system can answer "why is X current truth, and what did it displace?" (I5).

**Versioning invariants.**
1. **No in-place value mutation.** Losing/superseded items are closed (`valid_to`, `expired_at`), never edited or deleted (erasure excepted, §7). Winners are new rows.
2. **Linkage.** A superseding item records `superseded_by`/prior-version pointers and inherits/extends the `justification_id` chain.
3. **Bitemporal closure.** SUPERSEDE sets the loser's `valid_to` to the winner's `valid_from` and stamps `expired_at = txn_time` of the decision (I5, four timestamps per §19).
4. **Gate stamp for derived items.** Any superseding *derived* item (procedure/lesson/learned policy, and any fact promoted from inference) carries `validated_by = <regression-run id>` per §8.3; facts are validated by **external corroboration**, not self-verification.

**The resolution record (new auditable artifact).** Each fired resolution appends one record to the loser's and winner's provenance:

```
resolution {
  decision_id,                 # stable id
  branch, tenant_id,
  winner_cid, loser_cid,
  operator,                    # SUPERSEDE | UPDATE | NOOP | CONTEST | QUARANTINE | RETRACT | ADD
  deciding_axis,               # E1..E7 — the FIRST axis that separated them
  axis_values: { trust_tier, explicit, valid_from, confidence, corroboration, txn_time, cid },
  contest: bool,               # true when cross-tier-bury was avoided (§4)
  validated_by,                # regression-run id if derived; null for tier-0 fast path
  txn_time
}
```

`deciding_axis` makes audits trivial and makes determinism **checkable**: a replay that produces a different `deciding_axis` for the same inputs is a regression. `CONTEST` outcomes additionally appear in the §10.3 `contradictions` queue.

---

## 9. Boundaries with the lifecycle and privacy lanes (explicit hand-offs)

This policy **decides truth**; it does not **manage the lifetime** of memory or **enforce privacy**. The seams:

**A. Lifecycle lane (§10, §21) — owns everything *after* a flag.**
- *This lane emits:* the winner/loser + operator + resolution record, and—on cross-tier or held conflicts—a `CONTEST` with a `contradictions` flag.
- *Lifecycle owns:* the consolidation cadence that re-examines flagged contradictions (§21 belief-reviser pass), decay/salience scoring (§10.1), fidelity demotion and pruning (§10), summary regeneration, and embedding refresh. Lifecycle decides *when* a `CONTEST` is revisited and *whether* a superseded record is pruned to trace-tier (pointer kept).
- *Invariant at the seam:* lifecycle may **prune or decay** but may **never silently resolve** a `CONTEST` by deletion — resolution must re-run the §4 ladder (e.g., when new corroboration arrives) and emit a fresh resolution record.

**B. Privacy lane (§10.5, §17.3, §11.4) — owns erasure, PII, holds, access.**
- *Privacy sets:* `erased`, legal-hold, PII/sensitivity tags, access policy, taint labels (§11/I11).
- *This lane reads* those flags as the E0 short-circuit (§7) and as the QUARANTINE trigger for taint, and **never** clears, overrides, or works around them.
- *Invariant at the seam:* erasure is **not** supersession (§17.3). A conflict can be *avoided* by erasure (participant removed) but is never *resolved* by it; the difference is recorded (operator is absent, not `SUPERSEDE`).

**C. Schema, retrieval, gating (not redefined).** Envelope fields (§19) are read-only inputs. Retrieval ranking/activation (§7, §22) consumes current truth but is out of scope. The promotion gate and rollback (§8.3, Rollback-Guidance) are invoked, not re-specified.

---

## 10. Determinism & auditability guarantees (acceptance criteria)

1. **Totality.** The §4 ladder ends in a content-hash tie-break ⇒ every fired conflict has a unique winner; no "undecided" state except the intentional `CONTEST`/hold, which are explicit and flagged.
2. **Purity.** The decision is a pure function of recorded envelope fields (§2) — no wall-clock, no RNG, no model call at decision time. Same inputs ⇒ same outputs, on any node.
3. **Replay-stability.** Re-running consolidation/merge over the same evidence and branches reproduces identical current truth **and** identical `deciding_axis` values (checkable via resolution records).
4. **Merge-commutativity.** `merge(T,S)` and `merge(S,T)` agree on resolved truth (§6.5).
5. **Idempotency.** Re-applying a resolution or re-merging an already-merged pair is a NOOP.
6. **Auditability.** Every resolution emits a resolution record citing the deciding axis; `CONTEST`s are queryable; superseded history is preserved for as-of-time queries (I5).
7. **Safety preservation.** No resolution promotes a derived item past the regression gate (§8.3); no resolution overrides an E0 privacy short-circuit; tier-0 human items are never auto-superseded by lower trust.

---

## 11. Worked examples

1. **Same-tier update.** Tier-0 "manager = Bob" (valid 2025-01) vs tier-0 "manager = Alice" (valid 2026-06). E1 tie (both tier-0) → E2 tie → **E3 recency**: Alice wins. Operator **SUPERSEDE**; Bob's interval closed at 2026-06; `deciding_axis = E3`.
2. **Cross-tier, newer-but-untrusted.** Tier-0 "employer = Acme" (valid 2025) vs tier-5 scrape "employer = Globex" (valid 2026). **E1**: tier-0 wins and stays active; Globex stored as **CONTEST** hypothesis + `contradictions` flag → lifecycle/user confirmation. Nothing silently overwritten.
3. **Branch merge, both edited.** Trunk sets preference `theme=dark` (tier-0, 2026-05); feature branch sets `theme=light` (tier-2 inferred, 2026-06). Three-way: changed on both. Ladder **E1**: tier-0 trunk wins; branch value recorded `superseded_by`. Merge commit links both parents; resolution record `deciding_axis = E1`.
4. **Held conflict.** Asset under legal hold says `status=valid`; incoming tier-1 says `status=void`. **E0 hold** forces **CONTEST** (both retained); engine surfaces it; resolution deferred until privacy lifts the hold.
5. **Exact tie.** Two tier-2 derivations, identical valid_from, equal confidence and corroboration, same txn_time. **E7**: smaller `cid` wins — arbitrary but **stable and reproducible**, never a coin-flip.

---

## 12. Out of scope / open questions

- **Predicate cardinality catalogue.** The detection predicate (§3) depends on which predicates are cardinality-1; that ontology lives in §5.4 and should be enumerated there, not here.
- **Confidence calibration method.** E4 assumes calibrated confidences (I8); the calibration procedure is I8's, not this lane's.
- **`CONTEST` re-examination policy** (when/how often, auto-resolve thresholds) is the lifecycle lane's to set; this lane only guarantees a `CONTEST` is never resolved by silent deletion.
- **Multi-tenant / cross-user merges** are out of scope (per-tenant isolation, §11); this policy assumes a single `tenant_id` per conflict.
