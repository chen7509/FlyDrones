"""Prospective offset/native-lifecycle/receiver integration; injected OS only."""

import os
import socket
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def inert(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("native process/network forbidden in software tests")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(os, "system", denied)


@pytest.mark.parametrize("offset,boundary", [(7_000_000, 108_000_000), (-7_000_000, 96_000_000)])
def test_offset_causal_release_uses_shifted_imu_boundary_without_relabeling_image(offset, boundary):
    from tools.benchmark.offset_reset_native_source import OffsetCausalInput

    obj = OffsetCausalInput(session_id="native-session", clock_id="clock", offset_ns=offset)
    obj._pending = {
        "rgb": {100_000_000: ({"arrival_monotonic_ns": 1}, 0)},
        "info": {100_000_000: ({"arrival_monotonic_ns": 2, "camera_info": {}}, 1)},
    }
    obj._imu_first = 4_000_000
    obj._imu_latest = 100_000_000 + offset
    assert obj._release() == []
    obj._imu_latest = boundary
    value = obj._release()[0]
    assert value["sample_ns"] == 100_000_000
    assert value["imu_lookup_ns"] == 100_000_000 + offset
    assert value["imu_boundary_ns"] == boundary


@pytest.mark.parametrize("fault", ["native_pid", "native_session", "camera_imu_offset_ns", "reset_total"])
def test_native_lifecycle_actual_fields_cannot_change_or_resume(fault):
    from tools.benchmark.offset_reset_native_source import NativeLifecycleBinding

    process = SimpleNamespace(pid=42, poll=lambda: None)
    binding = NativeLifecycleBinding(process, "a" * 64, 7_000_000)
    row = dict(
        native_profile="offset-reset-v2",
        native_pid=42,
        native_session="a" * 64,
        camera_imu_offset_ns=7_000_000,
        reset_total=0,
        reset_counter=0,
        native_lifecycle_known=True,
    )
    assert binding.accept(row) == 0
    row[fault] = "b" * 64 if fault == "native_session" else row[fault] + 1
    with pytest.raises(ValueError):
        binding.accept(row)
    with pytest.raises(ValueError, match="latched"):
        binding.accept({})


def test_disarmed_odometry_encodes_current_native_sample_and_unknown_quality():
    from tools.benchmark.disarmed_odometry_receiver import DisarmedOdometryReceiver
    from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock
    from tools.benchmark.openvins_timesync_wire import PinnedCodec

    state = dict(
        sample_ns=120_000_000,
        reset_counter=0,
        reset_total=0,
        native_profile="offset-reset-v2",
        native_state13=[0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0, 0.0, 0.5],
        native_covariance12=np.eye(12).tolist(),
        native_session="a" * 64,
        native_pid=42,
        quality=None,
    )
    source = SimpleNamespace(wire_snapshot=lambda sim: state)
    receiver = DisarmedOdometryReceiver(source)
    clock = RemoteMonotonicClock("wire", sim_origin_ns=0, remote_origin_ns=1_000_000)
    receiver.response_ns = 100
    raw = receiver.odometry(PinnedCodec(), clock, 13, 101, 120_000_000, disarmed=True)
    row = PinnedCodec().decode_datagram(raw)[0]
    assert row["type"] == "ODOMETRY"
    fields = row["fields"]
    assert fields["time_usec"] == 121000
    assert fields["quality"] == 0 and fields["reset_counter"] == 0
    assert fields["frame_id"] == 20 and fields["child_frame_id"] == 12
    assert fields["z"] == -3.0 and fields["vx"] == 4.0
    assert receiver.odometry(PinnedCodec(), clock, 14, 102, 120_000_000, disarmed=True) is None


def selected_args(tmp_path):
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    return parse_capture_args(
        [
            "--output",
            str(tmp_path / "capture"),
            "--shadow-binary",
            str(tmp_path / "native-v2"),
            "--shadow-config",
            str(tmp_path / "estimator_config.yaml"),
            "--online-estimate-feed",
            "--managed-source-config",
            str(tmp_path / "managed.json"),
            "--managed-source-sha256",
            "a" * 64,
            "--execution-contract",
            str(tmp_path / "execution.json"),
            "--runtime-binding",
            str(tmp_path / "binding.json"),
            "--wire-config",
            str(tmp_path / "wire.json"),
            "--source-fanout-profile",
            "ready-shadow-heartbeat-estimator-v1",
            "--reference-module",
            str(tmp_path / "reference.py"),
            "--reference-sha256",
            "b" * 64,
            "--motion-profile",
            "supported-ready-v1",
            "--physics-trace-profile",
            "substep-ready-v1",
            "--native-estimate-profile",
            "offset-reset-v2",
            "--disarmed-odometry",
        ]
    )


def artifact_offset(tmp_path, offset=7_000_000):
    import hashlib
    import json

    from flydrones.benchmark.kalibr_camera_consumption import RAW_IMU_CONTRACT, KalibrCameraArtifact
    from tests.benchmark.test_managed_capture_source import calibration

    _, rig, _ = calibration(tmp_path)
    camera = json.loads((tmp_path / "camchain.yaml").read_bytes())
    camera["cam0"]["timeshift_cam_imu"] = offset / 1e9
    raw = json.dumps(camera).encode()
    (tmp_path / "camchain.yaml").write_bytes(raw)
    doc = json.loads((tmp_path / "artifact.json").read_bytes())
    doc["camchain"]["sha256"] = hashlib.sha256(raw).hexdigest()
    raw = json.dumps(doc).encode()
    (tmp_path / "artifact.json").write_bytes(raw)
    return KalibrCameraArtifact.load(
        tmp_path / "artifact.json", hashlib.sha256(raw).hexdigest(), rig, imu_contract=RAW_IMU_CONTRACT
    )


def test_actual_capture_factory_selects_v2_command_nonce_offset_and_worker_flags(tmp_path, monkeypatch):
    from tools.benchmark import managed_capture_source as managed
    from tools.benchmark import offset_reset_native_source as native
    from tools.benchmark.capture_contract import worker_options
    from tools.benchmark.capture_disarmed_sensors import make_capture_native_client

    artifact = artifact_offset(tmp_path)
    calls = []
    monkeypatch.setattr(managed, "load_managed_configuration", lambda *args, **kwargs: (artifact, ()))

    def init(self, command, output, *, source, **kwargs):
        calls.append((command, source))
        self.managed_source = source

    monkeypatch.setattr(native.OffsetResetNativeClient, "__init__", init)
    args = selected_args(tmp_path)
    client = make_capture_native_client(args, tmp_path, on_first_ack=None)
    assert type(client) is native.OffsetResetNativeClient
    assert len(calls[0][0]) == 6 and calls[0][0][-1] == "7000000"
    assert calls[0][0][-2] == client.managed_source.native_session and len(calls[0][0][-2]) == 64
    flags = worker_options(args)
    assert "--disarmed-odometry" in flags and flags[flags.index("--native-estimate-profile") + 1] == "offset-reset-v2"


@pytest.mark.parametrize("outcome", ["full", "short", "throw"])
def test_actual_observed_poll_sends_odometry_on_same_sequence_and_retains_return(monkeypatch, outcome):
    from tools.benchmark.disarmed_odometry_receiver import DisarmedOdometryReceiver
    from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock
    from tools.benchmark.openvins_observed_wire_session import ObservedWireSession
    from tools.benchmark.openvins_timesync_wire import PinnedCodec

    state = dict(
        sample_ns=120_000_000,
        reset_counter=0,
        reset_total=0,
        native_profile="offset-reset-v2",
        native_state13=[0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0, 0.0, 0.5],
        native_covariance12=np.eye(12).tolist(),
        native_session="a" * 64,
        native_pid=42,
        quality=None,
    )
    source = SimpleNamespace(wire_snapshot=lambda sim: state)
    observer = DisarmedOdometryReceiver(source)
    observer.request_ns = 100
    observer.response_ns = 101
    owner = object.__new__(ObservedWireSession)
    owner._estimate_receiver = observer
    owner._maintenance = object()
    owner._estimate_events = []
    codec = PinnedCodec()
    wire = SimpleNamespace(_codec=codec, _sequence=32, _peer=("127.0.0.1", 14588), _last_unarmed=100)
    owner._core = SimpleNamespace(_wire=wire, _owned=SimpleNamespace(check=lambda **kwargs: None))
    owner._remote = RemoteMonotonicClock("wire", sim_origin_ns=0, remote_origin_ns=1_000_000)
    owner._lane = SimpleNamespace(snapshot=lambda now: SimpleNamespace(observation=SimpleNamespace(sim_ns=120_000_000)))
    owner._operation = lambda action, commit: action()
    owner._context = lambda: None
    owner._clock = lambda: 102
    owner._forward = lambda *args: None
    sent = []

    def send(raw, peer, selected):
        sent.append((raw, peer, selected))
        if outcome == "throw":
            raise OSError("modeled socket failure")
        return len(raw) if outcome == "full" else 2

    owner._send_odometry = send
    if outcome == "full":
        owner.poll_estimate_receiver()
    else:
        with pytest.raises((ValueError, OSError)):
            owner.poll_estimate_receiver()
    assert len(sent) == 1 and wire._sequence == (32 if outcome == "throw" else 33)
    assert codec.decode_datagram(sent[0][0])[0]["type"] == "ODOMETRY"
    assert observer.send_events[-1]["bytes_returned"] == (
        None if outcome == "throw" else 2 if outcome == "short" else len(sent[0][0])
    )
    summary = observer.transport_summary()
    assert summary["odometry_full_returns"] == (outcome == "full")
    assert summary["odometry_short_returns"] == (outcome == "short")
    assert summary["odometry_without_return"] == (outcome == "throw")
    owner.poll_estimate_receiver()
    assert len(sent) == 1


def test_actual_v2_client_consumes_native_echo_offset_and_reset_from_real_fast_file(tmp_path, monkeypatch):
    import json
    import time

    from tools.benchmark import managed_capture_source as managed
    from tools.benchmark import openvins_online_shadow as shadow
    from tools.benchmark.capture_disarmed_sensors import make_capture_native_client

    artifact = artifact_offset(tmp_path)
    monkeypatch.setattr(managed, "load_managed_configuration", lambda *args, **kwargs: (artifact, ()))

    def init(self, command, output, **kwargs):
        self.process = SimpleNamespace(pid=42, poll=lambda: None)
        self.timeout_s, self.sequence, self.failed = 2.0, 0, None
        self.output = output
        self.echo = dict(
            native_profile="offset-reset-v2",
            native_pid=42,
            native_session=command[-2],
            camera_imu_offset_ns=int(command[-1]),
            reset_total=0,
            reset_counter=0,
            native_lifecycle_known=True,
        )
        (output / "fast.jsonl").write_bytes(b"")

    def send(self, action, pixels=None):
        ack = dict(
            sequence=self.sequence,
            sample_ns=action["sample_ns"],
            start_ns=105,
            end_ns=125,
            acknowledged_ns=time.monotonic_ns(),
            **self.echo,
        )
        self.sequence += 1
        if action["kind"] == "camera":
            ack.update(
                internal_initialized=True,
                public_initialized=True,
                state_time_s=0.012,
                imu_state=[0.0, 0.0, 0.0, 1.0, 10.0, 20.0, 30.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
        if action["sample_ns"] == 24_000_000:
            row = dict(
                target_ns=20_000_000,
                last_camera_ns=12_000_000,
                available_imu_ns=24_000_000,
                trigger_sequence=6,
                native_begin_ns=110,
                native_end_ns=120,
                filter_time_s=0.012,
                propagation_wall_s=0.0001,
                camera_imu_offset_s=0.007,
                internal_initialized=True,
                public_initialized=True,
                success=True,
                filter_unchanged=True,
                fusion_eligible=False,
                quality=None,
                state13=[0.0, 0.0, 0.0, 1.0, 11.0, 22.0, 33.0, 1.0, 2.0, 3.0, 0.0, 0.0, 0.5],
                covariance12=np.eye(12).tolist(),
                **self.echo,
            )
            with (self.output / "fast.jsonl").open("ab") as f:
                f.write((json.dumps(row) + "\n").encode())
        return ack

    monkeypatch.setattr(shadow.NativeClient, "__init__", init)
    monkeypatch.setattr(shadow.NativeClient, "send", send)
    monkeypatch.setattr(shadow.NativeClient, "finish", lambda self: dict(exit=0, failure=self.failed))
    client = make_capture_native_client(selected_args(tmp_path), tmp_path, on_first_ack=None)
    try:
        for ns in (4, 8, 12, 16, 20):
            client.send(dict(kind="imu", sample_ns=ns * 1_000_000))
        client.send(dict(kind="camera", sample_ns=12_000_000), b"pixels")
        client.send(dict(kind="imu", sample_ns=24_000_000))
        state = client.managed_source.wire_snapshot(20_000_000)
        assert state["reset_counter"] == 0 and state["native_state13"][4:7] == [11.0, 22.0, 33.0]
        client.managed_source.validate_wire_selection(state)
        client.echo["reset_total"] = 1
        with pytest.raises(ValueError, match="reset"):
            client.send(dict(kind="imu", sample_ns=28_000_000))
        with pytest.raises(ValueError, match="latched"):
            client.managed_source.wire_snapshot(28_000_000)
    finally:
        client.finish()


def boundary_fixture(fault=None):
    from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock
    from tools.benchmark.openvins_observed_wire_session import ObservedWireSession

    owner = object.__new__(ObservedWireSession)
    now = 3_000_000_000
    source = SimpleNamespace(validate_wire_selection=lambda state: None, _failure=None, lifecycle=SimpleNamespace(failure=None))
    owner._estimate_receiver = SimpleNamespace(source=source, response_ns=now)
    owner._estimate_sending_state = None
    owner._receiver = SimpleNamespace(check=lambda: None)
    owner._core = SimpleNamespace(_wire=SimpleNamespace(_last_unarmed=now))
    owner._open = lambda: None
    owner._backend = SimpleNamespace(clock=lambda: now)
    owner._remote = RemoteMonotonicClock("wire", sim_origin_ns=0, remote_origin_ns=1_000_000)
    owner._signature = ("wire", 0, 1_000_000)
    owner._lane = SimpleNamespace(
        session_id="wire", progress=dict(session_id="wire", failure=None, latest_callback_ns=now, pending_callback_ns=None)
    )
    owner._complete = owner._transitioning = owner._closed = owner._closing = False
    owner._failure = owner._selection = None
    owner._maintenance = object()
    owner._last_now = now
    owner._start = 0
    owner._deadline = 300_000_000_000
    owner._flags = 64
    sent = []
    owner._sock = SimpleNamespace(sendto=lambda *args: sent.append(args))
    state = dict(receipt_ns=now)
    if fault == "heartbeat":
        owner._core._wire._last_unarmed = now - 2_000_000_000
    if fault == "ev":
        owner._estimate_receiver.response_ns = now - 2_000_000_000
    if fault == "receipt":
        state["receipt_ns"] = now - 100_000_001
    if fault == "source":
        source._failure = "native reset"
    return owner, state, sent


@pytest.mark.parametrize("fault", ["heartbeat", "ev", "receipt", "source"])
def test_actual_send_boundary_stops_stale_or_failed_odometry_before_socket(fault):
    owner, state, sent = boundary_fixture(fault)
    with pytest.raises(ValueError):
        owner._send_odometry(b"packet", ("127.0.0.1", 14588), state)
    assert sent == []


@pytest.mark.parametrize("offset", [7_000_000, -7_000_000])
def test_actual_calibration_configuration_and_execution_contract_consume_nonzero_offset(tmp_path, offset):
    import hashlib
    import json

    from tests.benchmark.test_managed_capture_source import configuration
    from tools.benchmark.capture_contract import execution_contract
    from tools.benchmark.managed_capture_source import load_managed_configuration

    doc, _ = configuration(tmp_path)
    camera = json.loads((tmp_path / "camchain.yaml").read_bytes())
    camera["cam0"]["timeshift_cam_imu"] = offset / 1e9
    raw = json.dumps(camera).encode()
    (tmp_path / "camchain.yaml").write_bytes(raw)
    artifact = json.loads((tmp_path / "artifact.json").read_bytes())
    artifact["camchain"]["sha256"] = hashlib.sha256(raw).hexdigest()
    raw = json.dumps(artifact).encode()
    (tmp_path / "artifact.json").write_bytes(raw)
    doc["calibration"]["sha256"] = hashlib.sha256(raw).hexdigest()
    native = json.loads((tmp_path / "camera.yaml").read_bytes())
    native["cam0"]["timeshift_cam_imu"] = offset / 1e9
    raw = json.dumps(native).encode()
    (tmp_path / "camera.yaml").write_bytes(raw)
    next(row for row in doc["native_files"] if row["path"] == "camera.yaml")["sha256"] = hashlib.sha256(raw).hexdigest()
    raw = json.dumps(doc).encode()
    (tmp_path / "managed.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    loaded, files = load_managed_configuration(
        tmp_path / "managed.json", digest, tmp_path / "estimator_config.yaml", native_profile="offset-reset-v2"
    )
    assert loaded.timeshift_ns == offset and len(files) == 10
    with pytest.raises(ValueError, match="nonzero"):
        load_managed_configuration(tmp_path / "managed.json", digest, tmp_path / "estimator_config.yaml")
    (tmp_path / "wire.json").write_text(
        json.dumps(dict(schema="capture-wire-v1", session_id="wire", sim_origin_ns=0, remote_origin_ns=1_000_000)),
        encoding="utf-8",
    )
    args = selected_args(tmp_path)
    args.managed_source_sha256 = digest
    actual = execution_contract(args)
    assert actual["native_estimate_profile"]["disarmed_odometry"] is True
    assert actual["managed_source"]["calibration"]["timeshift_ns"] == offset


def test_existing_readiness_consumes_v2_native_camera_fields_without_faking_old_null_reset():
    from tests.benchmark.test_estimator_aware_readiness import ack
    from tools.benchmark.estimator_aware_readiness import _validate_camera_ack

    row = ack(public=True)
    row.update(
        native_profile="offset-reset-v2",
        native_pid=42,
        native_session="a" * 64,
        camera_imu_offset_ns=7_000_000,
        reset_total=0,
        reset_counter=0,
        native_lifecycle_known=True,
    )
    assert _validate_camera_ack(row, row["acknowledged_ns"])[:2] == (row["sequence"], row["sample_ns"])
    assert row["reset_counter"] == 0
    row["reset_total"] = 1
    with pytest.raises(ValueError, match="lifecycle"):
        _validate_camera_ack(row, row["acknowledged_ns"])


@pytest.mark.parametrize("exit_during", ["receiver", "lane"])
def test_review_native_exit_during_final_callbacks_refuses_send(exit_during):
    from tools.benchmark.offset_reset_native_source import NativeLifecycleBinding

    owner, state, sent = boundary_fixture()
    process = SimpleNamespace(pid=42, poll=lambda: None)
    lifecycle = NativeLifecycleBinding(process, "a" * 64, 7_000_000)
    row = dict(
        native_profile="offset-reset-v2",
        native_pid=42,
        native_session="a" * 64,
        camera_imu_offset_ns=7_000_000,
        reset_total=0,
        reset_counter=0,
        native_lifecycle_known=True,
    )
    source = owner._estimate_receiver.source
    source.lifecycle = lifecycle
    source.validate_wire_selection = lambda selected: lifecycle.accept(row)

    def exit_child():
        process.poll = lambda: 2

    if exit_during == "receiver":
        owner._receiver.check = exit_child
    else:
        original = owner._lane

        class Lane:
            session_id = original.session_id

            @property
            def progress(self):
                exit_child()
                return original.progress

        owner._lane = Lane()
    with pytest.raises(ValueError, match="native"):
        owner._send_odometry(b"packet", ("127.0.0.1", 14588), state)
    assert sent == [] and lifecycle.failure


@pytest.mark.parametrize("cleanup_raises", [False, True])
def test_review_actual_capture_setup_registers_cleanup_before_causal_failure(tmp_path, monkeypatch, cleanup_raises):
    import ast
    import inspect

    from tools.benchmark import capture_disarmed_sensors as capture
    from tools.benchmark import offset_reset_native_source as native
    from tools.benchmark.disarmed_sensor_provenance import CaptureJournal

    # Execute the actual ordinary-client setup statements from main, with only
    # its surrounding runtime supplied. This avoids invoking native main/gates.
    tree = ast.parse(inspect.getsource(capture.main))
    branch = next(
        node.orelse
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and any(
            isinstance(part, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "client" for t in part.targets)
            and isinstance(part.value, ast.Call)
            and isinstance(part.value.func, ast.Name)
            and part.value.func.id == "create_client"
            for part in node.orelse
        )
    )
    code = compile(ast.Module(body=branch, type_ignores=[]), capture.__file__, "exec")
    finished = []
    client = SimpleNamespace(
        process=SimpleNamespace(pid=42), managed_source=SimpleNamespace(bind_capture_session=lambda value: None)
    )

    def finish(value):
        finished.append(value)
        if cleanup_raises:
            raise RuntimeError("secondary cleanup failure")
        return dict(exit=0)

    def refuse(*args):
        raise ValueError("primary causal setup failure")

    monkeypatch.setattr(native, "install_offset_causal", refuse)
    result = dict(errors=[], status="starting")
    with CaptureJournal(tmp_path, result) as journal:
        scope = dict(
            args=SimpleNamespace(managed_source_config=True, health_profile=None, native_estimate_profile="offset-reset-v2"),
            create_client=lambda *args: client,
            ShadowInput=lambda *args, **kwargs: object(),
            journal=journal,
            result=result,
            finish_client=finish,
            shadow_dir=tmp_path,
            health=None,
        )
        exec(code, scope)
    assert finished == [client]
    assert "primary causal setup failure" in result["errors"][0]
    assert any("secondary cleanup failure" in value for value in result["errors"]) == cleanup_raises


def test_review_transport_summary_is_actual_returns_not_receipt():
    from tools.benchmark.disarmed_odometry_receiver import DisarmedOdometryReceiver

    receiver = DisarmedOdometryReceiver(None)
    receiver.response_ns = 100
    assert receiver.check(101, disarmed=True)["native_lifecycle_policy"] == "fresh-monitored-generation-or-terminal-refusal"
    assert receiver.transport_summary()["odometry_sent"] is False
    for count in (4, 2, None):
        receiver.send_events.append(dict(kind="odometry", raw_hex="01020304", bytes_returned=count))
    summary = receiver.transport_summary()
    assert summary["odometry_attempts"] == 3
    assert summary["odometry_full_returns"] == 1 and summary["odometry_short_returns"] == 1
    assert summary["odometry_without_return"] == 1 and summary["odometry_sent"] is True
    assert summary["px4_receipt_verified"] is False and summary["fusion_verified"] is False


def test_review_v2_required_source_recipe_is_prospective_only():
    import ast
    import inspect
    from pathlib import Path

    from tools.benchmark import capture_disarmed_sensors as capture

    tree = ast.parse(inspect.getsource(capture.main))
    branch = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and "offset-reset-v2" in ast.unparse(node.test)
        and any(isinstance(part, ast.Expr) and "required.extend" in ast.unparse(part) for part in node.body)
    )
    for selected in (None, "offset-reset-v2"):
        required = []
        exec(
            compile(ast.Module(body=[branch], type_ignores=[]), capture.__file__, "exec"),
            dict(args=SimpleNamespace(native_estimate_profile=selected), ROOT=capture.ROOT, required=required),
        )
        recipe = capture.ROOT / "tools/benchmark/native_offset_reset_v2/CMakeLists.txt"
        assert (recipe in required) == (selected is not None)
        assert all(isinstance(value, Path) for value in required)


def test_review_public_session_evidence_uses_retained_transport_summary():
    from tools.benchmark.disarmed_odometry_receiver import DisarmedOdometryReceiver
    from tools.benchmark.openvins_observed_wire_session import ObservedWireSession

    class EvidenceSession(ObservedWireSession):
        @property
        def progress(self):
            return dict(fusion_qualified=False)

    owner = object.__new__(EvidenceSession)
    owner._selections = []
    owner._restoration = owner._restoration_init_error = owner._retention = owner._receiver = owner._core = None
    owner._signature = ()
    owner._lane = SimpleNamespace(evidence={})
    owner._cleanup_errors = []
    owner._estimate_events = []
    owner._refusal_journal_error = None
    receiver = owner._estimate_receiver = DisarmedOdometryReceiver(None)
    for count in (None, 2, 4):
        receiver.send_events.append(dict(kind="odometry", raw_hex="01020304", bytes_returned=count))
        evidence = owner.evidence["estimate_receiver"]
        assert evidence["odometry_sent"] == (count == 4)
        assert evidence["fusion_verified"] is False and evidence["px4_receipt_verified"] is False
