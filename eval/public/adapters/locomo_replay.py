"""Offline native replay across the project's separate pinned scorer environment.

The caller selects an existing trusted Python executable; this module installs
nothing and does not execute a model. It does not establish signed run custody.
"""
from hashlib import sha256
import json
import math
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryFile

from .locomo import LoCoMoError

MAX_BYTES = 64 * 1024 * 1024
_FIELDS = {"samples", "records", "caption_policy", "choice_draws", "reader_policy", "choice_seed"}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LoCoMoError("duplicate replay JSON key")
        result[key] = value
    return result


def _decode(raw):
    def invalid_constant(value):
        raise LoCoMoError("non-finite replay JSON")
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise LoCoMoError("non-finite replay JSON")
        return result
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid_constant,
                          parse_float=finite_float)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise LoCoMoError("invalid replay JSON") from exc


def _encode(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise LoCoMoError("replay requires finite JSON") from exc
    if len(raw) > MAX_BYTES:
        raise LoCoMoError("replay exceeds 64 MiB transport bound")
    return raw


def replay_in_environment(samples, records, *, caption_policy, choice_draws=None,
                          python: str | Path, timeout_s: float = 120, reader_policy: dict | None = None, choice_seed: int | None = None) -> dict:
    """Return verified scoring output using an explicitly selected interpreter."""
    if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise LoCoMoError("replay timeout must be finite and positive")
    executable = Path(python).absolute()
    if not executable.is_file():
        raise LoCoMoError("scorer Python executable is missing")
    request = _encode(dict(samples=samples, records=records, caption_policy=caption_policy,
                           choice_draws=choice_draws, reader_policy=reader_policy, choice_seed=choice_seed))
    root = Path(__file__).resolve().parents[3]
    # -I ignores ambient PYTHONPATH/user packages; keep the selected venv intact.
    bootstrap = (f"import sys,runpy;sys.path[:0]={[str(root), str(root / 'src')]!r};"
                 "runpy.run_module('eval.public.adapters.locomo_replay',run_name='__main__')")
    with TemporaryFile() as output, TemporaryFile() as errors:
        try:
            completed = subprocess.run([str(executable), "-I", "-c", bootstrap], input=request,
                                       stdout=output, stderr=errors, timeout=timeout_s, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LoCoMoError("isolated replay failed or timed out") from exc
        if completed.returncode:
            raise LoCoMoError("isolated scorer rejected replay or its pinned environment")
        output.seek(0)
        raw = output.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise LoCoMoError("replay exceeds 64 MiB transport bound")
    envelope = _decode(raw)
    if (not isinstance(envelope, dict) or set(envelope) != {"request_sha256", "report"}
            or envelope["request_sha256"] != sha256(request).hexdigest()
            or not isinstance(envelope["report"], dict)):
        raise LoCoMoError("isolated replay response does not bind the request")
    return envelope["report"]


def _main():
    from .locomo_scoring import _runtime, replay_native_population
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise LoCoMoError("replay exceeds 64 MiB transport bound")
    request = _decode(raw)
    if not isinstance(request, dict) or set(request) != _FIELDS:
        raise LoCoMoError("replay request has an invalid shape")
    _runtime()  # Check all dependency pins even for an entirely missing run.
    report = replay_native_population(**request)
    sys.stdout.buffer.write(_encode({"request_sha256": sha256(raw).hexdigest(), "report": report}))


def verify_report_in_environment(report, samples, records, *, caption_policy, choice_draws=None,
                                 python: str | Path, timeout_s: float = 120, reader_policy: dict | None = None, choice_seed: int | None = None) -> dict:
    """Verify every saved report field against source, records and current policy.

    Changed replay source must be verified in its original checkout rather
    than silently treated as the same protocol. Success is local consistency,
    not proof of model execution or authorization to publish.
    """
    expected = replay_in_environment(samples, records, caption_policy=caption_policy,
                                     choice_draws=choice_draws, python=python, timeout_s=timeout_s, reader_policy=reader_policy, choice_seed=choice_seed)
    if _encode(report) != _encode(expected):
        raise LoCoMoError("saved native report does not match source-bound replay")
    return expected


if __name__ == "__main__":
    _main()
