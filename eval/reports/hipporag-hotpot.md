# Public evaluation report: hipporag-hotpot

This report is non-publishable, not PBPP headline eligible, and is not an independent external reproduction.

- External report SHA-256: `d4b55046b114b8d7241a794392f375c152f11700a42fef454315b149636ade34`
- Source bundle manifest SHA-256: `a7df98161a307b44bff44c9892b83728ff6269ebc233c2be377552f3345032fa`
- Reproduced bundle manifest SHA-256: `a7df98161a307b44bff44c9892b83728ff6269ebc233c2be377552f3345032fa`
- Git SHA: `ad4f722cc01320107dcc645fd8d446a80ef618fd`
- Generated at (UTC): `2026-07-11T07:06:53.995656Z`

## Assets and benchmark metadata

```json
{"assets":[{"citation":"Yang et al., HotpotQA (EMNLP 2018)","contamination":"Released HippoRAG 2 validation sample; no tuning permitted","filename":"hotpotqa.json","license":"CC-BY-SA-4.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"3ad9c0bcbf93f41d7004ca6007049c904d2605046b314a2f7ecfb379c64cba6d","split_role":"held-out-validation"},{"citation":"Yang et al., HotpotQA (EMNLP 2018)","contamination":"Released HippoRAG 2 corpus; no tuning permitted","filename":"hotpotqa_corpus.json","license":"CC-BY-SA-4.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"9333647b922382776cd2cb02893b390d77984df85a91bfa8be411284978aca7d","split_role":"evaluation-corpus"}],"benchmark_metadata":{"adapter":"hipporag-multihop","assets":[{"citation":"Yang et al., HotpotQA (EMNLP 2018)","contamination":"Released HippoRAG 2 validation sample; no tuning permitted","filename":"hotpotqa.json","license":"CC-BY-SA-4.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"3ad9c0bcbf93f41d7004ca6007049c904d2605046b314a2f7ecfb379c64cba6d","split_role":"held-out-validation"},{"citation":"Yang et al., HotpotQA (EMNLP 2018)","contamination":"Released HippoRAG 2 corpus; no tuning permitted","filename":"hotpotqa_corpus.json","license":"CC-BY-SA-4.0","revision":"5ec05b38deecc3318bb432c69865959c56058990","sha256":"9333647b922382776cd2cb02893b390d77984df85a91bfa8be411284978aca7d","split_role":"evaluation-corpus"}],"dataset_sha256":"685e051965220587c33efe953b191f2556d6cdf5143907612006d69f19e736a3","family":"deterministic-retrieval","independent_external_reproduction":false,"interval_method":"bootstrap","license":"CC-BY-SA-4.0","pbpp_headline_eligible":false,"publishable":false,"revision":"ad30fc3e2062202d9e975e32cd28212424a56ccb","scoring_profile":"hipporag-retrieval-v1","split_role":"held-out-validation","suite":"hipporag-hotpot"}}
```

- Eligible records: `1000`
- Excluded records: `0`

## Metrics

```json
{"family":"deterministic-retrieval","interval":{"confidence":0.95,"high":0.337,"iterations":2000,"low":0.302,"method":"bootstrap","seed":1234},"intervals":{"recall_at_2":{"confidence":0.95,"high":0.337,"iterations":2000,"low":0.302,"method":"bootstrap","seed":1234},"recall_at_5":{"confidence":0.95,"high":0.394,"iterations":2000,"low":0.356,"method":"bootstrap","seed":1234}},"metrics":{"recall_at_2":0.319,"recall_at_5":0.374},"profile":"hipporag-retrieval-v1","profile_version":1,"total":1000,"trace_count":1000}
```

## Reproduction and provenance

```json
{"command":["mneme","eval-public","--write-report","/Users/admin/mnemosyne-public-artifacts/hipporag-hotpot","--reproduced-bundle","/Users/admin/mnemosyne-public-artifacts/hipporag-hotpot-reproduced","--report-output","/Users/admin/mnemosyne-public-artifacts/hipporag-hotpot-report.json","--report-note","/Users/admin/Mnemosyne/eval/reports/hipporag-hotpot.md"],"provenance":{"build":{"environment_contract":"uv run --locked","system_seam":"public-cli-subprocess","version":1},"source_bundle":"/Users/admin/mnemosyne-public-artifacts/hipporag-hotpot","system_seam":"public-cli-subprocess"},"reproduction":{"matched_files":["README.md","benchmark.json","build.json","config.json","judge.json","metrics.json","reproduce.sh","traces.jsonl"],"reproduced_bundle":"/Users/admin/mnemosyne-public-artifacts/hipporag-hotpot-reproduced","verified":true}}
```
