"""FR-17 cold-loop replay-fidelity backtest harness (OQ2 gate).

Modules:
  * scorer.py                — OQ2 scorer: Spearman rho + bootstrap CI (n=1000),
                               sign-agreement, proxy-true gap, decision-coverage,
                               and the FidelityBar verdict.
  * corpus.py                — golden corpus built on the REAL cf arithmetic and
                               the REAL SelfModelStore/PolicyOutcome shapes; the
                               faithful corpus must pass and the degenerate cases
                               (all-tie, sign-flipped, tiny-window, noise,
                               biased-gap) must be rejected.
  * src_probe.py             — honest probe of current src (cf term not wired ->
                               loop correctly in shadow / veto-only).
  * replay_fidelity_check.py — runnable gate; exits non-zero when below bar.
"""
