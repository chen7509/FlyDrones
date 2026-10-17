"""Read-only PX4 DDS source prerequisite; never certifies a built/live bridge."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

_BASE_SHA = "7e9c730d45b22af92acfebbb81cb5de4e4a69ac0ca46b012b71ed8fa5c89cbc0"
_MESSAGE_SHA = "44cba4424c224753b8249729e9bf7e530d0b34e04d5299fcf94f2677c8f50bd5"
_STATUS_TOPIC = "/fmu/out/estimator_status"
_STATUS_TYPE = "px4_msgs::msg::EstimatorStatus"
_ANCHOR = (b"  - topic: /fmu/out/estimator_status_flags\n"
           b"    type: px4_msgs::msg::EstimatorStatusFlags\n"
           b"    rate_limit: 5.\n")
_ADDITION = (b"  - topic: /fmu/out/estimator_status\n"
             b"    type: px4_msgs::msg::EstimatorStatus\n"
             b"    rate_limit: 20.\n")
_NO_AUTHORITY = {
    "firmware_compiled_verified": False,
    "live_source_authenticated": False,
    "camera_calibration_qualified": False,
    "fusion_qualified": False,
    "training_eligible": False,
}


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader: _UniqueLoader, node: yaml.MappingNode) -> dict:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise ValueError("unhashable YAML mapping key") from exc
        if duplicate:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _publications(data: bytes) -> dict[str, dict]:
    parsed = yaml.load(data, Loader=_UniqueLoader)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("publications"), list):
        raise ValueError("PX4 DDS publications invalid")
    topics = {}
    for entry in parsed["publications"]:
        if (not isinstance(entry, dict) or type(entry.get("topic")) is not str
                or type(entry.get("type")) is not str):
            raise ValueError("PX4 DDS publication invalid")
        topic = entry["topic"]
        if topic in topics:
            raise ValueError(f"duplicate PX4 DDS publication: {topic}")
        topics[topic] = entry
    return topics


def audit_status_transport(base_yaml: bytes, candidate_yaml: bytes,
                           px4_msg: bytes, ros_msg: bytes) -> dict:
    """Inspect only the fixed source and candidate, with no runtime authority."""
    result = {
        "schema": "flydrones.px4_estimator_status_transport_preflight.v1",
        "pinned_px4_commit": "d6f12ad1c4f70ad3230afd7d86e971421e02fef4",
        "base_sha256": hashlib.sha256(base_yaml).hexdigest(),
        "px4_msg_sha256": hashlib.sha256(px4_msg).hexdigest(),
        "ros_msg_sha256": hashlib.sha256(ros_msg).hexdigest(),
        "ros_msg_exact": ros_msg == px4_msg and hashlib.sha256(px4_msg).hexdigest() == _MESSAGE_SHA,
        "base_status_published": False,
        "candidate_status_rate_hz": None,
        "source_candidate_ready": False,
        "missing": [],
        "errors": [],
        **_NO_AUTHORITY,
    }
    if result["base_sha256"] != _BASE_SHA:
        result["errors"].append("pinned_base_hash_mismatch")
        return result
    if result["px4_msg_sha256"] != _MESSAGE_SHA:
        result["errors"].append("pinned_estimator_message_mismatch")
        return result
    if b"uint32 filter_fault_flags" not in px4_msg:
        result["errors"].append("filter_fault_field_missing")
        return result
    if not result["ros_msg_exact"]:
        result["errors"].append("ros_estimator_message_mismatch")
    try:
        base_topics = _publications(base_yaml)
        candidate_topics = _publications(candidate_yaml)
    except (ValueError, yaml.YAMLError) as exc:
        result["errors"].append(f"dds_yaml_invalid: {exc}")
        return result
    required_existing = {
        "/fmu/out/vehicle_local_position": "px4_msgs::msg::VehicleLocalPosition",
        "/fmu/out/vehicle_attitude": "px4_msgs::msg::VehicleAttitude",
        "/fmu/out/vehicle_odometry": "px4_msgs::msg::VehicleOdometry",
        "/fmu/out/estimator_status_flags": "px4_msgs::msg::EstimatorStatusFlags",
    }
    if any(base_topics.get(topic, {}).get("type") != message
           for topic, message in required_existing.items()):
        result["errors"].append("existing_capture_publication_missing")
        return result
    result["base_status_published"] = _STATUS_TOPIC in base_topics
    if result["base_status_published"]:
        result["errors"].append("pinned_base_status_unexpected")
        return result
    result["missing"] = [_STATUS_TOPIC]
    if candidate_yaml == base_yaml:
        return result
    if base_yaml.count(_ANCHOR) != 1 or candidate_yaml != base_yaml.replace(
            _ANCHOR, _ANCHOR + _ADDITION):
        result["errors"].append("candidate_not_single_declared_addition")
        return result
    status = candidate_topics.get(_STATUS_TOPIC)
    if status != {"topic": _STATUS_TOPIC, "type": _STATUS_TYPE, "rate_limit": 20.0}:
        result["errors"].append("candidate_status_mapping_invalid")
        return result
    result["candidate_status_rate_hz"] = 20.0
    result["source_candidate_ready"] = not result["errors"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "candidate", "px4-msg", "ros-msg"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    paths = (args.base, args.candidate, args.px4_msg, args.ros_msg)
    try:
        if any(path.is_symlink() or not path.is_file() for path in paths):
            raise ValueError("source path missing or symlink")
        result = audit_status_transport(*(path.read_bytes() for path in paths))
    except (OSError, ValueError) as exc:
        result = {"source_candidate_ready": False, "training_eligible": False,
                  "errors": [str(exc)]}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
