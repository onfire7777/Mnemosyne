# Plan: make Mnemosyne's memory outperform Anthropic's

Status: proposed implementation plan; no implementation is recorded by this document.

Date: 2026-11-10. Starting release: `dev@d3b22e81`.

## Objective and comparison boundary

Make retained experience measurably improve later answers and actions, while reducing repeated mistakes, stale claims and the cost of supplying context. Preserve ownership, provenance, correction, erasure and safe promotion as the system improves.

The reference is Anthropic's [The components of agent memory](https://www.anthropic.com/research/components-of-agent-memory), published November 6, 2026. It describes selective notes, transcript-grounded correction, incremental knowledge representations and a small injected layer. Its experiments also show that model capability and task type affect the benefit. The article is a capability reference, not a complete specification of a single publicly reproducible product.

We will distinguish three claims: implementing those capabilities, outperforming a documented reference implementation, and outperforming an actual Anthropic product. Each requires its own evidence. A reference implementation win cannot establish the last claim.

## Starting evidence

The November 10 audit found:

- The personal store had 41 episodes, four resolved outcomes, zero learning-credit records, 35 legacy candidate artifacts, and no learned artifacts in retained context receipts. Only 13 episodes had receipts. These are a dated snapshot, not an invariant or a target to inflate.
- Recent turns were captured without receipts. Native and fresh authenticated status calls timed out during the audit. The exact causes remain to be traced; global lock contention is a hypothesis, not a finding of causation.
- The Codex hook omits available tools. Automatic retrieval omits selectors required for working and prospective memory.
- A focused reproduction injected roughly 96 KB of profile data despite a 32-token retrieval budget.
- Ordinary dream hypotheses lack the steps required by their own verification path and therefore cannot advance through it.
- Automatic formation misses useful project relationships, future relative dates remain unresolved, and general topic models are not automatically discovered. The personal store had no maintained models or knowledge pages.
- Task grouping remains mostly lexical. The new trained adapter improves a success prediction; its gate does not demonstrate better retrieval, strategies or answers.

The prior release's focused tests established specific repairs. They did not establish competitive memory effectiveness. Preserve those receipts and the older failing evaluation reports.

## Architectural commitments

Extend the existing stores and writers. Keep the hierarchy: original evidence → typed claims and verified experiences → maintained topic/skill views → a bounded session packet. Treat views as rebuildable projections with source dependencies, rather than additional independent truth stores.

Every derived unit needs an owner, stable identity/version, exact source references, epistemic class, observation time, applicable event time, scope and derivation version. Distinguish direct statements, reported beliefs, inferences and hypotheses. Model confidence cannot upgrade source authority. Maintain an explicit dependency map so correction, expiry, access revocation and erasure propagate through every layer.

Keep existing promotion thresholds and protected checks. Introduce new capabilities through shadow proposals and reversible activation. Raw evidence and historical receipts remain intact; absent historical delivery or outcomes stay absent. A deadline becoming overdue never means a commitment was completed.

## Milestone 1 — dependable live delivery and outcome capture

**Outcome:** every supported turn either receives usable memory in time or has an explicit, observable degraded result; completion capture remains independent.

**Implementation ownership:** `hosts/codex.py`, `experience/integration.py`, `experience/runtime.py`, `mcp_tools.py`, and tracked `integrations/codex/` deployment code. Reconcile the installed runtime wrapper with this contract rather than leaving critical behavior solely in an untracked local script.

1. Trace a correlation ID from host invocation through preparation, receipt persistence, context return, acknowledgment when available, completion and outcome. Record stage times, lock waits, cancellation, errors and version information without logging secret payloads.
2. Reproduce missing receipts through the real Codex host. Check actual hook invocation, trust/enablement, timeout, transcript IDs and state recovery before changing lock design. Separate prepared, returned, acknowledged and applied states; unsupported acknowledgment remains unknown.
3. Add bounded lock acquisition and end-to-end deadlines. Keep provider work outside shared write locks and make transactions short. Return source-valid local context when remote stages fail; identify omitted stages. One hung call must not indefinitely stall other chats or completion capture.
4. Pass the actual session, authenticated agent/user, workspace scope and current tool manifest. Forward the required working/prospective selectors. Explicitly represent unknown tool availability; never infer it from historical use or bypass eligibility checks.
5. Connect applied-memory reports to independent task checks. Non-coding outcomes need appropriate checkers: factual source checks, output validators, actual tool results or explicit human adjudication. A displayed memory or assistant success statement is not evidence of benefit.

**Exit evidence:** real-host traces across two chats, a fresh session, restart and interrupted completion; focused fault injection for slow providers, lock contention and retries. Every scripted turn has a complete explanation of its lifecycle. No duplicate observations or fabricated delivery. Correctly scoped working memory and due intentions appear; recalling an intention does not send a notification. Available-tool procedures appear and unavailable-tool procedures do not.

**Initial performance goals:** freeze after baseline collection: normal preparation p95 at or below five seconds; with a 15-second host timeout, return or report degradation within 12 seconds. Report the rate of useful delivery separately from the rate of merely returning on time.

## Milestone 2 — one selective, bounded context composer

**Outcome:** the agent receives the smallest packet sufficient for the current task.

**Implementation ownership:** context assembly in `experience/runtime.py` and `mcp_tools.py`, `user_model.py`, retrieval/pipeline integration and the host renderer.

1. Enforce one total memory budget across facts, profile, goals, working memory, topic summaries, procedures and verification requests. Reserve space for the envelope and source handles. Use the actual target tokenizer or a conservative bound.
2. Rank by task relevance, currentness, confidence, expected usefulness and duplication. Preserve required constraints before optional suggestions. Apply authority and source-custody filtering before ranking.
3. Render compact claims with dates, negation, uncertainty and source handles. Fetch full provenance on demand. Prefer a concise topic index to dumping entire profiles or source records.
4. Log selected and omitted identities with reasons. When required content cannot fit, expose overflow and a retrieval path; do not silently strip qualifiers or misreport the budget.

**Exit evidence:** the 100-entry profile reproduction stays within the total budget; unrelated arithmetic does not receive the entire profile. Relevant preferences and current goals survive distractors. No truncation changes meaning. Measure useful recall and token cost together, including a comparison against the current composer.

## Milestone 3 — richer semantic memory and current commitments

**Outcome:** ordinary project knowledge and changing plans become precise, source-backed memory.

**Implementation ownership:** `memory_formation.py`, `episodic_facts.py`, `assertion_semantics.py`, existing entity/temporal/intention components and storage adapters.

1. Keep deterministic extraction for supported cases; add a structured semantic proposal path for unsupported language. Validate source spans and type constraints before admission. Source presence alone does not prove that a proposed claim follows from it; uncertain interpretations remain proposals or attributed inferences.
2. Support project/asset relationships and conservative entity resolution. Resolve pronouns only with an unambiguous antecedent. Preserve distinct owners, projects and entities with similar names.
3. Anchor temporal phrases to the source timestamp and known timezone. Preserve original wording, precision and ambiguity. Use the existing intention model for pending commitments and retain the historical fact that a decision occurred.
4. Support source-backed rescheduling, cancellation and completion. Distinguish overdue from completed. Scheduled notifications continue through the app's automation system.
5. Backfill through previewable, versioned projections over retained evidence. Preserve raw sources and manual corrections; verify dependency invalidation before regeneration.

**Exit examples:**

- “My deployment server is Atlas. It runs Debian.” produces two linked, separately cited claims.
- “I have two projects: Mnemosyne and BurnOS.” retains both project identities and the count.
- “My coworker thinks Atlas runs Debian” remains an attributed belief.
- At a November 10 Los Angeles source timestamp, “meet Alex tomorrow” becomes November 11 without an invented time. An ambiguous “next Friday” stays unresolved.
- A supported cancellation stops the commitment from appearing as pending; erasing its only source removes dependent projections without resurrection.

## Milestone 4 — a complete, evidence-driven dreaming loop

**Outcome:** a discovered error or useful pattern can become tested knowledge that helps a later session.

**Implementation ownership:** `experience/sleep.py`, `candidates.py`, `signals.py`, `guards.py`, runtime/jobs and host verification adapters.

1. Introduce typed review contracts: factual claim review, contradiction resolution, procedural experiment and knowledge-maintenance proposal. Factual review must not require command steps.
2. Persist a resumable state machine: proposed → queued → running → verified/rejected/inconclusive. Bind results to source versions, verifier identity, applicability conditions and the exact candidate revision.
3. Route ordinary content-only hypotheses to a real reviewer/checker. Resolve factual questions against authoritative retained evidence; use deterministic checks where possible and record unresolved evidence honestly. A generative reviewer must provide checkable support, not certify its own prose.
4. Run permitted procedural experiments in disposable sandboxes. External or consequential actions retain the host's normal authorization. Verification infrastructure must work before any skill is promoted.
5. Admit verified corrections through semantic writers and demonstrated procedures through existing probation/control gates. Schedule reviews from recurring mistakes, useful successful discoveries, contradictions and frequently retrieved uncertainty.

**Exit evidence:** the current content-only hypothesis reproduction can reach verified, rejected and inconclusive states. A seeded wrong memory is corrected from source evidence and a fresh session answers correctly. Failed theories never become advice. Crash/retry, changed sources and duplicate checker responses cannot duplicate credit or preserve invalid verification.

## Milestone 5 — maintained knowledge across sessions

**Outcome:** important topics develop concise, current knowledge maps without requiring manual setup.

**Implementation ownership:** existing `KnowledgePage`, `MentalModel`, refresh workers, jobs and source dependency/indexing code. Treat task-specific lesson compilations as one view of the same source-linked system.

1. Discover worthwhile topics from recurring entities, repeated questions and explicit durable goals. Bound creation by demonstrated usefulness and maintenance budget.
2. Build source-linked topic pages containing established facts, decisions, pending commitments, uncertainties and related-topic links. Integrate them with search and the bounded context composer.
3. Incrementally correct and merge pages as evidence changes. Repair broken links, duplicate topics and unsupported summaries. Use leases/version checks to prevent concurrent overwrites.
4. Prioritize maintenance by source changes, retrieval frequency, observed failures and likely staleness. Cap wall time, provider tokens and background concurrency. Quiet topics should not trigger endless rebuilding.

**Exit evidence:** facts learned about Atlas in separate sessions support a coherent later answer; changing its operating system updates the relevant page and injected claim. Every displayed claim has readable support. Concurrent updates survive. Pages compress useful information rather than reproducing transcripts. Revocation and erasure propagate to cached and regenerated views.

## Milestone 6 — transferable skills and learned memory utility

**Outcome:** experience changes which eligible memory or strategy is used and improves later tasks.

**Implementation ownership:** `experience/task_class.py`, `candidates.py`, retrieval/ranking, runtime selection, signals and the existing guarded policy-learning machinery. Keep the current parametric predictor as a calibration diagnostic.

1. Add versioned semantic task contracts alongside immutable historical task IDs: intent, entities/inputs, expected outputs, constraints, capabilities and risk. Semantic models propose matches; explicit compatibility checks control trials.
2. Generalize procedures using typed variables, observed binding evidence and applicability conditions. Preserve flags, negation, effects, permissions and entity boundaries. A failed transfer must not silently corrupt the original procedure.
3. Train or update utility estimates for retrieval, selection and strategy choice from applied-memory evidence and subsequent outcomes. Begin with existing interpretable policies; add a learned scorer only when data and comparisons justify it. It may reorder eligible choices, never override protected content or authorization.
4. Retain served/control opportunities, selection propensities and actual-use evidence to address exposure bias. Distinguish correctness, cost and confidence improvements. Do not reward global task success as if every displayed memory caused it.

**Exit evidence:** unseen valid paraphrases and a new workspace reuse the correct procedure; changed constraints are rejected. Selection actually changes before the answer/action and improves later outcomes. Shuffled or irrelevant memories show no spurious benefit. Rollback restores the preceding selection policy.

## Measurement throughout implementation

Start with a small frozen pilot: 20 multi-session task streams across five families—project recall, corrections/stale facts, changing commitments, reusable coding/tool procedures, and cross-session continuation with distractors. Use consented real-task replays plus clearly labeled synthetic edge cases. A four-session stream can establish knowledge, test delayed recall, introduce a correction and test transfer. Track task-specific truth with source evidence or deterministic checks; blind any necessary human adjudication.

Compare the current Mnemosyne release, the improved release and a documented Anthropic-style notes + transcript-search + scheduled-dreaming/wiki reference. Use memory-disabled runs as a diagnostic ablation when needed. Keep the base model/version, tools, source corpus, task ordering, answer budget and total maintenance allowance matched. Let the reference model select salient notes rather than imposing a knowingly weak failure-only policy. Record the reference's limitations and configuration.

Primary measure: independently checked success on later tasks that require memory. Secondary measures: repeated-error rate, stale/false-claim rate, correction persistence, held-out transfer, supported recall precision/coverage, useful delivery rate, p95 latency, and total tokens/cost including amortized background work. Report confidence intervals and per-family results, not just an aggregate.

Proposed engineering targets, to freeze before collecting comparison results:

- At least a 10-percentage-point improvement in delayed task success over the reference, with a paired 95% confidence interval excluding zero on an untouched confirmation set.
- At least 25% fewer repeated mistakes where the reference has enough errors for that rate to be meaningful; always show absolute counts.
- At least 20% lower total memory-related token cost, including background maintenance, at the required quality level. Report tradeoffs if quality improves but this cost goal does not.
- No critical owner-isolation, evidence-authority or erasure failures in required checks, and no material per-family regression. Predeclare any statistical tolerance before observing results.

These are targets, not promises or existing measurements. The 20-stream pilot establishes direction and exposes failures; it may not establish statistical superiority. Use pilot variance to size a separate confirmation set. Freeze code, prompts and tuning choices before confirmation and seal future questions and labels. Each arm may learn and dream from information already observed within its own stream; prohibit future-turn, cross-arm and cross-stream leakage. Never reuse a repeatedly inspected holdout as untouched evidence. If evidence is insufficient, report that and keep improving rather than lowering checks.

### Final comparative release gate

The target remains beating Anthropic's actual memory, not only our reconstruction. After Milestone 6 and the reference comparison succeed, select an accessible, explicitly named Anthropic memory offering and record its version, configuration and supported capabilities. Give both systems equivalent setup, interaction history, user information and tool opportunities. Run a separate untouched set of workflows with blinded outcome grading and report retries as well as successes. Where the base model or internal maintenance compute cannot be controlled, label the result as a whole-product comparison and disclose the confound; do not attribute the entire difference to memory architecture or claim a hidden-cost advantage. Report observable cost and latency separately.

A public superiority statement must identify the tested offering, date, tasks and uncertainty. Completion of this plan's competitive objective requires both the controlled confirmation and the named-product comparison to meet their predeclared criteria, including acceptable quality in every critical task family and the same required privacy/correction checks. If product access or fair comparison is unavailable, the result remains a reference-implementation result and the broader goal remains unproven.

Use focused tests for each changed path and the small host pilot. Skip the full test suite and broad benchmark matrix for this effort, consistent with the requested workflow. Comparative checks should remain a bounded evidence lane, not displace fixing the actual memory path.

## Delivery, sequencing and rollback

Execute Milestones 1 and 2 first. Milestone 3 establishes shared semantic contracts. Milestone 4's typed verifier design can proceed alongside 3 once those contracts are agreed. Milestone 5 depends on 2–4. Milestone 6 depends on reliable receipts, selection and verified outcomes; generalization trials can proceed alongside topic maintenance.

Assign separate ownership for host/runtime reliability, semantic/temporal memory, verification/learning, and knowledge/context integration. Serialize shared changes to the runtime, MCP boundary, writers and guards. Each milestone should be reviewable as a coherent change with focused tests and a concrete before/after task trace.

Before live mutation, take consistent store/configuration backups. Rehearse migrations and erasure on a clone; produce an exact projection-change preview. Deploy supported host entry points together, verify their running versions and handle reconnects explicitly. Run new generation/selection paths in shadow, then a bounded live canary with independent outcomes. Preserve learning enabled by default; feature rollback should disable only the new path and invalidate its projections, leaving evidence and unaffected learning available.

For each milestone, record the source commit, test selectors/results, real-host traces, live state changes, cost, failure cases and rollback result. Delivery to `dev` is distinct from verified deployment; deployment is distinct from demonstrated user benefit. Existing planning history and acceptance claims remain unchanged by this proposal.

The first release milestone is concrete: a fresh supported session receives the right owned memory within budget and deadline, uses it in a checked task, and preserves a real correction for the following session. Subsequent releases must improve that behavior, not merely increase stored artifacts.
