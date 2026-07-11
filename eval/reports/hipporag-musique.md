# Public evaluation report: hipporag-musique

This report is non-publishable, not PBPP headline eligible, and is not an independent external reproduction.

- External report SHA-256: `85e063aa81fed06e2f1c8e36b8311207fc18912357f3fdbf73e1e6243e6eda76`
- Source bundle manifest SHA-256: `6167926faad5fd95f3d8d340fead4c5d17495abd6faa5f88c361e3e91c508277`
- Reproduced bundle manifest SHA-256: `6167926faad5fd95f3d8d340fead4c5d17495abd6faa5f88c361e3e91c508277`
- Git SHA: `ceb35a884ceadaa5d3e81f4d9409d949d50d7dd6`
- Generated at (UTC): `2026-07-11T05:12:59.307179Z`

## Assets and benchmark metadata

```json
{"assets":[{"citation":"Trivedi et al., MuSiQue (TACL 2022)","contamination":"Upstream warns seed questions may overlap training data; pinned sample ships no machine-readable exclusion IDs, so applied exclusion count is zero; no tuning permitted","filename":"musique.json","license":"CC-BY-4.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"98ed4e21d3076532f6388d42320fb809599c63a0d8dffca8ece5e41922be6b46","split_role":"held-out-validation"},{"citation":"Trivedi et al., MuSiQue (TACL 2022)","contamination":"Released HippoRAG 2 corpus; no tuning permitted","filename":"musique_corpus.json","license":"CC-BY-4.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"73157a03ce3f0b1a5673dd5dc12bb970c24976dbffc688af9eecdd758c97ffcb","split_role":"evaluation-corpus"}],"benchmark_metadata":{"adapter":"hipporag-multihop","assets":[{"citation":"Trivedi et al., MuSiQue (TACL 2022)","contamination":"Upstream warns seed questions may overlap training data; pinned sample ships no machine-readable exclusion IDs, so applied exclusion count is zero; no tuning permitted","filename":"musique.json","license":"CC-BY-4.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"98ed4e21d3076532f6388d42320fb809599c63a0d8dffca8ece5e41922be6b46","split_role":"held-out-validation"},{"citation":"Trivedi et al., MuSiQue (TACL 2022)","contamination":"Released HippoRAG 2 corpus; no tuning permitted","filename":"musique_corpus.json","license":"CC-BY-4.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"73157a03ce3f0b1a5673dd5dc12bb970c24976dbffc688af9eecdd758c97ffcb","split_role":"evaluation-corpus"}],"dataset_sha256":"7c0cbd3382c77d10139eeee25c93f4ff751171931eb1509a6111ce3b03da94f9","family":"deterministic-retrieval","independent_external_reproduction":false,"interval_method":"bootstrap","license":"CC-BY-4.0","pbpp_headline_eligible":false,"publishable":false,"revision":"ad30fc3e2062202d9e975e32cd28212424a56ccb","scoring_profile":"hipporag-retrieval-v1","split_role":"held-out-validation","suite":"hipporag-musique"}}
```

- Eligible records: `1000`
- Excluded records: `0`

## Metrics

```json
{"family":"deterministic-retrieval","interval":{"confidence":0.95,"high":0.09183333333333332,"iterations":2000,"low":0.06975,"method":"bootstrap","seed":1234},"intervals":{"recall_at_2":{"confidence":0.95,"high":0.09183333333333332,"iterations":2000,"low":0.06975,"method":"bootstrap","seed":1234},"recall_at_5":{"confidence":0.95,"high":0.117,"iterations":2000,"low":0.09158333333333332,"method":"bootstrap","seed":1234}},"metrics":{"recall_at_2":0.08083333333333333,"recall_at_5":0.10416666666666667},"profile":"hipporag-retrieval-v1","profile_version":1,"total":1000,"trace_count":1000}
```

## Reproduction and provenance

```json
{"command":["mneme","eval-public","--write-report","/Users/admin/mnemosyne-public-artifacts/hipporag-musique","--reproduced-bundle","/Users/admin/mnemosyne-public-artifacts/hipporag-musique-reproduced","--report-output","/Users/admin/mnemosyne-public-artifacts/hipporag-musique-report.json","--report-note","/Users/admin/Mnemosyne/eval/reports/hipporag-musique.md"],"provenance":{"build":{"environment_contract":"uv run --locked","system_seam":"public-cli-subprocess","version":1},"source_bundle":"/Users/admin/mnemosyne-public-artifacts/hipporag-musique","system_seam":"public-cli-subprocess"},"reproduction":{"matched_files":["README.md","benchmark.json","build.json","config.json","judge.json","metrics.json","reproduce.sh","traces.jsonl"],"reproduced_bundle":"/Users/admin/mnemosyne-public-artifacts/hipporag-musique-reproduced","verified":true}}
```
