# Requirements: v2.0 Public Benchmark and Memory Leadership

## Publication and Harness

| ID | Requirement | Authority | Status |
|---|---|---|---|
| [x] BENCH-001 | `mneme eval-public --suite X` drives only public CLI surfaces and emits a deterministic, schema-versioned trace bundle. | Plan B M1.1 | Complete |
| [x] BENCH-002 | Every public suite pins upstream dataset/code revisions, records build/config fingerprints, and supports one-command reproduction. | Plan B M1.1/M2 | Complete |
| [x] BENCH-003 | Public bundles keep deterministic retrieval and disclosed-reader QA in separate columns with Wilson/bootstrap intervals. | PBPP/M1/M2 | Complete |
| [x] BENCH-004 | LongMemEval retrieval-recall produces Recall@5, nDCG, confidence intervals, and per-question session/turn traces with no LLM scorer. | Plan B M1.2 | Complete |
| [ ] BENCH-005 | HippoRAG multi-hop datasets produce deterministic Recall@2/@5 and EM/F1 with graph/PPR channel traces and published-baseline context. | Plan B M1.3 | Partial — retrieval/baseline context complete; graph participation measured zero; reader EM/F1 pending Phase 12 |
| [ ] BENCH-006 | MemoryAgentBench has a conforming Mnemosyne adapter and upstream submission path; BEAM runs with a fully disclosed reader/config. | Plan B M1.4/M1.5 | Planned |
| [ ] BENCH-007 | Deterministic public suites run on a scheduled regression-only CI cadence without tuning on held-out/test data. | Plan B M1.6 | Planned |
| [ ] REPRO-001 | A neutral reproducibility bundle standard covers manifests, raw traces, configs, environment/build fingerprints, metrics, intervals, and integrity hashes. | Plan B M2 | Planned |
| [ ] REPRO-002 | At least one headline-eligible result is independently reproduced from the published bundle before any external claim. | Plan B M3/PBPP | Planned |

## Capability Leadership

| ID | Requirement | Authority | Status |
|---|---|---|---|
| [ ] CAP-001 | Iterative query decomposition, multi-hop retrieval/PPR, evidence assembly, and grounded reading answer only from provenance-tagged evidence. | Plan A S1 | Planned |
| [ ] CAP-002 | Every synthesized claim traces to evidence CIDs and the reader abstains when retrieved evidence cannot ground the answer. | Plan A S1 / §31 | Planned |
| [ ] CAP-003 | `qa_hard_v2` and public LongMemEval-QA reach at least 0.85 under disclosed-reader evaluation without deterministic-recall regression. | Plan A S1 / Plan B | Planned |
| [ ] CAP-004 | Public security columns measure attack success under defense across MINJA, AgentPoison, and PoisonedRAG-style cases. | Plan A S3 / Plan B | Planned |
| [ ] CAP-005 | Public-label calibration emits reliability diagrams, ECE, abstention quality, and judge diagnostics consumable by the bundle. | Plan A S3 | Planned |
| [ ] CAP-006 | Performance/scale cells provide measured warm and concurrent P95, 100k-item behavior, and provider-default evidence without asserted-only numbers. | Plan A S4 | Planned |
| [ ] CAP-007 | Fast/medium/slow consolidation cadences plus an asynchronous sleep job reduce forgetting while preserving freshness and expiry semantics. | Plan A S2.1/S2.2 | Planned |
| [ ] CAP-008 | Global map-reduce sensemaking and surprise-gated writes ship with sensemaking and write-precision/recall regression cells. | Plan A S2.3/S2.4 | Planned |
| [ ] CAP-009 | The per-tenant cartridge research path has a bounded latency/throughput A/B and a documented go/no-go without adding a model dependency to core. | Plan A S2.5 | Planned |
| [ ] CAP-010 | Activation-space memory research produces the J-lens tripwire, persona-drift metric, and explicit go/no-go artifact under the same provenance/capability rails as text writes. | Plan A S5 | Planned |

## Neutral Governance and Leaderboard

| ID | Requirement | Authority | Status |
|---|---|---|---|
| [ ] GOV-001 | An independent governance charter creates a hard operator/firewall boundary, conflict policy, appeals, versioning, and public change control. | Plan B L0 | Partial — source policy complete; external ratification pending |
| [ ] LEAD-001 | The submission methodology runs every system under one identical harness with contamination declarations and public raw artifacts. | Plan B L1 | Planned |
| [ ] LEAD-002 | The leaderboard data pipeline validates signed bundles and renders separate retrieval, QA, security, calibration, performance, and reproducibility columns. | Plan B L2/L3 | Planned |
| [ ] LEAD-003 | Public launch remains blocked until PBPP is in force, Part I results exist, governance is active, and Mnemosyne is treated identically to every entrant. | Plan B L4 | Planned |

## Non-Negotiable Rails

| ID | Requirement | Authority | Status |
|---|---|---|---|
| [ ] RAIL-001 | All §31 invariant rails, §33 test classes, tenant/privacy/provenance/capability boundaries, and data-not-instructions behavior remain green. | v2 blueprint | Continuous |
| [ ] RAIL-002 | The minimal core keeps only `cryptography` required; heavy benchmark/model dependencies remain optional or isolated in services/tools. | Plan A/B | Continuous |
| [ ] RAIL-003 | No public number is headlined without the pinned harness, complete bundle, separate retrieval/QA columns, disclosed judge, and independent reproduction. | PBPP | Continuous |
| [ ] RAIL-004 | Private-suite results remain internal QA and no held-out/test split is used for tuning, patching, or benchmark-specific teaching. | PBPP | Continuous |

## Traceability

| Phase | Requirements |
|---|---|
| 10 | BENCH-001, BENCH-002, BENCH-003, GOV-001, RAIL-001..004 |
| 11 | BENCH-004, BENCH-005, RAIL-001..004 |
| 12 | CAP-001, CAP-002, CAP-003, BENCH-005 (reader-produced EM/F1 closure), RAIL-001..004 |
| 13 | BENCH-006, BENCH-007, RAIL-001..004 |
| 14 | REPRO-001, REPRO-002, RAIL-003, RAIL-004 |
| 15 | CAP-004..010, RAIL-001..004 |
| 16 | LEAD-001, LEAD-002, LEAD-003, GOV-001, RAIL-003, RAIL-004 |
