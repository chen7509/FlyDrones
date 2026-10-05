import copy
import hashlib

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from tools.benchmark.audit_inertial_consistency import audit_imu_delivery, audit_inertial_window
from tools.benchmark.openvins_online_shadow import encode_packet


def samples(acc=(0.0, 0.0, 0.0), rot=None):
    rotation = Rotation.identity() if rot is None else rot
    imu, truth = [], []
    for i in range(26):
        stamp = 1_000_000_000 + i * 4_000_000
        imu.append(dict(kind="imu", sample_ns=stamp, accel_flu=rotation.inv().apply(np.array(acc) + [0, 0, 9.81]).tolist()))
        truth.append(
            dict(
                sim_ns=stamp,
                quaternion_xyzw=rotation.as_quat().tolist(),
                velocity_world=(np.array(acc) * i * 0.004).tolist(),
                accel_world=list(acc),
            )
        )
    return imu, truth


@pytest.mark.parametrize("acc", [(0.0, 0.0, 0.0), (2.0, -3.0, 4.0)])
@pytest.mark.parametrize("rot", [Rotation.identity(), Rotation.from_euler("xyz", [30, -20, 80], degrees=True)])
def test_exact_inertial_closure_including_rotated_frame(acc, rot):
    imu, truth = samples(acc, rot)
    result = audit_inertial_window(imu, truth, 1_000_000_000, 1_100_000_000, gravity=[0.0, 0.0, -9.81])
    assert result["samples"] == 26
    assert result["sensor_velocity_closure_norm_m_s"] < 1e-12
    assert result["physics_velocity_closure_norm_m_s"] < 1e-12


def test_alias_fixture_detects_mismatch_without_naming_root_cause():
    imu, truth = samples((0.0, 0.0, -2.0))
    for row in truth:
        row["velocity_world"] = [0.0, 0.0, 0.0]
    result = audit_inertial_window(imu, truth, 1_000_000_000, 1_100_000_000, gravity=[0.0, 0.0, -9.81])
    assert result["sensor_velocity_closure_m_s"] == pytest.approx([0.0, 0.0, -0.2])
    assert result["physics_velocity_closure_m_s"] == pytest.approx([0.0, 0.0, -0.2])
    assert result["root_cause_proven"] is False
    assert result["fusion_eligible"] is False


@pytest.mark.parametrize("fault", ["start", "end", "gap", "duplicate", "order", "nan", "qnorm", "qnan", "velocity", "bool"])
def test_invalid_window_rejected(fault):
    imu, truth = samples()
    if fault == "start":
        imu.pop(0)
    if fault == "end":
        truth.pop()
    if fault == "gap":
        imu.pop(5)
        truth.pop(5)
    if fault == "duplicate":
        imu.insert(2, copy.deepcopy(imu[1]))
    if fault == "order":
        truth[4], truth[5] = truth[5], truth[4]
    if fault == "nan":
        imu[4]["accel_flu"][1] = float("nan")
    if fault == "qnorm":
        truth[4]["quaternion_xyzw"] = [0.0, 0.0, 0.0, 2.0]
    if fault == "qnan":
        truth[4]["quaternion_xyzw"][0] = float("nan")
    if fault == "velocity":
        truth[-1]["velocity_world"][0] = float("inf")
    if fault == "bool":
        imu[4]["sample_ns"] = True
    with pytest.raises(ValueError):
        audit_inertial_window(imu, truth, 1_000_000_000, 1_100_000_000, gravity=[0.0, 0.0, -9.81])


def delivery():
    raw = dict(kind="imu", sample_ns=1_000_000, arrival_monotonic_ns=100, gyro_flu=[1.0, 2.0, 3.0], accel_flu=[4.0, 5.0, 6.0])
    action = dict(kind="imu", sample_ns=1_000_000, source_arrival_ns=100, wm=[1.0, -2.0, -3.0], am=[4.0, -5.0, -6.0])
    packet = encode_packet(action, sequence=0, dispatch_ns=101)
    request = dict(
        sequence=0, action=action, dispatch_ns=101, packet_sha256=hashlib.sha256(packet).hexdigest(), bytes=len(packet)
    )
    ack = dict(
        sequence=0,
        kind="I",
        sample_ns=1_000_000,
        receive_ns=102,
        start_ns=103,
        end_ns=104,
        acknowledged_ns=105,
        source_arrival_ns=100,
        dispatch_ns=101,
    )
    return [raw], [request], [ack]


def test_delivery_preserves_vectors_and_hash():
    assert audit_imu_delivery(*delivery())["matched_imu_packets"] == 1


@pytest.mark.parametrize(
    "field,value",
    [("acknowledged_ns", float("inf")), ("acknowledged_ns", 105.0), ("source_arrival_ns", 100.0), ("sequence", False)],
)
def test_malformed_ack_integer_fields_rejected(field, value):
    raw, requests, acks = delivery()
    acks[0][field] = value
    with pytest.raises(ValueError):
        audit_imu_delivery(raw, requests, acks)


@pytest.mark.parametrize("fault", ["flip", "swap", "hash", "size", "sample", "sequence", "arrival", "missing", "duplicate"])
def test_corrupt_delivery_rejected(fault):
    raw, requests, acks = delivery()
    if fault == "flip":
        requests[0]["action"]["am"][1] *= -1
    if fault == "swap":
        requests[0]["action"]["wm"], requests[0]["action"]["am"] = requests[0]["action"]["am"], requests[0]["action"]["wm"]
    if fault == "hash":
        requests[0]["packet_sha256"] = "0" * 64
    if fault == "size":
        requests[0]["bytes"] += 1
    if fault == "sample":
        acks[0]["sample_ns"] += 1
    if fault == "sequence":
        requests[0]["sequence"] = 1
    if fault == "arrival":
        requests[0]["action"]["source_arrival_ns"] = 99
    if fault == "missing":
        acks.clear()
    if fault == "duplicate":
        raw.append(copy.deepcopy(raw[0]))
    with pytest.raises(ValueError):
        audit_imu_delivery(raw, requests, acks)
