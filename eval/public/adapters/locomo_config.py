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
