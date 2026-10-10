"""Exact, offline-only profile for a future unarmed PX4 odometry source diagnostic."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

PX4_COMMIT = "d6f12ad1c4f70ad3230afd7d86e971421e02fef4"
LOGGER_SOURCE_SHA256 = "33c1cd7c55dc81d4fa53153b7f269401b67c7f6edc929707ec536203096bcfe5"
TOPICS_SHA256 = "0bb9a3d9b57c6a73c73e8fee75569b9e690857654c4631b6f6cd5b6654328994"
TOPIC_LINES = (
    "vehicle_odometry 0 0",
    "vehicle_status 100 0",
    "vehicle_attitude 20 0",
    "vehicle_local_position 20 0",
    "estimator_status 20 0",
    "estimator_selector_status 100 0",
    "sensor_combined 0 0",
    "timesync_status 1000 0",
    "logger_status 100 0",
    "failsafe_flags 100 0",
)
TOPICS_BYTES = ("\n".join(TOPIC_LINES) + "\n").encode("ascii")
DECLARATION = {
    "schema": "flydrones.px4_logger_diagnostic.v1",
    "profile_id": "source-diagnostic-v1",
    "px4_commit": PX4_COMMIT,
    "logger_source_sha256": LOGGER_SOURCE_SHA256,
    "sdlog_profile": 0,
    "diagnostic_only": True,
    "topics_sha256": TOPICS_SHA256,
}
_TOPIC_LINE = re.compile(r"[a-z][a-z0-9_]* [0-9]+ [0-9]+\Z")


@dataclass(frozen=True)
class LoggerProfileAudit:
    reason: str
    logger_file_candidate: bool = False
    runtime_topic_selection_verified: bool = False
    dds_ulog_parity_verified: bool = False
    source_authenticated: bool = False
    eligible_for_training: bool = False


def audit_profile(topics: bytes, declaration: object) -> LoggerProfileAudit:
    """Validate one exact candidate; never qualify actual PX4, DDS, or training."""
    if type(declaration) is not dict or declaration.keys() != DECLARATION.keys():
        return LoggerProfileAudit("declaration_schema")
    if any(type(declaration[key]) is not type(value) or declaration[key] != value
           for key, value in DECLARATION.items()):
        return LoggerProfileAudit("declaration_value")
    if type(topics) is not bytes:
        return LoggerProfileAudit("topic_bytes_required")
    if not topics.endswith(b"\n") or b"\r" in topics or len(topics) != 230:
        return LoggerProfileAudit("topics_line_endings_or_length")
    try:
        lines = topics.decode("ascii").split("\n")[:-1]
    except UnicodeDecodeError:
        return LoggerProfileAudit("topics_not_ascii")
    if (len(lines) != len(TOPIC_LINES)
            or any(len(line) >= 80 or _TOPIC_LINE.fullmatch(line) is None for line in lines)):
        return LoggerProfileAudit("topics_syntax")
    parts = [line.split(" ") for line in lines]
    if (len({part[0] for part in parts}) != len(parts)
            or any(int(part[1]) > 65535 or int(part[2]) != 0 for part in parts)):
        return LoggerProfileAudit("topics_duplicate_or_range")
    if topics != TOPICS_BYTES or hashlib.sha256(topics).hexdigest() != TOPICS_SHA256:
        return LoggerProfileAudit("topics_not_fixed")
    return LoggerProfileAudit("logger_file_candidate_only", logger_file_candidate=True)
