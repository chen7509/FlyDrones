"""Optional independent decode of retained EGO bridge CDR fields.

This is an offline format check, not ROS runtime or input-source attestation.
The strict command path accepts only the observed DDS four-byte zero alignment
suffix, retaining separate raw and canonical digests.
"""

from __future__ import annotations

import base64
import hashlib
import math
from importlib.metadata import version
from pathlib import Path
from zipfile import ZipFile

from tools.benchmark.ego_bridge_cdr_audit import audit_bridge_cdr_journal
from tools.benchmark.ego_bridge_cdr_journal import MAX_NS

POSITION_COMMAND_SHA256 = "9e0e570fa796d18ea4170c569491d1ba6a63daa78007d0d12c3b7b208c597944"
POSITION_COMMAND_MEMBER = "results/ego-causal-provenance-dev-1701/source/PositionCommand.msg"
ROSBAGS_VERSION = "0.11.5"
MESSAGE_TYPES = {
    "clock": "rosgraph_msgs/msg/Clock",
    "odometry": "nav_msgs/msg/Odometry",
    "trigger": "geometry_msgs/msg/PoseStamped",
    "camera_pose": "geometry_msgs/msg/PoseStamped",
    "depth": "sensor_msgs/msg/Image",
    "position_command": "quadrotor_msgs/msg/PositionCommand",
}


def _typestore():
    try:
        if version("rosbags") != ROSBAGS_VERSION:
            raise RuntimeError("wrong rosbags version for EGO CDR audit")
        from rosbags.typesys import Stores, get_types_from_msg, get_typestore
    except ImportError as exc:
        raise RuntimeError("rosbags 0.11.5 is required for EGO CDR audit") from exc
    archive_path = Path(__file__).resolve().parents[2] / "evidence/ego-causal-provenance-dev-1701.zip"
    with ZipFile(archive_path) as archive:
        definition = archive.read(POSITION_COMMAND_MEMBER)
    if hashlib.sha256(definition).hexdigest() != POSITION_COMMAND_SHA256:
        raise ValueError("pinned PositionCommand definition changed")
    store = get_typestore(Stores.ROS2_HUMBLE)
    store.register(get_types_from_msg(definition.decode("utf-8"), MESSAGE_TYPES["position_command"]))
    return store


def _stamp_ns(stamp) -> int:
    sec, nanosec = stamp.sec, stamp.nanosec
    if (type(sec) is not int or type(nanosec) is not int or sec < 0
            or not 0 <= nanosec < 1_000_000_000):
        raise ValueError("invalid CDR stamp")
    result = sec * 1_000_000_000 + nanosec
    if result > MAX_NS:
        raise ValueError("CDR stamp overflow")
    return result


def _validate_message(kind: str, message) -> int:
    if kind == "clock":
        return _stamp_ns(message.clock)
    stamp = _stamp_ns(message.header.stamp)
    if kind == "odometry":
        if message.header.frame_id != "world" or message.child_frame_id != "base_link":
            raise ValueError("CDR odometry frame mismatch")
    elif kind in ("trigger", "camera_pose"):
        if message.header.frame_id != "world":
            raise ValueError("CDR pose frame mismatch")
    elif kind == "depth":
        if (message.header.frame_id != "camera_optical" or message.encoding != "32FC1"
                or message.is_bigendian != 0 or message.height < 1 or message.width < 1
                or message.step != message.width * 4
                or len(message.data) != message.height * message.step):
            raise ValueError("CDR depth image geometry mismatch")
    elif kind == "position_command":
        numbers = (
            message.position.x, message.position.y, message.position.z,
            message.velocity.x, message.velocity.y, message.velocity.z,
            message.acceleration.x, message.acceleration.y, message.acceleration.z,
            message.yaw, message.yaw_dot, *message.kx, *message.kv,
        )
        if not all(math.isfinite(float(item)) for item in numbers):
            raise ValueError("nonfinite CDR position command")
    return stamp


def audit_ego_cdr_fields(rows: list[dict]) -> dict:
    """Check actual retained bytes against independently decoded fields."""
    audit_bridge_cdr_journal(rows)
    store = _typestore()
    decoded_rows = {row["message_sequence"]: row for row in rows
                    if row["phase"] == "command_decoded"}
    counts = {kind: 0 for kind in MESSAGE_TYPES}
    command_canonicalizations = {}
    for row in rows:
        if row["phase"] not in ("publish_intent", "command_received"):
            continue
        kind = row["kind"]
        raw = base64.b64decode(row["message_cdr_b64"], validate=True)
        if len(raw) > 8_000_000:
            raise ValueError("CDR payload too large")
        msgtype = MESSAGE_TYPES[kind]
        try:
            message = store.deserialize_cdr(raw, msgtype)
            canonical = bytes(store.serialize_cdr(message, msgtype))
        except Exception as exc:
            raise ValueError(f"invalid {kind} CDR") from exc
        padding = (-len(canonical)) % 4
        if canonical != raw and not (
                row["phase"] == "command_received" and kind == "position_command"
                and padding > 0 and raw == canonical + b"\x00" * padding):
            raise ValueError(f"noncanonical {kind} CDR")
        stamp = _validate_message(kind, message)
        if kind == "position_command":
            sequence = row["message_sequence"]
            command_canonicalizations[sequence] = {
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
                "padding_bytes": len(raw) - len(canonical),
            }
            metadata = decoded_rows[row["message_sequence"]]
            if (stamp != metadata["sample_ns"]
                    or message.trajectory_id != metadata["trajectory_id"]
                    or (message.trajectory_flag == 1) is not metadata["ready"]):
                raise ValueError("CDR command stamp, trajectory or ready mismatch")
        elif stamp != row["sample_ns"]:
            raise ValueError(f"CDR {kind} sample stamp mismatch")
        counts[kind] += 1
    missing = [kind for kind, count in counts.items() if count < 1]
    if missing:
        raise ValueError(f"missing required CDR kinds: {', '.join(missing)}")
    return {
        "message_count_by_kind": counts,
        "position_command_canonicalizations": command_canonicalizations,
        "position_command_definition_sha256": POSITION_COMMAND_SHA256,
        "rosbags_version": ROSBAGS_VERSION,
        "cdr_payload_fields_verified": True,
        "stamp_binding_verified": True,
        "ros_runtime_type_support_verified": False,
        "ros_topic_type_identity_verified": False,
        "source_attested": False,
        "planner_consumption_verified": False,
        "teacher_qualified": False,
    }
