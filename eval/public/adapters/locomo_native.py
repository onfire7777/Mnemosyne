"""Native LoCoMo public capture boundary; not an admitted benchmark runner."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from eval.harness.cli_driver import MnemoCLI
from eval.public.custody import capture_cid
from .locomo import LoCoMoError, decode_upstream_category5, normalize_dialogs, prepare_upstream_question


def answer_captured_question(conversation: dict, question: dict, annotation: dict, *,
                             choice_draw: float | None = None) -> dict:
    """Invoke the public ephemeral answer path and retain exact request custody.

    The caller owns dataset/run admission and provider/resource configuration.
    CLI exceptions propagate to that caller's attempt ledger; they are never
    converted to successful abstention. This function does not admit a run.
    """
    if (question.get("sample_id") != conversation["sample_id"]
            or not isinstance(question.get("question_id"), str) or not question["question_id"]
            or question.get("query") != annotation.get("question")):
        raise LoCoMoError("native question does not match its conversation and annotation")
    prepared = prepare_upstream_question(annotation, choice_draw=choice_draw)
    cli = conversation["cli"]
    if not isinstance(cli, MnemoCLI) or not Path(cli.store).is_file():
        raise LoCoMoError("native question requires a live captured store")
    request = {"question_id": question["question_id"], "question": prepared["query"],
               "context": {"tenant_id": conversation["tenant_id"], "user_id": "locomo", "role": "reader"}}
    raw_request = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    read_only = replace(cli, global_flags=[*cli.global_flags, "--evaluation-read-only"])
    with TemporaryDirectory(prefix="mneme-locomo-question-") as directory:
        path = Path(directory) / "request.jsonl"
        path.write_text(raw_request, encoding="utf-8")
        payload = read_only.eval_answer_batch(path)
    results = payload.get("results") if isinstance(payload, dict) else None
    if (not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict)
            or results[0].get("question_id") != question["question_id"]):
        raise LoCoMoError("native answer result does not match requested question")
    projection = project_native_response(results[0], annotation, conversation["evidence"],
                                         choice_draw=choice_draw)
    return {**projection, "question_id": question["question_id"],
            "request": request, "request_jsonl": raw_request,
            "request_sha256": sha256(raw_request.encode()).hexdigest(),
            "raw_batch_response": deepcopy(payload)}


def project_native_response(response: dict, annotation: dict, evidence: dict, *,
                            choice_draw: float | None = None) -> dict:
    """Project a public response without treating execution failure as abstention.

    Reader disclosure presence is a prerequisite, not proof of runtime custody;
    the eventual registered runner must validate the actual provider manifest.
    """
    prepared = prepare_upstream_question(annotation, choice_draw=choice_draw)
    if not isinstance(response, dict) or type(response.get("abstained")) is not bool:
        raise LoCoMoError("native response requires explicit boolean abstained")
    reader, hops, claims = response.get("reader"), response.get("hops"), response.get("claims")
    if not isinstance(reader, dict) or not isinstance(hops, list) or not isinstance(claims, list):
        raise LoCoMoError("native response requires reader, hop and claim records")
    for claim in claims:
        if (not isinstance(claim, dict) or not isinstance(claim.get("text"), str)
                or not isinstance(claim.get("evidence_cids"), list)
                or not isinstance(claim.get("spans"), list)):
            raise LoCoMoError("native claim is malformed")
        cited = claim["evidence_cids"]
        if any(not isinstance(cid, str) or cid not in evidence for cid in cited):
            raise LoCoMoError("native claim references unregistered evidence")
        for span in claim["spans"]:
            if not isinstance(span, dict) or not isinstance(span.get("cid"), str) or span["cid"] not in cited:
                raise LoCoMoError("native span must refer to the claim's registered evidence")
            content = evidence[span["cid"]].get("capture", {}).get("content")
            start, end = span.get("start"), span.get("end")
            if (not isinstance(content, str) or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(content)
                    or span.get("slice_sha256") != sha256(content[start:end].encode()).hexdigest()):
                raise LoCoMoError("native span does not match captured content")
    retrieved = []
    retrieved_cids = set()
    for hop in hops:
        if not isinstance(hop, dict) or not isinstance(hop.get("retrieved_cids"), list):
            raise LoCoMoError("native retrieval hop is malformed")
        for cid in hop["retrieved_cids"]:
            if not isinstance(cid, str) or cid not in evidence:
                raise LoCoMoError("native response references unregistered evidence")
            retrieved_cids.add(cid)
            dialog = evidence[cid]["dialog_id"]
            if dialog not in retrieved:
                retrieved.append(dialog)
    if any(cid not in retrieved_cids for claim in claims for cid in claim["evidence_cids"]):
        raise LoCoMoError("native claim cites evidence absent from retrieval trace")
    result = {"raw_response": deepcopy(response), "question_transformation": prepared,
              "retrieved_dialog_ids": retrieved, "decoded_prediction": None,
              "projection_policy": "native-explicit-abstention-v1",
              "status": "incomplete-reader-execution", "runtime_custody_verified": False}
    if not isinstance(reader.get("grounded_reader"), dict) or not reader["grounded_reader"]:
        return result
    answer = response.get("answer")
    if response["abstained"]:
        if answer not in (None, ""):
            raise LoCoMoError("native abstention contradicts nonempty answer")
        decoded = "No information available"
    else:
        if not isinstance(answer, str) or not answer.strip():
            raise LoCoMoError("native non-abstention requires an answer")
        decoded = (decode_upstream_category5(answer, prepared["answer_key"])["decoded_prediction"]
                   if prepared["category"] == 5 else answer.strip())
    result.update(status="projected", decoded_prediction=decoded)
    return result


@contextmanager
def captured_conversations(samples: object, cli: MnemoCLI, *, caption_policy: str):
    """Yield public CLI handles and verified evidence maps for isolated stores.

    Handles are valid only inside the context. Native preprocessing serializes
    source date/speaker/text/caption as JSON; this is not an upstream prompt.
    No explicit consolidation, answer call, clock advance or scoring occurs.
    """
    if not isinstance(cli, MnemoCLI) or cli.backend != "local":
        raise LoCoMoError("native capture requires an isolated local MnemoCLI")
    normalized = normalize_dialogs(samples, caption_policy=caption_policy)
    by_sample = {}
    for record in normalized["records"]:
        by_sample.setdefault(record["sample_id"], []).append(record)
    with TemporaryDirectory(prefix="mneme-locomo-native-") as directory:
        captured = []
        for index, (sample_id, records) in enumerate(by_sample.items()):
            tenant = "locomo:" + sha256(sample_id.encode()).hexdigest()
            child = replace(cli, store=str(Path(directory) / f"{index}.store.json"))
            rows, expected = [], {}
            for record in records:
                content = json.dumps({key: record[key] for key in
                                      ("source_timestamp", "speaker", "text", "caption")},
                                     sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                capture = {"tenant_id": tenant, "user_id": "locomo", "actor": "user",
                           "source_type": "locomo:dialog:" + record["record_id"],
                           "source_identity": record["record_id"], "content": content,
                           "content_pointer": None, "modality": "text", "sensitivity": 0}
                cid = capture_cid(capture)
                if cid in expected:
                    raise LoCoMoError("native capture produced duplicate expected evidence IDs")
                expected[cid] = {"capture": capture, "record_id": record["record_id"],
                                 "dialog_id": record["dialog_id"], "session_id": record["session_id"]}
                rows.append({"tenant": tenant, "user": "locomo", "content": content,
                             "source_type": capture["source_type"],
                             "source_identity": capture["source_identity"]})
            path = Path(directory) / f"{index}.capture.jsonl"
            path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
            results = child.capture_batch(path).get("results")
            if not isinstance(results, list) or len(results) != len(expected):
                raise LoCoMoError("native capture result count mismatch")
            actual = [row.get("cid") if isinstance(row, dict) else None for row in results]
            if actual != list(expected):
                raise LoCoMoError("native capture evidence IDs do not match declared inputs")
            captured.append({"sample_id": sample_id, "tenant_id": tenant,
                             "cli": child, "evidence": expected,
                             "caption_policy": caption_policy,
                             "explicit_lifecycle_operations": []})
        yield captured
