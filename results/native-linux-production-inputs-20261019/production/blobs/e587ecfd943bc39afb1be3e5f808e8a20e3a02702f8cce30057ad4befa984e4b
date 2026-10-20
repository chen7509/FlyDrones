"""Offline physical/fast-output joins, with no simulator or estimator execution."""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial.transform import Rotation

from tools.benchmark.audit_live_wire_study import _equal, _integer, _shape
from tools.benchmark.build_openvins_ekf2_fast_run_evidence import fast_grid_qualified
from tools.benchmark.disarmed_motion_probe import MotionPolicy
from tools.benchmark.openvins_ekf2_fast_contract import fast_sample_timing_qualified, transform_fast12
from tools.benchmark.openvins_health_contract import CovarianceProfile, OpenVinsHealthContract
from tools.benchmark.openvins_online_shadow import project_camera_health_row
from tools.benchmark.physics_substep_trace import _state

END = 25_000_000_000
STEP = 1_000_000
STATE = {"position", "velocity_world", "accel_world", "angular_world", "quaternion_xyzw"}


def audit_health_coverage_records(*, states, records, terminal, shadow_last, session_id, profile_name):
    """Reproduce normal single-session derived health, never adopt terminal grants.

    The frozen capture constructs an unqualified CovarianceProfile even when
    separate historical cohorts passed. Source/native success here is the same
    default passed by ShadowInput, not independent watchdog evidence. Such
    evidence and a separately authorized publication path remain prerequisites.
    """
    _equal(profile_name, "px4-d6f12ad-gate-floor-v1", "frozen health profile")
    if type(states) is not list or len(states) != 250 or type(records) is not list or len(records) != len(states):
        raise ValueError("incomplete camera health coverage")
    contract = OpenVinsHealthContract(session_id, profile=CovarianceProfile())
    source = dict(source_healthy=True, native_healthy=True, source_failure=None, native_failure=None)
    qualities, last = set(), None
    for state, record in zip(states, records, strict=True):
        for field, expected in dict(kind="C", fusion_eligible=False, quality=None, reset_counter=None).items():
            _equal(state[field], expected, "original native health " + field)
        projected = project_camera_health_row(state, session_id=session_id)
        last = contract.accept_camera(projected, source)
        if last["quality"] < 0 or last["failed_latched"]:
            raise ValueError("native camera health failed: " + repr(last["reasons"]))
        _equal(
            record,
            dict(
                event="camera_health",
                native_sequence=state["sequence"],
                sample_ns=state["sample_ns"],
                projected=projected,
                health=last,
                fusion_eligible=False,
            ),
            "derived camera health",
        )
        qualities.add(last["quality"])
    expected = dict(
        schema="openvins-online-health-result-v1",
        session_id=session_id,
        session_count=1,
        reset_total=0,
        reset_counter=0,
        last_quality=last["quality"],
        last_health=last,
        covariance_profile=profile_name,
        covariance_sim_domain_qualified=False,
        fusion_eligible=False,
    )
    _equal(terminal, expected, "health terminal replay")
    _equal(shadow_last, last, "shadow final health projection")
    return dict(
        camera_health_records=len(records),
        session_id=session_id,
        reset_total=0,
        quality_values=sorted(qualities),
        deterministic_projection_verified=True,
        covariance_sim_domain_qualified=False,
        hardware_covariance_calibrated=False,
        source_watchdog_qualified=False,
        live_qualified=False,
        fusion_qualified=False,
    )


def audit_physical_coverage_records(*, reference, trace, observations, terminal, trace_terminal):
    """Join fresh native canary rows and old Link callbacks to the retained clock.

    `observations` must also pass the existing full clock protocol audit. These
    are recorded assertions and numeric bounds, not an independent runtime or
    truth-authenticity proof. Old Link components are deliberately not compared
    numerically with fresh child components: their caching is already diagnosed.
    """
    for rows, length in ((reference, 25000), (trace, 50000), (observations, 25000)):
        if type(rows) is not list or len(rows) != length:
            raise ValueError("incomplete physical callback coverage")
    for key, value in dict(
        pre_count=25000,
        post_count=25000,
        failure=None,
        close_errors=[],
        complete=True,
        eligible_for_px4_fusion=False,
        native=dict(failed=False, pending=False, last_ns=END),
    ).items():
        _equal(terminal[key], value, "reference terminal " + key)
    _equal(terminal["last_attempt"]["phase"], "post", "last reference phase")
    _equal(terminal["last_attempt"]["ns_repr"], str(END), "last reference epoch")
    for key, value in dict(
        records=50000, failure=None, close_errors=[], complete=True, backend_recorded=True, eligible_for_px4_fusion=False
    ).items():
        _equal(trace_terminal[key], value, "trace terminal " + key)
    _equal(trace_terminal["last_attempt"], dict(phase="post", sim_ns_repr=str(END), record_index=49999), "last trace attempt")
    policy, identities, previous_wall, unavailable = MotionPolicy(), None, 0, 0
    reference_keys = STATE | {
        "rpy",
        "parent_entity",
        "child_entity",
        "pre_ns",
        "post_ns",
        "canary_overwritten",
        "wall_ns",
        "truth_for_abort_audit_only",
        "eligible_for_px4_fusion",
    }
    trace_keys = {
        "phase",
        "sim_ns",
        "dt_ns",
        "state_time_ns",
        "state_time_basis",
        "component_refresh_verified",
        "wall_ns",
        "available",
        "truth_for_diagnostics_only",
    }
    for index, (row, clock) in enumerate(zip(reference, observations, strict=True), 1):
        ns = index * STEP
        _shape(row, reference_keys, "native reference")
        _shape(clock, ("iteration", "sim_ns", "callback_ns", "journal_return_ns"), "physical clock")
        _equal(clock["iteration"], index, "physical iteration")
        _equal(clock["sim_ns"], ns, "physical clock step")
        for key in ("pre_ns", "post_ns"):
            _equal(row[key], ns, "native reference epoch")
        for key, value in dict(canary_overwritten=True, truth_for_abort_audit_only=True, eligible_for_px4_fusion=False).items():
            _equal(row[key], value, "native reference " + key)
        entity = [row["parent_entity"], row["child_entity"]]
        for value in entity:
            _integer(value, 1, 2**63 - 1, "reference entity")
        if entity[0] == entity[1]:
            raise ValueError("reference child equals parent")
        if identities is None:
            identities = entity
        _equal(entity, identities, "reference entity stability")
        _state(row)
        policy.observe(row["position"], row["velocity_world"], row["rpy"])
        # Check the independent tilt monitor uses the same orientation, including
        # noncommuting attitudes; no Euler branch comparison or truth correction.
        error = (Rotation.from_euler("xyz", row["rpy"]).inv() * Rotation.from_quat(row["quaternion_xyzw"])).magnitude()
        if not math.isfinite(error) or error > 1e-6:
            raise ValueError("reference RPY/quaternion disagreement")
        pre, post = trace[2 * (index - 1) : 2 * index]
        for current, phase in ((pre, "pre"), (post, "post")):
            if type(current.get("available")) is not bool:
                raise ValueError("invalid trace availability")
            _shape(current, trace_keys | (STATE if current["available"] else set()), "old Link trace")
            for key, value in dict(
                phase=phase,
                sim_ns=ns,
                dt_ns=STEP,
                state_time_ns=ns - STEP if phase == "pre" else ns,
                state_time_basis="callback_phase_only",
                component_refresh_verified=False,
                truth_for_diagnostics_only=True,
            ).items():
                _equal(current[key], value, "trace " + key)
            if current["available"]:
                _state(current)
            elif ns >= 100_000_000:
                raise ValueError("late unavailable physical fields")
            else:
                unavailable += 1
        # bind_capture_wire calls clock.post_update before original_post;
        # original_post records fresh reference before old Link post trace.
        previous = previous_wall
        for stamp in (pre["wall_ns"], clock["callback_ns"], clock["journal_return_ns"], row["wall_ns"], post["wall_ns"]):
            _integer(stamp, previous, 2**63 - 1, "physical callback wall order")
            previous = stamp
        previous_wall = previous
    _equal(trace_terminal["unavailable_records"], unavailable, "trace availability total")
    _shape(terminal["last_attempt"], ("phase", "ns_repr", "wall_ns"), "last reference attempt")
    _integer(
        terminal["last_attempt"]["wall_ns"],
        observations[-1]["journal_return_ns"],
        reference[-1]["wall_ns"],
        "last reference attempt wall time",
    )
    return dict(
        reference_cycles=len(reference),
        trace_records=len(trace),
        clock_steps=len(observations),
        entity_pair=identities,
        recorded_canary_coverage=True,
        numeric_abort_bounds_passed=True,
        old_link_refresh_qualified=False,
        backend_independently_authenticated=False,
        live_qualified=False,
        fusion_qualified=False,
    )


def audit_fast_coverage_records(*, records, acknowledgements, end_sim_ns):
    """Check current aligned 50 Hz producer outputs against the actual I/C order.

    Acks must additionally pass the source/request/native audit. This doesn't
    recompute OpenVINS, qualify accuracy, or turn a predicted covariance into a
    calibration. Unavailable targets remain explicit, never filled from old data.
    """
    _equal(end_sim_ns, END, "fast physical end")
    if type(acknowledgements) is not list or not acknowledgements or len(acknowledgements) > 7000:
        raise ValueError("invalid native acknowledgements")
    imu = [row["sample_ns"] for row in acknowledgements if row["kind"] == "I"]
    _equal(imu, [STEP, *range(4_000_000, END + 1, 4_000_000)], "complete fast IMU input grid")
    if not fast_grid_qualified(records, imu[0], end_sim_ns):
        raise ValueError("incomplete/current aligned fast target grid")
    fields = {
        "target_ns",
        "last_camera_ns",
        "available_imu_ns",
        "filter_time_s",
        "camera_imu_offset_s",
        "internal_initialized",
        "public_initialized",
        "success",
        "filter_unchanged",
        "propagation_wall_s",
        "state13",
        "covariance12",
        "trigger_sequence",
        "native_begin_ns",
        "native_end_ns",
        "fusion_eligible",
        "quality",
        "reset_counter",
    }
    cursor, last_camera, camera_state, previous_end, successes, public = 0, None, None, 0, 0, 0
    next_target = 20_000_000
    for sequence, ack in enumerate(acknowledgements):
        _equal(ack["sequence"], sequence, "native sequence")
        if ack["kind"] not in ("I", "C", "M"):
            raise ValueError("unknown native kind")
        _integer(ack["receive_ns"], previous_end, 2**63 - 1, "native receive order")
        _integer(ack["start_ns"], ack["receive_ns"], 2**63 - 1, "native start")
        _integer(ack["end_ns"], ack["start_ns"], 2**63 - 1, "native end")
        previous_end = ack["end_ns"]
        if ack["kind"] == "C":
            _integer(ack["sample_ns"], 1 if last_camera is None else last_camera + 1, END, "camera sequence")
            last_camera, camera_state = ack["sample_ns"], ack
        if ack["kind"] != "I":
            continue
        while next_target < ack["sample_ns"]:
            if cursor >= len(records):
                raise ValueError("missing native prediction")
            row = records[cursor]
            _shape(row, fields, "fast native output")
            for key, value in dict(
                target_ns=next_target,
                trigger_sequence=sequence,
                available_imu_ns=ack["sample_ns"],
                last_camera_ns=last_camera,
                fusion_eligible=False,
                quality=None,
                reset_counter=None,
                filter_unchanged=True,
            ).items():
                _equal(row[key], value, "fast " + key)
            for key in ("internal_initialized", "public_initialized", "success"):
                if type(row[key]) is not bool:
                    raise ValueError("invalid fast boolean")
            for key in ("filter_time_s", "camera_imu_offset_s", "propagation_wall_s"):
                value = row[key]
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError("invalid fast numeric time")
            if row["camera_imu_offset_s"] != 0 or row["propagation_wall_s"] < 0:
                raise ValueError("unsupported offset/negative duration")
            _integer(row["native_begin_ns"], ack["start_ns"], ack["end_ns"], "fast begin")
            _integer(row["native_end_ns"], row["native_begin_ns"], ack["end_ns"], "fast end")
            # micro/nanosecond floating conversion can round by one ns.
            if row["propagation_wall_s"] * 1e9 > row["native_end_ns"] - row["native_begin_ns"] + 1:
                raise ValueError("propagation duration outside recorded call")
            for key in ("internal_initialized", "public_initialized"):
                _equal(row[key], camera_state[key] if camera_state else False, "fast last camera " + key)
            if row["public_initialized"] and not row["internal_initialized"]:
                raise ValueError("public fast state before internal initialization")
            if camera_state:
                if abs(row["filter_time_s"] - camera_state["state_time_s"]) > 1e-9:
                    raise ValueError("fast filter time disagrees with last camera state")
            if row["success"]:
                if not row["internal_initialized"] or not fast_sample_timing_qualified(
                    next_target, last_camera, ack["sample_ns"]
                ):
                    raise ValueError("prediction without initialized recent camera/IMU")
                if not 0 < next_target * 1e-9 - row["filter_time_s"] <= 0.1 + 1e-9:
                    raise ValueError("invalid prediction filter time")
                try:
                    transform_fast12(row["state13"], row["covariance12"])
                except (np.linalg.LinAlgError, FloatingPointError) as exc:
                    raise ValueError("invalid fast numerical range") from exc
                successes += 1
                public += int(row["public_initialized"])
            elif row["state13"] is not None or row["covariance12"] is not None:
                raise ValueError("unavailable prediction with fabricated state")
            cursor += 1
            next_target += 20_000_000
    _equal(cursor, len(records), "all native predictions consumed")
    return dict(
        targets=cursor,
        successful_targets=successes,
        unavailable_targets=cursor - successes,
        public_successful_targets=public,
        producer_grid="absolute-20ms-aligned",
        native_call_join_qualified=True,
        accuracy_qualified=False,
        covariance_calibrated=False,
        live_qualified=False,
        fusion_qualified=False,
    )
