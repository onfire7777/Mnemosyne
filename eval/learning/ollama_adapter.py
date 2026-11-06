"""Local-only Ollama adapter for the learning benchmark command protocol."""

from __future__ import annotations

import json
import argparse
import hashlib
from pathlib import Path
import sys
from urllib.request import Request, urlopen


def respond(payload: dict, *, timeout_seconds: float = 55) -> dict:
    if payload.get("schema") != "mnemosyne.learning-agent.v1":
        raise ValueError("unsupported learning-agent protocol")

    identifiers = {
        name: sorted(
            {
                item["id"]
                for key in keys
                for item in payload["memory"].get(key, [])
                if isinstance(item, dict) and item.get("id")
            }
        )
        for name, keys in (
            ("skill", ("skills", "procedures", "chunks")),
            ("lesson", ("lessons",)),
        )
    }

    request = {
        "model": payload["model"],
        "messages": [
            {
                "role": "system",
                "content": payload["system"]
                + " For this local transport, return used_skill_index and used_lesson_index"
                " instead of ID arrays. Select -1 when none was used, or the zero-based"
                " index of the single artifact you followed from artifact_indexes.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": payload["request"],
                        "memory": payload["memory"],
                        "artifact_indexes": identifiers,
                    }
                ),
            },
        ],
        "stream": False,
        "think": False,
        "keep_alive": "30m",
        "format": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": payload["request"]["choices"]},
                **{
                    f"used_{kind}_index": {
                        "type": "integer",
                        "enum": [-1, *range(len(ids))],
                    }
                    for kind, ids in identifiers.items()
                },
            },
            "required": ["action", "used_skill_index", "used_lesson_index"],
        },
        "options": {
            "temperature": payload["temperature"],
            "seed": payload["seed"],
            "num_predict": 128,
        },
    }
    http_request = Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(request).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(http_request, timeout=timeout_seconds) as response:
        result = json.load(response)
    if not result.get("done") or result.get("done_reason") == "length":
        raise ValueError("local model did not finish its response")
    answer = json.loads(result["message"]["content"])
    for kind, ids in identifiers.items():
        index = answer.pop(f"used_{kind}_index")
        if type(index) is not int or not -1 <= index < len(ids):
            raise ValueError("model selected an unserved artifact index")
        answer[f"used_{kind}s"] = [] if index == -1 else [ids[index]]
    answer["provider_metadata"] = {
        key: result[key]
        for key in (
            "model",
            "done_reason",
            "total_duration",
            "load_duration",
            "prompt_eval_count",
            "eval_count",
        )
        if key in result
    }
    answer["provider_metadata"]["decoding"] = request["options"]
    answer["provider_metadata"]["keep_alive"] = request["keep_alive"]
    return answer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-dir", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=55)
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if args.trace_dir:
        args.trace_dir.mkdir(parents=True, exist_ok=True)
        (args.trace_dir / f"{key}.request.json").write_text(
            json.dumps(payload, indent=2)
        )
    try:
        result = respond(payload, timeout_seconds=args.timeout_seconds)
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        if args.trace_dir:
            (args.trace_dir / f"{key}.error.txt").write_text(detail)
        print(detail, file=sys.stderr)
        raise SystemExit(1) from None
    if args.trace_dir:
        (args.trace_dir / f"{key}.response.json").write_text(
            json.dumps(result, indent=2)
        )
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
