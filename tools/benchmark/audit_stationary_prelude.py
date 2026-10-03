"""Gate one saved development hover prelude before any OpenVINS replay."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from flydrones.benchmark.camera_info_capture import verify_camera_info_capture
from flydrones.benchmark.rgb_capture import verify_rgb_manifest
from flydrones.benchmark.ulog_capture import verify_episode_ulog_evidence
from tools.benchmark.audit_openvins_imu_init import score_ekf_init_velocity


def assess_prelude(result: dict, velocity_data: dict,
                   frame_ns: list[int]) -> tuple[list[dict], dict]:
    """Score EKF2's final two hover seconds; EKF2 is a reference, not truth."""
    if any(result.get(key) is not True for key in (
            "rgb_capture_accepted", "camera_info_capture_accepted",
            "px4_ulog_capture_accepted")) or result.get(
                "rgb_capture_out_of_order_drops") != 0 or any(result.get(key) is not None
                for key in ("rgb_capture_error", "camera_info_error", "px4_ulog_capture_error")):
        raise ValueError("incomplete capture evidence")
    prelude = result.get("development_hover_prelude")
    if (not isinstance(prelude, dict) or prelude.get("requested_steps") != 80
            or prelude.get("actual_steps") != 80 or prelude.get("terminal_status") is not None):
        raise ValueError("missing complete four-second prelude")
    start_ns, end_ns = prelude.get("start_sim_ns"), prelude.get("end_sim_ns")
    if (type(start_ns) is not int or type(end_ns) is not int
            or end_ns - start_ns != 4_000_000_000):
        raise ValueError("invalid prelude interval")
    decisions = result.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ValueError("missing first policy decision")
    if decisions[0].get("sim_ns") != end_ns:
        raise ValueError("first policy decision differs from prelude end")

    window_start_ns = end_ns - 2_000_000_000
    rows, velocity = score_ekf_init_velocity(
        velocity_data, window_start_ns / 1_000_000_000, end_ns / 1_000_000_000)
    velocity["speed_at_window_end_m_s"] = velocity.pop(
        "speed_at_first_initialized_sample_m_s")
    if not frame_ns or any(type(t) is not int for t in frame_ns) or any(
            later <= earlier for earlier, later in zip(frame_ns, frame_ns[1:])):
        raise ValueError("RGB frame timestamps invalid")
    frames = [t for t in frame_ns if window_start_ns <= t <= end_ns]
    failures = []
    if (len(frames) < 10 or frames[0] - window_start_ns > 150_000_000
            or end_ns - frames[-1] > 150_000_000
            or any(b - a > 200_000_000 for a, b in zip(frames, frames[1:]))):
        failures.append("rgb_missing_in_velocity_window")
    if velocity["median_speed_m_s"] >= .1:
        failures.append("speed_not_below_0_1_m_s")
    return rows, {
        "schema": "flydrones-stationary-prelude-gate-v1",
        "reference": "PX4 EKF2 velocity; not independent ground truth or VIO output",
        "window_start_s": window_start_ns / 1_000_000_000,
        "window_end_s": end_ns / 1_000_000_000,
        "rgb_frames_in_window": len(frames),
        "velocity": velocity,
        "failures": failures,
        "gate_passed": not failures,
    }


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_rgb_consistency(result: dict, rgb: dict) -> None:
    """Reconcile the retained frame manifest with the episode's capture status."""
    if result.get("rgb_capture_frame_count") != len(rgb["frames"]):
        raise ValueError("RGB frame count differs from result")
    if (rgb.get("out_of_order_drops") != 0 or
            result.get("rgb_capture_out_of_order_drops") != rgb["out_of_order_drops"]):
        raise ValueError("RGB out-of-order drops present or mismatched")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    episode, output = args.episode.resolve(), args.output_dir.resolve()
    if output.exists():
        raise SystemExit("output directory exists; preserve earlier evidence")
    result_path = episode / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    sources = {"result": result_path,
               "rgb_manifest": episode / "rgb-capture-manifest.json",
               "camera_info": episode / "camera-info.json",
               "camera_info_pb": episode / "camera-info.pb",
               "ulog_manifest": episode / "px4-ulog-manifest.json"}
    summary: dict
    rows: list[dict] = []
    try:
        verify_episode_ulog_evidence(episode, result)
        rgb = verify_rgb_manifest(episode)
        camera = verify_camera_info_capture(episode)
        verify_rgb_consistency(result, rgb)
        if result.get("camera_info_message_count") != camera["message_count"]:
            raise ValueError("camera-info count differs from result")
        if camera["changed_stable_fields"]:
            raise ValueError("camera-info stable fields changed")
        ulog_paths = [episode / record["path"] for record in result["px4_ulogs"]]
        if len(ulog_paths) != 1:
            raise ValueError("expected one PX4 ULog")
        from pyulog import ULog

        data = ULog(str(ulog_paths[0])).get_dataset("vehicle_local_position").data
        rows, summary = assess_prelude(result, data, [f["frame_ns"] for f in rgb["frames"]])
        sources["ulog"] = ulog_paths[0]
    except (KeyError, ValueError, OSError) as error:
        summary = {"schema": "flydrones-stationary-prelude-gate-v1",
                   "reference": "PX4 EKF2 velocity; not independent ground truth or VIO output",
                   "failures": [f"evidence_or_velocity_invalid: {error}"], "gate_passed": False}
    summary["input_sha256"] = {name: _sha256(path) for name, path in sources.items()
                               if path.is_file()}
    output.mkdir(parents=True)
    with (output / "velocity_window.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("timestamp_us", "vx_m_s", "vy_m_s",
                                                     "vz_m_s", "speed_m_s"))
        writer.writeheader()
        writer.writerows(rows)
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
