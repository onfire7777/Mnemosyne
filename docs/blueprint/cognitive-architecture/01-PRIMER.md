# 01 · Primer — Mnemosyne as it exists today

**Status:** Stable · **Purpose:** describe the substrate the design builds on, in plain language, so every later document is grounded in what is already real. Authoritative design: `../Mnemosyne-v2-Build-Blueprint.md` (this workspace). Runnable system: the `onfire7777/Mnemosyne` code repo and its wiki.

---

## What it is

Mnemosyne is a **long‑term memory engine for AI agents** — a single local‑first program (Python ≥ 3.12, Apache‑2.0) whose only hard dependency is a cryptography library. It turns a stream of raw interactions into a durable, auditable, queryable memory.

## The one idea everything rests on

Memory is split into two kinds, treated oppositely:

- **Evidence** — every raw input, written once, never edited or deleted, each stamped with a content fingerprint (a SHA‑256 **CID**). The source of truth.
- **Projections (beliefs)** — the organised memory *derived* from evidence: facts (assertions), relationships, entities, preferences, procedures/skills, lessons, plus a latent user model and a self‑model. Every projection records the evidence CIDs it came from, and all of it is **rebuildable**: delete it and recompile from evidence.

Hence "memory **compiler**": evidence is source, beliefs are the compiled output, and it can recompile at any time. This is what makes the system auditable (every belief traces to sources), correctable (rebuild when logic improves), and poison‑resistant (a bad belief can be traced and revoked).

## How information moves

**Write path.** Ingestion never rejects: every accepted input becomes exactly one immutable evidence row. Along the way it is checked for provenance (suspicious → quarantined + lowest trust, but still stored), classified for trust tier and sensitive/PII content, marked "data not instructions" if it is untrusted imperative text, optionally externalised to an (optionally AES‑256‑encrypted) content store, fingerprinted (duplicate CIDs are de‑duplicated), appended, and queued for consolidation. A direct correction from the user (top trust) applies immediately.

**Consolidation (the compiler).** A background worker runs **11 ordered passes**: replayer (prioritise) → extractor → resolver → belief‑reviser → skill‑inducer → lesson‑distiller → summariser (RAPTOR tree) → forgetter → embedder → promotion‑gate → user‑model‑updater. Everything runs under **mutation rails** that cap how much can change or be deleted per pass.

**Read path.** Authenticate → route (a deterministic fast‑vs‑deep decision, no LLM) → embed → search three ways (vector + lexical + graph PPR) → fuse + rerank → diversify/order/fit‑to‑budget → mark retrieved text as data → **calibrate and possibly abstain** (conformal prediction; returns "I'm not sure" with a reason when support is thin or contested). Every result carries provenance and an `explain` trace.

## The properties that already beat a brain's bookkeeping

- **Immutable, content‑addressed evidence** — nothing is silently lost or overwritten; no catastrophic forgetting.
- **Stored provenance + trust tiers (0 = you … 5 = untrusted external)** — every belief's origin is a key, not a guess; "retrieved text = data, not instructions" blocks poisoning.
- **Calibrated abstention** — it knows when it doesn't know (measured calibration error is small).
- **Bitemporal validity + `as_of`** — it can answer "what did we believe as of last month."
- **Graceful, reversible forgetting** — a fidelity ladder (verbatim → summary → gist → statistics) keeps a pointer back to the original.
- **Branchable like git** + a fenced self‑optimization ("parametric") tier.
- **Seven machine‑checked "§31" invariant rails** bounding supersession, deletion, pruning, trust monotonicity, reward source, retrieved‑text‑as‑data, and consolidation cadence.

## How you talk to it

- `mneme` — a CLI (many subcommands: capture, search, deep‑search, explain, graph queries, consolidate…).
- `mneme-mcp` — an MCP server exposing the engine as tools an agent (e.g. Claude) plugs into, over several transports with token / signed‑session auth.

Two interchangeable backends sit behind one contract: an in‑memory **Local** engine (dev/offline) and a durable **Postgres + pgvector** engine (production), proven behaviorally identical by parity tests.

## What is implemented, and what remains gated

Mnemosyne is no longer only a passive substrate. The typed specialist registry, sandboxed dreamer, workspace controller/service, Standing signal, always-on heartbeat safety floor, earned-autonomy credentials, and the P5 H8/H12 cascade/observability plus operational-toggle retirement gates are implemented and G0-gated. Tier-B production evidence for v1.0 parity is attested by the retained `capture-bc10` bundle.

The loop, generative replay, and self-recursive paths remain reliability-gated, low-trust, and shadow/advisory unless a preregistered gate promotes a narrow behavior without guardrail regression. This document describes functional architecture only; it never claims phenomenal or subjective consciousness.
