"""One-shot, read-only ROS graph gate for the synthetic XRCE diagnostic."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

TOPIC = "/fmu/out/vehicle_odometry"
ROS_TYPE = "px4_msgs/msg/VehicleOdometry"
COLLECTOR = "flydrones_px4_odometry_source"


def qos_acceptable(result: tuple) -> bool:
    """Humble returns (compatibility, reason); WARNING leaves an uncertainty."""
    return (isinstance(result, tuple) and len(result) == 2
            and getattr(result[0], "name", None) in ("OK", "WARNING")
            and isinstance(result[1], str))


def main(marker: Path, proof: Path) -> None:
    if marker.exists() or proof.exists():
        raise FileExistsError("graph evidence already exists")
    import rclpy
    from rclpy.qos import qos_check_compatible

    rclpy.init()
    node = rclpy.create_node("flydrones_xrce_graph_observer")
    started = time.monotonic_ns()
    result = {"schema": "flydrones.xrce_graph_gate.v1", "topic": TOPIC,
              "ros_type": ROS_TYPE, "matched": False,
              "synthetic_only": True, "px4_source_authenticated": False,
              "fusion_qualified": False, "polls": 0}
    stable_key = None
    stable_polls = 0
    try:
        while time.monotonic_ns() - started < 8_000_000_000:
            publishers = node.get_publishers_info_by_topic(TOPIC)
            subscribers = node.get_subscriptions_info_by_topic(TOPIC)
            result["polls"] += 1
            result["last_counts"] = {"publishers": len(publishers),
                                     "subscribers": len(subscribers)}
            if len(publishers) == 1 and len(subscribers) == 1:
                publisher, subscriber = publishers[0], subscribers[0]
                compatibility = qos_check_compatible(publisher.qos_profile,
                                                       subscriber.qos_profile)
                if (publisher.topic_type == ROS_TYPE
                        and subscriber.topic_type == ROS_TYPE
                        and subscriber.node_name == COLLECTOR
                        and qos_acceptable(compatibility)):
                    publisher_gid = bytes(publisher.endpoint_gid).hex()
                    subscriber_gid = bytes(subscriber.endpoint_gid).hex()
                    key = (publisher_gid, subscriber_gid)
                    stable_polls = stable_polls + 1 if key == stable_key else 1
                    stable_key = key
                    result["stable_polls"] = stable_polls
                    result["publisher_gid_hex"] = publisher_gid
                    result["subscriber_gid_hex"] = subscriber_gid
                    result["publisher_node"] = publisher.node_name
                    result["subscriber_node"] = subscriber.node_name
                    result["qos_compatibility"] = compatibility[0].name
                    result["qos_reason"] = compatibility[1]
                    if stable_polls >= 5:
                        result["matched"] = True
                        result["matched_monotonic_ns"] = time.monotonic_ns()
                        break
                else:
                    stable_key = None
                    stable_polls = 0
                    result["stable_polls"] = 0
                    result["last_mismatch"] = {
                        "publisher_type": publisher.topic_type,
                        "subscriber_type": subscriber.topic_type,
                        "subscriber_node": subscriber.node_name,
                        "qos": str(compatibility[0]),
                        "qos_reason": compatibility[1],
                    }
            else:
                stable_key = None
                stable_polls = 0
                result["stable_polls"] = 0
            time.sleep(0.1)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    result["ended_monotonic_ns"] = time.monotonic_ns()
    with proof.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2)
    if not result["matched"]:
        raise SystemExit("graph endpoints not qualified within 8 seconds")
    with marker.open("x", encoding="ascii") as file:
        file.write("ready\n")
    print(json.dumps({"matched": True, "publisher_gid_hex":
                      result["publisher_gid_hex"], "polls": result["polls"]}))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: graph_wait.py READY_MARKER PROOF_JSON")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
