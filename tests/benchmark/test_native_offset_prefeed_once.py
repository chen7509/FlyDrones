"""New production prefeed checks with inert OS boundaries; no native process."""

import json
import os
import socket
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("native/network/resource execution forbidden")

    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(os, "system", denied)


def ready(**changes):
    return dict(
        event="native_prefeed_ready",
        native_profile="offset-reset-v2",
        native_pid=42,
        native_session="a" * 64,
        camera_imu_offset_ns=7000000,
        reset_total=0,
        reset_counter=0,
        native_lifecycle_known=True,
        **changes,
    )


def client(tmp_path, monkeypatch, payload=None, check=None):
    from tools.benchmark.offset_reset_native_source import NativeLifecycleBinding, OffsetResetNativeClient

    c = object.__new__(OffsetResetNativeClient)
    c.process = SimpleNamespace(pid=42, poll=lambda: None, stdin=SimpleNamespace(fileno=lambda: 9))
    c.timeout_s, c.sequence, c.closed, c.failed, c._feed_failure = 2.0, 0, False, None, None
    c.output, c.buffer = tmp_path, b""
    c.managed_source = SimpleNamespace(
        lifecycle=NativeLifecycleBinding(c.process, "a" * 64, 7000000), latch_failure=lambda exc: None
    )
    c.ack_fd = 8
    c._prefeed_released = False
    wire = [json.dumps(ready() if payload is None else payload).encode() + b"\n"]
    monkeypatch.setattr("select.select", lambda reads, writes, errors, timeout: (reads, writes, []))
    monkeypatch.setattr(os, "read", lambda fd, size: wire.pop(0) if wire else b"")
    sent = []
    monkeypatch.setattr(os, "write", lambda fd, raw: sent.append(raw) or len(raw))

    def observe(role, phase):
        if check:
            check()
        return dict(observed_files_covered=True, identity_after=dict(pid=42), role=role, phase=phase)

    b = SimpleNamespace(required_owned={"openvins": ["prefeed", "ready", "prestop"]}, observe_owned=observe, errors=[])
    return c, b, sent


def test_send_cannot_feed_before_barrier_is_released(tmp_path, monkeypatch):
    from tools.benchmark.managed_capture_source import ManagedEstimateNativeClient

    c, _, _ = client(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(ManagedEstimateNativeClient, "send", lambda *a, **k: calls.append(a) or {})
    with pytest.raises(ValueError):
        c.send(dict(kind="imu"))
    assert calls == []


def test_ready_identity_and_maps_precede_exact_one_release(tmp_path, monkeypatch):
    def no_early_release():
        assert sent == []

    c, binding, sent = client(tmp_path, monkeypatch, check=no_early_release)
    result = c.release_prefeed(binding, "openvins")
    assert sent == [b"\x01"] and result["release_bytes_returned"] == 1
    assert result["source_authenticated"] is False
    with pytest.raises(ValueError):
        c.release_prefeed(binding, "openvins")
    assert sent == [b"\x01"]


@pytest.mark.parametrize("fault", ["nonce", "pid", "offset", "maps", "death", "timeout", "short"])
def test_bad_or_stale_prefeed_never_grants_input(tmp_path, monkeypatch, fault):
    payload = ready()
    if fault == "nonce":
        payload["native_session"] = "b" * 64
    if fault == "pid":
        payload["native_pid"] = 43
    if fault == "offset":
        payload["camera_imu_offset_ns"] = -7000000
    c, binding, sent = client(tmp_path, monkeypatch, payload)
    if fault == "maps":
        binding.observe_owned = lambda *a: dict(observed_files_covered=False)
    if fault == "death":
        binding.observe_owned = lambda *a: (
            setattr(c.process, "poll", lambda: 2) or dict(observed_files_covered=True, identity_after=dict(pid=42))
        )
    if fault == "timeout":
        ticks = iter([0, 0, 0, 3, 3, 3, 3])
        monkeypatch.setattr("time.monotonic", lambda: next(ticks))
    if fault == "short":
        monkeypatch.setattr(os, "write", lambda fd, raw: 0)
    with pytest.raises((ValueError, RuntimeError, TimeoutError)):
        c.release_prefeed(binding, "openvins")
    assert c._prefeed_released is False and c.failed
    if fault != "short":
        assert sent == []


def test_factory_refuses_missing_prefeed_binding_before_child(tmp_path, monkeypatch):
    from tools.benchmark import capture_disarmed_sensors as capture

    calls = []
    monkeypatch.setattr(capture, "make_capture_native_client", lambda *a, **k: calls.append(a))
    args = SimpleNamespace(native_estimate_profile="offset-reset-v2")
    with pytest.raises(ValueError):
        capture.start_bound_native_client(args, tmp_path, None, "openvins", lambda: None, "s")
    assert calls == []


@pytest.mark.parametrize("data", [b"", b"{}\n", b"x" * 8193, b"{}\n{}\n", b'{"event":1,"event":2}\n'])
def test_malformed_readiness_never_releases(tmp_path, monkeypatch, data):
    c, binding, sent = client(tmp_path, monkeypatch)
    chunks = [data]
    monkeypatch.setattr(os, "read", lambda *a: chunks.pop(0) if chunks else b"")
    with pytest.raises((ValueError, RuntimeError, EOFError)):
        c.release_prefeed(binding, "openvins")
    assert c.failed and not c._prefeed_released and sent == []


def test_production_factory_registers_before_maps_and_rolls_back_once(tmp_path, monkeypatch):
    from tools.benchmark import capture_disarmed_sensors as capture

    events = []

    class Native:
        process = SimpleNamespace(pid=42)

        def release_prefeed(self, binding, role):
            assert events == ["construct", "register"]
            events.append("prefeed")
            raise RuntimeError("modeled maps refusal")

        def finish(self):
            events.append("finish")
            raise RuntimeError("secondary cleanup")

    native = Native()
    monkeypatch.setattr(capture, "make_capture_native_client", lambda *a, **k: events.append("construct") or native)
    binding = SimpleNamespace(
        required_owned={"openvins": ["prefeed", "ready", "prestop"]}, register_owned=lambda *a: events.append("register")
    )
    with pytest.raises(RuntimeError, match="maps refusal") as caught:
        capture.start_bound_native_client(
            SimpleNamespace(native_estimate_profile="offset-reset-v2", shadow_binary="new"),
            tmp_path,
            binding,
            "openvins",
            lambda: None,
            "s",
        )
    assert events == ["construct", "register", "prefeed", "finish"]
    assert "secondary cleanup" in repr(caught.value.online_estimate_cleanup_errors)
