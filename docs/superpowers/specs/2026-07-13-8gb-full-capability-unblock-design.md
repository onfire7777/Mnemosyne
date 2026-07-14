# Mnemosyne — 8 GB Full-Capability Design and Progression Unblock Plan

**Date:** 2026-07-13
**Status:** Approved governing specification — execution in progress
**Scope:** Synthesis of the current progression problems, their resolutions, and
the governing product principles. It extends — and does not replace —
`docs/research/Compact-Reader-Reranker-8GB-Design.md`,
`.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md`,
`.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md`, the Phase 12 candidate
protocol, PBPP, or the §31/§33 rails. No frozen protocol, threshold, custody
rule, publication gate, or human-only governance boundary is changed here.
Approval authorizes implementation, not an 8 GiB compatibility result or a
benchmark/public claim.

## 1. Governing principles

1. **Full capability at physical 8 GiB.** Every product capability and every
   security rail must fit the preregistered floor envelope: at most 1 GiB of
   model/tokenizer artifacts, at most 3 GiB compact-sidecar peak memory, at
   most 6.5 GiB for the whole Mnemosyne process tree, and at least 1.5 GiB
   system-available memory throughout the exact-scale workload. A 2–2.5 GiB
   process target is an optimization goal, not accepted evidence. No compact
   model, including a possible `qwen3:0.6b` synthesis rung, is selected merely
   by appearing to fit on paper.
2. **Quality parity everywhere.** For the same corpus and request, the product
   quality path uses the same quality-critical artifacts, policy, budgets, and
   decoded decision on every admitted machine. Stronger hardware may improve
   latency, throughput, supported corpus capacity, and concurrency; it may not
   unlock a higher-scoring product configuration. Larger or hosted readers may
   exist only as separately disclosed research/teacher/comparison tracks.
   Reference, ONNX FP32, and promoted ONNX INT8 outputs must pass the exact
   span/abstention parity contract before promotion; no unsupported claim of
   cross-provider bit identity is made in advance.
3. **The compact stack is the product path, not a reduced variant.** The pinned
   `qwen3:8b` reader remains candidate-v19 development infrastructure, but it
   is not accepted as the physical-8-GiB product path. The compact candidate
   must be selected, trained, exported, and proven under the existing custody
   and acceptance protocols. Native acceleration supplies the stronger-host
   advantage through equivalent work completed faster.
4. **No custody compromise.** Preregistration, one-attempt-per-protected-split, once-ever held-out runs, TRAIN-only decontaminated corpora, digest pinning, and the hardware admission runbook all stand unchanged.

Evidence terms in this document are strict: **verified** means an immutable
artifact or exact-SHA check exists; **pending** means the gate has not passed;
**hypothesis** means a proposed design or claim; and **human-owned** means an
agent may prepare materials but may not perform the decision or external act.

## 2. Problem register (as of 2026-07-13)

| # | Problem | Evidence | Severity |
|---|---|---|---|
| P1 | Hardware admission is a recurring capacity constraint, not the current full-suite blocker | After bounded reclamation and serialized waiting, the complete gate passed at 56%/56%/57% free memory, load1 2.75/2.21/3.04, load5 5.33/5.08/5.09, and zero models; the 2,571-test full suite then passed. Duplicate installers, security scans, Brave relaunches, and VM-origin model loads showed why every later model/index/live/protected window must re-gate independently. | High, operational |
| P2 | Protected QA remains 0.0833 vs ≥0.85 | v17 and v18 each answered 2/24 and abstained at hop 0 on 22/24, with EM/F1 0.083333. v19's deterministic planner passes synthetic/dev gates but its protected effect and remaining reader residual are unmeasured. Both `qa_hard_v2` and held-out LongMemEval-QA must reach ≥0.85 without retrieval regression. | Critical |
| P3 | One-shot evidence economics | Five protected attempts are recorded: v3, v12, v13, v17, and v18. v12 produced no result because the 120-second outer wrapper expired. A digest-bound 24/24 exact-scale development receipt is now mandatory before another protected attempt. | High |
| P4 | No physical-8-GiB product path is proven | The compact reader/reranker work is design and preregistration only: no model has been selected, trained, downloaded, or accepted. Four probed local generative substitutes were rejected; that evidence does not exclude every possible model. Physical Windows and Linux x86-64 acceptance remains mandatory, with ARM64 additional rather than substitutive. | High |
| P5 | Production admission rails remain unfinished | MCP rotation R1c now has fixture-proven crash-resumable post-activation rollback, current section-31/section-33/planning evidence, a green 2,571-test full suite, and green exact-SHA CI on evidence head `7541635`. Committed reproof/finalization and the later live-window proof remain open. Vault recovery, dual-root trust debt, short-lived certificate renewal, and restart stability remain operational prerequisites. | High |
| P6 | Passing frozen QA alone cannot close Phase 12 | LongMemEval-QA ≥0.85, deterministic retrieval non-regression, positive provenance-linked graph/PPR effect, §31 rails, §33 classes, custody, and held-out controls are independent exit bars. Current Hippo evidence has zero positive graph/PPR participation. | High |
| P7 | CI is restored, but current-head and cost controls remain open | Billing was restored on 2026-07-12 and exact-SHA CI is available. Every later merge candidate still needs its own exact-head run. Hosted macOS wheel cadence should be optimized from measured billing artifacts; no unverified multiplier or push-rate estimate is treated as fact. | Medium |
| P8 | Governance and reproduction are human-owned long leads | Agents may prepare charters, recruitment packets, evidence bundles, and reproduction instructions. They may not recruit or seat the board, ratify policy on its behalf, commission the independent reproducer, approve public wording, or publish a number. | High, external |
| P9 | Knowledge freshness has one bounded post-commit closure step | The generated Graphify snapshot is current at `7541635` with 16,171 nodes, 27,405 edges, 1,171 communities, and zero commits behind, and a strong-gated Mnemosyne CBM index is ready with 15,578 nodes and 64,541 edges. Because CBM and gbrain are mutable external indexes, their final refresh must run after the evidence commit and be recorded in PR #12; availability alone is not freshness, and any later source edit reopens the check. | Medium, controlled |

**System diagnosis:** the admitted full-suite window closes P1 for this slice,
but not for later model/index/live/protected workloads, which must re-gate.
P2 is the central science gap, not the sole Phase 12 exit condition; P3, P5,
P6, and the human-owned gates must also close without weakening custody.

## 3. Hardware-class execution matrix

| Work class | Minimum admission | Examples and rule |
|---|---|---|
| Read-only/static | No heavy-work admission; avoid overlapping an evidence capture | Documentation, diff review, Bash syntax, Ruff/ShellCheck when they do not start services or models. |
| Serialized targeted unit | One fresh sample: memory free ≥35%, host load1 ≤10, zero resident model | A named focused test module/tier, run serially. The current R1c rotator/combined/regression tiers belong here; counts are evidence targets, not a reason to invoke the disruptive eval-window script. |
| Full project suite, index, live runtime, or VM change | Three samples 15 seconds apart: memory free ≥55%, load1 ≤7, load5 ≤8, plus topology, certificate, Vault, restart, and duplicate-stack rails | Apply `.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md` exactly. Never infer admission from one good sample. |
| Model load/probe/training on this host | Strong preflight plus model-residency, GPU placement, post-load memory, swap, context, and single-model rails | Reject before load when the artifact or expected residency is not viable. Prefer authorized remote training for the compact bakeoff; protected assets remain unreachable. |
| Exact-scale development eval | The runbook's full-scale subgate and abort monitors, after all candidate prerequisites | One process/question/model request at a time; 24/24 receipt must be digest-bound before protected access. |
| Protected/held-out | Passing exact-scale receipt plus fresh 60-second idle admission and all custody/topology rails | One permitted attempt, no concurrent CI/index/test/model work, and no protocol change after preregistration. |

## 4. Phase 12 exit matrix

| Gate | Required evidence |
|---|---|
| Frozen internal QA | `qa_hard_v2` EM ≥0.85 and token F1 ≥0.85 under the preregistered disclosed reader. |
| Held-out public-source/internal-only QA | LongMemEval-QA EM ≥0.85 and token F1 ≥0.85 on its once-ever reader track. |
| Retrieval | Frozen Recall@5/nDCG@5 remain 1.0/1.0; LongMemEval and all Hippo retrieval tracks do not regress. |
| Graph contribution | Positive provenance-linked graph/PPR participation with a preregistered counterfactual or ablation proving an effect. |
| Grounding and parity | Zero unsupported CID/span output; reference→FP32→INT8 decoded span/abstention parity; exact-scale receipt remains 24/24. |
| Invariant rails | Every §31 rail and §33 test class green on the exact merge candidate. |
| Custody | Immutable manifests, TRAIN-only decontamination, one-shot ledgers, no held-out inspection/tuning, and exact-SHA CI evidence. |
| Publication | No external claim until PBPP is complete and a genuine independent reproduction is on file; board/reproducer/publication acts remain human-owned. |

## 5. Workstreams

### A — Immediate unblock (resolves P1, P3)

- **A1. Eval-window preparation:** use the guarded reclamation helper only for a planned strong-workload window and only through its explicit opt-in confirmation. It may quit only the fixed Brave/Discord allowlist; it never stops services, inspects secrets, runs admission checks, or returns success as an admission signal. Its dedicated `ADMISSION PENDING` exit is followed by the complete three-sample runbook; only that separate read-only gate can admit work.
- **A2. Run the queues under their real gates:** retain R1c's now-green targeted/full-suite/CI evidence; obtain a new strong admission for the remaining immutable candidate-v19 prerequisites; then produce the 24/24 `qa_scale_dev_v1` receipt under the exact-scale procedure; only then may v19 consume its protected attempt.
- **A3. Hygiene:** land the clean stacked PR #12 only after its remaining R1c boundaries are explicit and its final merge head is green; keep one canonical work stream per machine during eval windows.
- **Alternatives considered:** shrinking the VM below 6 CPU/12 GiB — rejected (runbook-pinned custody topology); scheduled overnight eval windows — adopt as a complement after A1 proves out.

### B — Close the quality gap with the compact stack (resolves P2, P4)

- **B1. Decision Point 1 = v19's protected result.** It measures whether the synthetic/dev hop-0 gain transfers and bounds the remaining reader residual; it is not presumed to pass.
- **B2. Corpus preparation now:** complete source selection, license/provenance review, split/decontamination policy, immutable manifest schema, and bounded-work estimate as static work. Actual download, materialization, decontamination, or bulk hashing is admitted by its measured resource profile; the ≥35% targeted-unit exception does not authorize dataset processing.
- **B3. Remote distillation** per the compact design doc: candidate-scale extractive reader + cross-encoder reranker, strongest custody-approved teacher, TRAIN-only decontaminated corpora, preregistered seeds/hyperparameters, safetensors/ONNX only, ONNX FP32 → dynamic INT8, and all promotion gates. Off-host execution still requires a digest-pinned environment, secrets/cost/timeout controls, retained manifests, and explicit spend authority; P1 is not permission to bypass those controls.
- **B4. Candidate ladder:** v20 = extractive reader behind the unchanged `GroundedReader` interface. **Decision Point 2:** if synthesis-type questions remain below 0.85, v21 may add a preregistered compact synthesis rung under a tight extractive contract. `qwen3:0.6b` is one hypothesis, not a selected floor component; the rung must pass the same quality, custody, and physical-resource gates.
- **B5. Cross-backend parity gate:** require exact decoded spans and abstentions across reference/ONNX artifacts and every supported execution provider. Record byte-level tensor identity only where measured; do not make it a prerequisite claim without evidence.
- **Rejected with reasons:** four task-specific local generative substitutes failed either host feasibility or the required decomposition behavior; hosted API readers cannot define the self-hosted product path; from-scratch LLM training has no evidenced advantage over distillation; learned ranking cannot replace the deterministic retrieval rail.

### C — The 8 GB full-capability product profile

- **C1. Native single-node resource profile:** design a no-VM floor deployment around the shared engine contract, `SqliteEngine`, compact ONNX components, local encrypted key management, loopback/unix-socket defaults, and unchanged audit/provenance/security semantics. Every claimed crypto-shred or single-tenant boundary requires threat-model and parity evidence; this profile is not accepted merely by specification.
- **C2. Resource-floor parity suite:** the single-node profile must pass the same L0–L2 behavioral tests as the compose stack.
- **C3. Physical 8 GiB acceptance matrix:** obtain native x86-64 AVX2 Windows and Linux systems with exactly 8 GiB, and add ARM64 evidence separately. First-party acceptance is not independent reproduction and produces no headline claim by itself.
- **C4.** The 20-container compose stack remains the multi-tenant server deployment. A 64 GB development machine is an explicitly optional accelerator, required by no claim.

### D — Ops and economics hardening (resolves P5, P6)

- **D1.** Finish MCP client-cert rotation automation (in flight) plus a renewal timer comfortably inside the 6-hour expiry floor.
- **D2.** Complete the staged step-ca trust rotation.
- **D3.** Measure CI minute/cost use, then evaluate a hardened self-hosted macOS runner or a release-only hosted wheel cadence without weakening merge-gating source/test coverage. Preserve hosted Ubuntu coverage and supply-chain isolation.
- **D4.** Daily rails-health check (cert expiry, Vault seal, restart counts, load) alerting before eval windows rather than failing during them.

### E — Governance and publication (resolves the P8 long-lead)

- **E1.** Prepare the GOV-001 charter, role criteria, conflict-of-interest policy, outreach packet, and decision checklist for human action. The human operator owns outreach, recruitment, seating, and ratification.
- **E2.** Maintain only an internal claim-requirements matrix. Public wording, numbers, and leadership language remain unapproved hypotheses until PBPP, physical acceptance, and independent reproduction are complete and a human approves publication.
- **E3.** Phase 13 external adapters + scheduled CI proceed after Phase 12 closes, contingent on D3.

## 6. Sequence

- **Immediately:** land the now-green R1c rollback slice; prepare the human governance packet; complete compact-corpus planning and immutable-manifest preparation; establish a strong eval window without disrupting in-flight evidence.
- **Strong window:** remaining immutable candidate-v19 prerequisites → 24/24 exact-scale receipt → protected v19 attempt. A failed gate returns to development under a new candidate; it does not authorize another attempt or a weaker threshold.
- **After Decision Point 1:** execute the custody-approved compact bakeoff and R1c live-window work in separately admitted windows; complete D1–D4 with exact-head CI.
- **Next:** v20 (and v21 only if preregistered evidence requires it) → both ≥0.85 QA gates → retrieval and positive graph/PPR gates → §31/§33/custody close → physical 8 GiB acceptance → Phases 13–16. Human governance and reproduction work proceeds in parallel but is never impersonated by an agent.

## 7. Risks

1. **Extractive plateau below 0.85 on synthesis questions** → mitigated by a separately preregistered compact synthesis candidate and by teacher strength during distillation; no candidate is called floor-resident before physical acceptance.
2. **Cross-backend numeric divergence** breaking decision parity → mitigated by pinned runtimes, deterministic preprocessing/postprocessing, quantization, and the B5 gate. A tolerance policy is a new preregistered protocol decision, never an after-the-fact waiver.
3. **Single-tenant auth boundary criticism** → documented threat-model fit; multi-tenant remains the server stack's job.
4. **Memory floor recurrence** → guarded reclamation plus D4 alerts make strong windows schedulable, but only the runbook samples grant admission. The physical acceptance matrix eventually decouples product-floor evidence from the crowded development host.

## 8. Definition of done for this specification

- Every P1–P9 item is closed by an immutable artifact or explicitly handed to
  its human owner; no stale tracker contradicts the result.
- The compact product path passes the physical Windows/Linux 8 GiB contract
  and the cross-backend decision-parity matrix without a weaker quality rail.
- All Phase 12 exit-matrix rows pass on the exact merge candidate.
- Plan A, Plan B, the handoff, roadmap, requirements, state, result reports,
  CBM, GSD, and gbrain point to the same current evidence without duplicating
  an authority.
- No external compatibility, performance, benchmark, or leadership claim is
  made until PBPP and genuine independent reproduction are complete and the
  human-owned publication decision is recorded.
