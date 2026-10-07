"""The zero-skipping PPR for closed graphs is bit-identical to the pure oracle."""

from __future__ import annotations

import random
from collections import defaultdict

import pytest

from mnemosyne.algorithms import _ppr_power_iteration_closed, _ppr_power_iteration_pure


def _graph(seed: int) -> tuple[dict[str, set[str] | list[str]], set[str]]:
    rng = random.Random(seed)
    names = [f"n{i}" for i in range(rng.randint(1, 60))]
    adjacency: dict[str, set[str] | list[str]] = defaultdict(set)
    for _ in range(rng.randint(0, 120)):
        a, b = rng.choice(names), rng.choice(names)
        adjacency[a].add(b)  # type: ignore[union-attr]
        adjacency[b].add(a)  # type: ignore[union-attr]
    seeds = set(rng.sample(names, rng.randint(0, min(5, len(names)))))
    for name in seeds:
        adjacency.setdefault(name, [])  # seeds without edges, as graph_ppr adds them
    return dict(adjacency), seeds


@pytest.mark.parametrize("seed", range(200))
def test_closed_ppr_equals_the_pure_loop_bit_for_bit(seed: int) -> None:
    adjacency, seeds = _graph(seed)
    iterations = [12, 1, 0, 3, 30][seed % 5]
    matches = seeds.__contains__
    pure = _ppr_power_iteration_pure(adjacency, matches, iterations=iterations, damping=0.85, teleport=0.15)
    fast = _ppr_power_iteration_closed(adjacency, matches, iterations=iterations, damping=0.85, teleport=0.15)
    assert list(fast.items()) == list(pure.items())  # same keys, same order, same floats
    assert [value.hex() for value in fast.values()] == [value.hex() for value in pure.values()]
