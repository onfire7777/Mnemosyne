"""The engine must reproduce the legacy golden dumps exactly.

The fixtures in eval/perf/golden were dumped by eval/perf/golden_equivalence.py from main at
2083ffc4 - before the batch-scale engine work - under its deterministic runtime. Every gate
decision, the final main-branch state and the eval-query-batch output must stay byte for byte
the same; only branch bookkeeping (merged canaries, per-merge reinforce rows) is excluded, as the
harness documents.

synthetic-growth, synthetic-rails and synthetic-conflicts were re-dumped on 7 Oct 2026 from the
engine that made these deliberate changes (docs/recall-integrity-fixes-2026-10-07.md): a fact
cites only the evidence it came from, not the whole batch; name co-occurrence makes no fact;
search keeps relevance order (no U-curve). g0-write-gating did not change. Otherwise regenerate
only from the engine the fixtures were dumped from:

    python eval/perf/golden_equivalence.py dump --scenario NAME --src <2083ffc4 checkout>/src --out x.json
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
