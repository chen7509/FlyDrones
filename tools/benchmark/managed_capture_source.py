"""Calibration consumption in the owned capture client; no fusion authority."""

from __future__ import annotations

import json
import math
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from threading import Lock

import numpy as np
import yaml
from scipy.spatial.transform import Rotation

from flydrones.benchmark.kalibr_camera_consumption import (
    RAW_IMU_CONTRACT,
    KalibrCameraArtifact,
    references,
)
from flydrones.benchmark.px4_camera_source import MAX_DOCUMENT, CameraRigBinding, _bound_bytes, _unique
from tools.benchmark.capture_online_estimates import LiveEstimateNativeClient, _secondary


def _yaml(raw):
    # Native OpenCV files use this nonstandard directive; parse only its body.
    if raw.startswith(b"%YAML:1.0"):
        raw = raw.split(b"\n", 1)[1]

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        lambda loader, node: _unique([(loader.construct_object(k), loader.construct_object(v)) for k, v in node.value]),
    )
    if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(raw)):
        raise ValueError("native configuration aliases forbidden")
    result = yaml.load(raw, Loader=Loader)
    if type(result) is not dict:
        raise ValueError("native configuration mapping required")
    return result


def load_managed_configuration(path, digest, native_config, *, _records=None):
    """Bind all selected files before Popen; loaded values are not measurements."""
    path = Path(path)
    doc = json.loads(_bound_bytes(path, digest, MAX_DOCUMENT), object_pairs_hook=_unique)
    if (
        type(doc) is not dict
        or set(doc) != {"schema", "body_id", "camera_id", "rig", "calibration", "native_files"}
        or doc["schema"] != "managed-capture-source-v1"
    ):
        raise ValueError("invalid managed source configuration")
    selected = [path.resolve(strict=True)]
    expected = {selected[0]: digest}

    def bound(ref):
        if type(ref) is not dict or set(ref) != {"path", "sha256"}:
            raise ValueError("exact managed file reference required")
        name = ref["path"]
        if (
            type(name) is not str
            or not name
            or "\\" in name
            or ":" in name
            or PurePosixPath(name).is_absolute()
            or any(p in ("", ".", "..") for p in name.split("/"))
        ):
            raise ValueError("managed reference escapes configuration")
        file = path.parent / name
        raw = _bound_bytes(file, ref["sha256"], MAX_DOCUMENT)
        selected.append(file.resolve(strict=True))
        expected[selected[-1]] = ref["sha256"]
        return file, raw

    rig_path, _ = bound(doc["rig"])
    rig = CameraRigBinding.load(rig_path, doc["rig"]["sha256"], body_id=doc["body_id"], camera_id=doc["camera_id"])
    rig_doc = json.loads(_bound_bytes(rig_path, doc["rig"]["sha256"], MAX_DOCUMENT), object_pairs_hook=_unique)
    selected.extend((rig_path.parent / rig_doc[role]["path"]).resolve(strict=True) for role in ("intrinsics", "extrinsics"))
    expected.update(
        {
            (rig_path.parent / rig_doc[role]["path"]).resolve(strict=True): rig_doc[role]["sha256"]
            for role in ("intrinsics", "extrinsics")
        }
    )
    artifact_path, _ = bound(doc["calibration"])
    artifact = KalibrCameraArtifact.load(artifact_path, doc["calibration"]["sha256"], rig, imu_contract=RAW_IMU_CONTRACT)
    _, artifact_doc, _ = references(artifact_path, doc["calibration"]["sha256"])
    selected.extend((artifact_path.parent / artifact_doc[role]["path"]).resolve(strict=True) for role in ("camchain", "results"))
    expected.update(
        {
            (artifact_path.parent / artifact_doc[role]["path"]).resolve(strict=True): artifact_doc[role]["sha256"]
            for role in ("camchain", "results")
        }
    )
    files = doc["native_files"]
    if type(files) is not list or len(files) != 3:
        raise ValueError("three frozen native configuration files required")
    native = {}
    for ref in files:
        file, raw = bound(ref)
        if file.name in native:
            raise ValueError("duplicate native configuration file")
        native[file.name] = (file.resolve(strict=True), _yaml(raw))
    root = Path(native_config).resolve(strict=True)
    if root.name not in native or native[root.name][0] != root:
        raise ValueError("actual native config differs from selected calibration consumer")
    config = native[root.name][1]
    if (
        type(config.get("max_cameras")) is not int
        or config["max_cameras"] != 1
        or config.get("downsample_cameras") is not False
        or any(
            config.get(key) is not False
            for key in ("calib_cam_extrinsics", "calib_cam_intrinsics", "calib_cam_timeoffset", "init_dyn_mle_opt_calib")
        )
    ):
        raise ValueError("native calibration must remain fixed")
    linked = []
    for key in ("relative_config_imucam", "relative_config_imu"):
        name = config.get(key)
        if type(name) is not str or name != Path(name).name or name not in native or native[name][0].parent != root.parent:
            raise ValueError("native relative calibration reference mismatch")
        linked.append(name)
    if len(set([root.name, *linked])) != 3:
        raise ValueError("distinct native configuration closure required")
    camera = native[linked[0]][1].get("cam0", {})
    rotation, translation = artifact.body_from_camera()
    inverse = np.eye(4)
    inverse[:3, :3], inverse[:3, 3] = rotation, translation

    def equals(value, expected):
        try:
            observed = np.asarray(value, dtype=float)
            return observed.shape == np.shape(expected) and np.array_equal(observed, expected)
        except (ValueError, TypeError):
            return False

    if (
        camera.get("camera_model") != "pinhole"
        or camera.get("distortion_model") != "radtan"
        or not equals(camera.get("resolution"), [rig.width, rig.height])
        or not equals(camera.get("intrinsics"), artifact.intrinsics)
        or not equals(camera.get("distortion_coeffs"), artifact.distortion)
        or not equals(camera.get("T_imu_cam"), inverse)
        or type(camera.get("timeshift_cam_imu")) not in (int, float)
        or camera["timeshift_cam_imu"] != float(artifact.timeshift_decimal_s)
    ):
        raise ValueError("actual native camera calibration differs from artifact")
    if float(artifact.timeshift_decimal_s) != 0.0:
        raise ValueError("native fast consumer does not support nonzero offset")
    if len(set(selected)) != len(selected):
        raise ValueError("managed source files must be distinct")
    # Recheck the declared digests, including transitive rig/result references;
    # evidence must not hash an unbounded later replacement as a new identity.
    for file in selected:
        raw = _bound_bytes(file, expected[file], MAX_DOCUMENT)
        if _records is not None:
            _records.append(dict(path=str(file), sha256=expected[file], bytes=len(raw)))
    return artifact, tuple(selected)


def configuration_record(path, digest, native_config):
    records = []
    artifact, _ = load_managed_configuration(path, digest, native_config, _records=records)
    return dict(
        profile="calibrated-managed-capture-v1",
        configuration_sha256=digest,
        inputs=records,
        calibration=artifact.record(),
        fusion_eligible=False,
        controller_ready=False,
    )


class ManagedCaptureSource:
    """Bounded native state owner. An unqualified diagnostic is never controller input."""

    def __init__(self, artifact, *, now=time.monotonic_ns, session_id=None):
        if type(artifact) is not KalibrCameraArtifact or artifact.imu_contract != RAW_IMU_CONTRACT:
            raise ValueError("raw IMU calibration contract required")
        if float(artifact.timeshift_decimal_s) != 0:
            raise ValueError("native fast consumer does not support nonzero offset")
        self.artifact, self._now = artifact, now
        self.session_id = session_id
        self._lock = Lock()
        self._failure = None
        self._process = self._pid = None
        self._cameras = deque(maxlen=2)
        self._fast = None
        self._last_receipt = 0
        self._last_camera = self._last_target = -1

    @contextmanager
    def _access(self, process=None, *, deadline_ns=None):
        if not self._lock.acquire(timeout=0.05):
            raise TimeoutError("managed source owner busy")
        try:
            if deadline_ns is not None and time.monotonic_ns() >= deadline_ns:
                raise TimeoutError("managed source admission deadline")
            if self._failure:
                raise ValueError("managed source failure latched: " + self._failure)
            if process is not None and self._process is None:
                raise ValueError("managed native process not attached")
            if self._process is not None and (
                (process is not None and process is not self._process)
                or self._process.pid != self._pid
                or self._process.poll() is not None
            ):
                raise ValueError("managed native process changed/exited")
            yield
            # State changes remain inside this lock. An overrun latches refusal
            # before another thread can observe the derived state as usable.
            if deadline_ns is not None and time.monotonic_ns() >= deadline_ns:
                raise TimeoutError("managed source admission deadline")
        except BaseException as exc:
            if self._failure is None:
                self._failure = repr(exc)
            raise
        finally:
            self._lock.release()

    def attach_native(self, process):
        with self._access():
            if self._process is not None or type(process.pid) is not int or process.pid <= 0 or process.poll() is not None:
                raise ValueError("one live managed native process required")
            self._process, self._pid = process, process.pid

    def _receipt(self, ack):
        receipt, now = ack.get("acknowledged_ns"), self._now()
        if (
            type(receipt) is not int
            or type(now) is not int
            or not self._last_receipt <= receipt <= now
            or not 0 <= now - receipt < 2_000_000_000
        ):
            raise ValueError("managed source receipt clock stale/regressed")
        self._last_receipt = receipt
        return receipt

    @staticmethod
    def _state(value, size):
        state = np.asarray(value, dtype=float)
        if state.shape != (size,) or not np.isfinite(state).all() or abs(np.linalg.norm(state[:4]) - 1) > 1e-6:
            raise ValueError("invalid managed native state")
        # OpenVINS JPL q_GtoI coefficients interpreted as Hamilton give R_ItoG.
        return state, Rotation.from_quat(state[:4]).as_matrix()

    def accept_camera(self, ack, process, *, deadline_ns=None):
        with self._access(process, deadline_ns=deadline_ns):
            receipt = self._receipt(ack)
            stamp = ack.get("sample_ns")
            if type(stamp) is not int or stamp <= self._last_camera:
                raise ValueError("managed camera sample regression")
            self._last_camera = stamp
            if ack.get("internal_initialized") is not True or ack.get("public_initialized") is not True:
                return
            state, rotation = self._state(ack.get("imu_state"), 16)
            state_time = ack.get("state_time_s")
            if type(state_time) not in (int, float) or not math.isfinite(state_time):
                raise ValueError("invalid native camera state timestamp")
            if abs(state_time * 1e9 - stamp) > 1:
                return  # No exact image-time pose: do not interpolate an old filter state.
            mount, translation = self.artifact.body_from_camera()
            camera_rotation = Rotation.from_matrix(rotation @ mount).as_quat()
            pose = [*(state[4:7] + rotation @ translation), *camera_rotation]
            self._cameras.append((stamp, receipt, list(map(float, pose))))

    def accept_fast(self, prediction, ack, process, *, deadline_ns=None):
        with self._access(process, deadline_ns=deadline_ns):
            receipt = self._receipt(ack)
            target = prediction.get("target_ns")
            if type(target) is not int or target <= self._last_target or prediction.get("camera_imu_offset_s") != 0:
                raise ValueError("managed propagation sample/offset mismatch")
            self._last_target = target
            self._fast = None
            if not all(prediction.get(key) is True for key in ("success", "internal_initialized", "public_initialized")):
                return
            if prediction.get("reset_counter") is not None:
                raise ValueError("native reset lifecycle unavailable in this source version")
            state, rotation = self._state(prediction.get("state13"), 13)
            axis = rotation[:, 0]
            derivative = rotation @ np.cross(state[10:13], [1.0, 0.0, 0.0])
            denominator = axis[0] ** 2 + axis[1] ** 2
            if denominator < 1e-8:
                raise ValueError("managed yaw undefined")
            self._fast = dict(
                sample_ns=target,
                receipt_ns=receipt,
                native_pid=self._pid,
                session_id=self.session_id,
                last_camera_ns=prediction.get("last_camera_ns"),
                position=state[4:7].tolist(),
                velocity=(rotation @ state[7:10]).tolist(),
                yaw=math.atan2(axis[1], axis[0]),
                yaw_rate=float((axis[0] * derivative[1] - axis[1] * derivative[0]) / denominator),
                reset_counter=None,
                quality=None,
                controller_ready=False,
                fusion_eligible=False,
                frame="openvins-unregistered-gravity-local",
                calibration=self.artifact.record(),
            )

    def diagnostic_snapshot(self, sample_ns, camera_ns):
        with self._access():
            return self._snapshot_locked(sample_ns, camera_ns)

    def _snapshot_locked(self, sample_ns, camera_ns):
        now = self._now()
        state = self._fast
        if (
            self._process is None
            or state is None
            or type(sample_ns) is not int
            or not 0 <= sample_ns - state["sample_ns"] <= 100_000_000
            or not 0 <= now - state["receipt_ns"] < 2_000_000_000
        ):
            raise ValueError("managed propagation missing/stale/future")
        camera = next((item for item in self._cameras if item[0] == camera_ns), None)
        if (
            camera is None
            or state["last_camera_ns"] != camera_ns
            or not 0 <= sample_ns - camera_ns <= 100_000_000
            or not 0 <= now - camera[1] < 2_000_000_000
        ):
            raise ValueError("exact image-time camera pose missing/stale/future")
        # Selection, validation and owned deep copy all occur under one lock.
        return json.loads(json.dumps(dict(state, camera_ns=camera_ns, camera_pose=camera[2]), allow_nan=False))

    def require_ready(self, sample_ns):
        raise RuntimeError("managed source is not qualified for controller/fusion use")

    def latch_failure(self, error):
        # Set refusal first so a lock timeout cannot leave an old snapshot usable.
        self._failure = self._failure or repr(error)

    def latest_diagnostic(self, sim_ns):
        with self._access():
            if self._fast is None or not self._cameras:
                return None
            target, camera = self._fast["sample_ns"], self._fast["last_camera_ns"]
            present = any(item[0] == camera for item in self._cameras)
            # No interpolation or truth registration; one coherent source view.
            if not present:
                return None
            if target > sim_ns:
                raise ValueError("managed state ahead of observed simulation")
            return self._snapshot_locked(sim_ns, camera)

    def bind_capture_session(self, session_id):
        with self._access():
            if self._last_camera != -1 or self._last_target != -1 or not isinstance(session_id, str) or not session_id:
                raise ValueError("capture session must be bound before input")
            self.session_id = session_id


class ManagedEstimateNativeClient(LiveEstimateNativeClient):
    """The actual capture child/transport; consume only after parent send returns."""

    def __init__(self, command, output, *, source, **kwargs):
        self.managed_source = source
        self._pending_events = None
        super().__init__(command, output, **kwargs)
        try:
            source.attach_native(self.process)
        except BaseException as primary:
            try:
                super().finish()
            except BaseException as cleanup:
                _secondary(primary, [cleanup])
            raise

    def _write(self, event, **fields):
        super()._write(event, **fields)
        if self._pending_events is not None and event in ("camera_state", "fast_prediction"):
            if len(self._pending_events) >= 1:
                raise ValueError("multiple managed states in one source acknowledgement")
            self._pending_events.append((event, fields))

    def send(self, action, pixels=None):
        deadline_ns = time.monotonic_ns() + int(self.timeout_s * 1_000_000_000)
        self._pending_events = []
        try:
            ack = super().send(action, pixels)
            if time.monotonic_ns() >= deadline_ns:
                raise TimeoutError("managed source admission deadline")
            for event, fields in self._pending_events:
                if event == "camera_state":
                    self.managed_source.accept_camera(fields["ack"], self.process, deadline_ns=deadline_ns)
                else:
                    self.managed_source.accept_fast(fields["prediction"], fields["ack"], self.process, deadline_ns=deadline_ns)
            if time.monotonic_ns() >= deadline_ns:
                raise TimeoutError("managed source admission deadline")
            return ack
        except BaseException as exc:
            self._feed_failure = self.failed = repr(exc)
            self.managed_source.latch_failure(exc)
            raise
        finally:
            self._pending_events = None
