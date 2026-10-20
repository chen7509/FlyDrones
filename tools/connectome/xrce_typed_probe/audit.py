"""Audit one owned synthetic XRCE session and typed ROS 2 callback."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

from frozen_cdr import ARCHIVE_SHA, BODY_SHA, FULL_CDR_SHA, MEMBER, MESSAGE_BLOB

CLIENT_KEY = "0xF1D0D017"
IMAGE = "sha256:a4dae62b38bc01a01d084be7b68db83ec804fef7673604e1a9c986a4baa88a6a"
AGENT_SHA = "3918279bd7c3ae3a76a5338bd1b31a52e334c4e6c1d648141b0adca65a2d6d8e"
CLIENT_SHA = "286094c306ff9254896253a4eee454fe66dba2664d4c70ceb218db0a54bd0105"
COLLECTOR_SHA = "31ad3958028660bf4ed468ddcbd25e7d5ca3e994b7729e4538ebe383a46ecf7f"
MIN_FREE = 1610612736
SAMPLE_FIELDS = (
    "px4_publication_us", "px4_sample_us", "pose_frame", "velocity_frame",
    "reset_counter", "quality", "position_ned_m", "q_body_to_ned_wxyz",
    "velocity_ned_m_s", "omega_body_frd_rad_s", "position_variance_m2",
    "orientation_variance_rad2", "velocity_variance_m2_s2",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> list[dict]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("journal path or size refused")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def checked_preflight(preflight: dict, directory: Path) -> None:
    hashes = preflight.get("local_hashes", {})
    if (preflight.get("qualified") is not True
            or preflight.get("build_success") is not True
            or preflight.get("abi_qualified") is not True
            or preflight.get("minimum_bytes") != MIN_FREE
            or type(preflight.get("host_available_bytes")) is not int
            or preflight["host_available_bytes"] < MIN_FREE
            or hashes.get("collector") != COLLECTOR_SHA
            or hashes.get("body") != BODY_SHA
            or hashes.get("inside_source") != sha((directory / "inside.py").read_bytes())):
        raise ValueError("frozen runtime preflight mismatch")
    for name, expected in (("agent", AGENT_SHA), ("client", CLIENT_SHA)):
        record = preflight.get(name, {})
        if (record.get("returncode") != 0
                or record.get("args", [])[:5] != ["wsl", "-d", "Ubuntu", "--", "sha256sum"]
                or not record.get("stdout", "").startswith(expected + "  ")):
            raise ValueError(f"{name} binary identity mismatch")
    image = preflight.get("image", {})
    containers = preflight.get("containers", {})
    if (image.get("returncode") != 0 or image.get("stdout", "").strip() != IMAGE
            or image.get("args", [])[:4] != ["docker", "image", "inspect", IMAGE]
            or containers.get("returncode") != 0
            or containers.get("stdout", "").strip()
            or containers.get("args", [])[:2] != ["docker", "ps"]):
        raise ValueError("Docker image or pre-run occupancy mismatch")


def checked_cleanup(runtime: dict, inside: dict) -> None:
    for name in ("client", "graph", "collector", "agent"):
        if f"{name}_cleanup_error" in inside:
            raise ValueError(f"{name} cleanup failed")
    if inside.get("agent_exit") != -15 or inside.get("agent_cleanup") != "SIGTERM":
        raise ValueError("Agent cleanup not observed")
    for name in ("listed_after", "owned_after"):
        record = runtime.get(name, {})
        if (record.get("returncode") != 0 or record.get("stdout", "") != ""
                or record.get("args", [])[:2] != ["docker", "ps"]):
            raise ValueError(f"{name} query failed or found owned container")
    cleanup = runtime.get("cleanup")
    if cleanup is not None and cleanup.get("returncode") != 0:
        raise ValueError("Docker cleanup failed")
    command = runtime.get("command", [])
    if (command[:7] != ["wsl", "-d", "Ubuntu", "--", "docker", "run", "--rm"]
            or "--network" not in command
            or command[command.index("--network") + 1] != "none"
            or IMAGE not in command
            or runtime.get("ended_unix_ns", 0) - runtime.get("started_unix_ns", 0)
            > 30_000_000_000):
        raise ValueError("runtime command or deadline mismatch")


def audit(directory: Path, archive: Path, run_id: str = "synthetic-xrce-v1",
          rmw: str = "rmw_cyclonedds_cpp", require_graph: bool = False) -> dict:
    if sha(archive.read_bytes()) != ARCHIVE_SHA:
        raise ValueError("source archive hash mismatch")
    with zipfile.ZipFile(archive) as source:
        if source.testzip() is not None:
            raise ValueError("source archive CRC mismatch")
        original = [json.loads(line) for line in source.read(MEMBER).splitlines()]
    if len(original) != 2 or original[1].get("status") != "complete":
        raise ValueError("source sample incomplete")
    source_sample = original[0]
    journal_path = directory / "xrce-synthetic-v2.jsonl"
    actual = rows(journal_path)
    if (len(actual) != 2 or actual[0].get("kind") != "sample"
            or actual[0].get("schema") != "flydrones.px4_ros2_odometry_cdr.v2"
            or actual[0].get("run_id") != run_id
            or actual[0].get("journal_sequence") != 1
            or actual[1].get("kind") != "finish"
            or actual[1].get("run_id") != run_id
            or actual[1].get("status") != "complete"
            or actual[1].get("samples") != 1):
        raise ValueError("callback cardinality or identity mismatch")
    sample = actual[0]
    for key in ("topic", "ros_type", "message_blob_sha", *SAMPLE_FIELDS):
        if sample.get(key) != source_sample.get(key):
            raise ValueError(f"callback field mismatch: {key}")
    cdr = bytes.fromhex(sample["cdr_hex"])
    if (len(cdr) != 120 or cdr[:4] != b"\x00\x01\x00\x00"
            or sha(cdr) != FULL_CDR_SHA or sample.get("cdr_sha256") != FULL_CDR_SHA
            or sha(cdr[4:]) != BODY_SHA
            or sample.get("message_blob_sha") != MESSAGE_BLOB):
        raise ValueError("callback CDR mismatch")
    if (sample.get("rmw_implementation") != rmw
            or len(bytes.fromhex(sample.get("publisher_gid_hex", ""))) != 24
            or sample.get("rmw_source_timestamp_ns", 0) <= 0
            or sample.get("callback_steady_ns", 0) <= 0):
        raise ValueError("callback transport metadata missing")

    inside = load_json(directory / "inside-result.json")
    runtime = load_json(directory / "runtime-result.json")
    preflight = load_json(directory / "runtime-preflight.json")
    checked_preflight(preflight, directory)
    checked_cleanup(runtime, inside)
    if (not inside.get("completed")
            or not inside.get("agent_ready") or inside.get("client_exit") != 0
            or inside.get("collector_exit") != 0
            or inside.get("agent_cleanup") != "SIGTERM"
            or inside.get("px4_source_authenticated") is not False
            or inside.get("fusion_qualified") is not False
            or runtime.get("docker_exit") != 0 or runtime.get("timeout") is not False
            or runtime.get("owned_after", {}).get("stdout") != ""
            or runtime.get("px4_source_authenticated") is not False
            or runtime.get("fusion_qualified") is not False):
        raise ValueError("runtime lifecycle or qualification mismatch")
    client = load_json(directory / "client.log")
    if (client.get("session") is not True or client.get("entities") is not True
            or client.get("synthetic_sent") != 1
            or client.get("px4_source_authenticated") is not False):
        raise ValueError("XRCE client declaration mismatch")
    agent = (directory / "agent.log").read_text(encoding="utf-8")
    for marker in ("running...", "session established", "participant created",
                   "topic created", "publisher created", "datawriter created",
                   "session closed"):
        if agent.count(marker) != 1:
            raise ValueError(f"Agent evidence mismatch: {marker}")
    if agent.count(CLIENT_KEY) < 7:
        raise ValueError("Agent client key mismatch")
    if require_graph:
        graph = load_json(directory / "graph-proof.json")
        if (inside.get("graph_exit") != 0 or graph.get("matched") is not True
                or graph.get("stable_polls", 0) < 5
                or graph.get("last_counts") != {"publishers": 1, "subscribers": 1}
                or graph.get("topic") != "/fmu/out/vehicle_odometry"
                or graph.get("ros_type") != "px4_msgs/msg/VehicleOdometry"
                or graph.get("subscriber_node") != "flydrones_px4_odometry_source"
                or graph.get("qos_compatibility") != "OK"
                or graph.get("publisher_gid_hex") != sample["publisher_gid_hex"]
                or (directory / "graph-ready.txt").read_bytes() != b"ready\n"):
            raise ValueError("graph endpoint proof or callback GID mismatch")
        match = re.search(r"DataWriter\.cpp[^\n]*len: 116, data:\s*\n"
                          r"((?:[0-9a-fA-F]{4}: [^\n]+\n)+)", agent)
        if match is None:
            raise ValueError("Agent DDS write proof missing")
        written = bytes.fromhex(" ".join(line.split(":", 1)[1]
                                         for line in match.group(1).splitlines()))
        if len(written) != 116 or sha(written) != BODY_SHA:
            raise ValueError("Agent DDS write body mismatch")
    return {
        "schema": "flydrones.xrce_typed_synthetic_audit.v1",
        "journal_sha256": sha(journal_path.read_bytes()),
        "cdr_sha256": FULL_CDR_SHA,
        "source_archive_sha256": ARCHIVE_SHA,
        "client_key": CLIENT_KEY,
        "sample_count": 1,
        "fields_compared": len(SAMPLE_FIELDS),
        "graph_endpoint_verified": require_graph,
        "agent_dds_write_body_verified": require_graph,
        "typed_callback_verified": True,
        "owned_container_absent_on_queried_daemon": True,
        "runtime_daemon_identity_qualified": False,
        "synthetic_only": True,
        "px4_source_authenticated": False,
        "fusion_qualified": False,
        "eligible_for_live_capture": False,
    }


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4, 5, 6):
        raise SystemExit("usage: audit.py DIR ARCHIVE [RUN_ID [RMW [graph]]]")
    run_id = sys.argv[3] if len(sys.argv) == 4 else "synthetic-xrce-v1"
    if len(sys.argv) >= 4:
        run_id = sys.argv[3]
    rmw = sys.argv[4] if len(sys.argv) >= 5 else "rmw_cyclonedds_cpp"
    graph = len(sys.argv) == 6 and sys.argv[5] == "graph"
    if len(sys.argv) == 6 and not graph:
        raise ValueError("unknown graph option")
    print(json.dumps(audit(Path(sys.argv[1]), Path(sys.argv[2]), run_id,
                           rmw, graph), indent=2))
