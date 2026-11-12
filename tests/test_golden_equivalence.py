"""The engine must reproduce the legacy golden dumps exactly.

The fixtures in eval/perf/golden were dumped by eval/perf/golden_equivalence.py from main at
737a1ef8 - before the batch-scale engine work - under its deterministic runtime. Every gate
decision, the final main-branch state and the eval-query-batch output must stay byte for byte
the same; only branch bookkeeping (merged canaries, per-merge reinforce rows) is excluded, as the
harness documents.

synthetic-growth, synthetic-rails and synthetic-conflicts were re-dumped on 7 Oct 2026 from the
engine that made these deliberate changes (docs/recall-integrity-fixes-2026-10-07.md): a fact
cites only the evidence it came from, not the whole batch; name co-occurrence makes no fact;
search keeps relevance order (no U-curve). g0-write-gating was re-dumped on 5 Nov 2026 for one
deliberate change from codex/complete-ai-memory-prs: an erased source now stops extraction with
the reason source_evidence_unavailable, where it used to read candidate_extraction_not_configured
(rows[5], the erasure case); nothing else in that dump moved.

The three synthetic fixtures were refreshed again on 5 Nov 2026 for the integrated,
default-on learning stack, current retrieval rails, and corrected canary relation replay.
Thin/full branch outputs and independent repeated runs must agree before a refresh.
The harness authenticates encrypted audit payloads before normalizing internal ids;
it retains every payload field, envelope key id, and encryption timestamp. See
docs/learning-integration-validation.md for the scoped regression evidence.

The three synthetic fixtures were refreshed on 11 Nov 2026 for the deliberate changes of
9-10 Nov, after two regressions those changes introduced were fixed (a superseded fact merged
through a canary left its relation open on main, and a forget spanning several branches wiped
its own audit report). With both fixed, the set of open relations is the same as in the 5 Nov
dumps; what moved, and why:

* consolidated facts carry the owner of their sources, and a fact citing several sources
  depends on all of them, so forgetting one retracts and scrubs it instead of trimming it;
* a fact that is replayed already superseded or retracted takes no part in revision, so the
  per-merge ``supersede``/``trust_rejected`` audit rows and the duplicate closed relations
  those replays produced are gone;
* consolidation reports the hypotheses it reviewed.

g0-write-gating was not refreshed: it reproduces the 5 Nov dump once a consolidated fact that
revises an unowned fact continues that fact's lineage.

synthetic-growth and synthetic-conflicts were refreshed on 12 Nov 2026 for the deliberate
audit fixes of 11-12 Nov. Each movement was traced to its fix by replaying the fixes one by
one on the 11 Nov tree; no open relation, active fact or abstention changed. What moved, and why:

* the forgetter no longer treats a row without lifecycle metadata as 30 days old with
  importance 0.1, so fresh rows are no longer demoted to summary/gist tiers one per pass; each
  row instead gets its lifecycle (importance 0.5, verbatim tier), hence more forgetter
  ``update_evidence_metadata`` rows and slightly higher evidence activation;
* forget scrubs every relation it expires, the summary-gist links of the forgotten solo
  sources included, so those closed links become ``[erased]`` tombstones and merge with the
  other erased relation like the fact tombstones already did (conflicts: 39 -> 35 relations);
* the local lexical, hashing-vector, graph-seed, reranker and MMR stages score the question
  without function words, so "is"/"the" no longer pull in unrelated "X is Y" facts: hit
  order, kinds (assertion vs evidence), scores, grounding-floor rows and standing move, and a
  query answered by a single hit reports lower confidence (it counts hits) but still answers;
* the graph channel yields each neighbour's edge to the query entity, so ``graph_ppr``
  candidate counts grow; no hit changed;
* an automatic capture-batch job over one row no longer writes a gist of it (the two "Deal"
  gists and their links are gone), and forget drops the vector of the rows it erases.

To reproduce the original historical baseline instead:

    python eval/perf/golden_equivalence.py dump --scenario NAME --src <737a1ef8 checkout>/src --out x.json
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from eval.perf.golden_equivalence import diff, run
from mnemosyne.canary_overlay import THIN_CANARIES_ENV

GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "perf" / "golden"


@pytest.mark.parametrize("thin", ["1", "0"], ids=["thin-canaries", "full-branches"])
@pytest.mark.parametrize("name", ["synthetic-growth", "synthetic-rails", "synthetic-conflicts", "g0-write-gating"])
def test_engine_reproduces_the_legacy_golden_dump(name: str, thin: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Both the thin-canary fast path and its MNEMOSYNE_THIN_CANARIES=0 fallback must be exact.
    monkeypatch.setenv(THIN_CANARIES_ENV, thin)
    expected = json.loads(gzip.decompress((GOLDEN / f"{name}.json.gz").read_bytes()))
    actual = json.loads(json.dumps(run(name), sort_keys=True))
    for dump in (expected, actual):
        dump.pop("engine_source", None)
    problems = diff(expected, actual)
    assert not problems, "golden dump drifted:\n" + "\n".join(problems)


def test_golden_fixtures_cover_decisions_state_and_retrieval() -> None:
    growth = json.loads(gzip.decompress((GOLDEN / "synthetic-growth.json.gz").read_bytes()))
    errors = [step["error"] for step in growth["steps"] if "error" in step]
    candidates = [
        candidate
        for step in growth["steps"]
        for job in (step.get("consolidation") or {}).get("jobs", [])
        for candidate in job["result"]["candidate_results"]
    ]
    assert errors and all("rejected semantic candidates" in error for error in errors)
    # Since 7 Oct 2026 a fact cites only its own source, so one stated once waits for
    # corroboration instead of riding in on batch membership (docs/recall-integrity-fixes-2026-10-07.md).
    awaiting = [c for c in candidates if not c["promoted"]]
    assert len(candidates) - len(awaiting) > 20
    assert all(
        case.startswith("fact_external_corroboration:") for c in awaiting for case in c["failed_cases"]
    ) and all(c["failed_cases"] for c in awaiting)
    assert growth["queries"]["count"] == 9
    assert growth["state"]["golden-a"]["assertions"] and growth["state"]["golden-b"]["assertions"]
    rails = json.loads(gzip.decompress((GOLDEN / "synthetic-rails.json.gz").read_bytes()))["result"]
    promoted = {rate: sum(c["promoted"] for c in rails[rate]["run"]["candidate_results"]) for rate in rails}
    assert promoted["0.0"] == 0 and promoted["1.0"] == 6 and 0 < promoted["0.5"] < 6
    conflicts = json.loads(gzip.decompress((GOLDEN / "synthetic-conflicts.json.gz").read_bytes()))
    statuses = [row["status"] for row in conflicts["state"]["golden-conflicts"]["assertions"]]
    assert {"active", "superseded", "retracted"} <= set(statuses)
    assert conflicts["state"]["golden-conflicts"]["relations"]
