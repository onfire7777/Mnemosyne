# Memory-Native Benchmark (MNB)

Version: 0.1.0
Status: specification; no results claimed

## Why a new suite is justified

Existing public memory benchmarks measure **question answering over long
context**. Mnemosyne is a **memory compiler**: a content-addressed evidence
ledger with bitemporal projections, calibrated abstention, capability-gated
writes, signed deletion, and provenance. The overlap is real but partial, and
the gap is not a matter of difficulty — it is a matter of *what is scored*.

Three concrete misalignments:

1. **Abstention is penalised.** QA suites score a refusal as a miss. Mnemosyne's
   CAP-002 contract is that the reader *must* abstain when retrieved evidence
   cannot ground an answer. Correct behaviour costs points.
2. **Provenance is invisible.** A system that guesses the right answer and one
   that derives it from traceable evidence CIDs score identically.
3. **Time is flattened.** "What did you believe on 3 March, and what superseded
   it?" is unrepresented, yet bitemporality is a core storage primitive.

Nothing here argues the public suites are bad. They stay, unchanged, as the
primary comparable numbers. MNB measures the dimensions they do not reach.

Precedent already exists in-repo: `pm_bench_triggerbench` and
`working_memory_action_probe` were built because no public suite covered CAP-012
or CAP-013. MNB generalises that pattern rather than inventing it.

## Dimensions

Each dimension is programmatically graded wherever possible. Every dimension
maps to an existing capability requirement, so nothing is invented to flatter.

| # | Dimension | Question it answers | Maps to |
|---|---|---|---|
| D1 | Provenance integrity | Does every synthesized claim resolve to evidence CIDs? | CAP-002 |
| D2 | Calibrated abstention | Does it refuse when evidence is insufficient, and is refusal well-calibrated? | CAP-002, CAP-005 |
| D3 | Bitemporal correctness | Can it answer "what was believed at time T" separately from "what is true now"? | Engine contract |
| D4 | Belief revision | Are contradictions handled by supersession and contraction rather than silent overwrite? | §7 #13 |
| D5 | Deletion compliance | After a signed deletion manifest, is the content genuinely unrecoverable? | Engine contract |
| D6 | Write-path safety | Are taint propagation and capability gates enforced under adversarial writes? | CAP-004 |
| D7 | Consolidation and decay | Does memory degrade gracefully across cadences while preserving freshness and expiry? | CAP-007 |
| D8 | Prospective memory | Are subject-scoped intentions triggered deterministically and idempotently? | CAP-012 |
| D9 | Working memory | Are TTL, explicit promotion, and deterministic expiry honoured on a distinct route? | CAP-013 |

D1–D5 are engine-agnostic and portable to other systems. D6–D9 require the
target system to expose the relevant surface; where it does not, the cell is
reported **"not applicable"**, never as a zero. Scoring a competitor zero for
lacking a feature Mnemosyne happens to have is the exact self-dealing this
suite must avoid.

## Anti-self-dealing rules

An operator-authored benchmark is the highest-risk artifact in the project. The
Plan B risk register already names the failure mode — a self-defined headline
benchmark — as something to design against. These rules are binding.

1. **Spec before score.** The specification, generator, and grader are published
   and frozen *before* any system is run, including Mnemosyne. The freeze digest
   is pre-registered per [CREDIBILITY-MODEL](../governance/CREDIBILITY-MODEL.md).
2. **Never headline alone.** No MNB number is published without established
   public-benchmark results shown alongside it. The site renders
   operator-authored and established suites in visually distinct columns.
3. **Adapter parity.** Every system compared gets a real adapter, published and
   open. If a fair adapter cannot be written, the cell is "not measured".
4. **Publish the losses.** A standing "where Mnemosyne underperforms" section.
   If it is empty, the suite is presumed rigged until failures appear.
5. **Held-out and rotation.** A private split whose digest is published in
   advance; periodic task rotation; reveal on a stated schedule.
6. **Open dispute.** Anyone may contest a task, a grade, or a result; every
   dispute gets a public, logged resolution.
7. **External entries welcome.** Anyone may submit a system by pull request; the
   operator runs it under the identical harness and publishes the traces.
8. **No tuning against MNB.** Mnemosyne is not optimised against MNB tasks. Any
   change made in response to an MNB result is disclosed in the change log.

## Licensing and openness

Everything ships under the repository's Apache-2.0 licence: the specification,
task generators, graders, fixtures, adapters, and the harness. The point is that
a third party can regenerate the corpus, re-grade the outputs, and reproduce
every published number without asking permission or possessing private data.

Task data is generated from seeded, declared synthetic sources so the corpus can
be rebuilt deterministically rather than downloaded from a single owner.

## Status and gates

MNB is a **specification only**. No dimension is implemented, no result exists,
and no capability claim in `.planning/REQUIREMENTS.md` may cite it until its
dimension is implemented, pre-registered, and run.

Implementation order follows existing evidence: D8 and D9 have working probes to
generalise; D1–D3 exercise contracts already covered by tests; D4–D7 depend on
capability work still in progress.
