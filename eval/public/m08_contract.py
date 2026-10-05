"""Module-local M08 message validation; not a reversible-delete implementation."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA = Path(__file__).with_name("schema") / "wmbs-m08-operation-v0.1.schema.json"


def validate_message(message: dict) -> None:
    """Validate a closed message and restoration authority references."""
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(message))
    if errors:
        raise ValueError("invalid M08 operation message")
    if message["kind"] == "restore-request":
        deleted = message["delete_receipt"]
        if (message["operation_id"] == deleted["operation_id"]
                or any(message[key] != deleted[key] for key in
                       ("adapter_id", "adapter_version", "selector"))):
            raise ValueError("M08 restoration scope or operation identity mismatch")


def validate_receipt(request: dict, receipt: dict) -> None:
    """Bind an operation report to its request, without treating it as proof.

    This checks references, not signatures, operator authority or actual effects.
    An adapter must enforce access controls; the harness must run outcome probes.
    """
    request, receipt = deepcopy(request), deepcopy(receipt)
    validate_message(request)
    validate_message(receipt)
    if request["kind"] not in {"delete-request", "restore-request"}:
        raise ValueError("M08 receipt binding requires an operation request")
    if receipt["kind"] != request["kind"].replace("-request", "-receipt"):
        raise ValueError("M08 receipt operation type mismatch")
    if any(request[key] != receipt[key] for key in
           ("operation_id", "adapter_id", "adapter_version", "selector")):
        raise ValueError("M08 receipt does not match request identity and scope")
    if (request["kind"] == "restore-request"
            and receipt["delete_operation_id"] != request["delete_receipt"]["operation_id"]):
        raise ValueError("M08 receipt references a different deletion")


def validate_operation_sequence(exchanges: list[dict]) -> None:
    """Check ordered operation custody without inferring successful forgetting.

    Missing terminal receipts remain invalid here; a runner must record a failed
    or aborted receipt rather than erase an attempted operation from its ledger.
    """
    if not isinstance(exchanges, list) or len(exchanges) > 10_000:
        raise ValueError("M08 operation sequence must be a bounded list")
    exchanges = deepcopy(exchanges)
    receipts = {}
    for exchange in exchanges:
        if not isinstance(exchange, dict) or set(exchange) != {"request", "receipt"}:
            raise ValueError("M08 exchange requires request and terminal receipt")
        request, receipt = exchange["request"], exchange["receipt"]
        validate_receipt(request, receipt)
        operation_id = request["operation_id"]
        if operation_id in receipts:
            raise ValueError("M08 operation identity is duplicated")
        if request["kind"] == "restore-request":
            deleted = request["delete_receipt"]
            prior = receipts.get(deleted["operation_id"])
            if prior is None or prior != deleted:
                raise ValueError("M08 restoration requires its exact preceding delete receipt")
        receipts[operation_id] = receipt
