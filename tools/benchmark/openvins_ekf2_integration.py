"""Transport-neutral OpenVINS health-to-ODOMETRY candidate composition.

The state machine owns one :class:`OpenVinsHealthContract`.  Callers provide
native state and source/clock observations; they cannot provide quality, reset,
covariance-profile, or fusion decisions.  Candidate encoding is in-memory only.
"""

from __future__ import annotations

import copy
import importlib.metadata
import math
from typing import Protocol

import numpy as np

from tools.benchmark.openvins_ekf2_transform import FLOAT_MAX, convert_imu15
from tools.benchmark.openvins_ekf2_transform import PROFILE as FRAME_PROFILE
from tools.benchmark.openvins_health_contract import MAX_NS, OpenVinsHealthContract

CAMERA_RECORD_FIELDS = {
    "kind",
    "session_id",
    "sample_ns",
    "internal_initialized",
    "public_initialized",
    "state_time_s",
    "last_regular_update_s",
    "imu_state16",
    "imu_covariance15",
}
CLOCK_FIELDS = {"clock_session_id", "publisher_session_id", "observed_remote_ns"}
VELOCITY_LINEAR_UPPER_INDICES = frozenset({0, 1, 2, 6, 7, 11})
WIRE_FIELD_NAMES = {
    "time_usec",
    "frame_id",
    "child_frame_id",
    "x",
    "y",
    "z",
    "q",
    "vx",
    "vy",
    "vz",
    "rollspeed",
    "pitchspeed",
    "yawspeed",
    "pose_covariance",
    "velocity_covariance",
    "reset_counter",
    "estimator_type",
    "quality",
}


class EvidenceSink(Protocol):
    def write(self, record: dict) -> None: ...

    def close(self) -> None: ...


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(character.isspace() for character in value):
        raise ValueError(f"invalid {name}")
    return value


def _integer(value: object, name: str, *, minimum: int = 0, maximum: int = MAX_NS) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"invalid {name}")
    return value


def _upper_triangle(matrix: np.ndarray) -> list[float]:
    return matrix[np.triu_indices(6)].tolist()


def _velocity_upper(matrix3: np.ndarray) -> list[float | None]:
    result: list[float | None] = [None] * 21
    upper6 = list(zip(*np.triu_indices(6), strict=True))
    for index, (row, column) in enumerate(upper6):
        if row < 3 and column < 3:
            result[index] = float(matrix3[row, column])
    return result


class OfflineEkf2Composer:
    """One estimator/clock/publisher session; all failures remain offline."""

    def __init__(
        self,
        health_contract: OpenVinsHealthContract,
        *,
        clock_session_id: str,
        publisher_session_id: str,
        sample_to_remote_offset_ns: int,
        max_age_ns: int,
        sink: EvidenceSink | None = None,
    ) -> None:
        if not isinstance(health_contract, OpenVinsHealthContract):
            raise ValueError("invalid authoritative health contract")
        self.contract = health_contract
        self.clock_session_id = _identity(clock_session_id, "clock session identity")
        self.publisher_session_id = _identity(publisher_session_id, "publisher session identity")
        self.sample_to_remote_offset_ns = _integer(
            sample_to_remote_offset_ns,
            "sample-to-remote offset",
            minimum=-(MAX_NS - 1),
        )
        self.max_age_ns = _integer(max_age_ns, "maximum sample age", minimum=1)
        if sink is not None and (not callable(getattr(sink, "write", None)) or not callable(getattr(sink, "close", None))):
            raise ValueError("invalid evidence sink")
        self.sink = sink
        self.failure: str | None = None
        self.closed = False
        self.last_wire_us: int | None = None
        self.last_sample_ns: int | None = None
        self.last_observed_remote_ns: int | None = None
        self.candidate_count = 0
        self.refusal_count = 0

    def _refusal(self, reason: str, health: dict, *, latched: bool, reasons: list[str] | None = None) -> dict:
        self.refusal_count += 1
        return {
            "schema": "openvins-ekf2-offline-composition-v1",
            "status": "refused",
            "candidate": None,
            "refusal": {
                "reason": reason,
                "reasons": list(health.get("reasons", [])) if reasons is None else list(reasons),
                "latched": latched,
            },
            "health": copy.deepcopy(health),
            "fusion_eligible": False,
        }

    def _latch(self, reason: str) -> dict:
        if self.failure is None:
            self.failure = reason
        health = self.contract.fail(self.failure)
        return self._refusal(self.failure, health, latched=True, reasons=[self.failure])

    def _emit(self, record: dict) -> dict:
        if self.sink is None:
            return record
        try:
            self.sink.write(copy.deepcopy(record))
        except Exception:
            return self._latch("journal_write_failed")
        return record

    def compose(self, camera_record: object, source_health: object, clock_evidence: object) -> dict:
        if self.closed:
            raise RuntimeError("offline composer already closed")
        if self.failure is not None:
            return self._refusal(self.failure, self.contract.fail(self.failure), latched=True, reasons=[self.failure])
        if not isinstance(camera_record, dict) or set(camera_record) != CAMERA_RECORD_FIELDS:
            return self._emit(self._latch("camera_record_invalid"))
        if not isinstance(clock_evidence, dict) or set(clock_evidence) != CLOCK_FIELDS:
            return self._emit(self._latch("clock_evidence_invalid"))
        if camera_record["session_id"] != self.contract.session_id:
            return self._emit(self._latch("estimator_session_mismatch"))
        if clock_evidence["clock_session_id"] != self.clock_session_id:
            return self._emit(self._latch("clock_session_mismatch"))
        if clock_evidence["publisher_session_id"] != self.publisher_session_id:
            return self._emit(self._latch("publisher_session_mismatch"))

        try:
            sample_ns = _integer(camera_record["sample_ns"], "sample time", minimum=1)
            observed_remote_ns = _integer(clock_evidence["observed_remote_ns"], "remote observation time", minimum=1)
            sample_remote_ns = sample_ns + self.sample_to_remote_offset_ns
            if not 1 <= sample_remote_ns <= MAX_NS:
                raise ValueError("invalid transformed sample time")
            wire_us = sample_remote_ns // 1000
            if not 1 <= wire_us < 2**64:
                raise ValueError("invalid wire time")
        except (KeyError, TypeError, ValueError, OverflowError):
            return self._emit(self._latch("clock_evidence_invalid"))
        if self.last_sample_ns is not None and sample_ns <= self.last_sample_ns:
            return self._emit(self._latch("sample_time_regressed"))
        if self.last_wire_us is not None and wire_us <= self.last_wire_us:
            return self._emit(self._latch("wire_time_not_unique"))
        if self.last_observed_remote_ns is not None and observed_remote_ns <= self.last_observed_remote_ns:
            return self._emit(self._latch("observation_time_regressed"))
        if observed_remote_ns < sample_remote_ns:
            return self._emit(self._latch("sample_from_future"))
        if observed_remote_ns - sample_remote_ns > self.max_age_ns:
            return self._emit(self._latch("sample_too_old"))

        health_row = {key: camera_record[key] for key in CAMERA_RECORD_FIELDS if key != "imu_state16"}
        health = self.contract.accept_camera(health_row, source_health)
        if health["quality"] != 1:
            latched = health["quality"] == -1 or health["failed_latched"] is True
            if latched and self.failure is None:
                self.failure = health["reasons"][0] if health["reasons"] else "health_failed"
            reason = self.failure if latched else "health_not_positive"
            return self._emit(self._refusal(reason, health, latched=latched))
        try:
            geometry = convert_imu15(camera_record["imu_state16"], health["bounded_covariance15"])
        except (TypeError, ValueError, OverflowError, np.linalg.LinAlgError):
            return self._emit(self._latch("transform_invalid"))

        covariance = np.asarray(geometry["covariance9x9"], dtype=float)
        fields = {
            "time_usec": wire_us,
            "frame_id": 20,
            "child_frame_id": 12,
            "x": geometry["position_local_frd"][0],
            "y": geometry["position_local_frd"][1],
            "z": geometry["position_local_frd"][2],
            "q": geometry["q_body_to_local_frd_wxyz"],
            "vx": geometry["velocity_body_frd"][0],
            "vy": geometry["velocity_body_frd"][1],
            "vz": geometry["velocity_body_frd"][2],
            "rollspeed": None,
            "pitchspeed": None,
            "yawspeed": None,
            "pose_covariance": _upper_triangle(covariance[:6, :6]),
            "velocity_covariance": _velocity_upper(covariance[6:9, 6:9]),
            "reset_counter": health["reset_counter"],
            "estimator_type": 3,
            "quality": health["quality"],
        }
        candidate = {
            "schema": "openvins-ekf2-offline-candidate-v1",
            "frame_profile": FRAME_PROFILE,
            "fields": fields,
            "covariance9x9": geometry["covariance9x9"],
            "identities": {
                "estimator_session_id": self.contract.session_id,
                "clock_session_id": self.clock_session_id,
                "publisher_session_id": self.publisher_session_id,
            },
            "health": copy.deepcopy(health),
            "angular_velocity_source": "unavailable-none-not-zero",
            "fusion_eligible": False,
        }
        result = {
            "schema": "openvins-ekf2-offline-composition-v1",
            "status": "candidate",
            "candidate": candidate,
            "refusal": None,
            "health": copy.deepcopy(health),
            "fusion_eligible": False,
        }
        emitted = self._emit(result)
        if emitted["status"] != "candidate":
            return emitted
        self.last_sample_ns = sample_ns
        self.last_wire_us = wire_us
        self.last_observed_remote_ns = observed_remote_ns
        self.candidate_count += 1
        return emitted

    def replace_estimator(self, new_session_id: str) -> dict:
        if self.closed:
            raise RuntimeError("offline composer already closed")
        if self.failure is not None:
            return self._refusal(self.failure, self.contract.fail(self.failure), latched=True, reasons=[self.failure])
        try:
            self.contract = self.contract.replace_session(new_session_id)
        except (TypeError, ValueError, OverflowError):
            return self._emit(self._latch("estimator_session_invalid"))
        transition = {
            "schema": "openvins-ekf2-estimator-transition-v1",
            "estimator_session_id": self.contract.session_id,
            "clock_session_id": self.clock_session_id,
            "publisher_session_id": self.publisher_session_id,
            "quality": 0,
            "reset_total": self.contract.reset_total,
            "reset_counter": self.contract.reset_total % 256,
            "covariance_profile": self.contract.profile.name,
            "fusion_eligible": False,
        }
        return self._emit(transition)

    def finish(self) -> dict:
        if self.closed:
            raise RuntimeError("offline composer already closed")
        self.closed = True
        if self.sink is not None:
            try:
                self.sink.close()
            except Exception:
                return self._latch("journal_close_failed")
        if self.failure is not None:
            return self._refusal(self.failure, self.contract.fail(self.failure), latched=True, reasons=[self.failure])
        return {
            "schema": "openvins-ekf2-offline-result-v1",
            "status": "complete",
            "candidate_count": self.candidate_count,
            "refusal_count": self.refusal_count,
            "reset_total": self.contract.reset_total,
            "reset_counter": self.contract.reset_total % 256,
            "fusion_eligible": False,
        }


def _wire_fields(candidate: object) -> dict:
    if (
        not isinstance(candidate, dict)
        or candidate.get("schema") != "openvins-ekf2-offline-candidate-v1"
        or candidate.get("frame_profile") != FRAME_PROFILE
        or candidate.get("fusion_eligible") is not False
        or not isinstance(candidate.get("fields"), dict)
    ):
        raise ValueError("invalid offline candidate")
    fields = copy.deepcopy(candidate["fields"])
    health = candidate.get("health")
    identities = candidate.get("identities")
    if (
        set(fields) != WIRE_FIELD_NAMES
        or not isinstance(health, dict)
        or health.get("schema") != "openvins-health-evidence-v1"
        or health.get("quality") != 1
        or health.get("failed_latched") is not False
        or health.get("covariance_sim_domain_qualified") is not True
        or health.get("covariance_profile") != "px4-d6f12ad-gate-floor-v1"
        or not isinstance(identities, dict)
        or identities.get("estimator_session_id") != health.get("session_id")
        or fields.get("reset_counter") != health.get("reset_counter")
        or fields.get("frame_id") != 20
        or fields.get("child_frame_id") != 12
        or fields.get("estimator_type") != 3
        or fields.get("quality") != 1
        or type(fields.get("reset_counter")) is not int
        or not 0 <= fields["reset_counter"] <= 255
        or type(fields.get("time_usec")) is not int
        or not 0 < fields["time_usec"] < 2**64
    ):
        raise ValueError("invalid pinned packet identity")
    numeric = [fields.get(name) for name in ("x", "y", "z", "vx", "vy", "vz")]
    if any(
        type(value) is bool
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or abs(float(value)) > FLOAT_MAX
        for value in numeric
    ):
        raise ValueError("invalid packet state")
    quaternion = np.asarray(fields.get("q"), dtype=float)
    if (
        quaternion.shape != (4,)
        or not np.all(np.isfinite(quaternion))
        or float(np.max(np.abs(quaternion))) > FLOAT_MAX
        or abs(float(np.linalg.norm(quaternion)) - 1) > 1e-5
    ):
        raise ValueError("invalid packet quaternion")
    pose = fields.get("pose_covariance")
    velocity = fields.get("velocity_covariance")
    if (
        not isinstance(pose, list)
        or len(pose) != 21
        or any(
            type(value) is bool
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or abs(float(value)) > FLOAT_MAX
            for value in pose
        )
    ):
        raise ValueError("invalid pose covariance")
    if not isinstance(velocity, list) or len(velocity) != 21:
        raise ValueError("invalid velocity covariance")
    for index, value in enumerate(velocity):
        if index in VELOCITY_LINEAR_UPPER_INDICES:
            if (
                type(value) is bool
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or abs(float(value)) > FLOAT_MAX
            ):
                raise ValueError("invalid velocity covariance")
        elif value is not None:
            raise ValueError("angular covariance must remain unavailable")
    if any(fields.get(name) is not None for name in ("rollspeed", "pitchspeed", "yawspeed")):
        raise ValueError("angular velocity must remain unavailable")
    pose_matrix = np.zeros((6, 6))
    pose_matrix[np.triu_indices(6)] = pose
    pose_matrix += np.triu(pose_matrix, 1).T
    velocity_matrix = np.zeros((3, 3))
    velocity_matrix[np.triu_indices(3)] = [velocity[index] for index in (0, 1, 2, 6, 7, 11)]
    velocity_matrix += np.triu(velocity_matrix, 1).T
    covariance = np.asarray(candidate.get("covariance9x9"), dtype=float)
    if (
        covariance.shape != (9, 9)
        or not np.all(np.isfinite(covariance))
        or float(np.max(np.abs(covariance))) > FLOAT_MAX
        or not np.allclose(covariance, covariance.T, rtol=0.0, atol=1e-12)
    ):
        raise ValueError("invalid retained covariance")
    try:
        pose_minimum = float(np.linalg.eigvalsh(pose_matrix)[0])
        velocity_minimum = float(np.linalg.eigvalsh(velocity_matrix)[0])
        covariance_minimum = float(np.linalg.eigvalsh(covariance)[0])
    except np.linalg.LinAlgError as exc:
        raise ValueError("invalid packet covariance") from exc
    if pose_minimum < -1e-10 * max(1.0, float(np.max(np.abs(pose_matrix)))):
        raise ValueError("invalid pose covariance")
    if velocity_minimum < -1e-10 * max(1.0, float(np.max(np.abs(velocity_matrix)))):
        raise ValueError("invalid velocity covariance")
    if covariance_minimum < -1e-10 * max(1.0, float(np.max(np.abs(covariance)))):
        raise ValueError("invalid retained covariance")
    retained_pose = covariance[:6, :6][np.triu_indices(6)]
    retained_velocity = covariance[6:9, 6:9][np.triu_indices(3)]
    if not np.allclose(np.asarray(pose, dtype=float), retained_pose, rtol=0.0, atol=1e-12):
        raise ValueError("pose covariance does not match retained evidence")
    if not np.allclose(
        np.asarray([velocity[index] for index in (0, 1, 2, 6, 7, 11)], dtype=float),
        retained_velocity,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError("velocity covariance does not match retained evidence")
    fields["rollspeed"] = fields["pitchspeed"] = fields["yawspeed"] = float("nan")
    fields["velocity_covariance"] = [float("nan") if value is None else value for value in velocity]
    return fields


def encode_candidate(candidate: object) -> bytes:
    """Encode one candidate in memory; this function has no transport path."""
    if importlib.metadata.version("pymavlink") != "2.4.49":
        raise ValueError("unverified pymavlink version")
    from pymavlink.dialects.v20 import common

    message = common.MAVLink_odometry_message(**_wire_fields(candidate))
    return message.pack(common.MAVLink(None, srcSystem=1, srcComponent=191))


def decode_candidate(packet: object) -> dict:
    """Decode exactly one in-memory MAVLink2 ODOMETRY packet."""
    if not isinstance(packet, bytes) or not packet:
        raise ValueError("invalid packet bytes")
    if importlib.metadata.version("pymavlink") != "2.4.49":
        raise ValueError("unverified pymavlink version")
    from pymavlink.dialects.v20 import common

    try:
        parser = common.MAVLink(None)
        messages = parser.parse_buffer(packet)
    except Exception as exc:
        raise ValueError("invalid MAVLink packet") from exc
    if messages is None or len(messages) != 1 or parser.buf_len() != 0:
        raise ValueError("packet must contain exactly one complete message")
    message = messages[0]
    if message.get_type() != "ODOMETRY":
        raise ValueError("packet is not ODOMETRY")
    return message.to_dict()
