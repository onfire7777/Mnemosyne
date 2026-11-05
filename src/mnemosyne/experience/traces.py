"""Eligibility decays without reinforcing an item on exposure."""

import math


def trace(
    share: float, turns_ago: int, minutes_ago: float, lam: float = 0.7, tau: float = 30
) -> float:
    if not all(math.isfinite(v) for v in (share, turns_ago, minutes_ago, lam, tau)):
        raise ValueError("trace parameters must be finite")
    if min(share, turns_ago, minutes_ago) < 0 or not 0 <= lam <= 1 or tau <= 0:
        raise ValueError("invalid trace parameters")
    return share * lam**turns_ago * math.exp(-minutes_ago / tau)


def plastic_rate(eta0: float, n: float, kappa: float, volatility: float) -> float:
    if kappa <= 0 or min(n, volatility) < 0:
        raise ValueError("invalid learning-rate parameters")
    return max(0.01, min(0.5, eta0 * (1 + volatility) / (1 + n / kappa)))


def stiff_step(
    step: float,
    importance: float,
    omega0: float = 10,
    *,
    verified_failure: bool = False,
) -> float:
    if verified_failure:
        return step
    return step * max(0.05, 1 / (1 + importance / omega0))
