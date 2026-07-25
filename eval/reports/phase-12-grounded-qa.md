# Phase 12 Grounded QA Evidence

Status: in progress — consumed v3, v13, v17, and v18 frozen runs remain below threshold; no held-out result exists.

## Preregistered Candidate

- Protocol source: candidate v19; external post-commit manifest pending
- Decomposer: deterministic `mnemosyne-extractive-hop0-v1`, exact policy-spec digest
  `623c47250430e7f3a00ce0f11053b9c5397d2efcddd89428b556c507fb50805d`
- Decomposer implementation SHA-256:
  `1f00f376e79385a52fabd6fd2013d993b4f6eae84cda1e4d0065d462f97e9c6b`
- Reader: local Ollama `qwen3:8b`, exact content digest
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`
- Transport retries: zero; maximum attempts per protected split: one
- Evidence: at most 20 records, 24,000 characters, and 3 hops
- Canonical abstention: empty answer, empty claims, `abstained=true`
- Candidate manifest: must be created outside the repository after a clean
  candidate commit and immutable commit-addressed runtime installation

## Prepared Gates

- Public-CLI-only internal QA evaluator with frozen-dataset execution guard
- Scorer-only gold labels and payload-isolation tests
- LongMemEval-QA question-set/answer anchoring with separate reader columns
- Hippo reader EM/F1 and provenance-linked graph/PPR participation columns
- Exact Phase 11/internal retrieval no-regression comparator
- Candidate/report custody and non-publication schema

## Results

The v3 `qa_hard_v2` one-shot was consumed and returned 24/24 empty
abstentions with zero retrieval hops. Aggregate-only diagnosis identified the
systemic pre-provider query-support gate; no protected question, trace, or
content was inspected. LongMemEval-QA and Hippo reader evaluation remain not
run. At that checkpoint, a new committed v9 candidate was required before any
further protected action.

Candidate v4 was rejected at the synthetic live-model gate because its initial
query used inferred intent terms rather than an independently retrievable
literal anchor. It never reached a protected run and has no attempt ledger.

Candidate v5 was also rejected at the synthetic direct-provider gate: the
model returned a possessive entity plus a general intent noun. It never reached
a protected run and has no attempt ledger. Candidate v6 adds deterministic,
source-bound anchor normalization before ordinary retrieval.

Candidate v6 was rejected at the synthetic exact-runtime gate. An external,
never-protected diagnostic transcript showed that the evidence-aware model
omitted `Helios` and the reader emitted contradictory unresolved claims with a
malformed CID. Candidate v6 never reached a protected run and has no ledger.
Internal diagnostics: `~/.local/share/mnemosyne/diagnostics/v6-synthetic-transcript/`
(`result.json` SHA-256 `a700ccd6546f8b02c9eac32097c17c91247d72ec3b7b7c6724f102501b68218a`,
`transcript.jsonl` SHA-256 `2d484f7f49dee2cf5018d0aa8e970d19575a6461d053ac96dca4164c7b2ef644`).

Candidate v7 was rejected at the synthetic exact-runtime reader gate when
Ollama returned a claims/unresolved contradiction despite the dynamic XOR
schema. It never reached a protected run and has no ledger. Diagnostics:
`~/.local/share/mnemosyne/diagnostics/v7-synthetic-transcript/`
(`result.json` SHA-256 `865be871bd417f68ba653c417b3610a95c5c846c36005ff35feea2f3c4d33e85`,
`transcript.jsonl` SHA-256 `d0e611354f89582578b4dc4a42bc1ff712d92542edc3188ab0a01bd73f828812`).

Historical candidate v8 (retired) passed structural retrieval but corrupted exact evidence text
(`Q3 2026` became `Q3 2:026`) at the synthetic reader gate. It never reached a
protected run and has no ledger. Candidate v9 makes model-authored claim text
impossible by selecting replay-validated raw evidence spans.
Candidate v9 public traces retain rendered claim text plus only privacy-safe
span custody (`cid`, Unicode code-point `start`/`end`, and UTF-8
`slice_sha256`). Bundle verification reconstructs each slice and the
single-space rendering from the benchmark capture corpus and exact authorized
CID mapping rather than trusting trace self-attestation.
Candidate v9's model-authored offset selector failed synthetic exact-answer
quality and never reached protected evaluation; it has no protected ledger.
Candidate v10 replaces authored offsets with exact `{cid, quote}` selection.
The application rejects any non-substring and deterministically selects the
lowest raw Unicode code-point occurrence before deriving the unchanged public
offset and hash custody. The installed `qwen3:8b` manifest digest above was
verified locally for synthetic-only preparation; no protected run was made.
Candidate v10 was rejected at the repeated synthetic exact-answer gate because
both deterministic runs returned the full supporting sentence instead of the
shortest answer value. Retrieval remained perfect and two-hop; it never reached
protected evaluation and has no protected ledger. Candidate v11 makes the
answer-only minimality contract explicit while preserving exact raw-substring
selection, zero retries, and all frozen retrieval and authorization rails.
Candidate v11 was rejected at the repeated synthetic exact-answer gate for the
same full-sentence output and likewise has no protected ledger. Candidate v12
adds one generic, non-benchmark contrastive contract example so the local model
must distinguish an answer value from its supporting sentence; no rail, schema,
model, budget, or retry setting changes.
Candidate v12 passed the repeated synthetic gate, then consumed its protected
attempt without a benchmark result because the outer CLI batch wrapper timed
out at 120 seconds. The ledger exists, the result file does not, and no
question-level protected data was inspected. Candidate v13 raises only that
outer frozen-batch process bound to 3,600 seconds; per-provider timeouts, zero
retries, protocol content, retrieval rails, and answer custody are unchanged.

Candidate v13 passed both repeated immutable-runtime synthetic gates, then its
single protected `qa_hard_v2` attempt completed with 24/24 canonical
abstentions, zero retrieval hops, zero claims, EM/F1 0, and Recall@5/nDCG@5 0.
Only these aggregate metrics and structural counts were inspected; no protected
question, answer, trace content, or per-ID failure was read. Result SHA-256:
`af3497af93d07abe86217cc7cfb8408ae3b41e38dd94cb67be23d7c76242ee2d`.
Attempt-ledger SHA-256:
`3addbc57c640c64c8bbc807bbcce348075ff3e54e10374c4fc1b851a5c3c3a9e`.
The held-out LongMemEval and Hippo reader runs remain blocked by the frozen QA
threshold, and publication flags remain false.

Candidate v14 addresses only the aggregate zero-hop class without inspecting
protected content: when a model proposal contains no recognized entity, the
normalizer may recover the exact token-identical source span as a query. The
fallback rejects command/policy terms and Unicode-confusable control labels,
retains the existing entity path when available, and still sends every query
through the unchanged retrieval support and authorization gates.

Candidate v14 passed the original entity synthetic case twice but failed the
new lowercase literal case twice: the first hop retrieved only the ownership
record, and the reader returned that record instead of the answer. It never
reached protected evaluation and has no ledger. Candidate v15 retains the exact
literal proposal and, only on the fallback path, adds trailing substantive
source tokens in reverse order within the existing four-query budget. This
lets lowercase bridge terms participate without changing any retrieval rail.

Candidate v15 failed both lowercase synthetic repetitions at hop 0 and has no
protected ledger. Synthetic-only direct decomposition showed the proposal
`project cobalt launch`; expanding the question predicate created an
unsupported mandatory query. Candidate v16 therefore keeps hop 0 to the exact
literal proposal and enables trailing-token expansion only on later hops, where
the source is authorized retrieved evidence.

Candidate v16 passed the entity case but repeated the first lowercase record in
both literal repetitions and has no protected ledger. Synthetic-only
evidence-aware decomposition confirmed the model repeated `project cobalt`
instead of proposing the unseen bridge. Candidate v17 extends deterministic
later-hop traversal to safe substantive tokens from authorized evidence in
reverse source order; control ranges, deny terms, budgets, and ordinary
retrieval authorization remain enforced.

Candidate v17 passed all four expanded synthetic gates, then its single
protected attempt answered 2/24 with three hops and canonical claims while 22
items abstained at zero hops. Aggregate-only metrics were EM/F1
`0.08333333333333333`, Recall@5 `0.08333333333333333`, and nDCG@5 `0.0625`.
No protected content or per-ID result was inspected. Result SHA-256:
`908d50dd3ce340ba09ccb1e248749d175b11cb5d1a96b2a1bcb484d0cfb69d11`;
ledger SHA-256:
`c3826c2e7f4777e9361086e7648ad7adcee3786f8cb1d50436ee7e6fa1d7fe45`.
Candidate v18 adds a fail-closed partial-proposal fallback: when no full literal
span matches, select only the longest substantive source token also present in
the proposal. Control and command terms remain ineligible, and the selected
token still passes through ordinary retrieval and authorization.

Candidate v18 passed all four expanded synthetic gates, then reproduced v17's
protected aggregate exactly: 2/24 answered, 22 zero-hop abstentions, EM/F1
`0.08333333333333333`, Recall@5 `0.08333333333333333`, and nDCG@5 `0.0625`.
No protected content or per-ID result was inspected. Result SHA-256:
`9c3fbb85704afceeff9a23d30fc6cabcc1f8e8aa80db9f1fb7d9ff2f300e303d`;
ledger SHA-256:
`5d68a738b3e3f7270e0f802a31c07e3425bf94516956df4027a2efb9a5781c41`.
Because v18 made no aggregate improvement, no v19 candidate was preregistered
at that checkpoint; the next action was synthetic-only redesign, not another
speculative protected attempt. Phase 12 evaluation already uses host Ollama 0.24.0 directly at
`127.0.0.1:11434` with `qwen3:8b` on 100% GPU, so the production Colima
performance apply would not accelerate this evaluator and remains deferred.

A host-Metal `qwen3:14b` feasibility probe was rejected before
preregistration: the model occupied 9.8 GB at 100% GPU on the 16 GB host,
reduced free memory to roughly 60 MB, and failed to produce a trivial one-token
response within 300 seconds. Repeating the probe with Colima fully stopped
still produced no trivial response within 95 seconds, ruling out the VM's
reservation as the limiting cause. The model is installed externally for
possible future use on larger hardware, but it is not a candidate on this
machine.

A synthetic-only `qwen3.5:9b` probe was also rejected before preregistration.
The 6.6 GB model fit with the production VM active and completed a cold trivial
request in 39.237 seconds, but it reproduced the decisive decomposition defect:
given the lowercase question it proposed `project cobalt`, and after receiving
authorized evidence that project cobalt belongs to team juniper it again
proposed `project cobalt` instead of the newly exposed bridge. No protected
attempt or ledger was created. A model substitution must demonstrate a real
bridge-selection gain before it can become a custody-bound candidate.

Two final task-specialized reader-family probes were stopped at the same
synthetic boundary. `ministral-3:8b-instruct-2512-q4_K_M` fit the active host
topology but returned an empty query list for the lowercase hop-0 Project
Cobalt case. `granite3.3:8b` returned two nonliteral invented search phrases at
hop 0; after authorized evidence exposed Team Juniper, it generated two more
Project Cobalt questions instead of selecting the new bridge. Neither model
reached answer-minimality, scale preflight, preregistration, or protected
evaluation. These results close model substitution as the immediate strategy.
At that checkpoint, the next protocol had to disclose decomposition separately
from the reader and pass a broader synthetic matrix before becoming candidate
v19.

Candidate v19 now wires a separately disclosed extractive hop-0 planner. It
emits at most one exact substring of the question, fails closed on
custody/control terms, and deliberately emits no proposal once authorized
evidence exists; the already-tested orchestrator remains the sole owner of
later-hop authorized-evidence traversal and seen-query filtering. A
versioned 16-case development matrix covers proper and multiword names,
acronyms, mixed alphanumerics, lowercase project/archive identifiers,
hyphenation, generic marker use, marker-plus-intent cases, missing identifiers,
deny terms, and Unicode-confusable control labels. Runtime, environment,
candidate-manifest, registry, public-bundle, and verifier custody bind the
decomposer policy spec and exact implementation bytes independently from the
reader. Candidate v19 still requires its
external post-commit manifest, repeated synthetic validation, and the
24-question exact-wrapper receipt before any protected attempt.

The 2026-07-12 formal local admission retry failed before any suite or model
work: the three memory-free samples were 24%, 25%, and 22% against the required
55% floor. A follow-up audit found both the current Colima stack and an older
Docker Desktop stack live from the same compose project, with Desktop owning
host port 443 and retaining divergent persistent data.

The authorized cutover selected Colima as canonical. Desktop writers were
stopped before logical export; password-free globals plus `mnemosyne`,
`keycloak`, and `mnemosyne_row10` custom dumps were stored outside the
repository at
`/Users/admin/mnemosyne-runtime-backups/20260712T220109Z-desktop-linux-pre-cutover/`.
All three custom dumps passed `pg_restore --list`, all four files are mode
`0600`, and their SHA-256 values are respectively
`43499bd8a4699678a362a19b1ead3d32c8eb15eda51452f405dcef53d3c48142`,
`308cd408b319fbb613a7f43bd0a29e22e4b3d0aea4d0daf5da1d901eb84d203f`,
`351595b7d88feab24628a8951f54731383883a49b55fcb869d3c3ee8db1360a1`,
and `011d04b4b15b621f959dd3df5559a300d6d1f4aa92ac925530980d820a5c3293`.
The Desktop VM and all of its containers are stopped; its engine-local volumes
remain intact as a rollback source. Divergent databases were not blindly
overwritten or merged.

Independent live verification corrected the earlier restart-loop diagnosis:
TLS succeeds through the exact dual-root bundle mounted by API/stream and
reaches Vault, which returns HTTP 503 because it is sealed. The initialized
Vault is Shamir 1-of-1, not the documented 5-of-3 intent. API/stream therefore
fail closed while loading the Vault-backed session keyring and were stopped
after more than 1,300 retries each. Recovery requires the sole operator-held
unseal key through an interactive non-logged surface. Separate maintenance is
required to rotate the still-valid Vault leaf from its retained older Step CA
generation to the current root. No admission threshold changed, and no
candidate, exact-scale, held-out, or protected attempt was consumed.

Earlier cutover checkpoint (superseded below): after closing Cotypist at
roughly 3.36 GiB RSS, one lightweight sample reached
56% free memory with acceptable host load and no resident model. The four
runbook-authorized planning/status truth checks passed serialized. This is not
a formal three-sample full-workload admission: Vault remains sealed and the
canonical API/stream services remain intentionally stopped. A source-only
bootstrap fix also stages changed Step CA roots and refuses automatic trust-
bundle replacement; its red-green regression plus `bash -n`, ShellCheck, Ruff,
and the three existing synthetic Vault TLS validator cases pass. No candidate,
model, exact-scale, or protected work ran.

The original one-share recovery file was subsequently found outside the
repository at `/Users/admin/mnemosyne-prod-secrets/vault-init.json`. File type,
owner, mode `0600`, one-key schema, and decoded key length matched the live
initialized Shamir 1-of-1 Vault. The key was supplied only over hidden PTY
input and never entered argv, environment, output, logs, history, or source.
Vault now reports `sealed:false`; API and stream restarted with stable zero
restart growth, Caddy reclaimed port 443, and the obsolete interactive prompt
was closed.

An authenticated ingress check then found that the independent short-lived MCP
client certificate had expired. A fresh pair was issued under the unchanged
JWK duration policy, staged and validated against the exact client-auth chain,
published with the old pair retained externally, and the mounted blackbox and
operator consumers were recreated. Both `/health` and `/stream/healthz` return
HTTP 200 over TLS 1.3 with required client authentication.

The post-recovery formal admission samples were 50%, 47%, and 48% free memory,
so the unchanged 55% full-workload floor still rejects suites, models, indexes,
exact-scale evaluation, and protected capture. All other sampled rails passed:
load bounds, no resident model, one active Colima `infra` project, no
restarting/unhealthy service, Vault unsealed, and stable API/stream restart
counts. The pre-hardening live Vault/MCP validation remains preserved as
recovery evidence. Under the separate lightweight >=35% rule, post-hardening
Bash syntax, ShellCheck, Ruff, and 22 focused TLS/bootstrap cases pass. The
focused regressions categorically reject a real empty-password encrypted PKCS#8
key and legacy `Proc-Type: 4,ENCRYPTED`; live Vault/MCP validation was not rerun
after the validator hardening. This recovery consumed no candidate, held-out,
or protected attempt and changes no benchmark threshold.

Future protected attempts now require a no-overwrite, candidate/runtime-bound
receipt from the canonical 24-question `qa_scale_dev_v1` dataset. The exact CLI
batch wrapper must complete all 24 traces with no abstentions, EM/F1 1.0, and
Recall@5/nDCG@5 1.0 under the same 3,600-second outer bound. The frozen attempt
ledger binds the receipt digest before execution, preventing another
small-synthetic-pass/large-wrapper-timeout loss like v12.

No CAP-001/CAP-002/CAP-003/BENCH-005 completion or public number is claimed.

---

## 12-04-02 — Public-CLI-only internal evaluator (lease-12-04-02)

**Status:** Evaluator surface **complete**; live measured gates **not met** → **CAP-003 remains Partial**.
**Updated (UTC):** 2026-07-24T18:08:19Z (mne-implement F-1 path-2 + F-2 graph_evidence + re-validation @ `3239d30`)
**Task:** Run frozen `qa_hard_v2` through a public-CLI-only internal reader evaluator with scorer-isolated gold.

### Bound custody (immutable 12-04-01 freeze)

| Field | Value |
|-------|--------|
| freeze_path | `/home/runner/.local/share/mnemosyne/candidates/phase12-v19/candidate-manifest.json` |
| candidate_version | `phase12-candidate-v19` |
| git_sha | `df438ca34061467ecc227bcf4d45bb1f7e886aee` |
| candidate_manifest_sha256 | `e81fc655f81ab43f1cfd5ad1b8644a9271a190027c49233efe89a2dd682c95f3` |
| dataset | `eval/datasets/v2/qa_hard_v2.json` (`dataset_id=qa_hard_v2`, 24 queries) |
| dataset_sha256 | `1864974807f2171904a5e5f04b727b3cbfb258f94c1280106ecc08a4dade52e2` |
| scorer | `qa-em-f1-v1` (Wilson EM interval + bootstrap token F1) |
| evaluator module | `eval/datasets/v2/run_grounded_qa_v2.py` |

### Evaluator contract (implemented + unit-proven)

1. **Public-CLI-only path:** capture + `eval_answer_batch` via CLI driver; gold fields never appear in capture/answer JSONL payloads (`gold_answer`, `gold_aliases`, `relevant_doc_ids`, `distractor_answer` scorer-only).
2. **Full frozen set once:** loads canonical `qa_hard_v2` (24 cases); answer order must match dataset order (order drift hard-fails; **no** per-question ID patch / selective re-run surface).
3. **Reader traces:** each row carries answer, claims, hops, reader disclosure, retrieved doc ids, `scoring_family=qa`.
4. **Report columns projected by `evaluate` + `attach_custody`:**
   - EM / token F1 + intervals (`qa.metrics`, `qa.intervals`)
   - Grounding rails: abstained, unsupported_claims, fabricated_citations, second_hop, graph_participation
   - Retrieval Recall@5 and nDCG@5
   - External `candidate_manifest_sha256`, `candidate_git_sha`, optional `candidate_version`
5. **Failure policy:** failed candidate → new preregistered version only; attempt ledger + result paths are external O_EXCL no-overwrite.

### Validation (automated)

```bash
uv run --locked python -m pytest tests/test_grounded_qa_v2.py tests/test_public_requirement_truth.py -q
```

Pack result: **pass** (includes synthetic gold isolation, 24-case once dry-run against frozen corpus with public-CLI stand-in, custody bind constants, order-drift refusal, scale preflight, exclusive external paths).

Re-validation this cycle (`mne-implement` / unit residual, 2026-07-24T18:08:19Z @ `3239d30`):

- `tests/test_grounded_qa_v2.py` + `tests/test_public_requirement_truth.py` → **pass** (20+5)
- F-1 path-2: `test_cap_003_honesty_pins_live_in_lease_a_suite` dual-homes CAP-003 Partial honesty on primary suite (Plan path-1 truth file also CLEAR)
- F-2: `evaluate()` projects `graph_evidence` (forward CLI dict or derive `participated` from hop `graph`/`ppr` channels) — `test_evaluate_projects_graph_evidence_for_qa_report_dual_path`
- Ollama `127.0.0.1:11434` → **unreachable** (no live protected attempt; CAP-003 remains Partial)
- Residual unit pins: exact answer payload shape, frozen one-shot fail-closed gates, no per-QID patch surface, CAP-003 Partial until measured EM/F1 ≥ 0.85
- Handoff: `.agentsmesh/handoff/implement.md` → **ready-for-review / ready-for-test** *(historical: that handoff file lived on the build fleet's staging branch, which was retired 2026-07-25; the path no longer resolves. The evidence recorded above is unaffected.)*


### Live protected / host measurement residual

| Gate | Required | Measured under this lease |
|------|----------|---------------------------|
| Internal EM | ≥ 0.85 | **Not re-measured live** (host Ollama `127.0.0.1:11434` unreachable in this workspace) |
| Token F1 | ≥ 0.85 | **Not re-measured live** (same) |
| Recall@5 | 1.0 | **Not re-measured live** |
| nDCG@5 | 1.0 | **Not re-measured live** |
| Grounding rails | pass | **Not re-measured live** |

**Last protected aggregates on prior candidates (unchanged; not v19 live):**

- v17 / v18 protected `qa_hard_v2`: EM/F1 `0.08333333333333333`, Recall@5 `0.08333333333333333`, nDCG@5 `0.0625` (2/24 answered; aggregate-only; no per-ID inspection).
- v19 freeze is bound above; a new live one-shot still requires scale preflight receipt + attempt ledger + runtime manifest + Ollama under the frozen CLI path. That live attempt was **not** consumed under lease-12-04-02 in this workspace.

### CAP / BENCH truth

| Requirement | Status after 12-04-02 | Notes |
|-------------|----------------------|--------|
| **CAP-003** | **Partial** | Evaluator + custody + gold isolation + 24-case once contract proven; **no** measured EM/F1 ≥ 0.85 on frozen live run |
| **BENCH-005** | **Partial** | Held-out LongMemEval/Hippo remains 12-04-03 (not admitted) |
| CAP-001 / CAP-002 | Partial | Outside this task’s close criteria |

**Explicit non-claims:** no CAP-003 Complete; no BENCH-005 Complete; no held-out run; no registry self-SHA rewrite; no per-question patch of frozen IDs; no mutation of external freeze `phase12-candidate-v19`.
