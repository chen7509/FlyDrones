"""ULog checks for visual-estimation continuity after GNSS fusion is disabled."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def _indices_after(dataset: Mapping[str, Sequence], start_s: float) -> list[int]:
    return [index for index, timestamp in enumerate(dataset["timestamp"])
            if float(timestamp) / 1_000_000 >= start_s]


def _ratio(dataset: Mapping[str, Sequence], field: str, indices: list[int]) -> float:
    return sum(bool(dataset[field][index]) for index in indices) / len(indices) if indices else 0.0


def _observed_duration(dataset: Mapping[str, Sequence], field: str, indices: list[int]) -> float:
    """Hold each status flag until the next ULog status update."""
    return sum(
        (float(dataset["timestamp"][right]) - float(dataset["timestamp"][left])) / 1_000_000
        for left, right in zip(indices, indices[1:]) if bool(dataset[field][left])
    )


def summarize_post_gnss_evidence(
    datasets: Mapping[str, Mapping[str, Sequence]], *, gps_disable_s: float | None,
) -> dict:
    """Separate proven EV-only continuity from a proven GNSS-to-EV handoff."""
    required = ("estimator_status_flags", "estimator_aid_src_ev_pos",
                "vehicle_visual_odometry", "vehicle_local_position")
    missing = [name for name in required if name not in datasets]
    if missing:
        return {"accepted": False, "checks": {}, "metrics": {},
                "error": f"missing ULog datasets: {', '.join(missing)}"}
    if gps_disable_s is None or not math.isfinite(gps_disable_s):
        return {"accepted": False, "checks": {}, "metrics": {},
                "error": "EKF2_GPS_CTRL=0 change was not recorded"}

    status = datasets["estimator_status_flags"]
    ev_aid = datasets["estimator_aid_src_ev_pos"]
    visual = datasets["vehicle_visual_odometry"]
    local = datasets["vehicle_local_position"]
    # Ignore the first 0.2 s while PX4 applies the parameter update.
    start_s = gps_disable_s + 0.2
    status_post = _indices_after(status, start_s)
    aid_post = _indices_after(ev_aid, start_s)
    visual_post = _indices_after(visual, start_s)
    local_post = _indices_after(local, start_s)
    prior_overlap = any(
        float(timestamp) / 1_000_000 < gps_disable_s
        and all(bool(status[field][index]) for field in
                ("cs_gnss_pos", "cs_gnss_vel", "cs_ev_pos", "cs_ev_vel"))
        for index, timestamp in enumerate(status["timestamp"])
    )
    visual_times = [float(visual["timestamp"][index]) / 1_000_000 for index in visual_post]
    visual_gaps = [right - left for left, right in zip(visual_times, visual_times[1:])]
    local_valid = sum(bool(local["xy_valid"][index]) and bool(local["v_xy_valid"][index])
                      for index in local_post) / len(local_post) if local_post else 0.0
    ev_fused = _ratio(ev_aid, "fused", aid_post)
    ev_pos = _ratio(status, "cs_ev_pos", status_post)
    ev_vel = _ratio(status, "cs_ev_vel", status_post)
    gnss_pos = _ratio(status, "cs_gnss_pos", status_post)
    gnss_vel = _ratio(status, "cs_gnss_vel", status_post)
    dead_reckoning = _ratio(status, "cs_inertial_dead_reckoning", status_post)
    dead_reckoning_duration = _observed_duration(status, "cs_inertial_dead_reckoning", status_post)
    visual_duration = visual_times[-1] - visual_times[0] if len(visual_times) >= 2 else 0.0
    checks = {
        "visual_position_fused_after_gnss_disable": len(aid_post) >= 10 and ev_fused >= 0.90,
        "visual_position_and_velocity_control_active": len(status_post) >= 2 and ev_pos == 1.0 and ev_vel == 1.0,
        "gnss_fusion_inactive_after_disable": len(status_post) >= 2 and gnss_pos == 0.0 and gnss_vel == 0.0,
        "no_observed_inertial_dead_reckoning": len(status_post) >= 2 and dead_reckoning == 0.0,
        "local_position_valid": len(local_post) >= 10 and local_valid >= 0.95,
        "visual_stream_present": len(visual_post) >= 10 and visual_duration >= 5.0,
        "gnss_to_visual_handoff_proven": prior_overlap,
    }
    acceptance_keys = tuple(key for key in checks if key != "gnss_to_visual_handoff_proven")
    return {
        "schema": "flydrones-vio-post-gnss-evidence-v1",
        "accepted": all(checks[key] for key in acceptance_keys),
        "checks": checks,
        "metrics": {
            "gps_disable_timestamp_s": round(gps_disable_s, 6),
            "post_status_samples": len(status_post),
            "ev_position_fused_samples": sum(bool(ev_aid["fused"][index]) for index in aid_post),
            "ev_position_samples": len(aid_post),
            "ev_position_fused_ratio": round(ev_fused, 6),
            "ev_position_control_ratio": round(ev_pos, 6),
            "ev_velocity_control_ratio": round(ev_vel, 6),
            "gnss_position_control_ratio": round(gnss_pos, 6),
            "gnss_velocity_control_ratio": round(gnss_vel, 6),
            "inertial_dead_reckoning_ratio": round(dead_reckoning, 6),
            "dead_reckoning_observed_duration_s": round(dead_reckoning_duration, 6),
            "local_position_valid_ratio": round(local_valid, 6),
            "visual_stream_duration_s": round(visual_duration, 6),
            "visual_stream_max_gap_ms": round(max(visual_gaps) * 1000, 3) if visual_gaps else None,
        },
    }
