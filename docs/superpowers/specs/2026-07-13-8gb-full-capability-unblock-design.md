# Mnemosyne — 8 GB Full-Capability Design and Progression Unblock Plan

**Date:** 2026-07-13
**Status:** Design for review (brainstorming output; operator-approved goal: full capability at 8 GB, no compromise)
**Scope:** Synthesis of the current progression problems, their resolutions, and the governing product principles. Extends — does not replace — `docs/research/Compact-Reader-Reranker-8GB-Design.md`, `.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md`, `.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md`, and the Phase 12 candidate protocol. No frozen protocol, threshold, or custody rule is changed by this document.

## 1. Governing principles

1. **Full capability at 8 GB.** Every product capability — deterministic retrieval, hop-0 planning, extractive QA, synthesis QA, consolidation, personalization, parametric adapters, and all security rails (crypto-shred semantics, audit hash chain, Ed25519 evidence signing, C2PA verification) — ships within a physical 8 GB machine's envelope (~5 GB usable; target footprint ~2.5 GB). The `qwen3:0.6b` synthesis rung (522 MB) lives inside the floor, not above it.
2. **Quality parity everywhere.** Larger hardware is never permitted to score higher. The quality-critical path uses the same models and deterministic components on every machine, verified by a cross-backend parity gate (CPU ONNX vs Metal/GPU execution providers must produce identical outputs). Hardware scales only latency, throughput, corpus size, and concurrency.
3. **The compact stack is the product path, not a variant.** The pinned `qwen3:8b` reader (5.2 GB) is development scaffolding and exits the endgame. The perf program (P0–P5) and native-acceleration kernels are the "full potential of better hardware" story: same outputs, faster.
4. **No custody compromise.** Preregistration, one-attempt-per-protected-split, once-ever held-out runs, TRAIN-only decontaminated corpora, digest pinning, and the hardware admission runbook all stand unchanged.

## 2. Problem register (as of 2026-07-13)

| # | Problem | Evidence | Severity |
|---|---|---|---|
| P1 | Host memory starvation (meta-blocker) | 55% admission floor vs samples 50/47/48 → 42 → 53 → 31 → 34%; gates protected attempts, full 155/218/41 verification, and model work; multi-day critical-path stall | Critical |
| P2 | Quality gap 0.083 → 0.85 | 5 protected attempts consumed (v3, v12 timeout-lost, v13 = 0.0, v17/v18 = 0.083); failure classes: hop-0 decomposition (22/24 zero-hop; addressed by v19's deterministic extractive planner, unmeasured), answer minimality (v10/v11), synthesis residual (unknown size) | Critical |
| P3 | One-shot evidence economics | v12 burned on a 120 s wrapper timeout; scale-preflight receipt now required (24/24, EM/F1 1.0, ledger-bound) but admission passing remains luck-based while P1 persists | High |
| P4 | Reader endgame contradicts 8 GB goal | `qwen3:8b` cannot ship on 8 GB; all larger/equal local generative substitutes closed by probes (14b RAM-infeasible even with Colima stopped; 9b/8b-family reproduce the bridge-selection defect) | High |
| P5 | Ops fragility on admission rails | Vault reseal incident (>1,300 restart retries), MCP client cert found expired by accident; 6-hour expiry floor is now an admission rail; rotation automation in progress, its full verification itself blocked by P1 | Medium |
| P6 | CI economics recurrence | Billing fixed 2026-07-12, but `macos-14` wheels job at 10× multiplier on every push (~25 pushes/day at peak) will re-exhaust included minutes | Medium |
| P7 | Process drag | PR #11 draft for days; dirty trees for many hours; two concurrent AI sessions on one starved machine; GOV-001 (longest lead) unstarted; Phases 13–16 fully serialized behind Phase 12 | Medium |

**System diagnosis:** P1 is upstream of everything. While it blocks the critical path, sessions produce lateral work; P2 — the only number that closes Phase 12 — has not moved since 2026-07-11.

## 3. Workstreams

### A — Immediate unblock (resolves P1, P3)

- **A1. Eval-window procedure (scripted):** stop the reclaim list (desktop AI apps, Discord, spare browsers, idle MCP servers, gbrain Postgres/Ollama brew services; pause the non-executing AI session), then run the runbook's exact 3-sample admission (15 s apart: memory ≥55%, load bounds, no resident model, mTLS cert validation, stack health) and refuse to proceed on any miss. Admission becomes deterministic instead of a gamble.
- **A2. Run the parked queue in order:** full 155/218/41 verification → 24/24 `qa_scale_dev_v1` receipt → candidate v19 protected attempt.
- **A3. Hygiene:** land in-flight slices promptly; take PR #11 out of draft; one canonical work stream per machine during eval windows.
- **Alternatives considered:** shrinking the VM below 6 CPU/12 GiB — rejected (runbook-pinned custody topology); scheduled overnight eval windows — adopt as a complement after A1 proves out.

### B — Close the quality gap with the compact stack (resolves P2, P4)

- **B1. Decision Point 1 = v19's protected result.** It measures the post-retrieval residual and therefore the reader's required contribution.
- **B2. Corpus materialization + hashing now** (training-order step 1; explicitly no model work; passes the lightweight ≥35% admission rule).
- **B3. Remote distillation** per the compact design doc: ~41M extractive reader + ~23M cross-encoder reranker, strongest custody-approved teacher, TRAIN-only decontaminated corpora (SQuAD v2 / HotpotQA distractor-train / conditional 2Wiki), 3 fixed seeds, ≤5 epochs, safetensors/ONNX only, ONNX FP32 → dynamic INT8, promotion gates. Training runs off-host and is untouched by P1.
- **B4. Candidate ladder:** v20 = extractive reader behind the unchanged `GroundedReader` interface. **Decision Point 2:** if synthesis-type questions hold below 0.85, v21 adds the `qwen3:0.6b` rung under a tight extractive contract — inside the 8 GB floor, preserving parity.
- **B5. Cross-backend parity gate:** new test class asserting identical outputs across ONNX execution providers (CPU vs Metal/GPU), modeled on the existing DSN-parity gate culture.
- **Rejected with reasons:** larger local generative readers (five probes, same defect, RAM-infeasible); hosted API readers (breaks quality parity and the self-hosted claim); from-scratch LLM training (cost, no advantage); learned ranking inside deterministic retrieval (standing project rule).

### C — The 8 GB full-capability product profile

- **C1. Mnemosyne-8 (native single-node profile):** no Docker/VM; native service binaries; SqliteEngine (parity-proven via the shared engine contract); in-process ONNX embedder and compact models; encrypted local keystore with identical crypto-shred semantics (key deletion ⇒ data unrecoverable); loopback/unix-socket transport by default (TLS only when network-exposed); audit chain, Ed25519 signing, and C2PA verification unchanged (in-app libraries). Documented single-tenant boundary — a threat-model fit, not a weakened rail. External IdP optional for multi-user.
- **C2. `mnemo8-parity` suite:** the single-node profile must pass the same L0–L2 behavioral tests as the compose stack.
- **C3. Physical 8 GB acceptance rig** (used Apple Silicon mini-class machine): triple duty — `COMPACT-MODEL-8GB-ACCEPTANCE.md` physical custody, Phase 14 independent reproduction host, and the machine on which the headline number is captured.
- **C4.** The 20-container compose stack remains the multi-tenant server deployment. A 64 GB development machine is an explicitly optional accelerator, required by no claim.

### D — Ops and economics hardening (resolves P5, P6)

- **D1.** Finish MCP client-cert rotation automation (in flight) plus a renewal timer comfortably inside the 6-hour expiry floor.
- **D2.** Complete the staged step-ca trust rotation.
- **D3.** Self-hosted runner for the `macos-14` wheels job; gate hosted macOS wheels to tags/releases before enabling Phase 13's scheduled cadence; keep 1× Ubuntu jobs hosted.
- **D4.** Daily rails-health check (cert expiry, Vault seal, restart counts, load) alerting before eval windows rather than failing during them.

### E — Governance and publication (resolves the P7 long-lead)

- **E1.** Begin GOV-001 external board recruitment immediately (zero code, longest lead time; Phase 16 hard-gates on it).
- **E2.** Reserved headline claim: "Full capability, EM/F1 ≥ 0.85, deterministic retrieval 1.0, physical 8 GB machine, bit-identical answers at every hardware scale." Captured under PBPP with the acceptance receipt.
- **E3.** Phase 13 external adapters + scheduled CI proceed after Phase 12 closes, contingent on D3.

## 4. Sequence

- **Immediately:** A1 → A2 (v19 protected attempt) ∥ B2 ∥ E1 ∥ order C3 rig.
- **This week:** Decision Point 1 → B3 ∥ D1–D4.
- **Next:** v20 (→ v21 per Decision Point 2) → ≥0.85 frozen gate → once-ever held-out LongMemEval-QA + Hippo reader runs + BENCH-005 graph/PPR evidence → Phase 12 closes → C1/C2 build → acceptance capture on C3 → Phases 13–16.

## 5. Risks

1. **Extractive plateau below 0.85 on synthesis questions** → mitigated by the 0.6b floor-resident rung (v21) and by teacher strength during distillation; the deterministic components keep shrinking what the models must do.
2. **Cross-backend float divergence** breaking bit-parity → mitigated by INT8 quantization (integer arithmetic), pinned ORT versions, and the B5 gate; fall back to a documented tolerance policy only if exact parity is provably unattainable, disclosed in custody.
3. **Single-tenant auth boundary criticism** → documented threat-model fit; multi-tenant remains the server stack's job.
4. **Memory floor recurrence** → A1 script + D4 alerts make admission deterministic; the C3 rig eventually decouples acceptance evidence from the crowded dev host entirely.
