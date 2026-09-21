"""Deterministic, lease-based task consensus for autonomous swarm agents."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Literal

from flydrones.mission_contract import WorkUnit

AssignmentStatus = Literal["open", "claimed", "active", "completed", "failed"]

_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_WORK_KINDS = {"search_cell", "confirm_detection", "relay", "rally"}
_STATUS_RANK = {"open": 0, "claimed": 1, "active": 2, "failed": 3, "completed": 4}


def _finite(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{where} must be a finite number")
    return number


def _nonnegative_integer(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{where} must be a non-negative integer")
    return value


def _valid_digest(value: object, where: str) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{where} must be a 64-character lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class AgentCapability:
    vehicle_id: int
    position_m: tuple[float, float, float]
    battery_pct: float
    sensor_classes: tuple[str, ...]
    active_tasks: int


@dataclass(frozen=True)
class Bid:
    task_id: str
    bidder_id: int
    utility: float
    allocation_round: int
    created_at: float


@dataclass(frozen=True)
class TaskAssignment:
    task_id: str
    status: AssignmentStatus
    winner_id: int | None
    utility: float | None
    allocation_round: int
    lease_until: float | None
    evidence_hash: str | None
    confirmers: tuple[int, ...]


class TaskLedger:
    """Local task view that converges under deterministic record merging.

    Every agent owns one instance.  No method consults a central state store:
    callers exchange immutable :class:`Bid` and :class:`TaskAssignment` records.
    """

    def __init__(
        self,
        vehicle_id: int,
        mission_digest: str,
        work_units: list[WorkUnit] | tuple[WorkUnit, ...],
        *,
        lease_timeout_s: float = 3.0,
        confirmation_quorum: int = 2,
        minimum_battery_return_pct: float = 20.0,
    ) -> None:
        self.vehicle_id = _nonnegative_integer(vehicle_id, "vehicle_id")
        self.mission_digest = _valid_digest(mission_digest, "mission digest")
        self.lease_timeout_s = _finite(lease_timeout_s, "lease_timeout_s")
        if self.lease_timeout_s <= 0.0:
            raise ValueError("lease_timeout_s must be positive")
        self.confirmation_quorum = _nonnegative_integer(
            confirmation_quorum,
            "confirmation_quorum",
        )
        if self.confirmation_quorum < 2:
            raise ValueError("confirmation_quorum must be at least two")
        self.minimum_battery_return_pct = _finite(
            minimum_battery_return_pct,
            "minimum_battery_return_pct",
        )
        if not 0.0 <= self.minimum_battery_return_pct <= 100.0:
            raise ValueError("minimum_battery_return_pct must be between zero and 100")
        self._work_units: dict[str, WorkUnit] = {}
        self._assignments: dict[str, TaskAssignment] = {}
        for work_unit in work_units:
            self.add_work_unit(work_unit)

    def _check_digest(self, mission_digest: str | None) -> None:
        if mission_digest is not None and mission_digest != self.mission_digest:
            raise ValueError("mission digest mismatch")

    def _known_task(self, task_id: str) -> WorkUnit:
        try:
            return self._work_units[task_id]
        except KeyError:
            raise KeyError(f"unknown task ID: {task_id}") from None

    def add_work_unit(self, work_unit: WorkUnit) -> TaskAssignment:
        if not isinstance(work_unit, WorkUnit):
            raise ValueError("work unit must be a WorkUnit")
        if not work_unit.task_id:
            raise ValueError("work unit task_id cannot be empty")
        if work_unit.kind not in _WORK_KINDS:
            raise ValueError(f"unsupported work unit kind: {work_unit.kind}")
        if len(work_unit.center_m) != 3:
            raise ValueError("work unit center must contain three coordinates")
        for index, coordinate in enumerate(work_unit.center_m):
            _finite(coordinate, f"work unit center[{index}]")

        existing = self._work_units.get(work_unit.task_id)
        if existing is not None:
            if existing != work_unit:
                raise ValueError(f"dynamic work unit conflict for {work_unit.task_id}")
            return self._assignments[work_unit.task_id]

        self._work_units[work_unit.task_id] = work_unit
        assignment = TaskAssignment(
            task_id=work_unit.task_id,
            status="open",
            winner_id=None,
            utility=None,
            allocation_round=0,
            lease_until=None,
            evidence_hash=None,
            confirmers=(),
        )
        self._assignments[work_unit.task_id] = assignment
        return assignment

    def assignment(self, task_id: str) -> TaskAssignment:
        self._known_task(task_id)
        return self._assignments[task_id]

    def bid_for(
        self,
        task_id: str,
        capability: AgentCapability,
        *,
        now: float,
        required_sensor: str | None = None,
        mission_digest: str | None = None,
    ) -> Bid | None:
        self._check_digest(mission_digest)
        timestamp = _finite(now, "now")
        work_unit = self._known_task(task_id)
        assignment = self._assignments[task_id]
        if assignment.status == "completed":
            return None
        if work_unit.kind == "confirm_detection" and capability.vehicle_id in assignment.confirmers:
            return None
        self._validate_capability(capability)
        if capability.battery_pct <= self.minimum_battery_return_pct:
            return None

        sensor = required_sensor or self._required_sensor(work_unit)
        if sensor is not None and sensor not in capability.sensor_classes:
            return None
        distance = math.dist(capability.position_m, work_unit.center_m)
        utility = (
            100.0
            - distance
            - 4.0 * capability.active_tasks
            + 0.25 * capability.battery_pct
        )
        if sensor is not None:
            utility += 20.0
        return Bid(
            task_id=task_id,
            bidder_id=capability.vehicle_id,
            utility=utility,
            allocation_round=assignment.allocation_round,
            created_at=timestamp,
        )

    def observe_bid(
        self,
        bid: Bid,
        *,
        now: float,
        mission_digest: str | None = None,
    ) -> TaskAssignment:
        self._check_digest(mission_digest)
        timestamp = _finite(now, "now")
        if not isinstance(bid, Bid):
            raise ValueError("bid must be a Bid")
        self._validate_bid(bid)
        self._known_task(bid.task_id)
        current = self._assignments[bid.task_id]
        candidate = TaskAssignment(
            task_id=bid.task_id,
            status="claimed",
            winner_id=bid.bidder_id,
            utility=bid.utility,
            allocation_round=bid.allocation_round,
            lease_until=timestamp + self.lease_timeout_s,
            evidence_hash=current.evidence_hash,
            confirmers=current.confirmers,
        )
        return self.merge_assignment(candidate, now=timestamp)

    def merge_assignment(
        self,
        assignment: TaskAssignment,
        *,
        now: float,
        mission_digest: str | None = None,
    ) -> TaskAssignment:
        self._check_digest(mission_digest)
        _finite(now, "now")
        if not isinstance(assignment, TaskAssignment):
            raise ValueError("assignment must be a TaskAssignment")
        work_unit = self._known_task(assignment.task_id)
        self._validate_assignment(assignment, work_unit)
        current = self._assignments[assignment.task_id]

        if current.status == "completed":
            if assignment.status == "completed":
                winner_ids = [
                    winner_id
                    for winner_id in (current.winner_id, assignment.winner_id)
                    if winner_id is not None
                ]
                current = replace(
                    current,
                    winner_id=min(winner_ids) if winner_ids else None,
                    allocation_round=max(current.allocation_round, assignment.allocation_round),
                    confirmers=tuple(sorted(set(current.confirmers) | set(assignment.confirmers))),
                )
                self._assignments[current.task_id] = current
            return current
        if assignment.status == "completed":
            self._assignments[assignment.task_id] = assignment
            return assignment

        winner = self._choose_noncompleted(current, assignment)
        if work_unit.kind == "confirm_detection":
            evidence_values = [
                value for value in (current.evidence_hash, assignment.evidence_hash) if value is not None
            ]
            winner = replace(
                winner,
                evidence_hash=min(evidence_values) if evidence_values else None,
                confirmers=tuple(sorted(set(current.confirmers) | set(assignment.confirmers))),
            )
        self._assignments[assignment.task_id] = winner
        return winner

    def renew(
        self,
        task_id: str,
        *,
        winner_id: int,
        allocation_round: int,
        now: float,
        mission_digest: str | None = None,
    ) -> TaskAssignment:
        self._check_digest(mission_digest)
        timestamp = _finite(now, "now")
        current = self.assignment(task_id)
        if current.status == "completed":
            return current
        if current.winner_id != winner_id or current.allocation_round != allocation_round:
            raise ValueError("lease renewal does not match the current winner and allocation round")
        renewed = replace(
            current,
            status="active",
            lease_until=timestamp + self.lease_timeout_s,
        )
        self._assignments[task_id] = renewed
        return renewed

    def expire(self, *, now: float) -> tuple[str, ...]:
        timestamp = _finite(now, "now")
        expired: list[str] = []
        for task_id in sorted(self._assignments):
            current = self._assignments[task_id]
            if (
                current.status in {"claimed", "active"}
                and current.lease_until is not None
                and timestamp > current.lease_until
            ):
                self._assignments[task_id] = TaskAssignment(
                    task_id=task_id,
                    status="open",
                    winner_id=None,
                    utility=None,
                    allocation_round=current.allocation_round + 1,
                    lease_until=None,
                    evidence_hash=None,
                    confirmers=current.confirmers,
                )
                expired.append(task_id)
        return tuple(expired)

    def complete(
        self,
        task_id: str,
        winner_id: int,
        evidence_hash: str,
        *,
        now: float,
        mission_digest: str | None = None,
    ) -> TaskAssignment:
        self._check_digest(mission_digest)
        _finite(now, "now")
        confirmer = _nonnegative_integer(winner_id, "winner_id")
        evidence = _valid_digest(evidence_hash, "evidence hash")
        work_unit = self._known_task(task_id)
        current = self._assignments[task_id]
        if current.status == "completed":
            if confirmer not in current.confirmers:
                current = replace(
                    current,
                    confirmers=tuple(sorted((*current.confirmers, confirmer))),
                )
                self._assignments[task_id] = current
            return current

        confirmers = tuple(sorted(set(current.confirmers) | {confirmer}))
        completed = work_unit.kind != "confirm_detection" or len(confirmers) >= self.confirmation_quorum
        updated = replace(
            current,
            status="completed" if completed else "active",
            winner_id=current.winner_id if current.winner_id is not None else confirmer,
            lease_until=None if completed else current.lease_until,
            evidence_hash=current.evidence_hash or evidence,
            confirmers=confirmers,
        )
        self._assignments[task_id] = updated
        return updated

    def snapshot(self) -> tuple[TaskAssignment, ...]:
        return tuple(self._assignments[task_id] for task_id in sorted(self._assignments))

    @staticmethod
    def _required_sensor(work_unit: WorkUnit) -> str | None:
        payload = dict(work_unit.payload)
        explicit = payload.get("required_sensor")
        if explicit:
            return explicit
        targets = payload.get("target_classes")
        if targets:
            return targets.split(",", maxsplit=1)[0]
        return None

    @staticmethod
    def _validate_capability(capability: AgentCapability) -> None:
        if not isinstance(capability, AgentCapability):
            raise ValueError("capability must be an AgentCapability")
        _nonnegative_integer(capability.vehicle_id, "capability.vehicle_id")
        if len(capability.position_m) != 3:
            raise ValueError("capability.position_m must contain three coordinates")
        for index, coordinate in enumerate(capability.position_m):
            _finite(coordinate, f"capability.position_m[{index}]")
        battery = _finite(capability.battery_pct, "capability.battery_pct")
        if not 0.0 <= battery <= 100.0:
            raise ValueError("capability.battery_pct must be between zero and 100")
        _nonnegative_integer(capability.active_tasks, "capability.active_tasks")
        if any(not isinstance(sensor, str) or not sensor for sensor in capability.sensor_classes):
            raise ValueError("capability.sensor_classes must contain non-empty strings")

    @staticmethod
    def _validate_bid(bid: Bid) -> None:
        if not bid.task_id:
            raise ValueError("bid.task_id cannot be empty")
        _nonnegative_integer(bid.bidder_id, "bid.bidder_id")
        _finite(bid.utility, "bid.utility")
        _nonnegative_integer(bid.allocation_round, "bid.allocation_round")
        _finite(bid.created_at, "bid.created_at")

    def _validate_assignment(self, assignment: TaskAssignment, work_unit: WorkUnit) -> None:
        if assignment.status not in _STATUS_RANK:
            raise ValueError(f"invalid assignment status: {assignment.status}")
        _nonnegative_integer(assignment.allocation_round, "assignment.allocation_round")
        if assignment.winner_id is not None:
            _nonnegative_integer(assignment.winner_id, "assignment.winner_id")
        if assignment.utility is not None:
            _finite(assignment.utility, "assignment.utility")
        if assignment.lease_until is not None:
            _finite(assignment.lease_until, "assignment.lease_until")
        if tuple(sorted(set(assignment.confirmers))) != assignment.confirmers:
            raise ValueError("assignment.confirmers must be sorted and unique")
        for confirmer in assignment.confirmers:
            _nonnegative_integer(confirmer, "assignment.confirmer")
        if assignment.status == "completed":
            _valid_digest(assignment.evidence_hash, "assignment evidence hash")
            required = self.confirmation_quorum if work_unit.kind == "confirm_detection" else 1
            if len(assignment.confirmers) < required:
                raise ValueError("completed assignment lacks distinct confirmation evidence")

    @staticmethod
    def _choose_noncompleted(
        current: TaskAssignment,
        candidate: TaskAssignment,
    ) -> TaskAssignment:
        if candidate.allocation_round != current.allocation_round:
            return candidate if candidate.allocation_round > current.allocation_round else current

        current_utility = current.utility if current.utility is not None else -math.inf
        candidate_utility = candidate.utility if candidate.utility is not None else -math.inf
        if candidate_utility != current_utility:
            return candidate if candidate_utility > current_utility else current

        current_winner = current.winner_id if current.winner_id is not None else math.inf
        candidate_winner = candidate.winner_id if candidate.winner_id is not None else math.inf
        if candidate_winner != current_winner:
            return candidate if candidate_winner < current_winner else current

        if _STATUS_RANK[candidate.status] != _STATUS_RANK[current.status]:
            return candidate if _STATUS_RANK[candidate.status] > _STATUS_RANK[current.status] else current

        current_lease = current.lease_until if current.lease_until is not None else -math.inf
        candidate_lease = candidate.lease_until if candidate.lease_until is not None else -math.inf
        return candidate if candidate_lease > current_lease else current
