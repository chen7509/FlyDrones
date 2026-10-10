"""Pure EGO bridge input contract; no ROS, Docker or Gazebo required."""

import base64
import importlib.util
import json
import sys
import threading
import types
from pathlib import Path

import numpy as np
import pytest

from tools.benchmark.ego_wire_observation import (
    ObservationSequence,
    decode_observation,
    handle_observation_packet,
)


def packet(**changes):
    rgb = np.zeros((120, 160, 3), dtype=np.uint8)
    depth = np.full((120, 160), 10., dtype="<f4")
    depth[2, 3] = np.nan
    row = {
        "sim_ns": 1_000_000_000,
        "frame_ns": 1_000_000_000,
        "rgb": {"shape": [120, 160, 3],
                "data": base64.b64encode(rgb.tobytes()).decode("ascii")},
        "depth_m": {"shape": [120, 160],
                    "data": base64.b64encode(depth.tobytes()).decode("ascii")},
        "camera_pose": [0., 0., 1.5, 0., 0., 0., 1.],
        "position": [0., 0., 1.5],
        "velocity": [.1, 0., 0.],
        "yaw": 0.,
        "yaw_rate": 0.,
        "goal": [8., 0., 1.5],
    }
    row.update(changes)
    return json.dumps(row, separators=(",", ":"), allow_nan=False).encode("utf-8")


def change_depth(value):
    row = json.loads(packet())
    depth = np.full((120, 160), 10., dtype="<f4")
    depth[2, 3] = value
    row["depth_m"]["data"] = base64.b64encode(depth.tobytes()).decode("ascii")
    return json.dumps(row).encode()


def test_valid_packet_preserves_nan_mask_and_rgb_bytes():
    result = decode_observation(packet())
    assert result["rgb"].shape == (120, 160, 3)
    assert result["rgb"].dtype == np.uint8
    assert result["depth_m"].dtype == np.float32
    assert np.isnan(result["depth_m"][2, 3])
    assert result["depth_m"][0, 0] == 10.


@pytest.mark.parametrize("payload", [
    b"{bad", b"\xff", b'{"sim_ns":1,"sim_ns":2}',
    b'{"sim_ns": NaN}', b'{"sim_ns": Infinity}',
    packet(extra=1), packet(sim_ns=True), packet(sim_ns=-1),
    packet(frame_ns=1_000_000_001), packet(frame_ns=899_999_999),
    packet(position=[True, 0., 1.]), packet(velocity=["0.1", 0., 0.]),
    packet(yaw=False), packet(goal=[1., 2.]),
    packet(camera_pose=[0., 0., 1.5, 0., 0., 0., 0.]),
    packet(camera_pose=[0., 0., 1.5, 0., 0., 0., .8]),
    packet(camera_pose=[0., 0., 1.5, 0., 0., 0., .96]),
], ids=["bad-json", "bad-utf8", "duplicate-key", "nan-token", "infinity-token",
        "extra-field", "bool-time", "negative-time", "future-frame", "stale-frame",
        "bool-position", "string-velocity", "bool-yaw", "short-goal", "zero-q", "short-q",
        "nonunit-q"])
def test_bad_json_time_state_and_pose_are_refused(payload):
    with pytest.raises(ValueError):
        decode_observation(payload)


@pytest.mark.parametrize("field,packed", [
    ("rgb", {"shape": [120, 160, 4], "data": "AA=="}),
    ("rgb", {"shape": [120, 160, 3], "data": "AA=="}),
    ("depth_m", {"shape": [120, 160], "data": "!"}),
    ("depth_m", {"shape": [True, 160], "data": "AA=="}),
    ("depth_m", {"shape": [120, 160], "data": "AA==", "truth": 1}),
])
def test_bad_image_shape_encoding_or_extra_metadata_is_refused(field, packed):
    row = json.loads(packet())
    row[field] = packed
    with pytest.raises(ValueError):
        decode_observation(json.dumps(row).encode())


@pytest.mark.parametrize("value", [np.inf, -np.inf, 0., -1.])
def test_nonpositive_or_infinite_depth_is_refused(value):
    with pytest.raises(ValueError):
        decode_observation(change_depth(value))


def test_all_missing_depth_is_refused():
    row = json.loads(packet())
    depth = np.full((120, 160), np.nan, dtype="<f4")
    row["depth_m"]["data"] = base64.b64encode(depth.tobytes()).decode("ascii")
    with pytest.raises(ValueError):
        decode_observation(json.dumps(row).encode())


def test_monotonic_state_allows_repeated_camera_frame_then_rejects_regression():
    sequence = ObservationSequence()
    published = []
    handle_observation_packet(packet(), sequence, published.append)
    handle_observation_packet(packet(sim_ns=1_050_000_000), sequence, published.append)
    assert len(published) == 2
    for payload in (packet(sim_ns=1_050_000_000),
                    packet(sim_ns=1_060_000_000, frame_ns=999_999_999),
                    packet(sim_ns=1_200_000_000)):
        with pytest.raises(ValueError):
            handle_observation_packet(payload, sequence, published.append)
    assert len(published) == 2
    sequence.reset()
    handle_observation_packet(packet(), sequence, published.append)
    assert len(published) == 3


def test_bad_packet_has_no_publish_or_sequence_side_effect():
    sequence = ObservationSequence()
    published = []
    with pytest.raises(ValueError):
        handle_observation_packet(packet(position=["bad", 0., 1.]),
                                  sequence, published.append)
    assert published == []
    handle_observation_packet(packet(), sequence, published.append)
    assert len(published) == 1


def bridge_module(monkeypatch):
    """Load the actual bridge with inert ROS imports."""
    for package, child, names in (
        ("rclpy", "rclpy.node", {"Node": object}),
        ("builtin_interfaces", "builtin_interfaces.msg", {"Time": type("Time", (), {})}),
        ("geometry_msgs", "geometry_msgs.msg", {"PoseStamped": type("PoseStamped", (), {})}),
        ("nav_msgs", "nav_msgs.msg", {"Odometry": type("Odometry", (), {})}),
        ("quadrotor_msgs", "quadrotor_msgs.msg", {
            "PositionCommand": type("PositionCommand", (), {"TRAJECTORY_STATUS_READY": 1})}),
        ("rosgraph_msgs", "rosgraph_msgs.msg", {"Clock": type("Clock", (), {})}),
        ("sensor_msgs", "sensor_msgs.msg", {"Image": type("Image", (), {})}),
    ):
        parent_module = types.ModuleType(package)
        child_module = types.ModuleType(child)
        for name, value in names.items():
            setattr(child_module, name, value)
        setattr(parent_module, "msg" if child.endswith(".msg") else "node", child_module)
        monkeypatch.setitem(sys.modules, package, parent_module)
        monkeypatch.setitem(sys.modules, child, child_module)
    rclpy = sys.modules["rclpy"]
    ok_values = iter((True, False))
    rclpy.ok = lambda: next(ok_values)
    path = Path(__file__).resolve().parents[2] / "tools/benchmark/ego_node.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("ego_node_gate_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_bridge_refuses_future_frame_before_any_ros_publish(monkeypatch):
    """Exercise the actual client loop, including the no-publish failure path."""
    module = bridge_module(monkeypatch)
    rclpy = sys.modules["rclpy"]
    bridge = module.Bridge.__new__(module.Bridge)
    bridge.condition = threading.Condition()
    bridge.input_sequence = ObservationSequence()
    bridge.response_timeout_s = 0.
    bridge.reference_revision = 0
    published = []
    bridge.publish_observation = published.append
    inputs = iter((json.dumps({"type": "reset", "seed": 1}).encode(),
                   packet(frame_ns=1_000_000_001)))
    monkeypatch.setattr(module, "recv_packet", lambda _stream: next(inputs))
    monkeypatch.setattr(module, "send_packet", lambda _stream, _payload: None)
    with pytest.raises(ValueError):
        bridge.serve_client(None)
    assert published == []
    ok_values = iter((True, False))
    rclpy.ok = lambda: next(ok_values)
    inputs = iter((json.dumps({"type": "reset", "seed": 2}).encode(), packet()))
    bridge.serve_client(None)
    assert len(published) == 1
    assert published[0]["sim_ns"] == 1_000_000_000


def test_delayed_previous_command_cannot_answer_next_observation(monkeypatch):
    module = bridge_module(monkeypatch)
    rclpy = sys.modules["rclpy"]
    ok_values = iter((True, False))
    rclpy.ok = lambda: next(ok_values)
    bridge = module.Bridge.__new__(module.Bridge)
    bridge.condition = threading.Condition()
    bridge.input_sequence = ObservationSequence()
    bridge.response_timeout_s = 0.
    bridge.reference_revision = 0
    bridge.publish_observation = lambda _observation: None
    inputs = iter((json.dumps({"type": "reset", "seed": 1}).encode(), packet()))

    def receive(_stream):
        payload = next(inputs)
        if payload.startswith(b'{"sim_ns"'):
            # An answer to the preceding frame arrives while this one is read.
            with bridge.condition:
                bridge.reference_revision += 1
                bridge.reference = {"position": [99., 0., 0.]}
        return payload

    sent = []
    monkeypatch.setattr(module, "recv_packet", receive)
    monkeypatch.setattr(module, "send_packet", lambda _stream, payload: sent.append(json.loads(payload)))
    bridge.serve_client(None)
    assert sent[-1] == {"error": "EGO produced no new trajectory reference"}


def test_future_synthetic_fixture_obeys_the_same_wire_contract():
    path = (Path(__file__).resolve().parents[2] / "results/ego-upstream-source-audit-dev-1701"
            / "synthetic_client_v2.py")
    spec = importlib.util.spec_from_file_location("ego_synthetic_fixture_v2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    row = module.observation(0)
    accepted = decode_observation(json.dumps(row, allow_nan=False).encode())
    assert accepted["depth_m"].shape == (120, 160)
    assert accepted["rgb"].shape == (120, 160, 3)
