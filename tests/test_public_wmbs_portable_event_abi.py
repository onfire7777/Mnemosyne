"""Every published portable event must conform to the frozen `portable_event` ABI.

The pilot modules each documented their source events as conforming to
`$defs.portable_event` in `eval/public/schema/wmbs-0.1-draft.schema.json`, but
their own tests only compared top-level key sets, so a module could add keys —
to the event or to its `public_metadata` — and stay green while silently
breaking the closed ABI it claims to implement.

This binds the modules to the committed schema file itself rather than to a
transcribed key list, so widening the ABI requires editing the schema. The
checks intentionally cover the closure contract the schema encodes
(`required` + `additionalProperties: false`, recursively through `$ref`), which
is the part the modules violated; deep value-type validation is the scorers'
job. Deliberately dependency-free: the repo's test suite installs no JSON Schema
library, and the rest of the fixture validators are hand-written closed-key
checks in the same style.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "eval" / "public" / "schema" / "wmbs-0.1-draft.schema.json"
PORTABLE_EVENT_MARKERS = {"event_id", "content_sha256", "public_metadata"}


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Resolve a local `$ref` (`#/$defs/name`) to its definition."""
    seen = set()
    while "$ref" in node:
        ref = node["$ref"]
        assert ref.startswith("#/$defs/"), f"unsupported non-local $ref: {ref}"
        assert ref not in seen, f"cyclic $ref chain at {ref}"
        seen.add(ref)
        node = schema["$defs"][ref.removeprefix("#/$defs/")]
    return node


def _check_object(
    schema: dict[str, Any],
    node: dict[str, Any],
    value: Any,
    path: str,
) -> list[str]:
    """Return closure/required violations of `value` against object schema `node`."""
    node = _resolve(schema, node)
    if node.get("type") != "object" or not isinstance(value, dict):
        return []

    violations = []
    properties = node.get("properties", {})

    for key in node.get("required", []):
        if key not in value:
            violations.append(f"{path}: missing required key {key!r}")

    if node.get("additionalProperties") is False:
        for key in sorted(set(value) - set(properties)):
            violations.append(f"{path}: additional property {key!r} is not allowed")

    for key, sub_value in value.items():
        if key in properties:
            violations.extend(
                _check_object(schema, properties[key], sub_value, f"{path}.{key}")
            )
    return violations


def _iter_portable_events(node: Any) -> Iterator[dict[str, Any]]:
    """Yield every portable event embedded anywhere in a fixture."""
    if isinstance(node, dict):
        if PORTABLE_EVENT_MARKERS <= set(node):
            yield node
        for value in node.values():
            yield from _iter_portable_events(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_portable_events(value)


def _fixture(module_name: str) -> dict[str, Any]:
    module = pytest.importorskip(f"eval.public.{module_name}")
    # M05's committed fixture is the seed-13 generation; the others are default.
    if module_name == "wmbs_m05":
        return module.generate_fixture(13)
    return module.generate_fixture()


# Modules whose plans bind their source events to the frozen ABI:
#   M01 — the conforming precedent (`public_metadata` = {"source": ...}).
#   M05 — "every M05 source event carries all seven or fails ABI validation"
#         under `additionalProperties: false`
#         (docs/plans/wmb-m05-provenance-explanation-implementation-plan.md).
#
# M04 is deliberately absent. Its plan consumes the portable-event *shape
# vocabulary* and states "never a conformance claim"
# (docs/plans/wmb-m04-conflict-correction-implementation-plan.md), requiring
# only that fixture rows carry the seven keys. Its extra `source_id` is
# load-bearing: `gold.ablation_objects` is keyed by source, so dropping it
# would leave the ablation task unanswerable. M04's weaker, actual contract is
# pinned by `test_m04_carries_the_portable_event_vocabulary` below.
CONFORMING_MODULES = ["wmbs_m01", "wmbs_m05"]


@pytest.mark.parametrize("module_name", CONFORMING_MODULES)
def test_fixture_events_conform_to_frozen_portable_event_abi(module_name: str) -> None:
    schema = _schema()
    portable_event = schema["$defs"]["portable_event"]
    events = list(_iter_portable_events(_fixture(module_name)))
    assert events, f"{module_name} exposed no portable events to validate"

    violations: list[str] = []
    for index, event in enumerate(events):
        violations.extend(
            _check_object(schema, portable_event, event, f"{module_name}[{index}]")
        )

    # Report the distinct violation shapes rather than one line per event: a
    # systematic generator bug otherwise produces thousands of identical lines.
    distinct = sorted({v.split(": ", 1)[1] for v in violations})
    assert not violations, (
        f"{module_name}: {len(violations)} portable_event ABI violations across "
        f"{len(events)} events; distinct causes: " + "; ".join(distinct)
    )


def test_m04_carries_the_portable_event_vocabulary() -> None:
    """M04 borrows the shape vocabulary without claiming ABI conformance.

    Its plan requires fixture rows to *carry* the seven portable-event keys, so
    pin that, and pin the documented reason it is not ABI-validated: the extra
    `source_id` the ablation gold is keyed by. If M04 ever drops `source_id` it
    becomes ABI-conforming and belongs in CONFORMING_MODULES instead.
    """
    vocabulary = set(_schema()["$defs"]["portable_event"]["required"])
    events = list(_iter_portable_events(_fixture("wmbs_m04")))
    assert events, "M04 exposed no events"
    for event in events:
        assert vocabulary <= set(event), (
            f"M04 event {event['event_id']} is missing portable-event vocabulary "
            f"keys {sorted(vocabulary - set(event))}"
        )
    assert all("source_id" in event for event in events), (
        "M04's ablation gold is keyed by source_id; every event must carry it"
    )


def test_public_metadata_is_a_closed_single_key_object() -> None:
    """Pin the ABI the modules must not silently widen."""
    schema = _schema()
    public_metadata = schema["$defs"]["public_metadata"]
    assert public_metadata["additionalProperties"] is False
    assert set(public_metadata["properties"]) == {"source"}


def test_validator_rejects_a_widened_public_metadata() -> None:
    """The checker must actually fail on the violation shape found in review."""
    schema = _schema()
    portable_event = schema["$defs"]["portable_event"]
    events = list(_iter_portable_events(_fixture("wmbs_m01")))
    widened = dict(events[0])
    widened["public_metadata"] = {**widened["public_metadata"], "tenant_id": "t-1"}
    widened["source_id"] = "source-a"

    violations = _check_object(schema, portable_event, widened, "synthetic")
    assert any("'tenant_id'" in v for v in violations), violations
    assert any("'source_id'" in v for v in violations), violations
