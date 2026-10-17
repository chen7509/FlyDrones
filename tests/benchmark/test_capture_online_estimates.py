"""Software integration only: constructed child protocol, real bounded files."""

import copy
import json
import os
import socket
import subprocess
from types import SimpleNamespace

import pytest

from tools.benchmark import capture_contract as contract
from tools.benchmark import capture_disarmed_sensors as capture
from tools.benchmark import openvins_online_shadow as shadow


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("native/process/network forbidden in software test body")

    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(os, "system", denied)


def selected(tmp_path):
    return capture.parse_capture_args(
        [
            "--output",
            str(tmp_path / "capture"),
            "--online-estimate-feed",
            "--shadow-binary",
            str(tmp_path / "native"),
            "--shadow-config",
            str(tmp_path / "estimator_config.yaml"),
            "--execution-contract",
            str(tmp_path / "execution.json"),
            "--runtime-binding",
            str(tmp_path / "binding.json"),
        ]
    )


def prediction():
    return dict(
        target_ns=20_000_000,
        last_camera_ns=12_000_000,
        available_imu_ns=24_000_000,
        filter_time_s=0.012,
        camera_imu_offset_s=0.0,
        internal_initialized=True,
        public_initialized=True,
        success=True,
        filter_unchanged=True,
        propagation_wall_s=0.0001,
        state13=[0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0, 0.0, 0.0],
        covariance12=[[1.0 if i == j else 0.0 for j in range(12)] for i in range(12)],
        trigger_sequence=6,
        native_begin_ns=110,
        native_end_ns=120,
        fusion_eligible=False,
        quality=None,
        reset_counter=None,
    )


def controlled_native(tmp_path, monkeypatch):
    calls = []
    rows = []

    def init(self, command, output, **kwargs):
        self.output = output
        self.process = SimpleNamespace(pid=9182, poll=lambda: None)
        self.closed, self.failed, self.sequence = False, None, 0
        self.timeout_s = 2.0
        (output / "fast.jsonl").write_bytes(b"")

    def send(self, action, pixels=None):
        calls.append(copy.deepcopy(action))
        if rows:
            with (self.output / "fast.jsonl").open("ab") as f:
                f.write(rows.pop(0))
        result = dict(
            sequence=self.sequence,
            kind={"imu": "I", "camera": "C"}[action["kind"]],
            sample_ns=action["sample_ns"],
            source_arrival_ns=80,
            dispatch_ns=90,
            receive_ns=100,
            start_ns=105,
            end_ns=125,
            acknowledged_ns=130,
            fusion_eligible=False,
            quality=None,
            reset_counter=None,
        )
        if action["kind"] == "camera":
            result.update(
                imu_state=[0.0] * 16,
                imu_covariance15=[[0.0] * 15 for _ in range(15)],
                internal_initialized=False,
                public_initialized=False,
            )
        self.sequence += 1
        return result

    def finish(self):
        self.closed = True
        return dict(exit=0, accepted=self.sequence, failure=self.failed)

    monkeypatch.setattr(shadow.NativeClient, "__init__", init)
    monkeypatch.setattr(shadow.NativeClient, "send", send)
    monkeypatch.setattr(shadow.NativeClient, "finish", finish)
    client = capture.make_capture_native_client(selected(tmp_path), tmp_path, on_first_ack=None)
    return client, calls, rows


def prime(client):
    for sample in (4, 8, 12, 16):
        client.send(dict(kind="imu", sample_ns=sample * 1_000_000))
    client.send(dict(kind="camera", sample_ns=12_000_000), b"pixels")
    client.send(dict(kind="imu", sample_ns=20_000_000))


def test_live_capture_consumes_real_file_at_matching_imu_ack(tmp_path, monkeypatch):
    # Break caught: returning only the IMU ack/discarding the native fast output.
    client, calls, rows = controlled_native(tmp_path, monkeypatch)
    prime(client)
    rows.append((json.dumps(prediction()) + "\n").encode())
    ack = client.send(dict(kind="imu", sample_ns=24_000_000))
    assert ack["sequence"] == 6
    summary = client.finish()
    records = [json.loads(line) for line in (tmp_path / "online-estimates.jsonl").read_text().splitlines()]
    fast = [r for r in records if r["event"] == "fast_prediction"]
    assert len(fast) == 1
    assert fast[0]["prediction"] == prediction()
    assert fast[0]["camera_ack_sequence"] == 4
    assert fast[0]["native_pid"] == 9182
    assert fast[0]["ack"]["sample_ns"] == 24_000_000
    assert fast[0]["fusion_eligible"] is False
    assert summary["online_estimates"]["fast_predictions"] == 1
    assert summary["online_estimates"]["controller_ready"] is False
    assert len(calls) == 7


@pytest.mark.parametrize("fault", ["missing", "truncated", "extra", "trigger", "sample", "camera", "clock", "oversized"])
def test_bad_native_output_latches_before_next_delivery(tmp_path, monkeypatch, fault):
    # Break caught: old/malformed/foreign native rows reach downstream as new estimates.
    client, calls, rows = controlled_native(tmp_path, monkeypatch)
    prime(client)
    row = prediction()
    if fault == "trigger":
        row["trigger_sequence"] = 5
    if fault == "sample":
        row["available_imu_ns"] = 28_000_000
    if fault == "camera":
        row["last_camera_ns"] = 8_000_000
    if fault == "clock":
        row["native_end_ns"] = 126
    data = (json.dumps(row) + "\n").encode()
    if fault == "missing":
        data = b""
    if fault == "truncated":
        data = data[:-1]
    if fault == "extra":
        data += data
    if fault == "oversized":
        data = b" " * 16_385
    rows.append(data)
    with pytest.raises((ValueError, RuntimeError)):
        client.send(dict(kind="imu", sample_ns=24_000_000))
    delivered = len(calls)
    with pytest.raises(RuntimeError):
        client.send(dict(kind="imu", sample_ns=28_000_000))
    assert len(calls) == delivered
    assert client.finish()["online_estimates"]["failure"]


def test_new_workload_is_forwarded_and_bound_to_exact_declaration(tmp_path):
    # Break caught: supervisor drops selection or an old declaration accepts it silently.
    args = selected(tmp_path)
    assert "--online-estimate-feed" in contract.worker_options(args)
    actual = contract.execution_contract(args, {"PATH": "fixture"})
    assert actual["online_estimate_feed"]["profile"] == "native-ack-fast-output-v1"
    old = copy.deepcopy(actual)
    old.pop("online_estimate_feed")
    args.execution_contract.write_text(json.dumps(old), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        contract.validate_declaration(args, {"PATH": "fixture"})


def test_old_output_is_rejected_before_child_construction(tmp_path, monkeypatch):
    # Break caught: a fresh label reuses a consumed native fast file.
    (tmp_path / "fast.jsonl").write_bytes(b"old\n")
    selected_args = selected(tmp_path)
    with pytest.raises(FileExistsError):
        capture.make_capture_native_client(selected_args, tmp_path, on_first_ack=None)
    assert not (tmp_path / "online-estimates.jsonl").exists()


def test_profile_requires_bound_native_capture_before_effects(tmp_path):
    with pytest.raises(SystemExit):
        capture.parse_capture_args(["--output", str(tmp_path), "--online-estimate-feed"])
    assert list(tmp_path.iterdir()) == []


def test_real_native_pre_camera_null_is_consumed_unqualified(tmp_path, monkeypatch):
    # Native writer serializes its internal negative camera sentinel as JSON null.
    client, calls, rows = controlled_native(tmp_path, monkeypatch)
    for sample in (4, 8, 12, 16, 20):
        client.send(dict(kind="imu", sample_ns=sample * 1_000_000))
    row = prediction()
    row.update(
        last_camera_ns=None,
        trigger_sequence=5,
        success=False,
        internal_initialized=False,
        public_initialized=False,
        state13=None,
        covariance12=None,
    )
    rows.append((json.dumps(row) + "\n").encode())
    client.send(dict(kind="imu", sample_ns=24_000_000))
    summary = client.finish()["online_estimates"]
    assert summary["fast_predictions"] == 1
    assert summary["camera_states"] == 0
    assert summary["controller_ready"] is False


def test_replaced_fast_path_is_not_read_as_current_owned_output(tmp_path, monkeypatch):
    # Modeled pathname replacement: Windows denies rename of a real open descriptor.
    # Break caught: continuing a stale opened inode after the selected inode changes.
    client, calls, rows = controlled_native(tmp_path, monkeypatch)
    client.send(dict(kind="imu", sample_ns=4_000_000))
    path = tmp_path / "fast.jsonl"
    other = tmp_path / "other-fast.jsonl"
    other.write_bytes(b"")
    replacement = other.lstat()
    original_lstat = type(path).lstat
    monkeypatch.setattr(type(path), "lstat", lambda self: replacement if self == path else original_lstat(self))
    with pytest.raises(ValueError, match="changed"):
        client.send(dict(kind="imu", sample_ns=8_000_000))
    assert client.finish()["online_estimates"]["failure"]


def test_parent_cleanup_failure_still_closes_live_resources(tmp_path, monkeypatch):
    client, calls, rows = controlled_native(tmp_path, monkeypatch)
    client.send(dict(kind="imu", sample_ns=4_000_000))

    def fail(self):
        raise RuntimeError("primary cleanup failure")

    monkeypatch.setattr(shadow.NativeClient, "finish", fail)
    with pytest.raises(RuntimeError, match="primary cleanup failure"):
        client.finish()
    assert client._events.closed
    assert client._fast_fd is None


def test_live_feed_failure_reaches_actual_shadow_capture_latch(tmp_path, monkeypatch):
    # Break caught: capture continues native delivery after missing live output.
    client, calls, rows = controlled_native(tmp_path, monkeypatch)
    directory = tmp_path / "shadow"
    directory.mkdir()
    source = shadow.ShadowInput(client, directory, session_id="native-9182")
    for sample in (4, 8, 12, 16, 20, 24):
        stamp = sample * 1_000_000
        source.on_record(
            dict(
                kind="imu",
                sample_ns=stamp,
                arrival_monotonic_ns=stamp + 1,
                observed_sim_ns=stamp,
                gyro_flu=[0.0, 0.0, 0.0],
                accel_flu=[0.0, 0.0, 9.81],
            ),
            None,
        )
    assert "missing/truncated/extra" in source.failure
    delivered = len(calls)
    source.on_record(dict(kind="imu", sample_ns=28_000_000), None)
    assert len(calls) == delivered
    result = source.finish()
    assert result["skipped_after_failure"] == 1
    assert result["fusion_eligible"] is False
    client.finish()


def test_elapsed_transport_and_output_budget_refuses_before_next_request(tmp_path, monkeypatch):
    from tools.benchmark import capture_online_estimates as live

    client, calls, rows = controlled_native(tmp_path, monkeypatch)
    times = iter((10.0, 12.0))
    monkeypatch.setattr(live.time, "monotonic", lambda: next(times))
    with pytest.raises(TimeoutError, match="deadline"):
        client.send(dict(kind="imu", sample_ns=4_000_000))
    with pytest.raises(RuntimeError):
        client.send(dict(kind="imu", sample_ns=8_000_000))
    assert len(calls) == 1
    client.finish()


def test_internal_negative_camera_sentinel_is_not_the_wire_value(tmp_path, monkeypatch):
    client, calls, rows = controlled_native(tmp_path, monkeypatch)
    for sample in (4, 8, 12, 16, 20):
        client.send(dict(kind="imu", sample_ns=sample * 1_000_000))
    row = prediction()
    row.update(
        last_camera_ns=-1,
        trigger_sequence=5,
        success=False,
        internal_initialized=False,
        public_initialized=False,
        state13=None,
        covariance12=None,
    )
    rows.append((json.dumps(row) + "\n").encode())
    with pytest.raises(ValueError):
        client.send(dict(kind="imu", sample_ns=24_000_000))
    client.finish()


@pytest.mark.parametrize("kind", ["target_imu", "other_imu", "camera"])
def test_ack_sample_cannot_disagree_with_action_even_when_fast_output_agrees(tmp_path, monkeypatch, kind):
    client, calls, rows = controlled_native(tmp_path, monkeypatch)
    if kind != "other_imu":
        prime(client)
    else:
        client.send(dict(kind="imu", sample_ns=4_000_000))
    parent_send = shadow.NativeClient.send

    def mismatched(self, action, pixels=None):
        ack = parent_send(self, action, pixels)
        ack["sample_ns"] += 4_000_000
        return ack

    monkeypatch.setattr(shadow.NativeClient, "send", mismatched)
    if kind == "target_imu":
        row = prediction()
        row["available_imu_ns"] = 28_000_000
        rows.append((json.dumps(row) + "\n").encode())
    action = dict(
        kind="camera" if kind == "camera" else "imu",
        sample_ns={"target_imu": 24_000_000, "other_imu": 8_000_000, "camera": 16_000_000}[kind],
    )
    with pytest.raises(ValueError, match="sample"):
        client.send(action, b"pixels" if kind == "camera" else None)
    delivered = len(calls)
    with pytest.raises(RuntimeError):
        client.send(dict(kind="imu", sample_ns=28_000_000))
    assert len(calls) == delivered
    client.finish()


class CloseFailure:
    def __init__(self, stream, attempts):
        self.stream, self.attempts = stream, attempts

    def close(self):
        self.attempts.append("journal")
        self.stream.close()
        raise OSError("journal close failure")


def test_simultaneous_cleanup_failures_retain_primary_and_attempt_both_closes(tmp_path, monkeypatch):
    from tools.benchmark import capture_online_estimates as live

    client, calls, rows = controlled_native(tmp_path, monkeypatch)
    client.send(dict(kind="imu", sample_ns=4_000_000))
    attempts = []
    client._events = CloseFailure(client._events, attempts)
    real_close = os.close

    def fd_close(fd):
        attempts.append("descriptor")
        real_close(fd)
        raise OSError("descriptor close failure")

    def parent_close(self):
        raise RuntimeError("primary parent cleanup failure")

    monkeypatch.setattr(live.os, "close", fd_close)
    monkeypatch.setattr(shadow.NativeClient, "finish", parent_close)
    with pytest.raises(RuntimeError, match="primary parent cleanup failure") as caught:
        client.finish()
    assert attempts == ["descriptor", "journal"]
    assert "descriptor close failure" in str(caught.value.__notes__)
    assert "journal close failure" in str(caught.value.__notes__)


def test_constructor_rollback_close_failure_keeps_parent_start_failure(tmp_path, monkeypatch):
    from pathlib import Path

    real_open = Path.open
    attempts = []

    def opened(path, *args, **kwargs):
        stream = real_open(path, *args, **kwargs)
        return CloseFailure(stream, attempts) if path.name == "online-estimates.jsonl" else stream

    def parent_init(self, *args, **kwargs):
        raise RuntimeError("primary construction failure")

    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(shadow.NativeClient, "__init__", parent_init)
    with pytest.raises(RuntimeError, match="primary construction failure") as caught:
        capture.make_capture_native_client(selected(tmp_path), tmp_path, on_first_ack=None)
    assert attempts == ["journal"]
    assert "journal close failure" in str(caught.value.__notes__)
