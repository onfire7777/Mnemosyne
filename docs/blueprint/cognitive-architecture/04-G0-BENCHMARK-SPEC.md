# 04 · G0 — Benchmark Harness Specification (the blocking first deliverable)

**Status:** Implemented (eval/g0/) · **Gate:** G0 is *blocking* — per ADR‑001 (`03`), no feature in G1–G4 ships without an ablation win measured here. **Builds on (does not duplicate):** the workspace's evaluation lane — `../Mnemosyne-Evaluation-and-Test-Plan.md` and the `../eval/` spec suite — plus the repo‑root **eval harness** (`eval/g0/runner.py` · `eval/g0/gate.py` · `eval/g0/baselines/baseline-0.json` · `eval/g0/reports/report.json` · `eval/harness/` · `eval/calibration/` · `eval/run_eval.py`).

> Why this is first. Every claim in this program — "self‑improving," "better than the brain," "complete recall" — is a hypothesis until a number moves. G0 turns the goal into instrumentation. It is deliberately built **before** any new feature so that each later layer either earns its place or is cut, automatically and cheaply.

## 0. Relationship to the existing eval lane (reuse, don't reinvent)

This workspace already has a mature evaluation lane: `../Mnemosyne-Evaluation-and-Test-Plan.md` (test taxonomy §2, **metric catalog §3**, golden scenarios §4, **datasets §5**, acceptance criteria §6, tripwires §8) and the `../eval/` spec suite (`01-metrics-specification.md`, `02a/02b` catalogs, `03-dataset-and-corpora-spec.md`, `04-adversarial-security-playbook.md`, `05-harness-architecture-and-ci-gating.md`, `06-release-gate-and-tripwire-runbooks.md`). **G0 does not replace any of it.** G0 = (a) **freeze a baseline** using that harness, and (b) **add only the few program‑specific metrics** the brain comparison introduces — *confabulation/faithfulness rate*, *continual‑learning interference*, paid-provider cost, and *controller watts/\$* (for the G4 always‑on loop, measured only when explicit controller power/cost telemetry is supplied) — registering them in the existing metric catalog and wiring them into the existing CI gating (`eval/05`) and release‑gate runbooks (`eval/06`). Read everything below as **deltas** on that lane, not a parallel one.

---

## 1. Objective

Produce (a) a **frozen baseline** snapshot of the current system and (b) a **reproducible harness** that scores any build on the metric set below, plus (c) a **gate** (script/CI check) that blocks a change unless it improves a target metric without regressing any guardrail metric.

## 2. Metric set

Each metric: definition · how measured · classification (**target** = a metric a gate may aim to improve; **guardrail** = a metric that must never regress).

| Metric | Definition | Measurement | Class |
|---|---|---|---|
| **recall@k** | fraction of relevant items retrieved in top‑k | held‑out query→relevant‑CID set; k ∈ {1,5,10,20} | Target |
| **nDCG@k** | rank‑weighted retrieval quality | same set with graded relevance | Target |
| **multi‑hop recall/nDCG** | retrieval on questions needing ≥2 linked facts | a dedicated multi‑hop subset (the wiki flags this as the current weak spot) | Target |
| **ECE** | expected calibration error of confidence | binned calibration over a labelled QA set | Guardrail (≤ baseline) |
| **abstention precision / recall** | of abstentions, how many *should* have abstained, and coverage | label each query "answerable / not" vs engine's abstain decision; report risk–coverage curve | Guardrail |
| **continual‑learning interference** | accuracy drop on earlier tasks after learning later ones (backward transfer) | sequential ingest of task blocks; re‑test earlier blocks | Target (drive →0) |
| **confabulation rate** | fraction of answer claims **not** supported by cited provenance | automated provenance‑entailment check + sampled human/LLM audit | Guardrail (→0; never regress) |
| **poison‑block rate** | fraction of injected malicious/poison inputs that fail to corrupt belief or inject instructions | a poisoning test set (untrusted, imperative, contradictory) | Guardrail (stay 1.0) |
| **fast‑path P95 latency** | 95th‑pct read latency, warm | timed query suite | Guardrail (≤ budget) |
| **deep‑path P95 latency** | 95th‑pct multi‑hop latency | timed deep‑search suite | Reported |
| **cost** | tokens/query and \$/1k queries; for G4, controller **watts/\$** when always‑on | instrumented run | Reported (gated at G4) |

Notes: `confabulation rate`, `ECE`, `abstention`, `poison‑block`, and `fast‑path P95` are **guardrails** — the reliability invariant from the charter (`00` §3) expressed as numbers. A change that improves recall but raises confabulation or breaks a rail **does not ship**.

## 3. Datasets

Authoritative dataset/corpora spec: `../eval/03-dataset-and-corpora-spec.md`; the adversarial set is `../eval/04-adversarial-security-playbook.md`. G0 freezes versioned snapshots of three layers:

1. **Project‑native held‑out set (primary).** A representative sample of real Mnemosyne usage: evidence corpus + queries + ground‑truth relevant CIDs + "answerable/not" labels + a multi‑hop subset. This is the authoritative set because it matches deployment distribution.
2. **External public benchmarks (secondary, for comparability).** Candidates to adopt where licensing/format fit: a **long‑term conversational‑memory** benchmark (e.g. LoCoMo‑style), a **multi‑hop QA** set (e.g. HotpotQA‑style) for the multi‑hop axis, and a **continual‑learning** task sequence. Use these to sanity‑check that gains are not overfit to our own set. *(Confirm exact datasets/licenses at build time; do not hard‑commit here.)*
3. **Adversarial/poison set.** Curated untrusted, imperative, and mutually‑contradictory inputs to exercise trust tiers, R6 (data‑not‑instructions), and the contradiction path.

## 4. Baseline procedure (freeze)

1. Pin a commit, dataset versions, model/provider versions, and RNG seeds.
2. Run the full metric set; write results to a versioned `report.json` (extend the existing `eval/calibration/report.json` schema).
3. Record environment (engine backend, embedding provider, hardware) so numbers are reproducible.
4. Tag this as **baseline‑0**. All later gates compare against the most recent *accepted* baseline.

## 5. Ablation protocol (how a gate is decided)

For each proposed change (a G1–G4 item):

1. Run the harness with the change **on** vs **off**, all else identical (same data, seeds, env).
2. **Ship iff:** at least one *target* metric improves by a pre‑registered margin **and** no *guardrail* regresses beyond noise.
3. Pre‑register the target metric and margin **before** running (avoids p‑hacking / motivated reading — see charter `00` §3).
4. On ship, the change's "on" run becomes the new accepted baseline.
5. Record every gate decision (pass/fail + numbers) in a running log, so the program is auditable end‑to‑end.

## 6. Gate‑specific acceptance criteria (the go/no‑go for each later stage)

- **G1 (reliability core):** ≥1 of {recall, nDCG, ECE, abstention} improves; confabulation and poison‑block do not regress.
- **G2 (structure + generalisation):** generalisation up (recall/nDCG on held‑out *novel* queries) **and** continual‑learning interference down.
- **G3 (generative replay):** net‑new *corroborated* beliefs appear **and** confabulation rate does not rise — the decisive test for "dreaming without hallucinating."
- **G4 (always‑on workspace):** self‑triggered background consolidation beats on‑demand consolidation on **quality‑per‑unit‑compute** (a retrieval/calibration gain per watt‑hour or per \$), with zero rail violations and a bounded, non‑increasing rumination metric (loop iterations that produce no novel, useful state).

### G1 gate evidence

- **Implemented slice:** schema-fast-path retrieval + reality-monitoring abstention + retrieval-strengthening lifecycle marks + multi-signal write priority + prediction-error-gated consolidation metadata + contested status for uncorroborated-but-congruent projections.
- **Preregistration:** `eval/g0/preregistrations/g1-reliability-core-schema-fast-path.json`.
- **Decision log:** `eval/g0/decision-log.jsonl`.
- **Target:** `multi_hop_ndcg_at_k`, direction `increase`, minimum delta `0.02`.
- **Result:** PASS against `eval/g0/baselines/baseline-0.json`; candidate `multi_hop_ndcg_at_k = 1.0` vs baseline `0.5935` (`+0.4065`). Guardrails unchanged: ECE `0.006271`, abstention precision/recall `1.0/1.0`, confabulation rate `0.0`, poison-block rate `1.0`, fast-path P95 `92.1 ms`.

## 7. Tooling & deliverables

- Extend the existing harness (spec: `../eval/05-harness-architecture-and-ci-gating.md`; code: the repo‑root `eval/` harness — `eval/g0/`, `eval/harness/`, `eval/run_eval.py`) to compute the added metrics and emit the extended `report.json` — reuse, don't fork.
- A one‑command run (`mneme eval g0` or a script) that reproduces a baseline.
- A CI/gate check that fails a build on guardrail regression and prints the ablation table.
- The versioned dataset manifests (§3) and the gate‑decision log (§5).

## 8. Definition of done for G0

- [x] Harness runs reproducibly and emits `report.json` with every §2 metric slot. The default local report marks `controller_watts_per_dollar` missing until an explicit telemetry artifact is supplied; `--controller-telemetry` produces a 14/14 measured report.
- [x] `baseline‑0` recorded with pinned commit/seeds/env.
- [x] Adversarial/poison set wired to the poison‑block + R6 checks.
- [x] Gate script enforces "target‑up, guardrail‑not‑down," with pre‑registration.
- [x] Independently reproduce the wiki's headline SLOs (recall, nDCG, ECE, poison‑block, P95) inside this harness before citing them anywhere.

Only when this is green does G1 begin.
