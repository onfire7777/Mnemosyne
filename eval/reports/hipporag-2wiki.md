# Public evaluation report: hipporag-2wiki

This report is non-publishable, not PBPP headline eligible, and is not an independent external reproduction.

- External report SHA-256: `7856c425c913d61db62caefc3af033c53d76ed406b27a4ebc190dd9f88951abe`
- Source bundle manifest SHA-256: `dfdbd61f14ae62eda7cfe21058f2d7354c48f1b6e26cd134302855c352d97626`
- Reproduced bundle manifest SHA-256: `dfdbd61f14ae62eda7cfe21058f2d7354c48f1b6e26cd134302855c352d97626`
- Git SHA: `8944443bcbd92716c9e5bd0aa4ca06b185c64ec5`
- Generated at (UTC): `2026-07-11T05:23:50.146970Z`

## Assets and benchmark metadata

```json
{"assets":[{"citation":"Ho et al., 2WikiMultiHopQA (COLING 2020)","contamination":"Released HippoRAG 2 validation sample; no tuning permitted","filename":"2wikimultihopqa.json","license":"Apache-2.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"895cba294064df0c3302c76847b1fc08d99b5619f7663dfaa3b65cd780f1cac4","split_role":"held-out-validation"},{"citation":"Ho et al., 2WikiMultiHopQA (COLING 2020)","contamination":"Released HippoRAG 2 corpus; no tuning permitted","filename":"2wikimultihopqa_corpus.json","license":"Apache-2.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"9d6e352952aafb18dab22bf8195039461321a44a949df902ae83bce134ad238a","split_role":"evaluation-corpus"}],"benchmark_metadata":{"adapter":"hipporag-multihop","assets":[{"citation":"Ho et al., 2WikiMultiHopQA (COLING 2020)","contamination":"Released HippoRAG 2 validation sample; no tuning permitted","filename":"2wikimultihopqa.json","license":"Apache-2.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"895cba294064df0c3302c76847b1fc08d99b5619f7663dfaa3b65cd780f1cac4","split_role":"held-out-validation"},{"citation":"Ho et al., 2WikiMultiHopQA (COLING 2020)","contamination":"Released HippoRAG 2 corpus; no tuning permitted","filename":"2wikimultihopqa_corpus.json","license":"Apache-2.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"9d6e352952aafb18dab22bf8195039461321a44a949df902ae83bce134ad238a","split_role":"evaluation-corpus"}],"dataset_sha256":"552b4f01f9ede2d5e024a33577fc9dada544a4c369c1ba556b628e093c037c8e","family":"deterministic-retrieval","independent_external_reproduction":false,"interval_method":"bootstrap","license":"Apache-2.0","pbpp_headline_eligible":false,"publishable":false,"revision":"ad30fc3e2062202d9e975e32cd28212424a56ccb","scoring_profile":"hipporag-retrieval-v1","split_role":"held-out-validation","suite":"hipporag-2wiki"}}
```

- Eligible records: `1000`
- Excluded records: `0`

## Metrics

```json
{"family":"deterministic-retrieval","interval":{"confidence":0.95,"high":0.189,"iterations":2000,"low":0.16075,"method":"bootstrap","seed":1234},"intervals":{"recall_at_2":{"confidence":0.95,"high":0.189,"iterations":2000,"low":0.16075,"method":"bootstrap","seed":1234},"recall_at_5":{"confidence":0.95,"high":0.2535,"iterations":2000,"low":0.221,"method":"bootstrap","seed":1234}},"metrics":{"recall_at_2":0.17525,"recall_at_5":0.23725},"profile":"hipporag-retrieval-v1","profile_version":1,"total":1000,"trace_count":1000}
```

## Reproduction and provenance

```json
{"command":["mneme","eval-public","--write-report","/Users/admin/mnemosyne-public-artifacts/hipporag-2wiki","--reproduced-bundle","/Users/admin/mnemosyne-public-artifacts/hipporag-2wiki-reproduced","--report-output","/Users/admin/mnemosyne-public-artifacts/hipporag-2wiki-report.json","--report-note","/Users/admin/Mnemosyne/eval/reports/hipporag-2wiki.md"],"provenance":{"build":{"environment_contract":"uv run --locked","system_seam":"public-cli-subprocess","version":1},"source_bundle":"/Users/admin/mnemosyne-public-artifacts/hipporag-2wiki","system_seam":"public-cli-subprocess"},"reproduction":{"matched_files":["README.md","benchmark.json","build.json","config.json","judge.json","metrics.json","reproduce.sh","traces.jsonl"],"reproduced_bundle":"/Users/admin/mnemosyne-public-artifacts/hipporag-2wiki-reproduced","verified":true}}
```
