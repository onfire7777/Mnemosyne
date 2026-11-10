"""Mandatory learning boundary checks. These checks have no policy off switch."""

from __future__ import annotations

import math

from .receipts import digest
from .signals import WEIGHTS, verified_target_outcome, reprocessed_episode, receipt_target

GUARD_CLASSES = tuple([f"X{i}" for i in range(1, 23)] + [f"E{i}" for i in range(1, 5)])
STATES = {
    "candidate",
    "probation",
    "active",
    "labile",
    "demoted",
    "retired",
    "archived",
    "rejected",
}
TERMINAL_STATES = {"retired", "archived", "rejected"}
SERVABLE_STATES = {"probation", "active", "labile", "demoted"}
FORBIDDEN = {
    "groundedness",
    "authority",
    "trust_tier",
    "access_count",
    "popularity",
    "novelty_reward",
}
ASYMMETRIC_RATES = {
    "positive_rate",
    "negative_rate",
    "positive_learning_rate",
    "negative_learning_rate",
}


class LearningGuardError(ValueError):
    def __init__(self, code: str, reason: str):
        self.code = code
        super().__init__(f"{code}: {reason}")


def require(condition: bool, code: str, reason: str) -> None:
    if not condition:
        raise LearningGuardError(code, reason)


def _finite(value, minimum: float, maximum: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and minimum <= value <= maximum
    )


def _target_key(row: dict) -> str:
    return digest(
        [row["target_kind"], row["target_id"], row["revision"], row["task_class"]]
    )


def _forbidden_inputs(value, code: str) -> None:
    if isinstance(value, dict):
        require(
            not (FORBIDDEN & value.keys()),
            code,
            "authority and exposure inputs are outside learning",
        )
        require(
            not (ASYMMETRIC_RATES & value.keys()),
            "X5",
            "positive and negative outcomes share one learning rate",
        )
        for child in value.values():
            _forbidden_inputs(child, code)
    elif isinstance(value, list):
        for child in value:
            _forbidden_inputs(child, code)


def _validate_receipts(before: dict, after: dict, operation: str) -> None:
    from .task_class import validated_scope_query

    if operation != "erasure":
        require(
            before["receipts"].keys() <= after["receipts"].keys(),
            "X12",
            "receipts cannot be deleted",
        )
    for receipt_id, receipt in after["receipts"].items():
        prediction = receipt.get("prediction")
        require(_finite(prediction, 0, 1), "X12", "invalid prediction")
        require(
            receipt.get("prediction_hash") == digest(prediction),
            "X12",
            "prediction hash mismatch",
        )
        if receipt_id in before["receipts"] and operation != "erasure":
            require(
                receipt == before["receipts"][receipt_id], "X12", "receipt is immutable"
            )
        if receipt_id in before["receipts"]:
            continue
        scope_query = validated_scope_query(receipt, after)
        require(scope_query is not None, "X9", "invalid task scope equivalence")
        if receipt.get("mode") == "fast":
            require(
                receipt.get("goal_checked") is True,
                "X6",
                "fast serving requires a goal check",
            )
        for item in receipt.get("items", []):
            if item.get("kind") == "item":
                continue
            artifact = after["artifacts"].get(item.get("item_id"))
            require(
                artifact is not None and artifact.get("state") in SERVABLE_STATES,
                "X10",
                "served artifact must have a live revision",
            )
            require(
                item.get("revision") == artifact.get("revision"),
                "X10",
                "served revision mismatch",
            )
            require(
                artifact.get("task_class") == receipt.get("task_class"),
                "X9",
                "artifact served outside its class",
            )
            require(
                all(
                    condition.casefold() in scope_query.casefold()
                    for condition in artifact.get("conditions", [])
                ),
                "X9",
                "artifact conditions do not match",
            )
            if receipt.get("mode") == "fast":
                require(
                    bool(artifact.get("goal"))
                    and artifact["goal"].casefold()
                    == receipt.get("query", "").casefold(),
                    "X6",
                    "fast serving goal mismatch",
                )


def _validate_episodes(before: dict, after: dict, operation: str) -> None:
    consumed = set()
    for episode_id, episode in after["episodes"].items():
        for item in episode.get("signals", []):
            require(
                item.get("kind") in WEIGHTS
                and item.get("weight") == WEIGHTS[item["kind"]],
                "X7",
                "reward must have a known external source",
            )
            require(
                _finite(item.get("value"), -1, 1),
                "X7",
                "reward signal must be finite and bounded",
            )
            require(
                item.get("source")
                not in {"assistant", "self_generated", "provider_self_grade"},
                "X7",
                "self-generated signals cannot earn reward",
            )
        for receipt_id in episode.get("receipt_ids", []):
            receipt = after["receipts"].get(receipt_id)
            require(
                receipt is not None
                and receipt.get("session_id") == episode.get("session_id")
                and receipt.get("user_id") == episode.get("user_id")
                and receipt.get("tenant_id") == episode.get("tenant_id"),
                "X3",
                "receipt ownership mismatch",
            )
            require(
                receipt_id not in consumed, "X3", "receipt belongs to only one episode"
            )
            consumed.add(receipt_id)
        previous = before["episodes"].get(episode_id)
        if previous and operation not in {"erasure", "rollback"}:
            require(
                episode.get("prediction") == previous.get("prediction"),
                "X12",
                "episode prediction is immutable",
            )
            if previous.get("status") != "open" and not (
                previous.get("status") == "legacy"
                and operation in {"legacy_migration", "compatibility_save"}
                and episode.get("status") == "legacy"
            ):
                require(
                    episode == previous or (
                        operation == "outcome_reprocess"
                        and episode == reprocessed_episode(previous, after["artifacts"], after["receipts"])
                    ) or (
                        operation == "compatibility_save"
                        and {key: value for key, value in episode.items() if key != "failure_attribution"}
                            == {key: value for key, value in previous.items() if key != "failure_attribution"}
                    ),
                    "X3",
                    "a finalized episode cannot receive another outcome",
                )
        if episode.get("status") == "legacy":
            require(episode.get("reward") is None and episode.get("rpe") is None
                    and not episode.get("signals") and not episode.get("receipt_ids"),
                    "X7", "historical claims cannot supply verified outcomes")
        if episode.get("status") == "erased":
            require(
                not any(
                    episode.get(key)
                    for key in ("source_cids", "signals", "tool_events", "user_text")
                ),
                "X17",
                "erased episode retains source content",
            )
        if episode.get("status") == "resolved":
            for target, result in episode.get("target_outcomes", {}).items():
                require(_finite(result.get("value"), -1, 1)
                        and result.get("rpe") == result["value"] - (2 * episode["prediction"] - 1),
                        "X13", "target prediction error must match its recorded outcome")
                if not previous or previous.get("status") == "open":
                    item = next((item for rid in episode["receipt_ids"]
                                 for item in after["receipts"][rid]["items"] if item["item_id"] == target), None)
                    artifact = receipt_target(item, after["artifacts"]) if item else None
                    require(artifact is not None
                            and verified_target_outcome(artifact, episode) == result["value"],
                            "X7", "target verification requires its own external evidence")
            require(
                _finite(episode.get("reward"), -1, 1),
                "X7",
                "resolved reward must be finite",
            )
            require(
                _finite(episode.get("rpe"), -2, 2),
                "X13",
                "prediction error must be finite",
            )
            expected_error = episode["reward"] - (2 * episode["prediction"] - 1)
            require(
                math.isclose(episode["rpe"], expected_error, abs_tol=1e-12),
                "X13",
                "prediction error and reward must use the same scale",
            )


def _validate_credit(
    before: dict, after: dict, operation: str
) -> dict[str, list[dict]]:
    new_credit = {}
    for credit_id, row in after["credit"].items():
        episode = after["episodes"].get(row.get("episode_id"))
        require(
            episode is not None and episode.get("status") == "resolved",
            "X1",
            "credit needs a resolved outcome",
        )
        require(
            _finite(row.get("contingency_lb"), 0, 1)
            and row["contingency_lb"] > 0
            and min(row.get("served_n", 0), row.get("control_n", 0)) >= 8,
            "X3",
            "credit requires positive matched contingency",
        )
        require(
            row.get("delta") == episode.get("target_outcomes", {}).get(row.get("target_id"), {}).get("rpe", episode.get("rpe")),
            "X13",
            "credit must use recorded prediction error",
        )
        require(
            _finite(row.get("rate"), 0.01, 0.5), "X19", "learning rate out of bounds"
        )
        require(
            _finite(row.get("share"), 0, 1)
            and _finite(row.get("trace"), 0, row["share"]),
            "X19",
            "invalid eligibility or credit share",
        )
        served = [
            item
            for receipt_id in episode.get("receipt_ids", [])
            for item in after["receipts"][receipt_id].get("items", [])
        ]
        require(
            any(
                item.get("kind") == row.get("target_kind")
                and item.get("item_id") == row.get("target_id")
                and item.get("revision") == row.get("revision")
                for item in served
            ),
            "X3",
            "credit target was not served to this episode",
        )
        if credit_id not in before["credit"]:
            new_credit.setdefault(_target_key(row), []).append(row)
        elif operation not in {"erasure", "rollback"}:
            require(
                row == before["credit"][credit_id], "X3", "existing credit is immutable"
            )
    return new_credit


def _validate_stats(
    before: dict, after: dict, operation: str, new_credit: dict
) -> None:
    outcome_bounds = {}
    verified_bounds = {}
    for episode in after["episodes"].values():
        if episode.get("status") != "resolved":
            continue
        task = episode["task_class"]
        probability = (episode["reward"] + 1) / 2
        general_verified = any(signal.get("kind") in {"verifier", "tests", "critic", "rating"}
                               for signal in episode.get("signals", []))
        keys = {digest(["class", task, 1, task]): (probability, general_verified)}
        for receipt_id in episode.get("receipt_ids", []):
            for item in after["receipts"][receipt_id].get("items", []):
                result = episode.get("target_outcomes", {}).get(item["item_id"])
                target_probability = (result["value"] + 1) / 2 if result else probability
                checked = bool(result) if episode.get("outcome_version", 1) >= 2 else general_verified
                keys[digest([item["kind"], item["item_id"], item["revision"], task])] = (target_probability, checked)
        for key, (probability, checked) in keys.items():
            count, successes, failures = outcome_bounds.get(key, (0, 0.0, 0.0))
            outcome_bounds[key] = (
                count + 1,
                successes + probability,
                failures + 1 - probability,
            )
            if checked:
                verified_count, verified_successes = verified_bounds.get(key, (0, 0.0))
                verified_bounds[key] = (
                    verified_count + 1,
                    verified_successes + probability,
                )
    for key, row in after["stats"].items():
        utility = row.get("utility", 1)
        require(_finite(utility, 0.8, 1.2), "X19", "utility must be finite and bounded")
        require(
            _finite(row.get("alpha", 1), 1, float("inf"))
            and _finite(row.get("beta", 1), 1, float("inf"))
            and _finite(row.get("n", 0), 0, float("inf")),
            "X14",
            "invalid posterior counts",
        )
        require(
            math.isclose(
                row.get("alpha", 1) + row.get("beta", 1) - 2,
                row.get("n", 0),
                abs_tol=1e-8,
            ),
            "X14",
            "posterior sufficient statistics disagree",
        )
        count, successes, failures = outcome_bounds.get(key, (0, 0.0, 0.0))
        require(
            row.get("n", 0) <= count + 1e-8
            and row.get("alpha", 1) - 1 <= successes + 1e-8
            and row.get("beta", 1) - 1 <= failures + 1e-8,
            "X16",
            "posterior evidence exceeds recorded resolved outcomes",
        )
        verified_count, verified_successes = verified_bounds.get(key, (0, 0.0))
        require(
            _finite(row.get("verified_n", 0), 0, verified_count)
            and _finite(row.get("verified_successes", 0), 0, row.get("verified_n", 0))
            and row.get("verified_successes", 0) <= verified_successes + 1e-8,
            "X7",
            "verified statistics require actual externally evaluated outcomes",
        )
        previous = before["stats"].get(key, {})
        old_utility = previous.get("utility", 1)
        if utility == old_utility or operation in {"erasure", "rollback"}:
            continue
        if operation == "outcome_reprocess" and utility == 1:
            continue  # Retract utility derived from superseded outcome interpretation.
        normalization = operation == "consolidate" and abs(utility - 1) <= abs(
            old_utility - 1
        )
        if normalization:
            require(
                any(_target_key(credit) == key for credit in after["credit"].values()),
                "X1",
                "normalization needs previously credited utility",
            )
            continue
        require(
            key in new_credit,
            "X1",
            "utility changes require new outcome credit for this target",
        )
        require(
            any(
                (utility - old_utility) * credit["delta"] > 0
                for credit in new_credit[key]
            ),
            "X13",
            "utility moved against its recorded prediction error",
        )


def _validate_gate(artifact: dict) -> None:
    evidence = artifact.get("gate_evidence", {})
    require(
        artifact.get("gate_passed") is True and evidence.get("passed") is True,
        "X21",
        "artifact needs verified promotion gate evidence",
    )
    require(
        evidence.get("content_hash") == digest(artifact.get("content", ""))
        and bool(evidence.get("case_ids"))
        and evidence.get("protected_passed") is True,
        "X21",
        "gate evidence must cover this content and protected cases",
    )
    sanitized = artifact.get("sanitized", {})
    require(
        sanitized.get("content") == artifact.get("content")
        and sanitized.get("instruction_authority") == "none"
        and "no-write-authority" in sanitized.get("capability_tags", []),
        "X11",
        "learned text must retain the data-only boundary",
    )


def _validate_artifacts(
    before: dict, after: dict, operation: str, source_lookup
) -> None:
    for artifact_id, artifact in after["artifacts"].items():
        state = artifact.get("state")
        require(state in STATES, "X10", "unknown artifact state")
        previous = before["artifacts"].get(artifact_id)
        legacy = artifact.get("origin") == "legacy"
        if legacy:
            require(state == "candidate" or state in TERMINAL_STATES,
                    "X21", "unverified historical artifacts cannot be served")
            require(not previous or previous.get("origin") == "legacy",
                    "X21", "native artifacts cannot become historical claims")
        else:
            _forbidden_inputs(
                {key: value for key, value in artifact.items() if key != "sanitized"}, "X22"
            )
        legacy_edit = (legacy and previous and previous.get("origin") == "legacy"
                       and operation == "compatibility_save")
        legacy_admission = (previous and previous.get("origin") == "legacy"
                            and operation == "candidate_admission")
        if previous and operation != "erasure":
            require(
                legacy_edit or (artifact.get("content") == previous.get("content")
                and artifact.get("steps") == previous.get("steps")
                and artifact.get("revision") == previous.get("revision")),
                "X18",
                "content and steps changes require a new revision",
            )
            if previous.get("state") in TERMINAL_STATES:
                require(
                    state == previous["state"], "X10", "retired revisions cannot return"
                )
            if artifact.get("scope") != previous.get("scope") or artifact.get(
                "conditions"
            ) != previous.get("conditions"):
                sources = artifact.get("scope_evidence", [])
                require(
                    legacy_edit or legacy_admission or (operation == "scope_evidence"
                    and bool(sources)
                    and all(
                        after["episodes"].get(key, {}).get("reward", -1) > 0
                        for key in sources
                    )),
                    "X9",
                    "scope changes require recorded successful episodes",
                )
            if previous.get("locked") and operation not in {"lock", "rollback"}:
                require(
                    artifact == previous, "X18", "locked revisions cannot be mutated"
                )
        if previous is None and state in {"active", "labile", "demoted"}:
            require(
                False, "X21", "new artifacts must enter probation before activation"
            )
        if artifact.get("origin") == "imported" and previous is None:
            parent = before["artifacts"].get(artifact.get("parent_revision"), {})
            dormant_rollback = (
                operation == "rollback" and state == "candidate"
                and parent.get("state") in TERMINAL_STATES
                and artifact.get("gate_passed") is False
                and artifact.get("source_episode_ids") == parent.get("source_episode_ids")
                and artifact.get("source_cids") == parent.get("source_cids")
                and artifact.get("content") == parent.get("content")
                and artifact.get("steps") == parent.get("steps")
            )
            require(state == "probation" or dormant_rollback, "X21", "imports must start in probation")
        source_ids = artifact.get("source_episode_ids", [])
        episodes = [after["episodes"].get(key) for key in source_ids]
        require(
            legacy or all(episode is not None for episode in episodes),
            "X15",
            "missing source episode",
        )
        if state in SERVABLE_STATES or (
            state == "candidate" and artifact.get("content") and not legacy
        ):
            require(
                bool(source_ids) and bool(artifact.get("source_cids")),
                "X15",
                "artifact needs provenance",
            )
            allowed_statuses = (
                {"resolved", "imported"}
                if artifact.get("origin") == "imported"
                else {"resolved"}
            )
            require(
                all(episode.get("status") in allowed_statuses for episode in episodes),
                "X15",
                "artifact source episodes must be verified observations or imported provenance",
            )
            require(
                all(
                    episode.get("status") != "imported"
                    or (episode.get("reward") is None and not episode.get("signals"))
                    for episode in episodes
                ),
                "X7",
                "imported provenance cannot supply outcome reward",
            )
            tenants = {episode.get("tenant_id") for episode in episodes}
            require(
                len(tenants) == 1
                and (not artifact.get("tenant_id") or artifact["tenant_id"] in tenants),
                "X15",
                "artifact provenance crosses tenant boundaries",
            )
            recorded_cids = {
                cid for episode in episodes for cid in episode.get("source_cids", [])
            }
            require(
                set(artifact["source_cids"]) <= recorded_cids,
                "X15",
                "artifact evidence is absent from its episodes",
            )
            if source_lookup is not None:
                require(
                    all(
                        (source := source_lookup(cid)) is not None and not source.erased
                        for cid in artifact["source_cids"]
                    ),
                    "X15",
                    "artifact source evidence is not live",
                )
            require(
                artifact.get("explanation_sources") == source_ids
                and bool(artifact.get("explanation")),
                "E4",
                "explanation must identify its live source episodes",
            )
            if previous is None and operation == "consolidate":
                replayed = before["policy"].get("replayed", {})
                require(
                    any(
                        replayed.get(key)
                        != digest(after["episodes"][key].get("signals", []))
                        for key in source_ids
                    ),
                    "X8",
                    "new artifacts require fresh replay evidence",
                )
        if state in SERVABLE_STATES:
            _validate_gate(artifact)
        if state == "labile":
            require(previous is not None and previous.get("state") in {"active", "labile"},
                    "X21", "only an activated artifact may enter reconsolidation")
        if state == "active":
            require(
                not artifact.get("needs_approval") or artifact.get("approved"),
                "X21",
                "effects need approval",
            )
            if previous and previous.get("state") not in {"active", "labile"}:
                from .stats import Posterior, prob_better, wilson_interval

                key = digest(
                    [
                        artifact["kind"],
                        artifact_id,
                        artifact["revision"],
                        artifact["task_class"],
                    ]
                )
                row = after["stats"].get(key, {})
                tested = Posterior.from_dict(row)
                control = Posterior(
                    1 + row.get("control_successes", 0),
                    1 + row.get("control_n", 0) - row.get("control_successes", 0),
                    row.get("control_n", 0),
                )
                require(
                    tested.n >= (5 if artifact.get("schema_ref") else 12)
                    and control.n >= 8
                    and prob_better(tested, control) >= 0.9,
                    "X21",
                    "activation requires successful local probation trials",
                )
                require(
                    row.get("verified_n", 0)
                    >= (5 if artifact.get("schema_ref") else 12)
                    and wilson_interval(
                        row.get("verified_successes", 0), row.get("verified_n", 0)
                    ).low >= 0.5,
                    "X7",
                    "activation requires external verification beyond acceptance feedback",
                )
        quarantined_snapshot = (
            artifact_id in after["policy"].get("outcome_quarantine", {})
            and (operation == "outcome_reprocess"
                 or artifact_id in before["policy"].get("outcome_quarantine", {}))
            and previous == artifact and (artifact.get("pinned") or artifact.get("locked"))
        )
        if "confidence" in artifact and not quarantined_snapshot:
            key = digest(
                [
                    artifact["kind"],
                    artifact_id,
                    artifact["revision"],
                    artifact["task_class"],
                ]
            )
            row = after["stats"].get(key, {})
            expected = row.get("alpha", 1) / (row.get("alpha", 1) + row.get("beta", 1))
            require(
                row.get("n", 0) > 0
                and _finite(artifact["confidence"], 0, 1)
                and math.isclose(artifact["confidence"], expected, abs_tol=1e-12),
                "X16",
                "confidence must come from tested outcome statistics",
            )
        if artifact.get("schema_ref") or state in SERVABLE_STATES:
            quotes = artifact.get("source_quotes", [])
            quote_code = "X20" if artifact.get("schema_ref") else "X15"
            require(bool(quotes), quote_code, "servable content requires source quotes")
            for quote in quotes:
                episode = after["episodes"].get(quote.get("episode_id"), {})
                require(
                    quote.get("episode_id") in source_ids
                    and quote.get("cid") in episode.get("source_cids", [])
                    and bool(quote.get("quote")),
                    quote_code,
                    "quote needs recorded provenance",
                )
                require(
                    source_lookup is not None,
                    quote_code,
                    "quotes require live source verification",
                )
                source = source_lookup(quote["cid"])
                require(
                    source is not None
                    and not source.erased
                    and quote["quote"] in source.content,
                    quote_code,
                    "quote does not occur in live evidence",
                )
            require(
                all(
                    any(step in quote["quote"] for quote in quotes)
                    for step in artifact.get("steps", [])
                ),
                quote_code,
                "servable steps must occur in recorded quotes",
            )
        if artifact.get("replaces") and state == "active":
            scores = artifact.get("abstraction_evaluation", {})
            candidate, originals = (
                scores.get("candidate_scores", []),
                scores.get("original_scores", []),
            )
            require(
                bool(candidate)
                and len(candidate) == len(originals)
                and all(
                    _finite(a, 0, 1) and _finite(b, 0, 1) and a >= b
                    for a, b in zip(candidate, originals)
                ),
                "E3",
                "abstraction must preserve held-out performance",
            )
        for child_id in artifact.get("chunk_ids", []):
            child = after["artifacts"].get(child_id)
            require(child is not None, "E2", "chunk dependency is missing")
            require(
                state != "active" or child.get("state") == "active",
                "E2",
                "active parent has a regressed chunk",
            )


def _validate_replay(before: dict, after: dict) -> None:
    old_replayed = before["policy"].get("replayed", {})
    for episode_id, fingerprint in after["policy"].get("replayed", {}).items():
        if old_replayed.get(episode_id) == fingerprint:
            continue
        episode = after["episodes"].get(episode_id, {})
        require(
            episode.get("status") == "resolved"
            and fingerprint == digest(episode.get("signals", [])),
            "X8",
            "replay must identify a new resolved outcome",
        )
        require(
            old_replayed.get(episode_id) != digest(episode.get("signals", [])),
            "X8",
            "unchanged replay cannot advance",
        )
    for result in after["policy"].get("pattern_splits", {}).values():
        before_scores, after_scores = result.get("before", []), result.get("after", [])
        require(
            len(before_scores) == len(after_scores) == 2
            and all(
                _finite(old, 0, 1) and _finite(new, 0, 1) and new > old
                for old, new in zip(before_scores, after_scores)
            ),
            "E1",
            "a split must improve both held-out classes",
        )


def validate(before: dict, after: dict, operation: str, *, source_lookup=None) -> None:
    """Reject invalid state before persistence, allowing writer containment to commit."""
    require(
        after.keys() == before.keys()
        and all(isinstance(rows, dict) for rows in after.values()),
        "X1",
        "learning collections must preserve their schema",
    )
    for collection in (
        "receipts",
        "episodes",
        "credit",
        "stats",
        "artifacts",
        "defects",
    ):
        require(
            all(isinstance(row, dict) for row in after[collection].values()),
            "X1",
            "learning records must be mappings",
        )
    _forbidden_inputs(after["policy"], "X2")
    _validate_receipts(before, after, operation)
    _validate_episodes(before, after, operation)
    new_credit = _validate_credit(before, after, operation)
    _validate_stats(before, after, operation, new_credit)
    _validate_artifacts(before, after, operation, source_lookup)
    _validate_replay(before, after)
    policy = after["policy"]
    require(
        _finite(policy.get("exploration_floor", 0.02), 0.02, 1),
        "X4",
        "exploration floor is mandatory",
    )
    for weights in policy.get("routes", {}).values():
        require(
            all(_finite(weight, 0.05, 0.65) for weight in weights.values()),
            "X19",
            "route weights out of bounds",
        )
    if policy.get("routes", {}) != before["policy"].get(
        "routes", {}
    ) and operation not in {"erasure", "rollback"}:
        credited_tasks = {
            credit["task_class"] for rows in new_credit.values() for credit in rows
        }
        for task, weights in policy.get("routes", {}).items():
            if weights != before["policy"].get("routes", {}).get(task):
                require(
                    task in credited_tasks,
                    "X1",
                    "route changes require new credit for the same class",
                )
