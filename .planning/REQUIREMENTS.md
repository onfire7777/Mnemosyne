# Requirements

## P0 Must-Haves

| ID | Requirement | Blueprint Anchor | Current Status |
|----|-------------|------------------|----------------|
| REQ-001 | Append-only, content-addressed, verbatim evidence ledger with idempotent deduplication and byte retrieval. | FR-1, Phase 0 | Implemented and tested locally |
| REQ-002 | Branchable memory with discard rollback and promotion via merge. | I3, Phase 0, Phase 4 | Implemented locally and under clean Postgres DSN with branch/discard/merge promotion plus tenant-exported merge audit logs; deployment evidence is now covered by `release-audit` fingerprint gates |
| REQ-003 | Per-tenant and per-source isolation with trust tiers. | FR-7, Security §27 | Implemented locally and live-verified with Postgres RLS tests; production auth evidence is gated through OIDC/JWKS, authz-policy, session-secret, and release-audit checks |
| REQ-004 | Stable agent-facing MCP/CLI contract for capture, search, deep_search, explain, correct, forget, export. | FR-9, §30.7 | Implemented locally |
| REQ-005 | Bitemporal assertion store with supersession, no destructive overwrite, and as-of queries. | FR-2, Phase 1 | Implemented and tested locally |
| REQ-006 | Hybrid retrieval with lexical, dense, graph channel contract, RRF fusion, MMR dedup, budget control, provenance, and trust filtering. | FR-3, §22, §30.4 | Implemented locally with deterministic dense hash and graph PPR; provider-check and release-audit now require production embedding/reranker plus non-local lexical/graph backend evidence |
| REQ-007 | Explainability from returned facts to evidence and retrieval channels. | FR-4 | Implemented and tested locally |
| REQ-008 | User inspect, correct, export, and forget with transitive erasure behavior. | FR-8, §25 | Implemented and tested locally |
| REQ-009 | Confidence and abstention when evidence is thin, conflicting, or below threshold. | FR-6, §26 | Implemented locally with conformal calibration, empty/oversized prediction-set abstention, shared Local/Postgres retrieval coverage, and dataset-driven `calibration-tune` gates for production threshold tuning |
| REQ-010 | Capability-mediated writes, audit log, data-never-instruction handling, and reversible destructive operations. | FR-7, §27 | Implemented locally with signed sessions, authz-policy mapping, capability gates, audit records, and release-audit coverage for production role/auth surfaces |
| REQ-011 | Private regression suite with protected cases, seed suite, shadow mode, promotion gate, and no-regression invariant. | §23.3, §33 | Implemented locally with seed/gate checks, protected cases, fingerprinted suite review, minimum-case/protected-count gates, required smoke/core/archive tier coverage, and release-audit artifact validation |

## P1 Should-Haves

| ID | Requirement | Blueprint Anchor | Current Status |
|----|-------------|------------------|----------------|
| REQ-012 | Typed explicit user model with six categories, scope, confidence, validity, and override behavior. | FR-5, §24 | Implemented with six memory categories, scope/confidence/validity metadata, authority ordering, scope exceptions, latent advisory profile, and CLI/MCP/Postgres runtime persistence; dedicated product UX remains non-blocking |
| REQ-013 | TMS and AGM belief revision with cascade invalidation and contested multi-hypothesis beliefs. | I2, §30.3 | Implemented locally with justification links, dependency cascade invalidation, contradictions, supersession, and contested probability surfacing; broader production parity remains required |
| REQ-014 | Temporal entity graph with cached and live PPR. | Phase 2 | Local graph channel implemented; provider-check and release-audit now require an explicit non-local graph backend such as AGE/specialist adapters for production evidence |
| REQ-015 | Fidelity-tiered forgetting with salience decay, demotion ladder, gist-risk abstention, and spaced rehearsal. | I7, §25 | Implemented locally and under clean Postgres DSN with storage-backed lifecycle demotion, persisted must-keep rehearsal scheduling metadata, gist-risk abstention, and fingerprinted `forgetting-policy-check` suite validation |
| REQ-016 | Warm-loop consolidation with society-of-roles extraction, incremental recompute, and gate-protected promotion. | §21, §30.5 | Implemented locally and under clean Postgres DSN with ordered role passes, command-backed model adapter boundaries for extractor/resolver/summarizer, role-pipeline provenance reporting, incremental projection recompute, and gate-protected promotion; real hosted LLM/provider validation remains required |
| REQ-017 | Procedural and corrective learning with trajectory logging, lesson distillation, promotion gate, and rollback. | Phase 4 | Implemented with trajectory logging, failure attribution, lesson/procedure induction, promotion gates, rollback, CLI/MCP runtime persistence, protected-suite checks, and release-audit validation of deployed gate-suite evidence |
| REQ-018 | Profile-guided self-optimization for routing, activation weights, thresholds, and cadence in shadow mode. | Phase 5 | Shadow policy optimizer and contextual bandit learner implemented for logged policy-variant outcomes under invariant rails, with fingerprinted `policy-ops-check` validation for shadow-only variants, external rewards, cadence, tripwires, and contextual-bandit recommendation evidence |

## Non-Functional Requirements

| ID | Requirement | Current Status |
|----|-------------|----------------|
| NFR-001 | Fast-mode overhead P95 within roughly 300-400 ms before generation. | Implemented with local latency benchmark test |
| NFR-002 | Local to production parity with one schema and shared test suite. | Implemented and live-verified with Docker Postgres plus shared Python suite |
| NFR-003 | Evidence durability is highest SLO; derived stores are rebuildable. | Reflected in engine design and schema |
| NFR-004 | Privacy via tenant isolation, PII tagging, transitive erasure, and configurable residency. | Implemented with privacy classification, residency field, and erasure mode primitives |
| NFR-005 | Observability for retrieval hit rates, latency, consolidation, contradiction backlog, calibration, abstention, promotion, rollback, diversity, and proxy divergence. | Implemented with metrics registry and tested counters/gauges; dashboard remains an operations surface |
