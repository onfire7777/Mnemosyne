# Codex Handoff Prompt — Mnemosyne: Best-in-World Memory + Neutral Leaderboard

> Paste everything below the line into Codex as the task brief. It is written to be self-contained, but it points Codex at the authoritative in-repo docs as source of truth.

> **Live-status warning (2026-07-12):** This document initiated the program;
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

Do not restate these plans back to me. Read them, then execute the task queue in §6.

## 1. What Mnemosyne is (grounded context)
A local-first "memory compiler." An append-only, content-addressed **evidence ledger** (`evidence.cid` = SHA-256 over canonical JSON) is the single source of truth; everything else is a **rebuildable typed projection** (bitemporal subject–predicate–object beliefs, entities, relations, preferences, procedures, lessons; `as_of()` time travel + contradiction/supersession).

- **Three engines behind one `MemoryEngine` Protocol:** `LocalMemoryEngine` (in-mem/dev + parity oracle), `PostgresEngine` (production: Postgres 16 + pgvector HNSW, tsvector/GIN FTS, recursive graph/PPR, tenant Row-Level Security), `SqliteEngine` (per-tenant WAL, FTS5, optional sqlite-vec). Cross-engine parity is enforced by tests.
- **Retrieval:** hybrid dense (pgvector) + lexical BM25/FTS + **graph Personalized PageRank** (`algorithms.ppr_power_iteration`, `graph_ppr_cache`), fused via **RRF + MMR + U-curve + budget fit**, reranked (cross-encoder), then **conformal calibration → abstain-or-answer**. Retrieved text is treated as data, never executed.
- **Consolidation:** an 11-role ordered warm loop (`replayer → extractor → resolver → belief_reviser → skill_inducer → lesson_distiller → summarizer → forgetter → embedder → promotion_gate → user_model_updater`); `summarizer` builds a RAPTOR gist tree; every promotion passes a protected regression gate.
- **Forgetting:** graduated fidelity tiers `VERBATIM → EXTRACTIVE_SUMMARY → ABSTRACTIVE_GIST → STATISTICAL_TRACE`; optional ACT-R decay; crypto-shred erasure via Vault.
- **Also:** parametric tier (LoRA/TTT in `parametric.py`), multimodal ingestion (`media.py`), C2PA provenance, capability-secured fail-closed writes, TrustTier 0–5, hash-chained audit log, honeytokens, SSRF-guarded egress. **Seven §31 invariant rails + five §33 test classes** are enforced and regression-tested.
- **Stack:** Python ≥3.12 core (only required dep: `cryptography`; optional extras for psycopg/mcp/sqlite-vec) + **Rust** (PyO3 kernels for MMR/PPR; axum embed/rerank sidecar). Embedding service in `services/embedding/` (FastAPI+torch, 1024-dim; deterministic hashing fallback). Self-hosted Docker Compose infra (Postgres, Keycloak, Vault, SeaweedFS, Caddy, step-ca, VictoriaMetrics/Grafana, Ollama role-LLM, c2patool). Surfaces: `mneme` CLI (91 subcommands), `mneme-mcp` (48 MCP tools).

## 2. Current state
- **v1.0 is attested** (2026-07-07). In v2.0, Phases 10 and 11 are complete and Phase 12 Plan 12-04 is the active critical path. Candidate v19 is committed on draft PR #11; its hardware-admitted full suite, external manifest, exact-scale development receipt, and protected evidence remain pending.
- The public harness, LongMemEval retrieval, and deterministic HippoRAG retrieval tracks are wired under PBPP custody. No result is externally headline-eligible. Historical private-suite numbers remain internal QA only, and current public/protected claims still require PBPP plus independent reproduction.

## 3. Strategic decisions you must honor
- **Honesty pivot → PBPP.** The repo currently forbids headlining public benchmarks. Replace that blanket ban with the **Public-Benchmark Publication Protocol**: a public number may be published only if (a) produced by the pinned `eval/public/` harness, (b) shipped with the full artifact bundle, (c) reporting **retrieval-recall and LLM-judged-QA in SEPARATE columns** with judge model+prompt disclosed, (d) never conflated with the private suite, (e) independently reproducible from the bundle. Private-suite numbers stay internal QA forever.
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

## 6. Task queue (execute in order; each task's full DoD is in the plan docs)
**Critical path first.** Open a branch + PR per task. For each: implement → add a regression cell → keep all gates/tests green → write the artifact + a one-paragraph result note (`eval/reports/` or `leaderboard/reports/`).

1. **[Plan B · M4] Charter → PBPP.** Edit the benchmark-posture/honesty rule in the perf blueprint (benchmarking section) and `eval/provider_bakeoff/README.md` to reference PBPP instead of a blanket prohibition. DoD: docs updated; contributor lint points at PBPP.
2. **[Plan B · M1.1] Scaffold `eval/public/`.** New isolated tree that drives **only the public `mneme` CLI** (same discipline as `eval/run_eval.py`), pins each benchmark to a commit, and emits the reproducibility bundle (pinned commit, per-question traces of {stored, retrieved, answer}, disclosed judge/config, build fingerprint, Wilson/bootstrap CIs, one-command reproduce). DoD: `mneme eval-public --suite X` runs end-to-end and writes traces.
3. **[Plan B · M1.2] LongMemEval — retrieval-recall track.** Deterministic Recall@k / nDCG on the dataset's session/turn gold labels; **no LLM in scoring**. DoD: R@5 + Wilson CI + per-question retrieval traces.
4. **[Plan B · M1.3] HippoRAG multi-hop suite.** MuSiQue / 2WikiMultiHopQA / HotpotQA; deterministic Recall@2/@5 + EM/F1; exercises the graph+PPR channel. DoD: results table vs published HippoRAG 2 baselines.
5. **[Plan A · S1] Close the multi-hop answer-synthesis gap (top capability lever).** Add an iterative retrieve→read loop (query decomposition → PPR hops → evidence assembly) + a grounded reader (self-hosted Ollama role-LLM) that answers ONLY from retrieved, provenance-tagged evidence (every claim traces to an evidence CID) + EM-LLM-style episode-aware recall. DoD: `qa_hard_v2` and public LongMemEval-QA ≥ 0.85 with grounded per-hop traces; no deterministic-recall regression.
6. **[Plan B · M1.4 / M1.5] MemoryAgentBench adapter (upstream PR) + BEAM** (disclosed reader). DoD per plan.
7. **[Plan B · M2/M3] Reproducibility bundle standard + commission independent third-party reproduction** of headline numbers before any external claim.
8. **[Plan A · S3–S4] Security/calibration publication columns + perf/scale close-out** (expand MINJA/AgentPoison/PoisonedRAG to attack-success-under-defense; calibration vs public labels; concurrent+warm P95; 100k-item cells; provider default). These fill columns no competitor fills.

The neutral leaderboard build (Plan B · L0–L4: governance charter, methodology harness, `web/` site, launch) is the second phase — begin its governance/charter (L0) in parallel once M1 is underway, but do not build the public site until Part I results and PBPP are in force.

## 7. Working conventions
- Small, reviewable PRs, one task each; conventional commits.
- Run the existing test + eval gates before every merge; never merge red.
- Prefer deterministic grading; when an LLM judge is unavoidable, disclose model + prompt and report its acceptance rate on intentionally-wrong-but-topical answers.
- If a plan doc and this prompt disagree, the plan doc wins; if reality (the code) and the plan disagree, surface it and propose an update rather than forcing the plan.
- Ask before: changing any §31 rail, adding a core dependency, or publishing any external-facing number.

**Definition of done for the engagement:** LongMemEval-recall + HippoRAG-multihop wired and passing in `eval/public/` with bundles; multi-hop QA ≥ 0.85; security/calibration columns publishable; PBPP in force; ≥1 headline number independently reproduced; all §31/§33 gates green. Then proceed to the leaderboard build (Plan B Part II).
