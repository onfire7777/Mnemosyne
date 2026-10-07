"""Read-only held-out measurement of the passage retrieval route.

Run only after fixing the implementation on synthetic/development tests.
Never use the resulting held-out scores to select parameters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from eval.harness.metrics import recall_at_k, resolve_retrieved_doc_ids
from eval.public.adapters.hipporag_multihop import normalize
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.policy import OperatingPolicy


def measure(data_root: Path, dataset: str) -> dict:
    names = [f"{dataset}.json", f"{dataset}_corpus.json"]
    assets, hashes = {}, {}
    for name in names:
        raw = (data_root / name).read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        assets[name] = json.loads(raw)
    benchmark = normalize({"assets": assets})
    engine = LocalMemoryEngine(policy=OperatingPolicy(top_k=24, token_budget=16384))
    cid_to_doc = {}
    started = time.perf_counter()
    for row in benchmark["corpus"]:
        cid = engine.append_evidence(Evidence(
            tenant_id="recall-measurement", user_id="benchmark", actor="user",
            source_type="document", source_identity=row["doc_id"],
            content=f"{row['title']}\n{row['content']}",
            access_policy={"tenant": "recall-measurement"},
        ))
        cid_to_doc[cid] = row["doc_id"]
    ingest_seconds = time.perf_counter() - started
    recalls, elapsed, mismatches, abstentions = [], [], 0, 0
    filt = {"query_mode": "passages", "tenant_id": "recall-measurement", "branch": "main"}
    for index, row in enumerate(benchmark["questions"], 1):
        started = time.perf_counter()
        result = engine.retrieve(row["question"], tenant_id="recall-measurement",
                                 filt=filt, record_access=False)
        elapsed.append(time.perf_counter() - started)
        ranked = resolve_retrieved_doc_ids([hit.to_dict() for hit in result.hits], cid_to_doc)
        reference = engine.lexical_search(row["question"], 5, {**filt, "_retrieval_deep": False})
        mismatches += [hit.id for hit in result.hits[:5]] != [hit.id for hit in reference]
        abstentions += result.abstained
        recalls.append(recall_at_k(ranked, row["gold_references"], 5))
        if index % 100 == 0:
            print(f"{dataset}: {index}/{len(benchmark['questions'])} queries", flush=True)
    return {
        "dataset": dataset, "sha256": hashes, "documents": len(cid_to_doc),
        "questions": len(recalls), "recall_at_5": sum(recalls) / len(recalls),
        "bm25_top5_ranking_mismatches": mismatches, "answer_abstentions": abstentions,
        "ingest_seconds": ingest_seconds,
        "query_mean_seconds": sum(elapsed) / len(elapsed),
        "query_p95_seconds": sorted(elapsed)[int(0.95 * (len(elapsed) - 1))],
        "scope": "passage-only engine retrieval; no consolidation or model-backed graph",
        "held_out_no_tuning": True, "publishable": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for dataset in ["2wikimultihopqa", "hotpotqa", "musique"]:
        results.append(measure(args.data_root, dataset))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(results[-1]), flush=True)


if __name__ == "__main__":
    main()
