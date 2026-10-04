"""Contract checks do not establish any system's reversible-delete support."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from eval.public.m08_contract import _SCHEMA, validate_message, validate_receipt


def messages():
    request = {"schema_version": "wmbs-m08-operation/v0.1", "kind": "delete-request",
               "operation_id": "delete-1", "adapter_id": "synthetic", "adapter_version": "1",
               "selector": {"tenant_id": "a", "branch_id": "main", "source_handles": ["source-1"]},
               "mode": "reversible"}
    receipt = {**deepcopy(request), "kind": "delete-receipt", "outcome": "completed", "reason": None}
    return request, receipt


def test_closed_schema_and_complete_delete_restore_exchange():
    Draft202012Validator.check_schema(json.loads(_SCHEMA.read_text(encoding="utf-8")))
    request, receipt = messages()
    validate_receipt(request, receipt)
    restore = {key: deepcopy(value) for key, value in request.items() if key != "mode"}
    restore.update(kind="restore-request", operation_id="restore-1", delete_receipt=receipt)
    restored = {key: deepcopy(value) for key, value in restore.items() if key != "delete_receipt"}
    restored.update(kind="restore-receipt", delete_operation_id="delete-1", outcome="completed", reason=None)
    validate_receipt(restore, restored)
    for outcome in ("failed", "aborted", "unsupported"):
        validate_receipt(request, {**receipt, "outcome": outcome, "reason": "synthetic reason"})


@pytest.mark.parametrize("fault", ["tenant", "branch", "handles", "adapter", "version", "operation", "mode", "extra", "duplicate", "empty", "reason"])
def test_rejects_widened_mismatched_or_ambiguous_delete_receipts(fault):
    request, receipt = messages()
    if fault in {"tenant", "branch", "handles"}:
        field = {"tenant": "tenant_id", "branch": "branch_id", "handles": "source_handles"}[fault]
        receipt["selector"][field] = ["foreign"] if fault == "handles" else "foreign"
    elif fault in {"adapter", "version", "operation"}:
        receipt[{"adapter": "adapter_id", "version": "adapter_version", "operation": "operation_id"}[fault]] = "foreign"
    elif fault == "mode":
        receipt["mode"] = "hard_delete_legal"
    elif fault == "extra":
        receipt["publication_authorized"] = True
    elif fault == "duplicate":
        receipt["selector"]["source_handles"] *= 2
    elif fault == "empty":
        receipt["selector"]["source_handles"] = []
    else:
        receipt.update(outcome="failed", reason=None)
    with pytest.raises(ValueError):
        validate_receipt(request, receipt)


@pytest.mark.parametrize("fault", ["failed", "unsupported", "aborted", "tenant", "reuse"])
def test_restore_requires_completed_deletion_and_same_scope(fault):
    request, receipt = messages()
    restore = {key: deepcopy(value) for key, value in request.items() if key != "mode"}
    restore.update(kind="restore-request", operation_id="restore-1", delete_receipt=receipt)
    if fault in {"failed", "unsupported", "aborted"}:
        receipt.update(outcome=fault, reason="synthetic reason")
    elif fault == "tenant":
        restore["selector"]["tenant_id"] = "foreign"
    else:
        restore["operation_id"] = "delete-1"
    with pytest.raises(ValueError):
        validate_message(restore)


def operation_sequence():
    request, receipt = messages()
    restore = {key: deepcopy(value) for key, value in request.items() if key != "mode"}
    restore.update(kind="restore-request", operation_id="restore-1", delete_receipt=deepcopy(receipt))
    restored = {key: deepcopy(value) for key, value in restore.items() if key != "delete_receipt"}
    restored.update(kind="restore-receipt", delete_operation_id="delete-1", outcome="completed", reason=None)
    return [{"request": request, "receipt": receipt}, {"request": restore, "receipt": restored}]


def test_operation_sequence_binds_restore_to_actual_prior_receipt():
    from eval.public.m08_contract import validate_operation_sequence
    sequence = operation_sequence()
    validate_operation_sequence(sequence)
    assert sequence == operation_sequence()
    sequence[1]["receipt"].update(outcome="failed", reason="synthetic restore failure")
    validate_operation_sequence(sequence)


@pytest.mark.parametrize("fault", ["future", "omitted", "duplicate", "altered", "failed_delete", "unterminated", "extra"])
def test_operation_sequence_rejects_fabricated_history(fault):
    from eval.public.m08_contract import validate_operation_sequence
    sequence = operation_sequence()
    if fault == "future":
        sequence.reverse()
    elif fault == "omitted":
        sequence.pop(0)
    elif fault == "duplicate":
        sequence.append(deepcopy(sequence[0]))
    elif fault == "altered":
        # Both messages are internally consistent; the embedded delete is not
        # the receipt actually observed in the preceding exchange.
        for message in (sequence[1]["request"], sequence[1]["receipt"], sequence[1]["request"]["delete_receipt"]):
            message["selector"]["branch_id"] = "other"
    elif fault == "failed_delete":
        sequence[0]["receipt"].update(outcome="failed", reason="synthetic failure")
    elif fault == "unterminated":
        sequence[0].pop("receipt")
    else:
        sequence[0]["approved"] = True
    with pytest.raises(ValueError):
        validate_operation_sequence(sequence)
