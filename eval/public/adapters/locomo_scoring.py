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
