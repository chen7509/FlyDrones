import json
from importlib.util import find_spec

import pytest

from flydrones.vio_faults import FaultProfile, FaultStream, read_activation, route_model_from_frame, write_activation


def test_vio_fault_engine_module_exists():
    assert find_spec("flydrones.vio_faults") is not None


def profile(**changes):
    values = {"vehicle_id": 0, "seed": 23}
    values.update(changes)
    return FaultProfile(**values)


def test_passthrough_before_fault_marker_preserves_bytes_and_timestamp():
    stream = FaultStream(profile(delay_ms=120, drift_mps=(0.1, 0.0, 0.0)))
    event = stream.enqueue("x500_depth_fly_0", b"raw", 123456, now=10.0, activation_at=None)
    ready = stream.pop_ready(10.0)
    assert event.reason == "queued"
    assert [(item.payload, item.source_stamp_ns, item.offset_m) for item in ready] == [
        (b"raw", 123456, (0.0, 0.0, 0.0))
    ]


def test_only_target_vehicle_is_delayed_and_drifted_after_activation():
    stream = FaultStream(profile(delay_ms=120, drift_mps=(0.1, -0.2, 0.0)))
    other = stream.enqueue("x500_depth_fly_1", b"other", 1, now=12.0, activation_at=10.0)
    target = stream.enqueue("x500_depth_fly_0", b"target", 2, now=12.0, activation_at=10.0)
    first = stream.pop_ready(12.0)
    second = stream.pop_ready(12.12)
    assert other.reason == target.reason == "queued"
    assert [item.payload for item in first] == [b"other"]
    assert len(second) == 1
    assert second[0].source_stamp_ns == 2
    assert second[0].offset_m == pytest.approx((0.2, -0.4, 0.0))
    assert second[0].due_at == pytest.approx(12.12)


def test_scheduled_blackout_and_seeded_random_loss_are_reproducible():
    settings = profile(dropout_start_s=1.0, dropout_duration_s=0.5, drop_probability=0.5)
    outcomes = []
    for _ in range(2):
        stream = FaultStream(settings)
        reasons = [
            stream.enqueue("x500_depth_fly_0", b"m", index, now=10.0 + index * 0.2, activation_at=10.0).reason
            for index in range(12)
        ]
        outcomes.append(reasons)
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][5:8] == ["scheduled-dropout"] * 3
    assert "random-dropout" in outcomes[0]


def test_false_pose_offset_is_active_only_inside_window():
    stream = FaultStream(profile(false_pose_start_s=2.0, false_pose_duration_s=1.0, false_pose_offset_m=(3.0, 0.0, -1.0)))
    for when in (11.0, 12.5, 13.0):
        stream.enqueue("x500_depth_fly_0", b"m", 1, now=when, activation_at=10.0)
    offsets = [item.offset_m for item in stream.pop_ready(13.0)]
    assert offsets == [(0.0, 0.0, 0.0), (3.0, 0.0, -1.0), (0.0, 0.0, 0.0)]


def test_queue_is_bounded_and_reports_rejected_newest_sample():
    stream = FaultStream(profile(delay_ms=1000, max_queue=1))
    assert stream.enqueue("x500_depth_fly_0", b"first", 1, now=10.0, activation_at=10.0).reason == "queued"
    assert stream.enqueue("x500_depth_fly_0", b"second", 2, now=10.1, activation_at=10.0).reason == "queue-full"
    assert [item.payload for item in stream.pop_ready(11.0)] == [b"first"]


@pytest.mark.parametrize("changes", [
    {"delay_ms": -1},
    {"drop_probability": 1.1},
    {"dropout_duration_s": -1},
    {"drift_mps": (1.0, 2.0)},
    {"false_pose_offset_m": (float("nan"), 0.0, 0.0)},
    {"max_queue": 0},
])
def test_profile_rejects_invalid_values(changes):
    with pytest.raises(ValueError):
        profile(**changes)


def test_model_routing_rejects_unknown_or_malformed_frame_ids():
    models = {"x500_depth_fly_0", "x500_depth_fly_1"}
    assert route_model_from_frame("x500_depth_fly_0/odom", models) == "x500_depth_fly_0"
    assert route_model_from_frame("x500_depth_fly_00/odom", models) is None
    assert route_model_from_frame("x500_depth_fly_0/other", models) is None


def test_activation_marker_requires_matching_vehicle_and_finite_past_time(tmp_path):
    marker = tmp_path / "activation.json"
    assert read_activation(marker, vehicle_id=0, now=12.0) is None
    marker.write_text(json.dumps({"vehicle_id": 1, "monotonic_s": 10.0}), encoding="utf-8")
    assert read_activation(marker, vehicle_id=0, now=12.0) is None
    marker.write_text(json.dumps({"vehicle_id": 0, "monotonic_s": 13.0}), encoding="utf-8")
    assert read_activation(marker, vehicle_id=0, now=12.0) is None
    marker.write_text(json.dumps({"vehicle_id": 0, "monotonic_s": 10.0}), encoding="utf-8")
    assert read_activation(marker, vehicle_id=0, now=12.0) == 10.0


def test_activation_marker_is_written_after_gnss_change(tmp_path):
    marker = tmp_path / "activation.json"
    write_activation(marker, vehicle_id=0, monotonic_s=12.5)
    assert json.loads(marker.read_text(encoding="utf-8")) == {"vehicle_id": 0, "monotonic_s": 12.5}
    assert read_activation(marker, vehicle_id=0, now=12.6) == 12.5
