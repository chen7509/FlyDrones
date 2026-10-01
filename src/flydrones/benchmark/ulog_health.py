"""Read-only PX4 ULog topic and basic estimator evidence audit."""

from __future__ import annotations

from collections import Counter

import numpy as np

REQUIRED_TOPICS = (
    "vehicle_status",
    "vehicle_local_position",
    "estimator_status",
    "estimator_status_flags",
    "trajectory_setpoint",
    "vehicle_command_ack",
    "sensor_combined",
)


def summarize_ulog(ulog) -> dict:
    """Summarize logged evidence without treating truth or GNSS as VIO."""
    datasets = {item.name: item.data for item in ulog.data_list}
    failures = []
    counts = {}
    for name in REQUIRED_TOPICS:
        data = datasets.get(name)
        if data is None or "timestamp" not in data or len(data["timestamp"]) == 0:
            failures.append(f"{name}_missing")
            continue
        times = np.asarray(data["timestamp"], dtype=np.int64)
        counts[name] = len(times)
        if np.any(np.diff(times) < 0):
            failures.append(f"{name}_timestamp_nonmonotonic")

    def count(topic: str, field: str) -> int | None:
        data = datasets.get(topic)
        if data is None:
            return None
        if field not in data:
            failures.append(f"{topic}_{field}_missing")
            return None
        return int(np.count_nonzero(data[field]))

    status = datasets.get("vehicle_status")
    if status is not None and "nav_state" in status:
        nav_states = {str(int(key)): int(value) for key, value in
                      Counter(np.asarray(status["nav_state"]).tolist()).items()}
        if "14" not in nav_states:
            failures.append("offboard_state_missing")
    else:
        nav_states = {}
        if status is not None:
            failures.append("vehicle_status_nav_state_missing")
    failsafe = count("vehicle_status", "failsafe")
    filter_fault = count("estimator_status", "filter_fault_flags")
    xy_valid = count("vehicle_local_position", "xy_valid")
    z_valid = count("vehicle_local_position", "z_valid")
    dead_reckoning = count("vehicle_local_position", "dead_reckoning")
    gnss = count("estimator_status_flags", "cs_gnss_pos")
    external_vision = count("estimator_status_flags", "cs_ev_pos")
    if failsafe:
        failures.append("vehicle_failsafe_recorded")
    if filter_fault:
        failures.append("estimator_filter_fault_recorded")
    if xy_valid == 0 or z_valid == 0:
        failures.append("local_position_never_valid")
    return {
        "schema": "flydrones-px4-ulog-health-v1",
        "topic_counts": counts,
        "nav_state_counts": nav_states,
        "failsafe_samples": failsafe,
        "estimator_filter_fault_samples": filter_fault,
        "xy_valid_samples": xy_valid,
        "z_valid_samples": z_valid,
        "dead_reckoning_samples": dead_reckoning,
        "gnss_position_fusion_samples": gnss,
        "external_vision_position_fusion_samples": external_vision,
        "failures": failures,
        "basic_topic_gate_passed": not failures,
    }
