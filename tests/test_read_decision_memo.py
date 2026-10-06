"""engine._read_decision: may_read_item memoised per stored access-policy object."""

from __future__ import annotations

import datetime as dt
import random
from typing import Any

from mnemosyne import engine as eng
from mnemosyne.access_policy import may_read_item

ROLES = [None, "reader", "operator", "analyst", "nonsense"]
POLICY_SHAPES: list[dict[str, Any]] = [
    {},
    {"tenant": "t"},
    {"tenant": "other"},
    {"restricted": True},
    {"hold": True},
    {"hold:legal": True},
    {"max_sensitivity": 1},
    {"max_sensitivity": "bad"},
    {"allow_roles": ["reader"]},
    {"allow_roles": ["operator"]},
    {"require_capabilities": ["pii"]},
    {"allow_principals": ["u1"]},
    {"scope": ["work"]},
    {"purpose": ["support"]},
    {"lawful_basis": ["consent"]},
    {"redact_fields": ["ssn"], "min_role_for_raw": "operator"},
    {"min_role_for_raw": "operator"},
    {"min_role_for_raw": "nonsense"},
    {"data_residency": ["eu"]},
    {"break_glass": True},
    {"unknown_guard": True},
]
CONTEXT_SHAPES: list[dict[str, Any]] = [
    {},
    {"tenant_id": "t"},
    {"tenant_id": "nope"},
    {"role": "operator", "break_glass": True},
    {"max_sensitivity": 0},
    {"max_sensitivity": "bad"},
    {"capability_tags": ["pii"]},
    {"user_id": "u1"},
    {"scope": ["work"]},
    {"purpose": ["support"]},
    {"lawful_basis": ["consent"]},
    {"runtime_residency": "eu"},
    {"branch": "canary-x", "_retrieval_deep": True},
]


def test_memoised_decisions_equal_the_predicate_over_random_inputs() -> None:
    rng = random.Random(3)
    for _ in range(4000):
        policy = dict(rng.choice(POLICY_SHAPES))
        if rng.random() < 0.3:
            policy.update(rng.choice(POLICY_SHAPES))
        context = dict(rng.choice(CONTEXT_SHAPES))
        if rng.random() < 0.3:
            context.update(rng.choice(CONTEXT_SHAPES))
        if rng.random() < 0.2:
            context["role"] = rng.choice(ROLES) or "reader"
        kwargs = {
            "item_tenant_id": rng.choice(["t", "u"]),
            "sensitivity": rng.randint(0, 5),
            "access_policy": policy,
            "context": context,
            "policy_max_sensitivity": rng.randint(0, 4),
            "status": rng.choice(["active", "candidate", "contested", "superseded"]),
            "erased": rng.random() < 0.1,
        }
        expected = may_read_item(**kwargs)
        # Twice: the second call is the one that may come from the memo.
        assert eng._read_decision(**kwargs) == expected
        assert eng._read_decision(**kwargs) == expected


def test_an_expiring_policy_is_never_cached() -> None:
    soon = dt.datetime.now(dt.UTC) + dt.timedelta(milliseconds=120)
    policy = {"tenant": "t", "expires_at": soon.isoformat()}
    kwargs = {
        "item_tenant_id": "t", "sensitivity": 0, "access_policy": policy, "context": {"tenant_id": "t"},
        "policy_max_sensitivity": 3,
    }
    before = len(eng._READ_DECISIONS)
    assert eng._read_decision(**kwargs).allowed is may_read_item(**kwargs).allowed
    assert len(eng._READ_DECISIONS) == before
    while dt.datetime.now(dt.UTC) < soon:
        pass
    # The verdict moved with the clock, and the memo did not hold the old one.
    assert not eng._read_decision(**kwargs).allowed


def test_an_unkeyable_context_falls_back_to_the_predicate() -> None:
    policy = {"tenant": "t"}
    context = {"tenant_id": "t", "opaque": object()}
    before = len(eng._READ_DECISIONS)
    assert eng._read_decision(
        item_tenant_id="t", sensitivity=0, access_policy=policy, context=context, policy_max_sensitivity=3
    ) == may_read_item(
        item_tenant_id="t", sensitivity=0, access_policy=policy, context=context, policy_max_sensitivity=3
    )
    assert len(eng._READ_DECISIONS) == before


def test_the_memo_is_bounded_and_keyed_on_the_policy_object() -> None:
    eng._READ_DECISIONS.clear()
    context = {"tenant_id": "t"}
    policies = [{"tenant": "t", "max_sensitivity": i % 4} for i in range(200)]
    for policy in policies:
        eng._read_decision(
            item_tenant_id="t", sensitivity=1, access_policy=policy, context=context, policy_max_sensitivity=3
        )
    # Equal policies that are separate objects each get their own entry (identity keyed).
    assert len(eng._READ_DECISIONS) == len(policies)
    assert all(entry[0] is policy for entry, policy in zip(eng._READ_DECISIONS.values(), policies, strict=True))
    size = eng._READ_DECISIONS_SIZE
    try:
        eng._READ_DECISIONS_SIZE = 8
        for policy in [{"tenant": "t", "max_sensitivity": 2} for _ in range(40)]:
            eng._read_decision(
                item_tenant_id="t", sensitivity=1, access_policy=policy, context=context, policy_max_sensitivity=3
            )
        assert len(eng._READ_DECISIONS) <= 8
    finally:
        eng._READ_DECISIONS_SIZE = size
        eng._READ_DECISIONS.clear()
