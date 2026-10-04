"""Benchmark-owned replay of public claim-derivation/v1 receipts.

Operands must already be checked against the retained evidence spans. This
module uses only the standard library, never the system-under-test synthesizer.
"""
from datetime import date
from fractions import Fraction
import re


class DerivationError(ValueError):
    """A declared derivation does not reproduce its claim."""


def verify_claim_derivation(claim: dict, quotes: list[str]) -> str:
    if "derivation" not in claim:
        return "exact-quoted-spans" if claim["text"] == " ".join(quotes) else "derived-text-unverified"
    receipt = claim["derivation"]
    if (not isinstance(receipt, dict) or set(receipt) != {"schema_version", "kind", "operation"}
            or receipt["schema_version"] != "mnemosyne.claim-derivation/v1"):
        raise DerivationError("invalid derivation receipt")
    if receipt["kind"] == "quotation":
        if receipt["operation"] is not None or not 1 <= len(quotes) <= 3 or claim["text"] != " ".join(quotes):
            raise DerivationError("quotation derivation mismatch")
        return "exact-quoted-spans"
    if receipt["kind"] != "synthesis":
        raise DerivationError("unknown derivation kind")
    operands = [(span["cid"], quote) for span, quote in zip(claim["spans"], quotes, strict=True)]
    if (not 1 <= len(operands) <= 16 or len(set(operands)) != len(operands)
            or any(len(cid) > 256 or not 1 <= len(quote) <= 128 for cid, quote in operands)):
        raise DerivationError("invalid synthesis operands")
    operation = receipt["operation"]
    try:
        expected = _evaluate(operation, quotes)
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
        raise DerivationError("invalid synthesis operation or operands") from exc
    if claim["text"] != expected:
        raise DerivationError("synthesis derivation mismatch")
    return "replayed-deterministic-synthesis"


def _evaluate(operation, quotes):
    if operation == "compose_date":
        if (len(quotes) != 3 or re.fullmatch(r"[0-9]{4}", quotes[0]) is None
                or re.fullmatch(r"[0-9]{2}", quotes[2]) is None):
            raise ValueError("date operand shape")
        months = "january february march april may june july august september october november december".split()
        month = (int(quotes[1]) if re.fullmatch(r"[0-9]{2}", quotes[1]) else
                 months.index(quotes[1].lower()) + 1)
        return date(int(quotes[0]), month, int(quotes[2])).isoformat()
    if operation not in ("add", "subtract", "multiply", "divide"):
        raise ValueError("operation")
    for quote in quotes:
        if (re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", quote) is None
                or len(quote.lstrip("-").replace(".", "")) > 64
                or ("." in quote and len(quote.split(".")[1]) > 18)):
            raise ValueError("decimal operand shape")
    values = [Fraction(quote) for quote in quotes]
    result = values[0]
    for value in values[1:]:
        if operation == "add":
            result += value
        elif operation == "subtract":
            result -= value
        elif operation == "multiply":
            result *= value
        else:
            result /= value
    # A terminating decimal with at most 18 places divides this fixed grid.
    grid = 10**18
    if grid % result.denominator:
        raise ValueError("nonterminating or over-scale result")
    scaled = str(abs(result.numerator) * (grid // result.denominator)).zfill(19)
    integer, fraction = scaled[:-18], scaled[-18:].rstrip("0")
    if len(integer) + len(fraction) > 64:
        raise ValueError("oversize result")
    return ("-" if result < 0 else "") + integer + ("." + fraction if fraction else "")
