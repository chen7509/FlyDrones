"""Production calibration/source consumption with synthetic measurement artifacts."""

import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def inert(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("native process/network forbidden")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(os, "system", forbidden)


def write(path, value):
    data = json.dumps(value).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def calibration(tmp_path):
    from flydrones.benchmark.kalibr_camera_consumption import RAW_IMU_CONTRACT, KalibrCameraArtifact
    from flydrones.benchmark.px4_camera_source import CameraRigBinding

    rig = CameraRigBinding(
        "a" * 64,
        "body",
        "camera",
        "simulation-candidate",
        160,
        120,
        (100.0, 0.0, 80.0, 0.0, 100.0, 60.0, 0.0, 0.0, 1.0),
        ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        (0.0, 0.0, 0.0),
        (),
    )
    transform = [[0.0, -1.0, 0.0, 1.0], [1.0, 0.0, 0.0, 2.0], [0.0, 0.0, 1.0, 3.0], [0.0, 0.0, 0.0, 1.0]]
    chain = {
        "cam0": dict(
            camera_model="pinhole",
            distortion_model="radtan",
            resolution=[160, 120],
            intrinsics=[100.0, 100.0, 80.0, 60.0],
            distortion_coeffs=[0.0, 0.0, 0.0, 0.0],
            T_cam_imu=transform,
            timeshift_cam_imu=0.0,
        )
    }
    ch = write(tmp_path / "camchain.yaml", chain)
    (tmp_path / "result.txt").write_bytes(b"synthetic, not measured")
    doc = dict(
        schema="flydrones-kalibr-artifact-binding-v1",
        rig_sha256=rig.sha256,
        body_id="body",
        camera_id="camera",
        imu_contract=RAW_IMU_CONTRACT,
        camera_key="cam0",
        camchain=dict(path="camchain.yaml", sha256=ch),
        results=dict(path="result.txt", sha256=hashlib.sha256(b"synthetic, not measured").hexdigest()),
    )
    digest = write(tmp_path / "artifact.json", doc)
    artifact = KalibrCameraArtifact.load(tmp_path / "artifact.json", digest, rig, imu_contract=RAW_IMU_CONTRACT)
    return artifact, rig, digest


def test_raw_imu_artifact_is_explicit_and_cannot_cross_px4_consumer(tmp_path):
    from flydrones.benchmark.kalibr_camera_consumption import KalibrCameraArtifact

    artifact, rig, digest = calibration(tmp_path)
    with pytest.raises(ValueError, match="contract"):
        KalibrCameraArtifact.load(tmp_path / "artifact.json", digest, rig)
    assert artifact.record()["camera_calibration_qualified"] is False


def test_actual_managed_pose_uses_artifact_inverse_and_native_body_velocity(tmp_path):
    from tools.benchmark.managed_capture_source import ManagedCaptureSource

    artifact, rig, digest = calibration(tmp_path)
    clock = [1_000_000_000]
    process = SimpleNamespace(pid=421, poll=lambda: None)
    source = ManagedCaptureSource(artifact, now=lambda: clock[0])
    source.attach_native(process)
    camera = dict(
        sample_ns=100_000_000,
        acknowledged_ns=clock[0],
        state_time_s=0.1,
        internal_initialized=True,
        public_initialized=True,
        imu_state=[0.0, 0.0, 0.0, 1.0, 10.0, 20.0, 30.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        reset_counter=None,
        fusion_eligible=False,
        quality=None,
    )
    source.accept_camera(camera, process)
    fast = dict(
        target_ns=120_000_000,
        success=True,
        public_initialized=True,
        internal_initialized=True,
        last_camera_ns=100_000_000,
        camera_imu_offset_s=0.0,
        reset_counter=None,
        state13=[0.0, 0.0, 0.0, 1.0, 11.0, 22.0, 33.0, 1.0, 2.0, 3.0, 0.0, 0.0, 0.5],
    )
    source.accept_fast(fast, dict(acknowledged_ns=clock[0]), process)
    view = source.diagnostic_snapshot(120_000_000, 100_000_000)
    # T_cam_imu inverse translation is (-2,+1,-3), independently derived.
    assert view["camera_pose"][:3] == pytest.approx([8.0, 21.0, 27.0])
    assert view["position"] == pytest.approx([11.0, 22.0, 33.0])
    assert view["velocity"] == pytest.approx([1.0, 2.0, 3.0])
    assert view["yaw_rate"] == pytest.approx(0.5)
    assert view["reset_counter"] is None
    with pytest.raises(RuntimeError, match="qualified"):
        source.require_ready(120_000_000)


def test_native_process_change_latches_source_and_blocks_following_updates(tmp_path):
    from tools.benchmark.managed_capture_source import ManagedCaptureSource

    artifact, rig, digest = calibration(tmp_path)
    p = SimpleNamespace(pid=421, poll=lambda: None)
    source = ManagedCaptureSource(artifact, now=lambda: 1_000_000_000)
    source.attach_native(p)
    p.pid = 422
    with pytest.raises(ValueError, match="process"):
        source.accept_camera({}, p)
    p.pid = 421
    with pytest.raises(ValueError, match="latched"):
        source.accept_camera({}, p)


def test_cli_rejects_managed_source_without_sole_wire_owner(tmp_path):
    from tools.benchmark.capture_disarmed_sensors import parse_capture_args

    argv = [
        "--output",
        str(tmp_path),
        "--online-estimate-feed",
        "--shadow-binary",
        "native",
        "--shadow-config",
        "estimator_config.yaml",
        "--execution-contract",
        "execution.json",
        "--runtime-binding",
        "binding.json",
        "--managed-source-config",
        "managed.json",
        "--managed-source-sha256",
        "a" * 64,
    ]
    with pytest.raises(SystemExit):
        parse_capture_args(argv)
    args = parse_capture_args(
        argv
        + [
            "--wire-config",
            "wire.json",
            "--source-fanout-profile",
            "ready-shadow-heartbeat-estimator-v1",
            "--reference-module",
            "reference.py",
            "--reference-sha256",
            "a" * 64,
            "--motion-profile",
            "supported-ready-v1",
            "--physics-trace-profile",
            "substep-ready-v1",
        ]
    )
    from tools.benchmark.capture_contract import worker_options

    options = worker_options(args)
    assert options[options.index("--managed-source-sha256") + 1] == "a" * 64
    assert Path(options[options.index("--managed-source-config") + 1]).name == "managed.json"


def test_factory_uses_managed_client_and_concrete_owner(tmp_path, monkeypatch):
    from tools.benchmark import managed_capture_source as managed
    from tools.benchmark.capture_disarmed_sensors import make_capture_native_client

    artifact, _, _ = calibration(tmp_path)
    monkeypatch.setattr(managed, "load_managed_configuration", lambda *args: (artifact, ()))
    captured = {}

    def construct(self, command, output, *, source, **kwargs):
        captured.update(command=command, source=source)
        self.managed_source = source

    monkeypatch.setattr(managed.ManagedEstimateNativeClient, "__init__", construct)
    args = SimpleNamespace(
        online_estimate_feed=True,
        managed_source_config=tmp_path / "managed.json",
        managed_source_sha256="a" * 64,
        shadow_binary=tmp_path / "native",
        shadow_config=tmp_path / "config.yaml",
    )
    client = make_capture_native_client(args, tmp_path, on_first_ack=None)
    assert type(client) is managed.ManagedEstimateNativeClient
    assert type(captured["source"]) is managed.ManagedCaptureSource


def test_managed_client_does_not_publish_parent_deadline_failure(tmp_path, monkeypatch):
    from tools.benchmark.capture_online_estimates import LiveEstimateNativeClient
    from tools.benchmark.managed_capture_source import ManagedCaptureSource, ManagedEstimateNativeClient

    artifact, _, _ = calibration(tmp_path)
    source = ManagedCaptureSource(artifact)
    client = object.__new__(ManagedEstimateNativeClient)
    client.timeout_s = 2.0
    client.managed_source = source
    client._pending_events = None
    client._feed_failure = client.failed = None

    def failed(self, action, pixels=None):
        self._pending_events.append(("camera_state", {"ack": {}}))
        raise TimeoutError("parent deadline")

    monkeypatch.setattr(LiveEstimateNativeClient, "send", failed)
    with pytest.raises(TimeoutError, match="parent deadline"):
        client.send({})
    assert source._last_camera == -1
    assert client.failed


def configuration(tmp_path):
    artifact, rig, _ = calibration(tmp_path)

    def ref(name, value):
        digest = write(tmp_path / name, value)
        return dict(path=name, sha256=digest)

    intrinsic = ref(
        "intrinsic.json",
        dict(
            schema="flydrones-camera-info-v1",
            camera_info=dict(frame_id="camera", width=160, height=120, intrinsics_k=list(rig.intrinsics_k)),
        ),
    )
    extrinsic = ref(
        "extrinsic.json",
        dict(
            schema="flydrones-body-frd-from-camera-optical-v1",
            body_id="body",
            camera_id="camera",
            rotation=[list(r) for r in rig.body_from_optical],
            translation_m=[0.0, 0.0, 0.0],
        ),
    )
    rig_ref = ref(
        "rig.json",
        dict(
            schema="flydrones-px4-camera-rig-v1",
            body_id="body",
            camera_id="camera",
            domain="simulation-candidate",
            intrinsics=intrinsic,
            extrinsics=extrinsic,
        ),
    )
    # Rebind the synthetic Kalibr artifact to the actual fixture rig byte identity.
    doc = json.loads((tmp_path / "artifact.json").read_bytes())
    doc["rig_sha256"] = rig_ref["sha256"]
    artifact_ref = ref("artifact.json", doc)
    mount, translation = artifact.body_from_camera()
    inverse = np.eye(4)
    inverse[:3, :3], inverse[:3, 3] = mount, translation
    camera = dict(
        camera_model="pinhole",
        distortion_model="radtan",
        resolution=[160, 120],
        intrinsics=list(artifact.intrinsics),
        distortion_coeffs=list(artifact.distortion),
        T_imu_cam=inverse.tolist(),
        timeshift_cam_imu=0.0,
    )
    files = [
        ref(
            "estimator_config.yaml",
            dict(
                max_cameras=1,
                downsample_cameras=False,
                calib_cam_extrinsics=False,
                calib_cam_intrinsics=False,
                calib_cam_timeoffset=False,
                init_dyn_mle_opt_calib=False,
                relative_config_imucam="camera.yaml",
                relative_config_imu="imu.yaml",
            ),
        ),
        ref("camera.yaml", dict(cam0=camera)),
        ref("imu.yaml", dict(imu0={"synthetic": True})),
    ]
    managed = dict(
        schema="managed-capture-source-v1",
        body_id="body",
        camera_id="camera",
        rig=rig_ref,
        calibration=artifact_ref,
        native_files=files,
    )
    digest = write(tmp_path / "managed.json", managed)
    return managed, digest


def test_configuration_consumes_actual_native_inverse_and_all_bound_files(tmp_path):
    from tools.benchmark.managed_capture_source import configuration_record, load_managed_configuration

    doc, digest = configuration(tmp_path)
    artifact, inputs = load_managed_configuration(tmp_path / "managed.json", digest, tmp_path / "estimator_config.yaml")
    assert len(inputs) == 10
    assert artifact.imu_contract.endswith("sample-v1")
    assert (
        configuration_record(tmp_path / "managed.json", digest, tmp_path / "estimator_config.yaml")["controller_ready"] is False
    )
    (tmp_path / "camera.yaml").write_bytes(b"wrong native calibration")
    with pytest.raises(ValueError, match="SHA"):
        load_managed_configuration(tmp_path / "managed.json", digest, tmp_path / "estimator_config.yaml")


@pytest.mark.parametrize("fault", ["extrinsic", "offset", "learned"])
def test_native_consumer_refuses_coherently_pinned_mismatch_before_child(tmp_path, fault):
    from tools.benchmark.managed_capture_source import load_managed_configuration

    doc, digest = configuration(tmp_path)
    name = "estimator_config.yaml" if fault == "learned" else "camera.yaml"
    value = json.loads((tmp_path / name).read_bytes())
    if fault == "learned":
        value["calib_cam_timeoffset"] = True
    elif fault == "offset":
        value["cam0"]["timeshift_cam_imu"] = 0.01
    else:
        value["cam0"]["T_imu_cam"][0][3] += 1.0
    sha = write(tmp_path / name, value)
    next(ref for ref in doc["native_files"] if ref["path"] == name)["sha256"] = sha
    digest = write(tmp_path / "managed.json", doc)
    with pytest.raises(ValueError, match="native"):
        load_managed_configuration(tmp_path / "managed.json", digest, tmp_path / "estimator_config.yaml")


def test_actual_capture_client_consumes_camera_and_fast_file_after_ack(tmp_path, monkeypatch):
    import time

    from tools.benchmark import managed_capture_source as managed
    from tools.benchmark import openvins_online_shadow as shadow
    from tools.benchmark.capture_disarmed_sensors import make_capture_native_client

    artifact, _, _ = calibration(tmp_path)
    monkeypatch.setattr(managed, "load_managed_configuration", lambda *args: (artifact, ()))

    def init(self, command, output, **kwargs):
        self.process = SimpleNamespace(pid=421, poll=lambda: None)
        self.timeout_s, self.sequence, self.failed = 2.0, 0, None
        self.output = output
        (output / "fast.jsonl").write_bytes(b"")

    def send(self, action, pixels=None):
        ack = dict(
            sequence=self.sequence, sample_ns=action["sample_ns"], start_ns=105, end_ns=125, acknowledged_ns=time.monotonic_ns()
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
                camera_imu_offset_s=0.0,
                internal_initialized=True,
                public_initialized=True,
                success=True,
                filter_unchanged=True,
                fusion_eligible=False,
                reset_counter=None,
                quality=None,
                state13=[0.0, 0.0, 0.0, 1.0, 11.0, 22.0, 33.0, 1.0, 2.0, 3.0, 0.0, 0.0, 0.5],
                covariance12=np.eye(12).tolist(),
            )
            with (self.output / "fast.jsonl").open("ab") as f:
                f.write((json.dumps(row) + "\n").encode())
        return ack

    monkeypatch.setattr(shadow.NativeClient, "__init__", init)
    monkeypatch.setattr(shadow.NativeClient, "send", send)
    monkeypatch.setattr(shadow.NativeClient, "finish", lambda self: dict(exit=0, failure=None))
    args = SimpleNamespace(
        online_estimate_feed=True,
        managed_source_config=tmp_path / "config.json",
        managed_source_sha256="a" * 64,
        shadow_binary=tmp_path / "native",
        shadow_config=tmp_path / "native.yaml",
    )
    client = make_capture_native_client(args, tmp_path, on_first_ack=None)
    try:
        for ns in (4, 8, 12, 16):
            client.send(dict(kind="imu", sample_ns=ns * 1_000_000))
        client.send(dict(kind="camera", sample_ns=12_000_000), b"pixels")
        for ns in (20, 24):
            client.send(dict(kind="imu", sample_ns=ns * 1_000_000))
        value = client.managed_source.diagnostic_snapshot(20_000_000, 12_000_000)
        assert value["camera_pose"][:3] == pytest.approx([8.0, 21.0, 27.0])
        assert value["position"] == [11.0, 22.0, 33.0]
        assert value["controller_ready"] is False
    finally:
        client.finish()


def test_managed_admission_rejects_post_parent_deadline_overrun(monkeypatch):
    from tools.benchmark import managed_capture_source as managed
    from tools.benchmark.capture_online_estimates import LiveEstimateNativeClient

    clock = [0]
    failures = []

    def consume(*args, **kwargs):
        clock[0] = 2_010_000_000

    source = SimpleNamespace(accept_camera=consume, latch_failure=failures.append)
    client = object.__new__(managed.ManagedEstimateNativeClient)
    client.managed_source, client.process, client.timeout_s = source, object(), 2.0
    client._feed_failure = client.failed = None

    def inherited(self, action, pixels=None):
        clock[0] = 1_980_000_000
        self._pending_events.append(("camera_state", {"ack": {}}))
        return {}

    monkeypatch.setattr(LiveEstimateNativeClient, "send", inherited)
    monkeypatch.setattr(managed.time, "monotonic_ns", lambda: clock[0])
    with pytest.raises(TimeoutError, match="managed.*deadline"):
        client.send({})
    assert client.failed and failures


def test_latest_snapshot_keeps_camera_and_fast_atomic_across_writer_interleave(tmp_path):
    from tools.benchmark.managed_capture_source import ManagedCaptureSource

    artifact, _, _ = calibration(tmp_path)
    process = SimpleNamespace(pid=421, poll=lambda: None)
    source = ManagedCaptureSource(artifact, now=lambda: 1_000_000_000)
    source.attach_native(process)

    def camera(stamp):
        return dict(
            sample_ns=stamp,
            acknowledged_ns=1_000_000_000,
            state_time_s=stamp / 1e9,
            internal_initialized=True,
            public_initialized=True,
            imu_state=[0.0, 0.0, 0.0, 1.0, 10.0, 20.0, 30.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )

    def fast(stamp, image):
        return dict(
            target_ns=stamp,
            last_camera_ns=image,
            camera_imu_offset_s=0.0,
            success=True,
            internal_initialized=True,
            public_initialized=True,
            reset_counter=None,
            state13=[0.0, 0.0, 0.0, 1.0, 11.0, 22.0, 33.0, 1.0, 2.0, 3.0, 0.0, 0.0, 0.5],
        )

    source.accept_camera(camera(100_000_000), process)
    source.accept_fast(fast(120_000_000, 100_000_000), dict(acknowledged_ns=1_000_000_000), process)
    lock = source._lock

    class Interleave:
        once = True

        def acquire(self, *args, **kwargs):
            return lock.acquire(*args, **kwargs)

        def release(self):
            lock.release()
            if self.once:
                self.once = False
                source.accept_camera(camera(120_000_000), process)
                source.accept_fast(fast(140_000_000, 120_000_000), dict(acknowledged_ns=1_000_000_000), process)

    source._lock = Interleave()
    value = source.latest_diagnostic(140_000_000)
    assert value["last_camera_ns"] == value["camera_ns"]
    assert (value["sample_ns"], value["camera_ns"]) in ((120_000_000, 100_000_000), (140_000_000, 120_000_000))
    assert source._failure is None


def test_source_deadline_latches_before_unlock_exposes_derived_state(tmp_path, monkeypatch):
    from tools.benchmark import managed_capture_source as managed

    artifact, _, _ = calibration(tmp_path)
    source = managed.ManagedCaptureSource(artifact, now=lambda: 1_000_000_000)
    process = SimpleNamespace(pid=421, poll=lambda: None)
    source.attach_native(process)
    clock = [0]
    original = source._state

    def slow_state(value, size):
        result = original(value, size)
        clock[0] = 110
        return result

    monkeypatch.setattr(source, "_state", slow_state)
    monkeypatch.setattr(managed.time, "monotonic_ns", lambda: clock[0])
    ack = dict(
        sample_ns=100_000_000,
        acknowledged_ns=1_000_000_000,
        state_time_s=0.1,
        internal_initialized=True,
        public_initialized=True,
        imu_state=[0.0, 0.0, 0.0, 1.0, 10.0, 20.0, 30.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    )
    with pytest.raises(TimeoutError, match="deadline"):
        source.accept_camera(ack, process, deadline_ns=100)
    with pytest.raises(ValueError, match="latched"):
        source.latest_diagnostic(100_000_000)


def test_native_body_velocity_and_camera_mount_rotate_in_estimator_frame(tmp_path):
    from tools.benchmark.managed_capture_source import ManagedCaptureSource

    artifact, _, _ = calibration(tmp_path)
    source = ManagedCaptureSource(artifact, now=lambda: 1_000_000_000)
    process = SimpleNamespace(pid=421, poll=lambda: None)
    source.attach_native(process)
    q = [0.0, 0.0, 2**-0.5, 2**-0.5]
    source.accept_camera(
        dict(
            sample_ns=100_000_000,
            acknowledged_ns=1_000_000_000,
            state_time_s=0.1,
            internal_initialized=True,
            public_initialized=True,
            imu_state=q + [10.0, 20.0, 30.0] + [0.0] * 9,
        ),
        process,
    )
    source.accept_fast(
        dict(
            target_ns=120_000_000,
            last_camera_ns=100_000_000,
            camera_imu_offset_s=0.0,
            internal_initialized=True,
            public_initialized=True,
            success=True,
            reset_counter=None,
            state13=q + [11.0, 22.0, 33.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.5],
        ),
        dict(acknowledged_ns=1_000_000_000),
        process,
    )
    state = source.latest_diagnostic(120_000_000)
    assert state["velocity"] == pytest.approx([0.0, 1.0, 0.0], abs=1e-12)
    assert state["camera_pose"][:3] == pytest.approx([9.0, 18.0, 27.0])
    assert state["camera_pose"][3:] == pytest.approx([0.0, 0.0, 0.0, 1.0], abs=1e-12)
