# AI Memory Systems — Market Research Report

**Scope:** Memory layers for LLM agents and assistants (persistent, cross-session memory). Covers open-source and closed/hosted systems, the benchmark ecosystem, per-system SWOT, and market context.
**Date:** July 2026
**Author:** Research synthesis, verified against primary sources (GitHub, arXiv, official docs, tech press).

---

## 0. How to read this report (the one caveat that governs everything)

Two things make this market unusually hard to assess objectively. Every reader — and every buyer — needs both up front.

**1. Almost every benchmark number is vendor-produced and vendor-contested.** mem0, Zep, MemOS, supermemory, and others each publish results showing themselves as SOTA, run on their own harnesses. None are independently audited. Treat all "we beat X" claims as marketing until reproduced.

**2. Two incompatible metrics are routinely presented as if comparable:**

| Metric family | What it measures | Scoring | Example |
|---|---|---|---|
| **Retrieval recall@k / nDCG** | Did the right memory come back? | **Deterministic** (no LLM in the loop) | HippoRAG on MuSiQue/2Wiki |
| **LLM-judged QA accuracy** | Did an answering model produce the right answer? | **An LLM grades correctness** (non-standard prompts) | mem0/Zep on LoCoMo |

A "97% recall@5" and a "92% QA accuracy" are **not the same axis** and cannot be ranked against each other. This conflation is the single most common way memory rankings mislead — and it is exactly what drove the field's biggest disputes (Section 6).

---

## 1. Executive summary

- **The category went from niche to hot in 18 months.** "Memory" replaced "reasoning/hallucination" as the headline agent bottleneck in late 2025 as enterprises pushed agents from pilot to production. Funding followed: mem0 $24M, Letta $10M, Cognee $7.5M, supermemory ~$2.6M, and — the standout — **Engram at $98M / $600M valuation (June 2026)**.
- **Open-source leaders by traction:** mem0 (~50–60k★), supermemory (~28k★), Zep/Graphiti (~26k★), Letta/MemGPT (~23k★), Cognee (~17k★), Memori (~15k★), MemOS (~10k★). HippoRAG (~3.8k★) leads on academic rigor.
- **Every major assistant now ships memory:** OpenAI (ChatGPT "Dreaming"), Anthropic (Claude Memory), Google (Gemini Personal Context), Microsoft (Copilot Memory). This squeezes independent vendors from above (bundled consumer memory) and sideways (Cloudflare's edge memory-as-a-service, April 2026).
- **The benchmarks are contested and near-saturated.** LoCoMo — the most-cited memory benchmark — was independently audited to have a **6.4% wrong answer key**, an LLM judge that accepts ~63% of intentionally wrong answers, and corpora small enough to fit in a context window. LongMemEval is the current de-facto standard but is also LLM-judged.
- **There is no neutral leaderboard.** No GLUE/Papers-with-Code-style submission hub for memory exists (Papers with Code was shut down by Meta in July 2025). Every "leaderboard" today is single-benchmark academic or vendor-run. A March 2026 survey explicitly calls for the field to build one — confirming the gap.
- **Security is an unfilled column.** Memory-poisoning attacks (MINJA, AgentPoison) report **76–98% success rates**, yet no memory vendor publishes robustness numbers. Whoever does gains a near-unique credibility claim.
- **Caution flag for anyone doing competitive analysis:** two systems that circulated as "top-tier rivals" — **gbrain** and **MemPalace** — are April-2026 viral repos, not established systems. MemPalace's benchmark claims were audited and partly retracted (Section 8). Do not build strategy against them as if they were mem0-class incumbents.

---

## 2. Market & funding landscape

| Company | Stage / total | Valuation | Date | Lead(s) | Notable backers | Confidence |
|---|---|---|---|---|---|---|
| **Engram** | $98M launch | **$600M** | Jun 2026 | General Catalyst, Kleiner Perkins, Sequoia | Factory, Amplify, Neo; angels **Karpathy**, Pieter Abbeel, Assaf Rappaport (Wiz). Customers: Microsoft, Notion, Harvey | High |
| **mem0** | $24M (Seed + Series A) | n/d | Oct 2025 | Kindred (seed); Basis Set (A) | Peak XV, GitHub Fund, YC; angels Dharmesh Shah, Olivier Pomel, Scott Belsky | High |
| **Cognee** | €7.5M seed | n/d | Feb 2026 | Pebblebed | 42CAP, Vermilion; DeepMind/n8n angels | High |
| **Letta** (MemGPT) | $10M seed | **$70M** post | Sep 2024 | Felicis | Founders Fund, YC; angels Jeff Dean, Clem Delangue, Ion Stoica | High |
| **Memories.ai** (visual) | $16M seed (total) | n/d | Jul 2025 | Susa Ventures | Samsung Next, Seedcamp, Fusion Fund | High |
| **supermemory** | ~$2.6M seed | n/d | Oct 2025 | Susa, Browder Capital, SF1.vc | Jeff Dean, Dane Knecht, Logan Kilpatrick | High (note: some press rounds to "~$3M") |
| **Zep AI** | ~$0.5–2.3M seed (YC W24) | n/d | 2024 | Y Combinator | Aggregator data only | Medium |

**Market sizing:** analyst estimates put "agentic AI orchestration + memory systems" at ~$6.3B (2025) → ~$28B (2030), ~35% CAGR (Mordor Intelligence). Treat as directional, not hard data.

**Structural read:** Engram's raise is an order of magnitude above every prior round and signals the category "graduating" from seed to mega-round. Simultaneously, hyperscaler bundling (OpenAI/Anthropic/Google/Microsoft) and infra entrants (Cloudflare) are commoditizing basic memory — pressuring independents to differentiate on graph/temporal reasoning, token efficiency, security, or vertical depth.

---

## 3. Open-source systems

Star counts are approximate, as of ~mid-2026, and should be treated as order-of-magnitude (fast-moving; some GitHub star data in circulation is inflated — see Section 8).

| System (repo) | Architecture | License | ★ | Lang | Benchmark posture |
|---|---|---|---|---|---|
| **mem0** (`mem0ai/mem0`) | LLM extraction pipeline → vector store + optional graph memory | Apache-2.0 | ~50–60k | Python | Self-reported LoCoMo/LongMemEval QA-acc; +26% vs OpenAI memory claim |
| **Graphiti / Zep** (`getzep/graphiti`) | **Bi-temporal knowledge graph** + hybrid semantic/BM25/graph search | Apache-2.0 | ~26k | Python | Self-reported LoCoMo ~75–80%, LongMemEval ~90% (contested) |
| **Letta / MemGPT** (`letta-ai/letta`) | **OS-style tiered memory** (core/recall/archival), self-editing context | Apache-2.0 | ~23k | Python | DMR 93.4%; published a filesystem-baseline critique of LoCoMo |
| **Cognee** (`topoteretes/cognee`) | **ECL pipeline** (Extract-Cognify-Load) → knowledge graph + vector | Apache-2.0 | ~17k | Python | Marketing-grade eval only; 70+ production users cited |
| **Memori** (`MemoriLabs/Memori`) | **SQL-native** relational memory + entity/fact extraction | Apache-2.0 (unverified SPDX) | ~15k | Python | Self-reported; paper exists but unverified |
| **MemOS** (`MemTensor/MemOS`) | "Memory OS": MemCube over plaintext / KV-cache / parameter memory | Apache-2.0 | ~10k | Python + TS | Self-reported LoCoMo 92.3, LongMemEval 93.4 (vendor-run) |
| **supermemory** (`supermemoryai/supermemory`) | Memory API: hybrid vector+keyword, ontology-aware graph, connectors | MIT | ~28k | TypeScript | Self-reported LongMemEval ~85%; claims #1 LoCoMo/ConvoMem |
| **HippoRAG** (`OSU-NLP-Group/HippoRAG`) | **Knowledge graph (OpenIE) + Personalized PageRank** retrieval | MIT | ~3.8k | Python | **Deterministic** recall@k + EM/F1 on MuSiQue/2Wiki/HotpotQA (NeurIPS'24) |
| **A-Mem** (`agiresearch/A-mem`) | **Zettelkasten-style** self-linking, evolving notes | MIT | ~1k | Python | LoCoMo (LLM-judged); NeurIPS 2025 |
| **LangMem** (`langchain-ai/langmem`) | SDK: extraction + storage over any LangGraph store (not a DB) | MIT | ~1.5k | Python | No independent benchmark |
| **Mastra memory** (`mastra-ai/mastra`) | Working memory + semantic recall + history (TS agent framework) | Apache-2.0 (+ EE) | ~26k (whole framework) | TypeScript | Self-reported LongMemEval ~94.9% |
| **memvid** (`memvid/memvid`) | Novelty: encodes memory into **video files** for compression | — | ~15k | Python | Niche; compression-focused |

**Architectural camps:**
- **Extraction + vector** (mem0, supermemory, LangMem): simplest, most integrated, weakest at temporal/relational reasoning.
- **Knowledge graph** (Graphiti/Zep, Cognee, HippoRAG): stronger multi-hop and contradiction handling; heavier infra (Neo4j/graph DB).
- **OS-style hierarchical** (Letta/MemGPT, MemOS): explicit memory tiers + self-management; the conceptual origin of the space (MemGPT, 2023).
- **SQL-native** (Memori): bets on relational stores enterprises already run.

---

## 4. Closed-source / hosted platform memory

### Big-platform consumer/enterprise memory

| Provider | Mechanism | Status (mid-2026) | Notes |
|---|---|---|---|
| **OpenAI — ChatGPT Memory** | Saved memories + reference-all-history + background synthesis ("Dreaming") | **Dreaming V3** (Jun 2026): compute-efficient rewrite; auto-updates stale facts | Internal evals only (time-sensitive accuracy 9.4%→75.1%) |
| **Anthropic — Claude Memory** | Editable, human-readable user summary; **project-scoped**; refreshes ~24h | Free tier opt-in since Mar 2026; Incognito mode | Transparent/editable-file approach is a differentiator |
| **Google — Gemini Personal Context** | Saved Info + auto-learned "Personal Context"; compressed user profile | Beta rolling out globally (ex-EEA/UK/CH); Temporary Chats | Bundled in Gemini tiers |
| **Microsoft — Copilot Memory** | Durable preferences, saved on clear intent; stored in **Exchange mailbox** | GA Jul 2025, on by default | Inherits mailbox security/compliance |

### Memory-as-a-service / infra

| Provider | What they sell | Notes |
|---|---|---|
| **Zep Cloud** | Managed temporal-KG memory ("Context Block"); ~$25/mo Flex entry | Community Edition deprecated; self-host = run Graphiti + your DB |
| **mem0 Platform** | Hosted memory API ("3 lines of code"); Free→Enterprise tiers | AWS selected mem0 as a memory provider; 21+ integrations |
| **Letta Cloud** | Hosted stateful agents (REST); Free→Team | On AWS Marketplace |
| **supermemory** | Universal memory API; Free→Scale $399/mo; SOC2/HIPAA on Enterprise | Consumer app + SuperRAG filesystem |
| **Cloudflare Agent Memory** | Edge-native managed memory (Workers + Durable Objects + Vectorize) | Private beta Apr 2026; hyperscaler entrant |
| **Engram** | Trained per-org "memory models"; ~100x fewer tokens claim | Closed; $98M; customers Microsoft/Notion/Harvey |
| **Pinecone / vector DBs** | Substrate memory layers run *on top of* — not a memory product | No lifecycle/curation/contradiction handling by themselves |

---

## 5. Benchmark ecosystem

| Benchmark | Creator / Venue | Measures | Scoring | License | Status / notes |
|---|---|---|---|---|---|
| **LoCoMo** | Snap Research, ACL 2024 (arXiv 2402.17753) | Very-long-term conversational memory; **only 10 convos**, ~9K tokens | Originally F1/BLEU/ROUGE + recall@k; **now de-facto LLM-judged** | CC BY-NC 4.0 | Most-cited & most-criticized; **6.4% answer-key error**; saturated ~92–95% |
| **LongMemEval** | Tencent AI Lab / UCLA, ICLR 2025 (2410.10813) | 5 abilities incl. temporal, knowledge-update, abstention; ~40-session, ~115K tokens | **LLM-judged QA** (GPT-4o) + secondary recall@k | MIT | De-facto vendor standard; "cleaned" v2 released 2025 |
| **DMR / MSC** | MemGPT (2310.08560) / Meta (ACL 2022) | Single-fact recall / persona consistency across sessions | LLM-judged / perplexity+F1 | MIT / Apache | **Legacy, saturated** — too easy for 2026 |
| **BEAM** | U. Alberta + UMass, ICLR 2026 (2510.27246) | 10 abilities incl. contradiction, ordering; up to **10M tokens**, 2,000 Qs | LLM-judged | MIT | Designed to be un-saturable; not yet saturated |
| **MemoryAgentBench** | UCSD / HUST, ICLR 2026 (2507.05257) | 4 competencies incl. conflict resolution; "inject once, query many" | **Mostly deterministic** (SubEM/exact-match) + judged F1 subset | MIT | Strong methodology; ships adapters for Mem0/Cognee/Letta/HippoRAG |
| **HotpotQA / MuSiQue / 2Wiki** (via HippoRAG) | EMNLP'18 / TACL'22 / COLING'20; harness NeurIPS'24 | Multi-hop retrieval + QA | **Fully deterministic** (Recall@2/5, EM/F1) | CC/Apache/MIT | Cleanest deterministic option for retrieval claims |
| **ConvoMem** | Salesforce AI, Nov 2025 (2511.10523) | 75K QA pairs; facts, abstention, prefs, temporal | Mixed (MC + LLM-judged) | verify on HF | Thesis: first ~150 convos don't need RAG (full-context wins) |
| **THUIR MemoryBench** | Tsinghua THUIR, Oct 2025 (2510.17281) | Memory + continual learning; 11 datasets | **ELO via LLM-simulated feedback** | academic | Public leaderboard; closest to neutral (but single-team) |
| **OmniMemEval** | MemTensor (MemOS team) | 14 commercial products, 10 datasets | LLM-judged | vendor | **Vendor-run** — MemOS "wins"; not neutral |
| **AMA-Bench** | UCSD, ICML 2026 (2602.22769) | Long-horizon memory over **agent trajectories** (not dialogue) | LLM-judged | open | Finding: memory systems barely beat full-context; causality is hard |
| **STATE-Bench** | Microsoft, May 2026 | Whether memory improves enterprise task success | **Deterministic task-completion** | MIT | Measures utility, not retrieval |

**Adjacent/newer:** LongMemEval-V2 (web-agent memory, 115M tokens), PerLTQA, MemBench, MemoryArena, HaluMem (memory hallucination), MEMTRACK.

**Recommended slate for a credible, publishable claim** (deterministic-first, since it survives scrutiny):
1. **LongMemEval** (retrieval-recall track) — the flag everyone plants; MIT; publishable deterministically.
2. **HippoRAG multi-hop suite** (MuSiQue/2Wiki/HotpotQA) — fully deterministic recall@k + EM/F1.
3. **MemoryAgentBench** — mostly deterministic; contribute an upstream adapter (the closest thing to an "official submission").
4. **BEAM** — prestige, 10M-token scale; publish as "system + disclosed reader model."
5. **Novel columns nobody fills:** memory-poisoning attack-success rate (MINJA/AgentPoison) and calibration/ECE curves.
Avoid headlining **LoCoMo** and **DMR/MSC** — both are contested/saturated and will get a 2026 claim dismissed.

---

## 6. The credibility problem

### The mem0 ↔ Zep dispute (fully documented, partly resolved)
- **mem0's paper** (arXiv 2504.19413, ECAI 2025): claimed +26% LLM-judge over OpenAI memory (66.9% vs 52.9%), 91% lower p95 latency, ~90% fewer tokens; reported Zep at 65.99%.
- **Zep's rebuttal** (blog, May 2025): original claim **84%**; alleged mem0 misconfigured Zep (wrong user model, timestamp handling, sequential searches).
- **mem0's counter** (getzep/zep-papers issue #5): argued Zep wrongly included the excluded adversarial category, inflating by ~25 pts → **58.44%**.
- **Resolution:** Zep's CEO **conceded the arithmetic error**, corrected 84% → **75.14% ±0.17**, but stood by the methodology critique. The two never converged. Pick your preferred reality.
- **Letta's intervention:** a plain filesystem + `grep` on GPT-4o-mini scored **74% on LoCoMo** — above mem0's best graph variant (68.5%) — suggesting the benchmark rewards context management, not memory design.

### LoCoMo is contested-to-discredited
- **6.4% of the answer key is wrong** (99/1,540 questions) — Penfield Labs audit. Theoretical ceiling ~93.6%.
- The standard GPT-4o-mini judge **accepted 62.8% of intentionally wrong-but-topical answers.**
- Corpora (16–26K tokens) fit inside modern context windows → "measures context-window management, not long-term memory."
- Reproducibility failures abound: one system claiming 92.3% on LoCoMo was reproduced at 38.4% by a third party — a 54-point spread on the same benchmark, same year.

### No neutral leaderboard exists
- **Papers with Code was shut down by Meta on ~July 24, 2025** (9,327 leaderboards lost), removing the field's main neutral host exactly as memory benchmarking heated up.
- A **March 2026 survey** (arXiv 2603.07670) explicitly calls for a "GLUE-style shared leaderboard for agent memory … with standardized metrics." The call-to-action confirms the vacuum.
- Every current "leaderboard" is single-benchmark academic (THUIR MemoryBench, MemoryAgentBench) or vendor-run (OmniMemEval/MemTensor, omegamax, supermemory's harness, Vectorize's "neutral" AMB — which sells the Hindsight product that tops it).

---

## 7. Security & adversarial memory (the empty column)

| Attack | Venue | Result |
|---|---|---|
| **MINJA** (query-only memory injection) | arXiv 2503.03704 (2025) | 98.2% injection success, 76.8% avg attack success across GPT-4o-mini/Gemini/Llama |
| **AgentPoison** | NeurIPS 2024 (2407.12784) | >80% attack success at <0.1% poison rate, no retraining |
| **PoisonedRAG** | foundational | Few malicious texts control RAG output |
| **Agent Security Bench** | 2410.02644 | 84.3% avg attack success across 27 attack/defense combos |

**Takeaway:** persistent memory is a durable attack surface — poison once, and corruption re-executes across future sessions and even other users. **No memory vendor publishes quantitative robustness numbers.** This is the clearest open differentiation opportunity in the market.

---

## 8. Per-system SWOT

### mem0 — *the traction leader*
- **S:** Largest mindshare (~50–60k★), 21+ integrations, AWS selection, $24M funded, simple API.
- **W:** Extraction+vector is architecturally shallow for temporal/relational reasoning; benchmark claims contested.
- **O:** Become the default memory API across agent frameworks; enterprise tier.
- **T:** Hyperscaler bundling; graph-native rivals on hard reasoning tasks.

### Zep / Graphiti — *the temporal-graph specialist*
- **S:** Bi-temporal knowledge graph (best-in-class "what was true when"); strong technical narrative; arXiv paper.
- **W:** Heavier infra; publicly caught in a benchmark-inflation correction; small funding.
- **O:** Own "temporal reasoning" and compliance/audit use-cases.
- **T:** Credibility hangover from the 84%→75% episode; commoditization of basic memory.

### Letta (MemGPT) — *the OS-style pioneer*
- **S:** Originated the space (MemGPT); credible research team (Berkeley); $70M-val funding; intellectually honest (published the filesystem critique).
- **W:** Framework complexity; memory is one part of a broader stateful-agent platform.
- **O:** Standard runtime for stateful agents; research credibility → enterprise trust.
- **T:** Simpler APIs (mem0) win on developer adoption; no Series A yet.

### Cognee — *the knowledge-graph ETL play*
- **S:** ECL pipeline over 38+ sources; 70+ production users (incl. Bayer); €7.5M; EU/enterprise positioning.
- **W:** Lower mindshare than mem0/Zep; no independent benchmark.
- **O:** Enterprise data-integration + memory convergence.
- **T:** Overlaps with GraphRAG tooling and Zep.

### MemOS (MemTensor) — *the "memory OS" + benchmark host*
- **S:** Ambitious MemCube abstraction (plaintext/KV-cache/parameter memory); academic consortium; runs OmniMemEval.
- **W:** **Runs its own leaderboard where it wins** — credibility discount; funding/backing opaque.
- **O:** Define memory-OS category in China/academic markets.
- **T:** Neutral observers discount vendor-run evals.

### supermemory — *the developer-API upstart*
- **S:** Clean memory API, strong angel roster (Jeff Dean et al.), fast-growing (~28k★), connectors.
- **W:** Very small raise (~$2.6M); young team; self-reported "#1" claims.
- **O:** Win indie/startup developers; consumer app upside.
- **T:** Bundling; better-funded rivals (Engram, mem0).

### HippoRAG — *the academic rigor benchmark*
- **S:** **Only major system reporting clean deterministic recall@k**; NeurIPS'24; neuroscience-inspired PPR retrieval.
- **W:** Research artifact, not a product; no company/support.
- **O:** Reference baseline everyone measures against.
- **T:** Not commercialized; productized rivals capture the market.

### Engram — *the mega-funded dark horse*
- **S:** $98M / $600M val; Karpathy/Sequoia/GC backing; trained per-org memory models; ~100x token-efficiency claim; blue-chip customers (Microsoft, Notion, Harvey).
- **W:** Closed, unproven publicly; 13 people; no published benchmarks yet.
- **O:** Redefine memory as a *trained model* rather than a retrieval pipeline; enterprise land-grab.
- **T:** Delivery risk at valuation; frontier labs building memory in-house.

### Sidebar: gbrain & MemPalace — *viral episodes, not incumbents*
Both appeared **April 2026** and spread as "top memory systems." Treat with skepticism:
- **gbrain** (`garrytan/gbrain`): a real personal project by Garry Tan (YC), ~25k★ in weeks, but a **self-invented "BrainBench"** metric — not a validated, peer-reviewed system.
- **MemPalace** (`mempalace/mempalace`): ~47k★ in two weeks, then **independently audited (Issue #29) and partly retracted**. Its "96.6% R@5 on LongMemEval" is just ChromaDB's default embeddings on verbatim text; its 100% LoCoMo used top_k=50 (retrieving the entire candidate pool); the "palace" structure added no measurable lift. A textbook case of the recall-vs-QA conflation and benchmark-gaming. **Not a credible SOTA system.**
The lesson for competitive analysis: GitHub stars are a hype signal, not a quality signal, and 2026 saw deliberate star-inflation and benchmark theater in this exact category.

---

## 9. Strategic implications — what "best in the world" actually requires

Because no authority ranks these systems, **credibility is won on reproducibility hygiene, not raw scores.** Concretely:

1. **Lead with deterministic benchmarks.** Publish LongMemEval retrieval-recall + the HippoRAG multi-hop suite. Deterministic numbers survive the scrutiny that killed LoCoMo QA claims.
2. **Publish at the field's highest evidence standard:** pinned harness commits, per-question artifacts, retrieval traces, disclosed configs and judge prompts. This is what made Zep's 84% auditable and Mastra's number respected.
3. **Fill the empty columns.** Report memory-poisoning attack-success rate (MINJA/AgentPoison) and calibration/ECE. Almost no one does — it converts the debate from "who's #1 on a contested board" to "who's the only system with recall *and* security *and* calibration."
4. **Avoid the traps:** never headline LoCoMo/DMR; never present recall@k as if it were QA accuracy; never cite a private/self-defined benchmark as a public claim (that's exactly what sank MemPalace and what makes gbrain's "BrainBench" non-credible).
5. **The open opportunity:** the field is openly asking for a neutral, submission-accepting leaderboard. Whoever builds it credibly — pinned harnesses, artifact-required submissions, both metric families kept separate — owns the framing of the entire category.

---

## 10. Sources & confidence

**High confidence** (primary sources): system repos, licenses, languages; funding facts (Engram $98M, mem0 $24M, Letta $10M/$70M, Cognee €7.5M, supermemory $2.6M); benchmark provenance and scoring methodology; the mem0/Zep dispute and its correction; LoCoMo audit; Papers with Code shutdown; security attack papers.

**Medium confidence:** absolute GitHub star counts (fast-moving; some inflation in circulation); Zep's exact seed size; Memori's SPDX license; several 2026 self-reported vendor scores (measured on differing benchmark versions and judge prompts — not independently reproduced).

**Key primary sources:**
- Systems: github.com/{mem0ai/mem0, getzep/graphiti, letta-ai/letta, topoteretes/cognee, MemoriLabs/Memori, MemTensor/MemOS, OSU-NLP-Group/HippoRAG, agiresearch/A-mem}
- Papers: LoCoMo (arXiv 2402.17753), LongMemEval (2410.10813), HippoRAG (2405.14831), mem0 (2504.19413), Zep/Graphiti (2501.13956), BEAM (2510.27246), MemoryAgentBench (2507.05257), ConvoMem (2511.10523), memory survey (2603.07670), MINJA (2503.03704), AgentPoison (2407.12784)
- Dispute: getzep/zep-papers issue #5; blog.getzep.com; Letta filesystem-baseline blog; Penfield Labs LoCoMo audit
- Funding: TechCrunch (mem0, supermemory), PRNewswire/CNBC (Engram, Letta), EU-Startups (Cognee)
- MemPalace audit: github.com/MemPalace/mempalace/issues/29; independent reviews (artificiallyintimidating.com, danilchenko.dev)
- OpenAI/Anthropic/Google/Microsoft memory: official product blogs and docs

*All benchmark scores attributed to vendors are self-reported and mutually disputed. This report deliberately does not present any single system as objectively #1, because the evidence base does not support such a claim.*
