from __future__ import annotations

import copy
from types import SimpleNamespace

import numpy as np
import pytest


def api():
    from tools.benchmark import openvins_receiver_parity

    return openvins_receiver_parity


def fixture(index=0):
    pose = [0.0] * 21
    velocity = [None] * 21
    for i, value in zip((0, 6, 11, 15, 18, 20), (1., 4., 9., 16., 25., 36.), strict=True):
        pose[i] = value
    for i, value in zip((0, 1, 2, 6, 7, 11), (49., 0., 0., 64., 0., 81.), strict=True):
        velocity[i] = value
    wire = dict(time_usec=10_000_000 + 20_000 * index, frame_id=20, child_frame_id=12,
                x=1.25, y=-2.5, z=3.75, q=[.5, -.5, .5, .5], vx=-4., vy=5., vz=-6.,
                rollspeed=None, pitchspeed=None, yawspeed=None, pose_covariance=pose,
                velocity_covariance=velocity, reset_counter=255, estimator_type=3, quality=1)
    sent = dict(id=f"packet-{index}", source_system=254, source_component=191, wire=wire)
    row = dict(timestamp=10_011_000 + 20_000 * index, timestamp_sample=10_010_000 + 20_000 * index,
               pose_frame=2, position=[1.25, -2.5, 3.75], q=[.5, -.5, .5, .5],
               velocity_frame=3, velocity=[-4., 5., -6.], angular_velocity=[None] * 3,
               position_variance=[1., 4., 9.], orientation_variance=[16., 25., 36.],
               velocity_variance=[49., 64., 81.], reset_counter=255, quality=1)
    return sent, row


def audit(sent=None, rows=None):
    packet, row = fixture()
    return api().audit_pairs([packet] if sent is None else sent, [row] if rows is None else rows,
                             px4_minus_remote_us=10_000)


def test_exact_pinned_field_mapping_is_only_a_component_gate():
    result = audit()
    assert result["field_parity_pass"] is True
    assert result["matched_count"] == 1
    assert result["receiver_stage_qualified"] is False
    assert result["timesync_convergence_qualified"] is False
    assert result["failures"] == []


@pytest.mark.parametrize("field,value", [
    ("pose_frame", 1), ("velocity_frame", 2), ("quality", 0), ("reset_counter", 0),
    ("position", [1.25, 2.5, 3.75]), ("q", [-.5, .5, -.5, -.5]),
    ("velocity", [4., 5., -6.]), ("angular_velocity", [0., 0., 0.]),
    ("orientation_variance", [1., 4., 9.]), ("position_variance", [4., 1., 9.]),
    ("velocity_variance", [49., 81., 64.]), ("timestamp_sample", 10_011_000),
    ("timestamp", 10_009_999), ("timestamp", 10_110_001), ("timestamp", True),
    ("position", [float("nan"), 0., 0.]), ("velocity_variance", [float("inf"), 64., 81.]),
])
def test_mismatched_or_invalid_receiver_fields_fail(field, value):
    _, row = fixture()
    row[field] = value
    assert audit(rows=[row])["field_parity_pass"] is False


@pytest.mark.parametrize("field,value", [("frame_id", 1), ("child_frame_id", 1),
                                       ("quality", -1), ("quality", True),
                                       ("reset_counter", 256), ("estimator_type", 2),
                                       ("time_usec", True), ("x", float("nan")),
                                       ("q", [0., 0., 0., 0.])])
def test_invalid_local_packet_profile_never_qualifies(field, value):
    packet, _ = fixture()
    packet["wire"][field] = value
    assert audit(sent=[packet])["field_parity_pass"] is False


@pytest.mark.parametrize("which", ["empty", "missing", "extra", "reorder", "duplicate", "id_duplicate"])
def test_missing_extra_duplicate_or_reordered_evidence_fails(which):
    packets, rows = map(list, zip(fixture(0), fixture(1), strict=True))
    if which == "empty":
        packets, rows = [], []
    elif which == "missing":
        rows.pop()
    elif which == "extra":
        rows.append(copy.deepcopy(rows[1]))
    elif which == "reorder":
        rows.reverse()
    elif which == "duplicate":
        packets[1], rows[1] = copy.deepcopy(packets[0]), copy.deepcopy(rows[0])
    else:
        packets[1]["id"] = packets[0]["id"]
    assert audit(packets, rows)["field_parity_pass"] is False


def test_sender_identity_and_integer_timestamps_are_strict():
    packet, row = fixture()
    packet["source_system"] = 1  # Legacy offline encoder identity is not the future sender.
    assert not audit([packet], [row])["field_parity_pass"]
    with pytest.raises(ValueError, match="offset"):
        api().audit_pairs([], [], px4_minus_remote_us=True)


def dataset():
    _, row = fixture()
    data = {}
    for key, value in row.items():
        if isinstance(value, list):
            for i, number in enumerate(value):
                data[f"{key}[{i}]"] = np.array([float("nan") if number is None else number], dtype=np.float32)
        else:
            data[key] = np.array([value], dtype=np.int64)
    return SimpleNamespace(name="vehicle_visual_odometry", multi_id=0, data=data)


def ulog():
    return SimpleNamespace(data_list=[dataset()], file_corruption=False, dropouts=[])


def test_ulog_arrays_are_extracted_without_truth_or_interpolation():
    rows = api().extract_receiver_rows(ulog())
    assert rows == [fixture()[1]]
    assert audit(rows=rows)["field_parity_pass"]


@pytest.mark.parametrize("fault", ["missing_topic", "multiple", "missing_field", "unequal_lengths", "corruption", "dropout"])
def test_ulog_missing_ambiguous_or_damaged_data_is_refused(fault):
    log = ulog()
    if fault == "missing_topic":
        log.data_list.clear()
    elif fault == "multiple":
        log.data_list.append(dataset())
    elif fault == "missing_field":
        del log.data_list[0].data["q[3]"]
    elif fault == "unequal_lengths":
        log.data_list[0].data["position[0]"] = np.array([1., 2.], dtype=np.float32)
    elif fault == "corruption":
        log.file_corruption = True
    else:
        log.dropouts = [SimpleNamespace(duration=1)]
    with pytest.raises(ValueError):
        api().extract_receiver_rows(log)
