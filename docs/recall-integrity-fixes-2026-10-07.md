# Retrieval integrity fixes — 2026-10-07

Implemented in `C:\Users\Onfire\Documents\Codex\Mnemosyne`, based on the supplied
Mnemetric brief. The initial implementation did not locate the original brief or
reproduction scripts. They were subsequently located at
`C:\Users\Onfire\Desktop\QT projects\Mnemosyne\docs\recall-90-fix-prompt.md`
and `C:\Users\Onfire\Desktop\QT projects\Mnemosyne\_scratch\benchmark`.
The current source, Desktop Mnemetric harness/reports, and MnemetricData corpus
and diagnostics were inspected instead. The checkout is newer than the brief's
`e1ad2d0c` pin; the starting revision was `1e19ac52`.
Landed as one commit on `main` on 7 Oct 2026, with one fix found on review: once
the CID header left the summary text, two summaries with the same words over
different sources or RAPTOR levels hashed to the same evidence CID and collapsed
into one row (the root became a copy of a leaf). Each summary now ends with a
single `[gist <source fingerprint>]` token, which keeps every node distinct
without putting source lists back into the searchable text.

## Implemented

- Consolidation no longer assigns the entire input batch to every fact. Each
  candidate keeps its own source CIDs. Model-backed extraction preserves and
  validates explicit citations; ambiguous multi-document responses fail closed.
- The corroboration lookup now requires all subject/object terms, rather than
  any two overlapping words. Independent-source and promotion gates remain.
  This is still a lexical support check, not an entailment model.
- Bare capitalized-name co-occurrence no longer creates `related_to` assertions.
  The deterministic extractor remains conservative and heuristic.
- Summary provenance stays in metadata, outside searchable summary text.
- U-curve layout no longer reorders search results. Memory activation uses the
  request's evaluation instant. Passage search omits activation, recency, MMR,
  and the hashing-based local reranker so they cannot destroy BM25 order.
- `query_mode="passages"` ranks authorized source evidence using corpus-aware
  BM25, excluding generated summaries and assertions. It uses at least 100
  candidates and preserves an actual configured semantic provider/reranker.
  Hashing is not treated as a second semantic signal in this route.
- The graph candidate allowance in ordinary retrieval is increased from half
  the result count to at least the configured rerank width.
- Grounded answering can proceed past insufficient first-hop query coverage.
  Empty results, missing grounding diagnostics, gist-only support, and hard
  grounding gates still stop expansion. Final source and claim checks remain.
- Sourced consolidation summaries no longer consume the autonomous
  self-generation event allowance. Sources must exist, match tenant/branch,
  remain unerased, and classify as grounded. Summaries retain their derived,
  non-authoritative classification. Unsourced generation remains capped.
- Scoring gives a direct passage ID precedence and does not expand a
  multi-source fact into a fabricated passage ranking. An unambiguous
  single-source projection can still resolve to its passage.
- The HippoRAG-family adapter uses a single bounded query process for these
  1,000-query suites, passage mode, 24 results, a 16,384-token budget, and compact
  output. Trace rows reference the stored corpus by count and SHA-256 instead
  of repeating every corpus ID. The corpus remains in the benchmark artifact.
- The passage index is reused within an engine, always after authorization;
  mutations/erasure invalidate it. Only selected local hits are cloned.

The existing general memory search stays available for preferences, assertions,
and temporal retrieval. The benchmark adapter explicitly selects passage mode.
Existing poisoned stores are **not repaired in place**; rebuild evaluation
stores from their source corpus. Historical published artifacts were not edited.
Desktop Mnemetric's separate installed dependency and the live website were not
updated by these source changes.

## Measurements

Ranking was fixed using synthetic tests before examining these held-out scores.
All supplied 1,000-question sets were measured without parameter selection or
tuning on the results. The runner is `eval/recall_integrity.py`.

| Dataset | Passages | Recall@5 | Mean query | P95 query | BM25 top-five mismatches |
|---|---:|---:|---:|---:|---:|
| 2Wiki | 6,119 | 0.66425 | 15.80 ms | 19.35 ms | 0 / 1,000 |
| HotpotQA | 9,811 | 0.72750 | 27.66 ms | 35.74 ms | 0 / 1,000 |
| MuSiQue | 11,656 | 0.42808 | 33.64 ms | 42.95 ms | 0 / 1,000 |

These are **in-memory, passage-only engine measurements**, not an end-to-end
consolidated-store or model-backed HippoRAG reproduction. The parity check
compares the public engine result with its BM25 lexical route; it is not an
independent second implementation of BM25. Original passage ingest took 2.51,
5.33, and 7.33 seconds respectively, without consolidation. The old 2.7-second
per-question figure used a different store/path, so no direct speedup ratio is
claimed. Answer abstention and retrieval recall are distinct; abstentions were
19, 40, and 48, while retrieved passages were scored for every question.

Raw measurement and input hashes:
`C:\Users\Onfire\MnemetricData\runs\recall-integrity-20261007.json`.
The 2Wiki input hashes match the archived Desktop Mnemetric report.

Reproduce from this checkout:

```powershell
.venv\Scripts\python.exe -m eval.recall_integrity --data-root C:\Users\Onfire\MnemetricData\hipporag --output C:\Users\Onfire\MnemetricData\runs\recall-integrity-rerun.json
```

Use the compact passage route on an existing clean evaluation store:

```powershell
.venv\Scripts\python.exe -m mnemosyne.cli --backend local --store STORE.json --evaluation-read-only eval-query-batch --input-jsonl QUERIES.jsonl --retrieval-mode passages --retrieval-top-k 24 --retrieval-token-budget 16384 --compact
```

## Verification

- 389 focused tests passed, covering consolidation, source integrity, local and
  SQLite passage authorization/index refresh/erasure, summary budgets, grounded
  answering, engine parity, the public adapter/CLI, and promotion gates.
- Ruff passed on the changed implementation and regression tests.
- The public CLI adapter was exercised end to end on a synthetic corpus.
- Broader tests exposed existing Windows command-execution failures in C2PA and
  command lesson/skill fixtures, plus a telemetry newline/hash fixture failure.
  Those failures were reproduced with original `HEAD` runtime modules loaded
  directly from Git, without changing the working tree. The broad public-eval
  suite also failed; it is not included in the focused green-test claim.
- PostgreSQL code paths were updated, but no live PostgreSQL verification was
  performed. Its passage route currently uses the existing authorized export;
  it is correct-by-filtering rather than an optimized server-side BM25 index.

## Remaining model/research work

This section records the initial integrity implementation, not current project
acceptance. Subsequent graph/model work and its reported held-out measurements
are documented in [passage-graph.md](passage-graph.md). Those results do not close
the rolling-budget, all-suite, latency or exact-replay acceptance requirements.

No 90% recall claim is made. A learned embedding model, a learned cross-encoder,
and an actual OpenIE/synonym/PPR HippoRAG implementation were not installed or
validated here. The existing HTTP model/provider seams remain available, but
this machine's project environment has no torch, sentence-transformers,
transformers, or ONNX runtime and no cached text retrieval models. The existing
graph algorithm is not relabeled as HippoRAG. Source-bound answer expansion was
fixed and regression-tested, but no held-out model-backed second-hop study or
development-split tuning was performed. Autonomous unsourced memory still uses
its existing lifetime cap; the verified-summary exemption fixes the reported
summary blockage, not a general rolling-window budget redesign.

## Measurement follow-up — 2026-10-13

Local, uncommitted follow-up against `be29799f`:

- `eval/store_recall.py` now uses the shared ranked-document resolver. Working
  memory citations no longer create extra ranked hits; ambiguous ID-less
  projections and malformed citation containers do not earn retrieval credit.
- Latency p50/p95 use the harness's shared linear-interpolation percentile
  implementation. A synthetic report test checks 10/30 ms samples produce
  p50 20 ms and p95 29 ms.
- The public HippoRAG adapter has a synthetic CLI regression requiring identical
  serialized metrics and rankings with query shard sizes 1, 2 and 3. The test
  clears inherited `MNEMOSYNE_*` settings to avoid configured providers and
  sidecar paths; it also passed with deliberately invalid provider settings.
- Combined verification: `tests/test_public_hipporag.py`,
  `tests/test_retrieval_integrity.py`, `tests/test_store_recall.py`, and
  `tests/test_public_eval_scoring.py`: **42 passed**. Ruff and `git diff --check`
  passed for the changes. Separately, 26 LoCoMo scoring tests were skipped
  because the isolated pinned scorer environment was unavailable; they are
  not included in the passing count.
- A graph query-preparation regression also checks unchanged rankings across
  batch sizes 1, 2 and 64 with repeated questions and deterministic test
  providers. Including `tests/test_passage_graph.py` in the combined command
  above produced **83 passed** on October 13. This supersedes the smaller
  combined count, but does not substitute for real-model replay evidence.

No held-out benchmark or model-backed shard replay was run for this follow-up.
These tests do not establish efficiency thresholds, PostgreSQL acceptance or
full-suite readiness. Rolling-budget clock semantics await the user's decision
requested on October 12; automated continuations are not approval.

Bundle-efficiency follow-up: `_digest` hashes in 1 MiB chunks; four boundary
tests match ordinary SHA-256 without `Path.read_bytes`. Explicit LF writes for
the generated README and shell script fix Windows newline conversion and restore
the original frozen v1 bundle digest without repinning it. Eighteen focused
checks passed (digest tests, frozen-output test, public scoring tests).

Broader reproducibility verification remains incomplete: the symlink test fails
at setup with Windows privilege error 1314; the isolated clean-checkout command
test fails while `uv` resolves `setuptools>=70` due to PyPI DNS error 11003.
The combined run timed out after 45 seconds. Neither gate was weakened and no
full-suite success is claimed. The store-recall report also now labels
search-only latency and separately records query-vector preparation time;
both preparation paths are covered by synthetic tests.

The isolated M06 development-bundle round-trip subsequently completed with
exit code 0 (one test passed, session 13910). It verifies byte-identical replay
and rejection of metric, missing-trace, duplicate-trace and family tampering.
Four additional lifecycle tests passed for seed-set binding and the read-only
CLI provider gate. These bounded results do not clear the separate Windows
symlink or clean-checkout dependency-resolution failures above.
The M02 and M04 round-trips also passed separately (two tests, synthetic CLI).
All seven tests in the development-bundle lifecycle file have therefore passed
across the bounded runs; this is custody/plumbing evidence, not reader-quality
or held-out benchmark evidence.

Replay byte comparisons now use uncached 1 MiB chunk reads at all four existing
comparison sites; equality remains byte-exact rather than digest-only. Boundary
tests cover empty files, length differences, multiple chunks and late mismatches.
Fourteen helper/lifecycle tests passed with M06 excluded for that increment;
M06's earlier result predates the comparison change. Combined helper,
frozen-output and scoring verification subsequently passed 28 tests; Ruff and
diff checks passed.

A disposable 32 MiB synthetic hashing probe measured 2,229,282 bytes peak traced
Python allocation with streaming versus 33,554,666 bytes with a whole-file read,
with identical digests. This is helper-level allocation evidence, not process
RSS or acceptance of the scorer's 2 GB budget. Whole-bundle secret scanning and
materialized trace parsing still require bounded-memory work; their security
and schema checks must remain intact.

October 14 follow-up: all 11 streaming-helper tests passed, including explicit
read-size bounds, propagation of mid-stream I/O failures and closure of every
opened handle on failure. Ruff and diff checks passed. The later M06 run's
session output was unavailable after its process ended, so that run supplies
no additional acceptance evidence; post-comparison-change M06 verification
remains inconclusive.

Store-recall rows now additionally retain ordered full IDs in
`top5_evidence_cids`; the existing abbreviated `top5` display is unchanged.
This prevents same-prefix IDs from becoming indistinguishable when comparing
saved rankings. Five store-recall tests passed, including a prefix-collision
case under both query-preparation paths; Ruff and diff checks passed. This
adds replay evidence without claiming full deterministic replay acceptance.

Store-recall now registers engine cleanup immediately after loading tools so
indexing, query preparation and search failures close the copied store before
temporary-directory cleanup. Eight focused tests passed, including all three
failure stages, original-store preservation and absence of a partial report.
Ruff and diff checks passed. This is resource-lifecycle verification, not a
full efficiency measurement.

Combined October 14 verification passed all 22 selected tests in one run:
store-recall reporting/cleanup, streaming helpers, synthetic public shard
invariance, graph query-preparation batch invariance and the unchanged frozen
v1 bundle digest. This checks the local changes together; it does not replace
the outstanding M06, model-backed replay, platform or efficiency evidence.

Store-recall rejects empty question sets and empty, malformed or blank gold
CID lists before copying a store or loading providers. In particular an empty
gold prefix can no longer match every retrieved ID and inflate recall.
All 16 focused store-recall tests passed, including eight invalid-input cases;
Ruff and diff checks passed. Existing valid CID-prefix inputs remain supported.

An attempted SQLite extension of the synthetic public shard test stopped at
ingestion: `capture-batch` explicitly supports only the atomic local backend
(`cli.py`, `cmd_capture_batch`). The local case passed. The unsupported test
extension was removed, without changing the backend guard or skipping a
required assertion. Public-adapter shard evidence is local-only; SQLite and
Postgres need a backend-appropriate ingestion/replay path before parity can be
claimed.

The alternative SQLite single-capture path reaches a second explicit boundary:
`--evaluation-read-only` is restricted to local evaluation query/answer commands.
No guard was relaxed. A separate boundary regression test now confirms SQLite
evaluation is rejected before creating its store (one test passed; Ruff and
diff checks passed). This test records fail-closed behavior, not SQLite replay
success; cross-backend read-only evaluation remains an implementation gap.

Bundle verification now releases its concatenated secret-scan byte buffer as
soon as the scan succeeds, rather than retaining it during payload parsing and
scoring. Both scan paths preserve their original regex and concatenation
semantics. Thirteen focused tests passed (secret rejection, frozen v1 output
and streaming helpers); Ruff and diff checks passed. This reduces buffer
lifetime, not the scan's peak allocation; bounded-memory scanning is still open.

October 15: the four bundle JSONL parsing sites now iterate line boundaries
without materializing `splitlines()` lists. The shared iterator preserves all
11 Python line-separator forms, CRLF handling, blank lines and trailing-line
semantics; no malformed-line checks were relaxed. Twenty-four focused tests
passed, including separator parity, secret rejection and frozen v1 output;
Ruff and diff checks passed. The decoded input and parsed trace objects are
still materialized, so this is not fully streaming parsing or a 2 GB RAM claim.

A follow-up synthetic allocation probe over 200,000 80-character lines
(16,200,000 input characters) measured 25,824,056 peak traced Python bytes for
`splitlines()` versus 133,026 for the iterator, with identical consumed lengths.
The existing input string was allocated before tracing; these are neither RSS
nor whole-scorer measurements. Exhaustive combinations of ordinary text and
the ten single-character separators through length four matched Python's
`splitlines()` in all 16,105 cases, including mixed CR/LF boundaries.

After the line-iterator change, all five non-M06 development lifecycle tests
passed together, including M02/M04 byte-identical bundle round-trips and their
seed-set/provider gates. M06 was deliberately excluded; its outstanding
post-change verification and the other acceptance gaps are unchanged.

The line-iterator allocation reduction has a measured CPU tradeoff: on the
same 200,000-line synthetic input, five-run median consumption time was
0.022686 s for `splitlines()` and 0.279665 s for the iterator, with equal
16,000,000 consumed non-separator characters. This is about 12.3x slower for
line traversal alone (roughly 0.257 s extra for 16.2 MB), not an end-to-end
scoring timing. Do not describe the iterator as a throughput optimization;
the current evidence supports lower intermediate allocation only.

The boundary regex was subsequently factored to start with a separator
character class while consuming LF only after CR. All 16,105 parity cases and
22 helper tests still passed. On the same synthetic workload, five-run medians
were 0.153098 s for the revised iterator and 0.024871 s for `splitlines()`.
This reduces the earlier iterator overhead but remains slower than eager
splitting; no overall throughput or memory-budget acceptance is inferred.

The exhaustive 16,105-case separator comparison is now a retained regression
test rather than only an ad hoc probe. All 41 selected helper, store-recall,
secret-rejection and frozen-v1-output tests passed together on the revised
iterator; Ruff and diff checks passed. Broader acceptance gaps remain open.

M06 post-change verification was launched again after the material JSONL
iterator changes, selecting only the two M06 lifecycle cases. This run writes
JUnit evidence to
`C:/Users/Onfire/AppData/Local/Temp/mnemosyne-m06-replay-20261015.xml`
so a lost terminal handle need not lose the result. At launch it was pending;
neither the launch nor this note establishes a passing result.

The saved JUnit report subsequently confirmed both selected M06 cases passed:
2 tests, 0 failures, 0 errors, 0 skipped, 637.751 seconds total. The round-trip
case took 637.399 seconds; seed-set binding took 0.001 seconds. This supplies
post-comparison and post-parser-change M06 lifecycle evidence, replacing the
previously inconclusive status for those changes. It is not a held-out model
benchmark, and its test runtime must not be substituted for suite latency or
the benchmark's 600-second acceptance measurement.

Store-recall preflight also rejects missing IDs and missing, non-string or
blank question text before loading a store or preparing query vectors. This
avoids doing indexing/provider work for inputs that would fail later during
search or report construction. All 21 focused tests passed; Ruff and diff
checks passed. No restrictions on the type of an existing question ID were
added.

Independent BM25 source comparison (no held-out run): the Desktop benchmark
reference uses unique query terms (`set(toks(q))`), whereas `PassageIndex.scores`
weights each term by its query frequency (`Counter(tokenize(query))`). Both
use positive IDF and k1=1.2/b=0.75, but repeated-term queries therefore need not
have identical scores or rankings. This is a semantic difference, not evidence
that either implementation is defective. Exact independent-reference parity
must account for it rather than comparing the production implementation with
itself; no tokenizer or query-weight policy was changed.

A synthetic smoke comparison executed the independent script's unchanged
tokenizer/index/search block, excluding its dataset-loading and held-out loops.
Reference SHA-256:
`b817194599394932e6b4736b8fc2ba23832b39d935a23420c53d6646b480a3a8`.
For documents `mars`, `venus venus`, `clouds clouds venus`, ranked IDs matched
production for `mars`, `venus clouds`, `unknown` and `mars mars venus` (four
queries). This is limited rank concordance, not score equivalence, tokenizer
equivalence or held-out recall validation; the query-frequency difference
described above remains. No reference files or production policies changed.

Tokenizer probes further bound that concordance: the independent reference
removes stopwords and uses Unicode `\w+`; production retains stopwords and
preserves internal punctuation in ASCII tokens. Observed examples:
`the red planet` retains `the` only in production; `data-only v1.2` is two
production tokens versus four reference tokens; `café 東京` yields `caf` in
production versus the two intact Unicode words in the reference. These are
measured semantic differences, not a blanket correctness verdict. Independent
benchmark comparison must label the tokenizer difference, and exact parity
must not be asserted from the earlier four-query synthetic smoke check.

### SQLite evaluation-copy regression — 2026-10-16

Added a real SQLite integration test for `eval/store_recall.py`: capture one
synthetic memory, evaluate its temporary copy, require nonempty retrieved IDs
and zero recall for an intentionally unmatched gold ID, then compare every
source-store file byte-for-byte with its pre-evaluation snapshot. Inherited
`MNEMOSYNE_*` settings are cleared for this test to avoid configured providers.
The focused store-recall file completed with **22 passed**; Ruff and
`git diff --check` also passed. This verifies this synthetic evaluation-copy
path, not concurrent SQLite snapshot safety, public batch read-only support,
cross-backend replay parity, model-backed recall, or full-suite acceptance.

The follow-up source-preservation inspection found that `--out` could target
the original store despite evaluation using a copy. The evaluator now rejects
resolved output paths equal to or beneath the source directory before reading
questions or loading providers. Four regression cases cover the root, an
existing source file, a nested path and a `..` alias; source bytes remain intact.
All **26 store-recall tests passed**, along with Ruff and `git diff --check`.
This path guard is not a defense against concurrent filesystem-link changes
or external hard-link aliases, and does not change the broader acceptance gaps.

After that guard change, combined verification of `test_store_recall.py`,
`test_bundle_streaming_digest.py` and `test_retrieval_integrity.py` completed
successfully (exit 0, all 59 cases passed). This checks the accumulated evaluator,
bundle-helper and retrieval-integrity changes together; it is not a full-suite
or model-backed acceptance result. The completed M06 milestone was not rerun.

Fresh inspection on 2026-10-17 UTC found HEAD at `9b4e2895` (1.3.0), with
this chat's evaluator/bundle/test changes still uncommitted. On that combined
working tree, `test_passage_graph.py` and `test_public_hipporag.py` completed
with **57 passed, zero failures or skips**. This is focused compatibility
evidence after the HEAD change, not model-backed replay or full acceptance.
No release, branch, connector, or signed benchmark artifacts were modified
by this verification.

### Remaining scanner allocation — 2026-10-17 UTC

A synthetic allocation probe of the existing concatenation/decode/`SECRET`
search expression used eight preallocated ASCII byte buffers. For 2 MiB and
8 MiB total input, peak additional traced Python allocation was 4,194,858 and
16,777,290 bytes respectively (input buffers excluded). After releasing `raw`,
retained additional allocation was 480 and zero bytes. Thus releasing the
buffer prevents retention during parsing but does not make secret scanning
bounded-memory: this probe still adds approximately twice the input size at
peak. These are synthetic Python allocation measurements, not process RSS,
whole-verifier measurements, or proof of the 2 GB scorer acceptance target.
The cross-file and unbounded-header scanner semantics remain unchanged.

The next increment compiles the same ASCII-only pattern for bytes and applies
it directly to the concatenated bytes at both verification sites. This removes
the full decoded string without introducing chunk boundaries or shortening
the unbounded private-key header. Replacement decoding cannot create ASCII
characters from non-ASCII bytes, so these ASCII-only matches are preserved.
Regression coverage compares byte/text matching with all 256 byte values at
marker edges and an interior position, long headers, short nonmatches and
multibyte Unicode surroundings. All 24 helper tests and the existing fail-closed
secret test passed; Ruff and diff checks passed. An 8 MiB ASCII probe measured
8,388,913 additional peak Python bytes, versus the prior 16,777,290-byte probe.
This removes one whole-input allocation, not concatenation itself: scanning
still scales with bundle size, and full RSS/efficiency acceptance remains open.

Post-change integration coverage also verifies a 10,000-character header split
across adjacent bundle files, with malformed UTF-8 outside the marker: the
canonical verifier rejects it before parsing. All 25 helper tests passed.
Five additional frozen-schema/output, exact-digest and one-byte-tamper checks
passed after the byte-scanner change (zero failures/skips). No fixtures or
signed history were rewritten; this remains selected verification, not a
full reproducibility-suite result.

A separate seven-run CPU probe on a preallocated 8 MiB ASCII no-match buffer
measured median decode-plus-text search at 0.032378 s (range 0.030575–0.038404)
and direct byte search at 0.029000 s (range 0.027629–0.031388). This narrow probe
excludes file I/O, concatenation and parsing; the overlapping ranges do not
establish a general throughput improvement. It does not measure adversarial
regex inputs or satisfy full benchmark latency/efficiency acceptance. Newly
observed framework/release edits were left untouched during this measurement.

Static inspection identifies why current size checks cannot establish the RAM
target: the reproducibility schema permits up to 4,096 hash entries and the
loader applies a 16 MiB per-file bound, not an aggregate byte bound. Their
product alone is 64 GiB; this is a bound calculation, not a claim that a bundle
of that size passes all semantic checks. `_inventory_bytes` also reads directory
entries before rejecting inventory extras. Consequently neither per-file
validation nor the removed decoded copy proves a 2 GB peak. No large input was
allocated, no new rejection policy was introduced, and no unrelated edits were
touched. A future bounded-memory implementation must preserve validation and
cross-file scanner semantics rather than simply imposing an unstated quota.

On the newer `d81ae5a0` (1.5.0) working tree, combined passage-graph,
public-HippoRAG and store-recall verification completed with **83 passed,
zero failures/skips**. This supersedes the older-head compatibility evidence
for those selected files only; it does not validate model-backed replay,
Postgres, the full suite or the efficiency thresholds. No M06 or held-out
benchmark was rerun.

Inventory validation now decodes only JSON/JSONL payloads, avoiding unused text
allocations for lockfiles and other raw artifacts. A regression uses a byte
payload whose `decode` raises, verifies that its original bytes are returned,
and checks that an incorrect digest still fails closed. All 26 helper tests,
Ruff and diff checks passed. JSON parsing and whole-bundle secret scanning
remain in place; this is not a full bounded-memory implementation.

Five targeted integration tests passed after that change: malformed/deep JSON
rejection, scanning and rejection of an unhashed lock-named file, preventing
its reproduction, sibling-lock inventory rejection, and mutated command/lock
rejection before destination creation. Zero failures/skips; this does not
replace the outstanding full reproducibility and platform verification.
