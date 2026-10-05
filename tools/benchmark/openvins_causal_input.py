"""Raw simulation input contract. No estimator, transport, truth pose or fusion grant."""

from __future__ import annotations

import copy
import hashlib
import json
import math

from tools.benchmark.disarmed_sensor_provenance import validate_event


def raw_profile():
    """Fresh descriptive profile; noise candidates are not applied or calibrated."""
    noise = {}
    for name, std in [("gyro", [0.0008726646] * 3), ("accel", [0.00637, 0.00637, 0.00686])]:
        density = [v * math.sqrt(0.004) for v in std]
        noise[name] = dict(
            sample_stddev_xyz=std, density_xyz=density, scalar_density_envelope=max(density), bias_random_walk=None
        )
    f = 108.12401050876075
    return {
        "schema": "flydrones-gazebo-raw-imu-causal-v1",
        "source": "Gazebo raw IMU sample, not PX4 integrated/bias-corrected IMU",
        "gyro_units": "rad/s",
        "accel_units": "m/s^2",
        "sample_period_ns": 4_000_000,
        "noise": noise,
        "noise_scope": "model-derived continuous density candidate; no estimator config applied",
        "covariance_calibrated": False,
        "eligible_for_px4_fusion": False,
        "sample_to_camera_offset_ns": 0,
        "time_offset_scope": "same simulator clock; not dynamic calibration",
        "R_FLU_to_FRD": [[1, 0, 0], [0, -1, 0], [0, 0, -1]],
        "R_camera_to_FRD": [[0, 0, 1], [1, 0, 0], [0, 1, 0]],
        "p_camera_in_FRD_m": [0.12, 0.0, -0.002],
        "extrinsic_scope": "prior static optical probe and fixed model; dynamic validation outstanding",
        "camera_info": {
            "width": 160,
            "height": 120,
            "frame_id": "camera_link",
            "intrinsics_k": [f, 0.0, 80.0, 0.0, f, 60.0, 0.0, 0.0, 1.0],
            "projection_p": [f, 0.0, 80.0, 0.0, 0.0, f, 60.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            "distortion_model": 0,
            "distortion_k": [0.0] * 5,
        },
        "source_pins": {
            "gz_sensors_tag": "9348f9fe8a11b9d50381819f51e17e136aedab8a",
            "openvins": "69488123ed9362dd44b6f28e7f4680abbff1442b",
            "px4_models": "d6f12ad1c4f70ad3230afd7d86e971421e02fef4",
        },
        "limits": {
            "pending_per_kind": 8,
            "wall_wait_ns": 250_000_000,
            "image_imu_lag_ns": 200_000_000,
            "max_imu_gap_ns": 4_000_000,
        },
    }


class InputRefusal(ValueError):
    """A refused input remains identifiable even when no delivery actions are returned."""

    def __init__(self, disposition):
        super().__init__(disposition["reason"])
        self._disposition = copy.deepcopy(disposition)

    @property
    def disposition(self):
        return copy.deepcopy(self._disposition)


class CausalInput:
    """Single-owner bounded input scheduler; a refusal permanently latches failure."""

    def __init__(self, *, session_id, clock_id):
        if any(not isinstance(value, str) or not value.strip() for value in (session_id, clock_id)):
            raise ValueError("explicit session and clock identifiers required")
        self.session_id, self.clock_id = session_id, clock_id
        self._profile_json = json.dumps(raw_profile(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.profile_sha256 = hashlib.sha256(self._profile_json.encode()).hexdigest()
        self._last_sequence = -1
        self._watermark = 0
        self._last = {}
        self._last_arrival = {}
        self._pending = {"rgb": {}, "info": {}}
        self._imu_first = None
        self._imu_latest = None
        self._imu_sequence = None
        self.failure = None
        self._refused = None
        self._closed = False

    @property
    def profile(self):
        return json.loads(self._profile_json)

    def _reject(self, reason):
        self.failure = reason
        raise ValueError(reason)

    def _open(self):
        if self.failure:
            raise ValueError("failure latched: " + self.failure)
        if self._closed:
            raise ValueError("input session closed")

    def _expire(self):
        for pending in self._pending.values():
            for row, _ in pending.values():
                if self._watermark - row["arrival_monotonic_ns"] > 250_000_000:
                    self._reject("pending input exceeded wall wait")

    def accept(self, event, *, sequence, session_id, clock_id):
        self._open()
        transaction_fields = (
            "_last_sequence",
            "_watermark",
            "_last",
            "_last_arrival",
            "_pending",
            "_imu_first",
            "_imu_latest",
            "_imu_sequence",
        )
        before = {key: copy.deepcopy(getattr(self, key)) for key in transaction_fields}
        try:
            if session_id != self.session_id or clock_id != self.clock_id:
                raise ValueError("session/clock changed; explicit estimator reset required")
            if type(sequence) is not int or sequence != self._last_sequence + 1:
                raise ValueError("input sequence gap or duplicate")
            row = validate_event(copy.deepcopy(event))
            kind = row["kind"]
            if kind not in {"imu", "rgb", "info"}:
                raise ValueError("unsupported estimator input kind")
            stamp, arrival = row["sample_ns"], row["arrival_monotonic_ns"]
            if stamp <= self._last.get(kind, 0) or arrival < self._last_arrival.get(kind, 0):
                raise ValueError("duplicate/regressed sample or arrival")
            if kind == "imu" and kind in self._last and stamp - self._last[kind] > 4_000_000:
                raise ValueError("IMU sample gap")
            if kind == "info":
                calibration = row["camera_info"]
                if (
                    calibration != self.profile["camera_info"]
                    or any(type(calibration[key]) is not int for key in ("width", "height", "distortion_model"))
                    or any(
                        type(value) not in (int, float) or not math.isfinite(value)
                        for key in ("intrinsics_k", "projection_p", "distortion_k")
                        for value in calibration[key]
                    )
                ):
                    raise ValueError("camera calibration differs from pinned profile")
            self._watermark = max(self._watermark, arrival)
            if self._watermark - arrival > 250_000_000:
                raise ValueError("input already exceeded wall wait")
            self._expire()
            if kind != "imu" and len(self._pending[kind]) >= 8:
                raise ValueError("pending input capacity exceeded")
            self._last[kind], self._last_arrival[kind] = stamp, arrival
            self._last_sequence = sequence
            actions = []
            if kind == "imu":
                self._imu_first = stamp if self._imu_first is None else self._imu_first
                self._imu_latest, self._imu_sequence = stamp, sequence
                actions.append(
                    dict(
                        kind="imu",
                        sample_ns=stamp,
                        wm=row["gyro_frd"],
                        am=row["accel_frd"],
                        source_sequence=sequence,
                        source_arrival_ns=arrival,
                        release_sequence=sequence,
                        release_wall_ns=self._watermark,
                        profile_sha256=self.profile_sha256,
                        eligible_for_px4_fusion=False,
                    )
                )
            else:
                self._pending[kind][stamp] = (row, sequence)
            actions.extend(self._release())
            return actions
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            for key, value in before.items():
                setattr(self, key, value)
            self.failure = str(exc)
            self._refused = dict(
                kind="refused_input",
                source_sequence=sequence,
                input=copy.deepcopy(event),
                reason=self.failure,
                eligible_for_px4_fusion=False,
            )
            raise InputRefusal(self._refused) from exc

    def _release(self):
        actions = []
        while self._pending["rgb"]:
            stamp = min(self._pending["rgb"])
            if stamp not in self._pending["info"] or self._imu_latest is None or self._imu_latest <= stamp:
                break
            if self._imu_first > stamp:
                self._reject("camera precedes available IMU history")
            if self._imu_latest - stamp > 200_000_000:
                self._reject("camera exceeded IMU sample lag")
            rgb, rgb_seq = self._pending["rgb"].pop(stamp)
            info, info_seq = self._pending["info"].pop(stamp)
            actions.append(
                dict(
                    kind="camera",
                    sample_ns=stamp,
                    rgb_sequence=rgb_seq,
                    info_sequence=info_seq,
                    camera_info=copy.deepcopy(info["camera_info"]),
                    source_arrival_ns=rgb["arrival_monotonic_ns"],
                    info_arrival_ns=info["arrival_monotonic_ns"],
                    imu_boundary_ns=self._imu_latest,
                    imu_boundary_sequence=self._imu_sequence,
                    release_sequence=self._last_sequence,
                    release_wall_ns=self._watermark,
                    profile_sha256=self.profile_sha256,
                    eligible_for_px4_fusion=False,
                )
            )
        return actions

    def tick(self, wall_monotonic_ns):
        self._open()
        if type(wall_monotonic_ns) is not int or wall_monotonic_ns < self._watermark:
            self._reject("consumer wall clock regressed")
        self._watermark = wall_monotonic_ns
        self._expire()
        return []

    def finish(self):
        if self._closed:
            raise ValueError("input session already closed")
        self._closed = True
        pending = []
        for stamp in sorted(set(self._pending["rgb"]) | set(self._pending["info"])):
            rgb, info = self._pending["rgb"].get(stamp), self._pending["info"].get(stamp)
            reason = self.failure or (
                "rgb_missing" if rgb is None else "camera_info_missing" if info is None else "later_imu_missing"
            )
            pending.append(
                dict(
                    sample_ns=stamp,
                    rgb_sequence=rgb[1] if rgb else None,
                    info_sequence=info[1] if info else None,
                    reason=reason,
                    eligible_for_px4_fusion=False,
                )
            )
        if self._refused is not None:
            pending.append(copy.deepcopy(self._refused))
        return pending
