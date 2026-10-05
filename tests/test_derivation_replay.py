"""Independent public derivation replay; synthetic operands and no model calls."""
from hashlib import sha256
import random

import pytest

from eval.public.derivation import DerivationError, verify_claim_derivation
from eval.public.adapters.locomo import LoCoMoError
from eval.public.adapters.locomo_native import project_native_response


def claim(operation, quotes, answer):
    return {"text": answer, "evidence_cids": [f"cid-{i}" for i in range(len(quotes))],
            "spans": [{"cid": f"cid-{i}", "start": 0, "end": len(quote),
                       "slice_sha256": sha256(quote.encode()).hexdigest()} for i, quote in enumerate(quotes)],
            "derivation": {"schema_version": "mnemosyne.claim-derivation/v1", "kind": "synthesis", "operation": operation}}


@pytest.mark.parametrize("operation,quotes,answer", [
    ("add", ["1.20", "2.80"], "4"),
    ("add", ["-0.00"], "0"),
    ("subtract", ["1", "2.5", "3"], "-4.5"),
    ("multiply", ["-2.5", "4"], "-10"),
    ("divide", ["1", "8"], "0.125"),
    ("divide", ["20", "2", "5"], "2"),
    ("add", ["9" * 64], "9" * 64),
    ("add", ["0.000000000000000001"], "0.000000000000000001"),
    ("compose_date", ["2024", "February", "29"], "2024-02-29"),
    ("compose_date", ["2024", "02", "29"], "2024-02-29"),
])
def test_native_derivation_replay(operation, quotes, answer):
    row = claim(operation, quotes, answer)
    evidence = {f"cid-{i}": {"dialog_id": f"D1:{i}", "capture": {"content": quote}}
                for i, quote in enumerate(quotes)}
    response = {"answer": answer, "abstained": False, "claims": [row],
                "hops": [{"retrieved_cids": list(evidence)}],
                "reader": {"grounded_reader": {"provider": "synthetic"}}}
    annotation = {"question": "Synthetic?", "answer": answer, "category": 4}
    result = project_native_response(response, annotation, evidence)
    assert result["decoded_prediction"] == answer
    assert result["claim_text_custody"] == ["replayed-deterministic-synthesis"]
    row["text"] = response["answer"] = answer + " altered"
    with pytest.raises(LoCoMoError, match="derivation"):
        project_native_response(response, annotation, evidence)


@pytest.mark.parametrize("operation,quotes", [
    ("sum", ["1", "2"]), ("divide", ["1", "0"]), ("divide", ["1", "3"]),
    ("divide", ["1", "1048576"]), ("add", ["01"]), ("add", ["1e3"]),
    ("add", ["1 + 2"]), ("add", ["NaN"]), ("add", ["0." + "1" * 19]),
    ("add", ["9" * 65]), ("multiply", ["9" * 40, "9" * 40]),
    ("compose_date", ["2023", "February", "29"]),
    ("compose_date", ["2024", "2", "29"]),
])
def test_derivation_rejects_invalid_or_unbounded_operations(operation, quotes):
    with pytest.raises(DerivationError):
        verify_claim_derivation(claim(operation, quotes, "irrelevant"), quotes)


def test_random_arithmetic_matches_product_contract():
    from pathlib import Path
    from runpy import run_path
    # This standalone provider has no runtime dependencies. Avoid importing the
    # providers package initializer into the deliberately minimal scorer venv.
    namespace = run_path(str(Path(__file__).parents[1] / "src/mnemosyne/providers/deterministic_synthesis.py"))
    DeterministicSynthesizer = namespace["DeterministicSynthesizer"]
    DeterministicSynthesisError = namespace["DeterministicSynthesisError"]
    rng = random.Random(7104)
    product = DeterministicSynthesizer()
    for operation in ("add", "subtract", "multiply", "divide"):
        for _ in range(50):
            quotes = [str(rng.randint(-1000, 1000) / 100) for _ in range(3)]
            payload = {"operation": operation, "spans": [{"cid": f"cid-{i}", "quote": q}
                                                        for i, q in enumerate(quotes)]}
            try:
                answer = product.synthesize(payload)["answer"]
            except DeterministicSynthesisError:
                with pytest.raises(DerivationError):
                    verify_claim_derivation(claim(operation, quotes, "irrelevant"), quotes)
            else:
                assert verify_claim_derivation(claim(operation, quotes, answer), quotes) == "replayed-deterministic-synthesis"


def test_derivation_receipt_shape_and_version_are_closed():
    for change in ({"schema_version": "unknown"}, {"kind": "unknown"}, {"extra": True},
                   {"kind": "quotation", "operation": "add"}):
        row = claim("add", ["1", "2"], "3")
        row["derivation"].update(change)
        with pytest.raises(DerivationError):
            verify_claim_derivation(row, ["1", "2"])
