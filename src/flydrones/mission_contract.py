"""Strict structured missions shared by every autonomous swarm agent."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

WorkKind = Literal["search_cell", "confirm_detection", "relay", "rally"]

_CONTRACT_KEYS = {
    "schema_version",
    "mission_id",
    "mission_type",
    "area_polygon_m",
    "search_cell_size_m",
    "target_classes",
    "confirmation_quorum",
    "rally_position_m",
    "deadline_s",
    "safety",
}
_SAFETY_KEYS = {
    "maximum_speed_mps",
    "minimum_separation_m",
    "geofence_margin_m",
    "minimum_battery_return_pct",
}


def _require_exact_keys(data: Mapping[str, object], expected: set[str], where: str) -> None:
    missing = expected - set(data)
    extra = set(data) - expected
    if missing or extra:
        raise ValueError(f"{where} keys differ: missing={sorted(missing)}, extra={sorted(extra)}")


def _finite_number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{where} must be a finite number")
    return float(value)


def _positive_number(value: object, where: str) -> float:
    number = _finite_number(value, where)
    if number <= 0.0:
        raise ValueError(f"{where} must be positive")
    return number


def _integer(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where} must be an integer")
    return value


def _vector(value: object, length: int, where: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"{where} must contain {length} numbers")
    return tuple(_finite_number(item, f"{where}[{index}]") for index, item in enumerate(value))


def _polygon_area(points: tuple[tuple[float, float], ...]) -> float:
    return abs(sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )) / 2.0


def _point_inside_polygon(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


@dataclass(frozen=True)
class SafetyLimits:
    maximum_speed_mps: float
    minimum_separation_m: float
    geofence_margin_m: float
    minimum_battery_return_pct: float


@dataclass(frozen=True)
class WorkUnit:
    task_id: str
    kind: WorkKind
    center_m: tuple[float, float, float]
    payload: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MissionContract:
    schema_version: int
    mission_id: str
    mission_type: str
    area_polygon_m: tuple[tuple[float, float], ...]
    search_cell_size_m: float
    target_classes: tuple[str, ...]
    confirmation_quorum: int
    rally_position_m: tuple[float, float, float]
    deadline_s: float
    safety: SafetyLimits

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> MissionContract:
        if not isinstance(data, Mapping):
            raise ValueError("mission contract must be an object")
        _require_exact_keys(data, _CONTRACT_KEYS, "mission contract")
        schema_version = _integer(data["schema_version"], "schema_version")
        if schema_version != 1:
            raise ValueError("only mission schema version 1 is supported")
        mission_id = data["mission_id"]
        if not isinstance(mission_id, str) or not mission_id.strip() or len(mission_id) > 96:
            raise ValueError("mission_id must be a non-empty string of at most 96 characters")
        mission_type = data["mission_type"]
        if mission_type != "search_confirm_rally":
            raise ValueError("unsupported mission_type")

        polygon_value = data["area_polygon_m"]
        if not isinstance(polygon_value, (list, tuple)) or len(polygon_value) < 3:
            raise ValueError("area_polygon_m must contain at least three vertices")
        polygon = tuple(
            tuple(_vector(point, 2, f"area_polygon_m[{index}]"))
            for index, point in enumerate(polygon_value)
        )
        if _polygon_area(polygon) <= 1e-6:
            raise ValueError("area polygon must have positive area")

        target_value = data["target_classes"]
        if (
            not isinstance(target_value, (list, tuple))
            or not target_value
            or any(not isinstance(item, str) or not item.strip() for item in target_value)
        ):
            raise ValueError("target_classes must contain non-empty strings")
        target_classes = tuple(target_value)
        if len(set(target_classes)) != len(target_classes):
            raise ValueError("target_classes cannot contain duplicates")

        confirmation_quorum = _integer(data["confirmation_quorum"], "confirmation_quorum")
        if confirmation_quorum < 2:
            raise ValueError("confirmation_quorum must be at least two")

        safety_value = data["safety"]
        if not isinstance(safety_value, Mapping):
            raise ValueError("safety must be an object")
        _require_exact_keys(safety_value, _SAFETY_KEYS, "safety")
        battery_threshold = _finite_number(
            safety_value["minimum_battery_return_pct"],
            "safety.minimum_battery_return_pct",
        )
        if not 5.0 <= battery_threshold <= 95.0:
            raise ValueError("minimum_battery_return_pct must be between 5 and 95")
        safety = SafetyLimits(
            maximum_speed_mps=_positive_number(safety_value["maximum_speed_mps"], "safety.maximum_speed_mps"),
            minimum_separation_m=_positive_number(
                safety_value["minimum_separation_m"], "safety.minimum_separation_m"
            ),
            geofence_margin_m=_positive_number(safety_value["geofence_margin_m"], "safety.geofence_margin_m"),
            minimum_battery_return_pct=battery_threshold,
        )
        return cls(
            schema_version=schema_version,
            mission_id=mission_id,
            mission_type=mission_type,
            area_polygon_m=polygon,
            search_cell_size_m=_positive_number(data["search_cell_size_m"], "search_cell_size_m"),
            target_classes=target_classes,
            confirmation_quorum=confirmation_quorum,
            rally_position_m=tuple(_vector(data["rally_position_m"], 3, "rally_position_m")),
            deadline_s=_positive_number(data["deadline_s"], "deadline_s"),
            safety=safety,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "mission_type": self.mission_type,
            "area_polygon_m": [list(point) for point in self.area_polygon_m],
            "search_cell_size_m": self.search_cell_size_m,
            "target_classes": list(self.target_classes),
            "confirmation_quorum": self.confirmation_quorum,
            "rally_position_m": list(self.rally_position_m),
            "deadline_s": self.deadline_s,
            "safety": {
                "maximum_speed_mps": self.safety.maximum_speed_mps,
                "minimum_separation_m": self.safety.minimum_separation_m,
                "geofence_margin_m": self.safety.geofence_margin_m,
                "minimum_battery_return_pct": self.safety.minimum_battery_return_pct,
            },
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def expand_work_units(self) -> tuple[WorkUnit, ...]:
        minimum_x = min(point[0] for point in self.area_polygon_m)
        maximum_x = max(point[0] for point in self.area_polygon_m)
        minimum_y = min(point[1] for point in self.area_polygon_m)
        maximum_y = max(point[1] for point in self.area_polygon_m)
        centers: list[tuple[float, float]] = []
        y = minimum_y + self.search_cell_size_m / 2.0
        while y < maximum_y:
            x = minimum_x + self.search_cell_size_m / 2.0
            while x < maximum_x:
                if _point_inside_polygon((x, y), self.area_polygon_m):
                    centers.append((x, y))
                x += self.search_cell_size_m
            y += self.search_cell_size_m
        centers.sort(key=lambda point: (point[1], point[0]))
        altitude = self.rally_position_m[2]
        tasks = [
            WorkUnit(
                task_id=f"search-{index:04d}",
                kind="search_cell",
                center_m=(center[0], center[1], altitude),
                payload=(("target_classes", ",".join(self.target_classes)),),
            )
            for index, center in enumerate(centers)
        ]
        tasks.append(WorkUnit("rally-final", "rally", self.rally_position_m))
        return tuple(tasks)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def load_mission_contract(path: str | Path) -> MissionContract:
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(
            handle,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    if not isinstance(data, Mapping):
        raise ValueError("mission contract must be a JSON object")
    return MissionContract.from_dict(data)
