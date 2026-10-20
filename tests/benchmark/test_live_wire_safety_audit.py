"""Offline joins use the production watchdog, motion gate and gauge policy."""

import copy
import io
import json

import pytest

from tests.benchmark.test_motion_intent_gate import command, estimator, native_ack
from tests.benchmark.test_trajectory_gauge_contract import small_input
from tools.benchmark import audit_live_wire_study as audit
from tools.benchmark.motion_intent_gate import MotionIntentGate
from tools.benchmark.openvins_online_shadow import SourceWatchdog
from tools.benchmark.readiness_anchor import AnchoredPolicy, anchored_profile
from tools.benchmark.supported_excitation import MASSES
from tools.benchmark.trajectory_gauge_contract import trajectory_gauge_policy

END, STEP, START = 25_000_000_000, 1_000_000, 1_000_000_000


def api(name):
    fn = getattr(audit, name, None)
    assert callable(fn), "missing safety audit API: " + name
    return fn


def source_fixture():
    sources = []
    for kind, samples in [
        ("imu", [STEP, *range(4_000_000, END + 1, 4_000_000)]),
        ("rgb", [2_000_000, *range(100_000_000, END + 1, 100_000_000)]),
        ("info", [2_000_000, *range(100_000_000, END + 1, 100_000_000)]),
    ]:
        offset = {"imu": 1, "info": 2, "rgb": 3}[kind]
        for sample in samples:
            sources.append(dict(kind=kind, arrival_monotonic_ns=START + sample * 2 + offset))
    sources.sort(key=lambda row: row["arrival_monotonic_ns"])
    guard = SourceWatchdog(startup_timeout_ns=10_000_000_000)
    guard.start(START)
    for row in sources:
        guard.observe(row["kind"], row["arrival_monotonic_ns"])
    trace = [
        dict(phase=phase, sim_ns=ns, wall_ns=START + ns * 2 + offset)
        for ns in range(STEP, END + 1, STEP)
        for phase, offset in [("pre", 0), ("post", 10)]
    ]
    return dict(sources=sources, trace=trace, terminal=guard.snapshot(), capture_start_ns=START - 1, watchdog_failure=None)


def test_recorded_source_intervals_pass_without_claiming_check_call_journal():
    out = api("audit_source_health_records")(**source_fixture())
    assert out["physical_presteps_checked"] == 25000
    assert out["recorded_arrival_constraints_passed"] is True
    assert out["every_runtime_watchdog_call_observed"] is False
    assert out["fusion_qualified"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "silence",
        "missing",
        "regressed_kind",
        "last_arrival",
        "ready",
        "ttl",
        "startup",
        "future_start",
        "bool_time",
        "failure",
        "step_gap",
    ],
)
def test_source_health_refusals(fault):
    f = source_fixture()
    if fault == "silence":
        # Keep counts and final snapshot but make a genuine >2s interval.
        for row in f["sources"]:
            if row["kind"] == "imu" and 5_000_000_000 < row["arrival_monotonic_ns"] < 7_100_000_000:
                row["arrival_monotonic_ns"] = 5_000_000_000 + (row["arrival_monotonic_ns"] - 5_000_000_000) // 100
    elif fault == "missing":
        f["sources"] = [r for r in f["sources"] if r["kind"] != "rgb"]
    elif fault == "regressed_kind":
        f["sources"][4]["arrival_monotonic_ns"] = 1
    elif fault == "last_arrival":
        f["terminal"]["last_arrivals"]["imu"] -= 1
    elif fault == "ready":
        f["terminal"]["ready_ns"] += 1
    elif fault == "ttl":
        f["terminal"]["operational_timeout_ns"] += 1
    elif fault == "startup":
        f["terminal"]["startup_timeout_ns"] += 1
    elif fault == "future_start":
        f["terminal"]["started_ns"] = END * 4
    elif fault == "bool_time":
        f["sources"][0]["arrival_monotonic_ns"] = True
    elif fault == "failure":
        f["watchdog_failure"] = dict(reason="source silence")
    elif fault == "step_gap":
        f["trace"].pop(100)
    with pytest.raises(ValueError):
        api("audit_source_health_records")(**f)


def motion_fixture():
    anchor_ns = 2_621_000_000
    selected = anchor_ns - 200_000_000
    issued = START + selected * 2 + 20
    now = [issued]
    stream = io.StringIO()
    gate = MotionIntentGate(
        session_id="native-42",
        clock_id="gazebo-sim+linux-monotonic",
        stream=stream,
        clock=lambda: now[0],
        native_adapter_integrated=True,
    )
    camera = estimator(acknowledged_ns=issued - 10)
    gate.observe_estimator(camera)
    cmd = command(issued_monotonic_ns=issued, velocity_setpoint_frd_m_s=[0.0, 0.0, -0.2], yaw_rate_setpoint_rad_s=0.0)
    action = gate.request(cmd)
    ack = native_ack(action, receive_ns=issued + 4, start_ns=issued + 5, end_ns=issued + 6, acknowledged_ns=issued + 7)
    now[0] = issued + 8
    gate.acknowledge(ack)
    gate_terminal = gate.finish()
    raw_ack = {k: v for k, v in ack.items() if k != "native_sequence"}
    raw_ack.update(
        sequence=ack["native_sequence"], quality=None, fusion_eligible=False, dispatch_ns=issued + 3, source_arrival_ns=issued
    )
    raw_camera = dict(
        kind="C",
        sequence=camera["native_sequence"],
        sample_ns=camera["sample_ns"],
        acknowledged_ns=camera["acknowledged_ns"],
        internal_initialized=True,
        has_moved_since_zupt=camera["has_moved_since_zupt"],
        reset_counter=None,
    )
    proof = dict(checked_wall_ns=issued - 11, records=dict(heartbeat=dict(system_id=9, base_mode=29)))
    current = [0]
    anchors = []
    policy = AnchoredPolicy(lambda: proof if current[0] >= selected else None, anchors.append)
    forces, trace = [], []
    for ns in range(STEP, END + 1, STEP):
        current[0] = ns
        wall = START + ns * 2
        trace.extend([dict(phase="pre", sim_ns=ns, wall_ns=wall), dict(phase="post", sim_ns=ns, wall_ns=wall + 100)])
        force = policy.step(ns, STEP, unarmed_wall_ns=wall, wall_ns=wall)
        if any(force):
            forces.append(
                dict(
                    sim_ns=ns,
                    dt_ns=STEP,
                    force_world_n=force,
                    call_returned=True,
                    wall_ns=wall + 50,
                    per_link=[
                        dict(name=name, force_world_n=[v * mass / sum(MASSES.values()) for v in force], call_returned=True)
                        for name, mass in MASSES.items()
                    ],
                )
            )
    terminal = dict(
        policy.finish(), motion_intent_prepared=True, close_errors=[], recorded_commands=len(forces), last_attempt=forces[-1]
    )
    return dict(
        anchor=anchors[0],
        profile=anchored_profile(),
        forces=forces,
        trace=trace,
        intent_records=[json.loads(line) for line in stream.getvalue().splitlines()],
        requests=[dict(action=action, sequence=ack["native_sequence"])],
        acknowledgements=[raw_camera, raw_ack],
        intent_terminal=gate_terminal,
        motion_terminal=terminal,
        session_id="native-42",
    )


def test_motion_intent_and_force_waveform_reuse_frozen_producers():
    out = api("audit_motion_records")(**motion_fixture())
    assert out["lateral_steps"] == 1600
    assert out["motion_intent_replayed"] is True
    assert out["per_step_readiness_calls_observed"] is False
    assert out["fusion_qualified"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "missing_force",
        "duplicate_force",
        "wrong_force",
        "link_force",
        "missing_link",
        "failed_call",
        "early_call",
        "late_ack",
        "wrong_anchor",
        "wrong_profile",
        "command_source",
        "command_velocity",
        "raw_ack",
        "no_native_motion",
        "different_session",
        "intent_terminal",
        "motion_terminal",
        "armed",
        "extra_record",
    ],
)
def test_motion_corruption_refused(fault):
    f = motion_fixture()
    if fault == "missing_force":
        f["forces"].pop(100)
    elif fault == "duplicate_force":
        f["forces"].insert(100, copy.deepcopy(f["forces"][100]))
    elif fault == "wrong_force":
        f["forces"][100]["force_world_n"][1] = 1.0
    elif fault == "link_force":
        f["forces"][100]["per_link"][0]["force_world_n"][2] += 0.1
    elif fault == "missing_link":
        f["forces"][100]["per_link"].pop()
    elif fault == "failed_call":
        f["forces"][100]["per_link"][0]["call_returned"] = False
    elif fault == "early_call":
        f["forces"][0]["wall_ns"] = 1
    elif fault == "late_ack":
        f["acknowledgements"][-1]["acknowledged_ns"] = f["forces"][0]["wall_ns"] + 1
    elif fault == "wrong_anchor":
        f["anchor"]["anchor_ns"] += STEP
    elif fault == "wrong_profile":
        f["profile"]["force_world_y_n"] = 25.0
    elif fault == "command_source":
        f["intent_records"][1]["command"]["source"] = "truth-controller"
    elif fault == "command_velocity":
        f["intent_records"][1]["command"]["velocity_setpoint_frd_m_s"][2] = -0.3
    elif fault == "raw_ack":
        f["acknowledgements"][-1]["has_moved_since_zupt"] = False
    elif fault == "no_native_motion":
        f["acknowledgements"].pop()
    elif fault == "different_session":
        f["session_id"] = "native-43"
    elif fault == "intent_terminal":
        f["intent_terminal"]["physical_validation"] = True
    elif fault == "motion_terminal":
        f["motion_terminal"]["active_steps"] = 1599
    elif fault == "armed":
        f["anchor"]["proof"]["records"]["heartbeat"]["base_mode"] = 128
    elif fault == "extra_record":
        f["intent_records"].append(dict(event="hidden-reset"))
    with pytest.raises(ValueError):
        api("audit_motion_records")(**f)


def gauge_fixture():
    states, truth, _, _, _ = small_input()
    raw = [dict(row, post_ns=row["sim_ns"], truth_for_abort_audit_only=True) for row in truth]
    for row in raw:
        del row["sim_ns"], row["truth_for_fixture_audit_only"]
    return dict(
        states=states,
        reference=raw,
        policy=trajectory_gauge_policy(),
        anchor=dict(anchor_ns=1_622_000_000),
        motion_profile=anchored_profile(),
        health_terminal=dict(session_id="native-42", reset_counter=0, reset_total=0, last_quality=0),
        result=dict(status="capture_completed", end_sim_ns=END),
    )


def test_gauge_keeps_startup_and_missing_public_coverage_visible():
    out = api("audit_gauge_records")(**gauge_fixture())
    assert out["origin"]["sample_ns"] == 2_400_000_000
    assert out["startup_unavailable"]["duration_ns"] == 778_000_000
    assert out["public_coverage_qualified"] is False
    assert out["metrics"]["max_position_error_m"] < 1e-10
    assert out["fusion_qualified"] is False


@pytest.mark.parametrize("fault", ["policy_scale", "time_shift", "profile_duration", "truth_scope", "missing_truth"])
def test_gauge_does_not_relax_frozen_policy(fault):
    f = gauge_fixture()
    if fault == "policy_scale":
        f["policy"]["scale"] = 2.0
    elif fault == "time_shift":
        f["policy"]["time_shift_ns"] = 1
    elif fault == "profile_duration":
        f["motion_profile"]["total_duration_ns"] -= STEP
    elif fault == "truth_scope":
        f["reference"][0]["truth_for_abort_audit_only"] = False
    elif fault == "missing_truth":
        f["reference"].pop(0)
    with pytest.raises(ValueError):
        api("audit_gauge_records")(**f)
