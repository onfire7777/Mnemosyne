#!/usr/bin/env python3
"""FR-17 cold-loop replay-fidelity check (OQ2 gate). Exits non-zero below bar.

This is the runnable promotion gate. It does three things and emits a JSON+MD
evidence artifact:

  1. **Golden guarantee** — scores every case in ``corpus.GOLDEN_CASES`` and
     asserts the OQ2 bar accepts the faithful corpus and rejects every degenerate
     pathology (all-tie, sign-flipped, tiny-window, noise, biased-gap). If any
     golden expectation is violated, the gate itself is broken -> non-zero exit.

  2. **Current-src measurement (the honest forcing function)** — measures the
     CURRENT system. Today ``counterfactual_replay_score`` is computed (in
     ``mcp_tools.outcome_evaluate``) but is **not consumed by any promotion
     decision**: ``gate.PromotionGate.evaluate`` decides ``promoted`` purely on
     regression-case margin, and ``ShadowPolicyOptimizer.evaluate_variant``
     restores ``OperatingPolicy()`` in a ``finally`` so it never mutates
     production. So there is no wired cf->gate path to validate against real
     observed lift, and **no paired (predicted, observed) corpus exists in src**.
     The honest verdict is therefore: the replay proxy is **NOT yet authorized to
     gate** -> the loop is correctly kept in SHADOW (veto-only). The check proves
     this is the right state by showing the proxy would have to clear the OQ2 bar
     on real paired data first, and that bar is unmet because the data does not
     exist yet (window = 0).

  3. **Bar verdict** — exits 0 only when the golden guarantee holds AND the
      current-src state is safe: replay is wired into promotion, but unproven
      replay fidelity fails closed. It exits non-zero if the golden guarantee
      breaks, or if ``--require-wired`` is set before real replay pairs clear the
      OQ2 bar.

Run:
    python eval/replay_fidelity/replay_fidelity_check.py
    python eval/replay_fidelity/replay_fidelity_check.py --json-out eval/reports/...
    python eval/replay_fidelity/replay_fidelity_check.py --require-wired   # CI flip

Exit codes:
    0  golden guarantee holds and current-src state is correct (shadow/veto-only)
    1  golden guarantee violated (the OQ2 gate is itself broken)
    2  --require-wired set but the cf->gate path is not wired / not above bar
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import corpus  # noqa: E402
import scorer  # noqa: E402
from src_probe import probe_current_src  # noqa: E402


@dataclass(slots=True)
class GoldenResult:
    name: str
    expected_pass: bool
    actual_pass: bool
    score: dict

    @property
    def ok(self) -> bool:
        return self.expected_pass == self.actual_pass


def run_golden(bar: scorer.FidelityBar) -> list[GoldenResult]:
    results: list[GoldenResult] = []
    for name, (_builder, must_pass) in corpus.GOLDEN_CASES.items():
        pairs = corpus.build_case(name)
        # Exercise the real shapes end to end: pairs -> SelfModelStore -> pairs.
        store = corpus.pairs_to_store(pairs)
        recovered = corpus.pairs_from_store(store)
        pred = [p.proxy for p in recovered]
        obs = [p.truth for p in recovered]
        s = scorer.score_fidelity(pred, obs, bar=bar)
        results.append(
            GoldenResult(
                name=name,
                expected_pass=must_pass,
                actual_pass=s.passed,
                score=s.to_dict(),
            )
        )
    return results


def build_report(
    golden: list[GoldenResult],
    src_state: dict,
    bar: scorer.FidelityBar,
    require_wired: bool,
) -> dict:
    golden_ok = all(g.ok for g in golden)
    cf_wired = bool(src_state["cf_wired_into_gate"])
    # Current-src verdict: the proxy is authorized to gate only if it is wired AND
    # clears the OQ2 bar on real paired data.
    current_score = src_state.get("fidelity_score")
    proxy_authorized = cf_wired and bool(current_score and current_score.get("passed"))
    loop_correctly_shadow = bool(src_state.get("default_replay_fails_closed")) and not proxy_authorized

    if require_wired:
        # CI-flip mode: the cf->gate path is asserted to be live and above bar.
        passed = golden_ok and proxy_authorized
        exit_code = 0 if passed else 2
    else:
        # Default mode: pass iff the gate is internally sound, replay is wired,
        # and unproven replay fidelity blocks active promotion.
        passed = golden_ok and cf_wired and loop_correctly_shadow
        exit_code = 0 if passed else 1

    return {
        "meta": {
            "gate": "FR-17 cold-loop replay-fidelity (OQ2)",
            "blueprint_refs": ["OQ2", "FR-17 cold-loop gate", "§23.3", "§30.6"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "require-wired" if require_wired else "default",
            "bar": bar.to_dict(),
        },
        "golden": {
            "all_ok": golden_ok,
            "cases": [
                {
                    "name": g.name,
                    "expected": "pass" if g.expected_pass else "reject",
                    "actual": "pass" if g.actual_pass else "reject",
                    "ok": g.ok,
                    "n": g.score["n"],
                    "rho": g.score["rho"],
                    "rho_ci_low": g.score["rho_ci"]["ci_low"],
                    "sign_agreement": g.score["sign_agreement"],
                    "proxy_true_gap": g.score["proxy_true_gap"],
                    "decision_coverage": g.score["decision_coverage"],
                    "vetoed_by": [c["name"] for c in g.score["checks"] if not c["pass"]],
                }
                for g in golden
            ],
        },
        "current_src": src_state,
        "verdict": {
            "golden_ok": golden_ok,
            "cf_wired_into_gate": cf_wired,
            "proxy_authorized_to_gate": proxy_authorized,
            "loop_correctly_shadow_veto_only": loop_correctly_shadow,
            "passed": passed,
            "exit_code": exit_code,
        },
    }


def render_markdown(report: dict) -> str:
    v = report["verdict"]
    meta = report["meta"]
    lines: list[str] = []
    lines.append("# FR-17 Cold-Loop Replay-Fidelity Check (OQ2)")
    lines.append("")
    lines.append(f"- **Generated:** {meta['generated_at']}")
    lines.append(f"- **Mode:** `{meta['mode']}`")
    lines.append(f"- **Blueprint refs:** {', '.join(meta['blueprint_refs'])}")
    bar = meta["bar"]
    lines.append(
        f"- **OQ2 bar:** rho>={bar['min_rho']} & CI-lower>{bar['min_rho_ci_lower']}, "
        f"sign>={bar['min_sign_agreement']}, gap<={bar['max_proxy_true_gap']}, "
        f"window>={bar['min_window']}, coverage>={bar['min_decision_coverage']}"
    )
    lines.append("")
    verdict_label = "PASS (exit 0)" if v["passed"] else f"FAIL (exit {v['exit_code']})"
    lines.append(f"## Verdict: {verdict_label}")
    lines.append("")
    lines.append(f"- golden guarantee holds: **{v['golden_ok']}**")
    lines.append(f"- cf term wired into gate: **{v['cf_wired_into_gate']}**")
    lines.append(f"- proxy authorized to gate: **{v['proxy_authorized_to_gate']}**")
    lines.append(f"- loop correctly SHADOW (veto-only): **{v['loop_correctly_shadow_veto_only']}**")
    lines.append("")
    lines.append("## Golden corpus (faithful MUST pass; degenerates MUST be rejected)")
    lines.append("")
    lines.append("| Case | Expected | Actual | OK | n | rho | CI-low | sign | gap | cov | vetoed by |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for c in report["golden"]["cases"]:
        mark = "OK" if c["ok"] else "**WRONG**"
        veto = ", ".join(c["vetoed_by"]) or "—"
        lines.append(
            f"| {c['name']} | {c['expected']} | {c['actual']} | {mark} | {c['n']} | "
            f"{c['rho']} | {c['rho_ci_low']} | {c['sign_agreement']} | "
            f"{c['proxy_true_gap']} | {c['decision_coverage']} | {veto} |"
        )
    lines.append("")
    lines.append("## Current-src honest status")
    lines.append("")
    src = report["current_src"]
    lines.append(src["narrative"])
    lines.append("")
    if src.get("required_wiring"):
        lines.append("### Required src wiring to authorize the proxy as a gate")
        lines.append("")
        for item in src["required_wiring"]:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FR-17 OQ2 replay-fidelity check")
    parser.add_argument(
        "--require-wired",
        action="store_true",
        help="CI-flip: require the cf->gate path to be live and above the OQ2 bar.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=_HERE.parent / "reports" / "replay_fidelity_latest.json",
        help="Where to write the JSON evidence artifact.",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=_HERE.parent / "reports" / "replay_fidelity_latest.md",
        help="Where to write the Markdown report.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    bar = scorer.FidelityBar()
    golden = run_golden(bar)
    src_state = probe_current_src(bar)
    report = build_report(golden, src_state, bar, require_wired=args.require_wired)

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, default=str))
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    md = render_markdown(report)
    args.md_out.write_text(md)

    if not args.quiet:
        print(md)
        print(f"\n[evidence] {args.json_out}\n[evidence] {args.md_out}")

    return report["verdict"]["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
