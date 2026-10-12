"""Pure study admission, never binds a socket or starts a source."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.benchmark.probe_kernel_datagram_arrival as study
from tools.benchmark.probe_kernel_datagram_arrival import CONDITIONS, SOURCES, validate_profile

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def profile(tmp_path):
    root = tmp_path / "static-study"
    for name in SOURCES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    abi = root / CONDITIONS["abi_path"]
    abi.parent.mkdir(parents=True, exist_ok=True)
    abi.write_bytes((ROOT / "tests/fixtures/kernel_timestampns/new-abi-x86_64.json").read_bytes())
    (root / CONDITIONS["probe_path"]).write_bytes(b"synthetic probe byte identity; never executed")

    def sha(name):
        return hashlib.sha256((root / name).read_bytes()).hexdigest()

    value = {**CONDITIONS, "sources": {name: sha(name) for name in SOURCES},
             "abi_sha256": sha(CONDITIONS["abi_path"]), "probe_sha256": sha(CONDITIONS["probe_path"])}
    return value, root


def check(profile):
    value, root = profile
    raw = json.dumps(value).encode()
    return validate_profile(raw, hashlib.sha256(raw).hexdigest(), root)


def test_matching_declared_profile_is_read_only(profile):
    assert check(profile) == profile[0]


@pytest.mark.parametrize("field,value", [("count", 4), ("delay_ns", 1), ("outer_timeout_s", 30),
                                        ("outer_kill_after_s", True), ("run_id", "other")])
def test_frozen_condition_drift_refuses(profile, field, value):
    profile[0][field] = value
    with pytest.raises(ValueError, match="condition"):
        check(profile)


def test_source_inventory_or_source_digest_cannot_be_relabelled(profile):
    profile[0]["sources"][SOURCES[0]] = "0" * 64
    with pytest.raises(ValueError, match="source changed"):
        check(profile)
    profile[0]["sources"].pop(SOURCES[0])
    with pytest.raises(ValueError, match="source inventory"):
        check(profile)


def test_wrong_abi_probe_or_profile_hash_refuses(profile):
    value, root = profile
    raw = json.dumps(value).encode()
    with pytest.raises(ValueError, match="digest"):
        validate_profile(raw, "0" * 64, root)
    value["probe_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="capability"):
        check(profile)


@pytest.fixture
def fake_run(monkeypatch, profile):
    """In-memory protocol/close injection; never creates a native socket."""
    value, root = profile
    monkeypatch.setattr(study, "ROOT", root)
    monkeypatch.setattr(study.time, "sleep", lambda _seconds: None)
    real_times = iter([40_000_000] * 6 + [100_000_000] * 3)
    monkeypatch.setattr(study.time, "time_ns", lambda: next(real_times))
    sockets, receivers = [], []
    control = {"expected_drift": False, "constructor_failure": False}

    class Socket:
        def __init__(self, *_args):
            self.sent = []
            sockets.append(self)

        def bind(self, _peer): pass
        def setblocking(self, _value): pass
        def settimeout(self, _value): pass
        def setsockopt(self, *_args): pass
        def sendto(self, data, _peer):
            self.sent.append(data)
            return len(data)

    class Timestamp:
        def __init__(self, *_args): pass
        def enable_before_bind(self, _sock): pass
        @property
        def evidence(self): return {"profile_marker": "kept-before-receiver"}

    class Receiver:
        def __init__(self, _sock, _guard, _clock, _now, journal, **_kwargs):
            if control["constructor_failure"]:
                journal({"kind": "refusal", "reason": "injected initial option failure"})
                raise ValueError("injected initial option failure")
            self.journal = journal
            self.index = 0
            self.evidence = {"datagram_returns": 0, "retained_marker": "raw-profile-clock"}
            receivers.append(self)

        def poll(self):
            if len(receivers) == 2:
                self.journal({"kind": "unexpected-option-error", "raw": "retained"})
                if control["expected_drift"]:
                    raise ValueError("timestamp option changed")
                raise ValueError("injected native option failure")
            self.evidence["datagram_returns"] += 1
            packet = SimpleNamespace(data=sockets[1].sent[self.index], peer=tuple(value["peer"]),
                                     kernel_received_realtime_ns=50_000_000, received_ns=100)
            self.index += 1
            return packet

    monkeypatch.setattr(study.socket, "socket", Socket)
    monkeypatch.setattr(study, "KernelTimestampNS", Timestamp)
    monkeypatch.setattr(study, "DatagramReceiver", Receiver)
    monkeypatch.setattr(study, "snapshot", lambda _sock: {"fd": 99})
    monkeypatch.setattr(study, "close_owned", lambda _sock, rows: rows.append({"fd": 99, "fileno_after": -1}))
    return value, root, receivers, control


def test_unexpected_drift_failure_retains_case_events_and_profile(fake_run, tmp_path):
    value, root, _receivers, _control = fake_run
    output = tmp_path / "failed-run"
    raw = json.dumps(value).encode()
    path = root / "profile.json"
    path.write_bytes(raw)
    with pytest.raises(RuntimeError, match="retain"):
        study.run(value, output, profile_path=path, profile_sha256=hashlib.sha256(raw).hexdigest())
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "failed"
    assert result["option_drift"]["events"] == [{"kind": "unexpected-option-error", "raw": "retained"}]
    assert result["option_drift"]["receiver_evidence"]["retained_marker"] == "raw-profile-clock"
    assert result["profile_post_verified"] is True


@pytest.mark.parametrize("cases_pass", [False, True])
def test_study_always_records_post_source_drift_as_failure(fake_run, tmp_path, monkeypatch, cases_pass):
    value, root, _receivers, control = fake_run
    control["expected_drift"] = cases_pass
    raw = json.dumps(value).encode()
    path = root / "profile.json"
    path.write_bytes(raw)
    original = study.validate_profile
    calls = []

    def validate(*args):
        calls.append(True)
        if len(calls) == 2:
            (root / SOURCES[0]).write_bytes(b"injected source drift")
        return original(*args)

    monkeypatch.setattr(study, "validate_profile", validate)
    output = tmp_path / "post-drift"
    with pytest.raises(RuntimeError, match="retain"):
        study.run(value, output, profile_path=path, profile_sha256=hashlib.sha256(raw).hexdigest())
    result = json.loads((output / "result.json").read_text())
    assert len(calls) == 2
    assert result["status"] == "failed" and result["profile_post_verified"] is False
    assert any("post profile:" in error and "source changed" in error for error in result["errors"])


def test_close_confirmation_failure_retains_actual_descriptor_observations():
    class Socket:
        def fileno(self): return 777777
        def close(self): pass

    rows = []
    with pytest.raises(RuntimeError, match="closure"):
        study.close_owned(Socket(), rows)
    assert rows == [{"fd": 777777, "fileno_after": 777777, "fstat_errno": 9, "close_error": None}]


def test_receiver_constructor_refusal_keeps_journal_and_timestamp_profile(fake_run, tmp_path):
    value, root, _receivers, control = fake_run
    control["constructor_failure"] = True
    raw = json.dumps(value).encode()
    path = root / "profile.json"
    path.write_bytes(raw)
    output = tmp_path / "constructor-refusal"
    with pytest.raises(RuntimeError, match="retain"):
        study.run(value, output, profile_path=path, profile_sha256=hashlib.sha256(raw).hexdigest())
    result = json.loads((output / "result.json").read_text())
    assert result["normal"]["events"] == [{"kind": "refusal", "reason": "injected initial option failure"}]
    assert result["normal"]["timestamp_profile_evidence"] == {"profile_marker": "kept-before-receiver"}
