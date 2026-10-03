"""Strictly audit logging-only OpenVINS monocular KLT diagnostics."""

import math
import re
from collections import Counter
from dataclasses import dataclass

_MATCH = re.compile(
    r"FD_KLT_MATCH cam0=(\d+) cam1=(\d+) input=(\d+) klt=(\d+) "
    r"ransac=(\d+) combined=(\d+) status=(normal|few|empty)"
)
_FRAME = re.compile(
    r"FD_KLT_FRAME t=([0-9]+(?:\.[0-9]+)?) cam=(\d+) previous=(\d+) "
    r"retained=(\d+) added=(\d+) input=(\d+) accepted=(\d+) "
    r"branch=(normal|bootstrap|reset)"
)
_ID = re.compile(r"FD_KLT_ID t=([0-9]+(?:\.[0-9]+)?) cam=(\d+) id=(\d+)")


@dataclass(frozen=True)
class Match:
    cam0: int
    cam1: int
    input: int
    klt: int
    ransac: int
    combined: int
    status: str


@dataclass(frozen=True)
class TrackFrame:
    time: float
    cam: int
    previous: int
    retained: int
    added: int
    input: int
    accepted: int
    branch: str
    match: Match | None
    ids: tuple[int, ...]


def _match_record(record: str) -> Match:
    found = _MATCH.fullmatch(record)
    if found is None:
        raise ValueError(f"malformed KLT match: {record}")
    cam0, cam1, input_count, klt, ransac, combined = map(int, found.groups()[:6])
    status = found.group(7)
    if cam0 != cam1 or not (0 <= combined <= klt <= input_count and combined <= ransac <= input_count):
        raise ValueError(f"impossible KLT match counts: {record}")
    if (status == "empty") != (input_count == 0):
        raise ValueError(f"wrong empty KLT status: {record}")
    if status == "few" and not (0 < input_count < 10 and klt == ransac == combined == 0):
        raise ValueError(f"wrong few-point KLT status: {record}")
    if status == "normal" and input_count < 10:
        raise ValueError(f"wrong normal KLT status: {record}")
    return Match(cam0, cam1, input_count, klt, ransac, combined, status)


def parse_track_log(text: str) -> list[TrackFrame]:
    """Parse frames and per-ID writes, rejecting missing or inconsistent logs."""
    frames: list[TrackFrame] = []
    match: Match | None = None
    frame: TrackFrame | None = None
    ids: list[int] = []
    last_time: dict[int, float] = {}

    def finish_frame() -> None:
        nonlocal frame, ids
        if frame is None:
            return
        if len(ids) != frame.accepted:
            raise ValueError(f"missing KLT IDs at {frame.time}: {len(ids)} != {frame.accepted}")
        frames.append(TrackFrame(**{**frame.__dict__, "ids": tuple(ids)}))
        frame, ids = None, []

    for line in text.splitlines():
        marker = line.find("FD_KLT_")
        if marker < 0:
            continue
        record = line[marker:].strip()
        if record.startswith("FD_KLT_MATCH"):
            finish_frame()
            if match is not None:
                raise ValueError("duplicate unpaired KLT match")
            match = _match_record(record)
            continue
        if record.startswith("FD_KLT_FRAME"):
            finish_frame()
            found = _FRAME.fullmatch(record)
            if found is None:
                raise ValueError(f"malformed KLT frame: {record}")
            time = float(found.group(1))
            cam, previous, retained, added, input_count, accepted = map(int, found.groups()[1:7])
            branch = found.group(8)
            if not math.isfinite(time) or time <= last_time.get(cam, -math.inf):
                raise ValueError(f"non-increasing KLT time: {record}")
            if retained > previous or retained + added != input_count:
                raise ValueError(f"impossible KLT detection counts: {record}")
            if branch == "bootstrap":
                if match is not None or previous != 0 or retained != 0 or accepted != 0:
                    raise ValueError(f"invalid KLT bootstrap: {record}")
            elif match is None or match.cam0 != cam or match.input != input_count:
                raise ValueError(f"missing or mismatched KLT match: {record}")
            elif branch == "reset":
                if match.status != "empty" or accepted != 0:
                    raise ValueError(f"invalid KLT reset: {record}")
            elif match.status == "empty" or accepted > match.combined:
                raise ValueError(f"impossible accepted KLT count: {record}")
            frame = TrackFrame(time, cam, previous, retained, added, input_count, accepted, branch, match, ())
            match = None
            last_time[cam] = time
            continue
        if record.startswith("FD_KLT_ID"):
            found = _ID.fullmatch(record)
            if found is None or frame is None:
                raise ValueError(f"orphan or malformed KLT ID: {record}")
            time, cam, feature_id = float(found.group(1)), int(found.group(2)), int(found.group(3))
            if time != frame.time or cam != frame.cam or feature_id in ids or len(ids) >= frame.accepted:
                raise ValueError(f"inconsistent KLT ID: {record}")
            ids.append(feature_id)
            continue
        raise ValueError(f"unknown KLT diagnostic: {record}")
    finish_frame()
    if match is not None:
        raise ValueError("unpaired KLT match at end of log")
    if not frames:
        raise ValueError("no KLT frame diagnostics")
    return frames


def summarize_frames(frames: list[TrackFrame], start: float, end: float) -> dict[str, int]:
    """Count actual database writes and tracker stages in an inclusive window."""
    selected = [frame for frame in frames if start <= frame.time <= end]
    occurrences = Counter(feature_id for frame in selected for feature_id in frame.ids)
    return {
        "frames": len(selected),
        "unique_written_ids": len(occurrences),
        "ids_with_two_writes": sum(count >= 2 for count in occurrences.values()),
        "accepted_total": sum(frame.accepted for frame in selected),
        "previous_total": sum(frame.previous for frame in selected),
        "retained_total": sum(frame.retained for frame in selected),
        "added_total": sum(frame.added for frame in selected),
        "matching_input_total": sum(frame.input for frame in selected if frame.match),
        "klt_total": sum(frame.match.klt for frame in selected if frame.match),
        "ransac_total": sum(frame.match.ransac for frame in selected if frame.match),
        "matched_total": sum(frame.match.combined for frame in selected if frame.match),
    }
