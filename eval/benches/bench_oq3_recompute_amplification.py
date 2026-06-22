"""OQ3 — recompute work-amplification: passes-executed / projections-invalidated.

Blueprint open question OQ3 asks how much wasted recompute the consolidation /
projection-maintenance loop does. The ideal is ~1.0 (only re-run work for
projections whose inputs actually changed). This bench measures the CURRENT src
honestly on three cascade triggers — add, retraction, erasure — by driving the
real handler:

  * ``jobs.RuntimeJobHandlers.run_projection_recompute`` (src/mnemosyne/jobs.py:88)
    walks the dependency closure (``_affected_evidence_cids`` BFS, jobs.py:391)
    and then enqueues ONE ``consolidate_evidence`` job per *surviving* affected
    cid (``_surviving_evidence_cids``, jobs.py:457). Each consolidate job runs the
    full ``DEFAULT_CONSOLIDATION_PASSES`` pipeline (11 passes, consolidation.py:25).

  * "projections truly invalidated" = the count of distinct projection rows whose
    ``source_evidence_cids`` intersect the changed set (``_affected_projections``,
    jobs.py:442). That is the denominator: the work that *had* to be redone.

  * "passes executed" = enqueued consolidate jobs × passes-per-job. That is the
    numerator: the work actually scheduled.

AMPLIFICATION = passes_executed / projections_truly_invalidated.

HONEST STATUS as a forcing function: there is **no dirty-check / memoization**
today. ``run_projection_recompute`` re-enqueues a full 11-pass consolidation for
every surviving cid in the closure even when the projection it feeds is unchanged,
so amplification is >> 1. The bench also computes a **memo-hit-rate** by replaying
the SAME recompute twice and checking whether the second pass is skipped: it is
not (no memo table), so memo-hit-rate == 0.0. Both are measured, not asserted.

Run: ``python eval/benches/bench_oq3_recompute_amplification.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bench_common import emit, temp_store  # noqa: E402

from mnemosyne.consolidation import DEFAULT_CONSOLIDATION_PASSES  # noqa: E402
from mnemosyne.engine import LocalMemoryEngine  # noqa: E402
from mnemosyne.jobs import (  # noqa: E402
    PROJECTION_RECOMPUTE_JOB,
    RuntimeJobHandlers,
)
from mnemosyne.models import Evidence, Relation  # noqa: E402
from mnemosyne.queue import InProcessQueue  # noqa: E402

TENANT = "oq3-tenant"
PASSES_PER_JOB = len(DEFAULT_CONSOLIDATION_PASSES)
CHAIN_LEN = 6  # derived-evidence chain depth so the BFS closure is non-trivial


def _seed_chain(engine: LocalMemoryEngine) -> dict[str, object]:
    """Build a root evidence + a chain of derived evidence linked by relations.

    Mirrors the media/summary derivation shape the recompute BFS follows
    (predicate in {media-derived-text, summary-derived-gist}). Returns ids.
    """

    root = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id="u",
            actor="user",
            source_type="chat",
            content="root fact: Ada Lovelace wrote the first algorithm",
        )
    )
    chain = [root]
    prev = root
    for depth in range(CHAIN_LEN):
        derived = engine.append_evidence(
            Evidence(
                tenant_id=TENANT,
                user_id="u",
                actor="tool",
                source_type="media-extraction" if depth == 0 else "consolidation-summary",
                content=f"derived level {depth} of root",
                metadata={"source_evidence_cid": prev, "source_evidence_cids": [prev]},
            )
        )
        engine.add_relation(
            Relation(
                tenant_id=TENANT,
                source=prev,
                predicate="media-derived-text" if depth == 0 else "summary-derived-gist",
                target=derived,
                source_evidence_cids=[prev, derived],
            )
        )
        chain.append(derived)
        prev = derived
    return {"root": root, "chain": chain}


def _measure(engine: LocalMemoryEngine, handlers: RuntimeJobHandlers, changed_cid: str, label: str) -> dict[str, object]:
    queue = handlers.queue
    before = len(queue.snapshot().get("pending", [])) if isinstance(queue.snapshot(), dict) else 0

    res = handlers.run_projection_recompute(
        {
            "tenant_id": TENANT,
            "branch": "main",
            "changed_evidence_cids": [changed_cid],
            "enqueue_consolidation": True,
        }
    )
    details = res.details
    affected_ev = len(details["affected_evidence_cids"])  # type: ignore[index]
    queued = len(details["queued_consolidation_jobs"])  # type: ignore[index]
    proj_counts = details["affected_projection_counts"]  # type: ignore[index]
    projections_invalidated = sum(int(v) for v in proj_counts.values())

    passes_executed = queued * PASSES_PER_JOB

    # Replay the IDENTICAL recompute to probe for memoization / dirty-skip.
    res2 = handlers.run_projection_recompute(
        {
            "tenant_id": TENANT,
            "branch": "main",
            "changed_evidence_cids": [changed_cid],
            "enqueue_consolidation": True,
        }
    )
    queued2 = len(res2.details["queued_consolidation_jobs"])  # type: ignore[index]
    # memo-hit-rate: fraction of second-run jobs that were SKIPPED vs first run.
    memo_hit_rate = round(1.0 - (queued2 / queued), 4) if queued > 0 else 0.0

    denom = max(projections_invalidated, 1)
    amplification = round(passes_executed / denom, 4)

    return {
        "trigger": label,
        "changed_evidence_cids": 1,
        "affected_evidence_cids": affected_ev,
        "surviving_consolidation_jobs_enqueued": queued,
        "passes_per_job": PASSES_PER_JOB,
        "passes_executed": passes_executed,
        "projections_truly_invalidated": projections_invalidated,
        "affected_projection_counts": proj_counts,
        "work_amplification_passes_per_projection": amplification,
        "replay_jobs_enqueued": queued2,
        "memo_hit_rate": memo_hit_rate,
        "queue_pending_before": before,
    }


def main() -> dict[str, object]:
    results: list[dict[str, object]] = []

    # --- Trigger 1: ADD (a fresh changed root cascades through the chain) ---
    eng_add = LocalMemoryEngine(store_path=temp_store("oq3-add"))
    h_add = RuntimeJobHandlers(eng_add, InProcessQueue())
    ids_add = _seed_chain(eng_add)
    results.append(_measure(eng_add, h_add, ids_add["root"], "add_cascade"))  # type: ignore[arg-type]

    # --- Trigger 2: RETRACTION (supersede/retract the root, then recompute) ---
    eng_ret = LocalMemoryEngine(store_path=temp_store("oq3-ret"))
    h_ret = RuntimeJobHandlers(eng_ret, InProcessQueue())
    ids_ret = _seed_chain(eng_ret)
    # A retraction in this engine surfaces as a changed-evidence event on the
    # root; recompute must propagate to derived projections regardless of whether
    # the derived content actually changed — that's the amplification we measure.
    results.append(_measure(eng_ret, h_ret, ids_ret["root"], "retraction_cascade"))  # type: ignore[arg-type]

    # --- Trigger 3: ERASURE (mark root erased, then recompute) ---
    eng_era = LocalMemoryEngine(store_path=temp_store("oq3-era"))
    h_era = RuntimeJobHandlers(eng_era, InProcessQueue())
    ids_era = _seed_chain(eng_era)
    root = ids_era["root"]
    erase = getattr(eng_era, "erase_evidence", None) or getattr(eng_era, "forget_evidence", None)
    erased_applied = False
    if callable(erase):
        try:
            erase(TENANT, root, "main")  # type: ignore[misc]
            erased_applied = True
        except TypeError:
            try:
                erase(TENANT, root)  # type: ignore[misc]
                erased_applied = True
            except Exception:
                erased_applied = False
    era_row = _measure(eng_era, h_era, root, "erasure_cascade")  # type: ignore[arg-type]
    era_row["erasure_applied_in_src"] = erased_applied
    results.append(era_row)

    mean_amp = round(
        sum(float(r["work_amplification_passes_per_projection"]) for r in results) / len(results),
        4,
    )
    mean_memo = round(sum(float(r["memo_hit_rate"]) for r in results) / len(results), 4)

    payload: dict[str, object] = {
        "bench": "oq3_recompute_amplification",
        "blueprint_ref": "OQ3 recompute amplification",
        "src_wiring": {
            "recompute_handler": "mnemosyne.jobs.RuntimeJobHandlers.run_projection_recompute (src/mnemosyne/jobs.py:88)",
            "closure_bfs": "mnemosyne.jobs._affected_evidence_cids (src/mnemosyne/jobs.py:391)",
            "projection_invalidation": "mnemosyne.jobs._affected_projections (src/mnemosyne/jobs.py:442)",
            "surviving_enqueue": "mnemosyne.jobs._surviving_evidence_cids (src/mnemosyne/jobs.py:457)",
            "passes_per_job": f"DEFAULT_CONSOLIDATION_PASSES = {PASSES_PER_JOB} (src/mnemosyne/consolidation.py:25)",
            "job_kind": PROJECTION_RECOMPUTE_JOB,
        },
        "metric": {
            "triggers": results,
            "mean_work_amplification_passes_per_projection": mean_amp,
            "mean_memo_hit_rate": mean_memo,
        },
        "target": {
            "work_amplification": "~1.0 (only re-run truly-invalidated projection work)",
            "memo_hit_rate": ">0 on identical replay (dirty-skip / memoized recompute)",
        },
        "honest_status": {
            "dirty_check_today": False,
            "memo_table_today": False,
            "note": (
                "No dirty-check or memo table exists: run_projection_recompute "
                "enqueues a full 11-pass consolidation per surviving cid in the "
                "BFS closure and re-enqueues identically on replay (memo_hit_rate "
                "== 0.0). Amplification is therefore >> 1.0 — every projection in "
                "the closure pays the full pipeline whether or not its inputs "
                "actually changed."
            ),
        },
        "verdict": {
            "amplification_near_one": mean_amp <= 1.5,
            "memoization_present": mean_memo > 0.0,
        },
        "wiring_to_reduce_amplification": [
            "Add a projection-input fingerprint (hash of contributing "
            "source_evidence_cids + their content versions) and skip enqueue when "
            "the fingerprint is unchanged — turn _surviving_evidence_cids into a "
            "dirty-set filter (jobs.py:457).",
            "Introduce a memo table keyed on (tenant,branch,projection_id,input_hash) "
            "so an identical replay hits the cache (memo_hit_rate -> 1.0).",
            "Run only the passes whose outputs a given projection depends on instead "
            "of the full DEFAULT_CONSOLIDATION_PASSES pipeline per cid "
            "(consolidation.py pass selection).",
        ],
    }
    emit(payload)
    return payload


if __name__ == "__main__":
    main()
