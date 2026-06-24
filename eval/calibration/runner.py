"""Calibration runner: drive the REAL engine, measure ECE / reliability / Brier.

Blueprint refs: FR-6 (confidence & abstention) / §16 (ECE ≤ 0.05) / OQ4.

What this does (and does NOT do)
--------------------------------
* Drives the engine ONLY through the public CLI (``mneme capture`` / ``mneme search``
  / ``mneme calibration-tune``) via the existing ``harness.cli_driver.MnemoCLI``
  seam. No ``src/mnemosyne`` internals are imported — this is the same
  rules-of-engagement boundary the §33 harness already enforces.
* Collects the engine's REAL ``confidence`` and REAL ``abstained`` decision for
  every labeled probe, then derives ``correct`` from the engine's REAL retrieved
  hits matched against the dataset's gold substrings (see ``dataset.py`` docstring
  for the truth table). No confidence is fabricated.
* Computes, on that real data:
    - Expected Calibration Error (ECE), reusing ``harness.metrics`` (the §16/FR-6
      ECE primitive) so the number is consistent with the rest of the harness.
    - a reliability-diagram table (per-bin accuracy vs mean confidence + gap).
    - Brier score (mean squared error of confidence vs correctness).
  …overall, per-memory-type, and — crucially — under TWO thresholds:
    (a) the engine's current POLICY default threshold, and
    (b) the engine's current CONFORMAL threshold after the per-type calibration set
        is installed via ``calibration-tune``.
  Reporting both is what exposes "the true gap" the existing thresholds produce.

Codex reconciliation handoff
----------------------------
The runner also emits, per memory type, the exact ``[{confidence, correct}]`` list
that ``calibration-tune`` consumes. Codex tunes the conformal thresholds against
these REAL distributions to drive ECE from today's ~0.20 toward §16's ≤0.05
(docs/CODEX-RECONCILIATION.md FR-6). Re-running this runner after Codex's tuning
re-measures ECE the same way, closing the loop.

Usage
-----
    python eval/calibration/runner.py            # full run, writes report + dataset.json
    python eval/calibration/runner.py --json     # also dump the full report JSON to stdout
    python eval/calibration/runner.py --no-write  # don't touch disk (CI smoke)

Reuse the eval venv:
    /Users/admin/Projects/Mnemosyne-completion/.venv-eval/bin/python eval/calibration/runner.py
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

# --- wire up imports: this file lives in eval/calibration/, the harness in eval/ ---
_HERE = Path(__file__).resolve()
_EVAL_DIR = _HERE.parents[1]          # .../eval
_REPO_ROOT = _HERE.parents[2]         # repo root
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

from harness.cli_driver import MnemoCLI  # noqa: E402  (public-CLI seam, reused)
from harness.metrics import expected_calibration_error  # noqa: E402  (§16 ECE primitive)

# Local dataset (same dir). Support both "run as script" and "import as module".
try:
    from . import dataset as ds  # type: ignore
except ImportError:  # pragma: no cover - script execution path
    sys.path.insert(0, str(_HERE.parent))
    import dataset as ds  # type: ignore


# --------------------------------------------------------------------------- #
# Per-probe observation
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Observation:
    probe_id: str
    memory_type: str
    band: str
    answerable: bool
    # REAL signals from the engine:
    confidence: float
    abstained: bool
    hit_count: int
    gold_present: bool          # gold substring found in a retrieved hit (answerable only)
    # Derived correctness (engine output vs label):
    correct_policy: bool        # correctness under the engine's policy-default decision
    correct_conformal: bool     # correctness under the conformal-threshold decision

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "memory_type": self.memory_type,
            "band": self.band,
            "answerable": self.answerable,
            "confidence": round(self.confidence, 6),
            "abstained": self.abstained,
            "hit_count": self.hit_count,
            "gold_present": self.gold_present,
            "correct_policy": self.correct_policy,
            "correct_conformal": self.correct_conformal,
        }


def _gold_in_hits(result: dict[str, Any], gold_substr: str | None) -> bool:
    """True if the gold substring appears in any retrieved hit's text/summary."""
    if not gold_substr:
        return False
    needle = gold_substr.lower()
    for hit in result.get("hits", []) or []:
        haystack_parts: list[str] = []
        for key in ("text", "snippet", "content", "summary", "object", "title"):
            val = hit.get(key)
            if isinstance(val, str):
                haystack_parts.append(val)
            elif isinstance(val, dict):
                haystack_parts.append(json.dumps(val))
        # Also scan metadata which often carries the object/summary on assertions.
        meta = hit.get("metadata")
        if isinstance(meta, dict):
            haystack_parts.append(json.dumps(meta))
        haystack = " ".join(haystack_parts).lower()
        if needle in haystack:
            return True
    return False


def _correctness(answerable: bool, abstained: bool, gold_present: bool) -> bool:
    """Truth table (see dataset.py).

    answerable & not abstained & gold present -> correct
    answerable & not abstained & gold absent  -> incorrect (confident but wrong)
    answerable & abstained                    -> incorrect (missed an answerable item)
    unanswerable & abstained                  -> correct (good abstain)
    unanswerable & not abstained              -> incorrect (false accept)
    """
    if answerable:
        return (not abstained) and gold_present
    return abstained


def _confidence_for_calibration(answerable: bool, abstained: bool, confidence: float) -> float:
    """Confidence that the calibration target is measured against.

    For an *answerable* probe the engine's reported confidence IS the prediction
    probability for "I can answer this correctly". When the engine abstains, the
    calibrated decision is "I should not answer from these hits", so the comparable
    confidence is the complement of answer-confidence. This keeps the public search
    contract meaningful while ECE/Brier measure the correctness of the actual
    accept-or-abstain decision.
    """
    bounded = max(0.0, min(1.0, confidence))
    return 1.0 - bounded if abstained else bounded


# --------------------------------------------------------------------------- #
# Metric helpers (Brier + reliability table reuse harness ECE)
# --------------------------------------------------------------------------- #
def brier_score(confidences: Sequence[float], correct: Sequence[bool]) -> float:
    if not confidences:
        return float("nan")
    return sum((c - (1.0 if y else 0.0)) ** 2 for c, y in zip(confidences, correct)) / len(confidences)


def reliability_table(confidences: Sequence[float], correct: Sequence[bool], n_bins: int = 10) -> dict[str, Any]:
    res = expected_calibration_error(list(confidences), list(correct), n_bins=n_bins)
    return {
        "ece": res.ece,
        "n": res.n,
        "n_bins": n_bins,
        "brier": brier_score(confidences, correct),
        "bins": res.bins,
    }


# --------------------------------------------------------------------------- #
# Engine drive
# --------------------------------------------------------------------------- #
def _load_corpus(cli: MnemoCLI, tenant: str, user: str) -> int:
    """Capture every memory-type corpus doc through the public CLI. Returns count."""
    loaded = 0
    for s in ds.all_sets():
        for doc in s.corpus:
            cli.capture(
                tenant,
                user,
                doc.content,
                source_type=f"calib-{s.memory_type}",
                actor="user",
                trust_tier=doc.trust_tier,
            )
            loaded += 1
    return loaded


def _install_conformal_sets(cli: MnemoCLI, tenant: str, policy_obs: list[Observation]) -> dict[str, Any]:
    """Install a per-memory-type conformal calibration set from the FIRST (policy) pass.

    We feed ``calibration-tune`` the REAL ``{confidence, correct}`` examples gathered
    under the policy threshold. This is exactly the Codex handoff artifact; here we
    apply it (no --dry-run) so the *second* search pass runs under the conformal
    threshold and we can measure the conformal-side ECE/abstention. ``min-examples``
    is lowered to the per-type probe count so the small calibration set installs.
    """
    summaries: dict[str, Any] = {}
    by_type: dict[str, list[dict[str, Any]]] = {mt: [] for mt in ds.MEMORY_TYPES}
    for obs in policy_obs:
        by_type[obs.memory_type].append(
            {"confidence": obs.confidence, "correct": obs.correct_policy}
        )
    for mt, examples in by_type.items():
        min_ex = max(1, len(examples))
        summary = cli.calibration_tune(
            tenant,
            examples,
            memory_type=mt,
            dry_run=False,          # APPLY so subsequent searches use the conformal threshold
            min_examples=min_ex,
        )
        summaries[mt] = {
            "ok": summary.get("ok"),
            "threshold": summary.get("threshold"),
            "metrics": summary.get("metrics"),
            "failures": summary.get("failures"),
            "examples": examples,   # the exact Codex-tuning handoff list
        }
    return summaries


def _run_probes(cli: MnemoCLI, tenant: str, which: str) -> list[Observation]:
    """Drive every probe through ``mneme search`` and collect REAL signals.

    ``which`` is just a label ("policy" or "conformal") describing which threshold
    regime the engine is in for this pass; the *correctness* attribute set on the
    Observation is named accordingly.
    """
    observations: list[Observation] = []
    for probe in ds.all_probes():
        result = cli.search(tenant, probe.query)
        abstained = bool(result.get("abstained", True))
        confidence = _confidence_for_calibration(
            probe.answerable,
            abstained,
            float(result.get("confidence", 0.0)),
        )
        hits = result.get("hits", []) or []
        gold_present = _gold_in_hits(result, probe.gold_substr) if probe.answerable else False
        correct = _correctness(probe.answerable, abstained, gold_present)
        obs = Observation(
            probe_id=probe.probe_id,
            memory_type=probe.memory_type,
            band=probe.band,
            answerable=probe.answerable,
            confidence=confidence,
            abstained=abstained,
            hit_count=len(hits),
            gold_present=gold_present,
            correct_policy=correct if which == "policy" else False,
            correct_conformal=correct if which == "conformal" else False,
        )
        observations.append(obs)
    return observations


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _abstention_quality(obs: list[Observation]) -> dict[str, Any]:
    """Abstention precision/recall on the unanswerable vs answerable split."""
    ans = [o for o in obs if o.answerable]
    una = [o for o in obs if not o.answerable]
    correct_abstain = sum(1 for o in una if o.abstained)         # good abstains
    wrong_abstain = sum(1 for o in ans if o.abstained)           # missed answerable
    false_accept = sum(1 for o in una if not o.abstained)        # answered the unanswerable
    total_abstain = sum(1 for o in obs if o.abstained)
    abstain_precision = (correct_abstain / total_abstain) if total_abstain else float("nan")
    abstain_recall = (correct_abstain / len(una)) if una else float("nan")
    return {
        "answerable": len(ans),
        "unanswerable": len(una),
        "good_abstains": correct_abstain,
        "missed_answerable_abstains": wrong_abstain,
        "false_accepts": false_accept,
        "abstain_precision": abstain_precision,
        "abstain_recall": abstain_recall,
    }


def _confidence_signal(obs: list[Observation]) -> dict[str, Any]:
    """Diagnose whether the engine's confidence carries discriminative signal.

    A calibration set can only fix ECE if confidence actually *varies* with
    correctness. On ``--backend local`` (no real embedding seam — the documented
    FR-3/G8 gap) the engine returns a near-constant per-hit base confidence, so this
    block exposes the ROOT CAUSE of a flat ECE rather than hiding it behind a single
    number. ``unique_confidences`` near 1 and ``correct_vs_incorrect_gap`` near 0
    means the confidence axis is degenerate and threshold tuning alone cannot reach
    ECE ≤ 0.05 until confidence becomes discriminative (FR-3 dependency).
    """
    confs = [o.confidence for o in obs]
    if not confs:
        return {}
    mean = sum(confs) / len(confs)
    var = sum((c - mean) ** 2 for c in confs) / len(confs)
    # ``policy_obs`` is passed here; correctness lives in ``correct_policy``.
    correct = [o.confidence for o in obs if o.correct_policy]
    incorrect = [o.confidence for o in obs if not o.correct_policy]
    mean_correct = (sum(correct) / len(correct)) if correct else float("nan")
    mean_incorrect = (sum(incorrect) / len(incorrect)) if incorrect else float("nan")
    gap = (mean_correct - mean_incorrect) if (correct and incorrect) else float("nan")
    uniq = sorted({round(c, 4) for c in confs})
    degenerate = len(uniq) <= 2 or (isinstance(var, float) and var < 1e-4)
    return {
        "mean_confidence": mean,
        "variance": var,
        "unique_confidences": uniq,
        "n_unique": len(uniq),
        "mean_confidence_when_correct": mean_correct,
        "mean_confidence_when_incorrect": mean_incorrect,
        "correct_vs_incorrect_gap": gap,
        "degenerate_signal": degenerate,
        "interpretation": (
            "DEGENERATE: confidence is near-constant so it carries no discriminative "
            "signal; threshold tuning alone cannot reach ECE<=0.05 until confidence "
            "becomes discriminative (FR-3 real embedding seam / G8). The labeled set "
            "is still the correct Codex handoff: re-run after the seam lands."
            if degenerate
            else "Confidence varies; conformal threshold tuning over the calibration_examples can reduce ECE."
        ),
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value


def _aggregate(obs: list[Observation], correct_attr: str) -> dict[str, Any]:
    confidences = [o.confidence for o in obs]
    correct = [getattr(o, correct_attr) for o in obs]
    overall = reliability_table(confidences, correct)
    per_type: dict[str, Any] = {}
    for mt in ds.MEMORY_TYPES:
        sub = [o for o in obs if o.memory_type == mt]
        per_type[mt] = {
            **reliability_table([o.confidence for o in sub], [getattr(o, correct_attr) for o in sub]),
            "accuracy": (sum(1 for o in sub if getattr(o, correct_attr)) / len(sub)) if sub else float("nan"),
            "abstention": _abstention_quality(sub),
        }
    return {
        "overall": {
            **overall,
            "accuracy": (sum(1 for c in correct if c) / len(correct)) if correct else float("nan"),
            "abstention": _abstention_quality(obs),
        },
        "per_memory_type": per_type,
    }


def run(*, write: bool = True, dump_json: bool = False) -> dict[str, Any]:
    snapshot = ds.to_dict()
    out_dir = _HERE.parent

    with tempfile.TemporaryDirectory(prefix="mnemo-calib-") as tmp:
        store = str(Path(tmp) / "calibration_store.json")
        cli = MnemoCLI(store=store, backend="local")

        loaded = _load_corpus(cli, ds.TENANT, ds.USER)

        # Pass 1: engine under its CURRENT POLICY default threshold (no calibration set).
        policy_obs = _run_probes(cli, ds.TENANT, which="policy")
        policy_report = _aggregate(policy_obs, "correct_policy")

        # Install per-memory-type conformal calibration sets from the REAL pass-1 data
        # (this is also the exact Codex-tuning handoff list).
        conformal_summaries = _install_conformal_sets(cli, ds.TENANT, policy_obs)

        # Pass 2: SAME probes, now under the installed CONFORMAL thresholds.
        conformal_obs = _run_probes(cli, ds.TENANT, which="conformal")
        conformal_report = _aggregate(conformal_obs, "correct_conformal")

    report: dict[str, Any] = {
        "dataset_id": snapshot["dataset_id"],
        "blueprint_refs": snapshot["blueprint_refs"],
        "tenant": ds.TENANT,
        "corpus_docs_loaded": loaded,
        "totals": snapshot["totals"],
        "thresholds": {
            "policy_default_note": "engine Security/RetrievalPolicy.abstention_threshold (no calibration set installed)",
            "conformal_per_type": {
                mt: conformal_summaries[mt]["threshold"] for mt in ds.MEMORY_TYPES
            },
        },
        # The headline numbers: ECE the EXISTING thresholds produce on REAL data.
        "ece": {
            "policy_threshold": {
                "overall": policy_report["overall"]["ece"],
                "brier": policy_report["overall"]["brier"],
                "per_memory_type": {mt: policy_report["per_memory_type"][mt]["ece"] for mt in ds.MEMORY_TYPES},
                "target": 0.05,
                "meets_target": policy_report["overall"]["ece"] <= 0.05,
            },
            "conformal_threshold": {
                "overall": conformal_report["overall"]["ece"],
                "brier": conformal_report["overall"]["brier"],
                "per_memory_type": {mt: conformal_report["per_memory_type"][mt]["ece"] for mt in ds.MEMORY_TYPES},
                "target": 0.05,
                "meets_target": conformal_report["overall"]["ece"] <= 0.05,
            },
        },
        "reliability_diagram": {
            "policy_threshold": policy_report["overall"]["bins"],
            "conformal_threshold": conformal_report["overall"]["bins"],
        },
        # Root-cause diagnostic: is confidence discriminative at all?
        "confidence_signal": _confidence_signal(policy_obs),
        "policy_report": policy_report,
        "conformal_report": conformal_report,
        # Codex handoff: per-memory-type labeled {confidence, correct} examples,
        # plus the calibration-tune summary each one produced. Codex tunes the
        # conformal thresholds against these to push ECE toward ≤ 0.05.
        "codex_reconciliation": {
            "note": (
                "Feed calibration_examples[mt] to `mneme calibration-tune --memory-type mt`; "
                "tune target_coverage / thresholds to minimise ece.policy_threshold while keeping "
                "false_accept_rate within bound. Re-run this runner to re-measure ECE."
            ),
            "calibration_examples": {
                mt: conformal_summaries[mt]["examples"] for mt in ds.MEMORY_TYPES
            },
            "calibration_tune_summaries": {
                mt: {k: conformal_summaries[mt][k] for k in ("ok", "threshold", "metrics", "failures")}
                for mt in ds.MEMORY_TYPES
            },
        },
        "observations": {
            "policy": [o.to_dict() for o in policy_obs],
            "conformal": [o.to_dict() for o in conformal_obs],
        },
    }

    if write:
        (out_dir / "dataset.json").write_text(json.dumps(_json_ready(snapshot), indent=2) + "\n", encoding="utf-8")
        (out_dir / "report.json").write_text(json.dumps(_json_ready(report), indent=2) + "\n", encoding="utf-8")

    if dump_json:
        print(json.dumps(_json_ready(report), indent=2))
    else:
        _print_summary(report)

    return report


def _fmt(x: Any) -> str:
    if isinstance(x, float):
        return f"{x:.4f}"
    return str(x)


def _print_summary(report: dict[str, Any]) -> None:
    print("=" * 72)
    print("Mnemosyne per-memory-type calibration  (FR-6 / §16 ECE / OQ4)")
    print("=" * 72)
    t = report["totals"]
    print(f"corpus docs loaded : {report['corpus_docs_loaded']}")
    print(f"probes             : {t['probes']}  (answerable {t['answerable']} / unanswerable {t['unanswerable']})")
    print(f"memory types       : {', '.join(ds.MEMORY_TYPES)}")
    print("-" * 72)
    pol = report["ece"]["policy_threshold"]
    con = report["ece"]["conformal_threshold"]
    print("ECE on REAL data (the true gap the existing thresholds produce):")
    print(f"  POLICY  default threshold : ECE={_fmt(pol['overall'])}  Brier={_fmt(pol['brier'])}  "
          f"(target ≤0.05 -> {'MEETS' if pol['meets_target'] else 'FAILS'})")
    print(f"  CONFORMAL (applied set)   : ECE={_fmt(con['overall'])}  Brier={_fmt(con['brier'])}  "
          f"(target ≤0.05 -> {'MEETS' if con['meets_target'] else 'FAILS'})")
    print("-" * 72)
    print("Per-memory-type ECE (policy / conformal) + conformal threshold:")
    for mt in ds.MEMORY_TYPES:
        thr = report["thresholds"]["conformal_per_type"][mt]
        print(f"  {mt:<11} policy={_fmt(pol['per_memory_type'][mt])}  "
              f"conformal={_fmt(con['per_memory_type'][mt])}  thr={_fmt(thr)}")
    print("-" * 72)
    ab = report["policy_report"]["overall"]["abstention"]
    print("Abstention quality (policy pass):")
    print(f"  good_abstains={ab['good_abstains']}  false_accepts={ab['false_accepts']}  "
          f"missed_answerable={ab['missed_answerable_abstains']}")
    print(f"  abstain_precision={_fmt(ab['abstain_precision'])}  abstain_recall={_fmt(ab['abstain_recall'])}")
    print("-" * 72)
    sig = report["confidence_signal"]
    print("Confidence signal (root-cause diagnostic):")
    print(f"  mean={_fmt(sig['mean_confidence'])}  variance={_fmt(sig['variance'])}  "
          f"unique_values={sig['n_unique']}  degenerate={sig['degenerate_signal']}")
    print(f"  mean_conf|correct={_fmt(sig['mean_confidence_when_correct'])}  "
          f"mean_conf|incorrect={_fmt(sig['mean_confidence_when_incorrect'])}  "
          f"gap={_fmt(sig['correct_vs_incorrect_gap'])}")
    print(f"  -> {sig['interpretation']}")
    print("-" * 72)
    print("Reliability diagram (policy threshold) — non-empty bins:")
    print(f"  {'bin':<14}{'count':>7}{'conf':>9}{'acc':>9}{'gap':>9}")
    for b in report["reliability_diagram"]["policy_threshold"]:
        if not b["count"]:
            continue
        rng = f"[{b['lo']:.1f},{b['hi']:.1f}]"
        print(f"  {rng:<14}{b['count']:>7}{_fmt(b['confidence']):>9}{_fmt(b['accuracy']):>9}{_fmt(b['gap']):>9}")
    print("=" * 72)
    print("Codex handoff: report.json -> codex_reconciliation.calibration_examples[mt]")
    print("Tune conformal thresholds against those REAL {confidence,correct} lists to push ECE ≤ 0.05.")
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mnemosyne per-memory-type calibration runner (FR-6 / §16 ECE).")
    parser.add_argument("--json", action="store_true", dest="dump_json", help="dump full report JSON to stdout")
    parser.add_argument("--no-write", action="store_true", help="do not write dataset.json / report.json")
    args = parser.parse_args(argv)
    run(write=not args.no_write, dump_json=args.dump_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
