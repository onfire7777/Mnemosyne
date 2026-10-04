# OpenMemBench: auditable evaluation of AI memory systems

Status: methods draft, 2026-10-04. Not a results paper, public launch receipt,
or change to accepted Plans A/B. The policies in `docs/governance/` remain
authoritative. This draft describes implemented mechanisms separately from
requirements whose evidence is still missing.

## 1. Research question and scope

The intended comparison is whether memory systems retain, retrieve, revise,
and use information correctly under disclosed resource and access constraints.
Remembering a relevant passage and producing a correct answer are different
outcomes. We report them separately, alongside safety, calibration, latency,
cost, and scale. No universal superiority claim follows from one dataset or
one aggregate score.

The original launch roster includes Mem0, Graphiti/Zep, Letta, Cognee, MemOS,
Supermemory, HippoRAG and Mnemosyne. A hosted service and its open-source
counterpart are separate evaluated configurations. The launch must include
every system for which a fair adapter exists, and state the reason for each
absence. This roster is an intended comparison, not a claim that all adapters
are ready or that these systems have been measured together.

Mnemosyne is the operator's own entry. The evaluation is operator-run; it does
not claim independent operation or a seated neutral board. The optional board
does not replace the mandatory source-owned publication gates.

## 2. Registration and experiment identity

Before eligible scoring, a signed, publicly committed preregistration must
identify the harness commit, adapters, dataset revisions and hashes, split
roles, metric definitions, expected entrants, budgets and stopping rule.
Changes after registration require a new identifiable experiment; they must
not silently alter an existing run. Publish failed and aborted attempts as
well as successes, and retain the prior configuration.

The repository has canonical QA protocol and candidate validators, signed
ledger tooling, and roster-completeness checks. Those mechanisms do not prove
that a particular launch registration exists. In particular, the local
2026-10-04 retrieval run plan is only preparation: its public signed
preregistration is outstanding, and no score has been produced under it.

Avoid circular provenance when recording registration: retain the exact
registered source commit separately from the commit containing the signed
registration. Execute that source in a clean, identified checkout and bind the
result to it. Publishing registration must not silently move the measured
implementation to a different commit.

## 3. Data, rights and contamination

`eval/public/registry.json` specifies assets by immutable revision and SHA-256,
including license, citation, contamination notes and split role.
`eval/public/assets.py` validates the asset specification, rejects unsafe or
symlinked paths, checks file digests, and rejects duplicate JSON keys and
non-finite numbers. Normalized data must match the registry's separate dataset
digest before execution.

The prepared LongMemEval retrieval experiment uses the cleaned short release
and oracle support labels from the upstream revision
`98d7416c24c778c2fee6e6f3006e7a073259d48f`. On 2026-10-04 both downloaded file
hashes and the canonical normalized digest matched the registry. Normalization
contains 500 questions and 23,867 corpus records. The adapter performs its
registered deterministic secret-pattern redaction. The oracle supplies
scoring support; it is not an answer-generation prompt.

Held-out inputs are never development fixtures. Do not select favorable
questions, inspect failures to tune the same held-out experiment, or treat
renamed copies as a new split. Preserve all known contamination limitations.
For example, the registered MuSiQue sample explicitly discloses potential
training overlap and the lack of machine-readable upstream exclusion IDs.
Recording this limitation does not resolve it.

Source acquisition is separate from evaluation. File download, normalization
and hash verification do not constitute a measured memory-system result.

## 4. System interface and resource controls

The public harness drives Mnemosyne through CLI subprocesses rather than
importing its engine. Adapters translate benchmark operations onto that public
interface. The LongMemEval adapter uses isolated question stores and maps
retrieved content identifiers to session identities before scoring. Other
systems must receive equivalent data and budgets through their registered
adapters; adapting an input does not permit changing the task.

Record the OS, hardware, runtime, backend, model and embedding revisions,
context and evidence limits, parallelism, cache state, timeouts and retries.
Disclose concurrent workloads. Process-boundary latency is not equivalent to
warm in-process latency; report the measured boundary. Hardware-aborted runs
are failures or aborted attempts, never omitted samples.

The current development host is an M1 Pro Mac with 16 GiB unified memory.
Full LongMemEval normalization completed under a memory-pressure monitor with
approximately 2.34 GiB peak process memory. This establishes only preprocessing
feasibility. The separate grounded-reader preflight triggered memory pressure
during model loading and was stopped. Full model-benchmark feasibility on this
host remains unproven; no model, context or acceptance threshold was reduced
to conceal that limitation.

## 5. Outcomes, uncertainty and judges

Scoring is versioned in `eval/public/scoring.py`. Bind each result to its named
profile and disclose its sample count, aggregation, exclusions, interval
method and confidence level. Retrieval profiles measure recovery and ranking
of relevant support. QA profiles measure answer correctness; a reader may
fail even when retrieval succeeds.

The current implementation has bootstrap intervals for retrieval and token
F1, and Wilson intervals for exact-match proportions. These are implementation
mechanisms, not permission to choose whichever interval makes an entry look
better. Use the registered profile and report ties under the preregistered
rule. Do not infer significance solely from the order of point estimates.

For `longmemeval-retrieval-v1`, each question contributes the fraction of its
gold support sessions recovered among the first five hits, plus binary-relevance
nDCG at five. The final point estimate is the mean across questions. The current
bootstrap draws 2,000 question-level samples with replacement using seed 1,234
and reports the 2.5% and 97.5% percentile bounds. This sampling unit matters:
it is not a confidence interval formed by treating every retrieved hit as an
independent trial.

For `qa-em-f1-v1`, predictions and answer aliases undergo the profile's Unicode,
case, punctuation, article and whitespace normalization. Exact match accepts
any supplied alias; token F1 takes the best matching alias. Neither computation
is an LLM judge. Keep grounding, abstention and safety outcomes visible rather
than assuming that an exact answer alone proves a grounded answer.

If an evaluation uses a model judge, disclose the provider/model revision,
prompt, decoding, rubric, calibration data, agreement or sensitivity analysis,
and cost. Deterministic retrieval needs no model judge. A generated answer
and a judge's assessment must not be conflated with retrieval recall.

The static renderer displays supplied intervals without inventing their
confidence level. A missing interval is labeled missing, not zero. A complete
methods/result artifact must still supply the uncertainty information required
by the methodology policy.

## 6. Artifact custody, replay and presentation

`eval/public/bundle.py` verifies the supported bundle contracts and replays
supported profiles from their retained inputs. A valid bundle binds the
dataset, implementation, configuration, traces, scorer and derived metrics.
Use the documented `mneme eval-public --verify-bundle` and
`--reproduce-bundle` commands with the bundle's exact checkout and dependencies.
A verifier pass proves only the checks implemented for that contract; it is
not automatic admission or evidence that a model was actually executed.

`leaderboard/ledger.py` maintains signed outcome records and a signed roster
head. Its verification rejects unknown entrants and, when completeness is
required, missing roster outcomes. Corrections supersede earlier entries;
history must remain available. A missing competitor needs a reasoned `no_run`
record rather than a silently shortened table.

`leaderboard/publish.py` selects active successful records from a verified
ledger and checks required trace/artifact bindings. `leaderboard/readiness.py`
evaluates supplied readiness information. The release process must verify
that the cited evidence exists and supports each assertion; a declaration of
readiness alone is not proof.

The static site supplies results, run disclosures, question traces, a reading
guide and source-linked architecture summaries. Its current empty state
correctly reports that no verified results have been published. Temporary
synthetic UI fixtures are not launch data. L2 completion still requires a
public versioned data source, deployment, permanent result URLs, a data mirror
and at least one real entry browsable through its traces.

## 7. Failure reporting, corrections and review

Publish an adversarial report showing where Mnemosyne fails, with the exact
task, configuration, observations and limitations. A hardware cancellation,
a schema failure, a wrong answer and a safety failure are distinct outcomes.
Do not turn any of them into a passing score by changing the denominator.

The public dispute process must retain evidence, status, rationale, conflicts
and linked corrections. Existing appeals policy describes reviewer/quorum
steps tied to the optional board. Its operational relationship to the
operator-run Register A process must be resolved explicitly before launch;
this draft neither invents seated reviewers nor waives review requirements.

This methods draft can be reviewed openly without waiting for journal
acceptance. A published preprint and logged review channel are original Plan B
requirements; a local draft or an outline does not satisfy them. Outside
reproductions strengthen evidence but are not a substitute for the required
reproducibility-by-construction path.

## 8. Limitations and current availability

No current head-to-head comparison or best-system claim is established here.
Historical Phase 11 retrieval and Phase 12 QA reports remain historical,
non-headline evidence for their recorded configurations. Restored upstream
datasets do not recreate missing historical run bundles or candidate manifests.
Development module and UI test passes do not establish official benchmark
acceptance, real hardware envelopes, or complete production compatibility.

Before publication, populate the registration, run-ledger, raw-data,
reproduction, adversarial-report, methods-review and hosting references with
actual immutable artifacts. All original roadmap requirements remain in scope.
