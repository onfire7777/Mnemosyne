# Deployment Observability — Verification Checklist

> **Lane:** observability signals & verification only. This document says **what to
> observe** after a Mnemosyne deploy and **how to confirm each signal is healthy**.
> It does **not** deploy, tune, remediate, or write incident response. It **references**
> the blueprint's definitions (§15, §22.5, §23.5, §25–§27, §31, §32, §33); it never
> restates or changes them.

---

## Scope & boundaries (read first)

**This lane owns:** the catalog of observable signals (metrics, logs, traces, alerts)
and the post-deploy verification that each is **emitting** and **within its expected
envelope** in the target environment.

**This lane is the substance behind the validation lane's one observability checkbox.**
The sibling `partial-deployment-validation-checklist.md` (§5) confirms, as a single
go/no-go row, that §32 signals *exist* and tripwires route to an owner. This document
enumerates those signals one by one and verifies each. **Cross-reference, don't
overlap:** the validation lane gates the release; this lane proves the telemetry.

**This lane does NOT redefine — it references the authoritative sources:**

| Concern | Authoritative source (do not redefine) | This lane only… |
|---|---|---|
| Which signals exist + dashboards | §15 (Observability NFR), §32 (Ops/observability) | verifies each is **emitting** post-deploy |
| SLO targets + latency budgets | §15 (Reliability, Latency), §22.5 (fast-path budget) | verifies signals report **within** them |
| Metric definitions (recall@k, ECE, abstention) | §16 (success metrics), §26, §33 | verifies the metric is **wired & populated** |
| Tripwire thresholds + auto-rollback | §23.5 (mutation rails + tripwire), §31 (`invariant_rails`) | verifies the alert **fires & routes** |
| Audit-log contents | §27 (every write: actor/source/tier/diff) | verifies the log **stream is live** |
| Deployment steps / runbook procedures | §32 Deployment & operations | **out of lane** — neither restated nor authored |
| Incident response / remediation | (owning ops lane) | **out of lane** — a firing alert is recorded, not handled here |

---

## Verification rules (how a box gets checked)

1. Every item names a **signal** (metric series, log stream, trace span, or alert rule)
   and an **expected behavior** — the post-deploy envelope, baseline, or non-empty
   condition that means "healthy."
2. A box is checked **only** when the signal is observed **live in the target
   environment** — emitting real post-deploy data, not CI fixtures, not "should be wired."
3. Verification confirms the signal is **present, populated, and within envelope**. It
   does **not** judge release-readiness (that is the validation lane) and does **not**
   act on an out-of-envelope reading (that is incident response, out of lane).
4. A missing, flat, or unparseable signal is an **observability gap**: record under
   *Outstanding* with an owner and a pointer to the owning section. Do not fix it here.

**When each signal first becomes meaningful** (verify at the right moment, not before):
hot-path metrics/traces at first live traffic; consolidation & write-path signals after
the first consolidation cycle (cadence per §31 `consolidation_cadence_bounds`); gate
counters after the first candidate; nightly/archive quality metrics and the long-horizon
no-degradation guard on their own cadence. A signal that is legitimately empty because
its cycle hasn't run is **pending**, not a gap — note the window.

---

## 1. SLO & latency envelopes — *verify signals report against the blueprint's targets*

- [ ] **Evidence-durability signal is live (highest SLO, §15 Reliability).** Signal: ledger append/integrity metric + any evidence-loss counter. Expected: durability metric reporting, loss counter at zero.
- [ ] **Derived-store availability is observed separately (§15).** Signal: per-store (pgvector / FTS / graph) up + rebuild-lag metrics. Expected: emitting; derived-store SLO tracked distinctly from (and lower than) evidence durability.
- [ ] **Fast-path P95 budget is measured (§15 Latency, §22.5).** Signal: fast-mode memory-overhead P95 before generation. Expected: series populated and reported against the ~300–400 ms budget.
- [ ] **Write-path cost/latency is measured (§16 leading).** Signal: write-path cost + latency per op. Expected: emitting against a baseline.

## 2. Metrics — *per-stage retrieval, write/consolidation, quality, loop counts (§15, §32)*

**Hot path / retrieval**
- [ ] **Per-channel retrieval hit-rate (§32).** Signal: hit-rate per channel (exact · BM25 · dense · graph · prefs · procedures · lessons). Expected: each channel reporting; none silently dark.
- [ ] **Activation-score distribution (§32).** Signal: activation-score histogram. Expected: populated, shape within the prior baseline (no collapse to a spike/flat).
- [ ] **Abstention rate (§26, §32).** Signal: fraction of turns abstaining. Expected: emitting; neither pinned at 0 nor runaway (cross-check §4 over-abstention alert).

**Write / consolidation path**
- [ ] **Consolidation throughput (§32).** Signal: items consolidated per cycle. Expected: non-zero after the first cycle within `consolidation_cadence_bounds` (§31).
- [ ] **Prune & fidelity-demotion rates (§25, §32).** Signal: prune fraction + demotion counts per pass. Expected: emitting and **below** the §31 rails (`max_prune_fraction_per_pass`) — verified as a *reported value*, not enforced here.
- [ ] **Contradiction / contested backlog (§15, §32).** Signal: open-contradiction queue depth. Expected: a live gauge with a trend (the backlog is also a tripwire input, §3).

**Quality / calibration** *(own cadence — §33 tiered suite; verify wired, value per cadence)*
- [ ] **Retrieval quality on the private suite (§16, §33).** Signal: recall@k / nDCG with confidence intervals. Expected: metric populated from the suite run; reported with CIs.
- [ ] **Calibration error (§26, §33).** Signal: ECE per memory-type. Expected: computed and reported against the §16/§31 target coverage.
- [ ] **Abstention precision (§16).** Signal: does "I don't know" correlate with truly-unanswerable. Expected: metric wired and populated.

**Self-improvement loop**
- [ ] **Candidate → promote → rollback counts (§15, §23.3, §32).** Signal: the three counters across the promotion gate. Expected: all three emitting; rollback path observable (not a dead series).

## 3. Logs — *audit, security, erasure, abstention, shadow (§27, §25, §33)*

- [ ] **Security audit stream is live (§27).** Signal: per-write log carrying **actor · source · trust-tier · diff**. Expected: stream flowing; sampled entry contains all four fields.
- [ ] **Capability-mediation / quarantine events log (§27).** Signal: taint-tracking + write-sink denials (untrusted data blocked from preference/policy/system-prompt sinks). Expected: denial events are logged when exercised (pairs with the §4 injection-block-rate signal).
- [ ] **Erasure / deletion-propagation log (§25, §27).** Signal: crypto-shred + transitive-invalidation records across derived projections. Expected: an erasure produces a traceable propagation log (verify the stream exists; do not run a destructive test here).
- [ ] **Abstention events carry their uncertainty note (§26).** Signal: abstention log with the reason (empty/too-large conformal set, low aggregate confidence, gist-only support). Expected: notes present, not bare counts.
- [ ] **Shadow-mode prediction-vs-outcome log (§33).** Signal: for not-yet-promoted phases, logged predictions vs. real outcomes. Expected: stream populated, no user-facing effect (boundary owned by the validation lane; here verify the *log* exists).

## 4. Traces — *attribute the hot path & confirm the decision-cycle invariant (§18, §22, §23, §30.6)*

- [ ] **Hot-path retrieval trace is decomposed per stage (§22, §22.5).** Signal: spans for plan → channels → trust/validity filter → RRF → activation → rerank → MMR → confidence → context-compile. Expected: full span tree present so the P95 budget can be attributed to a stage.
- [ ] **Decision-cycle invariant is observable (§18 CoALA).** Signal: trace tags marking *planning = read-only* vs. *execution = mutating*. Expected: no truth-mutation span inside planning; retrieval emits only append-only telemetry (access counts, recency), tagged as telemetry not truth-mutation.
- [ ] **Consolidation job trace (§21, §30.5).** Signal: span chain extract → resolve-entities → belief-revise → induce-skills → distill-lessons → summarize → decay. Expected: traceable, attributable to the write-authorized consolidator role.
- [ ] **Promotion-gate trace on the canary branch (§23.3, §30.6).** Signal: spans for regression suite → counterfactual replay → promote/rollback. Expected: a promote and a rollback are each traceable; rollback shows branch-discard (no stranded supersession edge).

## 5. Alerts & tripwire expectations — *verify wiring & routing, not response (§23.5, §31)*

> Verify each alert **exists, is bound to its signal, and routes to a live owner**; where
> the blueprint specifies **auto-rollback**, verify that linkage is configured. The
> *response procedure* to a firing alert is incident-runbook work — **out of lane**.

- [ ] **Mutation-rate tripwire (§23.5).** Alert on supersession-rate / prune-fraction spike beyond the §31 rails. Expected: bound to the metric, **auto-rollback** linkage present, routes to an owner.
- [ ] **Contradiction-backlog tripwire (§23.5).** Alert on backlog spike. Expected: bound to the §2 backlog gauge; routes to an owner.
- [ ] **Model-collapse tripwire (§32).** Alert on falling diversity/entropy of learned lessons. Expected: signal computed, threshold set, routes to an owner.
- [ ] **Reward-hacking tripwire (§32).** Alert on proxy-vs-true success divergence post-promote. Expected: divergence signal live, alert bound, routes to an owner.
- [ ] **Long-horizon no-degradation guard (§25, §32, §33).** Alert if consolidated memory drops below the no-memory baseline. Expected: the long-horizon metric is tracked and the breach alert is wired.
- [ ] **Fast-path latency-breach alert (§22.5).** Alert when P95 exceeds the budget. Expected: bound to the §1 P95 signal; routes to an owner.
- [ ] **Calibration-drift & over-abstention alerts (§26).** Alert on ECE above target / abstention-rate runaway. Expected: both bound to their §2 metrics and routed.
- [ ] **Security-signal alerts (§27, §33).** Alert on injection-block-rate drop or capability-denial anomaly. Expected: bound to the §3 audit/quarantine streams; routes to an owner.
- [ ] **Every wired alert test-fires to a real channel.** Signal: one synthetic fire per alert path. Expected: reaches a live channel / on-call (routing proven, not just configured).

---

## Output / sign-off

```
Deployment Observability Verification: HEALTHY | GAPS (N) | PENDING (M cycles not yet run)

1 SLO & latency envelopes:   [healthy | k gaps | pending]
2 Metrics:                   [healthy | k gaps | pending]
3 Logs:                      [healthy | k gaps]
4 Traces:                    [healthy | k gaps]
5 Alerts & tripwires:        [healthy | k gaps]

Outstanding gaps (route to owning section, do not fix here):
- [signal] not emitting / flat / unrouted → owner → owning § (e.g., §32 ops, §23.5 rails)

Pending (signal legitimately empty until its cycle runs):
- [signal] → becomes meaningful at <window> (e.g., first consolidation cycle, nightly suite)

Sign-off: <name> @ <env> @ <timestamp>
```

If every box is checked (or explicitly *pending* with a window): `Deployment Observability Verification: HEALTHY.`

---

## Guardrail — what this checklist must NOT do

- **No deployment steps.** Deployment & operations procedures are §32. Reference them;
  never restate or author them here.
- **No incident response / remediation.** A signal out of envelope or an alert firing is
  recorded as *Outstanding* and routed to the owning lane. This document does not
  diagnose, tune, roll back, or fix.
- **No redefinition.** Do not restate or alter signal/metric definitions (§15, §16, §26,
  §33), SLO/latency targets (§15, §22.5), tripwire thresholds or `invariant_rails` (§31,
  §23.5), or audit-log contents (§27). Verify against them by reference.
- **No overlap with the validation lane.** Release go/no-go and the deployed-vs-shadow
  boundary live in `partial-deployment-validation-checklist.md`. This lane only proves
  each signal is emitting and healthy.

---

## File placement (provisional — no target path established yet)

The canonical repo (`~/Projects/Mnemosyne`) has **no `docs/` or `ops/` directory** as of
this writing — only `README.md`, `REVIEW.md`, `sql/`, `src/`, `tests/`. This file is
therefore placed next to the blueprint and its sibling validation checklist on the
Desktop, matching the existing convention. **Suggested permanent home once an ops-docs
path exists:** `docs/ops/observability-verification-checklist.md` in the canonical repo,
beside the deployment runbook (§32) it references. Move freely; nothing here depends on
the location.
