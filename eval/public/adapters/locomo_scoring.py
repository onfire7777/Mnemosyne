"""Pinned LoCoMo per-case scoring; no model execution or publication admission.

Run in the separate scorer environment described in requirements-locomo.txt.
The project runtime does not import or depend on these evaluation packages.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
import math
import string

from eval.public.adapters.locomo import LoCoMoError, UPSTREAM_REVISION

DEPENDENCIES = {"nltk": "3.8.1", "numpy": "1.26.0", "regex": "2022.10.31"}


@lru_cache(maxsize=1)
def _runtime():
    try:
        if any(version(name) != required for name, required in DEPENDENCIES.items()):
            raise LoCoMoError("LoCoMo scorer requires its pinned evaluation environment")
    except PackageNotFoundError as exc:
        raise LoCoMoError("LoCoMo scorer requires its pinned evaluation environment") from exc
    import numpy
    import regex
    from nltk.stem import PorterStemmer
    return numpy, regex, PorterStemmer()


def _tokens(text: str) -> list[str]:
    _, regex, stemmer = _runtime()
    text = text.lower().replace(",", "")
    text = "".join(ch for ch in text if ch not in string.punctuation)
    text = regex.sub(r"\b(a|an|the|and)\b", " ", text)
    return [stemmer.stem(token) for token in text.split()]


def _f1(prediction: str, reference: str) -> float:
    actual, expected = _tokens(prediction), _tokens(reference)
    overlap = sum((Counter(actual) & Counter(expected)).values())
    if not overlap:
        return 0.0
    precision, recall = overlap / len(actual), overlap / len(expected)
    return 2 * precision * recall / (precision + recall)


def score_case(annotation: dict, prediction: str, *, retrieved_context: list[str] | None = None) -> dict:
    """Score one decoded prediction, exposing upstream recall fallback separately.

    A None context means no upstream context field. An empty supplied context
    with nonempty evidence is invalid upstream and is rejected here too.
    Rounding matches evaluate_qa.py; unrounded scores remain available.
    """
    numpy, _, _ = _runtime()
    if not isinstance(annotation, dict) or not isinstance(prediction, str):
        raise LoCoMoError("annotation object and string prediction required")
    category = annotation.get("category")
    if type(category) is not int or category not in range(1, 6):
        raise LoCoMoError("category must be an integer from 1 through 5")
    reference = annotation.get("answer")
    if (type(reference) not in (str, int, float)
            or (type(reference) is float and not math.isfinite(reference))):
        raise LoCoMoError("reference must be a finite scalar answer")
    evidence = annotation.get("evidence")
    if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
        raise LoCoMoError("evidence must be a string list")
    if retrieved_context is not None and (
            not isinstance(retrieved_context, list)
            or any(not isinstance(item, str) for item in retrieved_context)):
        raise LoCoMoError("retrieved context must be a string list or absent")
    reference = str(reference)
    if category == 1:
        candidates = [text.strip() for text in prediction.split(",")]
        references = [text.strip() for text in reference.split(",")]
        score = float(numpy.mean([max(_f1(candidate, answer) for candidate in candidates)
                                  for answer in references]))
    elif category == 5:
        output = prediction.lower()
        score = float("no information available" in output or "not mentioned" in output)
    else:
        if category == 3:
            reference = reference.split(";")[0].strip()
        score = _f1(prediction, reference)
    applicable = retrieved_context is not None and bool(evidence)
    recall = 1.0
    if applicable:
        if not retrieved_context:
            raise LoCoMoError("upstream recall is undefined for empty context with evidence")
        if retrieved_context[0].startswith("S"):
            sessions = [item[1:] for item in retrieved_context]
            recall = sum(item.split(":")[0][1:] in sessions for item in evidence) / len(evidence)
        else:
            recall = sum(item in retrieved_context for item in evidence) / len(evidence)
    return {"category": category, "prediction": prediction, "score": score,
            "reported_score": round(score, 3), "upstream_recall": recall,
            "reported_upstream_recall": round(recall, 3),
            "measured_recall": recall if applicable else None,
            "recall_applicable": applicable, "upstream_revision": UPSTREAM_REVISION}


def score_prediction_set(samples: list[dict], predictions: list[dict]) -> dict:
    """Replay decoded predictions against a complete, explicit source population.

    Missing outputs remain in denominators and case history. Upstream-style
    aggregates are labeled separately from completeness and observed retrieval.
    No aggregate across categories or publication eligibility is produced.
    """
    from hashlib import sha256
    import json
    from eval.public.adapters.locomo import split_samples

    source = split_samples(samples)
    if not isinstance(predictions, list):
        raise LoCoMoError("predictions must be a list")
    known = {row["question_id"] for row in source["annotations"]}
    outputs = {}
    for row in predictions:
        if (not isinstance(row, dict)
                or not {"question_id", "decoded_prediction"} <= set(row)
                or set(row) - {"question_id", "decoded_prediction", "retrieved_context"}):
            raise LoCoMoError("prediction fields must follow the decoded-output contract")
        question_id = row["question_id"]
        if not isinstance(question_id, str) or question_id not in known or question_id in outputs:
            raise LoCoMoError("prediction IDs must be unique and present in the source population")
        if "retrieved_context" in row and row["retrieved_context"] is None:
            raise LoCoMoError("omit unavailable retrieved context; explicit null is not a context list")
        outputs[question_id] = row
    groups = {str(category): {"source_count": 0, "scored_count": 0, "missing_count": 0,
                             "rounded_score_sum": 0.0, "upstream_recall_sum": 0.0,
                             "observed_recall_count": 0, "fallback_recall_count": 0}
              for category in range(1, 6)}
    cases = []
    # Keep source order: upstream sums rounded scores in that order.
    for row in source["annotations"]:
        question_id, annotation = row["question_id"], row["annotation"]
        group = groups[str(annotation["category"])]
        group["source_count"] += 1
        if question_id not in outputs:
            group["missing_count"] += 1
            cases.append({"question_id": question_id, "category": annotation["category"],
                          "status": "missing-prediction", "score": None})
            continue
        output = outputs[question_id]
        scored = score_case(annotation, output["decoded_prediction"],
                            retrieved_context=output.get("retrieved_context"))
        group["scored_count"] += 1
        group["rounded_score_sum"] += scored["reported_score"]
        # evaluation_stats.py adds recall only for nonempty source evidence,
        # but divides by all source questions in the category.
        if annotation["evidence"]:
            group["upstream_recall_sum"] += scored["reported_upstream_recall"]
            group["observed_recall_count" if scored["recall_applicable"] else "fallback_recall_count"] += 1
        cases.append({"question_id": question_id, "status": "scored", **scored})
    for group in groups.values():
        count = group["source_count"]
        group["complete"] = count > 0 and group["missing_count"] == 0
        group["upstream_denominator_mean"] = group["rounded_score_sum"] / count if count else None
        group["upstream_recall_mean"] = group["upstream_recall_sum"] / count if count else None
    def digest(value):
        return "sha256:" + sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                            allow_nan=False).encode()).hexdigest()
    return {"schema_version": "mnemosyne.locomo-scoring-replay/v1",
            "upstream_revision": UPSTREAM_REVISION, "source_digest": digest(samples),
            "prediction_digest": digest(sorted(predictions, key=lambda row: row["question_id"])),
            "categories": groups, "cases": cases,
            "complete": all(group["complete"] for group in groups.values()),
            "publication_authorized": False,
            "scope": "decoded-prediction scoring replay; not a model execution or admission"}


def replay_native_population(samples: list[dict], records: list[dict], *,
                             caption_policy: str, choice_draws: dict[str, float] | None = None,
                             reader_policy: dict | None = None, choice_seed: int | None = None,
                             run_config: dict | None = None) -> dict:
    """Verify native records and report every source question without ranking.

    QA scoring retains the pinned category scorer. Native evidence recall is
    explicitly separate: exact source dialog-ID membership, zero for empty
    retrieval, and not applicable for empty gold evidence. No upstream fallback
    value is represented as an observed retrieval result.
    """
    from hashlib import sha256
    import json
    from .locomo import native_choice_policy, split_samples
    from .locomo_native import _prepare_native_replay, _verify_prepared_native_record

    _runtime()
    from copy import deepcopy
    from eval.public.reader_policy import validate_reader_policy
    reader_policy = deepcopy(reader_policy)
    if reader_policy is not None:
        validate_reader_policy(reader_policy)
    source = split_samples(samples)
    questions = {row["question_id"]: row for row in source["questions"]}
    annotations = {row["question_id"]: row for row in source["annotations"]}
    contexts = {row["sample_id"]: _prepare_native_replay(row, caption_policy=caption_policy)
                for row in samples}
    choice_policy = native_choice_policy(samples, choice_draws=choice_draws, choice_seed=choice_seed)
    choice_draws = choice_policy["draws"]
    from .locomo_config import bind_native_run_config
    run_config = deepcopy(run_config)
    config_digest = (bind_native_run_config(run_config, samples, caption_policy=caption_policy,
                    choice_policy=choice_policy, reader_policy=reader_policy)
                    if run_config is not None else None)
    if not isinstance(records, list):
        raise LoCoMoError("native replay records must be a list")
    verified = {}
    for record in records:
        qid = record.get("question_id") if isinstance(record, dict) else None
        if not isinstance(qid, str) or qid not in questions or qid in verified:
            raise LoCoMoError("native replay record IDs must be unique source questions")
        verified[qid] = _verify_prepared_native_record(
            contexts[questions[qid]["sample_id"]], annotations[qid]["source_index"], record,
            choice_draw=choice_draws.get(qid), reader_policy=reader_policy, run_config_sha256=config_digest)
    groups = {str(i): {"source_count": 0, "scored_count": 0, "missing_count": 0,
                       "rounded_qa_sum": 0.0, "native_recall_sum": 0.0,
                       "native_recall_count": 0} for i in range(1, 6)}
    cases = []
    for qid, row in annotations.items():
        annotation = row["annotation"]
        group = groups[str(annotation["category"])]
        group["source_count"] += 1
        record = verified.get(qid)
        status = record["status"] if record else "missing-record"
        if status != "projected":
            group["missing_count"] += 1
            cases.append({"question_id": qid, "status": status, "qa_score": None,
                          "native_evidence_recall": None})
            continue
        score = score_case(annotation, record["decoded_prediction"])["reported_score"]
        gold = annotation["evidence"]
        recall = (sum(item in record["retrieved_dialog_ids"] for item in gold) / len(gold)
                  if gold else None)
        group["scored_count"] += 1
        group["rounded_qa_sum"] += score
        if recall is not None:
            group["native_recall_count"] += 1
            group["native_recall_sum"] += recall
        cases.append({"question_id": qid, "status": "scored", "qa_score": score,
                      "native_evidence_recall": recall})
    for group in groups.values():
        count, observed = group["source_count"], group["native_recall_count"]
        group["complete"] = count > 0 and group["missing_count"] == 0
        group["qa_source_denominator_mean"] = group["rounded_qa_sum"] / count if count else None
        group["native_observed_recall_mean"] = group["native_recall_sum"] / observed if observed else None
    def digest(value):
        return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    absent_categories = [category for category, group in groups.items() if group["source_count"] == 0]
    protocol = native_replay_protocol()
    from leaderboard.native_metrics import category_metric
    category_metrics = {family: [category_metric(group, int(category), family=family,
                                scorer_digest="sha256:" + digest(protocol))
                                for category, group in groups.items()]
                        for family in ("reference_qa", "retrieval")}
    return {"schema_version": "mnemosyne.locomo-native-replay/v1", "categories": groups,
            "category_metrics": category_metrics,
            "protocol": protocol, "protocol_sha256": digest(protocol),
            "reader_policy": reader_policy, "run_config": run_config, "run_config_sha256": config_digest,
            "cases": cases, "complete": all(row["complete"] for row in groups.values()),
            "source_population_complete": all(row["missing_count"] == 0 for row in groups.values()),
            "absent_categories": absent_categories,
            "source_sha256": digest(samples), "records_sha256": digest(sorted(records, key=lambda r: r["question_id"])),
            "caption_policy": caption_policy, "choice_draws": dict(choice_draws),
            "choice_policy": choice_policy,
            "publication_authorized": False, "runtime_custody_verified": False,
            "scope": "native-memory structural replay; not an unchanged upstream run"}


def native_replay_protocol() -> dict:
    """Identify this offline replay policy and the source files it executes.

    This is not the SUT/model/runtime manifest. Those are separate admission
    requirements; these hashes identify only the listed local replay sources.
    """
    from hashlib import sha256
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    paths = (
        "eval/public/adapters/locomo.py", "eval/public/adapters/locomo_native.py",
        "eval/public/adapters/locomo_scoring.py", "eval/public/adapters/locomo_replay.py",
        "eval/public/adapters/locomo_config.py", "leaderboard/native_metrics.py",
        "eval/public/custody.py", "eval/public/derivation.py", "eval/public/reader_policy.py", "eval/harness/cli_driver.py", "src/mnemosyne/ids.py",
    )
    return {
        "id": "mnemosyne.locomo-native-scoring/v1",
        "upstream_revision": UPSTREAM_REVISION,
        "scorer_dependencies": dict(DEPENDENCIES),
        "capture": "canonical-source-dialog-json/v1",
        "source_time": "verbatim-data; no virtual-clock advancement",
        "question_transformation": "upstream-category-instructions-and-explicit-choice-draw",
        "projection": "native-explicit-abstention-v1",
        "claim_derivation": "mnemosyne.claim-derivation/v1; quotation or independently replayed arithmetic/date",
        "qa_scoring": "pinned-category-scorer; round-each-case-to-3-decimals",
        "qa_denominator": "all-source-questions-in-category; missing-contributes-zero",
        "native_evidence_recall": "exact-dialog-membership; empty-retrieval-zero; empty-gold-null",
        "recall_denominator": "executed-questions-with-nonempty-gold",
        "overall_rank": None,
        "replay_source_sha256": {path: sha256((root / path).read_bytes()).hexdigest() for path in paths},
    }
