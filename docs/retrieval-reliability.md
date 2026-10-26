# Retrieval reliability

The October 26 follow-up fixes runtime defects identified while reviewing the
Hindsight parity work. It supplies regression evidence, not a competitive score.

## Source-only multi-hop lookup

Default local retrieval can follow at most two named entities from its first two
readable source passages. Relational questions trigger this when the leading
passage lacks query terms; Python callers can also pass `filt={"multi_hop": True}`.
A single-hit budget does not expand. This applies to the existing source-only
fallback, not mixed assertion, external-provider or passage-graph routes.

Expansion searches the same tenant, branch and authenticated context, using only
redacted source text. The connecting passage and related passages are interleaved
within the existing candidate and token budgets. The explanation includes
`bridge_expansion`; resulting scores are labeled `reciprocal_rank`, not BM25.
Session source labels and process evaluation flags do not disable the route.
This deterministic name lookup is not a general multi-step reasoning engine.

## Time, privacy and confidence

- Candidate dates are canonical UTC strings. Invalid event metadata is omitted;
  redacted reads withhold source event dates so metadata cannot repeat hidden text.
- Time-window recall preserves requested speakers and explicit first/last order.
  Otherwise freshness only breaks relevance ties. Future or invalid timestamps
  do not receive an artificial freshness advantage.
- Confidence uses evidence quality, trust, provenance, relative relevance and query
  support. Word overlap no longer forces a 96–100% confidence floor. These remain
  heuristic confidence scores, not a demonstrated probability of correctness.
- Date parsing normalizes supported date/datetime values and rejects unsupported
  types instead of silently treating them as missing timestamps.

## Validation contract

The quality-gate tests compare each partition against its matching historical
floor and compare two current executions for reproducibility. Fresh query IDs and
counts are checked. Dataset saturation is a diagnostic; improved scores cannot
fail merely for exceeding the dataset's former ceiling. Invalid thresholds and
inconsistent verdicts fail closed.

No quality-gate benchmark or model inference was run for this follow-up. The
[verification report](../work/hindsight-comparison/retrieval-hardening/REPORT.md)
records targeted native-storage and retrieval tests and their limitations.
