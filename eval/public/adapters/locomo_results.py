"""Assemble one development result from replayed native artifacts.

This is a result projection, not a registered bundle writer or publication gate.
Caller-supplied run identity remains explicit; replay cannot invent it.
"""
from copy import deepcopy
from hashlib import sha256
import re

from leaderboard.validate import DIGEST_PAYLOAD_NAMES, SCHEMA_VERSION_V2, validate_record
from .locomo import LoCoMoError, UPSTREAM_REVISION
from .locomo_config import validate_native_run_config
from .locomo_replay import _decode, verify_report_in_environment

_REQUIRED = {"benchmark.json", "build.json", "config.json", "traces.jsonl", "native-replay.json", "bundle-manifest.json"}


def assemble_development_result(metadata: dict, payloads: dict[str, bytes], *, scorer_python) -> dict:
    """Bind explicit metadata to verified QA metrics and original artifact bytes.

    Retrieval summaries stay in native-replay.json under the same atomic attempt.
    Resource/runtime admission, actual measurements and signatures remain outside
    this development projection; their status may not be promoted here.
    """
    if (not isinstance(payloads, dict) or not _REQUIRED <= set(payloads)
            or any(not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) is None
                   or not isinstance(raw, bytes) for name, raw in payloads.items())):
        raise LoCoMoError("native result requires named local artifact bytes")
    payloads = dict(payloads)  # Freeze the mapping; artifact byte values are immutable.
    manifest = _decode(payloads["bundle-manifest.json"])
    if (not isinstance(manifest, dict) or set(manifest) != {"files", "version"}
            or type(manifest["version"]) is not int or manifest["version"] != 1
            or not isinstance(manifest["files"], dict)
            or set(manifest["files"]) != set(payloads) - {"bundle-manifest.json"}):
        raise LoCoMoError("native result artifact inventory mismatch")
    if any(sha256(payloads[name]).hexdigest() != digest for name, digest in manifest["files"].items()):
        raise LoCoMoError("native result artifact digest mismatch")
    config, build, benchmark, report = (_decode(payloads[name]) for name in
                                      ("config.json", "build.json", "benchmark.json", "native-replay.json"))
    if (not isinstance(config, dict) or set(config) != {"family", "scoring_profile", "native_run"}
            or config["family"] != "native-memory-qa" or config["scoring_profile"] != "locomo-native-v1"):
        raise LoCoMoError("native result requires its separate scoring configuration")
    native = config["native_run"]
    validate_native_run_config(native)
    if native["choice_policy"]["id"] != "python-random-source-order/v1":
        raise LoCoMoError("native result identity requires an explicit option seed")
    commit = native["reader_policy"]["candidate_git_sha"]
    if (not isinstance(build, dict) or build.get("candidate_git_sha") != commit
            or build.get("system_seam") != "public-cli-subprocess"):
        raise LoCoMoError("native result build does not bind its candidate and public seam")
    if not isinstance(benchmark, dict) or "data" not in benchmark:
        raise LoCoMoError("native result benchmark data is missing")
    records = [_decode(line) for line in payloads["traces.jsonl"].splitlines() if line.strip()]
    derived = {"schema_version", "metrics", *DIGEST_PAYLOAD_NAMES}
    if not isinstance(metadata, dict) or set(metadata) & derived:
        raise LoCoMoError("native result metadata may not override projected fields")
    if not isinstance(report, dict) or not isinstance(report.get("category_metrics"), dict):
        raise LoCoMoError("native result requires a replay report")
    result = {**deepcopy(metadata), "schema_version": SCHEMA_VERSION_V2,
              "metrics": deepcopy(report["category_metrics"].get("reference_qa")),
              **{field: "sha256:" + sha256(payloads[name]).hexdigest() for field, name in DIGEST_PAYLOAD_NAMES.items()}}
    errors = validate_record(result)
    if errors:
        raise LoCoMoError("invalid native result metadata: " + ", ".join(errors))
    identity = result["identity"]
    expected = {"system_id": "mnemosyne", "adapter_id": "mnemosyne-locomo-native",
                "adapter_version": native["replay_protocol_sha256"], "benchmark_id": "locomo-native",
                "benchmark_version": UPSTREAM_REVISION, "backend_id": native["cli"]["backend"],
                "dataset_split_digest": "sha256:" + native["source_sha256"],
                "seed": native["choice_policy"]["seed"]}
    if (any(identity[key] != value for key, value in expected.items())
            or result["run_commit"] != commit or result["system"] != "mnemosyne"
            or result["benchmark"] != "locomo-native" or result["benchmark_version"] != UPSTREAM_REVISION
            or result["run_profile"]["seeds"] != [expected["seed"]]):
        raise LoCoMoError("native result identity does not match its replay configuration")
    if (result["track_kind"] != "DEVELOPMENT" or result["track"] != "development"
            or result["resources"]["treatment"] != "resource-unverified"
            or result["evidence_level"] != "IMPLEMENTED" or result["attempt_outcome"] != "not-measured"
            or result["admission_state"] not in {"PROPOSED", "CONTRACT-READY"}
            or result["custody"] != "development-public" or result["signer_role"] != "operator"
            or result["publication"]["label"] != "operator-run"
            or result["publication"].get("register_b_satisfied", False) is not False
            or any(gate["status"] == "passed" for gate in result["safety_gates"])):
        raise LoCoMoError("offline native projection cannot promote execution or admission claims")
    verify_report_in_environment(report, benchmark["data"], records,
        caption_policy=native["caption_policy"], choice_seed=expected["seed"],
        reader_policy=native["reader_policy"], run_config=native, python=scorer_python)
    return result
