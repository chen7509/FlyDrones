"""Extract source-level EKF fusion evidence from a PX4 ULog."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path


REQUIRED_DATASETS = (
    "estimator_status_flags",
    "estimator_aid_src_ev_pos",
    "estimator_aid_src_gnss_pos",
    "estimator_aid_src_gnss_vel",
    "vehicle_visual_odometry",
    "vehicle_local_position",
)


def _seconds(values: Sequence[object]) -> list[float]:
    return [float(value) / 1_000_000.0 for value in values]


def _bools(values: Sequence[object]) -> list[bool]:
    return [bool(value) for value in values]


def _count_fused_after(dataset: Mapping[str, Sequence[object]], switch_s: float) -> tuple[int, int, int]:
    timestamps = _seconds(dataset["timestamp"])
    fused = _bools(dataset.get("fused", [False] * len(timestamps)))
    rejected = _bools(dataset.get("innovation_rejected", [False] * len(timestamps)))
    indices = [index for index, timestamp in enumerate(timestamps) if timestamp >= switch_s]
    return (
        len(indices),
        sum(fused[index] for index in indices),
        sum(rejected[index] for index in indices),
    )


def summarize_fusion_evidence(
    datasets: Mapping[str, Mapping[str, Sequence[object]]],
) -> dict:
    """Prove an EKF transition from GNSS+EV fusion to EV-only fusion."""
    missing = [name for name in REQUIRED_DATASETS if name not in datasets]
    if missing:
        raise ValueError(f"ULog is missing required datasets: {', '.join(missing)}")

    status = datasets["estimator_status_flags"]
    status_time = _seconds(status["timestamp"])
    ev_pos = _bools(status["cs_ev_pos"])
    ev_vel = _bools(status["cs_ev_vel"])
    gnss_pos = _bools(status["cs_gnss_pos"])
    gnss_vel = _bools(status["cs_gnss_vel"])
    dead_reckoning = _bools(status["cs_inertial_dead_reckoning"])

    pre_fused_indices = [
        index for index in range(len(status_time))
        if ev_pos[index] and ev_vel[index] and gnss_pos[index] and gnss_vel[index]
    ]
    switch_index = next((
        index for index in range(len(status_time))
        if ev_pos[index]
        and ev_vel[index]
        and not gnss_pos[index]
        and not gnss_vel[index]
        and any(previous < index for previous in pre_fused_indices)
    ), None)
    if switch_index is None:
        switch_s = math.inf
        post_status_indices: list[int] = []
    else:
        switch_s = status_time[switch_index]
        post_status_indices = list(range(switch_index, len(status_time)))

    ev_samples, ev_fused, ev_rejected = _count_fused_after(
        datasets["estimator_aid_src_ev_pos"], switch_s
    )
    ev_aid = datasets["estimator_aid_src_ev_pos"]
    ev_aid_time = _seconds(ev_aid["timestamp"])
    ev_aid_fused = _bools(ev_aid.get("fused", [False] * len(ev_aid_time)))
    ev_fused_before = sum(
        fused and timestamp < switch_s
        for timestamp, fused in zip(ev_aid_time, ev_aid_fused, strict=True)
    )
    gnss_pos_samples, gnss_pos_fused, _ = _count_fused_after(
        datasets["estimator_aid_src_gnss_pos"], switch_s
    )
    gnss_vel_samples, gnss_vel_fused, _ = _count_fused_after(
        datasets["estimator_aid_src_gnss_vel"], switch_s
    )

    visual_time = _seconds(datasets["vehicle_visual_odometry"]["timestamp"])
    visual_post = [timestamp for timestamp in visual_time if timestamp >= switch_s]
    visual_post_duration_s = visual_post[-1] - switch_s if visual_post else 0.0
    visual_post_gaps = [
        visual_post[index] - visual_post[index - 1]
        for index in range(1, len(visual_post))
    ]

    local = datasets["vehicle_local_position"]
    local_time = _seconds(local["timestamp"])
    reset_counters = [int(value) for value in local["xy_reset_counter"]]
    reset_index = next((
        index for index in range(1, len(local_time))
        if local_time[index] >= switch_s
        and local_time[index] - switch_s <= 0.25
        and reset_counters[index] > reset_counters[index - 1]
    ), None)
    if reset_index is None:
        reset_delta_m = 0.0
        reset_timestamp_s = None
    else:
        reset_delta_m = math.hypot(
            float(local["delta_xy[0]"][reset_index]),
            float(local["delta_xy[1]"][reset_index]),
        )
        reset_timestamp_s = local_time[reset_index]

    local_post_indices = [
        index for index, timestamp in enumerate(local_time) if timestamp >= switch_s
    ]
    local_valid = [
        bool(local["xy_valid"][index]) and bool(local["v_xy_valid"][index])
        for index in local_post_indices
    ]
    local_post_duration_s = (
        local_time[local_post_indices[-1]] - switch_s if local_post_indices else 0.0
    )
    local_valid_ratio = sum(local_valid) / len(local_valid) if local_valid else 0.0

    checks = {
        "external_vision_position_fused_before_gnss_loss": (
            bool(pre_fused_indices) and ev_fused_before > 0
        ),
        "external_vision_position_fused_after_gnss_loss": (
            ev_samples > 0 and ev_fused / ev_samples >= 0.90
        ),
        "external_vision_velocity_control_active_after_gnss_loss": (
            bool(post_status_indices) and all(ev_vel[index] for index in post_status_indices)
        ),
        "gnss_fusion_stopped": (
            switch_index is not None
            and all(not gnss_pos[index] and not gnss_vel[index] for index in post_status_indices)
            and gnss_pos_fused == 0
            and gnss_vel_fused == 0
        ),
        "no_inertial_dead_reckoning_after_switch": (
            bool(post_status_indices)
            and all(not dead_reckoning[index] for index in post_status_indices)
        ),
        "visual_odometry_stream_continued": (
            len(visual_post) >= 2
            and visual_post_duration_s >= 5.0
            and bool(visual_post_gaps)
            and max(visual_post_gaps) <= 0.20
        ),
        "local_position_valid_after_switch": (
            local_post_duration_s >= 5.0 and local_valid_ratio >= 0.95
        ),
        "local_origin_reset_observed": reset_index is not None and reset_delta_m > 0.0,
    }
    metrics = {
        "switch_timestamp_s": None if not math.isfinite(switch_s) else round(switch_s, 6),
        "external_vision_fusion_started_s": (
            round(status_time[pre_fused_indices[0]], 6) if pre_fused_indices else None
        ),
        "external_vision_position_fused_samples_before_switch": ev_fused_before,
        "external_vision_position_fused_samples_after_switch": ev_fused,
        "external_vision_position_samples_after_switch": ev_samples,
        "external_vision_position_rejected_samples_after_switch": ev_rejected,
        "gnss_position_samples_after_switch": gnss_pos_samples,
        "gnss_position_fused_samples_after_switch": gnss_pos_fused,
        "gnss_velocity_samples_after_switch": gnss_vel_samples,
        "gnss_velocity_fused_samples_after_switch": gnss_vel_fused,
        "visual_odometry_samples_after_switch": len(visual_post),
        "visual_odometry_duration_after_switch_s": round(visual_post_duration_s, 6),
        "visual_odometry_max_gap_after_switch_ms": (
            round(max(visual_post_gaps) * 1000.0, 3) if visual_post_gaps else None
        ),
        "local_position_duration_after_switch_s": round(local_post_duration_s, 6),
        "local_position_valid_ratio_after_switch": round(local_valid_ratio, 6),
        "local_origin_reset_timestamp_s": (
            round(reset_timestamp_s, 6) if reset_timestamp_s is not None else None
        ),
        "local_origin_reset_delta_m": round(reset_delta_m, 6),
    }
    return {
        "schema": "flydrones-px4-ekf-fusion-evidence-v1",
        "accepted": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
    }


def extract_ulog_fusion_evidence(
    ulog_path: str | Path,
    *,
    output_path: str | Path,
    fault_vehicle_id: int,
    preserve_ulog: bool = True,
) -> dict:
    """Read a ULog, preserve its source bytes and write verified fusion evidence."""
    try:
        from pyulog import ULog
    except ImportError as exc:  # pragma: no cover - optional PX4 analysis dependency
        raise RuntimeError("pyulog is required to verify PX4 EKF fusion evidence") from exc

    source = Path(ulog_path).resolve()
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    preserved = destination.parent / "px4-ulogs" / f"agent-{fault_vehicle_id}.ulg"
    if preserve_ulog:
        preserved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, preserved)
        parsed_path = preserved
    else:
        parsed_path = source

    ulog = ULog(str(parsed_path))
    available = {(dataset.name, dataset.multi_id): dataset.data for dataset in ulog.data_list}
    datasets = {}
    for name in REQUIRED_DATASETS:
        key = (name, 0)
        if key not in available:
            raise ValueError(f"ULog is missing required dataset {name}")
        datasets[name] = available[key]
    evidence = summarize_fusion_evidence(datasets)
    digest = hashlib.sha256(parsed_path.read_bytes()).hexdigest()
    evidence["source"] = {
        "fault_vehicle_id": int(fault_vehicle_id),
        "ulog_path": str(parsed_path),
        "ulog_bytes": parsed_path.stat().st_size,
        "ulog_sha256": digest,
    }
    destination.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return evidence


def newest_vehicle_ulog(px4_run_dir: str | Path, vehicle_id: int) -> Path:
    candidates = sorted(
        (Path(px4_run_dir) / f"instance_{vehicle_id}" / "log").glob("**/*.ulg"),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f"no ULog found for vehicle {vehicle_id}")
    return candidates[-1]
