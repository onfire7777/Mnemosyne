# Mnemosyne — Execution Plan B: Benchmarking & the Leaderboard
## Goal: prove Mnemosyne's results credibly, and build the field's neutral memory-benchmark leaderboard

**Version:** 1.2 · **Date:** 2026-07-13 · **Status:** In Progress (approved)
**Scope:** the public benchmark harness (`eval/public/`), the publication protocol, and the greenfield `leaderboard/` + `web/` products.
**Companion doc:** *Execution Plan A — The Memory System* builds the capabilities this plan measures. This plan owns measurement, publication, and the leaderboard. Where Plan A says "measured/published," the authority is here.
**Audience:** an autonomous engineering agent (or fleet) executing end-to-end, plus human operators for governance and third-party reproduction.

**Live execution routing:** M4/PBPP and BENCH-001 through
BENCH-004 are complete. M1.3 remains partial behind Phase 12's grounded-reader
and positive graph/PPR gates; Phases 13 through 16 own the remaining benchmark,
reproduction, capability-column, and leaderboard work. External board seating,
third-party reproduction, and approval of any public number remain human-only.
The physical-8-GiB full-capability and hardware-invariant product-quality path
is governed by
`docs/superpowers/specs/2026-07-13-8gb-full-capability-unblock-design.md`.
`.planning/STATE.md`, `.planning/ROADMAP.md`, and `.planning/REQUIREMENTS.md`
are the authoritative live trackers.

---

## 0. How to use this document (executing agent, read first)

Execution spec, not prose. Two parts: **Part I** benchmarks Mnemosyne credibly; **Part II** builds the neutral leaderboard. Part I's harness is reused as Part II's engine. Every task has a stable ID (`M1.2`, `L0.1`), a **DoD**, and required **artifacts**.

**Hard guardrails (violating any = stop and escalate):**

1. **PBPP governs every public number** (§2). No public claim without the full artifact bundle (§M2) and reproduction by construction — one documented command regenerates the number from its pinned bundle. Independent third-party reproduction strengthens a claim and is recorded when it occurs, but does not gate publication (§M3, revised v0.2.0).
2. **Retrieval-recall and LLM-judged-QA are never blended.** Separate columns, always. Disclose judge model + prompt. (This is the single most common field failure — MemPalace, the mem0↔Zep dispute.)
3. **Never tune on a held-out/test split** — our own system included. Contamination discipline (§M1, §L1) applies to us exactly as to submitters.
4. **No self-defined benchmark is ever a headline claim** (the gbrain "BrainBench" anti-pattern). Mnemosyne's private suite (0.977 / 0.983 / ECE 0.0063 / poison 1.0 / 149.5 ms) stays internal QA.
5. **Neutrality is structural, not asserted** (§L0). If we operate the leaderboard *and* compete, the firewall in §L0 is mandatory, or the board is not credible.

**Ground-truth references (source of truth over this doc if they conflict):**
`docs/research/AI-Memory-Systems-Market-Research-2026.md` (the competitive + benchmark landscape and why LoCoMo is contested), `docs/blueprint/Mnemosyne-Performance-and-Refactoring-Blueprint.md` (§9.2.7 slates LongMemEval/BEAM wiring and carries the current benchmark-posture/honesty rule), `eval/README.md`, `eval/provider_bakeoff/README.md`.

**DoD template:** *Harness/site code merged + artifacts written to the named path + a one-paragraph result note in `leaderboard/reports/` + public data-repo updated (Part II) + independent reproduction on file (headline numbers).*

---

## 1. Objectives & success criteria (measurable)

### Part I — Benchmark Mnemosyne credibly
| # | Win condition | Definition |
|---|---|---|
| M-i | Public benchmarks wired | LongMemEval (retrieval), HippoRAG multi-hop, MemoryAgentBench, BEAM runnable in `eval/public/` with artifact bundles |
| M-ii | Metric families separated | Every result reports deterministic-retrieval and LLM-judged-QA in distinct columns |
| M-iii | Reproducible | Every headline number reproduced by an independent third party from the bundle alone |
| M-iv | Honest posture | Charter upgraded to PBPP; private suite never headlined |

### Part II — The neutral leaderboard
| # | Win condition | Definition |
|---|---|---|
| L-i | It exists & is trusted | Public site + open harness + methods paper + openly-licensed results dump |
| L-ii | Structurally neutral | Operator runs every system under one harness; hard firewall on our own entry (§L0) |
| L-iii | Resists gaming | Hidden/rotated split, contamination controls, signed build==public attestation, honest LLM-judge reporting |
| L-iv | Becomes the default | Multi-track (conversational / agentic / multi-session); ≥8 systems live; academic co-sign |

### Explicit non-goals / anti-patterns
- No headlining **LoCoMo** or **DMR/MSC** (contested / saturated — market research §6).
- No presenting **recall@k as QA accuracy** (the MemPalace failure).
- No `top_k = entire-candidate-pool` "100%" retrieval theater.
- No "neutral" board that quietly advantages our own entry (the LMArena "Leaderboard Illusion").

---

## 2. Strategic framing — the two hard problems, resolved

**Problem 1 — the honesty-charter tension.** The perf blueprint §9.2.7 and
`eval/provider_bakeoff/README.md` originally forbade citing public benchmarks
in headline claims while none had been run under our discipline. M4 replaced
that blanket prohibition on 2026-07-10 with the stricter **Public-Benchmark
Publication Protocol (PBPP)**:

> **PBPP.** A public number may be published only if (a) produced by the pinned public harness in `eval/public/`, (b) the full artifact bundle (§M2) is released simultaneously, (c) retrieval-recall and LLM-judged-QA are reported in separate columns with judge model + prompt disclosed, (d) the private golden suite is never conflated with it, and (e) an independent third party reproduces it from the bundle. Private-suite numbers remain internal QA and are never headline public claims.

This turns honesty into the moat: any future published number must be among the
most reproducible in a field full of contested vendor claims. M4's two policy
surfaces and contributor regression gate are complete; no publication is
authorized by that source-owned completion alone.

**Problem 2 — the neutrality paradox.** We cannot be referee and champion on trust alone; vendor-run-where-they-win boards get dismissed (OmniMemEval, omegamax, the LMArena "Illusion"). Resolution (§L0): the leaderboard runs under **independent governance with a hard firewall**; the operator **runs every system itself under one identical harness** (killing the "you misconfigured us" defense that defined the mem0↔Zep dispute); Mnemosyne is entered and scored **by the same rules as everyone else**; all raw artifacts are public. We win by having the best *reproducible* numbers on neutral turf — not by controlling the scoreboard.

---

# PART I — Benchmark Mnemosyne credibly

### M1 — Wire public benchmarks into `eval/public/` (deterministic-first) — *Wave E kickoff*
Blueprint §9.2.7 slates this. Build as a new isolated tree so the private suite stays clean; drive only the public `mneme` CLI (same rule as `eval/run_eval.py`).

- **M1.1 Harness scaffold.** `eval/public/` runner: pins each benchmark to a commit, emits the §M2 bundle. DoD: `mneme eval-public --suite X` runs end-to-end and writes traces.
- **M1.2 LongMemEval — retrieval-recall track first.** Deterministic Recall@k / nDCG using the dataset's session/turn gold labels; **no LLM in scoring.** DoD: R@5 with Wilson CI + per-question retrieval traces. (Targets Plan A S-i.)
- **M1.3 HippoRAG multi-hop suite.** MuSiQue / 2WikiMultiHopQA / HotpotQA — deterministic retrieval Recall@2/@5 and scoring, plus separately disclosed-reader EM/F1 columns once Phase 12 supplies predictions. The current retrieval adapter measures the graph/PPR channel, but positive provenance-linked PPR effect remains an explicit gate. DoD: retrieval table vs published HippoRAG 2 baselines, reader columns, and positive-PPR evidence. (Plan A S-ii.)
- **M1.4 MemoryAgentBench adapter (upstream PR).** Mostly deterministic (SubEM/exact-match); contribute a Mnemosyne adapter upstream — the closest thing to an "official submission." DoD: PR open + local results. (Exercises conflict-resolution / belief-revision.)
- **M1.5 BEAM (prestige, LLM-judged).** Disclosed reader model; publish as "Mnemosyne + <reader>." DoD: BEAM-1M result + full config disclosure. (Plan A S-iii.)
- **M1.6 Scheduled CI job.** Runs deterministic public suites on a cadence; regression alerts only; never tune-to-test.

**Status (2026-07-13):** M1.1 and M1.2 source-owned DoDs are complete. M1.3's
deterministic retrieval adapters are wired, while disclosed-reader columns and
positive provenance-linked graph/PPR effect remain open behind Phase 12. The
aggregate M1 checkbox stays open, and none of this source-owned progress
authorizes publication without M2 plus genuine human-owned M3 reproduction.

### M2 — Reproducibility artifact bundle (the PBPP standard)
Every public result ships: pinned harness commit + `uv`/`pip` runner; per-question traces (**what was stored, what was retrieved, final answer**); disclosed judge model + prompt + all configs; system build fingerprint (we already emit `sha256:…` release fingerprints); Wilson/bootstrap CIs; one-command reproduce script. **DoD:** a clean-room agent run reproduces the number from the bundle alone as an internal bundle-readiness check. This does not satisfy M3's external independence requirement.

### M3 — Third-party reproduction
**Agent scope:** prepare the immutable bundle, reproduction instructions,
acceptance rubric, intake checklist, and report template. **Human scope:** select
and commission a genuinely independent external party, receive its result, and
decide whether it satisfies PBPP. **DoD:** a signed external reproduction note
supplied through the human-owned process is recorded in `leaderboard/reports/`
before any public claim. An agent may not commission, impersonate, or approve
the reproducer.

### M4 — Charter → PBPP
Update blueprint `§9.2.7` and the provider-bakeoff README to reference PBPP (§2). **DoD:** docs updated; CI lint points contributors to PBPP.

**Status (2026-07-10): complete.** Both policy surfaces now adopt PBPP §2 while preserving private-suite provider-promotion rules, and `tests/test_benchmark_publication_policy.py` is the CI regression gate. Result note: `eval/reports/m4-pbpp.md`.

### Benchmark slate (deterministic-first)
| Tier | Benchmark | Track | Scoring | Why |
|---|---|---|---|---|
| Primary | **LongMemEval** (retrieval-recall) | conversational | Deterministic | Publishable recall@k; the flag everyone plants |
| Primary | **HippoRAG suite** (MuSiQue/2Wiki/HotpotQA) | multi-hop | Deterministic retrieval R@k; disclosed-reader EM/F1 separate | Measures the PPR channel; positive PPR effect remains gated |
| Strong | **MemoryAgentBench** | agentic/conflict | Mostly deterministic | Upstream adapter = closest to an "official" submission |
| Prestige | **BEAM** (1M/10M tok) | long-horizon | LLM-judged (disclosed reader) | Un-saturated; differentiating at scale |
| Utility | **STATE-Bench** (Microsoft) | enterprise task success | Deterministic task-completion | Shows memory improves real tasks |
| Internal-only | private v2 suite, LongMemEval-QA | — | private / LLM-judged | QA + regression signal; **never** a headline claim |
| Avoid headlining | LoCoMo, DMR/MSC | — | contested / saturated | Run silently at most; never lead with them |

**Part I exit gate:** M-i…M-iv met; PBPP in force; third-party reproduction on file.

---

### M5 — Memory-native benchmark (MNB) — *added v0.2.0*
Existing public suites measure QA over long context. They do not score provenance integrity, calibrated abstention (they **penalise** it), bitemporal correctness, belief revision, deletion compliance, or write-path safety — the properties a memory compiler exists to provide. Spec: [`docs/benchmark/MEMORY-NATIVE-BENCHMARK.md`](benchmark/MEMORY-NATIVE-BENCHMARK.md).

Nine dimensions D1–D9, each mapped to an existing CAP requirement so nothing is invented to flatter. Fully open-sourced under the repo licence: spec, generators, graders, fixtures, adapters, harness. Binding anti-self-dealing rules — spec frozen before any system runs, never headlined alone, adapter parity or "not measured", a standing published record of where Mnemosyne loses, held-out split with pre-published digest, open dispute channel, no tuning against MNB without disclosure.

**DoD:** spec frozen and pre-registered; ≥1 dimension implemented with a passing programmatic grader; Mnemosyne and ≥1 external system measured on it; the "where Mnemosyne loses" section is non-empty.

# PART II — The neutral Memory Leaderboard

Working name: **OpenMemBench** (final naming is a branding decision; recommendation: a neutral, non-Mnemosyne-branded identity to preserve independence).

### L0 — Verifiable neutrality FIRST (the credibility moat — build before any code)
> **Revised v0.2.0.** The original L0 required a multi-institution board, legal steward, durable funding, external ratification, and a multi-owner archive. A solo maintainer cannot produce those by writing software, so Phase 16 could never open. Credibility now rests on **mechanical verifiability** — see [`docs/governance/CREDIBILITY-MODEL.md`](governance/CREDIBILITY-MODEL.md). The disclosure standard is unchanged; only *who vouches* changed.
- **L0.1 Pre-registration.** Before any scored run, commit a signed `preregistration.json` (harness commit, adapter versions, dataset digests, metric definitions, held-out split digest, stopping rule). Off-registration scores are ineligible and labelled so.
- **L0.2 One-harness rule.** Operator runs **every** system itself under one identical harness (the reused `eval/public/` core); vendor-submitted numbers are never accepted as-is. Unchanged from v0.1.0 and non-waivable.
- **L0.3 Append-only signed run ledger.** Every run — including failed, aborted, and discarded — hash-chained and Ed25519-signed, reusing the v1.0 Tier-B evidence substrate. Never deleted, only superseded with a stated reason. This is what makes cherry-picking third-party-detectable, which is the property the board was there to provide.
- **L0.4 Survivability by replication.** Openly-licensed results dump in git + DOI snapshot + public archive mirror, permissive licence, explicit "fork this" policy. Durability through replication rather than co-ownership.
- **L0.5 Methods write-up.** Public preprint plus an open, logged review channel. Not gated on peer-review acceptance.
- **L0.6 Honest label.** Outputs are **open, operator-run, fully auditable** — never "neutral" or "independent" while the operator competes and no board is seated.

### L1 — Benchmark methodology & harness (requirements checklist)
Each item maps to a proven precedent (full source map in Appendix B):
- **L1.a Multi-track, GLUE-style:** conversational · agentic · multi-session, shared metric stack.
- **L1.b Separate metric families:** deterministic retrieval (recall@k, EM, programmatic assertions) vs LLM-judged QA — never blended.
- **L1.c Contamination controls:** machine-validated training-data disclosure (MTEB `training_datasets`); surface a **zero-shot overlap** score *without hiding honest disclosers*; fresh-vs-circulated probes (SWE-bench-Illusion method).
- **L1.d Hidden/held-out + rotation:** publish train/dev, keep a **private scoring split** (ARC-AGI); public/private split with periodic reveal (Kaggle); scheduled task rotation + human baseline per track (GLUE saturation lesson).
- **L1.e Anti-gaming:** signed **attestation that evaluated build == public release** (LMArena's Llama-4 fix); submission throttling (SuperGLUE 2/day); disclose *all* variants tested; public retirement list.
- **L1.f Keep the judge honest:** publish the judge's acceptance rate on intentionally-wrong-but-topical answers (beat LoCoMo's 62.8%); multi-judge averaging; rotating human adjudication; prefer deterministic grading where possible.
- **L1.g Systems-fair reporting:** efficiency (latency + cost/query) first-class, budget-normalized; CIs + rank ranges with overlapping-CI systems treated as **ties**; set-independent aggregation (Borda, not mean-win-rate).
- **L1.h Reproducibility:** pinned harness commit, full per-question traces public, open-source-to-rank, and **reproducible by construction** — one documented command regenerates any published number from its bundle. Third-party reproduction is recorded as strengthening evidence when it happens, never as a blocking gate.

### L2 — Website architecture & build (greenfield `web/` + `leaderboard/`)
- **Stack (recommendation):** static-first for durability + trust — **Astro or Next.js (static export)** front-end; results stored as **flat, versioned JSON/Parquet in a public git repo** (not a hidden DB) so every number is auditable and URLs are permanent; light charting lib; a **per-question trace browser** (HELM's "browse all predictions" pattern). CDN-hosted; mirrored data dump.
- **Data model:** `system → track → benchmark_version → run(commit, build_fingerprint, config, judge) → per_question_traces → metrics(with CIs)`.
- **Submission flow:** reviewed **PR with provenance link** (MTEB model); CI validates schema + build attestation; organizer runs the eval; results + traces published.
- **DoD:** site renders the leaderboard from the public data repo; ≥1 system fully browsable end-to-end (traces included).

### L3 — Content / explainer layer ("explain memory to everyone")
Plain-language explainers of each major system's architecture (reuse `docs/research/AI-Memory-Systems-Market-Research-2026.md`), the **recall-vs-QA** distinction front-and-center, and a transparent methodology page. **DoD:** explainer pages published; reviewed for accuracy against primary sources.

### L4 — Launch & community
Seed by running **all major systems** (mem0, Zep/Graphiti, Letta, Cognee, MemOS, supermemory, HippoRAG, + Mnemosyne) under the one harness; publish the methods paper; open submissions + a public audit/dispute channel; **release raw head-to-head data** (LMArena's single most trust-restoring act). **DoD (revised v0.2.0):** public launch with every system for which a fair adapter exists, each absence disclosed with its reason, and a reproducible public methods write-up. Coverage is reported honestly rather than gated on a fixed count.

**Part II exit gate (revised v0.2.0):** Register A of [`BOARD-STATUS.md`](governance/BOARD-STATUS.md) satisfied with verifiable evidence; the open stack published; a populated adversarial self-report; methods write-up public; Mnemosyne entered under identical rules and labelled as the operator entry. System coverage is reported honestly rather than gated on a fixed count — every absence is disclosed with its reason. Board seating is an optional upgrade that would permit the *neutral* label.

---

## 5. Cross-cutting: anti-gaming, verification, risks

**Failure modes to design against (real 2026 episodes):**
- MemPalace: recall@k reported as QA; `top_k = whole pool`; hand-patching dev questions. → Enforced by L1.b, L1.d, per-question trace publication.
- gbrain: self-defined "BrainBench" headline. → Forbidden by guardrail #4 / PBPP.
- LMArena "Leaderboard Illusion": operator/unequal access. → Neutralized by L0.1–L0.2.
- LoCoMo: 6.4% wrong answer key + lenient judge. → We don't headline LoCoMo; judge honesty published (L1.f).

**Verification:** every headline public number reproduced by an independent party before publication (M3); every leaderboard result reproducible from its bundle; a standing "red-team the number" review before any external claim.

**Risk register:**
| Risk | Mitigation |
|---|---|
| Neutrality perception (we compete + operate) | Independent board, one-harness rule, no special access, raw-data release (§L0) |
| Honesty-charter breach | PBPP (§2); private suite never headlined |
| Benchmark saturation / contamination | Hidden split + rotation + fresh scenarios (L1.d) |
| Compute cost of running all systems | Budget realistically; curated reference set + community queue (Open-LLM-Leaderboard lesson) |
| Over-claiming | Recall vs QA separated; CIs + ties; "provisional" until reproduced |
| Depends on Plan A capabilities not ready | Part I can benchmark today's system; publish deterministic strengths first, add QA as S1 lands |

---

## 6. Timeline, roles, dependency map

**Sequencing (critical path bold):**
1. **M4 charter → PBPP** (unblocks all publication) — days.
2. **M1 public harness** (Wave E kickoff) ∥ **L0 governance charter** — weeks 1–3.
3. **M2/M3 bundle + third-party repro** ∥ **L1 methodology + L2 site scaffold** — weeks 2–8.
4. L3 explainers ∥ finalize Part I results — weeks 4–10.
5. **L4 launch** (seed ≥8 systems, methods paper) — weeks 8–14.

**Dependencies:** M4 blocks any publication; M1's harness **is** L1's engine (shared eval core — serialize writes); L0 blocks L4; Part I depends on **Plan A** capabilities for the QA numbers. Deterministic tracks may be benchmarked before reader tracks, but publication still requires the complete PBPP bundle and genuine independent reproduction.

**Roles:** *eval-eng agent* (M1–M2), *web agent* (L2–L3), *governance/human operator* (L0 board, M3 third-party repro), *research/writing* (L0.4 methods paper). Independent workstreams run as parallel sub-agents; serialize shared-eval-core writes.

### Definition-of-Done checklist (Plan B)
- [x] Charter updated to PBPP; provider-bakeoff README references it (M4).
- [ ] `eval/public/` harness live; LongMemEval-recall, HippoRAG multi-hop, MemoryAgentBench adapter, BEAM runnable with bundles (M1).
- [ ] Reproducibility bundle standard implemented; agent-reproduces from bundle (M2).
- [ ] Independent third-party reproduction of headline numbers on file (M3).
- [ ] Governance board seated; COI + firewall policy public (L0).
- [ ] Methodology + anti-gaming + contamination controls implemented (L1).
- [ ] Leaderboard site live from a public, versioned results repo; trace browser working (L2).
- [ ] Explainer/education layer published (L3).
- [ ] Public launch: ≥8 systems, methods paper, raw-data dump openly licensed (L4).
- [ ] Mnemosyne entered under identical rules; no special access.

---

## Appendix A — Dependency on Plan A
Plan A (*The Memory System*) produces the capabilities this plan measures: elite retrieval, multi-hop synthesis (S1, the QA-number driver), security-under-attack and calibration (S3), and scale numbers (S4). Deterministic-retrieval results can be benchmarked on today's system, but publication remains blocked on M2/M3, the complete PBPP bundle, genuine independent reproduction, and human approval; QA numbers improve as Plan A S1 lands.

## Appendix B — Leaderboard-credibility source map
MTEB (arXiv 2506.21182; docs.mteb.org), HELM (2211.09110; crfm.stanford.edu), Chatbot Arena / LMArena (2403.04132) + Leaderboard Illusion (2504.20879) + Arena response (arena.ai/blog/our-response), GLUE/SuperGLUE (1804.07461 / 1905.00537), SWE-bench Verified (openai.com/index/introducing-swe-bench-verified) + SWE-bench Illusion (2506.12286), ARC-AGI (arcprize.org), Kaggle (kaggle.com/docs/competitions), Papers-with-Code shutdown (github.com/paperswithcode/paperswithcode-data/issues/116), memory-leaderboard call (2603.07670), in-repo landscape (`docs/research/AI-Memory-Systems-Market-Research-2026.md`).

*This plan changes posture deliberately (public benchmarks + a public leaderboard) but only through PBPP, which is stricter than the field norm. Mnemosyne competes on the leaderboard under the same rules as every other system.*
