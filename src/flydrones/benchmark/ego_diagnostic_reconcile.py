"""Offline candidate join for pinned EGO diagnostic events.

This checks proposed bridge records, not their ROS producer or the patch binary.
It can never authorize training, fusion, or flight.
"""

from __future__ import annotations

import math

INT_MAX = 2**31 - 1
MAX_NS = 2**63 - 1
_BRIDGE_KEYS = frozenset({
    "schema", "run_id", "session", "pid", "sequence", "kind",
    "message_sha256", "sample_ns", "event_steady_ns", "source",
    "source_profile_sha256", "truth_used",
})
_SOURCE = {
    "odometry": "px4_ekf2",
    "depth": "calibrated_rgbd",
    "camera_pose": "px4_ekf2_calibrated_extrinsic",
    "position_command": "ego_server",
}
_PLANNER_EVENTS = frozenset({
    "fsm_odometry_received", "depth_pose_received", "depth_odom_received",
    "map_depth_applied", "map_cloud_applied", "plan_published",
})
_SERVER_EVENTS = frozenset({"server_bspline_received", "server_command_published"})
_TRACE_CORE = frozenset({
    "schema", "session", "pid", "sequence", "event_steady_ns", "event",
})
_EVENT_FIELDS = {
    "fsm_odometry_received": frozenset({
        "receive_node_ns", "odom_sequence", "odom_sha256", "stamp_ns",
        "frame_id", "child_frame_id",
    }),
    "depth_pose_received": frozenset({
        "receive_node_ns", "receive_sequence", "pending_for_apply",
        "image_sha256", "pose_sha256", "image_stamp_ns", "pose_stamp_ns",
    }),
    "depth_odom_received": frozenset({
        "receive_node_ns", "receive_sequence", "image_sha256",
        "pose_sha256", "image_stamp_ns", "pose_stamp_ns",
    }),
    "map_depth_applied": frozenset({
        "map_apply_node_ns", "revision", "depth_sequence", "receive_sequence",
        "image_sha256", "pose_sha256", "image_stamp_ns", "pose_stamp_ns",
        "pose_kind",
    }),
    "map_cloud_applied": frozenset({
        "map_cloud_node_ns", "revision", "cloud_sequence", "cloud_sha256",
    }),
    "plan_published": frozenset({
        "plan_publish_node_ns", "trajectory_id", "start_time_ns", "bspline_sha256",
        "start_origin", "parent_trajectory_id", "parent_start_time_ns",
        "parent_sample_s", "available_odom_sequence", "available_odom_sha256",
        "available_odom_stamp_ns", "map_before_revision", "map_after_revision",
        "map_depth_sequence", "map_depth_receive_sequence", "map_cloud_sequence",
        "map_image_sha256", "map_pose_sha256", "map_image_stamp_ns",
        "map_pose_stamp_ns", "map_pose_kind", "start_x", "start_y", "start_z",
        "start_vx", "start_vy", "start_vz",
    }),
    "server_bspline_received": frozenset({
        "raw_trajectory_id", "stored_trajectory_id", "start_time_ns",
        "bspline_sha256",
    }),
    "server_command_published": frozenset({
        "raw_trajectory_id", "stored_trajectory_id", "emitted_trajectory_id",
        "command_stamp_ns", "bspline_sha256", "command_sha256",
    }),
}


def _integer(value: object, label: str, *, minimum: int = 0,
             maximum: int = MAX_NS, serialized: bool = False) -> int:
    if serialized:
        if type(value) is not str or not value or (value.startswith("0") and value != "0"):
            raise ValueError(f"invalid {label}")
        if value.startswith("-"):
            digits = value[1:]
            if not digits or not digits.isascii() or not digits.isdecimal() or digits.startswith("0"):
                raise ValueError(f"invalid {label}")
        elif not value.isascii() or not value.isdecimal():
            raise ValueError(f"invalid {label}")
        try:
            value = int(value)
        except ValueError as exc:
            raise ValueError(f"invalid {label}") from exc
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"invalid {label}")
    return value


def _digest(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        raise ValueError(f"invalid {label}")
    return value


def _number(value: object, label: str) -> float:
    if type(value) is not str:
        raise ValueError(f"invalid {label}")
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc
    if not math.isfinite(result):
        raise ValueError(f"invalid {label}")
    return result


def _journal(rows: object, *, session_id: str, events: frozenset[str]) -> list[dict]:
    if type(rows) is not list or not rows:
        raise ValueError("missing diagnostic journal")
    pid = None
    last_steady_ns = 0
    for sequence, row in enumerate(rows, 1):
        if type(row) is not dict or type(row.get("schema")) is not int or row["schema"] != 1:
            raise ValueError("invalid diagnostic schema")
        if row.get("session") != session_id:
            raise ValueError("diagnostic session mismatch")
        current_pid = _integer(row.get("pid"), "diagnostic pid", minimum=1)
        if pid is None:
            pid = current_pid
        elif current_pid != pid:
            raise ValueError("diagnostic pid changed")
        if _integer(row.get("sequence"), "diagnostic sequence", minimum=1) != sequence:
            raise ValueError("diagnostic sequence gap or reorder")
        steady_ns = _integer(row.get("event_steady_ns"), "diagnostic clock", minimum=1)
        if steady_ns < last_steady_ns:
            raise ValueError("diagnostic clock regressed")
        last_steady_ns = steady_ns
        if type(row.get("event")) is not str or row["event"] not in events:
            raise ValueError("unknown diagnostic event")
        if row.keys() != _TRACE_CORE | _EVENT_FIELDS[row["event"]]:
            raise ValueError("unexpected diagnostic event fields")
        if any(type(row[key]) is not str for key in _EVENT_FIELDS[row["event"]]):
            raise ValueError("invalid diagnostic event field type")
    return rows


def _bridge(rows: object, *, run_id: str, session_id: str,
            source_mode: str) -> list[dict]:
    if type(rows) is not list or not rows:
        raise ValueError("missing bridge journal")
    pid = None
    last_steady_ns = 0
    for sequence, row in enumerate(rows, 1):
        if (type(row) is not dict or row.keys() != _BRIDGE_KEYS
                or type(row["schema"]) is not int or row["schema"] != 1):
            raise ValueError("invalid bridge record fields")
        if row["run_id"] != run_id or row["session"] != session_id:
            raise ValueError("bridge run or session mismatch")
        current_pid = _integer(row["pid"], "bridge pid", minimum=1)
        if pid is None:
            pid = current_pid
        elif current_pid != pid:
            raise ValueError("bridge pid changed")
        if _integer(row["sequence"], "bridge sequence", minimum=1) != sequence:
            raise ValueError("bridge sequence gap or reorder")
        steady_ns = _integer(row["event_steady_ns"], "bridge clock", minimum=1)
        if steady_ns < last_steady_ns:
            raise ValueError("bridge clock regressed")
        last_steady_ns = steady_ns
        if type(row["kind"]) is not str or row["kind"] not in _SOURCE:
            raise ValueError("unattested bridge source type")
        if source_mode == "candidate":
            if row["source"] != _SOURCE[row["kind"]] or row["truth_used"] is not False:
                raise ValueError("truth or unhealthy source")
            _digest(row["source_profile_sha256"], "bridge source profile")
        elif source_mode == "unattested_cdr":
            expected = ("unattested_ego_server" if row["kind"] == "position_command"
                        else "unattested_socket")
            if (row["source"] != expected or row["source_profile_sha256"] is not None
                    or row["truth_used"] != "unknown"):
                raise ValueError("unattested bridge source mislabeled")
        else:
            raise ValueError("unknown bridge source mode")
        _digest(row["message_sha256"], "bridge message digest")
        _integer(row["sample_ns"], "bridge sample time")
    return rows


def _one_matching(rows: list[dict], label: str, predicate) -> dict:
    matches = [row for row in rows if predicate(row)]
    if len(matches) != 1:
        raise ValueError(f"missing or ambiguous {label} record")
    return matches[0]


def _source(rows: list[dict], *, kind: str, digest: str, sample_ns: int) -> dict:
    matches = [row for row in rows if row["kind"] == kind
               and row["message_sha256"] == digest and row["sample_ns"] == sample_ns]
    if len(matches) != 1:
        raise ValueError(f"missing or ambiguous {kind} source")
    return matches[0]


def _field_int(row: dict, key: str, *, minimum: int = 0, maximum: int = MAX_NS) -> int:
    return _integer(row.get(key), key, minimum=minimum, maximum=maximum, serialized=True)


def _field_digest(row: dict, key: str) -> str:
    return _digest(row.get(key), key)


def _check_planner_counters(rows: list[dict]) -> None:
    odom_sequence = 0
    depth_receive_sequence = 0
    map_revision = 0
    applied_depth_sequence = 0
    depth_receipts = {}
    applied_receipts = set()
    for row in rows:
        event = row["event"]
        if event == "fsm_odometry_received":
            odom_sequence += 1
            if _field_int(row, "odom_sequence", minimum=1) != odom_sequence:
                raise ValueError("odometry source sequence gap or reorder")
        elif event in ("depth_pose_received", "depth_odom_received"):
            depth_receive_sequence += 1
            if _field_int(row, "receive_sequence", minimum=1) != depth_receive_sequence:
                raise ValueError("depth receive sequence gap or reorder")
            depth_receipts[depth_receive_sequence] = row
        elif event == "map_depth_applied":
            map_revision += 1
            applied_depth_sequence += 1
            if (_field_int(row, "revision", minimum=1) != map_revision
                    or _field_int(row, "depth_sequence", minimum=1)
                    != applied_depth_sequence):
                raise ValueError("map revision or applied-depth sequence gap")
            receive_sequence = _field_int(row, "receive_sequence", minimum=1)
            receipt = depth_receipts.get(receive_sequence)
            if (receipt is None or receive_sequence in applied_receipts
                    or receipt["event"] != "depth_pose_received"
                    or receipt["pending_for_apply"] != "true"
                    or row["pose_kind"] != "pose_stamped"
                    or any(row[map_key] != receipt[receipt_key]
                           for map_key, receipt_key in (
                               ("image_sha256", "image_sha256"),
                               ("pose_sha256", "pose_sha256"),
                               ("image_stamp_ns", "image_stamp_ns"),
                               ("pose_stamp_ns", "pose_stamp_ns")))):
                raise ValueError("map application lacks a matching pending depth receipt")
            applied_receipts.add(receive_sequence)


def _reconcile_diagnostics(bridge_events: list[dict], planner_events: list[dict],
                           server_events: list[dict], *, run_id: str, session_id: str,
                           source_mode: str) -> dict:
    """Match one unambiguous causal chain, with qualification hard-coded false."""
    if type(run_id) is not str or not run_id or type(session_id) is not str or not session_id:
        raise ValueError("run and session required")
    bridge = _bridge(bridge_events, run_id=run_id, session_id=session_id,
                     source_mode=source_mode)
    planner = _journal(planner_events, session_id=session_id, events=_PLANNER_EVENTS)
    server = _journal(server_events, session_id=session_id, events=_SERVER_EVENTS)
    if len({bridge[0]["pid"], planner[0]["pid"], server[0]["pid"]}) != 3:
        raise ValueError("bridge/planner/server process identity ambiguous")
    if any(row["event"] == "map_cloud_applied" for row in planner):
        raise ValueError("cloud map mutation has no source proof")
    if any(row["event"] == "depth_odom_received" for row in planner):
        raise ValueError("depth odometry extrinsic is unbound")
    _check_planner_counters(planner)
    plan_ids = [_field_int(row, "trajectory_id", minimum=1, maximum=INT_MAX)
                for row in planner if row["event"] == "plan_published"]
    if len(plan_ids) != len(set(plan_ids)):
        raise ValueError("duplicate trajectory id in planner session")

    bridge_commands = [row for row in bridge if row["kind"] == "position_command"]
    if not bridge_commands:
        raise ValueError("missing bridge command")
    command_source = bridge_commands[-1]
    command = _one_matching(
        server, "server_command_published",
        lambda row: row["event"] == "server_command_published"
        and row.get("command_sha256") == command_source["message_sha256"]
        and row.get("command_stamp_ns") == str(command_source["sample_ns"]))
    bspline = _one_matching(
        server, "server_bspline_received",
        lambda row: row["event"] == "server_bspline_received"
        and row.get("bspline_sha256") == command.get("bspline_sha256"))
    plan = _one_matching(
        planner, "plan_published",
        lambda row: row["event"] == "plan_published"
        and row.get("bspline_sha256") == bspline.get("bspline_sha256"))
    applied = _one_matching(
        planner, "map_depth_applied",
        lambda row: row["event"] == "map_depth_applied"
        and row.get("revision") == plan.get("map_before_revision"))
    depth = _one_matching(
        planner, "depth_pose_received",
        lambda row: row["event"] == "depth_pose_received"
        and row.get("receive_sequence") == applied.get("receive_sequence"))
    if depth.get("pending_for_apply") != "true":
        raise ValueError("depth was not pending for map application")
    odom = _one_matching(
        planner, "fsm_odometry_received",
        lambda row: row["event"] == "fsm_odometry_received"
        and row.get("odom_sequence") == plan.get("available_odom_sequence"))
    if not (odom["sequence"] < plan["sequence"]
            and depth["sequence"] < applied["sequence"] < plan["sequence"]
            and bspline["sequence"] < command["sequence"]):
        raise ValueError("map or plan event order invalid")

    odom_digest = _field_digest(odom, "odom_sha256")
    odom_stamp = _field_int(odom, "stamp_ns")
    odom_source = _source(bridge, kind="odometry", digest=odom_digest, sample_ns=odom_stamp)
    image_digest = _field_digest(depth, "image_sha256")
    pose_digest = _field_digest(depth, "pose_sha256")
    image_stamp = _field_int(depth, "image_stamp_ns")
    pose_stamp = _field_int(depth, "pose_stamp_ns")
    image_source = _source(bridge, kind="depth", digest=image_digest, sample_ns=image_stamp)
    pose_source = _source(bridge, kind="camera_pose", digest=pose_digest, sample_ns=pose_stamp)
    if image_source["source_profile_sha256"] != pose_source["source_profile_sha256"]:
        raise ValueError("camera source profile mismatch")
    if (odom_source["event_steady_ns"] > odom["event_steady_ns"]
            or image_source["event_steady_ns"] > depth["event_steady_ns"]
            or pose_source["event_steady_ns"] > depth["event_steady_ns"]):
        raise ValueError("source published after diagnostic receiver")
    odom_receive_ns = _field_int(odom, "receive_node_ns")
    depth_receive_ns = _field_int(depth, "receive_node_ns")
    map_apply_ns = _field_int(applied, "map_apply_node_ns")
    plan_publish_ns = _field_int(plan, "plan_publish_node_ns")
    if (odom_stamp > odom_receive_ns or image_stamp > depth_receive_ns
            or pose_stamp > depth_receive_ns or depth_receive_ns > map_apply_ns
            or map_apply_ns > plan_publish_ns or odom_receive_ns > plan_publish_ns):
        raise ValueError("node clock or source timestamp order invalid")

    revision = _field_int(applied, "revision", minimum=1)
    receive_sequence = _field_int(depth, "receive_sequence", minimum=1)
    if (_field_int(applied, "receive_sequence", minimum=1) != receive_sequence
            or _field_int(plan, "map_depth_receive_sequence", minimum=1) != receive_sequence
            or _field_int(plan, "map_before_revision", minimum=1) != revision
            or _field_int(plan, "map_after_revision", minimum=1) != revision
            or _field_int(plan, "map_depth_sequence", minimum=1)
            != _field_int(applied, "depth_sequence", minimum=1)
            or _field_int(plan, "map_cloud_sequence") != 0):
        raise ValueError("map revision or source sequence mismatch")
    if (applied.get("pose_kind") != "pose_stamped"
            or plan.get("map_pose_kind") != "pose_stamped"
            or any(_field_digest(row, image_key) != image_digest
                   or _field_digest(row, pose_key) != pose_digest
                   or _field_int(row, stamp_key) != image_stamp
                   or _field_int(row, pose_stamp_key) != pose_stamp
                   for row, image_key, pose_key, stamp_key, pose_stamp_key in (
                       (applied, "image_sha256", "pose_sha256", "image_stamp_ns", "pose_stamp_ns"),
                       (plan, "map_image_sha256", "map_pose_sha256",
                        "map_image_stamp_ns", "map_pose_stamp_ns")))):
        raise ValueError("map depth/pose source mismatch")
    if (_field_int(plan, "available_odom_sequence", minimum=1)
            != _field_int(odom, "odom_sequence", minimum=1)
            or _field_digest(plan, "available_odom_sha256") != odom_digest
            or _field_int(plan, "available_odom_stamp_ns") != odom_stamp):
        raise ValueError("plan odometry source mismatch")

    trajectory_id = _field_int(plan, "trajectory_id", minimum=1, maximum=INT_MAX)
    start_time_ns = _field_int(plan, "start_time_ns")
    bspline_digest = _field_digest(plan, "bspline_sha256")
    for row in (bspline, command):
        if (_field_int(row, "raw_trajectory_id", minimum=1, maximum=INT_MAX)
                != trajectory_id or _field_int(row, "stored_trajectory_id", minimum=1,
                                                maximum=INT_MAX) != trajectory_id
                or _field_digest(row, "bspline_sha256") != bspline_digest):
            raise ValueError("trajectory identity narrowed or mismatched")
    if (_field_int(command, "emitted_trajectory_id", minimum=1, maximum=INT_MAX)
            != trajectory_id or _field_int(bspline, "start_time_ns") != start_time_ns):
        raise ValueError("trajectory identity or start time mismatch")
    if plan["event_steady_ns"] > bspline["event_steady_ns"]:
        raise ValueError("B-spline arrived before planner publication")
    if bspline["event_steady_ns"] > command["event_steady_ns"]:
        raise ValueError("command published before B-spline arrival")

    command_digest = _field_digest(command, "command_sha256")
    command_stamp = _field_int(command, "command_stamp_ns")
    command_source = _source(bridge, kind="position_command", digest=command_digest,
                             sample_ns=command_stamp)
    if command_source["event_steady_ns"] < command["event_steady_ns"]:
        raise ValueError("command source received before server publication")
    origin = plan.get("start_origin")
    parent = _field_int(plan, "parent_trajectory_id", maximum=INT_MAX)
    parent_start_ns = _field_int(plan, "parent_start_time_ns", minimum=-1)
    parent_sample_s = _number(plan.get("parent_sample_s"), "parent sample")
    if origin == "odometry":
        if (parent, parent_start_ns, parent_sample_s) != (0, -1, -1.0):
            raise ValueError("odometry start has parent trajectory")
    elif origin == "previous_trajectory":
        parents = [row for row in planner if row["event"] == "plan_published"
                   and row["sequence"] < plan["sequence"]
                   and _field_int(row, "trajectory_id", minimum=1, maximum=INT_MAX) == parent]
        if (len(parents) != 1 or parent == trajectory_id or parent_sample_s < 0
                or _field_int(parents[0], "start_time_ns") != parent_start_ns):
            raise ValueError("parent trajectory lineage missing")
    else:
        raise ValueError("unknown start state origin")
    for key in ("start_x", "start_y", "start_z", "start_vx", "start_vy", "start_vz"):
        _number(plan.get(key), key)
    bridge_before_command = bridge[:command_source["sequence"] - 1]
    current_observation_match = all(
        max((row for row in bridge_before_command if row["kind"] == kind),
            key=lambda row: row["sequence"])["sequence"] == source["sequence"]
        for kind, source in (("odometry", odom_source), ("depth", image_source),
                             ("camera_pose", pose_source))
    )
    return {
        "identity_match": True,
        "current_observation_match": current_observation_match,
        "run_id": run_id,
        "session_id": session_id,
        "trajectory_id": trajectory_id,
        "map_revision": revision,
        "depth_sha256": image_digest,
        "camera_pose_sha256": pose_digest,
        "available_odom_sha256": odom_digest,
        "command_sha256": command_digest,
        "start_state_origin": origin,
        "parent_trajectory_id": parent,
        "runtime_source_verified": False,
        "clock_domain_verified": False,
        "planner_numerical_parity_verified": False,
        "teacher_qualified": False,
    }


def reconcile_diagnostics(bridge_events: list[dict], planner_events: list[dict],
                          server_events: list[dict], *, run_id: str,
                          session_id: str) -> dict:
    """Preserve the original proposed source-candidate contract."""
    return _reconcile_diagnostics(bridge_events, planner_events, server_events,
                                  run_id=run_id, session_id=session_id,
                                  source_mode="candidate")
