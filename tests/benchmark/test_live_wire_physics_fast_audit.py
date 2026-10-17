"""Raw offline coverage checks; synthetic rows never prove a physical run."""

import copy
import importlib

import pytest


def api(name):
    from tools.benchmark import audit_live_wire_study

    function = getattr(audit_live_wire_study, name, None)
    assert callable(function), f"missing raw coverage API: {name}"
    return function


def physical_fixture():
    state = dict(
        position=[0.0, 0.0, 0.5],
        velocity_world=[0.0, 0.0, 0.0],
        accel_world=[0.0, 0.0, 0.0],
        angular_world=[0.0, 0.0, 0.0],
        quaternion_xyzw=[0.0, 0.0, 0.0, 1.0],
    )
    reference, trace, clock = [], [], []
    for i in range(1, 25001):
        ns, wall = i * 1_000_000, i * 10_000_000
        reference.append(
            dict(
                state,
                rpy=[0.0, 0.0, 0.0],
                parent_entity=24,
                child_entity=69,
                pre_ns=ns,
                post_ns=ns,
                canary_overwritten=True,
                wall_ns=wall + 3,
                truth_for_abort_audit_only=True,
                eligible_for_px4_fusion=False,
            )
        )
        clock.append(dict(iteration=i, sim_ns=ns, callback_ns=wall + 1, journal_return_ns=wall + 2))
        for phase, offset in [("pre", 0), ("post", 4)]:
            trace.append(
                dict(
                    state,
                    phase=phase,
                    sim_ns=ns,
                    dt_ns=1_000_000,
                    state_time_ns=ns - 1_000_000 if phase == "pre" else ns,
                    state_time_basis="callback_phase_only",
                    component_refresh_verified=False,
                    wall_ns=wall + offset,
                    available=True,
                    truth_for_diagnostics_only=True,
                )
            )
    terminal = dict(
        pre_count=25000,
        post_count=25000,
        failure=None,
        close_errors=[],
        complete=True,
        eligible_for_px4_fusion=False,
        native=dict(failed=False, pending=False, last_ns=25_000_000_000),
        last_attempt=dict(phase="post", ns_repr="25000000000", wall_ns=250_000_000_002),
    )
    trace_terminal = dict(
        records=50000,
        unavailable_records=0,
        failure=None,
        close_errors=[],
        complete=True,
        backend_recorded=True,
        eligible_for_px4_fusion=False,
        last_attempt=dict(phase="post", sim_ns_repr="25000000000", record_index=49999),
    )
    return dict(reference=reference, trace=trace, observations=clock, terminal=terminal, trace_terminal=trace_terminal)


def test_complete_physical_coverage():
    result = api("audit_physical_coverage_records")(**physical_fixture())
    assert result["reference_cycles"] == 25000
    assert result["trace_records"] == 50000
    assert result["old_link_refresh_qualified"] is False
    assert result["live_qualified"] is False
    assert result["fusion_qualified"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "missing_reference",
        "missing_trace",
        "clock_step",
        "bool_epoch",
        "entity_change",
        "canary",
        "quaternion",
        "rpy",
        "speed",
        "displacement",
        "backward_wall",
        "before_clock_commit",
        "post_before_reference",
        "early_terminal",
        "close_error",
        "trace_refresh_claim",
        "trace_final_unavailable",
        "trace_count",
        "nonfinite",
        "terminal_wall",
    ],
)
def test_physical_corruption_refused(fault):
    f = physical_fixture()
    row = copy.deepcopy(f["reference"][999])
    f["reference"][999] = row
    if fault == "missing_reference":
        f["reference"].pop()
    elif fault == "missing_trace":
        f["trace"].pop()
    elif fault == "clock_step":
        f["observations"][999]["sim_ns"] += 1
    elif fault == "bool_epoch":
        row["pre_ns"] = True
    elif fault == "entity_change":
        row["child_entity"] = 70
    elif fault == "canary":
        row["canary_overwritten"] = False
    elif fault == "quaternion":
        row["quaternion_xyzw"] = [0.0, 0.0, 0.0, 2.0]
    elif fault == "rpy":
        row["rpy"] = [0.0, 0.0, 1.0]
    elif fault == "speed":
        row["velocity_world"] = [3.01, 0.0, 0.0]
    elif fault == "displacement":
        row["position"] = [1.01, 0.0, 0.5]
    elif fault == "backward_wall":
        row["wall_ns"] = 1
    elif fault == "before_clock_commit":
        row["wall_ns"] = f["observations"][999]["callback_ns"]
    elif fault == "post_before_reference":
        f["trace"][1999]["wall_ns"] = row["wall_ns"] - 1
    elif fault == "early_terminal":
        f["terminal"]["native"]["last_ns"] -= 1_000_000
    elif fault == "close_error":
        f["terminal"]["close_errors"] = ["close failed"]
    elif fault == "trace_refresh_claim":
        f["trace"][1999]["component_refresh_verified"] = True
    elif fault == "trace_final_unavailable":
        f["trace"][-1]["available"] = False
    elif fault == "trace_count":
        f["trace_terminal"]["records"] = 49999
    elif fault == "nonfinite":
        row["accel_world"] = [float("nan"), 0.0, 0.0]
    elif fault == "terminal_wall":
        f["terminal"]["last_attempt"]["wall_ns"] = 1
    with pytest.raises(ValueError):
        api("audit_physical_coverage_records")(**f)


def fast_fixture():
    acknowledgements, records = [], []
    last_camera = None
    target = 20_000_000
    for sample in [1_000_000, *range(4_000_000, 25_000_000_001, 4_000_000)]:
        seq = len(acknowledgements)
        ack = dict(
            sequence=seq, kind="I", sample_ns=sample, receive_ns=sample * 10, start_ns=sample * 10 + 1, end_ns=sample * 10 + 1000
        )
        acknowledgements.append(ack)
        while target < sample:
            ready = last_camera is not None
            records.append(
                dict(
                    target_ns=target,
                    last_camera_ns=last_camera,
                    available_imu_ns=sample,
                    filter_time_s=last_camera * 1e-9 if ready else -1.0,
                    camera_imu_offset_s=0.0,
                    internal_initialized=ready,
                    public_initialized=ready,
                    success=ready,
                    filter_unchanged=True,
                    propagation_wall_s=1e-9,
                    state13=[0.0, 0.0, 0.0, 1.0, *([0.0] * 9)] if ready else None,
                    covariance12=[[0.01 if i == j else 0.0 for j in range(12)] for i in range(12)] if ready else None,
                    trigger_sequence=seq,
                    native_begin_ns=ack["start_ns"] + 1,
                    native_end_ns=ack["start_ns"] + 100,
                    fusion_eligible=False,
                    quality=None,
                    reset_counter=None,
                )
            )
            target += 20_000_000
        # Same producer order as the causal consumer: image after later IMU.
        if sample % 100_000_000 == 4_000_000 and sample > 100_000_000:
            last_camera = sample - 4_000_000
            acknowledgements.append(
                dict(
                    sequence=len(acknowledgements),
                    kind="C",
                    sample_ns=last_camera,
                    receive_ns=sample * 10 + 1001,
                    start_ns=sample * 10 + 1002,
                    end_ns=sample * 10 + 2000,
                    internal_initialized=True,
                    public_initialized=True,
                    state_time_s=last_camera * 1e-9,
                )
            )
    return dict(records=records, acknowledgements=acknowledgements, end_sim_ns=25_000_000_000)


def test_unique_fast_targets_join_actual_imu_call():
    result = api("audit_fast_coverage_records")(**fast_fixture())
    assert result["targets"] == 1249
    assert result["successful_targets"] > 1200
    assert result["fusion_qualified"] is False
    assert result["accuracy_qualified"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "gap",
        "duplicate",
        "old_origin",
        "bool_target",
        "wrong_trigger",
        "future_imu",
        "wrong_camera",
        "begin_before_call",
        "end_after_ack",
        "mutated_filter",
        "quality",
        "public_before_internal",
        "filter_time",
        "covariance",
        "state",
        "failed_state",
        "timing_nan",
        "bool_sequence",
        "ack_gap",
        "unknown_field",
    ],
)
def test_fast_corruption_refused(fault):
    f = fast_fixture()
    r = f["records"][20]
    if fault == "gap":
        f["records"].pop(20)
    elif fault == "duplicate":
        f["records"].insert(20, copy.deepcopy(r))
    elif fault == "old_origin":
        for row in f["records"]:
            row["target_ns"] += 1_000_000
    elif fault == "bool_target":
        r["target_ns"] = True
    elif fault == "wrong_trigger":
        r["trigger_sequence"] += 1
    elif fault == "future_imu":
        r["available_imu_ns"] += 4_000_000
    elif fault == "wrong_camera":
        r["last_camera_ns"] -= 100_000_000
    elif fault == "begin_before_call":
        r["native_begin_ns"] = 1
    elif fault == "end_after_ack":
        r["native_end_ns"] += 100_000_000
    elif fault == "mutated_filter":
        r["filter_unchanged"] = False
    elif fault == "quality":
        r["quality"] = 1
    elif fault == "public_before_internal":
        r["internal_initialized"] = False
    elif fault == "filter_time":
        r["filter_time_s"] += 0.1
    elif fault == "covariance":
        r["covariance12"][0][0] = -0.1
    elif fault == "state":
        r["state13"][3] = 2.0
    elif fault == "failed_state":
        f["records"][0]["state13"] = r["state13"]
    elif fault == "timing_nan":
        r["propagation_wall_s"] = float("nan")
    elif fault == "bool_sequence":
        f["acknowledgements"][0]["sequence"] = False
    elif fault == "ack_gap":
        f["acknowledgements"].pop(1)
    elif fault == "unknown_field":
        r["estimated_quality"] = 1
    with pytest.raises(ValueError):
        api("audit_fast_coverage_records")(**f)


def test_audit_import_does_not_require_simulator():
    module = importlib.import_module("tools.benchmark.audit_live_wire_study")
    assert module is not None
