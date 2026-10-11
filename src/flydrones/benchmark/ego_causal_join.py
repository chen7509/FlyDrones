"""Fail-closed, offline join of EGO diagnostic identities.

This matches records; it does not attest their producers or approve flight/training.
The pinned PositionCommand lacks a plan start timestamp and consumed-input IDs.
"""

from __future__ import annotations

import math
from copy import deepcopy

INT_MAX = 2**31 - 1  # Pinned traj_server.cpp stores Bspline.int64 traj_id in C++ int.
MAX_TIMESTAMP_NS = 2**63 - 1
_OBS_KEYS = frozenset({
    "run_id", "session_id", "sequence", "sim_ns", "frame_ns", "odom_sample_ns",
    "depth_sha256", "odom_sha256", "camera_pose_sha256",
    "calibration_sha256", "odom_source", "camera_source",
    "source_healthy", "truth_used",
})
_MAP_KEYS = frozenset({
    "run_id", "session_id", "revision", "source_sequence", "frame_ns",
    "depth_sha256", "camera_pose_sha256", "applied_sim_ns", "update_completed",
})
_PLAN_KEYS = frozenset({
    "run_id", "session_id", "trajectory_id_raw", "trajectory_id_stored",
    "start_time_ns", "odom_sequence", "odom_sha256", "map_revision", "map_source_sequence",
    "created_sim_ns",
})
_COMMAND_KEYS = frozenset({
    "run_id", "session_id", "trajectory_id", "header_stamp_ns",
    "position_ref", "velocity_ref", "yaw_rate",
})


def _record(value: dict, keys: frozenset[str]) -> dict:
    if type(value) is not dict or value.keys() != keys:
        raise ValueError("unexpected record fields")
    return deepcopy(value)


def _integer(value: object, label: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"invalid {label}")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"invalid {label}")
    return value


def _vector(value: object, label: str) -> None:
    if (type(value) is not list or len(value) != 3
            or any(not _finite_number(x) for x in value)):
        raise ValueError(f"invalid {label}")


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


class EgoCausalJoin:
    """One run and planner session, with immutable accepted record copies.

    Records must come from separately verified producers. A successful match
    remains only an offline identity match; it never grants teacher eligibility.
    """

    def __init__(self, *, run_id: str, session_id: str) -> None:
        if not isinstance(run_id, str) or not run_id or not isinstance(session_id, str) or not session_id:
            raise ValueError("run and session identifiers required")
        self.run_id = run_id
        self.session_id = session_id
        self._observations: dict[int, dict] = {}
        self._maps: dict[int, dict] = {}
        self._plans: dict[int, dict] = {}

    def _scope(self, row: dict) -> None:
        if row["run_id"] != self.run_id or row["session_id"] != self.session_id:
            raise ValueError("run or session mismatch")

    def add_observation(self, value: dict) -> None:
        row = _record(value, _OBS_KEYS)
        self._scope(row)
        seq = _integer(row["sequence"], "observation sequence", 1)
        sim_ns = _integer(row["sim_ns"], "observation time", maximum=MAX_TIMESTAMP_NS)
        frame_ns = _integer(row["frame_ns"], "frame time", maximum=MAX_TIMESTAMP_NS)
        odom_ns = _integer(row["odom_sample_ns"], "odometry time", maximum=MAX_TIMESTAMP_NS)
        if frame_ns > sim_ns or odom_ns > sim_ns:
            raise ValueError("observation uses future input")
        _digest(row["depth_sha256"], "depth identity")
        _digest(row["odom_sha256"], "odometry identity")
        _digest(row["camera_pose_sha256"], "camera pose identity")
        _digest(row["calibration_sha256"], "calibration identity")
        if row["odom_source"] != "px4_ekf2" or row["camera_source"] != "calibrated_rgbd":
            raise ValueError("unattested source type")
        if row["source_healthy"] is not True or row["truth_used"] is not False:
            raise ValueError("unhealthy or truth-source observation")
        if self._observations:
            last = self._observations[max(self._observations)]
            if seq <= last["sequence"] or sim_ns <= last["sim_ns"] or frame_ns < last["frame_ns"]:
                raise ValueError("observation sequence or time regression")
        self._observations[seq] = row

    def add_applied_map(self, value: dict) -> None:
        row = _record(value, _MAP_KEYS)
        self._scope(row)
        revision = _integer(row["revision"], "map revision", 1)
        seq = _integer(row["source_sequence"], "map source sequence", 1)
        frame_ns = _integer(row["frame_ns"], "frame time", maximum=MAX_TIMESTAMP_NS)
        applied_ns = _integer(row["applied_sim_ns"], "map application time", maximum=MAX_TIMESTAMP_NS)
        _digest(row["depth_sha256"], "depth identity")
        _digest(row["camera_pose_sha256"], "camera pose identity")
        if row["update_completed"] is not True:
            raise ValueError("map update incomplete")
        source = self._observations.get(seq)
        if source is None:
            raise ValueError("map source observation missing")
        if frame_ns != source["frame_ns"] or row["depth_sha256"] != source["depth_sha256"]:
            raise ValueError("depth identity mismatch")
        if row["camera_pose_sha256"] != source["camera_pose_sha256"]:
            raise ValueError("camera pose identity mismatch")
        if applied_ns < source["sim_ns"]:
            raise ValueError("map application before source observation")
        if self._maps and revision <= max(self._maps):
            raise ValueError("map revision reused or regressed")
        self._maps[revision] = row

    def add_plan(self, value: dict) -> None:
        row = _record(value, _PLAN_KEYS)
        self._scope(row)
        traj_id = _integer(row["trajectory_id_raw"], "trajectory id", 1, INT_MAX)
        if _integer(row["trajectory_id_stored"], "trajectory id", 1, INT_MAX) != traj_id:
            raise ValueError("trajectory id narrowed or aliased")
        _integer(row["start_time_ns"], "plan start time", maximum=MAX_TIMESTAMP_NS)
        _digest(row["odom_sha256"], "odometry identity")
        created_ns = _integer(row["created_sim_ns"], "plan time", maximum=MAX_TIMESTAMP_NS)
        odom_seq = _integer(row["odom_sequence"], "odometry sequence", 1)
        map_revision = _integer(row["map_revision"], "map revision", 1)
        map_seq = _integer(row["map_source_sequence"], "map source sequence", 1)
        source = self._observations.get(odom_seq)
        applied = self._maps.get(map_revision)
        if source is None or applied is None:
            raise ValueError("observation or map revision missing")
        if row["odom_sha256"] != source["odom_sha256"]:
            raise ValueError("odometry identity mismatch")
        if applied["source_sequence"] != map_seq or map_seq != odom_seq:
            raise ValueError("plan input sequence does not match applied map")
        if created_ns < source["sim_ns"] or created_ns < applied["applied_sim_ns"]:
            raise ValueError("plan time precedes consumed input")
        if traj_id in self._plans:
            raise ValueError("duplicate trajectory id in session")
        self._plans[traj_id] = row

    def match_command(self, value: dict, *, observation_sequence: int) -> dict:
        row = _record(value, _COMMAND_KEYS)
        self._scope(row)
        traj_id = _integer(row["trajectory_id"], "trajectory id", 1, INT_MAX)
        _integer(row["header_stamp_ns"], "command header time", maximum=MAX_TIMESTAMP_NS)
        _vector(row["position_ref"], "position reference")
        _vector(row["velocity_ref"], "velocity reference")
        if not _finite_number(row["yaw_rate"]):
            raise ValueError("invalid yaw rate")
        seq = _integer(observation_sequence, "observation sequence", 1)
        if not self._observations or seq != max(self._observations):
            raise ValueError("not the latest observation")
        plan = self._plans.get(traj_id)
        if plan is None:
            raise ValueError("matching trajectory id missing")
        if plan["odom_sequence"] != seq or plan["map_source_sequence"] != seq:
            raise ValueError("old plan is not for latest observation")
        source = self._observations[seq]
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "observation_sequence": seq,
            "map_revision": plan["map_revision"],
            "trajectory_id": traj_id,
            "plan_start_time_ns": plan["start_time_ns"],
            "command_header_stamp_ns": row["header_stamp_ns"],
            "depth_sha256": source["depth_sha256"],
            "odom_sha256": source["odom_sha256"],
            "camera_pose_sha256": source["camera_pose_sha256"],
            "calibration_sha256": source["calibration_sha256"],
            "teacher_qualified": False,
        }
