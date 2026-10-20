"""Synthetic native intent, receipt journals and force calls on one test clock.

The production readiness/intent/force policies run here, but no native worker,
force API or dynamics engine runs. The static pose fixture is independent of the
force commands: it tests record composition, not mechanical or VIO accuracy.
"""

import hashlib
import io
import json
from bisect import bisect_right

from tools.benchmark.estimator_aware_readiness import EstimatorAwareReadiness
from tools.benchmark.motion_intent_gate import MotionIntentGate
from tools.benchmark.openvins_online_shadow import encode_packet, project_motion_intent_ack
from tools.benchmark.readiness_anchor import AnchoredPolicy, JournaledReadiness, anchored_profile
from tools.benchmark.ready_shadow_fanout import digest
from tools.benchmark.supported_excitation import MASSES
from tools.benchmark.trajectory_gauge_contract import trajectory_gauge_policy

STEP = 1_000_000
CLOCK_ID = "gazebo-sim+linux-monotonic"
SCOPE = "sensor fan-out commit plus independent heartbeat write/flush; heartbeat reconciliation is separate; not fsync durability"


def write_lines(directory, name, rows):
    with (directory / name).open("x", encoding="utf8") as stream:
        for row in rows:
            stream.write(json.dumps(row, allow_nan=False) + "\n")


def build_motion(source, trace, directory):
    camera = next(row for row in source["acknowledgements"] if row["kind"] == "C" and row["internal_initialized"])
    # Causal delivery occurs at the following 4 ms IMU, then select the next
    # actual retained 1 ms pre-step. No arbitrary/post-hoc trajectory origin.
    selected = camera["sample_ns"] + 5 * STEP
    pre, post = trace[2 * (selected // STEP - 1) : 2 * (selected // STEP - 1) + 2]
    issued = pre["wall_ns"]
    now, stream = [issued], io.StringIO()
    gate = MotionIntentGate(
        session_id=source["session_id"],
        clock_id=CLOCK_ID,
        stream=stream,
        clock=lambda: now[0],
        native_adapter_integrated=True,
    )
    gate.observe_estimator(
        dict(
            kind="C",
            native_sequence=camera["sequence"],
            sample_ns=camera["sample_ns"],
            acknowledged_ns=camera["acknowledged_ns"],
            internal_initialized=True,
            has_moved_since_zupt=camera["has_moved_since_zupt"],
            reset_counter=None,
        )
    )
    action = gate.request(
        dict(
            session_id=source["session_id"],
            clock_id=CLOCK_ID,
            command_sequence=0,
            effective_sim_ns=selected + 200_000_000,
            issued_monotonic_ns=issued,
            unarmed=True,
            safety_authorized=True,
            velocity_setpoint_frd_m_s=[0.0, 0.0, -0.2],
            yaw_rate_setpoint_rad_s=0.0,
            source="px4-safe-setpoint-supervisor",
        )
    )
    number = camera["sequence"] + 1
    ack = dict(
        sequence=number,
        kind="M",
        sample_ns=action["sample_ns"],
        receive_ns=issued + 1,
        start_ns=issued + 2,
        end_ns=issued + 3,
        acknowledged_ns=post["wall_ns"],
        source_arrival_ns=issued,
        dispatch_ns=issued,
        intent_sha256=action["intent_sha256"],
        estimator_session_sha256=hashlib.sha256(source["session_id"].encode()).hexdigest(),
        clock_id_sha256=hashlib.sha256(CLOCK_ID.encode()).hexdigest(),
        command_sequence=0,
        internal_initialized=True,
        has_moved_since_zupt=True,
        motion_intent_applied=True,
        try_zupt=True,
        zupt_only_at_beginning=True,
        reset_counter=None,
        fusion_eligible=False,
        quality=None,
    )
    source["requests"].insert(number, dict(sequence=number, action=action, dispatch_ns=issued))
    source["acknowledgements"].insert(number, ack)
    # Packet identity includes the native sequence. Re-encode after insertion;
    # never adjust only the JSON sequence while leaving an old request hash.
    for sequence, (request, native) in enumerate(zip(source["requests"], source["acknowledgements"], strict=True)):
        native["sequence"] = request["sequence"] = sequence
        pixels = b"\x20" * 57600 if native["kind"] == "C" else None
        packet = encode_packet(request["action"], sequence=sequence, dispatch_ns=request["dispatch_ns"], pixels=pixels)
        request.update(
            bytes=len(packet),
            packet_sha256=hashlib.sha256(packet).hexdigest(),
            rgb_sha256=hashlib.sha256(pixels).hexdigest() if pixels else None,
        )
        if native["kind"] == "C" and sequence > number:
            native["has_moved_since_zupt"] = True
    source["states"] = [
        {k: v for k, v in row.items() if k not in {"acknowledged_ns", "source_arrival_ns", "dispatch_ns"}}
        for row in source["acknowledgements"]
        if row["kind"] == "C"
    ]
    now[0] = ack["acknowledged_ns"]
    gate.acknowledge(project_motion_intent_ack(ack, action))
    gate.authorize_step(action["sample_ns"])
    intent_terminal = gate.finish()
    intent_records = [json.loads(line) for line in stream.getvalue().splitlines()]

    # Reuse actual source and estimator readiness receipts with the synthetic
    # clocks already inside each recorded fan-out consumer call.
    now[0] = 1
    readiness = JournaledReadiness(clock=lambda: now[0])
    estimator = EstimatorAwareReadiness(directory, readiness, clock=lambda: now[0], session_id=source["session_id"])
    heartbeat_records, selected_proof = [], None
    by_arrival = {}
    arrivals = [row["arrival_monotonic_ns"] for row in source["sources"]]
    for native in source["acknowledgements"]:
        if native["kind"] in ("I", "C"):
            # A camera retains its original image arrival, but is acknowledged
            # inside the later IMU delivery that releases it. Attribute the
            # readiness receipt to that actual dispatch window, not the image.
            delivery_arrival = arrivals[bisect_right(arrivals, native["dispatch_ns"]) - 1]
            by_arrival.setdefault(delivery_arrival, []).append(native)
    heartbeat_count = 0
    try:
        for row in source["sources"]:
            wall = row["arrival_monotonic_ns"]
            if selected_proof is None and wall > issued:
                now[0] = issued
                selected_proof = estimator.proof()
                if selected_proof is None:
                    raise ValueError("synthetic selection did not have causal internal state")
                selected_proof["scope"] = SCOPE
            if row["kind"] == "heartbeat":
                original = {
                    k: v
                    for k, v in row.items()
                    if k not in {"source_sequence", "writer_begin_monotonic_ns", "recorded_monotonic_ns"}
                }
                now[0] = wall + 2
                observation = dict(
                    event="heartbeat_observed",
                    observation_sequence=heartbeat_count,
                    source_sha256=digest(original),
                    arrival_monotonic_ns=wall,
                    observed_ns=now[0],
                    original=original,
                )
                heartbeat_records.append(observation)
                readiness.on_record(dict(original, writer_begin_monotonic_ns=now[0], recorded_monotonic_ns=now[0]), None)
                heartbeat_records.append(
                    dict(
                        event="heartbeat_reconciled",
                        observation_sequence=heartbeat_count,
                        source_sequence=row["source_sequence"],
                        source_sha256=digest(original),
                        reconciled_ns=wall + 72,
                    )
                )
                heartbeat_count += 1
            elif row["kind"] in ("imu", "rgb", "info"):
                now[0] = wall + 69
                estimator.observe_ack_batch(by_arrival.get(wall, []), row)
                now[0] = wall + 72
                readiness.on_record(row, None)
    finally:
        estimator.finish()
    estimator_records = [json.loads(line) for line in (directory / "estimator-readiness.jsonl").read_text().splitlines()]

    current, anchors, forces = [0], [], []
    policy = AnchoredPolicy(lambda: selected_proof if current[0] >= selected else None, anchors.append)
    for pre in trace[::2]:
        current[0] = pre["sim_ns"]
        force = policy.step(current[0], STEP, unarmed_wall_ns=pre["wall_ns"], wall_ns=pre["wall_ns"])
        if not any(force):
            continue
        forces.append(
            dict(
                sim_ns=current[0],
                dt_ns=STEP,
                force_world_n=force,
                call_returned=True,
                wall_ns=pre["wall_ns"],
                per_link=[
                    dict(name=name, force_world_n=[v * mass / sum(MASSES.values()) for v in force], call_returned=True)
                    for name, mass in MASSES.items()
                ],
            )
        )
    motion_terminal = dict(
        policy.finish(), motion_intent_prepared=True, close_errors=[], recorded_commands=len(forces), last_attempt=forces[-1]
    )
    anchor = anchors[0]
    for name, rows in (
        ("synthetic-motion-intent.jsonl", intent_records),
        ("synthetic-forces.jsonl", forces),
        ("synthetic-heartbeat-observation.jsonl", heartbeat_records),
    ):
        write_lines(directory, name, rows)
    for name, value in (
        ("synthetic-readiness-anchor.json", anchor),
        ("synthetic-motion-result.json", motion_terminal),
        ("synthetic-motion-intent-result.json", intent_terminal),
        ("synthetic-gauge-policy.json", trajectory_gauge_policy()),
        ("synthetic-capture-result.json", dict(status="completed", end_sim_ns=25_000_000_000)),
    ):
        with (directory / name).open("x", encoding="utf8") as output:
            json.dump(value, output, allow_nan=False)
    return dict(
        anchor=anchor,
        profile=anchored_profile(),
        forces=forces,
        trace=trace,
        intent_records=intent_records,
        requests=source["requests"],
        acknowledgements=source["acknowledgements"],
        intent_terminal=intent_terminal,
        motion_terminal=motion_terminal,
        session_id=source["session_id"],
        estimator_records=estimator_records,
        heartbeat_records=heartbeat_records,
    )
