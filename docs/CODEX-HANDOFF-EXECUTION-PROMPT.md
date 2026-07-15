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
- **v1.0 is attested** (2026-07-07). In v2.0, Phases 10 and 11 are complete and Phase 12 Plan 12-04 is the active critical path. Candidate v19 source/runtime/bundle custody is merged on `main@79f6b58`, while immutable external manifest/runtime custody, the 24/24 exact-scale development receipt, and protected evidence remain pending. R1c merged through PR #12 as `97f3c66`. R2a exact head `5bfd53d` passed CI `29377793617`, merged through PR #13 as `33967b1`, passed PR #11 exact-head CI `29378482152`, and merged to `main` through PR #11 as `79f6b58`; post-merge main CI `29379113689` passed all six gating jobs. The R2a surface is green at 55/55 focused, 39/39 §31, 7/7 §33, and 2/2 planning tests, with terminal CodeRabbit and independent reviews complete. Do not redo R2a. The final documentation reconciliation and hardware-admitted exact-final-main Graphify/CBM/gbrain refresh complete its delivery receipt. R2b-R2d, R3/R4, live proof, and the external Vault trust-file maintenance defect remain open.
- The public harness, LongMemEval retrieval, and deterministic HippoRAG retrieval tracks are wired under PBPP custody. No result is externally headline-eligible. Historical private-suite numbers remain internal QA only, and current public/protected claims still require PBPP plus independent reproduction.
- Full/index/model/live work is not admitted by a single good host sample. Run the complete three-sample hardware, TLS, Vault, service, and topology preflight first. The latest read-only gbrain Doctor result has one non-OK check (`cycle_freshness`); supervisor crashes are zero, historical failures are acknowledged, and no source sync has yet been admitted for this slice.

## 3. Strategic decisions you must honor
- **PBPP is in force.** A public number may be published only if (a) produced by the pinned `eval/public/` harness, (b) shipped with the full artifact bundle, (c) reporting **retrieval-recall and LLM-judged-QA in SEPARATE columns** with judge model+prompt disclosed, (d) never conflated with the private suite, and (e) genuinely reproduced by an independent third party through the human-owned M3 process. Private-suite numbers stay internal QA forever.
- **Neutrality is structural.** The leaderboard runs under independent governance with a hard firewall; the operator runs **every** system under **one identical harness**; Mnemosyne is entered under the same rules as everyone else; all raw artifacts are public. We win on reproducibility, not by controlling the scoreboard.
- **Deterministic-first.** Lead with LongMemEval retrieval-recall + the HippoRAG multi-hop suite (MuSiQue/2Wiki/HotpotQA). Treat BEAM/QA as LLM-judged with a disclosed reader. Do **not** headline LoCoMo or DMR/MSC.

**Standing execution authority:** proceed autonomously through all agent-owned
work without per-task approval. You may create branches, write code and tests,
add dependencies behind the required optional-extra/sidecar boundaries, run
admitted suites and evaluations, commit and push, open and merge PRs to
`main`, update documentation and knowledge indexes, and iterate until the
applicable definitions of done are met. The four hard stops below are the only
approval pauses; every other failure is a constraint to satisfy or a blocker to
work around and record.

## 4. The only four hard stops
1. **Invariant safety:** never break or weaken the §31 invariant rails or §33
   test classes. Stop and flag any change that would do so.
2. **External claims:** do not publish an externally facing number or public
   claim until it has passed PBPP and genuine independent reproduction.
   Building and running the benchmarks is authorized; external publication is
   the stop.
3. **Human governance and reproduction:** do not recruit or seat the external
   governance board, ratify policy on its behalf, or commission the third-party
   reproduction. Prepare the complete packets and hand those acts to the human
   operator.
4. **Destructive or irreversible operations:** do not rewrite shared history,
   force-push, delete data, commit secrets, or perform an equivalent
   irreversible operation without first stopping and flagging it.

Requirements to enforce inside the autonomous loop: keep all applicable
`eval/` gates and tests green; never blend retrieval-recall with LLM-judged QA;
never tune on held-out/test data; never headline a self-defined benchmark;
require measured evidence for performance/scale claims; keep heavy dependencies
behind optional extras or services/Rust sidecars; and preserve provenance,
capability checks, and the data-only treatment of retrieved content on every
new write path.

## 5. Anti-patterns to avoid (real 2026 failures — see the research doc)
- MemPalace: reporting recall@k as QA accuracy; `top_k = entire candidate pool` "100%" theater; hand-patching dev questions ("teaching to the test").
- gbrain: headlining a self-invented benchmark.
- LMArena "Leaderboard Illusion": operator/unequal-access advantage.
- LoCoMo: contested (6.4% wrong answer key; LLM judge accepts ~63% of wrong answers) — never headline it.

## 6. Live continuation queue

This section is a routing summary, not an independent tracker. The exact next
task, branch, evidence state, and blockers come from `.planning/STATE.md`,
`.planning/ROADMAP.md`, and `.planning/REQUIREMENTS.md`.

1. **Resume Phase 12 Plan 12-04 at its recorded checkpoint.** Verify the live
   final-main delivery/index receipt and local/GitHub cleanliness; do not redo
   the merged R2a coordinator. Run the separately rollback-safe Vault CA repair
   under the accepted shared lock, then integrate and prove R2b-R2d without
   conflating the local rotator lock with the shared contract. Preserve the
   staged-only/live-mutation boundary; R3/R4 and live rotation/no-op proof
   remain separate open work.
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
- Load `project-orchestration` for the persistent lifecycle and keep GSD as the
  single durable phase/roadmap owner. Use `gsd-autonomous` and `gsd-graphify`
  only at their named execution and graph-refresh checkpoints.
- Use `subagent-driven-development` and `dispatching-parallel-agents` to keep
  multiple bounded subagents active for independent implementation, research,
  and review lanes when they do not conflict. Give every subagent the same hard
  stops and workflow rules, serialize shared-file/stateful work, and explicitly
  close each lane after collecting its evidence.
- Apply Ponytail to every code, refactor, debug, review, and dependency choice;
  prefer no change, reuse, standard library, platform support, and installed
  dependencies before minimal new code. Use test-driven development for every
  behavior change and systematic debugging for every failure.
- Use context-mode/Think-in-Code for large output and session recall; use
  Context7 for current library/SDK/API/CLI documentation. Use CBM first for
  repository architecture/search/trace/impact and `cbm-holistic` for broad
  changes. Use gbrain-system for durable project knowledge, never as a CBM
  substitute, and do not duplicate ownership across memory systems.
- Small, reviewable PRs, one task each; conventional commits. Before staging,
  inspect the complete diff and run the secret/risky-file sweep. Never discard
  user changes, bypass hooks, rewrite shared history, or force-push.
- Run the admitted targeted/full test and eval gates, verification-before-
  completion, independent review, and terminal CodeRabbit before every merge;
  never merge red or reuse stale-head CI. Commit/push incrementally, require
  exact-head checks, verify the merged SHA, and keep local, GitHub, docs, CBM,
  Graphify, and gbrain reconciled to that same accepted SHA.
- Prefer deterministic grading; when an LLM judge is unavoidable, disclose model + prompt and report its acceptance rate on intentionally-wrong-but-topical answers.
- If a plan doc and this prompt disagree, the plan doc wins; if reality (the code) and the plan disagree, surface it and propose an update rather than forcing the plan.
- Never weaken a §31 rail or add a heavy dependency to the minimal core.
  Agents never publish an external-facing number; prepare the complete decision
  packet for human approval and action.

## 8. Definition of done

**R2a source-delivery receipt:** exact head `5bfd53d` passed CI `29377793617`,
merged through PR #13 as `33967b1`, passed stacked CI `29378482152`, and merged
through PR #11 to `main@79f6b58`. The merged reconciliation PR body is the live
owner for its own exact-head/final-main CI and the hardware-admitted
Graphify/CBM/gbrain receipt. Closing R2a does not close R2b-R2d, R3/R4, Vault
CA repair, live proof, candidate-v19 evidence, or Phase 12.

**Agent-owned program:** execute all remaining Plan A and Plan B source-owned
work through Plan B L4 preparation: public harness and bundles; both ≥0.85 QA
tracks; retrieval non-regression; positive graph/PPR contribution; physical
Windows/Linux 8 GiB full-capability acceptance; security/calibration/scale
evidence; reproducibility materials; governance and publication packets;
leaderboard repository/site/explainers/methods/raw-data launch artifacts; and
all §31/§33/custody/exact-SHA gates. Do not stop at Plan B Part I.

**Human-only overall gates:** the engagement is not externally launch-complete
until the human operator seats/ratifies the independent board, commissions and
receives genuine third-party reproduction, approves public wording, and
publishes. Agents prepare complete packets but never impersonate those acts or
publish a number.
