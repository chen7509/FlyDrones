"""Pure source -> fan-out -> native request/ack joins, never estimator execution.

Payloads are already-read bytes keyed by source sequence. The caller must bind
their original paths/manifests and runtime identity. This checks recorded work,
not physical accuracy, process provenance, health qualification or live delivery.
"""

from __future__ import annotations

import hashlib
from collections import Counter

from tools.benchmark.audit_live_wire_study import _equal, _integer, _shape
from tools.benchmark.disarmed_sensor_provenance import audit_event_records
from tools.benchmark.openvins_causal_input import CausalInput
from tools.benchmark.openvins_online_shadow import (
    CAMERA_HEALTH_TRANSPORT_FIELDS,
    encode_packet,
    project_camera_health_row,
    project_motion_intent_ack,
    validate_ack,
)
from tools.benchmark.ready_shadow_fanout import digest

END_NS = 25_000_000_000
TTL_NS = 2_000_000_000


def audit_source_native_records(*, sources, fanout, requests, acknowledgements, states, payloads, terminal, session_id):
    if type(sources) is not list or not 7004 <= len(sources) <= 7504:
        raise ValueError("full source workload required")
    if type(payloads) is not dict or any(type(key) is not int for key in payloads):
        raise ValueError("source payload identities")
    for value in (fanout, requests, acknowledgements, states):
        if type(value) is not list or len(value) > 15008:
            raise ValueError("invalid workload records")
    _equal(len(fanout), 2 * len(sources), "two fan-out records per source")
    _equal(len(requests), len(acknowledgements), "request acknowledgement count")
    if not 6501 <= len(requests) <= 6502:
        raise ValueError("full native workload required")
    if type(session_id) is not str or not session_id or any(c.isspace() for c in session_id):
        raise ValueError("explicit native session required")
    _shape(
        terminal,
        (
            "failure",
            "inputs_accepted",
            "delivered",
            "skipped_after_failure",
            "pending",
            "retained_pixel_stamps",
            "released_unacknowledged",
            "fusion_eligible",
            "quality",
            "reset_counter",
            "last_delivery_acks",
            "health_last",
        ),
        "shadow terminal",
    )
    audit_event_records(
        [{k: v for k, v in row.items() if k != "source_sequence"} for row in sources],
        required_kinds=["imu", "rgb", "info", "depth", "heartbeat"],
    )
    counts = Counter(row["kind"] for row in sources)
    for kind, count, period in (
        ("imu", 6251, 4_000_000),
        ("rgb", 251, 100_000_000),
        ("info", 251, 100_000_000),
        ("depth", 251, 100_000_000),
    ):
        _equal(counts[kind], count, kind + " count")
        stamps = [row["sample_ns"] for row in sources if row["kind"] == kind]
        _integer(stamps[0], 1, period - 1, "initial " + kind + " sample")
        _equal(stamps[1:], list(range(period, END_NS + 1, period)), kind + " cadence")
    _equal(
        [r["sample_ns"] for r in sources if r["kind"] == "rgb"],
        [r["sample_ns"] for r in sources if r["kind"] == "info"],
        "RGB/info samples",
    )
    _equal(
        [r["sample_ns"] for r in sources if r["kind"] == "rgb"],
        [r["sample_ns"] for r in sources if r["kind"] == "depth"],
        "RGB/depth samples",
    )
    _equal(set(payloads), {r["source_sequence"] for r in sources if r["kind"] in ("rgb", "info")}, "payload set")

    causal = CausalInput(session_id=session_id, clock_id="gazebo-sim+linux-monotonic")
    actions, action_bounds, images = [], [], {}
    accepted, previous_end = 0, 0
    for seq, source in enumerate(sources):
        _equal(source.get("source_sequence"), seq, "source sequence")
        # The callback reads the shared PostUpdate clock, not the sensor stamp.
        # They can straddle a physics step; retain both and replay CausalInput's
        # actual watermark checks rather than adding a new sample<=clock gate.
        _integer(source["observed_sim_ns"], 0, END_NS, "source simulation observation")
        if source["kind"] == "heartbeat":
            _equal(source["system_id"], 9, "heartbeat system")
        payload = payloads.get(seq)
        if source["kind"] == "rgb":
            if type(payload) is not bytes or len(payload) != 57600:
                raise ValueError("complete RGB bytes required")
            images[source["sample_ns"]] = payload
        elif source["kind"] == "info":
            if type(payload) is not bytes or not payload:
                raise ValueError("CameraInfo bytes required")
            _equal(hashlib.sha256(payload).hexdigest(), source["payload_sha256"], "CameraInfo payload hash")
        intent, delivery = fanout[2 * seq : 2 * seq + 2]
        identity = dict(
            sequence_repr=repr(seq),
            source_sequence=seq,
            source_sha256=digest(source),
            payload_sha256=hashlib.sha256(payload).hexdigest() if payload else None,
            begin_ns=intent.get("begin_ns"),
        )
        _equal(
            intent,
            dict(
                identity,
                event="source_intent",
                dispositions=dict(shadow="not_attempted", readiness="not_attempted"),
                consumers={},
            ),
            "fan-out intent",
        )
        _shape(delivery, set(identity) | {"event", "dispositions", "consumers", "end_ns"}, "source delivery")
        _equal({key: delivery[key] for key in identity}, identity, "fan-out identity")
        _equal(delivery["event"], "source_delivery", "delivery event")
        _equal(delivery["dispositions"], dict(shadow="returned", readiness="returned"), "source committed")
        _shape(delivery["consumers"], ("shadow", "readiness"), "consumers")
        times = [identity["begin_ns"]]
        for consumer in ("shadow", "readiness"):
            _shape(delivery["consumers"][consumer], ("start_ns", "returned_ns"), "consumer clocks")
            times.extend(delivery["consumers"][consumer][key] for key in ("start_ns", "returned_ns"))
        times.append(delivery["end_ns"])
        last = max(previous_end, source["recorded_monotonic_ns"])
        for timestamp in times:
            _integer(timestamp, last, 2**63 - 1, "source processing clock")
            last = timestamp
        if times[-1] - times[0] > TTL_NS:
            raise ValueError("source processing timeout")
        previous_end = times[-1]
        if source["kind"] not in ("imu", "rgb", "info"):
            continue
        kind = source["kind"]
        keys = {"kind", "sample_ns", "arrival_monotonic_ns", "observed_sim_ns"}
        keys |= {"imu": {"gyro_flu", "accel_flu"}, "rgb": {"width", "height"}, "info": {"camera_info"}}[kind]
        released = causal.accept(
            {key: source[key] for key in keys}, sequence=accepted, session_id=session_id, clock_id=causal.clock_id
        )
        accepted += 1
        actions.extend(released)
        action_bounds.extend([(times[1], times[2])] * len(released))
    pending = causal.finish()
    _equal(len(pending), 1, "one final unavailable camera")
    _equal(pending[0]["reason"], "later_imu_missing", "final camera reason")
    _equal(pending[0]["sample_ns"], END_NS, "final camera stamp")
    for key, value in dict(
        failure=None,
        inputs_accepted=6753,
        delivered=6501,
        skipped_after_failure=0,
        pending=pending,
        retained_pixel_stamps=[END_NS],
        released_unacknowledged=[],
        fusion_eligible=False,
        quality=None,
        reset_counter=None,
    ).items():
        _equal(terminal.get(key), value, "shadow terminal " + key)

    sensor_index = 0
    camera_acks, motion_acks = [], 0
    last_ack = 0
    for seq, (request, ack) in enumerate(zip(requests, acknowledgements)):
        _shape(request, ("sequence", "action", "dispatch_ns", "bytes", "packet_sha256", "rgb_sha256"), "native request")
        _equal(request["sequence"], seq, "request sequence")
        _equal(ack.get("sequence"), seq, "ack sequence")
        action = request["action"]
        is_motion = action.get("kind") == "motion_intent"
        if action.get("kind") == "imu":
            _shape(
                ack,
                (
                    "sequence",
                    "kind",
                    "sample_ns",
                    "receive_ns",
                    "start_ns",
                    "end_ns",
                    "gray_first",
                    "fusion_eligible",
                    "quality",
                    "reset_counter",
                    "acknowledged_ns",
                    "source_arrival_ns",
                    "dispatch_ns",
                ),
                "native IMU acknowledgement",
            )
        if is_motion:
            motion_acks += 1
            _equal(action.get("session_id"), session_id, "motion session")
            _equal(action.get("clock_id"), causal.clock_id, "motion clock")
            project_motion_intent_ack(ack, action)
        else:
            if sensor_index >= len(actions):
                raise ValueError("unexpected extra native action")
            _equal(action, actions[sensor_index], "causal native action")
            lower, upper = action_bounds[sensor_index]
            _integer(request["dispatch_ns"], lower, upper, "dispatch within source delivery")
            _integer(ack.get("acknowledged_ns"), lower, upper, "ack within source delivery")
            sensor_index += 1
        image = images[action["sample_ns"]] if action["kind"] == "camera" else None
        packet = encode_packet(action, sequence=seq, dispatch_ns=request["dispatch_ns"], pixels=image)
        _equal(request["bytes"], len(packet), "encoded bytes")
        _equal(request["packet_sha256"], hashlib.sha256(packet).hexdigest(), "encoded packet hash")
        _equal(request["rgb_sha256"], hashlib.sha256(image).hexdigest() if image else None, "request image hash")
        _integer(request["dispatch_ns"], last_ack, 2**63 - 1, "single worker dispatch")
        _integer(ack.get("acknowledged_ns"), request["dispatch_ns"], request["dispatch_ns"] + TTL_NS, "native timeout")
        validate_ack(
            ack, sequence=seq, kind=chr(packet[0]), dispatch_ns=request["dispatch_ns"], acknowledged_ns=ack["acknowledged_ns"]
        )
        for key, value in dict(
            sample_ns=action["sample_ns"],
            source_arrival_ns=action["source_arrival_ns"],
            dispatch_ns=request["dispatch_ns"],
            fusion_eligible=False,
            quality=None,
            reset_counter=None,
        ).items():
            _equal(ack.get(key), value, "native " + key)
        last_ack = ack["acknowledged_ns"]
        if image:
            project_camera_health_row(ack, session_id=session_id)
            camera_acks.append({key: value for key, value in ack.items() if key not in CAMERA_HEALTH_TRANSPORT_FIELDS})
    _equal(sensor_index, 6501, "complete native sensor actions")
    if motion_acks > 1:
        raise ValueError("repeated motion intent")
    _equal(states, camera_acks, "native camera state file")
    return dict(
        source_native_records_consistent=True,
        counts=dict(counts),
        native_sensor_acknowledgements=sensor_index,
        motion_intent_acknowledgements=motion_acks,
        public_camera_states=sum(r["public_initialized"] for r in camera_acks),
        causal_pending=pending,
        payload_file_provenance_qualified=False,
        motion_authority_qualified=False,
        source_watchdog_qualified=False,
        native_process_provenance_qualified=False,
        vio_accuracy_qualified=False,
        live_qualified=False,
        fusion_qualified=False,
    )
