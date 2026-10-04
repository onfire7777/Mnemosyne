"""LoCoMo ingestion boundary; not yet an admitted runnable benchmark adapter."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

UPSTREAM_REVISION = "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"
INPUT_SCHEMA = "mnemosyne.locomo-input/v1"


class LoCoMoError(ValueError):
    """A source sample cannot be separated into unambiguous inputs and labels."""


def split_samples(samples: object) -> dict:
    """Preserve source conversation/QA values in separate custody lanes.

    Conversation objects are model inputs. Questions contain only source query
    text and IDs; annotations retain full original QA objects for scoring and
    explicit protocol transformations (including category-5 choice creation).
    Generated observations/summaries are not silently substituted for dialogs.
    This function does not establish dataset pinning, rights or run admission.
    """
    if not isinstance(samples, list) or not samples:
        raise LoCoMoError("samples must be a non-empty list")
    conversations, questions, annotations = [], [], []
    seen = set()
    for sample in samples:
        if not isinstance(sample, dict):
            raise LoCoMoError("sample must be an object")
        sample_id = sample.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in seen:
            raise LoCoMoError("sample_id must be a unique non-empty string")
        seen.add(sample_id)
        conversation, qas = sample.get("conversation"), sample.get("qa")
        if not isinstance(conversation, dict) or not conversation:
            raise LoCoMoError("conversation must be a non-empty object")
        if not isinstance(qas, list) or not qas:
            raise LoCoMoError("qa must be a non-empty list")
        conversations.append({"sample_id": sample_id, "conversation": deepcopy(conversation)})
        for index, qa in enumerate(qas):
            if not isinstance(qa, dict):
                raise LoCoMoError("QA annotation must be an object")
            query, category = qa.get("question"), qa.get("category")
            if not isinstance(query, str) or not query:
                raise LoCoMoError("question must be a non-empty string")
            if type(category) is not int or category not in range(1, 6):
                raise LoCoMoError("category must be an integer from 1 through 5")
            if "answer" not in qa:
                raise LoCoMoError("source answer annotation is required")
            evidence = qa.get("evidence")
            if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
                raise LoCoMoError("evidence must be a list of original string identifiers")
            identity = json.dumps([sample_id, index], ensure_ascii=True, separators=(",", ":"))
            question_id = "locomo:" + sha256(identity.encode()).hexdigest()
            questions.append({"question_id": question_id, "sample_id": sample_id, "query": query})
            annotations.append({"question_id": question_id, "source_index": index,
                                "annotation": deepcopy(qa)})
    result = {"schema_version": INPUT_SCHEMA, "conversations": conversations,
              "questions": questions, "annotations": annotations}
    try:
        json.dumps(result, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise LoCoMoError("source must contain finite JSON values") from exc
    return result
