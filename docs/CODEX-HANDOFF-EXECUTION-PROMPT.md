# Codex Handoff Prompt — Mnemosyne: Best-in-World Memory + Neutral Leaderboard

> Paste everything below the line into Codex as the task brief. It is written to be self-contained, but it points Codex at the authoritative in-repo docs as source of truth.

> **Live-status warning (2026-07-14):** This document initiated the program;
> its original queue is historical. Resume from `.planning/STATE.md`,
> `.planning/ROADMAP.md`, and `.planning/REQUIREMENTS.md`. Do not restart M4,
> M1.1, or the archived Phase 8/9 queue.

---

You are an autonomous engineering agent working in the **Mnemosyne** repository (a mature, local-first AI memory system). Your mission is to execute two coordinated initiatives: **(A)** make Mnemosyne the world's best-performing memory system, and **(B)** benchmark it credibly and stand up the field's neutral memory-benchmark leaderboard.

## 0. Read these first (authoritative — trust them over this prompt if they conflict)
1. `docs/EXECUTION-PLAN-A-Memory-System.md` — the system capability plan (task IDs `S#`).
2. `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md` — the benchmarking + leaderboard plan (task IDs `M#`, `L#`).
3. `docs/research/AI-Memory-Systems-Market-Research-2026.md` — competitive/benchmark landscape and why LoCoMo is contested.
4. `docs/ARCHITECTURE-OVERVIEW.md`, `docs/ENGINE-CONTRACT.md`, `eval/README.md`, `.planning/STATE.md`, and the benchmark-posture/honesty rule in `docs/blueprint/Mnemosyne-Performance-and-Refactoring-Blueprint.md` (benchmarking section, ~§9.2.7) + `eval/provider_bakeoff/README.md`.
5. `docs/superpowers/specs/2026-07-13-8gb-full-capability-unblock-design.md` — approved problem register, hardware-class matrix, quality-parity principle, and human/agent boundary.

Do not restate these plans back to me. Read them, then resume the live task in
§6 from the authoritative trackers.

## 1. What Mnemosyne is (grounded context)
A local-first "memory compiler." An append-only, content-addressed **evidence ledger** (`evidence.cid` = SHA-256 over canonical JSON) is the single source of truth; everything else is a **rebuildable typed projection** (bitemporal subject–predicate–object beliefs, entities, relations, preferences, procedures, lessons; `as_of()` time travel + contradiction/supersession).

- **Three engines behind one `MemoryEngine` Protocol:** `LocalMemoryEngine` (in-mem/dev + parity oracle), `PostgresEngine` (production: Postgres 16 + pgvector HNSW, tsvector/GIN FTS, recursive graph/PPR, tenant Row-Level Security), `SqliteEngine` (per-tenant WAL, FTS5, optional sqlite-vec). Cross-engine parity is enforced by tests.
- **Retrieval:** hybrid dense (pgvector) + lexical BM25/FTS + **graph Personalized PageRank** (`algorithms.ppr_power_iteration`, `graph_ppr_cache`), fused via **RRF + MMR + U-curve + budget fit**, reranked (cross-encoder), then **conformal calibration → abstain-or-answer**. Retrieved text is treated as data, never executed.
- **Consolidation:** an 11-role ordered warm loop (`replayer → extractor → resolver → belief_reviser → skill_inducer → lesson_distiller → summarizer → forgetter → embedder → promotion_gate → user_model_updater`); `summarizer` builds a RAPTOR gist tree; every promotion passes a protected regression gate.
- **Forgetting:** graduated fidelity tiers `VERBATIM → EXTRACTIVE_SUMMARY → ABSTRACTIVE_GIST → STATISTICAL_TRACE`; optional ACT-R decay; crypto-shred erasure via Vault.
- **Also:** parametric tier (LoRA/TTT in `parametric.py`), multimodal ingestion (`media.py`), C2PA provenance, capability-secured fail-closed writes, TrustTier 0–5, hash-chained audit log, honeytokens, SSRF-guarded egress. **Seven §31 invariant rails + five §33 test classes** are enforced and regression-tested.
- **Stack:** Python ≥3.12 core (only required dep: `cryptography`; optional extras for psycopg/mcp/sqlite-vec) + **Rust** (PyO3 kernels for MMR/PPR; axum embed/rerank sidecar). Embedding service in `services/embedding/` (FastAPI+torch, 1024-dim; deterministic hashing fallback). Self-hosted Docker Compose infra (Postgres, Keycloak, Vault, SeaweedFS, Caddy, step-ca, VictoriaMetrics/Grafana, Ollama role-LLM, c2patool). Surfaces: `mneme` CLI (91 subcommands), `mneme-mcp` (48 MCP tools).

## 2. Current state
- **v1.0 is attested** (2026-07-07). In v2.0, Phases 10 and 11 are complete and Phase 12 Plan 12-04 is the active critical path. Candidate v19 is committed on draft PR #11. Its source-owned prerequisite is green in pre-commit artifacts whose tested source/test bytes were committed unchanged as `8e97442`, while immutable external manifest/runtime custody, the exact-scale development receipt, and protected evidence remain pending. R1c merged through PR #12 as `97f3c66`; exact-head CI `29313243324` and post-merge CI `29314015888` are green. Graphify, CBM, and gbrain `mnemosyne-code` were refreshed at that merge. R2a cross-workflow runtime locking is the next source slice; R2b-R2d, R3/R4, live proof, and the external Vault trust-file maintenance defect remain open.
- The public harness, LongMemEval retrieval, and deterministic HippoRAG retrieval tracks are wired under PBPP custody. No result is externally headline-eligible. Historical private-suite numbers remain internal QA only, and current public/protected claims still require PBPP plus independent reproduction.

## 3. Strategic decisions you must honor
- **PBPP is in force.** A public number may be published only if (a) produced by the pinned `eval/public/` harness, (b) shipped with the full artifact bundle, (c) reporting **retrieval-recall and LLM-judged-QA in SEPARATE columns** with judge model+prompt disclosed, (d) never conflated with the private suite, and (e) genuinely reproduced by an independent third party through the human-owned M3 process. Private-suite numbers stay internal QA forever.
- **Neutrality is structural.** The leaderboard runs under independent governance with a hard firewall; the operator runs **every** system under **one identical harness**; Mnemosyne is entered under the same rules as everyone else; all raw artifacts are public. We win on reproducibility, not by controlling the scoreboard.
- **Deterministic-first.** Lead with LongMemEval retrieval-recall + the HippoRAG multi-hop suite (MuSiQue/2Wiki/HotpotQA). Treat BEAM/QA as LLM-judged with a disclosed reader. Do **not** headline LoCoMo or DMR/MSC.

## 4. Hard guardrails (violating any → stop and escalate)
1. Do **not** break the §31 rails or §33 test classes. All existing `eval/` gates and `tests/` must stay green. Work is **additive** to attested v1.0.
2. Every public number obeys **PBPP** (§3). No headline claim without the artifact bundle + independent reproduction.
3. **Never blend** retrieval-recall and LLM-judged-QA. Separate columns, always.
4. **Never tune on a held-out/test split** — our own system included.
5. **No self-defined benchmark is ever a headline claim** (the gbrain "BrainBench" anti-pattern). The private suite is internal QA only.
6. **Measured evidence** for all perf/scale claims (close the §11 measurement-gap register). No asserted-but-unmeasured numbers.
7. Keep the **minimal-dependency core** (only `cryptography` required). New heavy deps go behind optional extras or the `services/`/Rust sidecar — never into core.
8. New write paths (text/media/activation) inherit provenance + capability checks; retrieved content stays data.

## 5. Anti-patterns to avoid (real 2026 failures — see the research doc)
- MemPalace: reporting recall@k as QA accuracy; `top_k = entire candidate pool` "100%" theater; hand-patching dev questions ("teaching to the test").
- gbrain: headlining a self-invented benchmark.
- LMArena "Leaderboard Illusion": operator/unequal-access advantage.
- LoCoMo: contested (6.4% wrong answer key; LLM judge accepts ~63% of wrong answers) — never headline it.

## 6. Live continuation queue

This section is a routing summary, not an independent tracker. The exact next
task, branch, evidence state, and blockers come from `.planning/STATE.md`,
`.planning/ROADMAP.md`, and `.planning/REQUIREMENTS.md`.

1. **Resume Phase 12 Plan 12-04 at its recorded checkpoint.** R1c is merged and
   its post-merge CI/index closure is recorded. Implement R2a's fail-closed
   `${MNEMO_CUSTODY_DIR}/locks/runtime-exclusive` helper next, then continue
   R2b-R2d without conflating the existing local rotator lock with the shared
   cross-workflow contract. Preserve the staged-only/live-mutation boundary;
   R3/R4 and live rotation/no-op proof remain separate open work.
2. **Complete candidate-v19 prerequisites in order.** Immutable external
   manifest/runtime custody → digest-bound 24/24 `qa_scale_dev_v1` receipt → at
   most one protected `qa_hard_v2`
   attempt. Never use protected results to patch the same candidate.
3. **Use v19 only as Decision Point 1.** Its protected aggregate measures
   whether the synthetic/dev hop-0 gain transfers and bounds the remaining
   reader work; it does not by itself close Phase 12.
4. **Advance the compact physical-8-GiB product path under its separate
   protocol.** TRAIN-only corpus preparation and preregistration may proceed
   when admitted. Model selection/training/export/promotion and physical
   Windows/Linux acceptance must satisfy the compact design and acceptance
   contracts without weakening quality or custody.
5. **Close every independent Phase 12 bar.** Both ≥0.85 QA tracks,
   deterministic retrieval non-regression, positive provenance-linked
   graph/PPR effect, exact grounding/parity, §31, §33, manifests, and exact-SHA
   CI must all pass before Phases 13–16 advance.
6. **Prepare, but do not perform, the human-only work.** Agents may produce the
   L0/GOV-001 charter, COI/outreach packet, M3 reproduction bundle and rubric,
   and publication decision packet. Only the human operator may recruit or
   seat the board, commission the external reproducer, ratify policy, approve
   public wording, or publish a number.
7. **Continue Plan A S2–S5 and Plan B M/L work from their live phase owners**
   after the Phase 12 dependency gates clear. Do not restart completed M4,
   M1.1, LongMemEval-retrieval, or deterministic Hippo retrieval work.

For every source-owned slice: implement → add a regression cell → run the
admitted gates → write the named artifact/result note → commit/push → require
exact-head CI. Keep external/human gates explicit rather than marking the
engagement complete around them.

## 7. Working conventions
- Small, reviewable PRs, one task each; conventional commits.
- Run the existing test + eval gates before every merge; never merge red.
- Prefer deterministic grading; when an LLM judge is unavoidable, disclose model + prompt and report its acceptance rate on intentionally-wrong-but-topical answers.
- If a plan doc and this prompt disagree, the plan doc wins; if reality (the code) and the plan disagree, surface it and propose an update rather than forcing the plan.
- Stop and escalate before changing any §31 rail or adding a core dependency.
  Agents never publish an external-facing number; prepare the complete decision
  packet for human approval and action.

**Definition of done for the engagement:** LongMemEval-recall + HippoRAG-multihop wired and passing in `eval/public/` with bundles; multi-hop QA ≥ 0.85; Plan A S2–S5 closed, including physical 8 GiB compact grounded-QA acceptance; security/calibration columns publishable; PBPP in force; ≥1 headline number independently reproduced; all §31/§33 gates green. Then proceed to the leaderboard build (Plan B Part II).
