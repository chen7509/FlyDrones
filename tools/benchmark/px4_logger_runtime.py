"""Stage the fixed diagnostic logger list in one owned PX4 SITL runtime.

This binds file bytes, not logger subscription or DDS source identity.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from tools.benchmark.capture_contract import read_declaration
from tools.connectome.audit_px4_logger_diagnostic import profile

PROFILE_NAME = "source-diagnostic-v1"
PROFILE_RELATIVE = Path("config/px4/source-diagnostic-v1")
RECEIPT_PROFILE = "disarmed-receipt-v2"
RECEIPT_TOPICS = b'vehicle_odometry 0 0\nvehicle_status 100 0\nvehicle_attitude 20 0\nvehicle_local_position 20 0\nestimator_status 20 0\nestimator_selector_status 100 0\nsensor_combined 0 0\ntimesync_status 1000 0\nlogger_status 100 0\nfailsafe_flags 100 0\nvehicle_visual_odometry 0 0\nactuator_armed 100 0\nestimator_status_flags 20 0\nestimator_aid_src_ev_pos 0 0\nestimator_aid_src_ev_vel 0 0\nestimator_aid_src_ev_hgt 0 0\n'
COPIED_RELATIVE = Path("etc/logging/logger_topics.txt")


def _stable_bytes(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("logger input missing, linked, or nonregular")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
        raise ValueError("logger input size or type invalid")
    data = path.read_bytes()
    after = path.stat()
    def identity(item):
        return (item.st_dev, item.st_ino, item.st_mode, item.st_size,
                item.st_mtime_ns, item.st_ctime_ns)
    if identity(before) != identity(after) or len(data) != before.st_size:
        raise ValueError("logger input changed during read")
    return data


def profile_record(source: Path) -> dict:
    source = Path(source)
    if not source.is_absolute() or source.is_symlink() or not source.is_dir():
        raise ValueError("absolute regular logger source directory required")
    topics_path, declaration_path = source / "logger_topics.txt", source / "profile.json"
    topics = _stable_bytes(topics_path, 1000)
    declaration_bytes = _stable_bytes(declaration_path, 4096)
    declaration = read_declaration(declaration_path)
    if declaration_bytes != _stable_bytes(declaration_path, 4096):
        raise ValueError("logger declaration changed during parse")
    selected = PROFILE_NAME
    if declaration.get("profile_id") == RECEIPT_PROFILE:
        expected = dict(schema="flydrones.px4_logger_disarmed_receipt.v2", profile_id=RECEIPT_PROFILE,
                        px4_commit="d6f12ad1c4f70ad3230afd7d86e971421e02fef4",
                        logger_source_sha256="33c1cd7c55dc81d4fa53153b7f269401b67c7f6edc929707ec536203096bcfe5",
                        sdlog_profile=0,diagnostic_only=True,topics_sha256=hashlib.sha256(RECEIPT_TOPICS).hexdigest())
        if declaration != expected or topics != RECEIPT_TOPICS:
            raise ValueError("disarmed receipt logger exact profile mismatch")
        selected = RECEIPT_PROFILE
    else:
        audit = profile.audit_profile(topics, declaration)
        if not audit.logger_file_candidate:
            raise ValueError("logger profile refused: " + audit.reason)
    return {
        "schema": "capture-px4-logger-profile-v1",
        "profile_id": selected,
        "source_paths": [str(topics_path), str(declaration_path)],
        "topics_sha256": hashlib.sha256(topics).hexdigest(),
        "declaration_sha256": hashlib.sha256(declaration_bytes).hexdigest(),
        "px4_environment_override": {"PX4_PARAM_SDLOG_PROFILE": "0"},
        "diagnostic_only": True,
        "runtime_topic_selection_verified": False,
        "dds_ulog_parity_verified": False,
        "source_authenticated": False,
    }


def stage_profile(record: dict, runtime: Path) -> dict:
    runtime = Path(runtime)
    if not runtime.is_absolute() or runtime.is_symlink() or not runtime.is_dir():
        raise ValueError("owned PX4 runtime must be an absolute regular directory")
    source = Path(record["source_paths"][0]).parent
    if profile_record(source) != record:
        raise ValueError("logger source changed before stage")
    topics = _stable_bytes(source / "logger_topics.txt", 1000)
    if hashlib.sha256(topics).hexdigest() != record["topics_sha256"]:
        raise ValueError("logger source changed before copy")
    folder = runtime / "etc/logging"
    for part in (runtime / "etc", folder):
        if part.is_symlink() or (part.exists() and not part.is_dir()):
            raise ValueError("owned logger directory linked or invalid")
        part.mkdir(exist_ok=True)
    target = runtime / COPIED_RELATIVE
    with target.open("xb") as stream:
        if stream.write(topics) != len(topics):
            raise OSError("short logger copy write")
        stream.flush()
        os.fsync(stream.fileno())
    copied = _stable_bytes(target, 1000)
    if copied != topics or hashlib.sha256(copied).hexdigest() != record["topics_sha256"]:
        raise ValueError("logger copy changed during stage")
    return {
        "schema": "capture-px4-logger-stage-v1",
        "source": record,
        "runtime_root": str(runtime),
        "copied_path": str(target),
        "copied_sha256": hashlib.sha256(copied).hexdigest(),
        "px4_environment_override": {"PX4_PARAM_SDLOG_PROFILE": "0"},
        "runtime_topic_selection_verified": False,
        "dds_ulog_parity_verified": False,
        "source_authenticated": False,
    }


def verify_profile(record: dict, staged: dict, runtime: Path) -> dict:
    runtime = Path(runtime)
    target = runtime / COPIED_RELATIVE
    if any(part.is_symlink() or not part.is_dir()
           for part in (runtime, runtime / "etc", runtime / "etc/logging")):
        raise ValueError("owned logger directory linked or invalid after stage")
    if (staged.get("schema") != "capture-px4-logger-stage-v1"
            or staged.get("source") != record
            or staged.get("runtime_root") != str(runtime)
            or staged.get("copied_path") != str(target)
            or staged.get("px4_environment_override") != {"PX4_PARAM_SDLOG_PROFILE": "0"}):
        raise ValueError("logger stage identity changed")
    if profile_record(Path(record["source_paths"][0]).parent) != record:
        raise ValueError("logger source changed after stage")
    if _stable_bytes(target, 1000) != _stable_bytes(Path(record["source_paths"][0]), 1000):
        raise ValueError("logger copy changed after stage")
    if hashlib.sha256(_stable_bytes(target, 1000)).hexdigest() != staged["copied_sha256"]:
        raise ValueError("logger copy hash changed after stage")
    return {"copy_stable": True, "runtime_topic_selection_verified": False,
            "dds_ulog_parity_verified": False, "source_authenticated": False}
