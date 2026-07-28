# Mnemosyne Whole-Memory Benchmark Standard — Design Specification

**Date:** 2026-07-26

**Hardened:** 2026-07-28

**Status:** Proposed subordinate standard — documentation and implementation
planning authorized; benchmark implementation and publication not authorized

**Author scope:** Convert the approved whole-memory benchmark research and its
2026-07-28 quality audit into an executable design contract without creating
benchmark production code, results, certifications, or comparative claims.

**Approval boundary.** The owner authorized this documentation hardening and a
separate implementation plan for the minimal reference harness and pilots
M01/M03/M10/M12/M13/M15/M20. That authorization does **not** authorize
benchmark implementation, benchmark execution, a push, a pull request,
publication, certification, or a superiority claim. Existing Phase 13 and
Phase 16 work remains governed by its own leases and evidence gates.

## 0. Authority and relationship to existing documents

This document is a **proposed subordinate standard**. It organizes comparison
and disclosure requirements; it does not supersede product architecture,
frozen metric rails, active phase ownership, or implemented publication
contracts.

Authority is resolved in this order:

| Precedence | Source | Authority retained |
|---|---|---|
| 1 | `docs/blueprint/Mnemosyne-v2-Build-Blueprint.md` and `.planning/PROJECT.md` | Controlling product architecture, invariants, and trust boundaries |
| 2 | `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/MILESTONES.md`, and `GOAL.md` | Canonical owners for status, requirements, dependencies, milestones, and leases; freshness must be verified against current Git/merge evidence |
| 3 | `docs/superpowers/specs/2026-07-15-world-best-memory-platform-design.md` | Approved program design and non-weakening boundary |
| 4 | `docs/EXECUTION-PLAN-A-Memory-System.md` | Product capability sequencing, hardware, and product acceptance intent |
| 5 | `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md` and PBPP | Public harness, official-suite fidelity, custody, publication eligibility, and claim boundaries |
| 6 | `docs/blueprint/eval/01-metrics-specification.md`, `docs/blueprint/eval/03-dataset-and-corpora-spec.md`, `docs/blueprint/eval/04-adversarial-security-playbook.md`, and hardware runbooks | Metric definitions, corpus contracts, safety rails, and workload admission |
| 7 | `eval/public/`, `leaderboard/schema/result-v1.schema.json`, and `leaderboard/{validate,ledger,render,publish,readiness}.py` | Implemented public bundle and publication semantics for the exact code/results they produce |
| 8 | `docs/benchmark/MEMORY-NATIVE-BENCHMARK.md` | Existing D1–D9 memory-native research dimensions |
| 9 | This document | Proposed whole-system taxonomy, comparator divisions, module contracts, and staged research program |

Ownership does not imply freshness. At this cutoff, `STATE.md`,
`MILESTONES.md`, `ROADMAP.md`, and `GOAL.md` lag portions of merged main; the
live requirement matrix below therefore records its Git cutoff and calls out
known stale owner records instead of treating them as current receipts.

If this document conflicts with a higher-precedence source, the affected
module is `DEFERRED-CONFLICT`; no implementer may choose the easier rule.
Completion status changes only in `.planning/*` and the active `GOAL.md`.

CBM is discovery evidence, not a portable normative dependency. At the
2026-07-28 hardening cutoff the canonical index was refreshed and healthy at
21,083 nodes and 96,224 edges, while the ADR facility returned no stored
sections. This standard therefore cites repository-owned architecture and
decision sources directly and makes no claim about a fixed count of CBM ADRs.

Current result-v1 and ledger behavior is reused by reference. A future
result-v2 may extend metric families and custody labels, but it must not
reinterpret, mutate, or silently migrate a valid v1 record.

The existing MNB dimensions map without duplication:

| Existing MNB dimension | Governing module here |
|---|---|
| D1 Provenance integrity | M05 Provenance and explanation |
| D2 Calibrated abstention | M10 Calibration and abstention |
| D3 Bitemporal correctness | M03 Temporal evolution |
| D4 Belief revision | M04 Conflict and correction |
| D5 Deletion compliance | M09 Declared-surface erasure conformance |
| D6 Write-path safety | M11 Security and isolation |
| D7 Consolidation and decay | M06 Consolidation and learning; M07 Retention, rehearsal, and decay |
| D8 Prospective memory | M12 Prospective action |
| D9 Working memory | M13 Working memory |

## 1. Non-negotiable intent

Mnemosyne's benchmark program evaluates a **whole memory system**, not
retrieval strength in isolation. It must measure evidence and provenance;
bitemporal correction with preserved history; repeated-cycle consolidation,
rehearsal, and non-degradation; protected retention; reversible forgetting
separately from irreversible legal erasure; calibrated abstention; tenant and
security isolation; safe handling of retrieved content as data rather than
instruction; prospective memory with exactly-once intention behavior; backend
parity and interoperability; and auditable, reproducible result publication.

The public comparator must remain fair across architectures. Universal
black-box outcome tests are scored for every entrant through a minimal
adapter. Advanced capabilities are tested only when a system exposes a native
or emulated interface and are otherwise disclosed as `unsupported`, not
converted into an artificial failure. A capability checklist is not a quality
score, and no superiority claim is permitted before held-out, reproducible
results exist.

This is a comprehensive benchmark standard, not a gap-filling supplement.
For every admitted upstream benchmark it preserves an `OFFICIAL-UPSTREAM`
track that runs the upstream protocol unchanged for direct comparability, and
it may define a separately named `ENHANCED-SUCCESSOR` track that tests the
same construct more rigorously. Official and successor results are distinct
evidence families: they are displayed side by side and are never blended into
one certified score, leaderboard rank, or headline claim.

Every capability in this specification must trace to:

1. a benchmark module or an explicit `unsupported` disclosure;
2. a portable adapter contract;
3. an objective measurable outcome and anti-gaming control;
4. public-comparison, release-gate, or internal-regression placement;
5. a signed, reproducible result artifact and honest claim boundary.

## 2. Design goals and non-goals

### 2.1 Goals

1. Compare complete memory systems through externally observable outcomes.
2. Preserve fair access for systems with different internal architectures.
3. Distinguish quality, capability coverage, safety certification, and
   efficiency rather than hiding them in one score.
4. Require executable contracts and measured feasibility receipts before a
   module is described as runnable.
5. Support a standard 16 GB Apple Silicon development profile without claiming
   that every official full-scale external benchmark fits that profile.
6. Preserve official upstream protocols unchanged while versioning stronger
   successor tracks separately; reuse existing repository contracts before
   creating new data, metrics, or infrastructure.
7. Produce reproducible, tamper-evident artifacts suitable for public review.

### 2.2 Non-goals

- This specification does not implement a harness, adapter, dataset, scorer,
  website, or leaderboard.
- It does not declare any result, ranking, launch readiness, or completed
  benchmark phase.
- It does not make feature presence a substitute for measured quality.
- It does not require competitors to expose private embeddings, graphs,
  confidence internals, databases, or proprietary prompts.
- It does not make an external board or third-party reproduction a prerequisite
  for an honestly labeled **open, operator-run, fully auditable** result.
  Stronger `neutral`, `independent`, or `certified` labels require the evidence
  those words claim.
- It does not waive human publication approval, PBPP custody, identical
  treatment, or protected-evidence gates.

## 3. Evidence language

- **Implemented:** code and a current internal test contract exist.
- **Internally measured:** a repeatable repository harness emits a metric, but
  the result is not an eligible public comparison.
- **Publicly measured:** a versioned official or faithful held-out protocol,
  comparable baselines, uncertainty, and replayable artifacts exist.
- **Supported:** the submitted adapter can perform the operation natively or
  through a disclosed emulation.
- **Unsupported:** the operation is unavailable through the submitted public
  interface. This is a disclosure, not a failed outcome.
- **Deferred:** a named feasibility dependency is absent, so implementation or
  execution is intentionally unscheduled.
- **Proposed:** the module has a design rationale but lacks one or more
  machine-readable feasibility artifacts.
- **Contract-ready:** schemas, fixtures/generator, scorer, baselines, and
  deferral rules are frozen, but no measured resource receipt exists.
- **Pilot-ready development (`PILOT-READY-DEV`):** a deterministic smoke
  receipt proves the contract on L16-DEV; this is not public run readiness.
- **Run-ready:** a signed, profile-specific receipt proves all admission,
  resource, custody, and replay gates for the exact module version.
- **Target:** a proposed acceptance threshold. A target is never an achieved
  result until a signed run proves it.

Machine-readable results keep two closed fields separate:

- `admission_state` uses only the Section 4.2 enum.
- `evidence_level` is one of `DESIGN_ONLY`, `IMPLEMENTED`,
  `INTERNALLY_MEASURED`, or `PUBLICLY_MEASURED`.

An implementation receipt cannot promote admission, and an admission state
cannot imply a measured result.

Proposed gates in this document do not silently override frozen product rails,
PBPP, or an approved metric definition. A later implementation plan must map
each gate to its canonical metric ID. If two approved thresholds conflict, the
module is DEFERRED until the owner resolves the conflict; an agent may not pick
the easier value.

## 4. Feasibility admission gate

No module enters production implementation or a scored run until its
machine-readable feasibility record contains every required field. The
separate pilot plan may implement only the minimal artifacts needed to move
M01/M03/M10/M12/M13/M15/M20 from `PROPOSED` toward
`PILOT-READY-DEV`.

### 4.1 Required fields

1. **Identity:** `module_id`, semantic `module_version`, source commit, and
   owning requirement/metric identifiers.
2. **Runnable adapter contract:** `adapter_schema_id@sha256`, exact calls,
   response/error fields, protocol negotiation, timeouts, retries,
   idempotency, ordering, and state-transition semantics.
3. **Data source:** `dataset_manifest_id@sha256` for a licensed pinned dataset,
   or `generator_id@sha256`, schema, seed domain, and golden fixtures for a
   deterministic synthetic generator.
4. **Objective scorer:** `scorer_id@sha256`, executable command, golden
   vectors, numeric precision/canonicalization rules, and failure exit codes.
   Any LLM judge is secondary, pinned, disclosed, and paired with an auditable
   rubric and human-audited sample.
5. **Inherited rails:** exact canonical metric IDs and non-waivable functional
   or safety thresholds. New comparison metrics may be diagnostic but may not
   weaken a rail.
6. **Baseline manifest:** `baseline_manifest_id@sha256` fixing tokenizer,
   chunking, overlap, embedding/model, index parameters, top-k, prompt,
   context order/truncation, cache state, setup/indexing cost, and budget.
7. **Inferential plan:** `power_plan_id@sha256` fixing the primary endpoint,
   denominator, independence/blocking unit, sample size or power/MDE rationale,
   seeds/reruns, interval, multiplicity, tie, missing-data, abort, and rerun
   rules.
8. **Repeat/replay protocol:** canonical deterministic payload, volatile-field
   exclusion, run count, seed encoding, float/order/time/locale rules, clean
   process replay, and artifact digest rules.
9. **Sandbox and metering:** `sandbox_profile_id@sha256`, trust boundaries,
   mounts, egress, secrets, privilege, resource limits, scorer isolation,
   model proxy, and harness-owned usage counters.
10. **Resource receipt:** `resource_receipt_id@sha256` from the exact profile,
    including full SUT boundary, wall time, peak RSS, host free memory, swap,
    disk, CPU/GPU, workers, network, model calls/tokens/cost, cold/warm state,
    and abort status.
11. **Supply-chain and data rights:** dataset/software BOM, declared and
    concluded licenses, redistribution mode, lineage, modifications,
    attribution, PII/consent basis, privacy scan, retention/takedown rules,
    OCI/lockfile/SBOM/build provenance, and external services/secrets.
12. **Result contract:** exact result schema version, metric family, attempt
    ledger state, signature/custody label, and v1/v2 compatibility behavior.
13. **Deferral condition:** the precise missing artifact, unstable dependency,
    authority conflict, resource failure, or rights restriction that blocks
    the next state.
14. **Feasibility disposition:** independently stated for development,
    official local, hosted-service, and production/operations variants.

### 4.2 Admission states

- **PROPOSED:** design-only; at least one §4.1 artifact is absent. Every module
  in this revision starts here.
- **CONTRACT-READY:** all contracts except the measured resource receipt and
  deterministic smoke receipt are complete and reviewed.
- **PILOT-READY-DEV:** an implemented deterministic development slice has a
  passing smoke receipt on L16-DEV. It remains non-ranking and non-certifying.
- **RUN-READY-`<profile>`:** every §4.1 artifact exists for the exact module
  version and the signed profile receipt passes. This state is earned by
  evidence, never assigned in prose.
- **DEFERRED:** a dependency is absent or its contract is not stable enough to
  implement honestly.
- **DEFERRED-CONFLICT:** two controlling sources disagree.
- **UNSUPPORTED-BY-SYSTEM:** the submitted public surface lacks an optional
  capability. This is a disclosure about an entrant, not module failure.
- **REJECTED:** the proposed module lacks an objective outcome, creates
  architecture-specific self-dealing, or cannot be reproduced within a
  declared budget.

An unavailable official track may never be replaced by a synthetic result
under the official name. A local slice remains a development conformance or
regression result, not an official reproduction or certification.

## 5. Resource profiles

### 5.1 L16-DEV — non-ranking development profile

- Apple Silicon Mac with 16 GB unified memory, macOS, and the
  repository-pinned Python/`uv` environment.
- The mandatory admission and abort rules are
  `.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md`; this document does not
  weaken them. Model-backed work is serialized to one model request/process.
- The resource boundary includes harness, adapter, model, database,
  containers, background workers, filesystem growth, and any local proxy.
  Process-tree RSS alone is insufficient.
- A module declares **proposed** ceilings, then earns
  `PILOT-READY-DEV` only after a measured receipt records host free memory,
  pressure/swap, worker count, wall time, peak RSS, disk, setup/indexing,
  cold/warm state, and cleanup/retention.
- There is no asserted ten-hour suite, six-hour stage, 25 GiB corpus, or
  four-worker guarantee in this revision. Suite ceilings may be introduced
  only from measured per-module receipts plus an explicit shared-artifact and
  cleanup schedule.
- No paid API is mandatory for deterministic pilots. Provider variants are
  separate profiles and never replace deterministic scoring.

L16-DEV results are conformance evidence only. They are never ranked as
hardware efficiency and do not prove the physical 8 GiB Windows/Linux
requirement in `.planning/REQUIREMENTS.md` CAP-011.

### 5.2 OFFICIAL-LOCAL — reproducible ranked reference profile

The official local profile is `DEFERRED` until governance freezes a
vendor-neutral reference host or a small published host matrix. Its manifest
must pin CPU/GPU/architecture, cores, memory, storage, OS/kernel, runtime,
drivers, locale/timezone, thermal/power policy, cache state, concurrency, and
network policy. Ranked latency, throughput, memory, and cost comparisons occur
only within the same exact profile.

### 5.3 HOSTED-X — hosted-service outcome profile

- The harness controller and request policy are pinned, while provider compute
  remains outside the measurable local boundary.
- Provider, endpoint/region, model revision, prompt digest, request/token
  counts, retry, latency, billed cost, rate limits, cache disclosures, and data
  egress are retained.
- Calls and tokens are counted by a harness-owned proxy, not trusted solely
  from entrant self-report.
- Hosted outcomes may be compared on task quality, service latency, and billed
  cost. They do not share local compute-efficiency ranks.

### 5.4 H8-PHYSICAL — physical-floor product profile

- CAP-011 requires real 8 GiB Windows/Linux evidence on the declared physical
  host class. An L16 run, VM memory limit, container limit, or extrapolation
  cannot substitute.
- The profile retains the same admitted quality-critical artifacts, policy,
  custody, and decoded decisions as stronger profiles; it may reduce only
  throughput, concurrency, corpus capacity, or acceleration.
- Exact OS/build, architecture, physical memory, storage, drivers, runtime,
  thermal/power state, background load, and measured resource/quality receipts
  are mandatory and remain separate per operating system.
- H8 execution is outside the minimal pilot plan and remains `DEFERRED` until
  the physical hosts and admission protocol exist.

### 5.5 P32-OPS — production/backend operations profile

- Used only for admitted PostgreSQL/object-storage/PITR, multi-service fault
  injection, or corpora that have a measured reason not to fit L16-DEV.
- Host shape, immutable container digests, database/object-store
  configuration, full SUT boundary, concurrency, RPO/RTO tier, fault authority,
  backup custody, network, cleanup, and cost are preregistered.
- Production certification remains deferred when the operator lacks safe fault
  authority, complete surface inventory, or an independently recorded expected
  fingerprint.

Every result names one exact profile version. Cross-profile results may appear
side by side but are not presented as equal-cost comparisons.

## 6. Fair comparator architecture

### 6.1 Comparison divisions

The standard does not force retrieval components, complete agents, and hosted
products into one artificial interface:

| Division | Required public surface | What is compared |
|---|---|---|
| `COMPONENT-CLOSED` | Ingest plus ordered retrieval | Memory/retrieval substrate under a harness-owned reader, prompt, tokenizer, context assembly, and budget |
| `AGENT-CLOSED` | Observation/tool/action episode protocol | Memory-enabled agent under a harness-owned model policy and deterministic environment |
| `SYSTEM-OPEN` | Ingest plus final answer/action | Entrant-supplied model, scaffold, and memory as one end-to-end system |
| `HOSTED-OUTCOME` | Hosted ingest/query/action API | Observable outcomes, service latency, calls/tokens, and billed cost; no local compute-efficiency rank |

Results never move between divisions by relabeling. The preregistration fixes
division, adapter, reader/agent policy, model, budget, and exposed hooks before
fixture access.

### 6.2 Common protocol and closed component ABI

All calls use `protocol_version = "wmbs/0.1-draft"` and the same closed request
context:

```text
RequestContext {
  protocol_version, run_id, attempt_id, request_id, idempotency_key,
  sequence, deadline_utc, tenant_id, principal_id?, session_id?
}
```

The first implementation plan must freeze JSON Schemas for:

```text
negotiate(ClientHello) -> ServerHello
create_run(CreateRunRequest) -> CreateRunReceipt
ingest(IngestRequest{ordered_events[]}) -> IngestReceipt
retrieve(RetrieveRequest{query, observation_time, top_k}) -> RetrievalEnvelope
answer(AnswerRequest{question, observation_time, response_mode}) -> AnswerEnvelope
finalize(FinalizeRequest) -> FinalizeReceipt
```

`response_mode` is `normal` or `forced`. Forced answers exist only for
explicitly declared calibration diagnostics; normal-mode safety gates remain
authoritative.

Portable events contain:

```text
event_id, content, actor_label, event_time, ingestion_time,
valid_from?, valid_to?, content_sha256, modality_handle?, public_metadata
```

The harness stamps immutable `ingestion_time`, which is the portable
transaction-time observation. An entrant may not backdate it. `valid_from` and
`valid_to` describe the fact's effective interval when a module exercises
temporal semantics.

`IngestReceipt` returns one ordered status per event:

```text
event_id, outcome(accepted|deduplicated|rejected),
durability(acknowledged|not_acknowledged), evidence_handle?, error?
```

`RetrievalEnvelope` contains ordered, unique hits:

```text
rank, stable_item_id, score?, content_or_handle, evidence_handles[],
observed_at, provenance_status
```

`AnswerEnvelope` contains:

```text
answer_text?, abstained, confidence?, evidence_handles[],
action_handles[], adapter_metadata
```

Usage is never accepted as an unverified field inside an answer. The
harness-owned `FinalizeReceipt` binds measured calls, tokens, CPU/RSS/disk,
network, storage, latency, retries, errors, and output digests to the attempt.

Every error is a closed `ErrorEnvelope` with:

```text
code, retriable, message, details_sha256?
```

The exact initial error enum is `INVALID_REQUEST`, `UNSUPPORTED_OPERATION`,
`UNAUTHORIZED`, `CONFLICT`, `ORDER_VIOLATION`, `DEADLINE_EXCEEDED`,
`RESOURCE_LIMIT`, `DEPENDENCY_UNAVAILABLE`, and `INTERNAL_ERROR`. Unknown
codes fail closed. Schemas fix ordering, maximum sizes, retry/idempotency
behavior, cancellation, deadline semantics, and whether partial writes are
acknowledged.

In `COMPONENT-CLOSED`, the harness alone invokes the pinned reader. A system
that exposes only final answers participates in `SYSTEM-OPEN` or
`HOSTED-OUTCOME`; it cannot claim fixed-reader comparability.

### 6.3 Closed agent ABI

`AGENT-CLOSED` requires a deterministic environment protocol:

```text
reset(EpisodeManifest) -> Observation
observe(EpisodeContext) -> Observation
act(ActionEnvelope{tool_name, canonical_arguments}) -> ActionReceipt
finish_episode() -> EpisodeReceipt
```

The manifest freezes tool schemas, state digest, seed, maximum turns/calls/
tokens, deadlines, allowed effects, and final-state assertions. The harness
owns the model policy in the closed division. Bring-your-own-agent outcomes
belong in `SYSTEM-OPEN`. M14 remains deferred until this ABI and one
deterministic simulator are implemented.

### 6.4 Advanced capability hooks

An adapter declares each hook `native`, `emulated`, or `unsupported`:

```text
update(selector, replacement)
delete(selector, mode=reversible|declared_surface_erasure)
restore(delete_receipt)
query_as_of(question, valid_time, transaction_time)
query_with_evidence(question)
create_principal / grant / revoke / query_as
schedule / update_intention / cancel / tick
working_put / working_query / working_expire / working_promote
export / import
state_digest / snapshot / restore_snapshot
health / queue_state
```

Each hook receives `RequestContext` and returns a versioned receipt. Emulation
uses only documented public operations and all added model calls, storage,
latency, and cost count. Unsupported hooks remain visible and prevent only the
profile label that requires them. A benchmark never invents an API on a
competitor's behalf or treats missing private internals as a failed outcome.

### 6.5 Trust boundaries, sandboxing, and metering

The benchmark treats entrant adapters, retrieved content, hosted responses,
media, and upstream artifacts as untrusted.

| Boundary | Required control |
|---|---|
| Entrant adapter → runner | Unprivileged ephemeral process/container; read-only staged inputs; closed output schemas; no host home, repository, Docker socket, signing key, or grader mount |
| Adapter → network/model | Default-deny egress; only preregistered endpoints through a harness-owned metering proxy; DNS/IP/protocol allowlist; no cloud metadata/private ranges |
| Held-out data/scorer → adapter | Gold and scorer execute in a separate process/trust domain; only public observations cross the boundary |
| Result → signing/publication | Canonical payload validated before a separate signing service; adapter never accesses keys or publication credentials |
| Media/path inputs → adapter | Content-addressed harness-local handles with digest, MIME, size, rights, and decoder policy; no entrant-selected URL or host path |

The sandbox pins UID/GID, mounts, environment allowlist, syscalls where
available, CPU/memory/process/file/output limits, wall deadline, egress,
locale/timezone, and cleanup. Logs redact secrets and direct personal data.
Termination produces a ledgered failed/aborted attempt rather than a missing
record. Harness metering covers the full declared SUT boundary and provider
calls; entrant self-reported usage is disclosure only.

## 7. Capability and live-requirement traceability

### 7.1 Proposed twenty-four-capability taxonomy

| ID | Capability | Comparison posture | Primary modules | Live authority |
|---|---|---|---|---|
| C01 | Capture and normalization | Universal outcome | M01, M02 | BENCH-001/002; RAIL-001/002 |
| C02 | Durable persistence and replayable projections | Advanced conformance | M01, M15, M17 | REPRO-001; RAIL-001 |
| C03 | Semantic, lexical, graph, and temporal retrieval | Closed-component outcome; route mechanism disclosed | M02 | BENCH-003/004/005; CAP-001/003 |
| C04 | Temporal evolution and bitemporal `as_of` | Universal outcome plus advanced hook | M03 | RAIL-001 |
| C05 | Correction, contradiction, multi-hypothesis belief, branch/merge | Outcome; branch/merge unsupported until a hook exists | M04 | RAIL-001 |
| C06 | Provenance, citation, explanation, and audit lineage | Advanced conformance | M05, M20 | CAP-002; REPRO-001; RAIL-001/003 |
| C07 | Entities, relations, preferences, user models, and procedures | Outcome plus disclosure | M02, M14 | CAP-001/008/009/010 |
| C08 | Consolidation, reflection, and test-time learning | Advanced outcome; mechanism disclosed | M06, M14 | CAP-007/008/009/010 |
| C09 | Retention, rehearsal, decay, fidelity demotion, and pruning | Advanced outcome; mechanism disclosed | M07 | CAP-007 |
| C10 | Reversible forgetting and tombstoning | Advanced outcome | M08 | RAIL-001 |
| C11 | Declared-surface irreversible erasure and residue control | Mandatory gate for erasure claims; not legal compliance | M09 | RAIL-001 |
| C12 | Calibrated uncertainty and abstention | Universal outcome | M10 | CAP-002/005 |
| C13 | Prospective memory and deferred action | Advanced outcome | M12 | CAP-012 |
| C14 | Working and session memory | Advanced outcome | M13 | CAP-013 |
| C15 | Retrieved-content safety, trust, and write authority | Advanced safety gate | M11 | CAP-004; RAIL-001/004 |
| C16 | Authentication, authorization, tenant/user/group isolation | Advanced safety gate | M11 | RAIL-001 |
| C17 | Determinism, reproducibility, and replay | Universal run property | M15, M20 | BENCH-001/002/003/007; REPRO-001/002; RAIL-003/004 |
| C18 | Backend parity and portability | Scoped release gate | M16 | CAP-011; RAIL-001 |
| C19 | Operational custody, queues, retries, backup/restore, and recovery | Advanced operational gate | M17 | RAIL-001 |
| C20 | Agent-facing ABI, MCP/CLI transports, and interchange | Scoped conformance | M16, M18 | BENCH-001/006; RAIL-001 |
| C21 | Multimodal evidence and custody | Advanced outcome | M19 | Future requirement; currently deferred |
| C22 | Public result contract, ledger, rendering, and publication | Standard infrastructure | M20 | GOV-001; LEAD-001/002/003 |
| C23 | End-to-end task and procedural utility | Closed-agent/open-system outcome | M14 | BENCH-006; CAP-008/009/010 |
| C24 | Efficiency, scale, and resource behavior | Mandatory report dimension, not one score | M01–M19 | CAP-006/011 |

The taxonomy is proposed, not proof of complete construct coverage. Internal
mechanisms such as graph routing, consolidation, rehearsal, cartridges, or
activation-space memory are disclosures unless an objective public outcome can
identify them without private signals. Group/multi-party memory, language and
domain diversity, and external-validity limits remain explicit research gaps.

### 7.2 Live requirement matrix

Status below is copied from `.planning/REQUIREMENTS.md` at the
`origin/main@489e1361` hardening cutoff; this document does not promote it.

| Requirement | Current status | Standard trace | Hardening disposition |
|---|---|---|---|
| BENCH-001 | Complete | M01/M15/M20; public CLI/bundle substrate | Reuse; do not replace |
| BENCH-002 | Complete | All official adapters; M15/M20 | Reuse registry pins and bundle fingerprints |
| BENCH-003 | Complete | M02/M20 | Preserve separate retrieval and QA families |
| BENCH-004 | Complete | M02 | Existing LongMemEval retrieval remains authoritative |
| BENCH-005 | Partial | M02/M05/M10/M16/M20 | Production parity and reader EM/F1 remain open |
| BENCH-006 | Planned | M02/M06/M14/M15/M20 | MemoryAgentBench and BEAM source work does not equal execution or results |
| BENCH-007 | Planned | M15/M20 | Scheduled regression-only CI; never tune on held-out data |
| REPRO-001 | Planned | M15/M20 | Pilot defines minimal manifest, canonical payload, and verifier extension |
| REPRO-002 | Planned | M15/M20 | One-command reproduction by construction; independent reproduction is strengthening evidence |
| CAP-001 | Partial | M02/M05/M14 | Grounded multi-hop source exists; measured closure remains open |
| CAP-002 | Partial | M05/M10 | Evidence-CID grounding and abstention retain frozen rails |
| CAP-003 | Partial | M02/M05/M10/M16 | Existing 0.85 QA target and no-recall-regression requirement remain controlling |
| CAP-004 | Planned | M11/M20 | Security column; not in minimal pilot plan |
| CAP-005 | Planned | M10/M20 | Calibration pilot emits only admitted metrics |
| CAP-006 | Planned | C24/M02/M14/M16/M20 | Requires measured warm/concurrent P95 and 100k behavior |
| CAP-007 | Planned | M03/M06/M07 | Multi-timescale/sleep consolidation; later stage |
| CAP-008 | Planned | M02/M06/M11/M14 | Map-reduce and surprise-gated write outcomes; later stage |
| CAP-009 | Planned | M02/M16/C24 | Cartridge research disclosure and bounded A/B; later research |
| CAP-010 | Planned | Research-deferred; inherits M05/M11/M15/M20 if adopted | No honest direct module yet |
| CAP-011 | Planned | H8 physical profile, M15/M16/C24 | Physical 8 GiB Windows/Linux gate is distinct from L16-DEV |
| CAP-012 | Complete | M12/M11/M16 | Reuse prospective implementation; benchmark proof remains separate |
| CAP-013 | Complete | M13/M11/M16 | Reuse working-memory implementation; benchmark proof remains separate |
| GOV-001 | Partial | M20/§13 | Source-owned operator model active; policy conflict blocks stronger labels |
| LEAD-001 | Partial | M15/M20 | Result contract and ledger exist; real runs/declarations/artifacts remain open |
| LEAD-002 | Partial | M20 | Validation/render/publication code exists; measured dimensions/site remain open |
| LEAD-003 | Partial | M20 | Readiness admission exists; real launch and human approval remain open |
| RAIL-001 | Continuous | Every module | All product invariants and test classes are non-waivable |
| RAIL-002 | Continuous | Harness and every adapter | Heavy benchmark/model dependencies stay optional or isolated |
| RAIL-003 | Continuous | M02/M15/M20 | No headline without pinned bundle, separate families, judge disclosure, and reproduction by construction |
| RAIL-004 | Continuous | Every data/scoring module | Private suites stay internal; held-out/test data never drives tuning |

### 7.3 Current-goal boundary

At this revision `GOAL.md` still records the Phase 13 P13-BEAM-B reader/judge
configuration contract and a stale `main@2834834a` baseline with unchecked
push/merge steps, although current main already contains the merged source.
This documentation lease does not rewrite that owner record. Its recorded
lease is limited to `GOAL.md`,
`eval/public/adapters/beam.py`, `tests/test_public_beam.py`, and
`docs/plans/2026-07-26-phase13-beam-adapter.md`. This standard does not absorb
that lease, treat the stale checklist as implementation truth, change
BENCH-006 status, run BEAM, or claim a result. BEAM maps to M02 retrieval/QA,
C24 resource reporting, M15 replay, and M20 disclosure; MemoryAgentBench maps
to M02/M04/M06/M14.

### 7.4 Inherited functional and safety rails

The following existing gates are minima, not comparison targets:

| Canonical owner | Inherited gate |
|---|---|
| `M-DEDUP-EXACT` | Exact duplicate materialization is zero; dedup accuracy is 1.0 |
| `M-ASOF-ACC` | Bitemporal as-of accuracy is 1.0 |
| `M-NODEGRADE` | Paired no-degradation confidence-interval lower bound is at least zero |
| `M-PROTECTED-REG` | Protected-memory regressions are zero |
| `M-ECE` | ECE is at most 0.05 where numeric confidence is supported |
| `M-ABST-PREC` | Confident-confabulation rate on the unanswerable split is zero; precision/AURC remains otherwise governed by its canonical posture |
| `M-POISON-BLOCK` and `M-BENIGN-DROP` | Poison block is at least 0.95 and untrusted-to-system-instruction remains absolute zero; benign-drop is the mandatory non-regression companion |
| `M-AUDIT-COMPLETE` | Every write has a complete audit record; score is 1.0 |
| `M-ERASURE` | Recoverable residue on declared evaluated surfaces is zero; score is 1.0 |
| `M-PARITY` | Gating deterministic behavioral/error/authorization parity is 1.0 |
| `M-PROV-COMPLETE` and `M-EXPLAIN-COV` | Durable factual provenance completeness and required explanation coverage are both 1.0 |
| Master-design security gate | Critical tenant/user isolation failures are zero |

Diagnostic graded metrics may be reported beside these gates. They cannot turn
a rail failure into conformance, certification, or a positive aggregate.

## 8. Module feasibility specifications

Every module below starts `PROPOSED`. A frozen canonical rail is binding where
named; every other numeric threshold or resource ceiling is a planning
hypothesis until a calibration or measured-resource receipt admits it. Only
M01, M03, M10, M12, M13, M15, and M20 are in the first reference-harness
pilot. The other modules remain design coverage, not implementation scope.

### M01 — Capture and durability

- **Contract:** universal `create_run`, `ingest`, and `finalize`; advanced
  `snapshot`/`restore_snapshot` when supported.
- **Data:** deterministic generator for 10,000 mixed text events with 5%
  exact duplicates, 5% near duplicates, malformed records, monotonic event
  IDs, and seeded crash points. A 100,000-event official variant remains
  deferred until its calibration and measured resource receipt exist.
- **Scorer:** acknowledged-write loss, duplicate materialization, accepted/
  rejected schema counts, provenance-field retention, and replay digest.
- **Acceptance:** zero acknowledged-write loss; exact-duplicate
  materialization zero (`M-DEDUP-EXACT=1.0`); 100% schema/provenance-field
  retention; and byte-identical canonical payloads in deterministic mode.
- **Repeat/replay:** five clean runs plus one crash/restart replay; canonical
  event order, fixture manifest, and SHA-256 payload digest.
- **Resource prerequisite:** the first implementation may target the proposed
  L16-DEV ceiling of 20 minutes, 4 GiB peak RSS, 2 GiB disk, and two workers,
  but admission requires an external-meter receipt from the declared profile.
- **External dependencies:** none for Local/SQLite. PostgreSQL crash testing is
  P32 and requires pinned Docker images.
- **Deferral:** defer only the P32 variant when Docker/host preflight fails;
  reject any adapter that cannot return an ingest receipt.
- **Feasibility disposition:** `PROPOSED`; eligible for the L16-DEV pilot
  after the common ABI, metadata pass-through, sandbox, scorer golden vectors,
  and resource receipt exist. P32 remains `DEFERRED`.
- **Placement:** universal ingestion result; release/operations extension for
  crash durability.

### M02 — Retrieval and organization

- **Contract:** universal `ingest`, `retrieve`, and `answer`.
- **Data:** public adapters for LoCoMo, LongMemEval, LongMemEval-V2, and
  HippoRAG-compatible multi-hop sets where licensing permits; deterministic
  2,000-event local corpus with exact, paraphrase, entity, relation, multi-hop,
  and unanswerable queries.
- **Scorer:** answer EM/F1, Recall@K, nDCG@K, evidence recall when IDs exist,
  unsupported-claim rate, latency, tokens, calls, and storage.
- **Acceptance:** public comparison has no quality-based admission floor.
  Improvement claims require the paired confidence-interval lower bound to be
  above zero versus the named baseline; non-inferiority claims use a
  preregistered two-percentage-point margin.
- **Repeat/replay:** deterministic retrievers once plus clean-process replay;
  stochastic answer models at least five preregistered seeds with paired
  bootstrap confidence intervals.
- **Resource prerequisite:** a measured receipt must establish an admitted
  profile; 45 minutes, 8 GiB peak RSS, 8 GiB disk, and four workers is only an
  L16-DEV planning hypothesis.
- **External dependencies:** official datasets and a pinned answer model for
  official QA; local conformance needs neither.
- **Deferral:** an official adapter is `DEFERRED` until its dataset revision,
  license, split digest, and scorer are pinned. Synthetic results cannot use
  the official suite name.
- **Feasibility disposition:** `PROPOSED` for the deterministic local corpus;
  each official adapter is `DEFERRED` until the exact baseline, dataset,
  rights, environment, and scorer manifests exist. M02 is not in the first
  pilot.
- **Placement:** universal public comparison.

### M03 — Temporal evolution

- **Contract:** universal `ingest` plus `retrieve`/`answer`. Native bitemporal
  conformance additionally requires portable-event `valid_from`/`valid_to`,
  harness-stamped `ingestion_time`, and the Section 6 `query_as_of` hook;
  natural-language temporal QA is a separate comparison cell.
- **Data:** seeded timelines containing ordered and late events, valid-time
  versus ingestion-time differences, retroactive corrections, and historical
  questions.
- **Scorer:** current-state accuracy, historical accuracy, stale-fact leakage,
  interval correctness when disclosed, and update-to-query latency.
- **Acceptance:** exact current-state and as-of reconstruction
  (`M-ASOF-ACC=1.0`), zero stale-current leakage, and 100% deterministic
  tie-policy replay. Natural-language answer quality is reported separately
  and needs a calibrated comparison threshold before ranking.
- **Repeat/replay:** five deterministic timelines across at least five seeds;
  exact event/query order and virtual-clock state retained.
- **Resource prerequisite:** measured admission receipt; 20 minutes, 4 GiB
  RSS, 1 GiB disk, and two workers is an L16-DEV planning hypothesis.
- **External dependencies:** none.
- **Deferral:** never read private validity tables. Mnemosyne's pilot is
  `DEFERRED` until a narrow public valid-time/as-of surface exists; systems
  without that surface may still enter the natural-language outcome cell and
  disclose native bitemporal support as `unsupported`.
- **Feasibility disposition:** `PROPOSED`; pilot admission is conditional on
  the public temporal contract and golden vectors.
- **Placement:** universal public comparison; native bitemporal certification
  is advanced.

### M04 — Conflict and correction

- **Contract:** universal `ingest`, `retrieve`, and `answer`; the exact
  Section 6 `update` hook is optional.
- **Data:** seeded independent, duplicated, low-quality, high-quality,
  malicious, unresolved, and later-resolved conflicting sources.
- **Scorer:** correct current answer, preserved historical answer, calibrated
  unresolved state, false supersession, and source-ablation sensitivity.
- **Acceptance:** 100% preservation of superseded history, at most 1% false
  high-confidence resolution, and no monotonic-source-policy violation.
- **Repeat/replay:** three source-order permutations per case and at least
  five seeds.
- **Resource prerequisite:** measured admission receipt; the former L16
  numbers are not an admitted profile.
- **External dependencies:** none.
- **Deferral:** reject scoring based on Mnemosyne-specific trust-tier labels;
  the gold defines only observable source reliability and expected outcome.
- **Feasibility disposition:** `PROPOSED`; branch/merge subcapabilities are
  `UNSUPPORTED-BY-SYSTEM` unless an entrant exposes a public contract.
- **Placement:** universal public comparison and internal regression.

### M05 — Provenance and explanation

- **Contract:** `query_with_evidence` or optional `evidence_ids` in the answer
  envelope. Systems without either are `unsupported`.
- **Data:** deterministic claims requiring one or more source events,
  distractors, derived claims, and tampered lineage records.
- **Scorer:** citation precision/recall, claim coverage, unsupported-claim
  rate, lineage tamper detection, and explanation consistency.
- **Acceptance:** exact required claim-to-source grounding
  (`M-PROV-COMPLETE=1.0`) and attribution coverage
  (`M-EXPLAIN-COV=1.0`), zero unsupported claims for the protected slice, and
  100% rejection of tampered lineage. Citation precision/recall remains a
  diagnostic on non-protected material.
- **Repeat/replay:** at least five seeds; canonical citation order does not
  affect set metrics; signed source manifest retained.
- **Resource prerequisite:** measured admission receipt; the former L16
  numbers are planning hypotheses only.
- **External dependencies:** none.
- **Deferral:** defer explanation faithfulness if no objective claim-to-source
  alignment scorer exists; citation scoring remains runnable.
- **Feasibility disposition:** `PROPOSED` for citation/lineage scoring;
  explanation-faithfulness scoring is `DEFERRED` until objective alignment is
  demonstrated. M05 is not in the first pilot.
- **Placement:** advanced public certification.

### M06 — Consolidation and learning

- **Contract:** universal `ingest`, `retrieve`, and `answer` across episodes;
  no private consolidation API is required.
- **Data:** deterministic repeated, corroborated, contradictory, procedural,
  related-transfer, and unrelated-control episodes.
- **Scorer:** utility delta against no-consolidation/no-memory controls,
  harmful promotion, compounding-error rate, cross-episode transfer, storage,
  and cost.
- **Acceptance:** utility-improvement confidence-interval lower bound above
  zero and canonical no-degradation lower confidence bound at least zero, with
  zero protected regressions. Harmful-promotion and unrelated-task thresholds
  require preregistered calibration.
- **Repeat/replay:** five cycles per case and at least five seeds, with a real
  public no-consolidation control when supported; otherwise use the universal
  no-memory control and disclose the missing ablation.
- **Resource prerequisite:** measured admission receipt; provider-backed
  variants also inherit the declared provider budget.
- **External dependencies:** none for deterministic local roles; official
  MemoryAgentBench/EvoMemBench adapters require pinned upstream data/models.
- **Deferral:** official variants defer when upstream data/scoring cannot be
  reproduced; a no-consolidation comparison defers when it cannot be exercised
  through a public control.
- **Feasibility disposition:** `PROPOSED`; official
  MemoryAgentBench/EvoMemBench variants are `DEFERRED` until pinned. M06 is not
  in the first pilot.
- **Placement:** advanced public outcome plus release non-degradation gate.

### M07 — Retention, rehearsal, and decay

- **Contract:** universal `ingest`, `retrieve`, and `answer` with a
  harness-owned virtual clock.
  Timestamped events alone do not prove time progression; an adapter must
  expose or faithfully emulate the clock through its public boundary and
  disclose the method.
- **Data:** seeded months-long virtual timelines with protected facts,
  high/low-utility items, repeated access, spacing schedules, stale facts, and
  storage pressure.
- **Scorer:** protected-item survival, stale-item retention, retrieval quality,
  storage growth, rehearsal cost, and unrelated-item interference.
- **Acceptance:** protected-item survival 1.0, zero protected regressions, and
  storage/cost reported as a Pareto frontier rather than hidden in a quality
  score. All other retention thresholds require calibration.
- **Repeat/replay:** at least five virtual-calendar seeds; no wall-clock
  sleeps.
- **Resource prerequisite:** measured admission receipt; no asserted L16
  budget.
- **External dependencies:** none.
- **Deferral:** reject any design that requires real-month waiting or an
  unbounded corpus; virtual time and bounded event counts are mandatory.
- **Feasibility disposition:** `PROPOSED`; not in the first pilot.
- **Placement:** advanced public outcome and internal lifecycle regression.

### M08 — Reversible forgetting

- **Contract:** Section 6 `delete(selector, mode=reversible)` plus
  `retrieve`/`answer`; adapters may expose `restore(delete_receipt)`.
- **Data:** deterministic selective-forget cases followed by exact, paraphrase,
  multi-hop, re-ingestion, unrelated-control, and optional restore probes.
- **Scorer:** direct and semantic leakage, false removal, unrelated utility
  loss, restore correctness, and re-ingestion contamination.
- **Acceptance:** zero exact-canary leakage, semantic leakage at most 1%,
  unrelated utility loss at most 0.5 percentage points, and 100% restore
  correctness when restore is claimed.
- **Repeat/replay:** at least five seeds, two delete/re-ingest cycles, and
  canonical canary digests.
- **Resource prerequisite:** measured admission receipt.
- **External dependencies:** none.
- **Deferral:** systems without a reversible-delete operation are
  `unsupported`; they are not scored zero.
- **Feasibility disposition:** `PROPOSED` for adapters exposing the hook;
  otherwise `UNSUPPORTED-BY-SYSTEM`. M08 is not in the first pilot.
- **Placement:** advanced public capability.

### M09 — Declared-surface erasure conformance

- **Contract:** Section 6
  `delete(selector, mode=declared_surface_erasure)`, `retrieve`/`answer`, and
  declared `snapshot`/`restore_snapshot` surfaces.
- **Data:** deterministic identity-linked evidence, derivatives, indexes,
  caches, intentions, working state, unrelated tenant controls, and restore
  probes.
- **Scorer:** direct residue, semantic leakage, false deletion, unrelated
  mutation, completion SLA, and signed receipt validity.
- **Acceptance:** zero recoverable residue on every declared surface, zero
  unrelated mutation, 100% valid signed receipts, and zero attributable
  semantic leakage where the gold can objectively tie the leaked fact to the
  erased subject. Passing is technical conformance for declared surfaces, not
  a legal-compliance opinion.
- **Repeat/replay:** three delete-operation IDs, retry after each injected
  crash boundary, and one restore pass for every declared readable snapshot.
- **Resource prerequisite:** measured local or P32 receipt for the exact
  declared surfaces.
- **External dependencies:** Docker/P32 only for production replicas, object
  storage, and full PITR.
- **Deferral:** no erasure certification if any declared readable surface
  cannot be probed, backup scope is undisclosed, or identity authorization
  cannot be exercised. Unsupported systems receive no erasure claim.
- **Feasibility disposition:** `PROPOSED` for Local/SQLite declared surfaces;
  P32 replicas/object storage/PITR are `DEFERRED`. M09 is not in the first
  pilot.
- **Placement:** mandatory pass/fail gate for legal-erasure claims.

### M10 — Calibration and abstention

- **Contract:** universal `answer` with required `abstained`; numeric
  confidence is optional.
- **Data:** balanced answerable, unanswerable, contradictory, distribution-
  shifted, and adversarial questions drawn from the same event generator as
  M02–M04.
- **Scorer:** assertion accuracy, abstention precision/recall, risk-coverage,
  ECE/Brier when confidence exists, and useful coverage at fixed risk.
- **Acceptance:** in normal mode, zero confident assertions on canonical
  unanswerables and `ECE <= 0.05` when numeric confidence is supported. A
  preregistered useful-coverage floor or baseline comparison is mandatory so
  “always abstain” cannot pass. Forced-answer mode is diagnostic only.
- **Repeat/replay:** at least five seeds; fixed bins and bootstrap method;
  judge-free gold where possible.
- **Resource prerequisite:** measured admission receipt; 20 minutes, 4 GiB
  RSS, and 1 GiB disk is an L16-DEV planning hypothesis.
- **External dependencies:** none for deterministic answers; X16 for official
  judged QA.
- **Deferral:** numeric calibration metrics are `unsupported` without
  confidence, but abstention outcomes remain universal.
- **Feasibility disposition:** `PROPOSED`; eligible for the first pilot after
  the coverage floor/baseline and normal/forced response modes are frozen.
  Numeric-confidence submetrics are `UNSUPPORTED-BY-SYSTEM` when omitted.
- **Placement:** universal public comparison.

### M11 — Security and isolation

- **Contract:** advanced `create_principal`/`grant`/`revoke`/`query_as` plus
  normal `ingest`, `retrieve`, and `answer`. A simpler per-scope adapter may
  participate if it can create isolated principals.
- **Data:** deterministic multi-principal workloads, forged identities,
  cross-tenant canaries, prompt injection, poison memories, capability
  escalation attempts, and benign controls.
- **Scorer:** unauthorized disclosure/write, authorized utility, attack
  persistence, recovery, and benign false-positive cost.
- **Acceptance:** zero unauthorized reads or writes and zero untrusted
  retrieved-content tokens entering a system instruction. Authorized utility
  is reported against the benign control but cannot average away a protected
  failure.
- **Repeat/replay:** at least five seeds and two principal-order permutations;
  all attack payloads and allowed outcomes are digest-pinned.
- **Resource prerequisite:** measured admission receipt.
- **External dependencies:** none for local auth simulation; external OIDC is a
  separate P32 certification variant.
- **Deferral:** systems without principal isolation are `unsupported`; no
  security certification is awarded. Do not emulate auth by inspecting
  private storage.
- **Feasibility disposition:** `PROPOSED` for internal local-principal
  conformance; native authorization is required for a public security claim.
  OIDC/P32 remains `DEFERRED`. M11 is not in the first pilot.
- **Placement:** mandatory pass/fail gate for security/isolation claims.

### M12 — Prospective action

- **Contract:** advanced `schedule`, `update_intention`, `cancel`, and
  virtual-clock `tick` requests with typed identifiers, trigger definition,
  authorization context, revision, and idempotency key. Every firing targets a
  harness-owned idempotent sink. Emulation is allowed only through public
  tools and is fully costed.
- **Data:** deterministic exact-time, window, event, condition, dependency,
  recurrence, cancellation, negative, implicit, and overloaded-trigger cases.
- **Scorer:** precision/recall/F1, false alarms, missed triggers, lateness,
  duplicate execution, cancellation correctness, and cost.
- **Acceptance:** zero duplicate execution, zero cancelled-intention
  execution, and a preregistered absolute recall/F1 floor plus non-inferiority
  margin versus the exact reference baseline. The floor and margin must be
  calibrated before ranking.
- **Repeat/replay:** at least five virtual-week seeds; no real payload
  execution.
- **Resource prerequisite:** measured admission receipt; 30 minutes, 4 GiB
  RSS, and 1 GiB disk is an L16-DEV planning hypothesis.
- **External dependencies:** local generator has none; official PM-Bench and
  TriggerBench variants require pinned upstream revisions.
- **Deferral:** official labels defer until upstream fixtures and scorers are
  licensed and pinned. Systems without action hooks are `unsupported`.
- **Feasibility disposition:** `PROPOSED`; eligible for the first pilot only
  after recurrence, cancellation, exact-once sink, calibrated baseline, and
  golden vectors exist. Existing PM-Bench/TriggerBench probes are
  development-only; official variants remain `DEFERRED`.
- **Placement:** advanced public action certification.

### M13 — Working memory

- **Contract:** advanced `working_put`, `working_query`, `working_expire`, and
  `working_promote` requests, or an exactly mapped public equivalent, with
  session, tenant, expiry, and idempotency fields.
- **Data:** deterministic items under capacity pressure, expiry, interruption,
  explicit promotion, deletion, and cross-session/tenant distractors.
- **Scorer:** active recall, expiry correctness, scope leakage, promotion
  utility, and stale-item interference.
- **Acceptance:** zero cross-session/tenant leakage, expiry correctness 1.0,
  and preregistered active-recall/capacity floors plus a promotion-versus-
  no-promotion control. The quality floors require calibration before ranking.
- **Repeat/replay:** at least five seeds and at least three capacity settings.
- **Resource prerequisite:** measured admission receipt; 15 minutes, 4 GiB
  RSS, and 1 GiB disk is an L16-DEV planning hypothesis.
- **External dependencies:** none.
- **Deferral:** systems without a distinct session/working scope are
  `unsupported`; do not infer failure from a long-term-only API.
- **Feasibility disposition:** `PROPOSED`; eligible for the first pilot after
  multi-seed/capacity golden vectors and the promotion control exist. Systems
  without the scope are `UNSUPPORTED-BY-SYSTEM`.
- **Placement:** advanced public capability and internal regression.

### M14 — Procedural task utility

- **Contract:** the Section 6.3 `reset`/`observe`/`act`/`finish_episode`
  protocol connected to a deterministic sandboxed task environment;
  bring-your-own-agent is a separate track.
- **Data:** local stateful support/travel/shopping-style tasks with repeated,
  structurally related, novel, and unrelated controls; official STATE-Bench
  and EvoMemBench adapters when pinned.
- **Scorer:** deterministic final-state assertions, procedure compliance,
  pass@1, pass^5, turns, tool calls, tokens, cost, and secondary UX rubric.
- **Acceptance:** improvement claims require a paired confidence-interval
  lower bound above zero versus no-memory and the inherited no-degradation
  lower bound at least zero on unrelated/novel tasks; zero protected
  regressions. Pass^5, cost, and UX remain separately visible.
- **Repeat/replay:** five runs per task for reliability; paired no-memory
  control; simulator seed and rule digest retained.
- **Resource prerequisite:** measured receipt for the exact task simulator and
  model policy.
- **External dependencies:** official tasks may require X16 models and upstream
  environments.
- **Deferral:** official variants defer when their simulator/model contract
  cannot be pinned within the preregistered budget. Deterministic state scoring
  remains required.
- **Feasibility disposition:** `DEFERRED` until the deterministic simulator,
  protocol, paired control, and scorer are pinned; official
  STATE-Bench/EvoMemBench variants are also `DEFERRED`. M14 is not in the
  first pilot.
- **Placement:** universal public task-utility track.

### M15 — Determinism and replay

- **Contract:** applies to every admitted adapter and run bundle.
- **Data:** a representative fixed cassette drawn from M01–M14.
- **Scorer:** byte-identical canonical payloads for declared deterministic
  mode; metric variance and seed coverage for stochastic mode. Volatile wall
  time, RSS samples, signatures, paths, and runtime timestamps are retained as
  evidence but excluded from the canonical equality projection.
- **Acceptance:** 100% byte equality for every declared canonical payload.
  Stochastic results require every seed and confidence interval; missing replay
  metadata is a hard publication failure.
- **Repeat/replay:** five identical runs plus one clean-process restart/replay.
- **Resource prerequisite:** measured admission receipt; 20 minutes, 4 GiB
  RSS, and 2 GiB disk is an L16-DEV planning hypothesis.
- **External dependencies:** none.
- **Deferral:** no public result if the adapter cannot emit a complete run
  manifest, seed record, and canonical artifacts. Stochastic operation is not
  a deferral if variance is honestly measured.
- **Feasibility disposition:** `PROPOSED`; eligible for the first pilot after
  the canonical projection, five-run cassette, and clean-process reproduction
  are frozen.
- **Placement:** universal release and publication property.

### M16 — Backend and transport parity

- **Contract:** same public cassette through each declared backend and each
  CLI/MCP transport.
- **Data:** bounded capture/query/correct/forget/prospective/working/security
  conformance cases shared with other modules.
- **Scorer:** semantic output equality, error class, authorization outcome,
  migration fidelity, and latency/cost delta.
- **Acceptance:** 100% deterministic semantic, error-class, and authorization
  equivalence. Non-byte-identical judged outputs remain diagnostic until an
  equivalence margin and powered comparison are calibrated.
- **Repeat/replay:** at least five runs per backend/transport pair.
- **Resource prerequisite:** a measured receipt for every executed
  backend/transport pair.
- **External dependencies:** PostgreSQL/hosted HTTP requires pinned Docker or
  P32.
- **Deferral:** defer only unavailable backend pairs; never generalize
  Local/SQLite parity into a PostgreSQL claim.
- **Feasibility disposition:** `PROPOSED` for Local/SQLite/local MCP;
  PostgreSQL/hosted HTTP is `DEFERRED`. M16 is not in the first pilot.
- **Placement:** internal release gate; public portability disclosure.

### M17 — Custody and recovery

- **Contract:** advanced `health`/`queue_state`/`snapshot`/
  `restore_snapshot` plus normal operations.
- **Data:** deterministic queue redelivery, partial outage, crash-after-commit,
  object loss, retry, backup, and PITR scenarios.
- **Scorer:** acknowledged loss, duplicate external effects, recovery
  completeness, RPO/RTO, audit continuity, and operator steps.
- **Acceptance:** zero acknowledged loss, zero duplicate externally visible
  effects, complete audit continuity, and an RPO/RTO tier frozen by the
  standard before the run; a submitter-selected target cannot certify itself.
- **Repeat/replay:** three crash points per scenario and two clean restores.
- **Resource prerequisite:** a measured local receipt or an admitted P32
  recovery receipt for the exact claimed surfaces.
- **External dependencies:** PostgreSQL/object-store/PITR requires P32 and
  pinned service images.
- **Deferral:** production certification defers when retained infrastructure,
  external custody, or an independently recorded expected fingerprint is
  absent. Local results cannot close production rows.
- **Feasibility disposition:** `PROPOSED` for local fault injection; P32
  recovery certification is `DEFERRED`. M17 is not in the first pilot.
- **Placement:** operator/internal certification.

### M18 — Interoperability

- **Contract:** advanced export/import with a versioned portable envelope;
  transport conformance uses public adapter schemas.
- **Data:** deterministic evidence, corrections, provenance, deletions,
  intentions, and unsupported-extension cases.
- **Scorer:** required-field preservation, semantic query delta before/after
  migration, rejection of unknown critical fields, and loss disclosure.
- **Acceptance:** 100% preservation of required fields and 100% rejection of
  unknown critical fields. Semantic delta remains diagnostic until an
  equivalence margin is calibrated and powered.
- **Repeat/replay:** three export orderings and two round trips.
- **Resource prerequisite:** measured receipts from at least two independent
  implementations for a public interoperability claim.
- **External dependencies:** at least two independently implemented adapters
  are required for public certification.
- **Deferral:** public interoperability certification defers until a second
  adapter exists; single-system round-trip remains an internal result.
- **Feasibility disposition:** `PROPOSED` for internal single-system
  round-trip; public certification is `DEFERRED` until a frozen envelope and
  second adapter exist. M18 is not in the first pilot.
- **Placement:** advanced public certification.

### M19 — Multimodal memory

- **Contract:** universal `ingest`, `retrieve`, and `answer` with an opaque,
  digest-bound `modality_handle`; raw host paths and entrant-controlled fetch
  URLs are forbidden. Evidence and deletion hooks are optional extensions.
- **Data:** small redistributable text/image/audio/video fixtures with
  cross-modal questions, provenance, distractors, and deletion canaries.
- **Scorer:** answer/evidence quality, cross-modal linkage, provenance,
  modality-specific leakage, latency, and storage.
- **Acceptance:** public comparison has no quality-based admission floor;
  improvement claims require a positive paired confidence-interval lower bound,
  while provenance and erasure claims inherit M05/M09 gates unchanged.
- **Repeat/replay:** at least five seeds; media files and derived
  representations are digest-pinned.
- **Resource prerequisite:** measured receipt for an admitted profile; no local
  generative model is assumed.
- **External dependencies:** official EMemBench or provider-backed media
  extraction is eligible only after pinned data/model and rights contracts.
- **Deferral:** official multimodal variants defer when media licensing,
  download stability, or model cost is not fixed. Text-only systems are
  `unsupported`, not failed.
- **Feasibility disposition:** `DEFERRED` because no complete redistributable
  fixture-rights manifest and portable media contract have been admitted.
  Text-only systems are `UNSUPPORTED-BY-SYSTEM`. M19 is not in the first
  pilot.
- **Placement:** advanced public capability.

### M20 — Publication integrity

- **Contract:** reuse `leaderboard/schema/result-v1.schema.json`,
  `leaderboard.validate`, `leaderboard.ledger`, `leaderboard.render`,
  `leaderboard.publish`, and `leaderboard.readiness` without reinterpreting
  signed v1 bytes. A new `result-v2` may add module/disclosure, safety-gate,
  resource, attempt, custody, and complete digest bindings through explicit
  version dispatch.
- **Data:** deterministic valid, tampered, duplicated, truncated, revoked,
  superseded, cyclic, and mismatched-fingerprint bundles.
- **Scorer:** valid acceptance, invalid rejection, exact digest replay,
  non-destructive history, and verifier exit status.
- **Acceptance:** 100% acceptance of valid bundles, 100% rejection of invalid
  bundles, exact digest replay, and no mutation of prior published history.
- **Repeat/replay:** five input orderings, two clean renders, and one
  interrupted publication.
- **Resource prerequisite:** measured admission receipt; 15 minutes, 2 GiB
  RSS, and 1 GiB disk is an L16-DEV planning hypothesis.
- **External dependencies:** local signing keys only; public hosting and human
  approval are separate publication acts.
- **Deferral:** v2 admission requires verification of build, config, bundle,
  and trace-index digests before rendering. Mixed v1/v2 rendering remains
  blocked until schema dispatch and cross-version supersession tests pass.
  Public release also defers without human approval and PBPP-complete custody.
- **Feasibility disposition:** v2 `admission_state` is `PROPOSED`; the existing
  v1 substrate has `evidence_level=IMPLEMENTED` but no implied v2 admission.
  Historical v1 ledger entries remain immutable; migration appends a linked v2
  supersession rather than rewriting history.
- **Placement:** mandatory standard infrastructure.

## 9. Scoring and reporting

### 9.1 Primary result: capability vector

Every result reports:

1. per-module outcome metrics and confidence intervals;
2. native/emulated/unsupported capability disclosures;
3. mandatory safety-gate status;
4. latency, wall time, tokens, API calls, storage, peak RSS, cost, and profile;
5. run variance, seeds, retries, and aborted runs;
6. exact adapter, system, model, prompt, dataset, container, and artifact
   digests.

No overall rank may hide a failed safety gate or an unsupported capability.

### 9.2 Composite status

No universal quality composite is specified or publishable in this revision.
Weighting, normalization, construct validity, sensitivity, and stakeholder
review are later research. The capability vector, mandatory gate failures, and
resource Pareto axes are the only auditable primary presentation. A future
composite requires a new version and may never average away a safety failure,
turn unsupported capability into zero quality, or mix comparison divisions.

### 9.3 Baselines

Every applicable module includes versioned no-memory, full/long-context,
canonical BM25, canonical vector, and submitted-system baselines run through
the same harness, reader/model policy, prompt, budget, data access, metering,
and scorer. Each manifest pins tokenizer, chunking, embedding model/revision,
dimensions, distance, retrieval parameters, reranker, ordering, truncation,
context assembly, cache policy, preprocessing, indexing command, and
setup/query cost. “BM25 or equivalent” is not a reproducible baseline.

### 9.4 Statistical and inferential contract

Before a result can rank or support a comparison claim, its preregistration
MUST define the primary estimand, independent unit, contrast, direction,
smallest meaningful effect, stopping rule, exclusions, retry policy, and
missing-output treatment.

- Sampled or stochastic point estimates use 95% intervals with 10,000
  bootstrap resamples. Paired comparisons use paired resampling; longitudinal
  tests use session/block resampling. A deterministic census of a finite
  declared corpus reports the exact numerator and denominator without a
  pseudo-population interval.
- Stochastic systems use at least five preregistered independent seeds/runs.
  Unchanged-system repeats establish the noise band.
- Sample size targets at least 80% power at two-sided alpha 0.05 for the
  meaningful effect, or a preregistered 95% interval half-width. Otherwise the
  result is descriptive and non-ranking.
- Binary safety gates use the appropriate one-sided 95% exact bound in
  addition to the observed rate. An observed zero alone is insufficient.
- Primary comparison families control family-wise error at 0.05, using Holm
  adjustment by default. Exploratory sweeps may use Benjamini-Hochberg FDR
  0.05 but remain non-gating.
- Missing primary outputs are failures unless the frozen scorer defines a more
  conservative rule. Aborted, retried, and discarded attempts remain in the
  ledger; best-of-run selection is prohibited.
- Effect sizes and intervals accompany p-values. A finite deterministic
  development corpus is reported as full-corpus conformance, not population
  inference.

### 9.5 Atomic result and comparison-projection contract

The signed ledger stores one immutable atomic attempt record per:

```text
system_id, system_version, adapter_id, adapter_version,
track_kind, benchmark_id, benchmark_version, module_id, division,
resource_profile, backend_id, hardware_fingerprint, model_policy_id,
dataset_split_digest, run_id, attempt_id, seed
```

`track_kind` is closed to `OFFICIAL-UPSTREAM`, `ENHANCED-SUCCESSOR`, or
`DEVELOPMENT`. An official record also binds the upstream protocol, dataset,
split, preprocessing, scorer, environment, and revision digests. A successor
record binds its parent official construct and a machine-readable difference
manifest. An atomic record carries raw outcomes, scorer outputs, safety gates,
resource measurements, retry/abort state, custody, and all artifact digests;
it never contains a cross-attempt or cross-system average.

Aggregates and comparison pages are reproducible projections over selected
atomic records, not new evidence or mutable ledger rows. A projection must
publish its filter, compatible-record set, exclusions, metric version and
unit, weighting formula, numerator/denominator, uncertainty method, missing
and unsupported counts, and source record IDs. It may compare or average only
records with compatible track, benchmark/scorer version, division, metric
semantics, and declared resource treatment. Backend, hardware, model policy,
and resource-profile differences remain visible grouping/filter dimensions;
they are never silently pooled.

The future website may provide side-by-side systems, filters, transparent
user-selected averages, confidence intervals, and cost/latency/RAM/hardware
views. Such user-selected averages are labeled exploratory, never official,
certified, or headline results. They must be exactly reproducible from the
listed atomic records. Official-upstream and enhanced-successor scores remain
separate even when a user selects both for one view.

Safety-gate failures are non-averageable. Any selected failed gate remains
prominent at the system, module, and attempt level and cannot be offset by
quality, coverage, efficiency, another backend, or another seed. Missing,
unsupported, failed, aborted, and not-measured are distinct states; none is
silently converted to zero or omitted from a denominator.

Detailed website information architecture, interaction design, and hosting
belong to a separate future specification. That surface is a read-only
projection of validated result/ledger/publication contracts and may not alter
their evidence semantics.

### 9.6 Cross-capability scenarios

Single-module tests are necessary but insufficient. The following scenarios
must use one event history and preserve every constituent rail:

| Scenario | Modules | Required joint outcome |
|---|---|---|
| Correction with evidence | M03/M04/M05 | current correction, historical reconstruction, and source lineage all remain exact |
| Retain, forget, erase | M07/M08/M09 | protected retention survives reversible forgetting while declared erasure leaves no recoverable residue |
| Learn without leaking | M06/M11/M14 | repeated-cycle utility improves without protected regression, tenant leakage, or unsafe retrieved instructions |
| Authorized future action | M11/M12/M17 | schedule/update/cancel/retry remains authorized, exactly once, and auditable across recovery |
| Working-to-long-term promotion | M10/M13/M16 | expiry, abstention, explicit promotion, isolation, and executed-path parity all hold |
| Recoverable public evidence | M15/M16/M17/M20 | replay, backend parity, recovery, and result/ledger bindings remain mutually consistent |

Until the relevant modules are admitted, each joint scenario is `DEFERRED`;
passing constituent smokes cannot imply joint conformance.

## 10. Anti-gaming and credibility controls

1. Preregister the SUT, division, adapter, model, prompt, budget, hardware,
   public hooks, estimands, exclusions, and stopping rule before held-out
   access. The SUT includes every entrant-controlled process, database, cache,
   worker, proxy, model/tool call, and pre/post-processing step.
2. Keep gold, graders, virtual clocks, and metering outside the SUT. Arbitrary
   entrant code runs in a fresh non-root, read-only, quota-limited sandbox with
   ephemeral storage, no host mounts, dropped capabilities, and deny-by-default
   egress except a preregistered allowlist. Record the image and policy digests.
3. Measure CPU/GPU time, wall time, peak memory, disk high-water/I/O, network
   bytes, API calls, tokens, retries, billed cost, setup/indexing,
   maintenance, and queries outside the SUT. Self-reports corroborate but do
   not replace the meter. Unmeterable systems are `resource-unverified` and
   cannot share a cost/performance rank.
4. Publicly release generators and scorers. Before candidate instances exist,
   freeze the sampling algorithm and derive the hidden seed from committed
   public randomness or an independent custodian. Ledger every candidate-
   selection event so the operator cannot test and discard unfavorable seeds.
   Only instances/seeds may be hidden, with a pre-access signed split/Merkle
   commitment, encrypted custody, access/runner logs, exposure history,
   retirement/reveal date, and leak response. Hidden runs block SUT egress and
   gold access.
5. Declare training, fine-tuning, and RAG exposure as `known-unexposed`,
   `declared-exposed`, or `unknown`, plus benchmark-specific tuning,
   authorship, and conflicts. Unknown remains visible.
6. Scan exact/near duplicates, canaries, search-time leakage, suspicious
   evidence paths, and anomalous results. Benchmark detection, input-specific
   answer encoding, gold access, and hidden-only code paths are prohibited.
7. Pair applicable runs with the exact versioned baselines in Section 9.3.
   No private no-consolidation or privileged internal signal may be used.
8. Ledger every attempt, including aborted, failed, retried, and discarded
   runs. Audit selection has random and cause-based components.
9. Include unanswerable, conflicting, poisoned, cross-tenant, deleted,
   overloaded-trigger, and benign-control cases, plus the cross-capability
   scenarios in Section 9.6.
10. Correct results only by signed supersession or revocation. A leak
    quarantines the affected round and produces a superseding record.
11. `Certification-held-out` requires a custodian independent of the
    entrant/vendor. Otherwise use `operator-held-out`; secrecy alone is not
    independence.
12. Disclose benchmark-author, adapter-author, vendor, judge, operator,
    custodian, reproducer, and maintainer conflicts of interest.

## 11. Open-source, rights, and provenance gates

- Benchmark code uses an OSI-approved license. Every dataset, fixture, model,
  adapter, scorer, container, and dependency appears in a machine-readable
  software/data BOM with stable identifier, upstream URI, version/commit,
  digests, SPDX declared/concluded license, copyright/attribution, derivation
  lineage, and transformation-script digest.
- Dataset records additionally name collection/generation method, creator or
  generating model, intended use, redistribution/commercial limits, personal-
  data status, authority/consent basis, de-identification, retention,
  deletion/takedown process, and jurisdiction restrictions.
- `NOASSERTION`, incompatible, noncommercial, or nonredistributable inputs may
  appear only in a separately labeled research track. They cannot support an
  open-commercial or unrestricted-reproduction claim.
- Public bundles contain no raw personal data. A rights/privacy withdrawal
  quarantines the affected version and supersedes, rather than erases,
  dependent results.
- Each official track publishes content-addressed harness/adapter commits,
  locks/hashes, build recipe, OS/kernel/architecture, CPU/GPU/drivers,
  database settings, locale/timezone, concurrency, RNG/seeds, cache state, and
  cold/warm policy. Fixtures and golden vectors have versioned manifests and
  hashes.
- A clean machine must reproduce the public result with one documented command
  within frozen deterministic or statistical tolerances. Hardware/resource
  profiles remain separate rankings.

## 12. Governance, signing, appeals, and claims

- The specification, schemas, reference adapter, scoring code, baselines,
  issues, appeals, and change proposals are public and independently versioned
  where their compatibility can change.
- Before governance activation, a content-addressed governance manifest must
  pin the semantic version, SHA-256, activation state, and precedence of
  `docs/governance/CHARTER.md`, `CHANGE-CONTROL.md`,
  `APPEALS-AND-DISPUTES.md`, and `CONFLICT-OF-INTEREST.md`. That manifest does
  not yet exist, and the current source-activation language conflicts: no
  `governed`, `neutral`, or `certified` label is available until both gaps are
  resolved.
- Material changes publish rationale, compatibility impact, validation,
  conflicts, review record, effective date, and at least a 14-day comment
  period. Any change after held-out access creates a new version/round.
- Appeals record receipt, scope, evidence hashes, reviewer assignments and
  recusals, response opportunity, decision, rationale, vote, and remedy.
  Triage is due within ten business days and final disposition within thirty
  days or a public extension. Narrow security redaction preserves the
  sealed-original hash. Publication additionally requires a preregistered pool
  of at least three conflict-free eligible reviewers and quorum of two. If
  recusals leave no quorum, the contested result is quarantined and
  non-publishable until replacement reviewers are appointed; quarantine is the
  fail-closed default remedy.
- Every result is a canonical schema-validated attestation over the result
  bundle and binds preregistration, harness, adapter, SUT, model, prompt,
  dataset/BOM, environment, hardware/profile, seeds, raw logs, attempts,
  metrics, uncertainty, exclusions, custody, and supersession links.
  Submitter, operator, custodian, and reproducer are distinct signing roles.
  Identity-bound public verification, transparency inclusion, trust roots,
  rotation, revocation, compromise response, and offline verification are
  required. A self-signature proves integrity, not neutrality.
- `Independently reproduced` means a conflict-free party outside the submitter
  and operator reran the pinned public bundle, reproduced deterministic hashes
  exactly and statistics within frozen tolerances, and published a signed
  report. Mnemosyne may publish only the existing
  `open, operator-run, fully auditable` class after source-owned gates; stronger
  labels require their stronger evidence.
- Human approval remains mandatory. Every claim names division, module/track,
  versions, resource profile, model policy, budget, date, custody, exposure,
  and reproduction status. No superiority claim is permitted before held-out,
  reproducible results and an approved versioned claim rule.

## 13. Non-colliding delivery stages

This is dependency ordering, not an implementation plan or completion status.

### WMBS-A — Authority and traceability freeze

Freeze precedence, the live requirement matrix, canonical metric/corpus IDs,
and official-suite registry. No module is admitted before this exit review.

### WMBS-B — Comparator and evidence contracts

Freeze the common ABI, divisions, disclosures, sandbox/metering contract, M15
replay, and additive M20 result/ledger migration. This stage must reuse Phase
16 evidence contracts.

### WMBS-C — Core comparison cells

Build M01–M05, M10, and M14 local/portable cells after WMBS-B. Official QA
remains gated by the live Phase 12/13 owners.

### WMBS-D — Lifecycle, safety, and action cells

Build M06–M13 after WMBS-B and after each product capability exists through a
public contract. CAP-012/013 source may be reused; current probes are not
certification evidence.

### WMBS-E — Portability, custody, and media cells

Build M16–M19 plus H8/P32 profiles only after the behavior being claimed and
the relevant hardware/custody gates are admitted.

### WMBS-F — Official adapters and public operation

Run faithful official adapters and held-out rounds only after affected module
readiness, PBPP/Register-A evidence, and human approval. Render only measured
dimensions; no stage requires or implies a composite or superiority claim.

## 14. Result and disclosure labels

Current modules use the admission states in Section 4 only. Public reports
pair those states with:

- track (`OFFICIAL-UPSTREAM`, `ENHANCED-SUCCESSOR`, or `DEVELOPMENT`);
- division (`COMPONENT-CLOSED`, `AGENT-CLOSED`, `SYSTEM-OPEN`, or
  `HOSTED-OUTCOME`);
- capability (`native`, `emulated`, or `unsupported`);
- custody (`development-public`, `operator-held-out`, or
  `certification-held-out`);
- reproduction (`operator-run` or `independently reproduced`);
- resources (`verified` or `resource-unverified`).

No `certified`, `governed`, `neutral`, “whole-system,” or “industry standard”
badge is available in this revision. Those words require resolved governance,
frozen mandatory-core rules, independent evidence where named, and measured
held-out results. Unsupported advanced capabilities remain disclosures, not
quality failures.

## 15. Public benchmark reuse

Every admitted public suite has two explicitly separate possible tracks:

1. **`OFFICIAL-UPSTREAM`:** run the official protocol unchanged. Pin and
   preserve the upstream dataset and split, preprocessing, prompt/model policy
   where prescribed, scorer, aggregation, environment, and release/commit.
   The adapter may translate transport only; it may not change task content,
   labels, budgets, scoring, exclusions, or aggregation. Any required change
   makes the run non-official.
2. **`ENHANCED-SUCCESSOR`:** a separately named and versioned Mnemosyne
   successor may test the same ability with stronger controls, harder or
   adversarial cases, better temporal/provenance/safety coverage, larger
   scale, or improved statistics. It must publish the parent construct,
   difference manifest, construct-validity rationale, fixtures/generator,
   scorer, anti-gaming controls, and baseline bridge. It never inherits the
   official name or score.

Official and enhanced results are published in separate columns and evidence
families. Neither may replace the other, and no certified aggregate, rank, or
headline average may combine them. This separation preserves direct external
comparability while allowing the standard to improve rigor rather than merely
fill omitted capability gaps.

The implementation program should prefer faithful official adapters and
source-grounded successor tracks over unrelated new data:

- [LoCoMo](https://github.com/snap-research/locomo)
- [LongMemEval](https://github.com/xiaowu0162/LongMemEval)
- [LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2)
- [MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench)
- BEAM (official source/revision to be pinned under BENCH-006)
- Memora and FAMA (official sources/revisions to be pinned)
- MemoryArena (official source/revision to be pinned)
- AFTER (official source/revision to be pinned)
- [HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG)
- [GateMem](https://arxiv.org/abs/2606.18829)
- [GroupMemBench](https://www.microsoft.com/en-us/research/publication/groupmembench-benchmarking-llm-agent-memory-in-multi-party-conversations/)
- [PM-Bench](https://arxiv.org/abs/2607.12385)
- [TriggerBench](https://arxiv.org/abs/2606.23459)
- [STATE-Bench](https://github.com/microsoft/STATE-Bench)
- [EvoMemBench](https://github.com/DSAIL-Memory/EvoMemBench)
- [EMemBench](https://arxiv.org/abs/2601.16690)

This list is a reuse registry, not an admission claim. An upstream name may be
used only after its official URI, commit/release, license, split, scorer,
environment, and BOM are pinned and its adapter passes fidelity review. A
local generator inspired by a paper receives a repository-specific development
name. GateMem and GroupMemBench remain unassigned until a runnable module
contract is approved; name-only coverage is not implementation.

## 16. Spec hardening checklist

Completed design corrections:

- [x] Whole-memory intent is explicit.
- [x] Official upstream protocols and enhanced successor tracks are separate;
      their scores cannot be blended into one certified result.
- [x] All 24 capabilities map to modules.
- [x] Universal outcomes are separated from advanced disclosures.
- [x] All 20 modules define contract, data, scorer, gate, replay, resource
      prerequisite, dependencies, deferral, and honest disposition.
- [x] L16-DEV is non-ranking and requires measured receipts; official local,
      H8, hosted, and P32 profiles are separate.
- [x] Official external runs cannot be replaced by synthetic labels.
- [x] Sandboxing, metering, statistics, anti-gaming, rights/privacy/SBOM,
      governance, custody, appeals, signing, and human approval are explicit.
- [x] Existing result-v1/ledger/publication contracts are reused and preserved;
      result-v2 is an additive migration.
- [x] Atomic attempt records are authoritative; comparison views and
      user-selected averages are transparent, reproducible projections.
- [x] Cross-capability scenarios and the live requirements matrix are explicit.
- [x] No implementation or completion status is implied.
- [x] No superiority claim is made before held-out reproducible results.
- [x] Existing canonical metric, corpus, publication, MNB, blueprint, plan, and
      implementation owners are referenced rather than duplicated.

Future admission evidence remains deliberately open:

- [ ] `wmbs/0.1-draft` schema and golden vectors pass independent review.
- [ ] Every pilot module has a runnable adapter, deterministic generator,
      objective scorer, inferential plan, BOM, sandbox receipt, and measured
      resource receipt.
- [ ] Result-v2 dispatch and full bundle/build/config/trace binding pass without
      mutating result-v1 history.
- [ ] Governance activation conflicts are resolved through their owning files.
- [ ] At least one clean-machine reproduction proves the public command.
- [ ] Any official/held-out result passes PBPP, custody, and human approval.

## 17. Authorized next planning boundary

The separately reviewed implementation plan may cover only the minimal
reference harness and pilots M01, M03, M10, M12, M13, M15, and M20. It may
reuse existing public runner, bundle, action/working-memory probes, and
leaderboard contracts, and may name the narrow public-ABI gaps required to
make those pilots honest. It must not implement code, start an official run,
publish a result/site, claim certification, or open a pull request without a
later explicit instruction.
