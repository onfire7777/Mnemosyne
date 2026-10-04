"""Offline reference-tokenizer audit; never loads weights or calls a provider.

Optional tool environment: tokenizers==0.22.1. Inputs are an Ollama verbose
api/show capture, the pinned Qwen tokenizer.json, and exported system/user
strings from grounded_protocol.render_prompt. This is diagnostic evidence,
not proof of Ollama tokenization, template execution or resource admission.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

TOKENIZER_SHA256 = "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4"
TOKENIZER_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"


def read_json(path: Path) -> tuple[bytes, dict]:
    with path.open("rb") as source:
        raw = source.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("audit input exceeds 20 MiB")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("audit inputs must be JSON objects")
    return raw, value


def audit(metadata_path: Path, tokenizer_path: Path, prompts_path: Path) -> dict:
    if importlib.metadata.version("tokenizers") != "0.22.1":
        raise ValueError("this audit requires tokenizers==0.22.1")
    from tokenizers import Tokenizer

    metadata_raw, metadata = read_json(metadata_path)
    tokenizer_raw, reference = read_json(tokenizer_path)
    _, prompts = read_json(prompts_path)
    if hashlib.sha256(tokenizer_raw).hexdigest() != TOKENIZER_SHA256:
        raise ValueError("reference tokenizer differs from the pinned artifact")
    info = metadata["model_info"]
    if (info["general.architecture"], info["tokenizer.ggml.pre"]) != ("qwen3", "qwen2"):
        raise ValueError("unexpected model architecture or pre-tokenizer")
    tokens = info["tokenizer.ggml.tokens"]
    vocab = reference["model"]["vocab"]
    if any(tokens[index] != token for token, index in vocab.items()):
        raise ValueError("model vocabulary differs from reference")
    if any(tokens[item["id"]] != item["content"] for item in reference["added_tokens"]):
        raise ValueError("model added-token IDs differ from reference")
    merges = [" ".join(pair) for pair in reference["model"]["merges"]]
    if merges != info["tokenizer.ggml.merges"]:
        raise ValueError("model merge rules differ from reference")
    if set(prompts) != {"system", "user"} or any(
        not isinstance(text, str) or not text or not text.isascii()
        for text in prompts.values()
    ):
        raise ValueError("this diagnostic is limited to nonempty ASCII system/user prompts")
    tokenizer = Tokenizer.from_str(tokenizer_raw.decode("utf-8"))
    counts = {
        role: {
            "characters": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "reference_tokens": len(tokenizer.encode(text, add_special_tokens=False).ids),
        }
        for role, text in prompts.items()
    }
    return {
        "schema": "mnemosyne.qwen-reference-context-audit/v1",
        "tokenizer_revision": TOKENIZER_REVISION,
        "tokenizer_sha256": TOKENIZER_SHA256,
        "tokenizers_version": "0.22.1",
        "model_metadata_sha256": hashlib.sha256(metadata_raw).hexdigest(),
        "matched_vocabulary_entries": len(vocab),
        "matched_added_token_ids": len(reference["added_tokens"]),
        "matched_merge_rules": len(merges),
        "prompts": counts,
        "scope": "Separate message contents only; excludes chat template and output tokens.",
        "runtime_tokenizer_equivalence_verified": False,
        "full_context_coverage_verified": False,
        "resource_admission_verified": False,
        "model_execution_performed": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_metadata", type=Path)
    parser.add_argument("tokenizer", type=Path)
    parser.add_argument("prompts", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.model_metadata, args.tokenizer, args.prompts), indent=2, sort_keys=True))
