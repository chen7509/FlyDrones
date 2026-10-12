"""Prospective admission and mocked study lifecycle; never opens native sockets."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.benchmark.probe_kernel_rx_timestamping as study

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    root = tmp_path / "inputs"
    for name in study.SOURCES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    abi = root / study.ABI_PATH
    abi.parent.mkdir(parents=True, exist_ok=True)
    abi.write_bytes((ROOT / "tests/fixtures/kernel_timestampns/rx-generated-x86_64.json").read_bytes())
    probe = root / study.PROBE_PATH
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_bytes(b"fake probe for admission tests; never executed")
    monkeypatch.setattr(study, "PROBE_SHA", hashlib.sha256(probe.read_bytes()).hexdigest())
    value = {**study.CONDITIONS, "abi_sha256": study.ABI_SHA, "probe_sha256": study.PROBE_SHA,
             "sources": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in study.SOURCES}}
    path = root / "profile.json"
    path.write_text(json.dumps(value))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return root, value, path, digest


def test_exact_profile_is_read_only(frozen):
    root, value, path, digest = frozen
    assert study.validate_profile(path.read_bytes(), digest, root) == value


@pytest.mark.parametrize("field,value", [("count", 2), ("run_id", "opaque-loopback-v1"),
                                       ("delay_ns", 1), ("outer_timeout_s", 30), ("outer_kill_after_s", True)])
def test_declared_conditions_cannot_drift(frozen, field, value):
    root, profile, _path, _digest = frozen
    profile[field] = value
    raw = json.dumps(profile).encode()
    with pytest.raises(ValueError, match="condition"):
        study.validate_profile(raw, hashlib.sha256(raw).hexdigest(), root)


def test_rehashed_capability_substitution_refuses(frozen):
    root, profile, _path, _digest = frozen
    profile["abi_sha256"] = "0" * 64
    raw = json.dumps(profile).encode()
    with pytest.raises(ValueError, match="pinned"):
        study.validate_profile(raw, hashlib.sha256(raw).hexdigest(), root)


def test_source_drift_or_missing_inventory_refuses(frozen):
    root, profile, _path, _digest = frozen
    (root / study.SOURCES[0]).write_bytes(b"drift")
    raw = json.dumps(profile).encode()
    with pytest.raises(ValueError, match="source"):
        study.validate_profile(raw, hashlib.sha256(raw).hexdigest(), root)


@pytest.mark.parametrize("fault", ["duplicate", "unknown", "inventory", "missing_capability"])
def test_declared_admission_faults_are_independently_refused(frozen, fault):
    root, profile, _path, _digest = frozen
    if fault == "unknown":
        profile["extra"] = False
    if fault == "inventory":
        profile["sources"].pop(study.SOURCES[0])
    if fault == "missing_capability":
        (root / study.ABI_PATH).unlink()
    raw = json.dumps(profile).encode()
    if fault == "duplicate":
        raw = b'{"count":3,' + raw[1:]
    with pytest.raises((ValueError, FileNotFoundError)):
        study.validate_profile(raw, hashlib.sha256(raw).hexdigest(), root)


@pytest.fixture
def mock_runtime(frozen, monkeypatch):
    root, value, path, digest = frozen
    monkeypatch.setattr(study, "ROOT", root)
    monkeypatch.setattr(study, "check_module_origins", lambda: None)
    controls = {"constructor_error": False, "read_error": False, "short_send": False, "close_error": False,
                "payload_error": False, "queue_error": False, "unexpected_drift": False}
    sockets = []
    monkeypatch.setattr(study.time, "sleep", lambda _seconds: None)
    times = iter([40_000_000] * 6 + [100_000_000] * 3)
    monkeypatch.setattr(study.time, "time_ns", lambda: next(times))

    class Sock:
        def __init__(self, *_args):
            self.sent = []
            sockets.append(self)
        def bind(self, _peer): pass
        def setblocking(self, _value): pass
        def settimeout(self, _value): pass
        def setsockopt(self, *_args): pass
        def sendto(self, data, _peer):
            self.sent.append(data)
            return len(data) - 1 if controls["short_send"] else len(data)

    class Profile:
        def __init__(self, *_args): pass
        def enable_before_bind(self, _sock): pass
        @property
        def evidence(self):
            return {"profile_evidence": "retained", "abi": {"sol_socket": 1, "so_timestamping_new": 65}}

    class Receiver:
        def __init__(self, _sock, _guard, _now, _start, journal, **_kwargs):
            self.journal, self.index = journal, 0
            self.evidence = {"datagram_returns": 0}
            if controls["constructor_error"]:
                journal({"kind": "refusal", "reason": "constructor failure"})
                raise ValueError("constructor failure")
        def poll(self):
            if len(sockets) == 3:
                self.journal({"kind": "refusal", "reason": "kernel timestamp option changed"})
                if controls["unexpected_drift"]:
                    raise ValueError("injected unexpected drift error")
                raise ValueError("kernel timestamp option changed")
            if controls["read_error"]:
                self.journal({"kind": "receive_return", "data_hex": "6162", "ancillary_raw": []})
                raise ValueError("missing generated metadata")
            self.evidence["datagram_returns"] += 1
            packet = SimpleNamespace(data=b"unexpected" if controls["payload_error"] else sockets[1].sent[self.index],
                                     peer=tuple(value["peer"]),
                                     kernel_received_realtime_ns=99_000_000 if controls["queue_error"] else 50_000_000,
                                     received_ns=100)
            self.index += 1
            return packet

    def close(_sock, rows):
        rows.append({"fd": 9, "fileno_after": -1, "fstat_errno": 9})
        if controls["close_error"]:
            raise OSError("injected owned close error")

    monkeypatch.setattr(study.socket, "socket", Sock)
    monkeypatch.setattr(study, "KernelRXTimestamping", Profile)
    monkeypatch.setattr(study, "DatagramReceiver", Receiver)
    monkeypatch.setattr(study, "snapshot", lambda _sock: {"fd": 9})
    monkeypatch.setattr(study, "close_owned", close)
    return value, path, digest, controls


def invoke(mock_runtime, output):
    profile, path, digest, _controls = mock_runtime
    return study.run(profile, output, profile_path=path, profile_sha256=digest)


def test_mocked_normal_and_drift_are_retained(mock_runtime, tmp_path):
    result = invoke(mock_runtime, tmp_path / "normal")
    assert result["status"] == "passed" and len(result["normal"]["received"]) == 3
    assert result["option_drift"]["refused"] and result["profile_post_verified"]
    assert result["source_authenticated"] is False


@pytest.mark.parametrize("fault", ["constructor_error", "read_error", "short_send", "close_error"])
def test_failure_paths_keep_actual_partial_evidence(mock_runtime, tmp_path, fault):
    mock_runtime[3][fault] = True
    output = tmp_path / fault
    with pytest.raises(RuntimeError, match="retain"):
        invoke(mock_runtime, output)
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "failed" and result["profile_post_verified"]
    assert result["normal"]["timestamp_profile_evidence"]
    if fault == "constructor_error":
        assert result["normal"]["events"][0]["reason"] == "constructor failure"
    if fault == "read_error":
        assert result["normal"]["events"][0]["data_hex"] == "6162"
    if fault == "short_send":
        assert result["normal"]["sent"][0]["bytes"] < len(bytes.fromhex(result["normal"]["sent"][0]["payload_hex"]))
    assert result["owned_close"]


def test_post_source_drift_cannot_leave_passed_result(mock_runtime, tmp_path, monkeypatch):
    original = study.validate_profile
    calls = []
    def validate(*args):
        calls.append(True)
        if len(calls) == 2:
            raise ValueError("injected post source drift")
        return original(*args)
    monkeypatch.setattr(study, "validate_profile", validate)
    output = tmp_path / "post-drift"
    with pytest.raises(RuntimeError, match="retain"):
        invoke(mock_runtime, output)
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "failed" and not result["profile_post_verified"]
    assert any("post source drift" in error for error in result["errors"])


def test_post_admission_abi_read_failure_retains_failed_result(mock_runtime, tmp_path, monkeypatch):
    original = study.read_static
    calls = []
    def read(path):
        if Path(path) == study.ROOT / study.ABI_PATH:
            calls.append(True)
            if len(calls) == 3:
                raise OSError("injected ABI setup read failure")
        return original(path)
    monkeypatch.setattr(study, "read_static", read)
    output = tmp_path / "ABI-setup-failure"
    with pytest.raises(RuntimeError, match="retain"):
        invoke(mock_runtime, output)
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "failed" and result["profile_post_verified"]
    assert any("ABI setup" in error for error in result["errors"])


def test_post_send_clock_failure_keeps_actual_send_count(mock_runtime, tmp_path, monkeypatch):
    calls = []
    def clock():
        calls.append(True)
        if len(calls) == 2:
            raise OSError("injected post-send realtime failure")
        return 40_000_000
    monkeypatch.setattr(study.time, "time_ns", clock)
    output = tmp_path / "post-send-clock"
    with pytest.raises(RuntimeError, match="retain"):
        invoke(mock_runtime, output)
    result = json.loads((output / "result.json").read_text())
    assert len(result["normal"]["sent"]) == 1
    actual = result["normal"]["sent"][0]
    assert actual["bytes"] == len(bytes.fromhex(actual["payload_hex"]))
    assert actual["after_realtime_ns"] is None and actual["after_monotonic_ns"] is None


@pytest.mark.parametrize("fault", ["payload_error", "queue_error", "unexpected_drift"])
def test_qualification_failure_keeps_actual_return_and_drift_history(mock_runtime, tmp_path, fault):
    mock_runtime[3][fault] = True
    output = tmp_path / fault
    with pytest.raises(RuntimeError, match="retain"):
        invoke(mock_runtime, output)
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "failed" and result["normal"]["received"][0]["packet_returned"]
    assert result["normal"]["received"][0]["kernel_received_realtime_ns"]
    if fault == "unexpected_drift":
        assert result["option_drift"]["executed"] and not result["option_drift"]["refused"]
        assert result["option_drift"]["events"] and result["option_drift"]["receiver_evidence"]
