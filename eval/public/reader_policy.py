"""Explicit reader disclosure policy; matching is not runtime attestation."""
from copy import deepcopy
from hashlib import sha256
import json
import re


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def grounded_reader_disclosure(model_content_sha256: str) -> dict:
    from mnemosyne.providers.extractive_decomposer import disclosure
    from mnemosyne.providers.grounded_protocol import GENERATION_SPEC, MODEL_SELECTOR, role_digests
    return {"query_decomposer": disclosure(), "grounded_reader": {
        "role": "grounded_reader", "model": MODEL_SELECTOR,
        "model_content_digest": model_content_sha256, **role_digests("grounded_reader"),
        "decoding_options": deepcopy(GENERATION_SPEC),
    }}


def candidate_reader_policy(candidate: dict) -> dict:
    """Bind the existing validated candidate to its expected public disclosure."""
    from eval.public.runner import validate_candidate_manifest
    validate_candidate_manifest(candidate)
    policy = {"schema_version": "mnemosyne.reader-policy/v1",
              "candidate_git_sha": candidate["git_sha"],
              "candidate_manifest_sha256": sha256(_canonical(candidate) + b"\n").hexdigest(),
              "reader": grounded_reader_disclosure(candidate["model_content_sha256"])}
    validate_reader_policy(policy)
    return policy


def validate_reader_policy(policy: dict) -> str:
    """Validate disclosure structure and return a canonical policy digest.

    The caller must separately authenticate/admit the candidate manifest and
    runtime. A well-formed policy or matching disclosure cannot prove either.
    """
    if (not isinstance(policy, dict) or set(policy) != {
            "schema_version", "candidate_git_sha", "candidate_manifest_sha256", "reader"}
            or policy["schema_version"] != "mnemosyne.reader-policy/v1"):
        raise ValueError("invalid reader policy schema")
    for field, length in (("candidate_git_sha", 40), ("candidate_manifest_sha256", 64)):
        value = policy[field]
        if not isinstance(value, str) or re.fullmatch(f"[0-9a-f]{{{length}}}", value) is None:
            raise ValueError("invalid reader policy candidate identity")
    reader = policy["reader"]
    if not isinstance(reader, dict) or set(reader) != {"query_decomposer", "grounded_reader"}:
        raise ValueError("reader policy requires both public roles")
    for role, disclosure in reader.items():
        if (not isinstance(disclosure, dict) or set(disclosure) != {
                "role", "model", "model_content_digest", "prompt_sha256", "serializer_sha256",
                "decoding_sha256", "decoding_options"} or disclosure["role"] != role
                or not isinstance(disclosure["model"], str) or not disclosure["model"].strip()
                or not isinstance(disclosure["decoding_options"], dict) or not disclosure["decoding_options"]):
            raise ValueError("invalid reader policy role")
        for field in ("model_content_digest", "prompt_sha256", "serializer_sha256", "decoding_sha256"):
            if not isinstance(disclosure[field], str) or re.fullmatch("[0-9a-f]{64}", disclosure[field]) is None:
                raise ValueError("invalid reader policy role digest")
        if sha256(_canonical(disclosure["decoding_options"])).hexdigest() != disclosure["decoding_sha256"]:
            raise ValueError("reader policy decoding digest mismatch")
    return sha256(_canonical(policy)).hexdigest()


def match_reader_policy(reader: dict, policy: dict) -> bool:
    validate_reader_policy(policy)
    if not isinstance(reader, dict) or set(reader) not in (set(), {"query_decomposer"}, {"query_decomposer", "grounded_reader"}):
        raise ValueError("reader disclosure roles do not match policy")
    if any(_canonical(value) != _canonical(policy["reader"][role]) for role, value in reader.items()):
        raise ValueError("reader disclosure does not match policy")
    return set(reader) == {"query_decomposer", "grounded_reader"}
