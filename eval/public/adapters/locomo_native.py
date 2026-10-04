"""Native LoCoMo public capture boundary; not an admitted benchmark runner."""
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from eval.harness.cli_driver import MnemoCLI
from eval.public.custody import capture_cid
from .locomo import LoCoMoError, normalize_dialogs


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
