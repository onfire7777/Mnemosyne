# Public evaluation harness

Run the redistributable development self-test with `uv run --locked mneme
eval-public --suite smoke --out-dir /tmp/mneme-smoke`, then verify it with
`uv run --locked mneme eval-public --verify-bundle /tmp/mneme-smoke`.

The smoke suite exercises Mnemosyne exclusively through public CLI subprocesses.
It is permanently non-publishable, ineligible for PBPP headlines, and is not an
independent external reproduction. Retrieval proportions use Wilson intervals;
future answer-quality tracks must name their reader/judge and use bootstrap
intervals. Families are never aggregated.
