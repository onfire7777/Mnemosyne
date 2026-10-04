"""LoCoMo ingestion boundary; not yet an admitted runnable benchmark adapter."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re

UPSTREAM_REVISION = "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"
INPUT_SCHEMA = "mnemosyne.locomo-input/v1"


class LoCoMoError(ValueError):
    """A source sample cannot be separated into unambiguous inputs and labels."""


def normalize_dialogs(samples: object, *, caption_policy: str) -> dict:
    """Build label-free dialog records; not an upstream prompt or admitted run.

    Source timestamps remain verbatim: interpreting them or advancing a clock
    belongs to the registered adapter. Only an explicit caption policy controls
    whether supplied BLIP text enters memory. Image URLs are never fetched.
    """
    if caption_policy not in ("include-source-caption", "exclude-caption"):
        raise LoCoMoError("an explicit supported caption_policy is required")
    separated = split_samples(samples)
    records = []
    for entry in separated["conversations"]:
        sample_id, conversation = entry["sample_id"], entry["conversation"]
        if any(not isinstance(key, str) for key in conversation):
            raise LoCoMoError("conversation keys must be strings")
        sessions = sorted(int(key[8:]) for key in conversation
                          if re.fullmatch(r"session_[1-9][0-9]*", key))
        if not sessions:
            raise LoCoMoError("conversation has no numbered sessions")
        valid_session_keys = {f"session_{number}{suffix}" for number in sessions
                              for suffix in ("", "_date_time")}
        if any(key.startswith("session_") and key not in valid_session_keys
               for key in conversation):
            raise LoCoMoError("malformed session key or orphan timestamp")
        seen_dialogs = set()
        for number in sessions:
            session_id = f"session_{number}"
            timestamp = conversation.get(session_id + "_date_time")
            dialogs = conversation[session_id]
            if not isinstance(timestamp, str) or not timestamp.strip():
                raise LoCoMoError("session requires a source timestamp")
            if not isinstance(dialogs, list) or not dialogs:
                raise LoCoMoError("session requires a non-empty dialog list")
            for position, dialog in enumerate(dialogs):
                if not isinstance(dialog, dict):
                    raise LoCoMoError("dialog must be an object")
                for field in ("dia_id", "speaker", "text"):
                    if not isinstance(dialog.get(field), str) or not dialog[field].strip():
                        raise LoCoMoError(f"dialog requires non-empty {field}")
                dialog_id = dialog["dia_id"]
                if dialog_id in seen_dialogs:
                    raise LoCoMoError("duplicate dialog ID within conversation")
                seen_dialogs.add(dialog_id)
                caption = dialog.get("blip_caption")
                if "blip_caption" in dialog and not isinstance(caption, str):
                    raise LoCoMoError("source caption must be a string")
                identity = json.dumps([sample_id, session_id, dialog_id],
                                      ensure_ascii=True, separators=(",", ":"))
                records.append({
                    "record_id": "locomo-dialog:" + sha256(identity.encode()).hexdigest(),
                    "sample_id": sample_id, "session_id": session_id,
                    "dialog_id": dialog_id, "position": position,
                    "source_timestamp": timestamp, "speaker": dialog["speaker"],
                    "text": dialog["text"],
                    "caption": caption if caption_policy == "include-source-caption" else None,
                })
    return {"schema_version": "mnemosyne.locomo-dialogs/v1",
            "upstream_revision": UPSTREAM_REVISION, "caption_policy": caption_policy,
            "records": records}


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


def prepare_upstream_question(annotation: dict, *, choice_draw: float | None = None) -> dict:
    """Apply the pinned GPT question transformation with caller-owned randomness.

    This is only the question transformation, not the surrounding model prompt.
    The caller must retain this record and its registered RNG state for replay.
    """
    import math

    if not isinstance(annotation, dict):
        raise LoCoMoError("annotation must be an object")
    query, category = annotation.get("question"), annotation.get("category")
    if not isinstance(query, str) or not query:
        raise LoCoMoError("question must be a non-empty string")
    if type(category) is not int or category not in range(1, 6):
        raise LoCoMoError("category must be an integer from 1 through 5")
    answer_key = None
    if category == 5:
        if (type(choice_draw) not in (float, int) or not 0 <= choice_draw < 1
                or not math.isfinite(choice_draw)):
            raise LoCoMoError("category 5 requires a recorded choice draw in [0, 1)")
        answer = annotation.get("answer")
        if not isinstance(answer, str):
            raise LoCoMoError("category 5 distractor must be a string")
        choices = ["Not mentioned in the conversation", answer]
        if choice_draw >= 0.5:
            choices.reverse()
        answer_key = dict(zip(("a", "b"), choices, strict=True))
        query += f" Select the correct answer: (a) {choices[0]} (b) {choices[1]}. "
    else:
        if choice_draw is not None:
            raise LoCoMoError("choice draw is only valid for category 5")
        if category == 2:
            query += " Use DATE of CONVERSATION to answer with an approximate date."
    return {"upstream_revision": UPSTREAM_REVISION, "category": category,
            "query": query, "choice_draw": choice_draw, "answer_key": answer_key}


def decode_upstream_category5(raw_prediction: str, answer_key: dict) -> dict:
    """Retain raw text and the upstream decoder's unusual short-output behavior.

    This is not a robust semantic answer parser: parity deliberately maps any
    one-character non-a or three-character non-(a) response to option b.
    """
    if not isinstance(raw_prediction, str):
        raise LoCoMoError("prediction must be a string")
    if (not isinstance(answer_key, dict) or set(answer_key) != {"a", "b"}
            or any(not isinstance(value, str) for value in answer_key.values())):
        raise LoCoMoError("answer key must contain string choices a and b")
    normalized = raw_prediction.strip().lower()
    if len(normalized) == 1:
        decoded = answer_key["a" if normalized == "a" else "b"]
    elif len(normalized) == 3:
        decoded = answer_key["a" if normalized == "(a)" else "b"]
    else:
        decoded = normalized
    return {"raw_prediction": raw_prediction, "decoded_prediction": decoded,
            "upstream_revision": UPSTREAM_REVISION}


def prepare_single_question_prompt(context: str, annotation: dict, *,
                                   choice_draw: float | None = None) -> dict:
    """Reproduce pinned GPT batch-size-one prompt assembly on supplied context.

    Context construction, retrieval and token budgeting are separate contracts.
    This does not claim that arbitrary supplied context is upstream-equivalent.
    Retain the returned record alongside raw model output for later replay.
    """
    if not isinstance(context, str):
        raise LoCoMoError("context must be a string")
    prepared = prepare_upstream_question(annotation, choice_draw=choice_draw)
    if prepared["category"] == 5:
        instruction = "Based on the above context, answer the following question."
    else:
        instruction = ("Based on the above context, write an answer in the form of a short phrase "
                       "for the following question. Answer with exact words from the context whenever possible.")
    prompt = context + "\n\n\n" + instruction + "\n\nQuestion: " + prepared["query"] + " Short answer:\n"
    return {"schema_version": "mnemosyne.locomo-single-question-prompt/v1",
            "upstream_revision": UPSTREAM_REVISION, "batch_size": 1,
            "question": prepared, "prompt": prompt,
            "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
            "context_sha256": sha256(context.encode("utf-8")).hexdigest(),
            "generation": {"num_gen": 1, "num_tokens_request": 32, "temperature": 0},
            "context_conformance_verified": False}


def prepare_nonrag_context(sample: dict, *, token_count, max_length: int,
                           num_question_tokens: int, batch_size: int) -> dict:
    """Preserve pinned non-RAG context ordering and strict budget comparison.

    token_count must use the registered tokenizer. num_question_tokens must
    include upstream's batch-question prompt and conversation-start prompt.
    This function does not prepend the start prompt or enforce a final model
    limit: upstream may emit headers even when the first turn does not fit.
    """
    for name, value, minimum in (("max_length", max_length, 1),
                                  ("num_question_tokens", num_question_tokens, 0),
                                  ("batch_size", batch_size, 1)):
        if type(value) is not int or value < minimum:
            raise LoCoMoError(f"{name} must be an integer >= {minimum}")
    if not callable(token_count):
        raise LoCoMoError("token_count must be callable")

    def count(text):
        value = token_count(text)
        if type(value) is not int or value < 0:
            raise LoCoMoError("token_count must return a non-negative integer")
        return value

    records = normalize_dialogs([sample], caption_policy="include-source-caption")["records"]
    sessions = {}
    for record in records:
        sessions.setdefault(record["session_id"], []).append(record)
    context, included, omitted_at = "", [], None
    for session in sessions.values():
        context += "\n\n"
        header = "DATE: " + session[0]["source_timestamp"] + "\nCONVERSATION:\n"
        for record in reversed(session):
            turn = record["speaker"] + ' said, "' + record["text"] + '"\n'
            if record["caption"] is not None:
                turn += " and shared " + record["caption"] + "."
            turn += "\n"
            if count(header + turn) + count(context) + num_question_tokens < max_length - 50 * batch_size:
                context = turn + context
                included.insert(0, record["record_id"])
            else:
                omitted_at = record["record_id"]
                break
        context = header + context
        if omitted_at is not None:
            break
    return {"schema_version": "mnemosyne.locomo-nonrag-context/v1",
            "upstream_revision": UPSTREAM_REVISION, "context": context,
            "context_sha256": sha256(context.encode()).hexdigest(),
            "included_record_ids": included, "first_omitted_record_id": omitted_at,
            "truncated": omitted_at is not None,
            "budget": {"max_length": max_length, "num_question_tokens": num_question_tokens,
                       "batch_size": batch_size, "reserved_answer_tokens": 50 * batch_size},
            "tokenizer_conformance_verified": False}


def prepare_nonrag_request(sample: dict, question_index: int, *, speaker_order: list[str],
                           token_count, max_length: int, choice_draw: float | None = None) -> dict:
    """Compose the upstream single-question non-RAG path with explicit ordering.

    The caller must record the upstream speaker order rather than silently sort
    the original set. Tokenizer identity/model mapping and execution remain the
    runner's responsibility; this request is not an admitted benchmark result.
    """
    separated = split_samples([sample])
    if type(question_index) is not int or not 0 <= question_index < len(separated["questions"]):
        raise LoCoMoError("question_index must select a source question")
    normalize_dialogs([sample], caption_policy="include-source-caption")
    first_session = sample["conversation"].get("session_1")
    if not isinstance(first_session, list) or not first_session:
        raise LoCoMoError("upstream start prompt requires session_1")
    source_speakers = {turn["speaker"] for turn in first_session}
    if (not isinstance(speaker_order, list) or len(speaker_order) != 2
            or any(not isinstance(speaker, str) for speaker in speaker_order)
            or len(set(speaker_order)) != 2 or set(speaker_order) != source_speakers):
        raise LoCoMoError("speaker_order must explicitly order the two session_1 speakers")
    start = (f"Below is a conversation between two people: {speaker_order[0]} and {speaker_order[1]}. "
             "The conversation takes place over multiple days and the date of each conversation "
             "is wriiten at the beginning of the conversation.\n\n")
    annotation = sample["qa"][question_index]
    question = prepare_upstream_question(annotation, choice_draw=choice_draw)
    batch_prompt = ('\nBased on the above conversations, write short answers for each of the following '
                    'questions in a few words. \nWrite the answers in the form of a json dictionary where '
                    'each entry contains the question number as "key" and the short answer as "value". \n'
                    'Use single-quote characters for named entities and double-quote characters for '
                    'enclosing json elements. Answer with exact words from the conversations whenever possible.\n\n')
    if not callable(token_count):
        raise LoCoMoError("token_count must be callable")
    counts = [token_count(start), token_count(batch_prompt + "0: " + question["query"])]
    if any(type(count) is not int or count < 0 for count in counts):
        raise LoCoMoError("token_count must return a non-negative integer")
    context = prepare_nonrag_context(sample, token_count=token_count, max_length=max_length,
                                     num_question_tokens=sum(counts), batch_size=1)
    request = prepare_single_question_prompt(start + context["context"], annotation,
                                              choice_draw=choice_draw)
    request.update({"question_id": separated["questions"][question_index]["question_id"],
                    "speaker_order": list(speaker_order), "context_assembly": context,
                    "mode": "nonrag-single-question", "publication_authorized": False})
    return request
