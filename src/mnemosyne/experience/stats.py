"""Tested-outcome posteriors and conservative causal contrasts."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass

from types import SimpleNamespace


def wilson_interval(successes: float, total: float):
    if total <= 0:
        return SimpleNamespace(low=0.0, high=1.0)
    p, z = successes / total, 1.96
    d = 1 + z * z / total
    center = (p + z * z / (2 * total)) / d
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / d
    return SimpleNamespace(
        low=max(0.0, center - margin), high=min(1.0, center + margin)
    )


@dataclass
class Posterior:
    alpha: float = 1.0
    beta: float = 1.0
    n: float = 0.0

    def update(self, probability: float, weight: float = 1.0) -> None:
        if (
            not all(math.isfinite(v) for v in (probability, weight))
            or not 0 <= probability <= 1
            or weight < 0
        ):
            raise ValueError(
                "posterior updates require a probability and nonnegative finite weight"
            )
        self.alpha += probability * weight
        self.beta += (1 - probability) * weight
        self.n += weight

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        total = self.alpha + self.beta
        return self.alpha * self.beta / (total * total * (total + 1))

    @property
    def lower_bound(self) -> float:
        return wilson_interval(self.alpha - 1, self.n).low if self.n else 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict | None) -> Posterior:
        value = value or {}
        return cls(
            **{key: value[key] for key in ("alpha", "beta", "n") if key in value}
        )


def prob_better(
    candidate: Posterior, incumbent: Posterior, samples: int = 2048
) -> float:
    rng = random.Random(0)
    return (
        sum(
            rng.betavariate(candidate.alpha, candidate.beta)
            > rng.betavariate(incumbent.alpha, incumbent.beta)
            for _ in range(samples)
        )
        / samples
    )


def contingency_lower_bound(
    served_successes: float,
    served_n: int,
    control_successes: float,
    control_n: int,
    minimum: int = 8,
) -> float | None:
    if min(served_n, control_n) < minimum:
        return None
    return (
        wilson_interval(served_successes, served_n).low
        - wilson_interval(control_successes, control_n).high
    )
