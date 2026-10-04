"""Source-bound native run declarations; not runtime or resource attestation."""
from copy import deepcopy
from hashlib import sha256
import json
import math
import re

from eval.public.reader_policy import validate_reader_policy
from .locomo import LoCoMoError, native_choice_policy, normalize_dialogs

_FIELDS = {"schema_version", "source_sha256", "normalized_sha256", "replay_protocol_sha256",
           "caption_policy", "choice_policy", "reader_policy", "runtime_manifest_sha256",
           "resource_manifest_sha256", "cli"}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return sha256(_canonical(value)).hexdigest()


def _cli_policy(cli):
    return {"backend": cli.backend, "global_flags_sha256": _digest(list(cli.global_flags)),
            "timeout_seconds": cli.timeout_s}


def validate_native_run_config(config: dict, *, cli=None) -> str:
    """Check closed declaration structure, optionally against the invoked CLI.

    Referenced runtime/resource artifacts require independent authentication and
    enforcement. Neither their hashes nor a matching CLI declaration prove it.
    """
    if (not isinstance(config, dict) or set(config) != _FIELDS
            or config["schema_version"] != "mnemosyne.locomo-native-config/v1"):
        raise LoCoMoError("invalid native run configuration schema")
    for field in _FIELDS:
        if field.endswith("_sha256"):
            if not isinstance(config[field], str) or re.fullmatch("[0-9a-f]{64}", config[field]) is None:
                raise LoCoMoError("native run configuration requires exact artifact digests")
    try:
        validate_reader_policy(config["reader_policy"])
    except (ValueError, TypeError) as exc:
        raise LoCoMoError("native run configuration requires a reader policy") from exc
    policy = config["cli"]
    if (not isinstance(policy, dict) or set(policy) != {"backend", "global_flags_sha256", "timeout_seconds"}
            or policy["backend"] != "local"
            or not isinstance(policy["global_flags_sha256"], str)
            or re.fullmatch("[0-9a-f]{64}", policy["global_flags_sha256"]) is None
            or type(policy["timeout_seconds"]) not in (int, float)
            or not math.isfinite(policy["timeout_seconds"]) or policy["timeout_seconds"] <= 0):
        raise LoCoMoError("native run configuration has invalid CLI settings")
    choice = config["choice_policy"]
    if (not isinstance(choice, dict) or set(choice) != {"id", "seed", "draws"}
            or choice["id"] not in {"explicit-draws/v1", "python-random-source-order/v1"}
            or not isinstance(choice["draws"], dict)):
        raise LoCoMoError("native run configuration has invalid choice policy")
    if choice["id"] == "explicit-draws/v1":
        if choice["seed"] is not None:
            raise LoCoMoError("explicit native choices cannot declare a seed")
    elif type(choice["seed"]) is not int or not 0 <= choice["seed"] < 2 ** 64:
        raise LoCoMoError("seeded native choices require an unsigned 64-bit seed")
    if any(not isinstance(key, str) or type(value) not in (int, float)
           or not math.isfinite(value) or not 0 <= value < 1
           for key, value in choice["draws"].items()):
        raise LoCoMoError("invalid native choice draw")
    if config["caption_policy"] not in ("include-source-caption", "exclude-caption"):
        raise LoCoMoError("native run configuration has invalid caption policy")
    if cli is not None and _canonical(_cli_policy(cli)) != _canonical(policy):
        raise LoCoMoError("invoked CLI does not match native run configuration")
    return _digest(config)


def build_native_run_config(samples, cli, *, caption_policy: str, reader_policy: dict,
                            runtime_manifest_sha256: str, resource_manifest_sha256: str,
                            choice_draws: dict | None = None, choice_seed: int | None = None) -> dict:
    """Freeze inputs and artifact references before execution, without admitting a run."""
    from .locomo_scoring import native_replay_protocol
    config = {"schema_version": "mnemosyne.locomo-native-config/v1",
              "source_sha256": _digest(samples),
              "normalized_sha256": _digest(normalize_dialogs(samples, caption_policy=caption_policy)),
              "replay_protocol_sha256": _digest(native_replay_protocol()),
              "caption_policy": caption_policy,
              "choice_policy": native_choice_policy(samples, choice_draws=choice_draws, choice_seed=choice_seed),
              "reader_policy": deepcopy(reader_policy), "runtime_manifest_sha256": runtime_manifest_sha256,
              "resource_manifest_sha256": resource_manifest_sha256, "cli": _cli_policy(cli)}
    validate_native_run_config(config, cli=cli)
    return config


def bind_native_run_config(config, samples, *, caption_policy, choice_policy, reader_policy, cli=None):
    """Recompute input/protocol bindings, returning the exact declaration digest."""
    from .locomo_scoring import native_replay_protocol
    digest = validate_native_run_config(config, cli=cli)
    expected = {"source_sha256": _digest(samples),
                "normalized_sha256": _digest(normalize_dialogs(samples, caption_policy=caption_policy)),
                "replay_protocol_sha256": _digest(native_replay_protocol()),
                "caption_policy": caption_policy, "choice_policy": choice_policy,
                "reader_policy": reader_policy}
    if any(_canonical(config[key]) != _canonical(value) for key, value in expected.items()):
        raise LoCoMoError("native run configuration does not match inputs or replay policy")
    return digest


def verify_native_artifacts(config: dict, artifacts: dict, *, repo_root=None) -> dict:
    """Verify referenced bytes and candidate-owned runtime files without running them.

    The resource file is hash-bound only: its contents do not discharge resource
    admission, and file custody does not attest model execution or registration.
    """
    from pathlib import Path
    from eval.public.reader_policy import candidate_reader_policy
    from eval.public.runner import _current_clean_head, _reject_symlink_components, validate_candidate_manifest
    from eval.public.runtime_custody import grounded_runtime_environment
    from .locomo_replay import _decode

    validate_native_run_config(config)
    if not isinstance(artifacts, dict) or set(artifacts) != {"candidate", "runtime", "resource"}:
        raise LoCoMoError("native artifact verification requires candidate, runtime and resource paths")
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    paths, raw, parsed = {}, {}, {}
    for name, value in artifacts.items():
        path = Path(value).expanduser().absolute()
        _reject_symlink_components(path)
        if not path.is_file():
            raise LoCoMoError("native artifact must be a regular file")
        with path.open("rb") as handle:
            content = handle.read(16 * 1024 * 1024 + 1)
        if len(content) > 16 * 1024 * 1024:
            raise LoCoMoError("native artifact exceeds 16 MiB")
        payload = _decode(content)
        if not isinstance(payload, dict):
            raise LoCoMoError("native artifact must be a JSON object")
        paths[name], raw[name], parsed[name] = path, content, payload
    expected_hashes = {"candidate": config["reader_policy"]["candidate_manifest_sha256"],
                       "runtime": config["runtime_manifest_sha256"],
                       "resource": config["resource_manifest_sha256"]}
    if any(sha256(raw[name]).hexdigest() != digest for name, digest in expected_hashes.items()):
        raise LoCoMoError("native artifact bytes do not match configuration references")
    candidate = parsed["candidate"]
    validate_candidate_manifest(candidate, expected_git_sha=_current_clean_head(root))
    if _canonical(candidate_reader_policy(candidate)) != _canonical(config["reader_policy"]):
        raise LoCoMoError("native candidate does not match reader policy")
    # This existing verifier compares every installed file with candidate Git
    # content; a forged tree plus a freshly hashed manifest cannot pass.
    grounded_runtime_environment(paths["runtime"], candidate, "http://127.0.0.1:11434", repo_root=root)
    for name, path in paths.items():
        _reject_symlink_components(path)
        with path.open("rb") as handle:
            if handle.read(16 * 1024 * 1024 + 1) != raw[name]:
                raise LoCoMoError("native artifacts changed during verification")
    return {"candidate_manifest_sha256": expected_hashes["candidate"],
            "runtime_manifest_sha256": expected_hashes["runtime"],
            "resource_manifest_sha256": expected_hashes["resource"],
            "runtime_files_verified": True, "resource_artifact_hash_verified": True,
            "resource_preflight_verified": False, "model_execution_verified": False,
            "publication_authorized": False}
