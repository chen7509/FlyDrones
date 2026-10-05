"""Pair OpenVINS extracted/new points with one prior detector frame."""

import re
from collections import Counter
from dataclasses import dataclass

from tools.benchmark.audit_openvins_detection_pruning import DetectionRecord

_POINT = re.compile(r"FD_CANDIDATE x=(-?[0-9]+(?:\.[0-9]+)?) y=(-?[0-9]+(?:\.[0-9]+)?)")
_NEW = re.compile(r"FD_NEW id=(\d+) x=(-?[0-9]+(?:\.[0-9]+)?) y=(-?[0-9]+(?:\.[0-9]+)?)")
_FRAME = re.compile(r"FD_KLT_FRAME t=([0-9]+(?:\.[0-9]+)?) cam=(\d+) ")


@dataclass(frozen=True)
class Candidate:
    x: float
    y: float


@dataclass(frozen=True)
class NewPoint:
    feature_id: int
    x: float
    y: float


@dataclass(frozen=True)
class CandidateRecord:
    time: float
    candidates: tuple[Candidate, ...]
    new: tuple[NewPoint, ...]


def is_interior(x: float, y: float, width: int, height: int, edge: int = 10) -> bool:
    """Mirror C++ integer truncation followed by TrackKLT's border check."""
    if width <= 2 * edge or height <= 2 * edge:
        raise ValueError("invalid image bounds")
    ix, iy = int(x), int(y)
    return edge <= ix < width - edge and edge <= iy < height - edge


def parse_candidate_log(text: str, detections: list[DetectionRecord]) -> list[CandidateRecord]:
    """Require one complete candidate/new/summary group per paired frame."""
    records: list[CandidateRecord] = []
    candidates: list[Candidate] = []
    new: list[NewPoint] = []
    saw_summary = False
    seen_ids: set[int] = set()
    for line in text.splitlines():
        markers = [(line.find(key), key) for key in ("FD_CANDIDATE", "FD_NEW", "FD_DETECT_SUMMARY", "FD_KLT_FRAME")]
        present = [(position, key) for position, key in markers if position >= 0]
        if not present:
            continue
        position, marker = min(present)
        payload = line[position:].strip()
        if marker == "FD_CANDIDATE":
            match = _POINT.fullmatch(payload)
            if match is None or saw_summary:
                raise ValueError(f"malformed or late candidate: {payload}")
            candidates.append(Candidate(float(match.group(1)), float(match.group(2))))
        elif marker == "FD_NEW":
            match = _NEW.fullmatch(payload)
            if match is None or saw_summary:
                raise ValueError(f"malformed or late new point: {payload}")
            feature_id = int(match.group(1))
            if feature_id in seen_ids or any(point.feature_id == feature_id for point in new):
                raise ValueError(f"duplicate new point ID: {feature_id}")
            new.append(NewPoint(feature_id, float(match.group(2)), float(match.group(3))))
        elif marker == "FD_DETECT_SUMMARY":
            if saw_summary or len(records) >= len(detections):
                raise ValueError(f"duplicate/unpaired summary: {payload}")
            detection = detections[len(records)]
            if len(candidates) != detection.candidates or len(new) != detection.added:
                raise ValueError(f"candidate/new counts differ from detector: {payload}")
            available = Counter((point.x, point.y) for point in candidates)
            for point in new:
                coordinate = (point.x, point.y)
                if available[coordinate] <= 0:
                    raise ValueError(f"new point not extracted candidate: {point.feature_id}")
                available[coordinate] -= 1
            saw_summary = True
        else:
            match = _FRAME.match(payload)
            if match is None or not saw_summary or len(records) >= len(detections):
                raise ValueError(f"unpaired candidate frame: {payload}")
            detection = detections[len(records)]
            if (float(match.group(1)), int(match.group(2))) != (detection.time, detection.cam):
                raise ValueError(f"candidate frame mismatch: {payload}")
            records.append(CandidateRecord(detection.time, tuple(candidates), tuple(new)))
            seen_ids.update(point.feature_id for point in new)
            candidates, new, saw_summary = [], [], False
    if candidates or new or saw_summary or len(records) != len(detections):
        raise ValueError("unmatched candidate diagnostics")
    return records
