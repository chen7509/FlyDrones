"""Offline unarmed ULog observations, with raw framing and decoded counts joined."""

from __future__ import annotations

import hashlib
import importlib.metadata
import struct
from pathlib import PurePosixPath

from tools.benchmark.audit_live_wire_study import _equal, _integer, _shape
from tools.benchmark.openvins_receiver_parity import _ObservedULogBuffer, validate_ulog_stream


def audit_unarmed_ulog(raw, entry):
    """Decode the same retained bytes; never open a socket or mutate the input.

    This establishes disarmed/standby *logged observations*, not coverage of
    intervals absent from the log, PX4 fusion, or provenance of an actual run.
    The whole-study reader must bind entry to the capture and stable local file.
    """
    _shape(entry, ("path", "bytes", "sha256", "valid_header"), "ULog entry")
    path = entry["path"]
    if (
        type(path) is not str
        or not path.startswith("px4-ulog/")
        or "\\" in path
        or "\0" in path
        or ".." in PurePosixPath(path).parts
        or PurePosixPath(path).suffix != ".ulg"
    ):
        raise ValueError("ULog evidence path")
    if type(raw) is not bytes or not 16 <= len(raw) <= 512 * 1024 * 1024:
        raise ValueError("ULog byte bound")
    _equal(entry["bytes"], len(raw), "ULog bytes")
    _equal(entry["sha256"], hashlib.sha256(raw).hexdigest(), "ULog hash")
    _equal(entry["valid_header"], True, "ULog declared header")
    framing = validate_ulog_stream(raw, include_topic_counts=True)
    if importlib.metadata.version("pyulog") != "1.2.4":
        raise ValueError("unverified pyulog version")
    from pyulog import ULog

    stream = _ObservedULogBuffer(raw)
    try:
        parsed = ULog(stream, disable_str_exceptions=False)
    except (struct.error, NotImplementedError, IndexError, KeyError, UnicodeError, RecursionError) as exc:
        raise ValueError("ULog parse failed: " + type(exc).__name__) from exc
    finally:
        stream.close()
    if stream.last_read != (len(raw), 3, 0):
        raise ValueError("ULog parser did not reach normal EOF")
    if parsed.file_corruption or parsed.dropouts:
        raise ValueError("ULog corruption or dropout")
    observations = {}
    for name, field, expected in (("vehicle_status", "arming_state", 1), ("actuator_armed", "armed", 0)):
        raw_topics = [row for row in framing["topic_counts"] if row["name"] == name]
        topics = [row for row in parsed.data_list if row.name == name]
        if len(raw_topics) != 1 or raw_topics[0]["multi_id"] != 0 or len(topics) != 1 or topics[0].multi_id != 0:
            raise ValueError("missing or ambiguous unarmed topic: " + name)
        data = topics[0].data
        if "timestamp" not in data or field not in data:
            raise ValueError("unarmed ULog field missing")
        times, values = data["timestamp"], data[field]
        if len(times) < 2 or len(times) != len(values) or len(times) != raw_topics[0]["data_count"]:
            raise ValueError("raw/decoded unarmed sample count")
        previous = 0
        stamps = []
        for timestamp, value in zip(times, values):
            timestamp = timestamp.item() if hasattr(timestamp, "item") else timestamp
            value = value.item() if hasattr(value, "item") else value
            _integer(timestamp, previous + 1, 2**64 - 1, "unarmed sample time")
            if type(value) not in (int, bool) or value != expected or field == "arming_state" and type(value) is not int:
                raise ValueError("ULog armed or outside standby profile")
            previous = timestamp
            stamps.append(timestamp)
        observations[name] = dict(count=len(stamps), first_us=stamps[0], last_us=stamps[-1], span_us=stamps[-1] - stamps[0])
    return dict(
        unarmed_log_observations=True,
        parser_version="1.2.4",
        raw_message_count=framing["message_count"],
        status_samples=observations["vehicle_status"]["count"],
        actuator_samples=observations["actuator_armed"]["count"],
        status_span_us=observations["vehicle_status"]["span_us"],
        observation_bounds=observations,
        full_capture_coverage_qualified=False,
        live_qualified=False,
        fusion_qualified=False,
    )
