"""Prospective first-internal-state trajectory gauge and sealed-evidence audit.

This module is offline-only. It never starts an estimator, simulator, PX4, or a
transport publisher, and it never makes truth available to an online consumer.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np
from scipy.spatial.transform import Rotation

PR48_SHA256 = "07a2a247b87ff43304ec4c0fe787640264772ad12c272b354d5a5116cdecaeb2"
PR48_ROOT = "results/supported-online-vio-dev-1701/"
PR48_MEMBERS = {
    "audit": PR48_ROOT + "audit.json",
    "anchor": PR48_ROOT + "capture-v1/readiness-anchor.json",
    "motion": PR48_ROOT + "capture-v1/motion-profile.json",
    "session": PR48_ROOT + "capture-v1/shadow/native-session.json",
    "states": PR48_ROOT + "capture-v1/shadow/states.jsonl",
    "truth": PR48_ROOT + "capture-v1/motion-ground-truth.jsonl",
}

FLU_FRD = np.diag([1.0, -1.0, -1.0])
MAX_MAGNITUDE = 1e10
MAX_NS = 2**63 - 1


def trajectory_gauge_policy():
    """Return the immutable, truth-independent policy used before an anchor exists."""
    return {
        "schema": "trajectory-gauge-policy-v1",
        "anchor_source": "immutable_readiness_anchor",
        "origin_rule": "first_internal_initialized_state_in_session",
        "alignment": "yaw_translation_4dof",
        "scale": 1.0,
        "time_shift_ns": 0,
        "truth_used_for_origin_selection": False,
        "native_orientation": "JPL_q_GtoI_xyzw_numeric_Hamilton_I_to_G",
        "native_position": "p_IinG",
        "native_velocity": "v_IinG_global",
        "reference_orientation": "world_from_FLU_then_FLU_to_FRD",
        "wire_frames_not_emitted": ["LOCAL_FRD", "BODY_FRD"],
        "lateral_start_offset_ns": 3_000_000_000,
        "expected_duration_ns": 25_000_000_000,
        "required_public_end_offset_ns": 24_900_000_000,
        "max_public_gap_ns": 200_000_000,
        "exact_time_tolerance_ns": 1,
        "screens": {
            "max_position_error_m": 0.25,
            "max_velocity_error_m_s": 0.25,
            "max_attitude_error_deg": 10.0,
            "max_initial_gravity_axis_error_deg": 5.0,
        },
        "truth_scope": "offline_scoring_and_isolated_abort_only",
        "eligible_for_px4_fusion": False,
        "flight_ready": False,
    }


def _typed_equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_typed_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def validate_trajectory_gauge_policy(value):
    expected = trajectory_gauge_policy()
    if not _typed_equal(value, expected):
        raise ValueError("invalid trajectory gauge policy")
    return copy.deepcopy(expected)


def _strict_int(value, name, *, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_NS:
        raise ValueError(f"invalid {name}")
    return value


def _number(value, name):
    if type(value) is bool or not isinstance(value, (int, float, np.number)):
        raise ValueError(f"invalid numeric {name}")
    result = float(value)
    if not math.isfinite(result) or abs(result) > MAX_MAGNITUDE:
        raise ValueError(f"invalid numeric {name}")
    return result


def _vector(value, size, name):
    if not isinstance(value, (list, tuple, np.ndarray)) or len(value) != size:
        raise ValueError(f"invalid numeric {name}")
    result = np.asarray([_number(item, name) for item in value], dtype=float)
    if result.shape != (size,):
        raise ValueError(f"invalid numeric {name}")
    return result


def _orientation(value, name):
    quaternion = _vector(value, 4, name)
    if abs(float(np.linalg.norm(quaternion)) - 1.0) > 1e-5:
        raise ValueError(f"invalid quaternion {name}")
    return Rotation.from_quat(quaternion).as_matrix()


def _seconds_to_ns(value, name):
    seconds = _number(value, name)
    scaled = seconds * 1e9
    rounded = round(scaled)
    if not 0 <= rounded <= MAX_NS or abs(scaled - rounded) > 1.0:
        raise ValueError(f"invalid {name}")
    return rounded


def trajectory_contract(*, anchor_ns, total_duration_ns=25_000_000_000, lateral_start_offset_ns=3_000_000_000):
    anchor = _strict_int(anchor_ns, "anchor_ns")
    end = _strict_int(total_duration_ns, "total_duration_ns", minimum=1)
    offset = _strict_int(lateral_start_offset_ns, "lateral_start_offset_ns", minimum=1)
    if anchor + offset > MAX_NS or end <= anchor + offset:
        raise ValueError("invalid trajectory interval")
    return {
        "schema": "trajectory-gauge-contract-v1",
        "origin_rule": "first_internal_initialized_state_in_session",
        "alignment": "yaw_translation_4dof",
        "scale": 1.0,
        "time_shift_ns": 0,
        "truth_used_for_origin_selection": False,
        "native_orientation": "JPL_q_GtoI_xyzw_numeric_Hamilton_I_to_G",
        "native_position": "p_IinG",
        "native_velocity": "v_IinG_global",
        "reference_orientation": "world_from_FLU_then_FLU_to_FRD",
        "wire_frames_not_emitted": ["LOCAL_FRD", "BODY_FRD"],
        "anchor_ns": anchor,
        "lateral_start_ns": anchor + offset,
        "expected_end_ns": end,
        "required_public_end_ns": end - 100_000_000,
        "max_public_gap_ns": 200_000_000,
        "exact_time_tolerance_ns": 1,
        "screens": {
            "max_position_error_m": 0.25,
            "max_velocity_error_m_s": 0.25,
            "max_attitude_error_deg": 10.0,
            "max_initial_gravity_axis_error_deg": 5.0,
        },
        "truth_scope": "offline_scoring_and_isolated_abort_only",
        "eligible_for_px4_fusion": False,
        "flight_ready": False,
    }


def select_origin(states, contract):
    if contract.get("origin_rule") != "first_internal_initialized_state_in_session":
        raise ValueError("unsupported origin rule")
    for index, row in enumerate(states):
        if type(row.get("internal_initialized")) is not bool:
            raise ValueError("invalid internal initialization flag")
        if row["internal_initialized"]:
            return {"index": index, "sample_ns": _strict_int(row.get("sample_ns"), "sample_ns")}
    return None


def _native_state(value):
    state = _vector(value, 16, "native state")
    return _orientation(state[:4], "native state"), state[4:7], state[7:10]


def _truth_state(value):
    if value.get("truth_for_fixture_audit_only") is not True:
        raise ValueError("truth scope missing")
    rotation = _orientation(value.get("quaternion_xyzw"), "truth") @ FLU_FRD
    return rotation, _vector(value.get("position"), 3, "truth position"), _vector(
        value.get("velocity_world"), 3, "truth velocity"
    )


class YawTranslationGauge:
    """Four-degree-of-freedom offline gauge; scale and time remain fixed."""

    def __init__(self, native_origin, truth_origin):
        rn, pn, _ = _native_state(native_origin)
        rt, pt, _ = _truth_state(truth_origin)
        hn, ht = rn[:2, 0], rt[:2, 0]
        nn, nt = float(np.linalg.norm(hn)), float(np.linalg.norm(ht))
        if nn < 1e-6 or nt < 1e-6:
            raise ValueError("degenerate horizontal heading")
        hn, ht = hn / nn, ht / nt
        yaw = math.atan2(float(hn[0] * ht[1] - hn[1] * ht[0]), float(hn @ ht))
        self.rotation = Rotation.from_euler("z", yaw).as_matrix()
        self.native_origin = pn.copy()
        self.truth_origin = pt.copy()
        aligned_up = self.rotation @ rn[:, 2]
        self.gravity_axis_error_deg = math.degrees(
            math.acos(float(np.clip(aligned_up @ rt[:, 2], -1.0, 1.0)))
        )
        self.yaw_rad = yaw

    def compare(self, native_state, truth_state):
        rn, pn, vn = _native_state(native_state)
        rt, pt, vt = _truth_state(truth_state)
        dn, dt = pn - self.native_origin, pt - self.truth_origin
        aligned_position = self.rotation @ dn + self.truth_origin
        aligned_rotation = self.rotation @ rn
        return {
            "position_error_m": float(np.linalg.norm(aligned_position - pt)),
            "velocity_error_m_s": float(np.linalg.norm(self.rotation @ vn - vt)),
            "attitude_error_deg": float(
                np.degrees(Rotation.from_matrix(rt.T @ aligned_rotation).magnitude())
            ),
            "displacement_error_lower_bound_m": float(abs(np.linalg.norm(dn) - np.linalg.norm(dt))),
            "eligible_for_px4_fusion": False,
        }


def _validate_states(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("missing state rows")
    seen_internal = seen_public = False
    last_sample = last_sequence = last_regular = last_initializer = None
    last_receive = last_start = last_end = None
    reset_values, quality_values = [], []
    for row in rows:
        if not isinstance(row, dict) or row.get("kind") != "C":
            raise ValueError("invalid state row")
        sample = _strict_int(row.get("sample_ns"), "sample_ns")
        sequence = _strict_int(row.get("sequence"), "sequence")
        if (last_sample is not None and sample <= last_sample) or (
            last_sequence is not None and sequence <= last_sequence
        ):
            raise ValueError("duplicate or regressed sample")
        last_sample, last_sequence = sample, sequence
        receive = _strict_int(row.get("receive_ns"), "receive_ns")
        start = _strict_int(row.get("start_ns"), "start_ns")
        end = _strict_int(row.get("end_ns"), "end_ns")
        if not receive <= start <= end:
            raise ValueError("invalid processing clock order")
        if (
            (last_receive is not None and receive < last_receive)
            or (last_start is not None and start < last_start)
            or (last_end is not None and end < last_end)
        ):
            raise ValueError("processing clock regressed")
        last_receive, last_start, last_end = receive, start, end
        internal, public = row.get("internal_initialized"), row.get("public_initialized")
        if type(internal) is not bool or type(public) is not bool:
            raise ValueError("invalid internal/public flag")
        if seen_internal and not internal:
            raise ValueError("internal initialization reverted")
        if public and not internal:
            raise ValueError("public initialized before internal")
        if seen_public and not public:
            raise ValueError("public initialization reverted")
        seen_internal |= internal
        seen_public |= public
        state_time = row.get("state_time_s")
        if internal:
            if _seconds_to_ns(state_time, "state time") != sample:
                raise ValueError("state time does not match sample")
            _native_state(row.get("imu_state"))
        else:
            if row.get("imu_state") is not None:
                raise ValueError("uninitialized row has state")
            value = _number(state_time, "state time")
            if value != -1 and _seconds_to_ns(value, "state time") > sample:
                raise ValueError("uninitialized future state time")
        initializer = _number(row.get("initializer_time_s"), "initializer time")
        if initializer != -1:
            initializer_ns = _seconds_to_ns(initializer, "initializer time")
            if initializer_ns > sample or (last_initializer is not None and initializer_ns < last_initializer):
                raise ValueError("initializer time regressed or after sample")
            last_initializer = initializer_ns
        regular = _number(row.get("last_regular_update_s"), "regular update time")
        if public and regular == -1:
            raise ValueError("public state missing regular update time")
        if regular != -1:
            regular_ns = _seconds_to_ns(regular, "regular update time")
            if regular_ns > sample or (last_regular is not None and regular_ns < last_regular):
                raise ValueError("regular update time regressed")
            last_regular = regular_ns
        for name in ("zupt_flag_latched", "has_moved_since_zupt"):
            if type(row.get(name)) is not bool:
                raise ValueError(f"invalid {name}")
        if row.get("fusion_eligible") is not False:
            raise ValueError("state unexpectedly fusion eligible")
        reset, quality = row.get("reset_counter"), row.get("quality")
        if reset is not None and (type(reset) is not int or not 0 <= reset <= 255):
            raise ValueError("invalid row reset counter")
        if quality is not None and (type(quality) is not int or not -1 <= quality <= 100):
            raise ValueError("invalid row quality")
        if reset is not None:
            reset_values.append(reset)
        if quality is not None:
            quality_values.append(quality)
    return {"reset_values": reset_values, "quality_values": quality_values}


def _truth_index(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("missing truth rows")
    result = {}
    last = None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid truth row")
        stamp = _strict_int(row.get("sim_ns"), "truth sim_ns")
        if last is not None and stamp <= last:
            raise ValueError("duplicate or regressed truth sample")
        last = stamp
        _truth_state(row)
        result[stamp] = row
    return result


def _validate_session(session):
    if not isinstance(session, dict) or not isinstance(session.get("session_id"), str) or not session["session_id"].strip():
        raise ValueError("invalid session identity")
    reset = session.get("reset_counter")
    quality = session.get("quality")
    if reset is not None and (type(reset) is not int or not 0 <= reset <= 255):
        raise ValueError("invalid reset counter")
    if quality is not None and (type(quality) is not int or not -1 <= quality <= 100):
        raise ValueError("invalid quality")
    if type(session.get("covariance_calibrated")) is not bool:
        raise ValueError("invalid covariance status")
    if "reset_observed" in session and type(session["reset_observed"]) is not bool:
        raise ValueError("invalid reset observation")


def audit_trajectory(states, truth_rows, session, capture, contract):
    if not isinstance(contract, dict) or contract.get("schema") != "trajectory-gauge-contract-v1":
        raise ValueError("invalid trajectory contract")
    state_evidence = _validate_states(states)
    truth = _truth_index(truth_rows)
    _validate_session(session)
    if not isinstance(capture, dict) or not isinstance(capture.get("status"), str):
        raise ValueError("invalid capture status")
    end_sim_ns = _strict_int(capture.get("end_sim_ns"), "capture end")
    origin = select_origin(states, contract)
    reasons = []
    metrics = None
    diagnostic_available = origin is not None
    first_public = next((row["sample_ns"] for row in states if row["public_initialized"]), None)

    if origin is None:
        reasons.append("missing_internal_state")
        diagnostic_available = False
    elif origin["sample_ns"] > contract["lateral_start_ns"]:
        reasons.append("origin_after_lateral_start")
        diagnostic_available = False

    internal_rows = states[origin["index"] :] if origin is not None else []
    matched = []
    for row in internal_rows:
        if not row["internal_initialized"]:
            continue
        reference = truth.get(row["sample_ns"])
        if reference is None:
            raise ValueError(f"missing exact truth at {row['sample_ns']}")
        matched.append((row, reference))

    if diagnostic_available:
        gauge = YawTranslationGauge(matched[0][0]["imu_state"], matched[0][1])
        comparisons = [gauge.compare(row["imu_state"], reference) for row, reference in matched]
        metrics = {
            "matched_state_count": len(comparisons),
            "yaw_alignment_rad": gauge.yaw_rad,
            "initial_gravity_axis_error_deg": gauge.gravity_axis_error_deg,
            "max_position_error_m": max(row["position_error_m"] for row in comparisons),
            "terminal_position_error_m": comparisons[-1]["position_error_m"],
            "max_velocity_error_m_s": max(row["velocity_error_m_s"] for row in comparisons),
            "max_attitude_error_deg": max(row["attitude_error_deg"] for row in comparisons),
            "max_displacement_error_lower_bound_m": max(
                row["displacement_error_lower_bound_m"] for row in comparisons
            ),
            "scale": 1.0,
            "time_shift_ns": 0,
            "later_realignment": False,
        }

    public_rows = [row for row in states if row["public_initialized"]]
    public_gaps = [
        current["sample_ns"] - previous["sample_ns"]
        for previous, current in zip(public_rows, public_rows[1:], strict=False)
    ]
    public_coverage = bool(
        public_rows
        and first_public <= contract["lateral_start_ns"]
        and (not public_gaps or max(public_gaps) <= contract["max_public_gap_ns"])
        and public_rows[-1]["sample_ns"] >= contract["required_public_end_ns"]
    )
    if not public_coverage:
        reasons.append("public_coverage_incomplete")
    capture_complete = capture["status"] == "capture_completed" and end_sim_ns >= contract["expected_end_ns"]
    if not capture_complete:
        reasons.append("capture_incomplete")

    reset = session.get("reset_counter")
    quality = session.get("quality")
    row_resets = state_evidence["reset_values"]
    row_qualities = state_evidence["quality_values"]
    reset_observed = bool(
        session.get("reset_observed", False)
        or len(set(row_resets)) > 1
        or (reset is not None and any(value != reset for value in row_resets))
    )
    quality_changed = bool(
        len(set(row_qualities)) > 1
        or (quality is not None and any(value != quality for value in row_qualities))
    )
    if reset is None:
        reasons.append("reset_unknown")
    if reset_observed:
        reasons.append("reset_observed")
    if quality is None or quality == 0:
        reasons.append("quality_unknown")
    elif quality < 0:
        reasons.append("quality_failed")
    if quality_changed:
        reasons.append("quality_changed")
    if not session["covariance_calibrated"]:
        reasons.append("covariance_uncalibrated")
    health = bool(
        reset is not None
        and not reset_observed
        and quality is not None
        and quality > 0
        and not quality_changed
        and session["covariance_calibrated"]
    )

    screens = contract["screens"]
    accuracy_screens = bool(
        metrics
        and metrics["max_position_error_m"] <= screens["max_position_error_m"]
        and metrics["max_velocity_error_m_s"] <= screens["max_velocity_error_m_s"]
        and metrics["max_attitude_error_deg"] <= screens["max_attitude_error_deg"]
        and metrics["initial_gravity_axis_error_deg"] <= screens["max_initial_gravity_axis_error_deg"]
    )
    if diagnostic_available and not accuracy_screens:
        reasons.append("accuracy_screen_failed")
    startup = None
    if origin is not None and origin["sample_ns"] > contract["anchor_ns"]:
        startup = {
            "start_ns": contract["anchor_ns"],
            "end_ns": origin["sample_ns"],
            "duration_ns": origin["sample_ns"] - contract["anchor_ns"],
        }
    post_origin_qualified = bool(
        diagnostic_available and accuracy_screens and public_coverage and capture_complete and health
    )
    full_motion_qualified = bool(post_origin_qualified and startup is None)
    return {
        "schema": "trajectory-gauge-audit-v1",
        "contract": contract,
        "origin": None
        if origin is None
        else {
            **origin,
            "rule": contract["origin_rule"],
            "truth_used_for_selection": False,
        },
        "startup_unavailable": startup,
        "state_count": len(states),
        "internal_state_count": len(matched),
        "public_state_count": len(public_rows),
        "first_public_sample_ns": first_public,
        "max_public_gap_ns": max(public_gaps) if public_gaps else None,
        "zupt_latched_row_count": sum(row["zupt_flag_latched"] for row in states),
        "regular_update_row_count": sum(row["last_regular_update_s"] != -1 for row in states),
        "metrics": metrics,
        "diagnostic_available": diagnostic_available,
        "diagnostic_screens_pass": accuracy_screens,
        "public_coverage_qualified": public_coverage,
        "capture_complete": capture_complete,
        "estimator_health_qualified": health,
        "post_origin_trajectory_qualified": post_origin_qualified,
        "full_motion_trajectory_qualified": full_motion_qualified,
        "trajectory_qualified": full_motion_qualified,
        "reasons": list(dict.fromkeys(reasons)),
        "truth_used_online": False,
        "eligible_for_px4_fusion": False,
        "fusion_eligible": False,
        "flight_ready": False,
    }


def _strict_json(data, name):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key in {name}")
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON in {name}") from error


def _jsonl(data, name):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"invalid UTF-8 in {name}") from error
    if not text.endswith("\n"):
        raise ValueError(f"unterminated JSONL in {name}")
    return [_strict_json(line, name) for line in text.splitlines() if line]


def _write_exclusive(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def audit_pr48_archive(path, *, expected_sha256=PR48_SHA256, output=None):
    if output is not None and Path(output).exists():
        raise FileExistsError(output)
    archive_path = Path(path)
    archive_bytes = archive_path.read_bytes()
    archive_sha = hashlib.sha256(archive_bytes).hexdigest()
    if archive_sha != expected_sha256:
        raise ValueError("archive SHA mismatch")
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive member")
        for name in names:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError("unsafe archive member")
        if archive.testzip() is not None:
            raise ValueError("archive CRC failure")
        manifest = _strict_json(archive.read("SHA256-MANIFEST.json"), "manifest")
        consumed = {}
        payloads = {}
        for role, name in PR48_MEMBERS.items():
            if name not in manifest:
                raise ValueError(f"manifest missing {name}")
            data = archive.read(name)
            identity = manifest[name]
            digest = hashlib.sha256(data).hexdigest()
            if identity != {"bytes": len(data), "sha256": digest}:
                raise ValueError(f"manifest mismatch for {name}")
            consumed[role] = {"path": name, "bytes": len(data), "sha256": digest}
            payloads[role] = data

    audit = _strict_json(payloads["audit"], "audit")
    anchor = _strict_json(payloads["anchor"], "anchor")
    motion = _strict_json(payloads["motion"], "motion")
    native_session = _strict_json(payloads["session"], "session")
    states = _jsonl(payloads["states"], "states")
    truth = _jsonl(payloads["truth"], "truth")
    contract = trajectory_contract(
        anchor_ns=anchor.get("anchor_ns"),
        total_duration_ns=motion.get("total_duration_ns"),
        lateral_start_offset_ns=motion.get("lateral_start_after_anchor_ns"),
    )
    session = {
        "session_id": consumed["session"]["sha256"],
        "reset_counter": native_session.get("reset_counter"),
        "quality": native_session.get("quality"),
        "reset_observed": False,
        "covariance_calibrated": bool(audit.get("covariance_calibrated", False)),
    }
    result = audit_trajectory(
        states,
        truth,
        session,
        {"status": audit.get("capture_status"), "end_sim_ns": audit.get("end_sim_ns")},
        contract,
    )
    result.update(
        archive_sha256=archive_sha,
        consumed_members=consumed,
        consumed_members_verified=True,
        source_capture="PR48 supported-ready-shadow-v1 retained failure",
    )
    if output is not None:
        _write_exclusive(output, result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-sha256", default=PR48_SHA256)
    args = parser.parse_args()
    result = audit_pr48_archive(args.archive, expected_sha256=args.expected_sha256, output=args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
