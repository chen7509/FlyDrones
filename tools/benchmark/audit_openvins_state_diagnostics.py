"""Strict offline integrity screening of native OpenVINS diagnostics, never fusion permission."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

FLAGS = ("internal_initialized", "public_initialized", "zupt_flag_latched", "has_moved_since_zupt")
TIMES = ("initializer_time_s", "state_time_s", "last_regular_update_s", "feed_camera_wall_s")
ARRAYS = {"quaternion_xyzw": (4,), "position": (3,), "velocity": (3,), "imu_covariance": (15, 15)}
FIELDS = {"image_ns", *FLAGS, *TIMES, *ARRAYS}


def _finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def _array(value, shape):
    raw = np.asarray(value, dtype=object)
    if raw.shape != shape or not all(_finite(v) for v in raw.flat):
        raise ValueError("invalid diagnostic array")
    return np.asarray(value, dtype=float)


def audit_records(records: list[dict], expected_ns: list[int], start_ns: int, end_ns: int) -> dict:
    if (
        not expected_ns
        or any(type(t) is not int or t <= 0 for t in expected_ns)
        or any(b <= a for a, b in zip(expected_ns, expected_ns[1:]))
        or type(start_ns) is not int
        or type(end_ns) is not int
        or not 0 < start_ns < end_ns
        or len(records) != len(expected_ns)
    ):
        raise ValueError("invalid image stream or window")
    rows = []
    initializer = previous_state = None
    first_internal = first_public = None
    first_handoff = None
    previous_regular = -1.0
    movement_latched = False
    for i, (record, expected) in enumerate(zip(records, expected_ns)):
        if (
            set(record) != FIELDS
            or type(record["image_ns"]) is not int
            or record["image_ns"] != expected
            or any(type(record[k]) is not bool for k in FLAGS)
            or any(not _finite(record[k]) for k in TIMES)
            or record["feed_camera_wall_s"] < 0
        ):
            raise ValueError("malformed diagnostic record")
        internal, public = record["internal_initialized"], record["public_initialized"]
        init_s, state_s, regular_s = (record[k] for k in TIMES[:3])
        if (
            public != (internal and regular_s >= 0)
            or (regular_s != -1 and regular_s < 0)
            or regular_s > state_s + 1e-9
            or regular_s < previous_regular
        ):
            raise ValueError("inconsistent public/internal state")
        previous_regular = regular_s
        if movement_latched and not record["has_moved_since_zupt"]:
            raise ValueError("movement latch regressed without reset evidence")
        movement_latched = record["has_moved_since_zupt"]
        reasons = []
        if not internal:
            if (
                initializer is not None
                or regular_s != -1.0
                or record["zupt_flag_latched"]
                or record["has_moved_since_zupt"]
                or any(record[k] is not None for k in ARRAYS)
            ):
                raise ValueError("invalid sentinel or lost initialization without reset evidence")
            if (init_s, state_s) == (-1.0, -1.0):
                reasons.append("not_initialized")
            elif 0 <= init_s == state_s <= expected * 1e-9:
                # Pinned synchronous initializer joins its worker, then returns false.
                # Its success latch is consumed by the manager on the next image.
                initializer = init_s
                first_handoff = expected
                reasons.append("initializer_handoff_pending")
            else:
                raise ValueError("invalid initializer handoff")
        else:
            if (
                not 0 <= init_s <= state_s
                or (initializer is not None and init_s != initializer)
                or (previous_state is not None and state_s <= previous_state)
            ):
                raise ValueError("invalid state time or unannounced reset")
            initializer, previous_state = init_s, state_s
            if first_internal is None:
                first_internal = expected
            if public and first_public is None:
                first_public = expected
            arrays = {k: _array(record[k], shape) for k, shape in ARRAYS.items()}
            covariance = arrays["imu_covariance"]
            with np.errstate(over="raise", invalid="raise"):
                try:
                    norm = float(np.linalg.norm(arrays["quaternion_xyzw"]))
                    eigenvalues = np.linalg.eigvalsh(covariance)
                except (FloatingPointError, np.linalg.LinAlgError) as exc:
                    raise ValueError("invalid diagnostic numerical range") from exc
            if (
                not math.isfinite(norm)
                or abs(norm - 1.0) > 0.01
                or not np.allclose(covariance, covariance.T, atol=1e-8, rtol=0)
                or not np.all(np.isfinite(eigenvalues))
                or eigenvalues.min() < -1e-8
            ):
                raise ValueError("invalid quaternion or covariance")
            if abs(state_s - expected * 1e-9) > 0.05 + 1e-9:
                reasons.append("state_time_mismatch")
        if i and expected - expected_ns[i - 1] > 150_000_000:
            reasons.append("image_gap")
        rows.append(
            {
                "image_ns": expected,
                "screen_passed": not reasons,
                "reasons": reasons,
                "internal_initialized": internal,
                "public_initialized": public,
                "state_time_s": state_s,
                "zupt_flag_latched": record["zupt_flag_latched"],
            }
        )
    window = [r for r in rows if start_ns <= r["image_ns"] <= end_ns]
    covered = bool(window) and window[0]["image_ns"] - start_ns < 100_000_000 and end_ns - window[-1]["image_ns"] < 100_000_000
    return {
        "schema": "flydrones-openvins-state-diagnostics-audit-v1",
        "scope": "offline native-state integrity only; not accuracy, observability or flight qualification",
        "total_frames": len(rows),
        "internal_initialized_frames": sum(r["internal_initialized"] for r in rows),
        "public_initialized_frames": sum(r["public_initialized"] for r in rows),
        "first_internal_image_ns": first_internal,
        "first_initializer_handoff_image_ns": first_handoff,
        "initializer_reference_time_s": initializer,
        "first_public_image_ns": first_public,
        "prearm_frame_count": len(window),
        "prearm_screen_passed": covered and all(r["screen_passed"] for r in window),
        "prearm_internal_public_mismatch_frames": sum(r["internal_initialized"] and not r["public_initialized"] for r in window),
        "eligible_for_px4_fusion": False,
        "remaining_fusion_gaps": [
            "frame transformation validation",
            "reset and quality evidence",
            "online arrival/transport latency",
            "uncertainty calibration",
            "fault recovery",
        ],
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--episode-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("diagnostic audit output exists")
    records = [json.loads(line) for line in args.diagnostics.read_text().splitlines()]
    with args.frames.open() as stream:
        expected = [int(r["timestamp_ns"]) for r in csv.DictReader(stream)]
    prearm = json.loads(args.episode_result.read_text())["development_prearm_stationary"]
    if prearm["status"] != "completed":
        raise ValueError("incomplete prearm window")
    result = audit_records(records, expected, prearm["start_sim_ns"], prearm["end_sim_ns"])
    result["source_sha256"] = {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in [("diagnostics", args.diagnostics), ("frames", args.frames), ("episode_result", args.episode_result)]
    }
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
