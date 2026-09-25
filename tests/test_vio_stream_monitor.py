"""The safety gate must react to delivered VIO frames, not a fresh PX4 pose."""

import json
import socket

import pytest

from flydrones.vio_stream_monitor import VioStreamMonitor
from tools.relay_gazebo_vio import encode_vio_stream_frame


def _send(port, **overrides):
    frame = {
        "schema": "flydrones-vio-stream-v1",
        "vehicle_id": 0,
        "sequence": 1,
        "source_stamp_ns": 123,
        "received_at": 10.0,
        "published_at": 10.12,
    }
    frame.update(overrides)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.sendto(json.dumps(frame).encode(), ("127.0.0.1", port))


def test_delayed_frame_is_healthy_but_400ms_blackout_fails_closed():
    with VioStreamMonitor(vehicle_id=0, port=0, max_age_s=0.25) as monitor:
        assert monitor.health(now=10.0).reason == "missing-vio-frame"
        _send(monitor.port)
        assert monitor.health(now=10.14).healthy
        assert monitor.health(now=10.14).sample_age_s == pytest.approx(0.14)
        assert monitor.health(now=10.26).reason == "stale-vio-frame"
        assert monitor.health(now=10.43).reason == "stale-vio-frame"


def test_bad_vehicle_replay_and_malformed_frames_cannot_refresh_stream():
    with VioStreamMonitor(vehicle_id=0, port=0, max_age_s=0.25) as monitor:
        _send(monitor.port, sequence=2)
        assert monitor.health(now=10.13).healthy
        _send(monitor.port, vehicle_id=1, sequence=3, received_at=10.2, published_at=10.2)
        _send(monitor.port, sequence=1, received_at=10.2, published_at=10.2)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(b"not-json", ("127.0.0.1", monitor.port))
        assert monitor.health(now=10.27).reason == "stale-vio-frame"


def test_excessive_transport_delay_is_rejected_even_when_publish_is_recent():
    with VioStreamMonitor(vehicle_id=0, port=0, max_age_s=0.25) as monitor:
        _send(monitor.port, received_at=9.7, published_at=10.0)
        assert monitor.health(now=10.01).reason == "delayed-vio-frame"


def test_relay_frame_encoding_drives_the_real_monitor():
    with VioStreamMonitor(vehicle_id=0, port=0) as monitor:
        frame = encode_vio_stream_frame(
            vehicle_id=0, sequence=7, source_stamp_ns=321,
            received_at=10.0, published_at=10.12,
        )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(frame, ("127.0.0.1", monitor.port))
        assert monitor.health(now=10.13).healthy


def test_new_relay_sequence_with_repeated_source_timestamp_does_not_refresh_vio():
    with VioStreamMonitor(vehicle_id=0, port=0, max_age_s=0.25) as monitor:
        _send(monitor.port, sequence=1, source_stamp_ns=123,
              received_at=10.0, published_at=10.0)
        assert monitor.health(now=10.01).healthy
        _send(monitor.port, sequence=2, source_stamp_ns=123,
              received_at=10.30, published_at=10.30)
        assert monitor.health(now=10.31).reason == "stale-vio-frame"
