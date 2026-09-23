"""Read-only evaluation through MaleCNS reflex and deterministic safety layers."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from .multitask_contract import PolicyIntent, ScenarioManifest, Skill
from .multitask_env import MultiTaskEnv
from .multitask_metrics import EpisodeTelemetry
from .multitask_policy import (
    PolicyState,
    ProjectionResult,
    SafetyArbiter,
    SafetyProjector,
)
from .multitask_reflex import ReflexDecision, ReflexEvidence
from .training import AcceptanceReport, MultiTaskAcceptance


class _UnavailableReflex:
    """Fail-closed bridge used when a CLI run has no live connectome path."""

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, observation) -> ReflexDecision:
        self.calls += 1
        return ReflexDecision(
            PolicyIntent(
                Skill.YIELD_RETURN_LAND,
                (0.0, 0.0, 0.0, 0.0),
                1.0,
                0.2,
            ),
            ReflexEvidence("unavailable", 0, 0, 0, self.calls, 0.0),
        )


@dataclass(frozen=True)
class EvaluationEvidence:
    metrics: Mapping[str, float]
    missing_evidence: tuple[str, ...]
    admission: AcceptanceReport
    telemetry: EpisodeTelemetry
    episodes: tuple[Mapping[str, object], ...]
    reflex_calls: int
    local_decisions: int
    male_cns_backend: str
    male_cns_fallbacks: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        object.__setattr__(
            self,
            "episodes",
            tuple(MappingProxyType(dict(episode)) for episode in self.episodes),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "metrics": dict(self.metrics),
            "missing_evidence": list(self.missing_evidence),
            "admission": {
                "passed": self.admission.passed,
                "failures": list(self.admission.failures),
            },
            "telemetry": self.telemetry.to_dict(),
            "episodes": [dict(episode) for episode in self.episodes],
            "reflex_calls": self.reflex_calls,
            "local_decisions": self.local_decisions,
            "male_cns_backend": self.male_cns_backend,
            "male_cns_fallbacks": self.male_cns_fallbacks,
            "central_control_commands": int(
                self.metrics.get("central_control_commands", 0.0)
            ),
        }


def _combine_telemetry(items: Sequence[EpisodeTelemetry]) -> EpisodeTelemetry:
    disturbance_names = sorted(
        {name for item in items for name in item.disturbance_injections}
    )
    injections = {
        name: sum(item.disturbance_injections.get(name, 0) for item in items)
        for name in disturbance_names
    }
    minimums = {
        name: min(
            (
                item.disturbance_minimums[name]
                for item in items
                if name in item.disturbance_minimums
            ),
            default=0.0,
        )
        for name in disturbance_names
    }
    maximums = {
        name: max(
            (
                item.disturbance_maximums[name]
                for item in items
                if name in item.disturbance_maximums
            ),
            default=0.0,
        )
        for name in disturbance_names
    }
    return EpisodeTelemetry(
        tracking_squared_error_sum=sum(
            item.tracking_squared_error_sum for item in items
        ),
        tracking_samples=sum(item.tracking_samples for item in items),
        tracking_lost_steps=sum(item.tracking_lost_steps for item in items),
        union_coverage_cells=sum(item.union_coverage_cells for item in items),
        duplicate_coverage_visits=sum(
            item.duplicate_coverage_visits for item in items
        ),
        coverage_visits=sum(item.coverage_visits for item in items),
        formation_squared_error_sum=sum(
            item.formation_squared_error_sum for item in items
        ),
        formation_samples=sum(item.formation_samples for item in items),
        gate_crossings=sum(item.gate_crossings for item in items),
        gate_contacts=sum(item.gate_contacts for item in items),
        safety_failures=tuple(
            failure for item in items for failure in item.safety_failures
        ),
        safety_overrides=sum(item.safety_overrides for item in items),
        completed_evidence=tuple(
            evidence for item in items for evidence in item.completed_evidence
        ),
        central_control_commands=sum(
            item.central_control_commands for item in items
        ),
        disturbance_injections=injections,
        disturbance_minimums=minimums,
        disturbance_maximums=maximums,
    )


def _hold_result(reason: str) -> ProjectionResult:
    return ProjectionResult(
        PolicyIntent(
            Skill.YIELD_RETURN_LAND,
            (0.0, 0.0, 0.0, 0.0),
            1.0,
            0.2,
        ),
        True,
        reason,
    )


def evaluate_manifests(
    actor,
    manifests: Sequence[ScenarioManifest],
    *,
    reflex_factory: Callable[[int, ScenarioManifest], object] | None = None,
    max_steps: int = 80,
) -> EvaluationEvidence:
    if not manifests:
        raise ValueError("evaluation requires at least one manifest")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
        raise ValueError("max_steps must be positive")
    factory = reflex_factory or (lambda _vehicle_id, _manifest: _UnavailableReflex())
    episode_reports: list[dict[str, object]] = []
    episode_telemetry: list[EpisodeTelemetry] = []
    reflex_calls = 0
    local_decisions = 0
    fallback_calls = 0
    backend_sources: set[str] = set()
    reflex_coverage_failed = False

    for scenario in manifests:
        env = MultiTaskEnv(scenario, max_steps=max_steps)
        observations, _reset_info = env.reset(seed=scenario.seed)
        states = {
            vehicle_id: PolicyState.zeros(64) for vehicle_id in observations
        }
        bridges = {
            vehicle_id: factory(vehicle_id, scenario) for vehicle_id in observations
        }
        arbiters = {
            vehicle_id: SafetyArbiter(SafetyProjector())
            for vehicle_id in observations
        }
        episode_reward = 0.0
        last_info: dict[str, object] = {}
        step_count = 0
        while step_count < max_steps:
            actions: dict[int, PolicyIntent] = {}
            for vehicle_id in sorted(observations):
                local_decisions += 1
                try:
                    local = env.local_observation(vehicle_id)
                except ValueError:
                    reflex_coverage_failed = True
                    final = _hold_result("stale-observation")
                    env.record_safety_override(final.reason)
                    actions[vehicle_id] = final.intent
                    continue

                decision = bridges[vehicle_id].evaluate(local)
                reflex_calls += 1
                backend_sources.add(decision.evidence.source)
                fallback_calls += decision.evidence.fallback_calls
                arbiter = arbiters[vehicle_id]
                try:
                    final = arbiter.preflight(
                        env.safety_snapshot(vehicle_id),
                        reflex_override=decision.intent,
                    )
                    if final is None:
                        skill, motion, confidence, next_state = actor.act(
                            local, states[vehicle_id]
                        )
                        states[vehicle_id] = next_state
                        proposed = PolicyIntent(skill, motion, confidence, 0.2)
                        final = arbiter.resolve(
                            proposed,
                            env.safety_snapshot(vehicle_id),
                            now=step_count * env.dt,
                        )
                except (TypeError, ValueError, RuntimeError):
                    final = _hold_result("invalid-evaluation-input")
                if final.overrode:
                    env.record_safety_override(final.reason)
                actions[vehicle_id] = final.intent
            observations, rewards, terminated, truncated, last_info = env.step(actions)
            episode_reward += sum(rewards.values())
            states = {
                vehicle_id: states.get(vehicle_id, PolicyState.zeros(64))
                for vehicle_id in observations
            }
            step_count += 1
            if terminated or truncated:
                break
        telemetry = env.telemetry()
        episode_telemetry.append(telemetry)
        episode_reports.append(
            {
                "seed": scenario.seed,
                "manifest_digest": scenario.digest,
                "active_skills": [skill.value for skill in scenario.active_skills],
                "fleet_size": scenario.fleet_size,
                "steps": step_count,
                "reward": episode_reward,
                "safety_failure": last_info.get("safety_failure"),
                "completed_evidence": list(telemetry.completed_evidence),
                "telemetry_digest": telemetry.digest,
            }
        )

    telemetry = _combine_telemetry(episode_telemetry)
    metrics: dict[str, float] = {
        "episodes": float(len(episode_reports)),
        "full_scale_episodes": float(
            sum(report["fleet_size"] == 100 for report in episode_reports)
        ),
        "collisions": float(Counter(telemetry.safety_failures)["collision"]),
        "geofence_violations": float(
            Counter(telemetry.safety_failures)["geofence"]
        ),
        "return_reserve_violations": float(
            Counter(telemetry.safety_failures)["return-reserve"]
        ),
        "central_control_commands": float(telemetry.central_control_commands),
        "gate_contacts": float(telemetry.gate_contacts),
    }

    skill_episode_counts = Counter(
        skill
        for report in episode_reports
        for skill in report["active_skills"]
    )
    prefix = {
        Skill.NAVIGATE_EXIT.value: "exit:",
        Skill.TRACK_TARGET.value: "track:",
        Skill.SEARCH_COVER.value: "search:",
        Skill.FORMATION_RALLY.value: "formation:",
        Skill.GATE_COURSE.value: "gate:",
        Skill.YIELD_RETURN_LAND.value: "return:",
    }

    def success_fraction(skill_name: str) -> float | None:
        total = skill_episode_counts[skill_name]
        if total == 0:
            return None
        successes = sum(
            skill_name in report["active_skills"]
            and any(
                str(item).startswith(prefix[skill_name])
                for item in report["completed_evidence"]
            )
            for report in episode_reports
        )
        return successes / total

    exit_success = success_fraction(Skill.NAVIGATE_EXIT.value)
    tracking_success = success_fraction(Skill.TRACK_TARGET.value)
    gate_success = success_fraction(Skill.GATE_COURSE.value)
    if exit_success is not None:
        metrics["exit_success"] = exit_success
    if tracking_success is not None:
        metrics["tracking_success"] = tracking_success
    if gate_success is not None:
        metrics["gate_success"] = gate_success
    if telemetry.tracking_samples:
        metrics["tracking_rmse_m"] = math.sqrt(
            telemetry.tracking_squared_error_sum / telemetry.tracking_samples
        )
        metrics["tracking_loss_fraction"] = (
            telemetry.tracking_lost_steps / telemetry.tracking_samples
        )
    search_episodes = skill_episode_counts[Skill.SEARCH_COVER.value]
    if search_episodes and telemetry.coverage_visits:
        metrics["search_coverage"] = min(
            1.0, telemetry.union_coverage_cells / (16.0 * search_episodes)
        )
        metrics["duplicate_coverage"] = (
            telemetry.duplicate_coverage_visits / telemetry.coverage_visits
        )
    if telemetry.formation_samples:
        metrics["formation_rmse_m"] = math.sqrt(
            telemetry.formation_squared_error_sum / telemetry.formation_samples
        )
    compound_reports = [
        report for report in episode_reports if len(report["active_skills"]) > 1
    ]
    if compound_reports:
        compound_successes = 0
        for report in compound_reports:
            evidence = report["completed_evidence"]
            if all(
                any(str(item).startswith(prefix[skill]) for item in evidence)
                for skill in report["active_skills"]
            ):
                compound_successes += 1
        metrics["compound_success"] = compound_successes / len(compound_reports)

    acceptance = MultiTaskAcceptance.spec_defaults()
    required = {
        *(key for key, _value in acceptance.minimums),
        *(key for key, _value in acceptance.maximums),
        *acceptance.zeros,
    }
    missing = required - set(metrics)
    if (
        backend_sources != {"malecns-v1.0-live"}
        or fallback_calls != 0
        or reflex_coverage_failed
        or reflex_calls != local_decisions
    ):
        missing.add("male_cns_backend")
    base_admission = acceptance.evaluate(metrics)
    failures = tuple(sorted(set(base_admission.failures) | missing))
    admission = AcceptanceReport(not failures, failures)
    backend = ",".join(sorted(backend_sources)) if backend_sources else "unavailable"
    return EvaluationEvidence(
        metrics=metrics,
        missing_evidence=tuple(sorted(missing)),
        admission=admission,
        telemetry=telemetry,
        episodes=tuple(episode_reports),
        reflex_calls=reflex_calls,
        local_decisions=local_decisions,
        male_cns_backend=backend,
        male_cns_fallbacks=fallback_calls,
    )
