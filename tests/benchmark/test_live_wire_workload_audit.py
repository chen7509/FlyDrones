"""Synthetic source/native evidence; no simulator, sockets or estimator process."""

import copy
import hashlib
import importlib.util

import pytest

from tools.benchmark.disarmed_sensor_provenance import validate_event
from tools.benchmark.openvins_causal_input import CausalInput, raw_profile
from tools.benchmark.openvins_online_shadow import encode_packet
from tools.benchmark.ready_shadow_fanout import digest


def api():
    name = "tools.benchmark.audit_live_wire_workload"
    assert importlib.util.find_spec(name) is not None, "raw workload audit missing"
    return __import__(name, fromlist=["audit_source_native_records"]).audit_source_native_records


def build_chain(callback_clock_lag_ns=0):
    schedule = [(1_000_000, "imu")]
    schedule += [(i * 4_000_000, "imu") for i in range(1, 6251)]
    for stamp in [2_000_000] + [i * 100_000_000 for i in range(1, 251)]:
        schedule += [(stamp, kind) for kind in ("info", "rgb", "depth")]
    schedule += [(i * 1_000_000_000, "heartbeat") for i in range(1, 25)]
    rows, fanout, requests, acks, states = [], [], [], [], []
    pixels, payloads = b"\x20" * 57600, {}
    causal = CausalInput(session_id="synthetic-1", clock_id="gazebo-sim+linux-monotonic")
    input_sequence = 0
    for sequence, (stamp, kind) in enumerate(sorted(schedule)):
        wall = 10_000_000_000 + stamp + sequence * 100
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
        session_id="synthetic-1",
    )


@pytest.fixture(scope="module")
def chain():
    return build_chain()


def test_callback_clock_is_not_sensor_sample_time():
    out = api()(**build_chain(callback_clock_lag_ns=1_000_000))
    assert out["source_native_records_consistent"] is True


def test_full_synthetic_source_native_chain(chain):
    out = api()(**chain)
    assert out["source_native_records_consistent"] is True
    assert out["counts"] == {"imu": 6251, "rgb": 251, "info": 251, "depth": 251, "heartbeat": 24}
    assert out["native_sensor_acknowledgements"] == 6501
    assert out["public_camera_states"] == 0
    assert out["live_qualified"] is out["fusion_qualified"] is out["vio_accuracy_qualified"] is False


@pytest.mark.parametrize("field", ["failure", "quality", "reset_counter"])
def test_missing_null_terminal_fields_refuse(chain, field):
    data = copy.deepcopy(chain)
    del data["terminal"][field]
    with pytest.raises(ValueError):
        api()(**data)


def test_unknown_native_imu_field_refuses(chain):
    data = copy.deepcopy(chain)
    data["acknowledgements"][0]["truth_correction"] = True
    with pytest.raises(ValueError):
        api()(**data)


@pytest.mark.parametrize(
    "fault",
    [
        "source_gap",
        "reduced_load",
        "armed",
        "imu_transform",
        "arrival",
        "image_truncated",
        "image_hash",
        "missing_info_payload",
        "source_hash",
        "fanout_missing",
        "partial_delivery",
        "fanout_timeout",
        "ack_missing",
        "request_action",
        "packet_hash",
        "short_packet",
        "ack_sample",
        "ack_sequence_bool",
        "ack_timeout",
        "native_gap",
        "state_mismatch",
        "pending_hidden",
        "failure_hidden",
        "unlisted_payload",
        "native_extra",
    ],
)
def test_corrupted_raw_chain_refuses(chain, fault):
    data = copy.deepcopy(chain)
    if fault == "source_gap":
        data["sources"][2]["source_sequence"] += 1
    elif fault == "reduced_load":
        data["sources"].pop()
    elif fault == "armed":
        next(r for r in data["sources"] if r["kind"] == "heartbeat")["base_mode"] |= 128
    elif fault == "imu_transform":
        data["sources"][0]["accel_frd"][2] *= -1
    elif fault == "arrival":
        data["sources"][0]["recorded_monotonic_ns"] = 1
    elif fault in ("image_truncated", "image_hash"):
        seq = next(r["source_sequence"] for r in data["sources"] if r["kind"] == "rgb")
        data["payloads"][seq] = b"a" if fault == "image_truncated" else b"a" * 57600
    elif fault == "missing_info_payload":
        del data["payloads"][next(r["source_sequence"] for r in data["sources"] if r["kind"] == "info")]
    elif fault == "source_hash":
        data["fanout"][0]["source_sha256"] = "0" * 64
    elif fault == "fanout_missing":
        data["fanout"].pop()
    elif fault == "partial_delivery":
        data["fanout"][1]["dispositions"]["readiness"] = "not_attempted"
    elif fault == "fanout_timeout":
        data["fanout"][1]["end_ns"] += 2_000_000_001
    elif fault == "ack_missing":
        data["acknowledgements"].pop()
    elif fault == "request_action":
        data["requests"][0]["action"]["am"][0] += 1
    elif fault == "packet_hash":
        data["requests"][0]["packet_sha256"] = "0" * 64
    elif fault == "short_packet":
        data["requests"][0]["bytes"] -= 1
    elif fault == "ack_sample":
        data["acknowledgements"][0]["sample_ns"] += 1
    elif fault == "ack_sequence_bool":
        data["acknowledgements"][0]["sequence"] = False
    elif fault == "ack_timeout":
        data["acknowledgements"][0]["acknowledged_ns"] += 2_000_000_001
    elif fault == "native_gap":
        data["requests"].pop(0)
        data["acknowledgements"].pop(0)
    elif fault == "state_mismatch":
        data["states"][0]["public_initialized"] = True
    elif fault == "pending_hidden":
        data["terminal"]["pending"] = []
    elif fault == "failure_hidden":
        data["terminal"]["failure"] = "source failure"
    elif fault == "unlisted_payload":
        data["payloads"][99999] = b"extra"
    elif fault == "native_extra":
        data["requests"].append(data["requests"][-1])
        data["acknowledgements"].append(data["acknowledgements"][-1])
    with pytest.raises(ValueError):
        api()(**data)
