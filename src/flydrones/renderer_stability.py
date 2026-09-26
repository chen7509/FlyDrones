"""Immutable schedule and fail-closed scoring for paired Gazebo renderer trials."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any


@dataclass(frozen=True)
class CampaignTrial:
    name: str
    pair_id: int
    pair_position: int
    renderer_profile: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def campaign_schedule() -> tuple[CampaignTrial, ...]:
    profiles = (
        ("default", "d3d12-nvidia"),
        ("d3d12-nvidia", "default"),
        ("default", "d3d12-nvidia"),
        ("d3d12-nvidia", "default"),
        ("default", "d3d12-nvidia"),
    )
    return tuple(
        CampaignTrial(
            name=f"renderer-pair-{pair_id}-{position}-{profile}",
            pair_id=pair_id,
            pair_position=position,
            renderer_profile=profile,
        )
        for pair_id, pair in enumerate(profiles, start=1)
        for position, profile in enumerate(pair, start=1)
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def score_renderer_trial(manifest: Mapping[str, object], summary: Mapping[str, object]) -> dict[str, object]:
    """Score one preserved trial without masking missing or malformed evidence."""
    failures: list[str] = []
    name = str(manifest.get("name", summary.get("name", "unknown")))
    profile = str(_mapping(manifest.get("renderer")).get("requested_profile", "unknown"))

    if manifest.get("schema") != "flydrones-vio-stress-trial-v2":
        failures.append("invalid_trial_manifest_schema")
    if summary.get("schema") != "flydrones-vio-stress-summary-v5":
        failures.append("invalid_trial_summary_schema")
    if manifest.get("fleet_size") != 5 or summary.get("fleet_size") != 5:
        failures.append("fleet_size_not_5")
    if manifest.get("name") != summary.get("name"):
        failures.append("manifest_summary_name_mismatch")
    if manifest.get("evidence_accepted") is not True:
        failures.append("manifest_evidence_rejected")
    if not _mapping(manifest.get("raw_artifact_sha256")):
        failures.append("raw_artifact_hashes_missing")

    attestation = _mapping(_mapping(manifest.get("renderer")).get("attestation"))
    if (
        attestation.get("accepted") is not True
        or attestation.get("requested_profile") != profile
    ):
        failures.append("renderer_attestation_rejected")

    workers = summary.get("workers")
    workers = workers if isinstance(workers, list) else []
    mission_count = sum(worker.get("mission_accepted") is True for worker in workers
                        if isinstance(worker, Mapping))
    landing_count = sum(worker.get("landed") is True for worker in workers
                        if isinstance(worker, Mapping))
    if len(workers) != 5 or mission_count != 5:
        failures.append("mission_count_not_5")
    if len(workers) != 5 or landing_count != 5:
        failures.append("landing_count_not_5")
    if any(
        bool(worker.get("state_health_failures")) or bool(worker.get("fail_closed_land"))
        for worker in workers if isinstance(worker, Mapping)
    ):
        failures.append("normal_run_vio_gate_triggered")

    if not (
        summary.get("geometry_separation_check_pass") is True
        and summary.get("geometry_forest_clearance_check_pass") is True
    ):
        failures.append("safety_geometry_failed")

    health = _mapping(summary.get("external_vision_health_by_vehicle"))
    if len(health) != 5 or any(
        _mapping(health.get(str(vehicle_id))).get("accepted") is not True
        for vehicle_id in range(5)
    ):
        failures.append("per_vehicle_external_vision_evidence_rejected")

    post_gnss = _mapping(summary.get("post_gnss_evidence_by_vehicle"))
    if len(post_gnss) != 5 or any(
        _mapping(post_gnss.get(str(vehicle_id))).get("accepted") is not True
        for vehicle_id in range(5)
    ):
        failures.append("per_vehicle_post_gnss_evidence_rejected")
    if len(workers) != 5 or any(
        not isinstance(worker, Mapping) or worker.get("gnss_disable_injected") is not True
        for worker in workers
    ):
        failures.append("per_vehicle_gnss_disable_not_injected")

    runtime = _mapping(summary.get("runtime"))
    if runtime.get("accepted") is not True or runtime.get("startup_reliability_pass") is not True:
        failures.append("runtime_or_startup_evidence_rejected")
    raw = _mapping(runtime.get("raw_vio_by_vehicle"))
    raw_p99: list[float] = []
    raw_max: list[float] = []
    for vehicle_id in range(5):
        vehicle = _mapping(raw.get(str(vehicle_id)))
        steady = _mapping(vehicle.get("steady_state"))
        p99 = _finite_number(steady.get("p99_ms"))
        maximum = _finite_number(steady.get("max_ms"))
        if vehicle.get("steady_state_valid") is not True or p99 is None or maximum is None:
            failures.append("raw_vio_steady_state_missing")
            break
        raw_p99.append(p99)
        raw_max.append(maximum)

    clock = _mapping(runtime.get("clock"))
    clock_steady = _mapping(clock.get("steady_state"))
    clock_p99 = _finite_number(clock_steady.get("p99_ms"))
    clock_max = _finite_number(clock_steady.get("max_ms"))
    if clock.get("steady_state_valid") is not True or clock_p99 is None or clock_max is None:
        failures.append("clock_steady_state_missing")
    rtf = _finite_number(_mapping(runtime.get("rtf")).get("steady_state"))
    if rtf is None:
        failures.append("steady_state_rtf_missing")

    worst_raw_p99 = max(raw_p99) if len(raw_p99) == 5 else None
    worst_raw_max = max(raw_max) if len(raw_max) == 5 else None
    tail_p99 = max(worst_raw_p99, clock_p99) if worst_raw_p99 is not None and clock_p99 is not None else None
    tail_max = max(worst_raw_max, clock_max) if worst_raw_max is not None and clock_max is not None else None
    if worst_raw_max is not None and worst_raw_max >= 250.0:
        failures.append("raw_vio_max_not_below_250_ms")
    if clock_max is not None and clock_max >= 250.0:
        failures.append("clock_max_not_below_250_ms")
    if tail_p99 is not None and tail_p99 > 100.0:
        failures.append("tail_p99_above_100_ms")
    if rtf is not None and rtf < 0.95:
        failures.append("rtf_below_0_95")
    if summary.get("trial_cleanup_verified") is not True:
        failures.append("cleanup_not_verified")
    if summary.get("operational_continuity_pass") is not True:
        failures.append("operational_continuity_failed")

    return {
        "name": name,
        "renderer_profile": profile,
        "pair": dict(_mapping(manifest.get("pair"))),
        "passed": not failures,
        "failures": failures,
        "metrics": {
            "mission_count": mission_count,
            "landing_count": landing_count,
            "raw_vio_p99_max_ms": worst_raw_p99,
            "raw_vio_max_ms": worst_raw_max,
            "clock_p99_ms": clock_p99,
            "clock_max_ms": clock_max,
            "tail_p99_ms": tail_p99,
            "tail_max_ms": tail_max,
            "rtf": rtf,
        },
    }


def _frozen_value(manifest: Mapping[str, object]) -> dict[str, object]:
    return {
        key: manifest.get(key)
        for key in (
            "seed",
            "campaign_id",
            "repository_revision",
            "controller_revision",
            "px4_revision",
            "frozen_hashes",
            "software_versions",
        )
    }


def _validate_campaign(
    trials: Sequence[tuple[Mapping[str, object], Mapping[str, object]]],
) -> list[str]:
    failures: list[str] = []
    expected = campaign_schedule()
    if len(trials) != len(expected):
        failures.append(f"expected_10_trials_got_{len(trials)}")
    names = [str(manifest.get("name", "")) for manifest, _summary in trials]
    if len(names) != len(set(names)):
        failures.append("duplicate_trial_names")
    baseline = _frozen_value(trials[0][0]) if trials else None
    for index, (manifest, summary) in enumerate(trials):
        if index >= len(expected):
            failures.append(f"unexpected_trial_at_position_{index + 1}")
            continue
        scheduled = expected[index]
        renderer = _mapping(manifest.get("renderer"))
        pair = _mapping(manifest.get("pair"))
        if manifest.get("name") != scheduled.name:
            failures.append(f"trial_{index + 1}_name_or_order_mismatch")
        if renderer.get("requested_profile") != scheduled.renderer_profile:
            failures.append(f"trial_{index + 1}_profile_mismatch")
        if pair.get("id") != scheduled.pair_id or pair.get("position") != scheduled.pair_position:
            failures.append(f"trial_{index + 1}_pair_metadata_mismatch")
        if manifest.get("schema") != "flydrones-vio-stress-trial-v2":
            failures.append(f"trial_{index + 1}_manifest_schema_invalid")
        if summary.get("schema") != "flydrones-vio-stress-summary-v5":
            failures.append(f"trial_{index + 1}_summary_schema_invalid")
        if baseline is not None and _frozen_value(manifest) != baseline:
            failures.append(f"trial_{index + 1}_frozen_inputs_mismatch")
    return failures


def _delta(right: float | int | None, left: float | int | None) -> float | None:
    return float(right) - float(left) if right is not None and left is not None else None


def _sustained_degradation(values: Sequence[float | None]) -> bool:
    finite = [value for value in values if value is not None]
    if len(finite) != len(values):
        return True
    return any(
        left < middle < right and right - left > 5.0
        for left, middle, right in zip(finite, finite[1:], finite[2:])
    )


def _aggregate(scores: Sequence[Mapping[str, object]]) -> dict[str, object]:
    fields = ("tail_p99_ms", "tail_max_ms", "rtf", "mission_count", "landing_count")
    result: dict[str, object] = {"trial_count": len(scores)}
    for field in fields:
        values = [
            _finite_number(_mapping(score.get("metrics")).get(field))
            for score in scores
        ]
        present = [value for value in values if value is not None]
        result[field] = values
        result[f"{field}_distribution"] = {
            "min": min(present) if present else None,
            "median": median(present) if present else None,
            "max": max(present) if present else None,
        }
    return result


def score_campaign(
    trials: Sequence[tuple[Mapping[str, object], Mapping[str, object]]],
) -> dict[str, object]:
    """Validate the frozen sequence and score every run, including failures."""
    validation_failures = _validate_campaign(trials)
    scores = [score_renderer_trial(manifest, summary) for manifest, summary in trials]
    by_pair: dict[int, dict[str, Mapping[str, object]]] = {}
    for score in scores:
        pair_id = _mapping(score.get("pair")).get("id")
        if isinstance(pair_id, int):
            by_pair.setdefault(pair_id, {})[str(score["renderer_profile"])] = score
    pairs = []
    for pair_id in range(1, 6):
        members = by_pair.get(pair_id, {})
        default = members.get("default")
        d3d12 = members.get("d3d12-nvidia")
        if default is None or d3d12 is None:
            continue
        default_metrics = _mapping(default.get("metrics"))
        d3d12_metrics = _mapping(d3d12.get("metrics"))
        pairs.append({
            "pair_id": pair_id,
            "default_trial": default["name"],
            "d3d12_trial": d3d12["name"],
            "deltas": {
                field: _delta(d3d12_metrics.get(field), default_metrics.get(field))
                for field in ("tail_p99_ms", "tail_max_ms", "rtf", "mission_count")
            },
        })

    grouped = {
        profile: [score for score in scores if score["renderer_profile"] == profile]
        for profile in ("default", "d3d12-nvidia")
    }
    d3d12 = grouped["d3d12-nvidia"]
    no_trend = not _sustained_degradation([
        _finite_number(_mapping(score.get("metrics")).get("tail_p99_ms")) for score in d3d12
    ]) and not _sustained_degradation([
        _finite_number(_mapping(score.get("metrics")).get("tail_max_ms")) for score in d3d12
    ])
    complete = not validation_failures and len(scores) == 10 and len(pairs) == 5
    campaign_failures = []
    if not no_trend:
        campaign_failures.append("d3d12_sustained_tail_degradation")
    gate = complete and len(d3d12) == 5 and all(score["passed"] for score in d3d12) and no_trend
    return {
        "schema": "flydrones-renderer-stability-campaign-v1",
        "formal_artifacts_complete": complete,
        "validation_failures": validation_failures,
        "campaign_failures": campaign_failures,
        "trials": scores,
        "pairs": pairs,
        "renderer_aggregates": {
            profile: _aggregate(profile_scores) for profile, profile_scores in grouped.items()
        },
        "d3d12_no_sustained_degradation": no_trend,
        "d3d12_stability_gate_pass": gate,
    }
