import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
PBPP = "docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md"
POLICY_FILES = (
    ROOT / "docs/blueprint/Mnemosyne-Performance-and-Refactoring-Blueprint.md",
    ROOT / "eval/provider_bakeoff/README.md",
)


def test_public_benchmark_policy_points_contributors_to_pbpp() -> None:
    for path in POLICY_FILES:
        policy = path.read_text(encoding="utf-8")
        assert re.search(r"Public-Benchmark\s+Publication Protocol \(PBPP\)", policy), (
            f"{path} must name PBPP"
        )
        assert PBPP in policy, f"{path} must point contributors to {PBPP} §2"
        for requirement in (
            "pinned",
            "artifact bundle",
            "retrieval-recall",
            "LLM-judged",
            "independent",
        ):
            assert requirement in policy, f"{path} omits PBPP requirement: {requirement}"


def test_public_benchmark_policy_does_not_retain_blanket_prohibition() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in POLICY_FILES)
    assert "Public benchmark sets remain internal sanity checks only" not in combined
    assert "public claims remain measured-latency/SLO numbers only" not in combined
