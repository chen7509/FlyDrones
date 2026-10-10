"""Synthetic source/native protocol generator; no native estimator is run."""

import hashlib

from tools.benchmark.disarmed_sensor_provenance import validate_event
from tools.benchmark.openvins_causal_input import CausalInput, raw_profile
from tools.benchmark.openvins_online_shadow import encode_packet
from tools.benchmark.ready_shadow_fanout import digest


def build_chain(
    callback_clock_lag_ns=0, *, arrival_clock=None, info_payloads=None, session_id="synthetic-1", initialized_at_ns=None
):
    # This opt-in is synthetic native output, never an estimator implementation.
    if initialized_at_ns is not None and (
        type(initialized_at_ns) is not int or initialized_at_ns < 100_000_000 or initialized_at_ns % 100_000_000
    ):
        raise ValueError("synthetic initialization must select an existing camera epoch")
    schedule = [(1_000_000, "imu")]
    schedule += [(i * 4_000_000, "imu") for i in range(1, 6251)]
    for stamp in [2_000_000] + [i * 100_000_000 for i in range(1, 251)]:
        schedule += [(stamp, kind) for kind in ("info", "rgb", "depth")]
    schedule += [(i * 1_000_000_000, "heartbeat") for i in range(1, 25)]
    rows, fanout, requests, acks, states = [], [], [], [], []
    pixels, payloads = b"\x20" * 57600, {}
    causal = CausalInput(session_id=session_id, clock_id="gazebo-sim+linux-monotonic")
    input_sequence = 0
    for sequence, (stamp, kind) in enumerate(sorted(schedule)):
        wall = arrival_clock(stamp) if arrival_clock is not None else 10_000_000_000 + stamp + sequence * 100
        event = dict(kind=kind, arrival_monotonic_ns=wall, observed_sim_ns=max(0, stamp - callback_clock_lag_ns))
        if kind == "heartbeat":
            event.update(system_id=9, base_mode=29, custom_mode=0)
        else:
            event["sample_ns"] = stamp
            if kind == "imu":
                event.update(gyro_flu=[0.0, 0.0, 0.0], accel_flu=[0.0, 0.0, 9.81])
            elif kind == "info":
                event["camera_info"] = raw_profile()["camera_info"]
            else:
                event.update(width=160, height=120)
        row = dict(
            validate_event(event), source_sequence=sequence, writer_begin_monotonic_ns=wall + 1, recorded_monotonic_ns=wall + 2
        )
        payload = pixels if kind == "rgb" else b"synthetic protobuf" if kind == "info" else None
        if kind == "info" and info_payloads is not None:
            payload = info_payloads[stamp]
        if payload is not None:
            payloads[sequence] = payload
        if kind == "info":
            row.update(payload_path=f"camera-info-messages/{stamp}.pb", payload_sha256=hashlib.sha256(payload).hexdigest())
        rows.append(row)
        identity = dict(
            sequence_repr=repr(sequence),
            source_sequence=sequence,
            source_sha256=digest(row),
            payload_sha256=hashlib.sha256(payload).hexdigest() if payload else None,
            begin_ns=wall + 3,
        )
        fanout.append(
            dict(
                identity,
                event="source_intent",
                dispositions=dict(shadow="not_attempted", readiness="not_attempted"),
                consumers={},
            )
        )
        fanout.append(
            dict(
                identity,
                event="source_delivery",
                dispositions=dict(shadow="returned", readiness="returned"),
                consumers=dict(
                    shadow=dict(start_ns=wall + 4, returned_ns=wall + 70),
                    readiness=dict(start_ns=wall + 71, returned_ns=wall + 72),
                ),
                end_ns=wall + 73,
            )
        )
        if kind not in ("imu", "info", "rgb"):
            continue
        actions = causal.accept(event, sequence=input_sequence, session_id=causal.session_id, clock_id=causal.clock_id)
        input_sequence += 1
        for offset, action in enumerate(actions):
            number, dispatch = len(requests), wall + 10 + offset * 20
            image = pixels if action["kind"] == "camera" else None
            packet = encode_packet(action, sequence=number, dispatch_ns=dispatch, pixels=image)
            requests.append(
                dict(
                    sequence=number,
                    action=action,
                    dispatch_ns=dispatch,
                    bytes=len(packet),
                    packet_sha256=hashlib.sha256(packet).hexdigest(),
                    rgb_sha256=hashlib.sha256(image).hexdigest() if image else None,
                )
            )
            ack = dict(
                sequence=number,
                kind=chr(packet[0]),
                sample_ns=action["sample_ns"],
                receive_ns=dispatch + 1,
                start_ns=dispatch + 2,
                end_ns=dispatch + 3,
                gray_first=32 if image else -1,
                fusion_eligible=False,
                quality=None,
                reset_counter=None,
                acknowledged_ns=dispatch + 4,
                source_arrival_ns=action["source_arrival_ns"],
                dispatch_ns=dispatch,
            )
            if image:
                ack.update(
                    internal_initialized=False,
                    public_initialized=False,
                    initializer_time_s=-1,
                    state_time_s=-1,
                    last_regular_update_s=-1,
                    zupt_flag_latched=False,
                    has_moved_since_zupt=False,
                    imu_state=None,
                    imu_covariance15=None,
                )
                if initialized_at_ns is not None and action["sample_ns"] >= initialized_at_ns:
                    public = action["sample_ns"] > initialized_at_ns
                    ack.update(
                        internal_initialized=True,
                        public_initialized=public,
                        initializer_time_s=initialized_at_ns * 1e-9,
                        state_time_s=action["sample_ns"] * 1e-9,
                        last_regular_update_s=action["sample_ns"] * 1e-9 if public else -1.0,
                        # FRD relative to the fixture's identity world-from-FLU:
                        # 180 degrees about x, not identity. p/v/bias are known
                        # test values; they are not fed to any native process.
                        imu_state=[1.0, 0.0, 0.0, 0.0, *([0.0] * 12)],
                        imu_covariance15=[[0.01 if i == j else 0.0 for j in range(15)] for i in range(15)],
                    )
                states.append(
                    {
                        key: value
                        for key, value in ack.items()
                        if key not in {"acknowledged_ns", "source_arrival_ns", "dispatch_ns"}
                    }
                )
            acks.append(ack)
    terminal = dict(
        failure=None,
        inputs_accepted=input_sequence,
        delivered=6501,
        skipped_after_failure=0,
        pending=causal.finish(),
        retained_pixel_stamps=[25_000_000_000],
        released_unacknowledged=[],
        fusion_eligible=False,
        quality=None,
        reset_counter=None,
        last_delivery_acks=[],
        health_last=None,
    )
    return dict(
        sources=rows,
        fanout=fanout,
        requests=requests,
        acknowledgements=acks,
        states=states,
        payloads=payloads,
        terminal=terminal,
        session_id=session_id,
    )


def synthetic_fast_records(acknowledgements):
    """Known static test estimates on the absolute grid, not propagation output.

    Follow the supplied I/C dispatch order: a C arriving after the I that
    releases it cannot retroactively initialize predictions in that I call.
    Each successful state uses the preceding synthetic camera state only.
    """
    rows, camera, target = [], None, 20_000_000
    for ack in acknowledgements:
        if ack["kind"] == "C":
            camera = ack
        if ack["kind"] != "I":
            continue
        while target < ack["sample_ns"]:
            internal = camera is not None and camera["internal_initialized"]
            successful = internal and 0 < target - camera["sample_ns"] <= 100_000_000
            state = camera["imu_state"] if successful else None
            rows.append(
                dict(
                    target_ns=target,
                    last_camera_ns=camera["sample_ns"] if camera else None,
                    available_imu_ns=ack["sample_ns"],
                    filter_time_s=camera["state_time_s"] if camera else -1.0,
                    camera_imu_offset_s=0.0,
                    internal_initialized=internal,
                    public_initialized=camera["public_initialized"] if camera else False,
                    success=successful,
                    filter_unchanged=True,
                    propagation_wall_s=1e-9,
                    state13=[*state[:10], 0.0, 0.0, 0.0] if successful else None,
                    covariance12=[[0.01 if i == j else 0.0 for j in range(12)] for i in range(12)] if successful else None,
                    trigger_sequence=ack["sequence"],
                    native_begin_ns=ack["start_ns"],
                    native_end_ns=ack["end_ns"],
                    fusion_eligible=False,
                    quality=None,
                    reset_counter=None,
                )
            )
            target += 20_000_000
    return rows
