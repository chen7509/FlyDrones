"""Same-owner receiver gate; real codec bytes, no sockets or native processes."""

import os
import socket
import subprocess

import pytest


@pytest.fixture(autouse=True)
def inert(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("native/network forbidden")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(os, "system", denied)


def test_parameter_query_is_read_only_and_reset_unknown_never_publishable():
    from tools.benchmark.disarmed_estimate_receiver import DisarmedEstimateReceiver
    from tools.benchmark.openvins_timesync_wire import PinnedCodec

    codec = PinnedCodec()
    observer = DisarmedEstimateReceiver()
    raw = observer.request(codec, 41, 1_000)
    row = codec.decode_datagram(raw)[0]
    assert row["type"] == "PARAM_REQUEST_READ"
    assert row["fields"]["target_system"] == 9
    assert row["fields"]["param_id"] == "EKF2_EV_CTRL"
    from pymavlink.dialects.v20 import common

    encoder = common.MAVLink(None, srcSystem=9, srcComponent=1)
    response = common.MAVLink_param_value_message(b"EKF2_EV_CTRL", 0.0, common.MAV_PARAM_TYPE_INT32, 1, 0).pack(encoder)
    observer.receive(codec.decode_datagram(response), 1_001)
    assert observer.check(1_002, disarmed=True)["receiver_only_verified"] is True
    with pytest.raises(RuntimeError, match="reset"):
        observer.require_publishable({"reset_counter": None})


@pytest.mark.parametrize("case", ["noquery", "expired", "enabled", "armed"])
def test_receiver_gate_refuses_missing_late_enabled_or_armed(case):
    from pymavlink.dialects.v20 import common

    from tools.benchmark.disarmed_estimate_receiver import DisarmedEstimateReceiver
    from tools.benchmark.openvins_timesync_wire import PinnedCodec

    codec = PinnedCodec()
    observer = DisarmedEstimateReceiver()
    if case != "noquery":
        observer.request(codec, 0, 100)
    encoder = common.MAVLink(None, srcSystem=9, srcComponent=1)
    raw = common.MAVLink_param_value_message(
        b"EKF2_EV_CTRL", 1.0 if case == "enabled" else 0.0, common.MAV_PARAM_TYPE_INT32, 1, 0
    ).pack(encoder)
    with pytest.raises(ValueError):
        observer.receive(codec.decode_datagram(raw), 2_000_000_100 if case == "expired" else 101)
        observer.check(102, disarmed=case != "armed")


def test_actual_observed_poll_routes_query_through_existing_send_and_sequence():
    from types import SimpleNamespace

    from tools.benchmark.disarmed_estimate_receiver import DisarmedEstimateReceiver
    from tools.benchmark.openvins_observed_wire_session import ObservedWireSession
    from tools.benchmark.openvins_timesync_wire import PinnedCodec

    # This exercises the new production scheduling method with inert boundary
    # protocols; existing owner/clock integration checks are verified separately.
    owner = object.__new__(ObservedWireSession)
    owner._maintenance = object()
    owner._estimate_events = []
    owner._estimate_receiver = DisarmedEstimateReceiver()
    codec = PinnedCodec()
    wire = SimpleNamespace(_codec=codec, _sequence=32, _peer=("127.0.0.1", 14588), _last_unarmed=100)
    owner._core = SimpleNamespace(_wire=wire, _owned=SimpleNamespace(check=lambda **kwargs: None))
    owner._operation = lambda action, commit: action()
    owner._context = lambda: None
    owner._clock = lambda: 101
    events, sent = [], []
    owner._forward = lambda source, event: events.append((source, event))

    def send(raw, peer):
        sent.append((raw, peer))
        return len(raw)

    owner._send_interval = send
    owner.poll_estimate_receiver()
    assert wire._sequence == 33
    assert len(sent) == 1
    assert codec.decode_datagram(sent[0][0])[0]["type"] == "PARAM_REQUEST_READ"
    assert owner._estimate_receiver.send_events[0]["bytes_returned"] == len(sent[0][0])
    owner.poll_estimate_receiver()
    assert len(sent) == 1  # Pending response never opens another request/socket.
