"""Synthetic v2 geometry journal tests; fake CDR never authenticates PX4."""

import hashlib
import json

import pytest

from flydrones.connectome_training.px4_odometry_adapter import (
    CameraExtrinsic,
    CameraStamp,
    Px4OdometryCausalAdapter,
)
from flydrones.connectome_training.px4_ros2_source_journal import (
    audit_source_journal,
    offline_geometry_to_event,
    read_offline_odometry_geometry,
)

V2 = "flydrones.px4_ros2_odometry_cdr.v2"
V1 = "flydrones.px4_ros2_odometry_cdr.v1"


def row(sequence=1, **changed):
    cdr = bytes.fromhex("000100001234")  # Deliberately not a real VehicleOdometry CDR.
    value = {
        "schema": V2, "kind": "sample", "topic": "/fmu/out/vehicle_odometry",
        "ros_type": "px4_msgs/msg/VehicleOdometry",
        "message_blob_sha": "cf117ff82cdbf191bf576db91db900b7ce34f6a7",
        "run_id": "synthetic-v2", "journal_sequence": sequence,
        "rmw_implementation": "rmw_cyclonedds_cpp", "publisher_gid_hex": "ab" * 24,
        "rmw_source_timestamp_ns": 1000 * sequence,
        "rmw_received_timestamp_ns": 1000 * sequence + 1,
        "rmw_publication_sequence": sequence, "rmw_reception_sequence": sequence,
        "callback_steady_ns": 20_000_000 * sequence,
        "px4_publication_us": 10_010 * sequence, "px4_sample_us": 10_000 * sequence,
        "pose_frame": 1, "velocity_frame": 1, "reset_counter": 0, "quality": 0,
        "position_ned_m": [1.0, 2.0, -3.0],
        "q_body_to_ned_wxyz": [1.0, 0.0, 0.0, 0.0],
        "velocity_ned_m_s": [0.2, 0.3, -0.1],
        "omega_body_frd_rad_s": [0.0, 0.0, 0.1],
        "position_variance_m2": [0.1, 0.1, 0.2],
        "orientation_variance_rad2": [0.01, 0.01, 0.02],
        "velocity_variance_m2_s2": [0.2, 0.2, 0.3],
        "cdr_hex": cdr.hex(), "cdr_sha256": hashlib.sha256(cdr).hexdigest(),
    }
    value.update(changed)
    return value


def finish(samples, **changed):
    value = {"schema": V2, "kind": "finish", "run_id": "synthetic-v2",
             "samples": samples, "status": "complete", "reason": ""}
    value.update(changed)
    return value


def write(path, *rows):
    path.write_text("".join(json.dumps(value) + "\n" for value in rows), encoding="utf-8")
    return path


def test_v2_full_geometry_is_audited_but_never_authenticates_source(tmp_path):
    path = write(tmp_path / "odometry.jsonl", row(), row(2), finish(2))
    audit = audit_source_journal(path)
    geometry = read_offline_odometry_geometry(path)
    assert audit.samples == 2 and audit.completed
    assert audit.eligible_for_live_capture is False
    assert len(geometry) == 2
    assert geometry[0].position_ned_m == (1.0, 2.0, -3.0)
    assert geometry[0].q_body_to_ned_wxyz == (1.0, 0.0, 0.0, 0.0)
    assert geometry[0].journal_sha256 == audit.journal_sha256
    assert geometry[0].rmw_implementation == "rmw_cyclonedds_cpp"
    assert geometry[0].rmw_source_timestamp_ns == 1000
    assert geometry[0].rmw_received_timestamp_ns == 1001
    assert geometry[0].rmw_publication_sequence == 1
    assert geometry[0].rmw_reception_sequence == 1
    assert geometry[0].eligible_for_live_capture is False
    assert "cdr_decode_parity_not_verified" in audit.missing_qualification


def test_invalid_px4_geometry_is_retained_but_cannot_become_event(tmp_path):
    path = write(tmp_path / "unknown.jsonl", row(position_ned_m=[None, 2.0, -3.0]), finish(1))
    assert audit_source_journal(path).completed
    with pytest.raises(ValueError, match="invalid geometry"):
        read_offline_odometry_geometry(path)


@pytest.mark.parametrize("field,value", [
    ("position_ned_m", [1.0, 2.0]),
    ("position_ned_m", [True, 2.0, 3.0]),
    ("velocity_ned_m_s", ["1", 2.0, 3.0]),
    ("position_variance_m2", [0.1, -0.1, 0.1]),
    ("orientation_variance_rad2", [0.1, 0.1, 1e40]),
    ("orientation_variance_rad2", [0.1, 0.1, 10**1000]),
    ("q_body_to_ned_wxyz", [1.0, 0.0, 0.0, float("inf")]),
])
def test_v2_invalid_field_is_refused(tmp_path, field, value):
    path = write(tmp_path / "bad.jsonl", row(**{field: value}), finish(1))
    with pytest.raises(ValueError):
        audit_source_journal(path)


def test_v1_and_v2_rows_cannot_mix(tmp_path):
    path = write(tmp_path / "mixed.jsonl", row(), finish(1, schema=V1))
    with pytest.raises(ValueError, match="schema"):
        audit_source_journal(path)


def test_v2_geometry_requires_complete_journal(tmp_path):
    path = write(tmp_path / "incomplete.jsonl", row())
    with pytest.raises(ValueError, match="terminal"):
        read_offline_odometry_geometry(path)


def test_second_geometry_pass_remains_bounded_if_journal_changes(tmp_path, monkeypatch):
    from flydrones.connectome_training import px4_ros2_source_journal as source

    path = write(tmp_path / "changed.jsonl", row(), finish(1))
    original_audit = source.audit_source_journal

    def change_after_audit(value):
        audit = original_audit(value)
        path.write_bytes(b"{" + b"x" * 32769 + b"}\n")
        return audit

    monkeypatch.setattr(source, "audit_source_journal", change_after_audit)
    with pytest.raises(ValueError, match="journal changed|truncated or oversized"):
        source.read_offline_odometry_geometry(path)


def test_explicit_offline_bridge_reaches_camera_adapter_without_capture_grant(tmp_path):
    path = write(tmp_path / "odometry.jsonl", row(), finish(1))
    geometry = read_offline_odometry_geometry(path)[0]
    event = offline_geometry_to_event(
        geometry, provisional_session_id="offline-only", provisional_instance=0)
    adapter = Px4OdometryCausalAdapter(CameraExtrinsic(
        position_body_frd_m=(0.0, 0.0, 0.0),
        q_camera_to_body_wxyz=(1.0, 0.0, 0.0, 0.0),
        artifact_sha256="a" * 64,
    ))
    adapter.push(event)
    candidate = adapter.at_camera(CameraStamp(sample_us=10_020, receipt_monotonic_ns=20_001_000))
    assert candidate.position_enu_m == (2.0, 1.0, 3.0)
    assert candidate.eligible_for_live_capture is False
    assert geometry.eligible_for_live_capture is False


@pytest.mark.parametrize("changed", [
    {"provisional_session_id": ""},
    {"provisional_instance": -1},
    {"provisional_instance": True},
])
def test_offline_bridge_refuses_unbounded_identity(tmp_path, changed):
    geometry = read_offline_odometry_geometry(write(tmp_path / "a.jsonl", row(), finish(1)))[0]
    args = {"provisional_session_id": "offline", "provisional_instance": 0}
    args.update(changed)
    with pytest.raises(ValueError):
        offline_geometry_to_event(geometry, **args)


def test_offline_bridge_rejects_invalid_quaternion(tmp_path):
    path = write(tmp_path / "bad-q.jsonl", row(q_body_to_ned_wxyz=[0., 0., 0., 0.]), finish(1))
    assert audit_source_journal(path).completed
    with pytest.raises(ValueError, match="quaternion"):
        read_offline_odometry_geometry(path)
