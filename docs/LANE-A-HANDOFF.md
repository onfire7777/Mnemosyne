# Lane-A Reconciliation — Landed + Residual Handoff

**Branch:** `reconcile/lane-a-cold` (isolated clone off committed Codex `main` @ `97a5c6b`).
**Discipline:** additive / default-off / byte-identical when inactive; never touches Codex's live
working tree; merges with minimal delta. Each completion forcing-function flips `xfail→xpass` as its
paired src wiring lands.

---

## ✅ LANDED on this branch (verified: ruff clean, full main suite 0 failures)

| Item | File(s) | Forcing function / proof |
|---|---|---|
| RegressionCase `origin`+`mode` (OQ5, synthetic excluded) | gate.py | capability harness |
| PromotionGate `ignition_status()` + `IgnitionStatus` + `require_ignition` shadow-no-merge | gate.py | mirrors completion `ignition_status` oracle |
| cf-term `replay_predicted_lift` surfaced in `evaluate` | gate.py | replay-fidelity source probe |
| ACT-R power-law decay (`decayed_salience`/`demotion_decision`) + retrieval base_level | policy/lifecycle/retrieval | capability harness; default `actr_decay=0.0` = off |
| ACT-R forgetter wire (`_run_forgetter` forwards `policy.actr_decay`) | consolidation.py | byte-identical default |
| `cold_loop_counterfactual_trusted` rail (top-level bool; NOT in `immutable_rails` — preserves drift all-True/exact-set) | policy.py | drift suite stays green |
| **RAIL 1** `max_supersession_rate` live clamp (scale-gated window) | engine.upsert_assertion | `test_supersession_rate.py::...five_percent` → XPASS |
| **RAIL 3** `max_prune_fraction_per_pass` live clamp | consolidation._run_forgetter | `test_prune_fraction.py::...two_percent` → XPASS |
| **RAIL 6** `untrusted_to_system_prompt` serve-time sink guard (`assemble_system_prompt`) + punctuation-robust tokenizer | engine.py / text.py | `test_untrusted_to_system_prompt.py::...refused_at_runtime` → XPASS |
| **G8 embedding seam** — `LocalMemoryEngine(adapters=…)` + `_embed`; `cli.load_engine` threads adapters into local backend | engine.py / cli.py | seam routes through real adapter; default hashing byte-identical |

**Rail 2** (`min_corroboration_for_delete`) — already enforced by Codex (engine.forget); its forcing
function already XPASSes. No action.

**Drift gotcha (load-bearing):** `tests/test_config_drift.py` asserts `set(immutable_rails)==baseline`
(exact) AND `all(immutable_rails.values())` is True — so a default-OFF flag must be a top-level policy
field, never an `immutable_rails` entry. Applied to `cold_loop_counterfactual_trusted` and `actr_decay`.

---

## 🔧 RESIDUAL — needs Codex-coordination or real infra (NOT cleanly closable in isolation)

### R1 — RAIL 7 `consolidation_cadence_bounds [5_steps,24h]` (⚠️ contract conflict)
The per-tenant step governor already EXISTS (`consolidation.py:187`) but defaults OFF
(`consolidation_min_steps=0`). The forcing test uses the default ctor and expects back-to-back passes
refused → requires flipping the default to ≥5. **But the in-code note (`consolidation.py:154-156`)
warns the shared summary-rotation contract runs back-to-back passes and escalates default-on to the
Coordinator.** Flipping the default will break those green tests. Closing this cleanly requires
reconciling the summary-rotation contract (space its passes or opt out) — Codex's domain. Adding a
no-op policy constant does not flip the test, so it was intentionally not added.

### R2 — ECE calibration (the one failing §16 SLO: 0.279 vs ≤0.05)
Local `search` returns a constant `0.7` confidence (`engine.py` confidence default) and never abstains
on the local path, so ECE is degenerate. The mechanism fix (varied, calibrated confidence + working
abstention + conformal thresholds) is codeable, but: (a) it shifts the abstention threshold logic
across many existing tests (high regression surface), and (b) proving ECE ≤ 0.05 needs the completion
eval harness + a per-memory-type calibration set with **real embeddings** — not unit-verifiable.
Sequence after the embedding seam (now landed). Best done with the eval harness in the loop.

### R3 — `--object` argparse ambiguity (low value)
`propose`/`assert`/`correct --object` collides with the `--object-store*` globals under argparse
abbreviation. Fix: `allow_abbrev=False` on those subparsers (or rename globals). Needs reproduction to
confirm the exact inheritance path; deferred as cli ergonomics, low value, hot file.

### R4 — ACT-R exact-sum form
The landed retrieval base_level uses the Petrov closed-form approximation (recency+frequency from
stored `last_accessed`/`access_count`). The literal `ln(Σ_k age(access_k)^−d)` needs a stored
per-item access-timestamp list → `models.py` field + append-on-read in `engine.py`/`postgres_engine.py`
+ schema migration. Only pursue if a milestone demands exactness.

### R5 — Completion-branch marker removals
Rails 1/2/3/6 forcing functions now XPASS (strict) on this branch — their `xfail(strict)` markers
should be removed on `completion/blueprint-parity` so they become clean green guards. That is a
completion-branch edit (this src branch deliberately does not modify `tests/completion`).

---

## Merge / landing notes
- This branch merges conflict-free onto `97a5c6b` (verified: 0 Codex commits touched the cold files;
  hot-file changes are additive). Rebase onto Codex latest before merging.
- Recommended: hand this doc + branch to Codex (it owns engine/consolidation/cli), or PR the branch and
  let the residual (R1–R5) follow.
