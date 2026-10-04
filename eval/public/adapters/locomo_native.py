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


def project_native_response(response: dict, annotation: dict, evidence: dict, *,
                            choice_draw: float | None = None) -> dict:
    """Project a public response without treating execution failure as abstention.

    Reader disclosure presence is a prerequisite, not proof of runtime custody;
    the eventual registered runner must validate the actual provider manifest.
    """
    prepared = prepare_upstream_question(annotation, choice_draw=choice_draw)
    if not isinstance(response, dict) or type(response.get("abstained")) is not bool:
        raise LoCoMoError("native response requires explicit boolean abstained")
    reader, hops = response.get("reader"), response.get("hops")
    if not isinstance(reader, dict) or not isinstance(hops, list):
        raise LoCoMoError("native response requires reader and hop records")
    retrieved = []
    for hop in hops:
        if not isinstance(hop, dict) or not isinstance(hop.get("retrieved_cids"), list):
            raise LoCoMoError("native retrieval hop is malformed")
        for cid in hop["retrieved_cids"]:
            if not isinstance(cid, str) or cid not in evidence:
                raise LoCoMoError("native response references unregistered evidence")
            dialog = evidence[cid]["dialog_id"]
            if dialog not in retrieved:
                retrieved.append(dialog)
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
