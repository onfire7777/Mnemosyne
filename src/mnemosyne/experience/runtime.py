"""Experience capture, causal credit, serving and operator controls."""

from __future__ import annotations

import copy
import math
import random
from datetime import UTC, datetime, timedelta
from mnemosyne.ids import new_id

from mnemosyne.models import Evidence
from mnemosyne.learning import Trajectory
from .guards import require
from .receipts import ContextReceipt, ROUTE_OF_CHANNEL, ServedItem, digest
from .signals import reward, signal, tool_signals, user_signals
from .stats import Posterior, contingency_lower_bound, wilson_interval
from .task_class import classify
from .traces import plastic_rate, stiff_step, trace
from .writer import LearningWriter

COMPONENTS = (
    "routes",
    "skills",
    "items",
    "lessons",
    "three_factor",
    "adaptive_rates",
    "stiffness",
    "deferred_resolution",
    "reconsolidation",
    "pattern_separation",
    "schema",
    "homeostasis",
    "revalidation",
    "dreamer",
    "contingency",
    "curiosity",
    "exploration",
    "fast_path",
    "chunking",
    "insight",
    "metacognition",
    "selective_import",
)


def now() -> datetime:
    return datetime.now(UTC)


def _posterior(row: dict | None) -> Posterior:
    return Posterior.from_dict(row)


def stat_key(kind: str, target: str, revision: int, task: str) -> str:
    return digest([kind, target, revision, task])


class _PolicyEvaluationEngine:
    """Keep policy evaluation isolated while using the owning engine's read gates."""

    def __init__(self, engine):
        self.engine = engine
        self.policy = copy.deepcopy(engine.policy)

    def __getattr__(self, name):
        return getattr(self.engine, name)

    def retrieve(
        self,
        query,
        tenant_id,
        branch="main",
        deep=False,
        filt=None,
        *,
        record_access=False,
    ):
        context = dict(filt or {})
        context["_learning_policy_overrides"] = {
            "top_k": self.policy.top_k,
            "abstention_threshold": self.policy.abstention_threshold,
        }
        return self.engine.retrieve(
            query,
            tenant_id,
            branch=branch,
            deep=deep,
            filt=context,
            record_access=False,
        )


class LearningRuntime:
    def __init__(self, engine, skill_store=None):
        self.engine = engine
        self.skill_store = skill_store
        self.writer = LearningWriter(engine)

    def _enabled(self, state: dict, component: str) -> bool:
        policy = self.engine.policy
        enabled = state["policy"].get(
            "enabled", getattr(policy, "learning_enabled", True)
        )
        modes = state["policy"].get("modes", {})
        mode = modes.get(
            component, getattr(policy, "learning_modes", {}).get(component, "active")
        )
        return enabled and not state["policy"].get("frozen", False) and mode == "active"

    def _collects(self, state: dict, component: str) -> bool:
        policy = self.engine.policy
        mode = (
            state["policy"]
            .get("modes", {})
            .get(
                component,
                getattr(policy, "learning_modes", {}).get(component, "active"),
            )
        )
        return (
            state["policy"].get("enabled", getattr(policy, "learning_enabled", True))
            and not state["policy"].get("frozen", False)
            and mode != "off"
        )

    def status(self, tenant_id: str) -> dict:
        state = self.writer.read(tenant_id)
        return {
            "enabled": state["policy"].get(
                "enabled", getattr(self.engine.policy, "learning_enabled", True)
            ),
            "frozen": state["policy"].get("frozen", False),
            "episodes": len(state["episodes"]),
            "credit_rows": len(state["credit"]),
            "artifacts": len(state["artifacts"]),
            "guard_failures": len(state["defects"]),
            "revision": state["policy"].get("revision", 0),
            "modes": {
                name: state["policy"]
                .get("modes", {})
                .get(
                    name,
                    getattr(self.engine.policy, "learning_modes", {}).get(
                        name, "active"
                    ),
                )
                for name in COMPONENTS
            },
            "task_class_method": "explicit-or-lexical-hash",
            "open_defects": sum(
                row["status"] != "verified" for row in state["defects"].values()
            ),
        }

    def mode(self, tenant_id: str, component: str, mode: str) -> dict:
        if component not in COMPONENTS or mode not in {"off", "shadow", "active"}:
            raise ValueError("unknown component or mode")

        def change(state):
            state["policy"].setdefault("modes", {})[component] = mode
            return {"component": component, "mode": mode}

        return self.writer.apply(tenant_id, "mode", change)

    def pause(self, tenant_id: str) -> dict:
        return self.writer.apply(
            tenant_id, "pause", lambda s: s["policy"].update(enabled=False)
        ) or self.status(tenant_id)

    def resume(self, tenant_id: str) -> dict:
        def change(state):
            if any(row["status"] != "verified" for row in state["defects"].values()):
                raise ValueError(
                    "unverified learning defects must be fixed before resuming"
                )
            state["policy"].update(enabled=True, frozen=False)

        self.writer.apply(tenant_id, "resume", change)
        return self.status(tenant_id)

    def defects(self, tenant_id: str, status: str | None = None) -> list[dict]:
        return [
            row
            for row in self.writer.read(tenant_id)["defects"].values()
            if status is None or row["status"] == status
        ]

    def defect_export(self, tenant_id: str, defect_id: str) -> dict:
        from .defects import export

        defect = self.writer.read(tenant_id)["defects"][defect_id]
        return export(defect, self.engine)

    def verify_defect(
        self,
        tenant_id: str,
        defect_id: str,
        fixing_commit: str,
        regression_passed: bool,
    ) -> dict:
        if not regression_passed or not fixing_commit.strip():
            raise ValueError("a fixing commit and passing regression are required")
        from .defects import replay

        if not replay(self.defect_export(tenant_id, defect_id))["passed"]:
            raise ValueError("the redacted defect regression did not pass")

        def change(state):
            defect = state["defects"][defect_id]
            defect.update(status="verified", fixing_commit=fixing_commit)
            return defect

        return self.writer.apply(tenant_id, "verify_defect", change)

    def _sources_live(
        self, tenant: str, cids: list[str], user_id: str | None = None
    ) -> bool:
        from mnemosyne.access_policy import may_read_item

        for cid in cids:
            evidence = self.engine.get_evidence(tenant, cid)
            if evidence is None or evidence.erased:
                return False
            if (
                user_id is not None
                and not may_read_item(
                    item_tenant_id=tenant,
                    sensitivity=evidence.sensitivity,
                    access_policy=evidence.access_policy,
                    context={
                        "tenant_id": tenant,
                        "principal": user_id,
                        "role": "reader",
                    },
                    policy_max_sensitivity=self.engine.policy.max_sensitivity,
                ).allowed
            ):
                return False
        return bool(cids)

    def prepare_context(
        self,
        tenant_id: str,
        user_id: str,
        session_id: str,
        query: str,
        available_tools: list[str] | None = None,
        task_type: str | None = None,
        risk_level: str | None = None,
    ) -> dict:
        tools = available_tools or []
        task = classify(query, tools, task_type)
        if risk_level not in {None, "low", "normal", "high"}:
            raise ValueError("risk_level must be low, normal or high")
        high_risk = risk_level == "high" or task.lower().split(":", 1)[0] in {
            "safety",
            "security",
            "medical",
            "legal",
            "financial",
        }
        self.expire(tenant_id)
        state = self.writer.read(tenant_id)
        if self.skill_store is not None and self._collects(state, "selective_import"):
            from .candidates import register_import

            for candidate in self.skill_store.learning_context(
                query,
                tenant_id=tenant_id,
                user_id=user_id,
                available_tools=tools,
                task_class=task,
            ):
                register_import(self, tenant_id, candidate)
            state = self.writer.read(tenant_id)
        retrieval_filter = {"role": "reader", "user_id": user_id, "principal": user_id}
        effective_policy = self.engine.policy.to_dict()
        effective_policy["learning_enabled"] = state["policy"].get(
            "enabled", effective_policy["learning_enabled"]
        )
        effective_policy["learning_frozen"] = bool(state["policy"].get("frozen", False))
        effective_policy["learning_modes"] = {
            name: state["policy"]
            .get("modes", {})
            .get(name, effective_policy["learning_modes"].get(name, "active"))
            for name in COMPONENTS
        }
        active_variant = state["policy"].get("active_policy_variants", {}).get(task)
        chosen_variant = (
            state["policy"]
            .get("policy_candidates", {})
            .get(task, {})
            .get("variant", {})
            .get("id")
        )
        if not self._enabled(state, "routes") or (
            chosen_variant and active_variant and chosen_variant != active_variant["id"]
        ):
            active_variant = None
        if active_variant:
            from mnemosyne.self_optimization import (
                PolicyVariant,
                within_invariant_rails,
            )

            variant = PolicyVariant(**active_variant)
            if (
                within_invariant_rails(self.engine.policy, variant)
                and variant.abstention_threshold
                >= self.engine.policy.abstention_threshold
            ):
                retrieval_filter["_learning_policy_overrides"] = {
                    "top_k": variant.top_k,
                    "abstention_threshold": variant.abstention_threshold,
                }
                effective_policy.update(retrieval_filter["_learning_policy_overrides"])
            else:
                active_variant = None

        if self._enabled(state, "routes"):
            routes = self._route_prior(state, task)
            if routes:
                retrieval_filter["_learning_route_weights"] = routes
        effective_policy["applied_route_weights"] = copy.deepcopy(
            retrieval_filter.get("_learning_route_weights", {})
        )
        effective_policy["applied_policy_variant"] = (
            active_variant["id"] if active_variant else None
        )
        artifacts = []
        for item in state["artifacts"].values():
            # Source readability does not transfer ownership of learned behavior.
            # Match the owner scope used by framework and revalidation serving.
            if item.get("user_id") != user_id:
                continue
            if item["state"] not in {
                "active",
                "labile",
                "probation",
                "demoted",
            }:
                continue
            required_tools = item.get("needs", [])
            if (
                not required_tools
                and item.get("source_skill_id")
                and self.skill_store is not None
            ):
                import json

                library_row = self.skill_store._skill(
                    item["source_skill_id"], item["source_skill_revision"]
                )
                required_tools = json.loads(library_row["needs"])
            if not {name.casefold() for name in required_tools}.issubset(
                {name.casefold() for name in tools}
            ):
                continue
            if high_risk:
                from mnemosyne.skills import effects_of

                if item.get("needs_approval") or effects_of(
                    [{"content": item["content"]}], []
                ):
                    continue
            component = "skills" if item["kind"] in {"skill", "chunk"} else "lessons"
            if (
                not self._enabled(state, component)
                or item.get("needs_approval")
                and not item.get("approved")
            ):
                continue
            if not self._sources_live(tenant_id, item.get("source_cids", []), user_id):
                continue
            from .candidates import applies_to

            if not applies_to(item, task, query):
                continue
            stats = self._target_posterior(
                state, item["kind"], item["id"], item["revision"], task
            )
            artifacts.append(
                {
                    **item,
                    "confidence": stats.mean,
                    "lower_bound": stats.lower_bound,
                    "low_confidence": stats.lower_bound < 0.8,
                }
            )
        seed = int(
            digest([tenant_id, session_id, query, len(state["receipts"])])[:16], 16
        )
        rng = random.Random(seed)
        exploration = (
            not high_risk
            and self._enabled(state, "exploration")
            and rng.random()
            < max(
                getattr(self.engine.policy, "learning_exploration_floor", 0.02),
                getattr(self.engine.policy, "learning_exploration_rate", 0.1),
            )
        )
        known_active = sorted(
            (item for item in artifacts if item["state"] == "active"),
            key=lambda item: (-item["lower_bound"], item["id"]),
        )
        best_known = known_active[0] if known_active else None
        pending_trial = any(
            item.get("ab_trial", {}).get("status") == "pending" for item in artifacts
        )
        fast_eligible = bool(
            best_known
            and self._enabled(state, "fast_path")
            and not high_risk
            and not exploration
            and not pending_trial
            and best_known.get("goal", "").casefold() == query.casefold()
            and best_known["lower_bound"] >= 0.8
            and not state["policy"].get("surprised", {}).get(task)
        )
        comparison_sample = fast_eligible and rng.random() < getattr(
            self.engine.policy, "learning_goal_check_comparison_rate", 0.05
        )
        full_retrieval_performed = not fast_eligible or comparison_sample
        if full_retrieval_performed:
            retrieval = self.engine.retrieve(
                query, tenant_id=tenant_id, filt=retrieval_filter, record_access=True
            )
            hits = [hit.to_dict() for hit in retrieval.hits]
            eligible_hits = list(hits)
            # Scoring occurs only after the engine's access, trust and tenant filters.
            if self._enabled(state, "items"):
                for hit in hits:
                    key = stat_key("item", hit["id"], 1, task)
                    hit["learning_utility"] = (
                        state["stats"].get(key, {}).get("utility", 1.0)
                    )
                hits.sort(
                    key=lambda hit: (
                        float(hit.get("score", 0)) * hit["learning_utility"]
                    ),
                    reverse=True,
                )
        else:
            hits, eligible_hits = [], []
        if not high_risk and self._enabled(state, "exploration"):
            hits = [
                hit
                for hit in hits
                if rng.random()
                >= max(
                    getattr(self.engine.policy, "learning_exploration_floor", 0.02),
                    getattr(self.engine.policy, "learning_exploration_rate", 0.1),
                )
            ]
        active = [item for item in artifacts if item["state"] in {"active", "labile"}]
        candidates = [
            item for item in artifacts if item["state"] in {"probation", "demoted"}
        ]
        active.sort(key=lambda item: (-item["lower_bound"], item["id"]))
        if exploration and candidates:
            # Thompson sampling expresses uncertainty, using tested outcome posteriors only.
            candidates.sort(
                key=lambda item: rng.betavariate(
                    _posterior(
                        state["stats"].get(
                            stat_key(item["kind"], item["id"], item["revision"], task)
                        )
                    ).alpha,
                    _posterior(
                        state["stats"].get(
                            stat_key(item["kind"], item["id"], item["revision"], task)
                        )
                    ).beta,
                ),
                reverse=True,
            )
            active = [{**candidates[0], "exploration": True}] + active
        selected = active[:3]
        revision_trial = None
        for candidate in sorted(artifacts, key=lambda item: item["id"]):
            trial = candidate.get("ab_trial", {})
            if candidate["state"] != "probation" or trial.get("status") != "pending":
                continue
            parent = next(
                (item for item in artifacts if item["id"] == trial["incumbent_id"]),
                None,
            )
            if parent is None:
                continue
            from .revisions import ab_assignment

            trial_key = digest(
                [session_id, state["policy"].get("turns", {}).get(session_id, 0), query]
            )
            arm = ab_assignment(tenant_id, task, trial_key, parent["id"])
            chosen = candidate if arm == "candidate" else parent
            selected = [chosen] + [
                item
                for item in selected
                if item["id"] not in {candidate["id"], parent["id"]}
            ]
            selected = selected[:3]
            revision_trial = {
                "candidate_id": candidate["id"],
                "arm": arm,
                "trial_key": trial_key,
            }
            break
        prediction = _posterior(
            state["stats"].get(stat_key("class", task, 1, task))
        ).mean
        if selected:
            logits = [
                math.log(
                    max(0.001, min(0.999, item["confidence"]))
                    / (1 - max(0.001, min(0.999, item["confidence"])))
                )
                for item in selected
            ]
            prediction = 1 / (1 + math.exp(-sum(logits) / len(logits)))
        bin_key = str(min(9, int(prediction * 10)))
        calibration = state["policy"].get("calibration_bins", {}).get(bin_key, {})
        if self._enabled(state, "metacognition") and calibration.get("n", 0) >= 20:
            prediction = (calibration["successes"] + 1) / (calibration["n"] + 2)
        mode = "fast" if fast_eligible else "deliberate"
        turn_index = state["policy"].get("turns", {}).get(session_id, 0)
        served = []
        for rank, hit in enumerate(hits, 1):
            channels = hit.get("metadata", {}).get("channels") or str(
                hit.get("channel", "")
            ).split("+")
            if isinstance(channels, str):
                channels = channels.split("+")
            routes = tuple(
                sorted(
                    {
                        ROUTE_OF_CHANNEL.get(channel, channel)
                        for channel in channels
                        if channel
                    }
                )
            )
            served.append(ServedItem("item", hit["id"], routes, rank))
        served += [
            ServedItem(item["kind"], item["id"], (), rank, item["revision"])
            for rank, item in enumerate(selected, 1)
        ]
        receipt = ContextReceipt(
            new_id(),
            tenant_id,
            user_id,
            session_id,
            task,
            prediction,
            digest(effective_policy),
            now().isoformat(),
            turn_index,
            tuple(served),
        ).to_dict()
        receipt.update(
            query=query,
            effective_policy=effective_policy,
            policy_variant_id=active_variant["id"]
            if active_variant
            else self._policy_variants(task)[0].id,
            mode=mode,
            full_retrieval_performed=full_retrieval_performed,
            comparison_sample=bool(comparison_sample),
            goal_checked=mode == "fast",
            exploration=exploration,
            risk_level="high" if high_risk else risk_level or "normal",
            revision_trial=revision_trial,
            eligible_targets=[
                {"kind": "item", "item_id": hit["id"], "revision": 1}
                for hit in eligible_hits
            ]
            + [
                {
                    "kind": item["kind"],
                    "item_id": item["id"],
                    "revision": item["revision"],
                }
                for item in artifacts
            ],
            available_tools=tools,
            source_cids=sorted(
                {cid for item in selected for cid in item["source_cids"]}
            ),
        )

        def capture(current):
            current["receipts"][receipt["id"]] = receipt

        self.writer.apply(tenant_id, "capture", capture)
        from .candidates import (
            learning_knowledge_context,
            materialize_framework,
            verification_requests,
        )

        selected_ids = [item["id"] for item in selected]
        knowledge = learning_knowledge_context(
            self,
            tenant_id,
            user_id,
            task,
            query,
            state=state,
            selected_artifact_ids=selected_ids,
        )
        for item in selected:
            item["framework"] = materialize_framework(
                self, tenant_id, user_id, item, state
            )
        requests = verification_requests(
            self, tenant_id, user_id, task, query, state=state
        )
        if comparison_sample:
            requests.append(
                {
                    "kind": "goal_comparison",
                    "receipt_id": receipt["id"],
                    "query": query,
                    "artifact_ids": selected_ids,
                }
            )
        return {
            "hits": hits,
            "lessons": [a for a in selected if a["kind"] == "lesson"],
            "procedures": [a for a in selected if a["kind"] == "procedure"],
            "skills": [a for a in selected if a["kind"] in {"skill", "chunk"}],
            "chunks": [a for a in selected if a["kind"] == "chunk"],
            "knowledge_pages": knowledge,
            "verification_requests": requests,
            "policy_verification_request": {
                "variant": self._policy_variants(task)[1].to_dict(),
                "policy_fingerprint": digest(self._policy_variants(task)[1].to_dict()),
                "event_name": "policy_variant_verifier",
            },
            "receipt_id": receipt["id"],
            "task_class": task,
            "prediction": prediction,
            "mode": mode,
            "goal_checked": mode == "fast",
            "exploration": exploration,
        }

    def observe_turn(
        self,
        tenant_id: str,
        user_id: str,
        session_id: str,
        user_text: str,
        assistant_text: str,
        tool_events: list[dict] | None = None,
        receipt_ids: list[str] | None = None,
        used_skills: list | None = None,
        used_lessons: list | None = None,
        source_cids: list[str] | None = None,
    ) -> dict:
        state = self.writer.read(tenant_id)
        supplied = []
        for cid in source_cids or []:
            source = self.engine.get_evidence(tenant_id, cid)
            if (
                source is None
                or source.erased
                or source.user_id != user_id
                or source.session_id != session_id
            ):
                raise ValueError(
                    "captured source belongs to a different or erased session"
                )
            if (source.actor, source.content) not in {
                ("user", user_text),
                ("assistant", assistant_text),
            }:
                raise ValueError("captured source does not match the observed turn")
            supplied.append(source)
        receipts = [state["receipts"][key] for key in (receipt_ids or [])]
        used = {
            key
            for episode in state["episodes"].values()
            for key in episode["receipt_ids"]
        }
        if len({r["id"] for r in receipts}) != len(receipts):
            raise ValueError("duplicate receipt")
        for receipt in receipts:
            if (
                receipt["user_id"] != user_id
                or receipt["session_id"] != session_id
                or receipt["id"] in used
            ):
                raise ValueError("receipt belongs to a different turn")
        previous = [
            e
            for e in state["episodes"].values()
            if e["session_id"] == session_id
            and e["user_id"] == user_id
            and e["status"] == "open"
        ]
        previous.sort(key=lambda e: (e["created_at"], e["id"]))
        for episode in previous[-1:]:
            age = (
                now() - datetime.fromisoformat(episode["created_at"])
            ).total_seconds()
            previous_query = (
                episode.get("user_text", "")
                if not any(
                    item["kind"] in {"verifier", "tests", "critic"}
                    for item in episode["signals"]
                )
                else ""
            )
            replies = user_signals(user_text, previous_query) if age <= 900 else []
            for item in replies:
                self.record_signal(
                    tenant_id,
                    episode_id=episode["id"],
                    kind=item["kind"],
                    value=item["value"],
                    evidence=item["evidence"],
                    source_cid=next(
                        (
                            source.cid
                            for source in supplied
                            if source.actor == "user"
                            and source.content == item["evidence"]
                        ),
                        None,
                    ),
                )
            if replies or episode.get("signals"):
                self.resolve(tenant_id, episode["id"])
        cids = []
        for actor, text in [("user", user_text), ("assistant", assistant_text)]:
            if not text:
                continue
            existing = next(
                (
                    source
                    for source in supplied
                    if source.actor == actor and source.content == text
                ),
                None,
            )
            if existing is not None:
                cids.append(existing.cid)
                continue
            cids.append(
                self.engine.append_evidence(
                    Evidence(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        actor=actor,
                        source_type="learning_turn",
                        content=text,
                        document_segment_id="learning:" + digest([tenant_id, user_id, session_id, actor]),
                        session_id=session_id,
                        trust_tier=0 if actor == "user" else 5,
                        metadata={
                            "reality_class": "external"
                            if actor == "user"
                            else "self_generated"
                        },
                        access_policy={
                            "tenant": tenant_id,
                            "allow_principals": [user_id],
                        },
                    )
                )
            )
        for event in tool_events or []:
            if event.get("source") in {
                "assistant",
                "self_generated",
                "provider_self_grade",
            }:
                continue
            content = str(event.get("output") or event.get("evidence") or "")
            for field in ("expected_steps", "corrective_steps", "tested_steps"):
                steps = event.get(field)
                if isinstance(steps, list) and all(
                    isinstance(step, str) for step in steps
                ):
                    content += "\n" + "\n".join(steps)
            if content:
                cids.append(
                    self.engine.append_evidence(
                        Evidence(
                            tenant_id=tenant_id,
                            user_id=user_id,
                            actor="tool",
                            source_type="learning_tool_result",
                            content=content,
                            document_segment_id="learning:" + digest([tenant_id, user_id, session_id, "tool"]),
                            session_id=session_id,
                            trust_tier=1,
                            access_policy={
                                "tenant": tenant_id,
                                "allow_principals": [user_id],
                            },
                        )
                    )
                )
        signals = tool_signals(tool_events or [])
        served_ids = {
            item["item_id"] for receipt in receipts for item in receipt["items"]
        }
        normalized_skills = []
        for value in used_skills or []:
            revision = value.get("revision") if isinstance(value, dict) else None
            identifier = (
                str(value.get("skill_id", value.get("id", "")))
                if isinstance(value, dict)
                else str(value)
            )
            if "@" in identifier and identifier.rsplit("@", 1)[1].isdigit():
                identifier, encoded_revision = identifier.rsplit("@", 1)
                revision = int(encoded_revision)
            matches = [
                artifact_id
                for artifact_id in served_ids
                if artifact_id == identifier
                or (
                    state["artifacts"].get(artifact_id, {}).get("source_skill_id")
                    == identifier
                    and (
                        revision is None
                        or state["artifacts"][artifact_id].get("source_skill_revision")
                        == revision
                    )
                )
            ]
            if len(matches) == 1 and matches[0] not in normalized_skills:
                normalized_skills.append(matches[0])
        normalized_lessons = [item for item in used_lessons or [] if item in served_ids]
        episode_id = new_id()
        timestamp = now()
        episode = Trajectory.from_record({
            "id": episode_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "session_id": session_id,
            "task_class": receipts[-1]["task_class"]
            if receipts
            else classify(user_text, []),
            "receipt_ids": list(receipt_ids or []),
            "source_cids": cids,
            "signals": signals,
            "tool_events": copy.deepcopy(tool_events or []),
            "used_skills": normalized_skills,
            "used_lessons": normalized_lessons,
            "user_text": user_text,
            "cited_cids": sorted(
                {
                    cid
                    for event in tool_events or []
                    for claim in event.get("claims", [])
                    for cid in claim.get("evidence_cids", [])
                }
            ),
            "status": "open",
            "created_at": timestamp.isoformat(),
            "expires_at": (
                timestamp
                + timedelta(
                    minutes=getattr(
                        self.engine.policy, "learning_resolution_window_minutes", 180
                    )
                )
            ).isoformat(),
            "prediction": receipts[-1]["prediction"] if receipts else 0.5,
            "reward": None,
            "rpe": None,
            "turn_index": len(
                [e for e in state["episodes"].values() if e["session_id"] == session_id]
            ),
        }).to_record()

        def observe(current):
            if any(
                receipt_id in row["receipt_ids"]
                for row in current["episodes"].values()
                for receipt_id in episode["receipt_ids"]
            ):
                raise ValueError("receipt was consumed concurrently")
            current["episodes"][episode_id] = episode
            current["policy"].setdefault("turns", {})[session_id] = (
                episode["turn_index"] + 1
            )

        self.writer.apply(tenant_id, "observe", observe)
        return {"episode_id": episode_id}

    def episode(self, tenant_id: str, episode_id: str) -> dict:
        return self.writer.read(tenant_id)["episodes"][episode_id]

    def record_signal(
        self,
        tenant_id: str,
        episode_id: str | None = None,
        receipt_id: str | None = None,
        kind: str = "verifier",
        value: float = 0,
        evidence: str = "",
        final: bool = False,
        source_cid: str | None = None,
    ) -> dict:
        self.expire(tenant_id)
        item = signal(kind, value, evidence)
        correction_cid = None
        if kind == "correction" and evidence.strip():
            current = self.writer.read(tenant_id)
            targets = [
                row
                for row in current["episodes"].values()
                if row["id"] == episode_id
                or (receipt_id is not None and receipt_id in row["receipt_ids"])
            ]
            if (
                len(targets) == 1
                and targets[0]["status"] == "open"
                and item not in targets[0]["signals"]
            ):
                episode = targets[0]
                if source_cid is not None:
                    source = self.engine.get_evidence(tenant_id, source_cid)
                    if (
                        source is None
                        or source.erased
                        or source.user_id != episode["user_id"]
                        or source.actor != "user"
                        or source.content != evidence
                    ):
                        raise ValueError(
                            "correction source does not match the external user text"
                        )
                    correction_cid = source_cid
                else:
                    correction_cid = self.engine.append_evidence(
                        Evidence(
                            tenant_id=tenant_id,
                            user_id=episode["user_id"],
                            actor="user",
                            source_type="learning_correction",
                            content=evidence,
                            document_segment_id="learning:" + digest([tenant_id, episode["user_id"], episode["session_id"], "user"]),
                            session_id=episode["session_id"],
                            trust_tier=1,
                            metadata={"reality_class": "external"},
                            access_policy={
                                "tenant": tenant_id,
                                "allow_principals": [episode["user_id"]],
                            },
                        )
                    )

        def record(state):
            target = episode_id
            if target is None:
                candidates = [
                    row["id"]
                    for row in state["episodes"].values()
                    if receipt_id in row["receipt_ids"]
                ]
                if len(candidates) != 1:
                    raise ValueError("receipt must identify one observed episode")
                target = candidates[0]
            episode = state["episodes"][target]
            if episode["status"] != "open":
                if item in episode["signals"]:
                    return target
                raise ValueError("episode already finalized")
            if item not in episode["signals"]:
                episode["signals"].append(item)
                if correction_cid and correction_cid not in episode["source_cids"]:
                    episode["source_cids"].append(correction_cid)
            return target

        target = self.writer.apply(tenant_id, "signal", record)
        return (
            self.resolve(tenant_id, target)
            if final
            else self.episode(tenant_id, target)
        )

    def resolve(
        self, tenant_id: str, episode_id: str, *, expired: bool = False
    ) -> dict:
        def resolve_episode(state):
            episode = state["episodes"][episode_id]
            if episode["status"] != "open":
                return episode
            outcome = reward(episode["signals"])
            if outcome is None and not expired:
                return episode
            episode["status"] = "unknown" if outcome is None else "resolved"
            episode["reward"] = outcome
            episode["resolved_at"] = now().isoformat()
            episode["resolved_turn_index"] = (
                state["policy"]
                .get("turns", {})
                .get(episode["session_id"], episode["turn_index"] + 1)
            )
            if outcome is None:
                return episode
            episode["rpe"] = outcome - (2 * episode["prediction"] - 1)
            for receipt_id in episode["receipt_ids"]:
                receipt = state["receipts"][receipt_id]
                require(
                    receipt["prediction_hash"] == digest(receipt["prediction"]),
                    "X12",
                    "prediction changed",
                )
            episode["learning_collected"] = self._collects(state, "contingency")
            episode["learning_components"] = {
                component: self._collects(state, component)
                for component in ("items", "lessons", "skills")
            }
            if episode["learning_collected"]:
                self._credit(state, episode)
            self._update_goal_state(state, episode)
            if self._collects(state, "metacognition") and any(
                signal["kind"] in {"verifier", "tests"} for signal in episode["signals"]
            ):
                bin_key = str(min(9, int(episode["prediction"] * 10)))
                calibration = (
                    state["policy"]
                    .setdefault("calibration_bins", {})
                    .setdefault(bin_key, {"n": 0, "successes": 0.0})
                )
                calibration["n"] += 1
                calibration["successes"] += (outcome + 1) / 2
            if self._enabled(state, "skills"):
                for receipt_id in episode["receipt_ids"]:
                    for item in state["receipts"][receipt_id]["items"]:
                        artifact = state["artifacts"].get(item["item_id"], {})
                        if (
                            artifact.get("source_skill_id")
                            and item["item_id"] in episode["used_skills"]
                        ):
                            event_id = digest([episode["id"], artifact["id"]])
                            state["policy"].setdefault("skill_outbox", {})[event_id] = {
                                "skill_id": artifact["source_skill_id"],
                                "revision": artifact["source_skill_revision"],
                                "success": outcome,
                                "evidence": episode["id"],
                                "episode_id": episode["id"],
                            }
            self._record_policy_learning(state, episode)
            self._breaker(state, episode)
            return episode

        result = self.writer.apply(tenant_id, "resolve", resolve_episode)
        self._flush_skill_outbox(tenant_id)
        self._evaluate_policy_learning(tenant_id, result["task_class"])
        return result

    def _update_goal_state(self, state: dict, episode: dict) -> None:
        if not self._enabled(state, "fast_path"):
            return
        task = episode["task_class"]
        if episode["rpe"] <= -0.5:
            state["policy"].setdefault("surprised", {})[task] = True
            return
        verified = any(
            item["kind"] in {"verifier", "tests", "critic", "rating"}
            for item in episode["signals"]
        )
        if episode["reward"] <= 0 or not verified:
            return
        for receipt_id in episode["receipt_ids"]:
            receipt = state["receipts"][receipt_id]
            for item in receipt["items"]:
                artifact = state["artifacts"].get(item["item_id"], {})
                if (
                    artifact.get("state") == "active"
                    and artifact.get("goal", "").casefold()
                    == receipt.get("query", "").casefold()
                ):
                    state["policy"].get("surprised", {}).pop(task, None)
                    return

    def _flush_skill_outbox(self, tenant_id: str) -> None:
        if self.skill_store is None:
            return
        if not self._enabled(self.writer.read(tenant_id), "skills"):
            return
        # The library projects the native ledger; delivering an event must never
        # run a second lifecycle or add outcomes on top of projected counters.
        self._sync_library_revision_states(tenant_id)
        if self.writer.read(tenant_id)["policy"].get("skill_outbox"):
            self.writer.apply(
                tenant_id, "skill_outcomes_projected",
                lambda state: state["policy"].pop("skill_outbox", None),
            )

    def _credit(self, state: dict, episode: dict, *, rebuild: bool = False) -> None:
        task, outcome = episode["task_class"], episode["reward"]
        probability = (outcome + 1) / 2
        receipts = [state["receipts"][key] for key in episode["receipt_ids"]]
        targets = {
            (item["kind"], item["item_id"], item["revision"]): item
            for receipt in receipts
            for item in receipt["items"]
        }
        class_key = stat_key("class", task, 1, task)
        class_stats = _posterior(state["stats"].get(class_key))
        class_stats.update(probability)
        state["stats"][class_key] = class_stats.to_dict()
        # Eligibility is frozen at serve time, so future artifacts never become historical controls.
        for receipt in receipts:
            for item in receipt.get("eligible_targets", receipt["items"]):
                targets.setdefault(
                    (item["kind"], item["item_id"], item["revision"]), None
                )
        route_rewards = {}
        for (kind, target, revision), served in targets.items():
            component = "skills" if kind in {"skill", "chunk"} else "lessons" if kind in {"lesson", "procedure"} else "items"
            if not episode.get("learning_components", {}).get(component, True):
                continue
            key = stat_key(kind, target, revision, task)
            row = state["stats"].setdefault(
                key,
                {
                    **Posterior().to_dict(),
                    "served_successes": 0.0,
                    "served_n": 0,
                    "control_successes": 0.0,
                    "control_n": 0,
                    "utility": 1.0,
                    "importance": 0.0,
                },
            )
            prefix = "served" if served else "control"
            row[prefix + "_n"] += 1
            row[prefix + "_successes"] += probability
            if served:
                if any(
                    item["kind"] in {"verifier", "tests", "critic", "rating"}
                    for item in episode["signals"]
                ):
                    row["verified_n"] = row.get("verified_n", 0) + 1
                    row["verified_successes"] = (
                        row.get("verified_successes", 0.0) + probability
                    )
                previous_outcome = row.get("last_outcome")
                row["reversals"] = row.get("reversals", 0) + int(
                    previous_outcome is not None
                    and (previous_outcome > 0) != (outcome > 0)
                )
                row["last_outcome"] = outcome
                row["last_outcome_at"] = episode["resolved_at"]
                row["volatility"] = row["reversals"] / max(1, row["served_n"] - 1)
                posterior = _posterior(row)
                posterior.update(probability)
                row.update(posterior.to_dict())
            lower = contingency_lower_bound(
                row["served_successes"],
                row["served_n"],
                row["control_successes"],
                row["control_n"],
                minimum=getattr(
                    self.engine.policy, "learning_contingency_min_samples", 8
                ),
            )
            if rebuild or not served or lower is None or lower <= 0:
                continue
            cited = set(episode.get("cited_cids", []))
            if kind == "item":
                cited_items = sum(
                    item is not None and key[0] == "item" and key[1] in cited
                    for key, item in targets.items()
                )
                other_items = sum(
                    item is not None and key[0] == "item" and key[1] not in cited
                    for key, item in targets.items()
                )
                share = (
                    0.7 / max(1, cited_items)
                    if target in cited
                    else 0.3 / max(1, other_items)
                )
            elif kind in {"skill", "chunk"} and target in episode.get(
                "used_skills", []
            ):
                share = 1.0
            elif kind == "lesson" and target in episode.get("used_lessons", []):
                share = 0.5
            else:
                share = 0.3 / max(1, sum(item is not None for item in targets.values()))
            elapsed = (
                (
                    datetime.fromisoformat(episode["resolved_at"])
                    - datetime.fromisoformat(receipts[-1]["created_at"])
                ).total_seconds()
                / 60
                if receipts
                else 0
            )
            eligibility = trace(
                share,
                max(
                    0,
                    episode.get("resolved_turn_index", episode["turn_index"] + 1)
                    - receipts[-1]["turn_index"]
                    - 1,
                ),
                elapsed,
                lam=receipts[-1]
                .get("effective_policy", {})
                .get("learning_trace_lambda", 0.7)
                if receipts
                else 0.7,
                tau=receipts[-1]
                .get("effective_policy", {})
                .get("learning_trace_tau_minutes", 30)
                if receipts
                else 30,
            )
            rate = (
                plastic_rate(0.1, row["n"], 20, row.get("volatility", 0))
                if self._enabled(state, "adaptive_rates")
                else 0.1
            )
            delta = max(-1.0, min(1.0, episode["rpe"]))
            step = rate * eligibility * delta
            if self._enabled(state, "stiffness"):
                step = stiff_step(
                    step,
                    row["importance"]
                    + sum(
                        max(0.0, credit["delta"]) * credit.get("share", 1.0)
                        for credit in state["credit"].values()
                        if credit["target_id"] == target
                        and credit["target_kind"] == kind
                        and credit["task_class"] != task
                    ),
                    verified_failure=outcome < 0
                    and any(s["kind"] == "verifier" for s in episode["signals"]),
                )
            old_utility = row["utility"]
            if kind == "item":
                day = episode["resolved_at"][:10]
                used_budget = sum(
                    abs(credit.get("step", 0.0))
                    for credit in state["credit"].values()
                    if credit["target_kind"] == "item"
                    and credit["target_id"] == target
                    and (prior := state["episodes"].get(credit["episode_id"], {})).get(
                        "user_id"
                    )
                    == episode.get("user_id")
                    and prior.get("session_id") == episode.get("session_id")
                    and prior.get("resolved_at", "")[:10] == day
                )
                remaining = max(0.0, 0.10 - used_budget)
                step = max(-remaining, min(remaining, step))
            if self._collects(state, "three_factor"):
                row["utility"] = max(0.8, min(1.2, old_utility + step))
            for route in served.get("routes", []):
                route_rewards[route] = route_rewards.get(
                    route, 0
                ) + delta * eligibility / max(1, len(served["routes"]))
            if outcome > 0:
                row["importance"] += probability
            credit_id = digest([episode["id"], kind, target, revision])
            state["credit"][credit_id] = {
                "episode_id": episode["id"],
                "target_kind": kind,
                "target_id": target,
                "revision": revision,
                "task_class": task,
                "share": share,
                "trace": eligibility,
                "delta": episode["rpe"],
                "rate": rate,
                "step": row["utility"] - old_utility,
                "contingency_lb": lower,
                "served_n": row["served_n"],
                "control_n": row["control_n"],
            }
            artifact = state["artifacts"].get(target)
            if (
                artifact
                and share >= 0.3
                and episode["rpe"] <= -0.5
                and self._enabled(state, "reconsolidation")
            ):
                if not artifact.get("pinned") and artifact["state"] == "active":
                    artifact["state"] = "labile"
                    artifact["labile_until"] = (now() + timedelta(hours=3)).isoformat()
        if not rebuild and self._collects(state, "routes"):
            from .learners import update_routes

            update_routes(state, task, route_rewards)

    def _target_posterior(
        self, state: dict, kind: str, target: str, revision: int, task: str
    ):
        local = _posterior(state["stats"].get(stat_key(kind, target, revision, task)))
        if local.n >= 20:
            return local
        classes = {
            row["task_class"]
            for row in state["episodes"].values()
            if row["status"] == "resolved" and row["task_class"] != task
        }
        others = [
            _posterior(state["stats"].get(stat_key(kind, target, revision, other)))
            for other in classes
        ]
        total = sum(row.n for row in others)
        if not total:
            return local
        mean = sum(row.alpha - 1 for row in others) / total
        strength = min(2.0, (20 - local.n) / 10)
        return Posterior(
            local.alpha + strength * mean,
            local.beta + strength * (1 - mean),
            local.n + strength,
        )

    def _route_prior(self, state: dict, task: str):
        from mnemosyne.self_optimization import AdaptiveRouteWeighter

        routes = state["policy"].get("routes", {})
        local = routes.get(task)
        n = _posterior(state["stats"].get(stat_key("class", task, 1, task))).n
        others = [row for other, row in routes.items() if other != task]
        if n >= 20 or not others:
            return local
        base = local or AdaptiveRouteWeighter().get_weights("prior")
        shared = {
            key: sum(row.get(key, base[key]) for row in others) / len(others)
            for key in base
        }
        weight = n / 20
        return {key: weight * base[key] + (1 - weight) * shared[key] for key in base}

    def _policy_variants(self, task: str):
        from mnemosyne.self_optimization import PolicyVariant

        base = self.engine.policy
        prefix = "policy-" + digest(task)[:16]
        return [
            PolicyVariant(
                prefix + "-baseline",
                dict(base.activation_weights),
                base.abstention_threshold,
                base.top_k,
            ),
            PolicyVariant(
                prefix + "-wide",
                dict(base.activation_weights),
                min(0.95, base.abstention_threshold + 0.05),
                min(64, base.top_k + 4),
            ),
        ]

    def _record_policy_learning(self, state: dict, episode: dict) -> None:
        from mnemosyne.self_optimization import (
            ContextualBanditLearner,
            PolicyOutcome,
            SelfModelStore,
            tripwire_check,
        )

        if not self._collects(state, "routes"):
            return
        task = episode["task_class"]
        variants = self._policy_variants(task)
        records = state["policy"].setdefault("policy_outcomes", {})
        truth = [
            item for item in episode["signals"] if item["kind"] in {"verifier", "tests"}
        ]
        proxy = [item for item in episode["signals"] if item["kind"] == "acceptance"]
        receipts = [state["receipts"][key] for key in episode["receipt_ids"]]
        variant_id = (
            receipts[-1].get("policy_variant_id", variants[0].id)
            if receipts
            else variants[0].id
        )
        records.setdefault(
            episode["id"],
            {
                "episode_id": episode["id"],
                "task_class": task,
                "variant_id": variant_id,
                "reward": (episode["reward"] + 1) / 2,
                "true_reward": float(
                    sum(item["value"] * item["weight"] for item in truth) > 0
                )
                if truth
                else None,
                "proxy_reward": float(
                    sum(item["value"] * item["weight"] for item in proxy) > 0
                )
                if proxy
                else None,
            },
        )
        model = SelfModelStore()
        learner = ContextualBanditLearner(model)
        for key, row in records.items():
            if row["task_class"] == task:
                model.add_policy_outcome(
                    PolicyOutcome(
                        tenant_id=episode["tenant_id"],
                        variant_id=row["variant_id"],
                        reward=row["reward"],
                        context={"task_class": task},
                        id=key,
                    )
                )
        chosen = learner.choose_variant(
            episode["tenant_id"], variants, {"task_class": task}
        )
        state["policy"].setdefault("policy_candidates", {})[task] = {
            "variant": chosen.to_dict(),
            "status": "shadow",
            "outcome_count": len(model.policy_outcomes),
            "reason": "independent replay and protected verification required",
        }
        candidate = variants[1]
        for event in episode.get("tool_events", []):
            measured = event.get("policy_replay")
            if (
                event.get("source") != "tool"
                or event.get("name") != "policy_variant_verifier"
                or not isinstance(measured, dict)
            ):
                continue
            predicted = measured.get("predicted_lift")
            valid = (
                bool(event.get("output") or event.get("evidence"))
                and measured.get("policy_fingerprint") == digest(candidate.to_dict())
                and type(measured.get("baseline_success")) is bool
                and type(measured.get("candidate_success")) is bool
                and type(predicted) in {int, float}
                and math.isfinite(predicted)
                and -1 <= predicted <= 1
            )
            if valid:
                observed = float(measured["candidate_success"]) - float(
                    measured["baseline_success"]
                )
                state["policy"].setdefault("policy_replay_pairs", {})[episode["id"]] = {
                    "episode_id": episode["id"],
                    "task_class": task,
                    "variant_id": candidate.id,
                    "predicted_lift": predicted,
                    "observed_lift": observed,
                }
                for measured_variant, passed in (
                    (variants[0], measured["baseline_success"]),
                    (candidate, measured["candidate_success"]),
                ):
                    records[episode["id"] + ":" + measured_variant.id] = {
                        "episode_id": episode["id"],
                        "task_class": task,
                        "variant_id": measured_variant.id,
                        "reward": float(passed),
                        "true_reward": float(passed),
                        "proxy_reward": None,
                        "source": "external_policy_replay",
                    }
        rows = [
            row
            for row in records.values()
            if row["task_class"] == task
            and row["true_reward"] is not None
            and row["proxy_reward"] is not None
        ]
        if rows:
            tripwire = tripwire_check(
                min(
                    1.0,
                    len(
                        {
                            row["variant_id"]
                            for row in records.values()
                            if row["task_class"] == task
                        }
                    )
                    / 2,
                ),
                sum(row["proxy_reward"] for row in rows) / len(rows),
                sum(row["true_reward"] for row in rows) / len(rows),
            )
            state["policy"].setdefault("policy_tripwires", {})[task] = (
                tripwire.to_dict()
            )
            if not tripwire.passed:
                state["policy"].setdefault("active_policy_variants", {}).pop(task, None)

    def _evaluate_policy_learning(self, tenant: str, task: str) -> None:
        from mnemosyne.self_optimization import (
            SelfModelStore,
            ShadowPolicyOptimizer,
            evaluate_oq2_fidelity,
        )

        state = self.writer.read(tenant)
        if not self._enabled(state, "routes"):
            return
        pairs = [
            row
            for row in state["policy"].get("policy_replay_pairs", {}).values()
            if row["task_class"] == task
        ]
        report = evaluate_oq2_fidelity(
            [(row["predicted_lift"], row["observed_lift"]) for row in pairs]
        )
        tripwire = state["policy"].get("policy_tripwires", {}).get(task, {})
        if not report.authorized_to_trust or not tripwire.get("passed"):
            return
        cases = [
            case
            for case in getattr(self, "protected_cases", [])
            if case.protected
            and case.origin in {"curated", "genuine"}
            and case.mode == "active"
        ]
        if not cases:
            return
        model = SelfModelStore()
        for row in pairs:
            model.record_replay_pair(
                tenant, row["variant_id"], row["predicted_lift"], row["observed_lift"]
            )
        candidate = self._policy_variants(task)[1]
        facade = _PolicyEvaluationEngine(self.engine)
        gate = ShadowPolicyOptimizer(
            facade, cases, self_model=model, require_ignition=True
        ).evaluate_variant(tenant, candidate)

        def persist(current):
            if not self._enabled(current, "routes"):
                return
            current["policy"].setdefault("policy_evaluations", {})[task] = {
                "oq2": report.to_dict(),
                "gate": gate.to_dict(),
            }
            if gate.promoted:
                current["policy"].setdefault("active_policy_variants", {})[task] = (
                    candidate.to_dict()
                )

        self.writer.apply(tenant, "evaluate_policy_variant", persist)

    def _breaker(self, state: dict, episode: dict) -> None:
        if not state["policy"].get(
            "enabled", getattr(self.engine.policy, "learning_enabled", True)
        ) or state["policy"].get("frozen", False):
            return
        rows = sorted(
            [
                row
                for row in state["episodes"].values()
                if row["status"] == "resolved"
                and row["task_class"] == episode["task_class"]
            ],
            key=lambda row: (row["created_at"], row["id"]),
        )
        checkpoints = state["policy"].setdefault("last_good", {})
        task = episode["task_class"]
        if task not in checkpoints and episode.get("reward", 0) > 0:
            checkpoints[task] = self._behavior_checkpoint(state, task)
        if len(rows) < 40:
            return
        previous = sum(row["reward"] > 0 for row in rows[-40:-20]) / 20
        current = sum(row["reward"] > 0 for row in rows[-20:]) / 20
        previous_interval = wilson_interval(previous * 20, 20)
        current_interval = wilson_interval(current * 20, 20)
        if previous - current >= 0.15 and previous_interval.low > current_interval.high:
            state["policy"]["frozen"] = True
            state["policy"]["breaker"] = {
                "task_class": episode["task_class"],
                "before": previous,
                "after": current,
            }
            checkpoint = checkpoints.get(task, {})
            for key, value in checkpoint.get("policy", {}).items():
                if value is None:
                    state["policy"].setdefault(key, {}).pop(task, None)
                else:
                    state["policy"].setdefault(key, {})[task] = copy.deepcopy(value)
            saved = checkpoint.get("artifacts", {})
            for artifact in state["artifacts"].values():
                if (
                    artifact["task_class"] == episode["task_class"]
                    and not artifact.get("pinned")
                    and not artifact.get("locked")
                    and artifact["state"] in {"active", "labile"}
                ):
                    previous_state = saved.get(artifact["id"])
                    artifact["state"] = (
                        previous_state
                        if previous_state
                        in {"active", "labile", "probation", "demoted"}
                        else "demoted"
                    )
            state["policy"]["breaker"]["restored_last_good"] = bool(checkpoint)
        elif current >= previous:
            checkpoints[task] = self._behavior_checkpoint(state, task)

    @staticmethod
    def _behavior_checkpoint(state: dict, task: str) -> dict:
        return {
            "policy": {
                key: copy.deepcopy(state["policy"].get(key, {}).get(task))
                for key in ("routes", "active_policy_variants")
            },
            "artifacts": {
                item["id"]: item["state"]
                for item in state["artifacts"].values()
                if item["task_class"] == task
                and item["state"] not in {"retired", "archived", "rejected"}
            },
        }

    def expire(self, tenant_id: str) -> None:
        for episode in self.writer.read(tenant_id)["episodes"].values():
            if (
                episode["status"] == "open"
                and datetime.fromisoformat(episode["expires_at"]) <= now()
            ):
                self.resolve(tenant_id, episode["id"], expired=True)

    def end_session(self, tenant_id: str, session_id: str) -> dict:
        for episode in self.writer.read(tenant_id)["episodes"].values():
            if episode["session_id"] == session_id and episode["status"] == "open":
                self.resolve(tenant_id, episode["id"], expired=True)
        return self.status(tenant_id)

    def explain(self, tenant_id: str, target: str) -> dict:
        state = self.writer.read(tenant_id)
        return {
            "target": target,
            "artifact": state["artifacts"].get(target),
            "credit": [
                row for row in state["credit"].values() if row["target_id"] == target
            ],
            "audit": [
                row
                for row in self.writer.store.history(tenant_id)
                if any(change["key"] == target for change in row["changes"])
            ],
        }

    def set_import_state(
        self, tenant_id: str, skill_id: str, revision: int, state: str,
        *, approve_effects: bool = False,
    ) -> dict:
        """Apply an authenticated operator request at the native lifecycle owner."""
        from mnemosyne.skills import STATES

        if state not in STATES:
            raise ValueError(f"state is one of {sorted(STATES)}")
        desired = "candidate" if state == "draft" else state

        def change(current):
            artifacts = [item for item in current["artifacts"].values()
                         if item.get("source_skill_id") == skill_id
                         and item.get("source_skill_revision") == revision]
            if not artifacts:
                raise ValueError("native skill revision not found")
            for item in artifacts:
                if item.get("state") in {"retired", "archived", "rejected"} and desired != item["state"]:
                    raise ValueError("terminal native revisions cannot be reactivated")
                if approve_effects:
                    item["approved"] = True
                if desired in {"active", "labile"}:
                    from .sleep import activation_supported
                    if not activation_supported(self, current, item):
                        raise ValueError("activation requires verified native probation and control outcomes")
                item["state"] = desired
            return {"skill_id": skill_id, "revision": revision, "state": state}

        result = self.writer.apply(tenant_id, "skill_state", change)
        self._sync_library_revision_states(tenant_id)
        return self.skill_store.status(skill_id, revision) if self.skill_store else result

    def rollback(self, tenant_id: str, audit_id: str) -> dict:
        result = self.writer.rollback(tenant_id, audit_id)
        self._sync_library_revision_states(tenant_id)
        return result

    def retire_artifact(self, tenant_id: str, target: str) -> dict:
        def retire(state):
            artifact = state["artifacts"][target]
            if artifact["state"] not in {"retired", "archived", "rejected"}:
                artifact["state"] = "retired"
            return artifact

        result = self.writer.apply(tenant_id, "retire_artifact", retire)
        self._sync_library_revision_states(tenant_id)
        return result

    def pin(self, tenant_id: str, target: str, pinned: bool = True) -> dict:
        def change(state):
            state["artifacts"][target]["pinned"] = bool(pinned)
            return state["artifacts"][target]

        return self.writer.apply(tenant_id, "pin", change)

    def lock(self, tenant_id: str, target: str, locked: bool = True) -> dict:
        def change(state):
            state["artifacts"][target]["locked"] = bool(locked)
            return state["artifacts"][target]

        return self.writer.apply(tenant_id, "lock", change)

    def erase(self, tenant_id: str, cid: str) -> dict:
        erasure_terms = [cid, "legacy_learning"]

        def scrub(state):
            affected = {
                row["id"]
                for row in state["episodes"].values()
                if cid in row.get("source_cids", [])
                or cid in str(row.get("legacy_trajectory", {}))
            }
            for row in state["receipts"].values():
                if cid in row.get("source_cids", []) or any(
                    item["item_id"] == cid
                    for item in row.get("eligible_targets", row["items"])
                ):
                    erasure_terms.append(row["id"])
                    row["query"] = ""
                    row["items"] = [
                        item for item in row["items"] if item["item_id"] != cid
                    ]
                    row["eligible_targets"] = [
                        item
                        for item in row.get("eligible_targets", [])
                        if item["item_id"] != cid
                    ]
                    row["source_cids"] = [
                        item for item in row.get("source_cids", []) if item != cid
                    ]
                    affected.update(
                        e["id"]
                        for e in state["episodes"].values()
                        if row["id"] in e["receipt_ids"]
                    )
            # A source turn also owns the query stored in its decision receipts.
            for episode_id in affected:
                for receipt_id in state["episodes"][episode_id]["receipt_ids"]:
                    receipt = state["receipts"][receipt_id]
                    receipt["query"] = ""
                    erasure_terms.append(receipt_id)
            erasure_terms.extend(affected)
            for episode_id in affected:
                row = state["episodes"][episode_id]
                keep = {"id", "tenant_id", "user_id", "session_id", "task_class", "created_at",
                        "expires_at", "turn_index", "receipt_ids", "prediction", "reward", "rpe"}
                for name in list(row):
                    if name not in keep:
                        row.pop(name)
                row["used_skills"] = []
                row["used_lessons"] = []
                row["cited_cids"] = []
                row.update(
                    status="erased",
                    source_cids=[],
                    signals=[],
                    tool_events=[],
                    user_text="",
                )
            for key, row in list(state["credit"].items()):
                if row["episode_id"] in affected or row["target_id"] == cid:
                    del state["credit"][key]
            for row in state["artifacts"].values():
                if cid in row.get("source_cids", []) or affected.intersection(
                    row["source_episode_ids"]
                ):
                    erasure_terms.append(row["id"])
                    keep = {"id", "tenant_id", "user_id", "kind", "task_class", "revision",
                            "parent_revision", "origin", "state", "pinned", "locked", "created_at",
                            "source_skill_id", "source_skill_revision", "source_library_skill_id",
                            "source_library_parent_revision", "source_library_parent_artifact"}
                    for name in list(row):
                        if name not in keep:
                            row.pop(name)
                    row["erased"] = True
                    row["goal"] = ""
                    row["scope"] = row["task_class"]
                    row["explanation"] = ""
                    row.update(
                        state=row["state"] if row["state"] in {"retired", "archived", "rejected"} else "candidate",
                        source_cids=[],
                        source_episode_ids=[],
                        explanation_sources=[],
                        content="",
                        steps=[],
                        gate_passed=False,
                    )
            from .candidates import erase_derived_policy

            erasure_terms.extend(erase_derived_policy(state, cid, affected))
            for key, event in list(state["policy"].get("skill_outbox", {}).items()):
                if event["episode_id"] in affected:
                    del state["policy"]["skill_outbox"][key]
            for episode_id in affected:
                state["policy"].setdefault("skill_erasure_outbox", {})[episode_id] = (
                    True
                )
            for key in ("policy_outcomes", "policy_replay_pairs"):
                if key not in state["policy"]:
                    continue
                values = state["policy"][key]
                if isinstance(values, list):
                    state["policy"][key] = [
                        row for row in values if row.get("episode_id") not in affected
                    ]
                elif isinstance(values, dict):
                    state["policy"][key] = {
                        name: row
                        for name, row in values.items()
                        if row.get("episode_id") not in affected
                    }
            for key in ("last_good", "active_policy_variants", "policy_gate_evidence"):
                state["policy"].pop(key, None)
            for tracking in state["policy"].get("host_consolidation", {}).values():
                removed = {"failure:" + key for key in affected}
                tracking["completed"] = [key for key in tracking.get("completed", []) if key not in removed]
                pending = tracking.get("pending")
                if pending:
                    pending["triggers"] = [key for key in pending.get("triggers", []) if key not in removed]
                    if not pending["triggers"]:
                        tracking.pop("pending", None)
            # Rebuild sufficient statistics without reissuing credit or learning again.
            state["stats"] = {}
            for row in sorted(
                state["episodes"].values(), key=lambda e: (e["created_at"], e["id"])
            ):
                if row["status"] == "resolved" and row.get("learning_collected", True):
                    self._credit(state, row, rebuild=True)
            for credit_id, credit in list(state["credit"].items()):
                key = stat_key(
                    credit["target_kind"],
                    credit["target_id"],
                    credit["revision"],
                    credit["task_class"],
                )
                row = state["stats"].get(key)
                bound = (
                    contingency_lower_bound(
                        row["served_successes"],
                        row["served_n"],
                        row["control_successes"],
                        row["control_n"],
                    )
                    if row
                    else None
                )
                if bound is None or bound <= 0:
                    del state["credit"][credit_id]
                    continue
                credit.update(
                    contingency_lb=bound,
                    served_n=row["served_n"],
                    control_n=row["control_n"],
                )
                row["utility"] = max(
                    0.8, min(1.2, row.get("utility", 1) + credit.get("step", 0))
                )
                if state["episodes"][credit["episode_id"]]["reward"] > 0:
                    row["importance"] += (
                        state["episodes"][credit["episode_id"]]["reward"] + 1
                    ) / 2
            from .sleep import _homeostasis, activation_supported

            erasure_targets = {
                item["item_id"]
                for episode_id in affected
                for receipt_id in state["episodes"][episode_id].get("receipt_ids", [])
                for item in state["receipts"].get(receipt_id, {}).get("items", [])
            }
            for artifact in state["artifacts"].values():
                if artifact["id"] in erasure_targets and artifact["state"] in {"active", "labile"} and not activation_supported(self, state, artifact):
                    artifact["state"] = "probation"
            _homeostasis(state)
            state["policy"].pop("routes", None)
            state["policy"].pop("route_daily", None)
            state["policy"].pop("calibration_bins", None)
            for defect in state["defects"].values():
                if any(term in str(defect) for term in erasure_terms):
                    defect.pop("before", None)
                    defect.pop("attempted", None)
            return {"erased": True, "episodes_retracted": len(affected)}

        result = self.writer.apply(
            tenant_id, "erasure", scrub, erasure_terms=erasure_terms
        )
        self.flush_skill_erasures(tenant_id)
        skill_store = self.skill_store or getattr(
            self.engine, "_learning_skill_store", None
        )
        if skill_store is not None:
            skill_store.retract_source(cid)
        self._sync_library_revision_states(tenant_id)
        profile_erasure = getattr(self.engine, "_learning_profile_erasure", None)
        if profile_erasure is not None:
            profile_erasure(tenant_id, cid)
        return result

    def flush_skill_erasures(self, tenant_id: str) -> None:
        store = self.skill_store or getattr(self.engine, "_learning_skill_store", None)
        if store is None:
            return
        for episode_id in self.writer.read(tenant_id)["policy"].get(
            "skill_erasure_outbox", {}
        ):
            store.retract_outcome(episode_id)

            def acknowledge(state):
                state["policy"].get("skill_erasure_outbox", {}).pop(episode_id, None)

            self.writer.apply(tenant_id, "skill_erasure_delivered", acknowledge)

    def _sync_library_revision_states(self, tenant_id: str) -> None:
        store = self.skill_store or getattr(self.engine, "_learning_skill_store", None)
        if store is None:
            return
        import json

        with self.writer.store.transaction(tenant_id) as (state, _):
            groups = {}
            for artifact in state["artifacts"].values():
                skill_id, revision = artifact.get("source_skill_id"), artifact.get("source_skill_revision")
                if skill_id and revision is not None:
                    groups.setdefault((skill_id, revision), []).append(artifact)
            # A rollback can remove a native revision entirely. Keep its append-only
            # library record, but revoke the projection that no longer has an owner.
            for row in store._rows("SELECT * FROM skill_revisions"):
                origin = json.loads(row.get("memory") or "{}")
                if origin.get("tenant") == tenant_id and store._learning_managed(row):
                    groups.setdefault((row["skill_id"], row["revision"]), [])
            for (skill_id, revision), artifacts in groups.items():
                try:
                    library_row = store._skill(skill_id, revision)
                except ValueError:
                    continue
                owner = json.loads(library_row.get("memory") or "{}")
                if owner.get("tenant") != tenant_id or any(
                    item.get("tenant_id") != tenant_id or item.get("user_id") != owner.get("user")
                    for item in artifacts
                ):
                    continue
                identities = {(item["id"], item["revision"]) for item in artifacts}
                outcomes = []
                for episode in state["episodes"].values():
                    if (episode.get("status") != "resolved"
                            or not episode.get("learning_collected", True)
                            or not episode.get("learning_components", {}).get("skills", True)
                            or not any(
                        signal.get("kind") in {"verifier", "tests", "critic", "rating"}
                        for signal in episode.get("signals", [])
                    )):
                        continue
                    served = {
                        (item["item_id"], item["revision"])
                        for receipt_id in episode.get("receipt_ids", [])
                        for item in state["receipts"].get(receipt_id, {}).get("items", [])
                    }
                    if identities.intersection(served):
                        outcomes.append({"episode_id": episode["id"],
                                         "probability": (episode["reward"] + 1) / 2})
                store.sync_learning_revision(
                    skill_id, revision, artifacts, outcomes=outcomes,
                )

    def _flush_skill_revision_outbox(self, tenant_id: str) -> None:
        if self.skill_store is None:
            return
        snapshot = self.writer.read(tenant_id)
        for artifact_id in snapshot["policy"].get("skill_revision_outbox", {}):

            def mirror(state):
                if not self._enabled(state, "skills"):
                    return
                job = state["policy"].get("skill_revision_outbox", {}).get(artifact_id)
                if job is None:
                    return
                artifact = state["artifacts"].get(artifact_id)
                if (
                    not artifact
                    or artifact["state"] != "active"
                    or artifact.get("locked")
                    or artifact.get("pinned")
                ):
                    return
                parent_revision = job.get("parent_revision")
                if parent_revision is None:
                    parent = state["artifacts"].get(job.get("parent_artifact_id"), {})
                    parent_revision = parent.get("source_skill_revision")
                if parent_revision is None:
                    job["pending_reason"] = "library_parent_not_mirrored"
                    return
                candidate = {
                    **artifact,
                    "_library_statistics": state["stats"].get(
                        stat_key(
                            artifact["kind"],
                            artifact_id,
                            artifact["revision"],
                            artifact["task_class"],
                        ),
                        {},
                    ),
                }
                try:
                    mirrored = self.skill_store.mirror_learned_revision(
                        job["skill_id"], parent_revision, candidate
                    )
                except ValueError as error:
                    job["pending_reason"] = str(error)
                    return
                artifact["source_skill_id"] = mirrored["skill_id"]
                artifact["source_skill_revision"] = mirrored["revision"]
                state["policy"]["skill_revision_outbox"].pop(artifact_id)

            self.writer.apply(tenant_id, "mirror_skill_revision", mirror)

    def consolidate(self, tenant_id: str) -> dict:
        from .sleep import consolidate

        result = consolidate(self, tenant_id)
        self._flush_skill_revision_outbox(tenant_id)
        self._sync_library_revision_states(tenant_id)
        from .monitors import run_monitors

        result["monitors"] = run_monitors(self.writer, tenant_id)
        return result
