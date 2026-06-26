# Partial Deployment — Validation Checklist (Outline)

> **Lane:** validation only. This document confirms that a *partial* deployment is
> ready and behaving, using evidence. It does **not** deploy, tune, remediate, or
> author procedure. It **references** the blueprint's definitions; it never restates
> or changes them.

---

## Scope & boundaries (read first)

**This lane owns:** evidence-based validation checks and their pass criteria.

**This lane does NOT redefine — it references the authoritative sources:**

| Concern | Authoritative source (do not redefine) | This lane only… |
|---|---|---|
| Key schemas — content-addressed ids, primary keys, columns | §29 Data model (DDL) + Appendix A | validates **conformance** to them |
| Config keys — tunables vs. immutable rails | §31 (`invariant_rails` + tunable set) | validates the **loaded values** match |
| Guardrails — rails, gate, security | §31, §23.5 (self-editable surface), §30.6 (promotion gate), §27 (security & governance) | validates they are **enforced** |
| Runbook / operations procedures | §32 Deployment & operations | validates the steps **were followed** + signals exist |

**"Partial" is a given, not a derivation.** The deployed-vs-held-back split is fixed
by §34 (phased roadmap) and §38 (maturity): the buildable phases ship; later
phases run shadow-first behind the rails. **Do not re-derive which phases are in
scope** — take the split as input and treat every held-back phase as remaining ops
work to confirm-inert, not to reclassify.

---

## Evidence rules (how a box gets checked)

1. Every item names an **evidence artifact** (command output, dashboard panel, log
   line, test report, migration record, config dump) and a **pass criterion** (the
   observable state/threshold).
2. A box is checked **only** when the artifact is attached/linked **and** the
   criterion is met **in the target environment** — not CI-only, not "should be fine."
3. Anything unmet is a **blocker**: record under *Outstanding* with an owner and a
   pointer to the owning section. Do not fix it here.
4. If validating a check would require changing a key, rail, or procedure — **stop**.
   That is out of lane; raise it against the owning section instead.

---

## 1. Deployment integrity — *what shipped is what was intended*

- [ ] **Released artifact matches intended commit.** Evidence: build manifest / git tag. Pass: hash matches the approved commit.
- [ ] **Schema conforms to §29 / Appendix A; migrations applied and recorded.** Evidence: migration ledger + schema diff vs. §29. Pass: zero drift, none half-applied.
- [ ] **Effective config matches expected tunables (§31).** Evidence: effective-config dump. Pass: every tunable within its §31-stated default/range.

## 2. Guardrail / invariant-rail enforcement — *verify, never set*

- [ ] **`invariant_rails` present and enforced (§31).** Evidence: config dump + a rejection probe. Pass: each rail observed binding (e.g., a pass exceeding `max_supersession_rate` is refused; delete without `min_corroboration_for_delete` is refused).
- [ ] **`reward_signal: external_only` holds (§23.5).** Evidence: capability/permission check on the optimizer. Pass: optimizer write to verifier/eval-suite is denied.
- [ ] **Untrusted-to-system-prompt forbidden / data-never-instruction (§27).** Evidence: MINJA/AgentPoison-style attack-suite result (§33). Pass: injection blocked.
- [ ] **Promotion gate + branch rollback wired (§30.6).** Evidence: candidate→promote→rollback counters + one rehearsed discard. Pass: rollback proven reversible (no supersession edge stranded).

## 3. Functional validation of the deployed slice — *evidence = §33 harness + §34 exits*

- [ ] **Each deployed phase meets its §34 Exit criteria.** Evidence: per-phase regression report. Pass: that phase's exit assertions are green.
- [ ] **Retrieval quality on the private suite (§33).** Evidence: recall@k / nDCG report with confidence intervals. Pass: beats the stated baseline at the token budget, delta outside noise.
- [ ] **Confidence / abstention calibrated (§26, §33).** Evidence: ECE + abstention-precision report. Pass: ECE under the §31 target coverage.
- [ ] **Protected + security test tiers green (§33).** Evidence: tiered suite run (smoke/core/protected + attack tier). Pass: all green; the "test classes that must exist" are present.

## 4. Boundary of the partial deployment — *held-back work is correctly inert*

- [ ] **Shadow / disabled phases are not live.** Evidence: shadow-mode logs + flag state. Pass: predictions logged vs. outcomes, never promoted; no user-facing effect.
- [ ] **Held-back items are tracked as remaining ops work.** Evidence: tracking list. Pass: each shadow phase has an owner and an explicit switch-on condition (e.g., "active at suite size N", "Phase 4 gate").
- [ ] **No deployed path depends on a held-back phase to function or fail safe.** Evidence: dependency check. Pass: none found (any dependency is a blocker).

## 5. Observability evidence — *confirm signals exist, do not author dashboards*

- [ ] **§32 dashboards show real post-deploy data.** Evidence: live panels/queries for retrieval hit-rate + P95, consolidation throughput + prune/demotion, contested backlog, calibration error + abstention, candidate→promote→rollback counts, the model-collapse and reward-hacking tripwires, the long-horizon no-degradation metric, and the security audit log. Pass: each emitting against a baseline.
- [ ] **Tripwire alerts route to a real owner.** Evidence: alert config + one test fire. Pass: alert reaches a live channel/on-call.

---

## Output / sign-off

```
Partial Deployment Validation: READY | NOT READY (N blockers)

1 Deployment integrity:   [pass | M unmet]
2 Guardrail enforcement:  [pass | M unmet]
3 Functional (deployed):  [pass | M unmet]
4 Partial boundary:       [pass | M unmet]
5 Observability:          [pass | M unmet]

Outstanding (route to owning section, do not fix here):
- [item] unmet criterion → owner → owning § (e.g., §32 ops, §31 rails)

Sign-off: <name> @ <env> @ <timestamp>
```

If every box is checked: `Partial Deployment Validation: READY.`

---

## Guardrail — what this checklist must NOT do

- **No redefinition.** Do not restate, alter, or "clarify" key schemas (§29 / App. A),
  config keys or `invariant_rails` (§31), guardrails (§23.5, §27, §30.6), or runbook
  procedures (§32). Reference by section; validate against them.
- **No re-derivation of the split.** The deployed-vs-shadow scope (§34, §38) is an
  input. Held-back phases are remaining ops work to confirm-inert — not items to
  reclassify, promote, or recompute here.
- **No remediation.** Validation only. Failures become *Outstanding* entries routed to
  the owning lane; this document does not fix, tune, or deploy.
