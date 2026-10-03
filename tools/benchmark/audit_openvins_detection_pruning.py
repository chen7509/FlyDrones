"""Strictly pair OpenVINS detection decisions with monocular KLT frames."""

import re
from collections import Counter
from dataclasses import dataclass

from tools.benchmark.audit_openvins_track_lifetime import TrackFrame

REASONS = ("edge", "close_bounds", "grid_bounds", "close_collision", "mask")
_DROP = re.compile(
    r"FD_DETECT_DROP id=(\d+) reason=(edge|close_bounds|grid_bounds|close_collision|mask) "
    r"x=(-?[0-9]+(?:\.[0-9]+)?) y=(-?[0-9]+(?:\.[0-9]+)?)"
)
_SUMMARY = re.compile(
    r"FD_DETECT_SUMMARY input=(\d+) edge=(\d+) close_bounds=(\d+) grid_bounds=(\d+) "
    r"close_collision=(\d+) mask=(\d+) retained=(\d+) candidates=(\d+) added=(\d+) branch=(topoff|skip)"
)
_FRAME_TIME = re.compile(r"FD_KLT_FRAME t=([0-9]+(?:\.[0-9]+)?) cam=(\d+) ")


@dataclass(frozen=True)
class Drop:
    feature_id: int
    reason: str
    x: float
    y: float


@dataclass(frozen=True)
class DetectionRecord:
    time: float
    cam: int
    input: int
    edge: int
    close_bounds: int
    grid_bounds: int
    close_collision: int
    mask: int
    retained: int
    candidates: int
    added: int
    branch: str
    drops: tuple[Drop, ...]


def parse_detection_log(text: str, lifetime_frames: list[TrackFrame]) -> list[DetectionRecord]:
    """Require one conserved detection summary per frame and prior-ID drops."""
    records: list[DetectionRecord] = []
    pending_drops: list[Drop] = []
    pending_summary: tuple[int, ...] | None = None
    pending_branch = ""

    for line in text.splitlines():
        drop_marker = line.find("FD_DETECT_")
        frame_marker = line.find("FD_KLT_FRAME")
        if drop_marker >= 0:
            record = line[drop_marker:].strip()
            if record.startswith("FD_DETECT_DROP"):
                found = _DROP.fullmatch(record)
                if found is None or pending_summary is not None:
                    raise ValueError(f"malformed or late detection drop: {record}")
                feature_id = int(found.group(1))
                if any(drop.feature_id == feature_id for drop in pending_drops):
                    raise ValueError(f"duplicate detection drop ID: {feature_id}")
                pending_drops.append(Drop(feature_id, found.group(2), float(found.group(3)), float(found.group(4))))
            elif record.startswith("FD_DETECT_SUMMARY"):
                found = _SUMMARY.fullmatch(record)
                if found is None or pending_summary is not None:
                    raise ValueError(f"missing or duplicate detection summary: {record}")
                values = tuple(map(int, found.groups()[:9]))
                input_count, *counts, retained, candidates, added = values
                pending_branch = found.group(10)
                reason_counts = Counter(drop.reason for drop in pending_drops)
                if any(reason_counts[reason] != count for reason, count in zip(REASONS, counts, strict=True)):
                    raise ValueError(f"drop reason counts differ from ID records: {record}")
                if input_count - retained != len(pending_drops) or added > candidates:
                    raise ValueError(f"detection count conservation failed: {record}")
                if pending_branch == "skip" and (candidates != 0 or added != 0):
                    raise ValueError(f"skip branch added points: {record}")
                pending_summary = values
            else:
                raise ValueError(f"unknown detection diagnostic: {record}")
            continue
        if frame_marker < 0:
            continue
        record = line[frame_marker:].strip()
        found = _FRAME_TIME.match(record)
        if found is None or pending_summary is None or len(records) >= len(lifetime_frames):
            raise ValueError(f"unpaired or malformed detection frame: {record}")
        frame = lifetime_frames[len(records)]
        time, cam = float(found.group(1)), int(found.group(2))
        input_count, edge, close_bounds, grid_bounds, close_collision, mask, retained, candidates, added = pending_summary
        if (time, cam) != (frame.time, frame.cam):
            raise ValueError(f"detection frame order differs from KLT frame: {record}")
        if (input_count, retained, added) != (frame.previous, frame.retained, frame.added):
            raise ValueError(f"detection summary differs from KLT frame: {record}")
        if records and records[-1].time < time and lifetime_frames[len(records) - 1].branch == "normal":
            previous_ids = lifetime_frames[len(records) - 1].ids
            if len(previous_ids) != input_count or not {drop.feature_id for drop in pending_drops}.issubset(previous_ids):
                raise ValueError(f"dropped ID not in previous written KLT IDs: {record}")
        records.append(DetectionRecord(time, cam, input_count, edge, close_bounds, grid_bounds, close_collision, mask,
                                       retained, candidates, added, pending_branch, tuple(pending_drops)))
        pending_drops, pending_summary, pending_branch = [], None, ""

    if pending_drops or pending_summary is not None or len(records) != len(lifetime_frames):
        raise ValueError("missing frame or unmatched detection diagnostics")
    return records
