"""Autonomous mission state machine with deterministic safety preemption."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Literal

from flydrones.mission_contract import MissionContract, WorkUnit
from flydrones.peer_udp import PeerTrack
from flydrones.task_consensus import AgentCapability, Bid, TaskAssignment, TaskLedger
from flydrones.task_udp import TaskMessage

SafetyPhase = Literal["nominal", "degraded", "return", "land", "emergency"]


@dataclass(frozen=True)
class AgentState:
    position_m: tuple[float, float, float]
    velocity_mps: tuple[float, float, float]
    battery_pct: float
    depth_age_s: float
    localization_valid: bool


@dataclass(frozen=True)
class Detection:
    target_class: str
    position_m: tuple[float, float, float]
    confidence: float
    evidence_hash: str


@dataclass(frozen=True)
class NavigationIntent:
    velocity_mps: tuple[float, float, float]
    target_m: tuple[float, float, float] | None
    source: str


@dataclass(frozen=True)
class AgentDecision:
    phase: str
    safety_phase: str
    intent: NavigationIntent
    outbound_messages: tuple[tuple[str, dict[str, object]], ...]
    released_task_ids: tuple[str, ...]
    central_control_commands: int = 0


def _finite_vector(values: tuple[float, float, float]) -> bool:
    return len(values) == 3 and all(math.isfinite(float(value)) for value in values)


def _limit(vector: tuple[float, float, float], maximum: float) -> tuple[float, float, float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude <= maximum or magnitude <= 1e-12:
        return vector
    scale = maximum / magnitude
    return tuple(value * scale for value in vector)


def _closest_approach(
    relative_position: tuple[float, float, float],
    own_velocity: tuple[float, float, float],
    other_velocity: tuple[float, float, float],
    horizon_s: float,
) -> tuple[float, float]:
    closing = tuple(own_velocity[index] - other_velocity[index] for index in range(3))
    speed_squared = sum(value * value for value in closing)
    if speed_squared < 1e-9:
        return 0.0, math.sqrt(sum(value * value for value in relative_position))
    time_s = sum(relative_position[index] * closing[index] for index in range(3)) / speed_squared
    time_s = max(0.0, min(horizon_s, time_s))
    miss = tuple(relative_position[index] - closing[index] * time_s for index in range(3))
    return time_s, math.sqrt(sum(value * value for value in miss))


def _work_unit_payload(work_unit: WorkUnit) -> dict[str, object]:
    return {
        "task_id": work_unit.task_id,
        "kind": work_unit.kind,
        "center_m": list(work_unit.center_m),
        "payload": [list(item) for item in work_unit.payload],
    }


def _work_unit_from_payload(payload: object) -> WorkUnit:
    if not isinstance(payload, dict):
        raise ValueError("work_unit payload must be an object")
    return WorkUnit(
        task_id=str(payload["task_id"]),
        kind=str(payload["kind"]),  # type: ignore[arg-type]
        center_m=tuple(float(value) for value in payload["center_m"]),  # type: ignore[arg-type]
        payload=tuple(tuple(str(value) for value in item) for item in payload.get("payload", ())),  # type: ignore[arg-type]
    )


def _confirmation_affinity(task_id: str, vehicle_id: int) -> int:
    """Return a stable rendezvous score used to spread confirmation work."""
    digest = hashlib.sha256(f"{task_id}:{vehicle_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


class MissionAgent:
    """One vehicle's mission intelligence; all mutable state is process-local."""

    def __init__(
        self,
        vehicle_id: int,
        vehicle_count: int,
        contract: MissionContract,
        ledger: TaskLedger,
    ) -> None:
        self.vehicle_id = vehicle_id
        self.vehicle_count = vehicle_count
        self.contract = contract
        self.ledger = ledger
        self._work_units = {unit.task_id: unit for unit in contract.expand_work_units()}
        self._phase = "auction"
        self._safety_phase: SafetyPhase = "nominal"
        self._terminal_safety: SafetyPhase | None = None
        self._active_task_id: str | None = None
        self._active_since: float | None = None
        self._depth_stale_since: float | None = None
        self._low_connectivity_since: float | None = None
        self._task_peer_seen_at: dict[int, float] = {}
        self._seen_evidence: set[str] = set()
        self._released_tasks: set[str] = set()
        self._last_bid_at = -math.inf
        self._last_renew_at = -math.inf
        self._steps = 0

    @classmethod
    def for_contract(
        cls,
        vehicle_id: int,
        vehicle_count: int,
        contract: MissionContract,
    ) -> MissionAgent:
        if vehicle_count <= 0 or not 0 <= vehicle_id < vehicle_count:
            raise ValueError("vehicle ID must fall inside the fleet")
        units = contract.expand_work_units()
        ledger = TaskLedger(
            vehicle_id,
            contract.digest,
            units,
            confirmation_quorum=contract.confirmation_quorum,
            minimum_battery_return_pct=contract.safety.minimum_battery_return_pct,
        )
        return cls(vehicle_id, vehicle_count, contract, ledger)

    @property
    def work_unit_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._work_units))

    def step(
        self,
        now: float,
        state: AgentState,
        peer_tracks: list[PeerTrack] | tuple[PeerTrack, ...],
        messages: list[TaskMessage] | tuple[TaskMessage, ...],
        detections: list[Detection] | tuple[Detection, ...],
        *,
        bidding_enabled: bool = True,
        preferred_task_ids: tuple[str, ...] = (),
    ) -> AgentDecision:
        timestamp = float(now)
        if not math.isfinite(timestamp):
            raise ValueError("now must be finite")
        outbound: list[tuple[str, dict[str, object]]] = []
        self.ingest_messages(messages, now=timestamp)
        self.ledger.expire(now=timestamp)
        self._update_detections(detections, outbound)
        self._update_relay_task(timestamp, state, outbound)

        safety = self._apply_safety(timestamp, state)
        released: tuple[str, ...] = ()
        if safety in {"return", "land", "emergency"}:
            released = self._release_active_task(timestamp)
            for task_id in released:
                outbound.append(("award", {"assignment": asdict(self.ledger.assignment(task_id))}))
        if safety in {"land", "emergency"}:
            self._phase = "land" if safety == "land" else "emergency"
            intent = NavigationIntent((0.0, 0.0, 0.0), None, f"safety-{safety}")
            self._steps += 1
            return AgentDecision(self._phase, safety, intent, tuple(outbound), released)
        if safety == "return":
            self._phase = "rally"
            intent = self._velocity_toward(state.position_m, self.contract.rally_position_m, "safety-return")
            intent = self._apply_peer_separation(intent, state, peer_tracks)
            self._steps += 1
            return AgentDecision(self._phase, safety, intent, tuple(outbound), released)
        if safety == "degraded":
            self._steps += 1
            return AgentDecision(
                self._phase,
                safety,
                NavigationIntent((0.0, 0.0, 0.0), self._active_target(), "safety-depth-hold"),
                tuple(outbound),
                released,
            )
        if not bidding_enabled:
            self._phase = "reserve"
            self._steps += 1
            return AgentDecision(
                self._phase,
                safety,
                NavigationIntent((0.0, 0.0, 0.0), None, "deterministic-reserve"),
                tuple(outbound),
                released,
            )

        self._allocate_or_renew(
            timestamp,
            state,
            outbound,
            preferred_task_ids=preferred_task_ids,
        )
        self._complete_if_ready(timestamp, state, outbound)
        intent = self._task_intent(state)
        intent = self._apply_peer_separation(intent, state, peer_tracks)
        decision_phase = "auction" if self._steps == 0 else self._phase
        self._steps += 1
        return AgentDecision(decision_phase, safety, intent, tuple(outbound), released)

    def ingest_messages(
        self,
        messages: list[TaskMessage] | tuple[TaskMessage, ...],
        *,
        now: float,
    ) -> None:
        """Merge validated peer records during a communication-only convergence tail."""
        self._merge_messages(messages, float(now))

    def work_unit(self, task_id: str) -> WorkUnit:
        return self._work_units[task_id]

    def _merge_messages(self, messages: list[TaskMessage] | tuple[TaskMessage, ...], now: float) -> None:
        for message in messages:
            if message.mission_id != self.contract.mission_id or message.mission_digest != self.contract.digest:
                continue
            if message.sender_id != self.vehicle_id:
                self._task_peer_seen_at[message.sender_id] = now
            payload = message.payload
            try:
                if message.kind == "bid":
                    self.ledger.observe_bid(
                        Bid(
                            str(payload["task_id"]),
                            int(payload["bidder_id"]),
                            float(payload["utility"]),
                            int(payload["allocation_round"]),
                            float(payload["created_at"]),
                        ),
                        now=now,
                    )
                elif message.kind == "award" and "assignments" in payload:
                    assignments = payload["assignments"]
                    if not isinstance(assignments, list):
                        continue
                    for assignment_payload in assignments:
                        self.ledger.merge_assignment(
                            self._assignment_from_payload(assignment_payload),
                            now=now,
                        )
                elif message.kind == "award" and "work_unit" in payload:
                    unit = _work_unit_from_payload(payload["work_unit"])
                    self.ledger.add_work_unit(unit)
                    self._work_units[unit.task_id] = unit
                elif message.kind in {"award", "lease", "evidence"} and "assignment" in payload:
                    self.ledger.merge_assignment(self._assignment_from_payload(payload["assignment"]), now=now)
                elif message.kind == "evidence" and "work_unit" in payload:
                    unit = _work_unit_from_payload(payload["work_unit"])
                    self.ledger.add_work_unit(unit)
                    self._work_units[unit.task_id] = unit
            except (KeyError, TypeError, ValueError):
                continue

    def _update_detections(
        self,
        detections: list[Detection] | tuple[Detection, ...],
        outbound: list[tuple[str, dict[str, object]]],
    ) -> None:
        for detection in detections:
            if detection.evidence_hash in self._seen_evidence:
                continue
            if detection.target_class not in self.contract.target_classes:
                continue
            if not _finite_vector(detection.position_m) or not 0.0 <= detection.confidence <= 1.0:
                continue
            if len(detection.evidence_hash) != 64:
                continue
            quantized = tuple(round(value) for value in detection.position_m)
            identity = (
                f"{detection.target_class}|{quantized[0]}|{quantized[1]}|{quantized[2]}|"
                f"{detection.evidence_hash}"
            ).encode()
            task_id = f"confirm-{hashlib.sha256(identity).hexdigest()[:12]}"
            unit = WorkUnit(
                task_id,
                "confirm_detection",
                tuple(float(value) for value in quantized),
                (
                    ("required_sensor", detection.target_class),
                    ("first_evidence_hash", detection.evidence_hash),
                ),
            )
            self.ledger.add_work_unit(unit)
            self._work_units[task_id] = unit
            self._seen_evidence.add(detection.evidence_hash)
            outbound.append(("evidence", {"work_unit": _work_unit_payload(unit)}))

    def _update_relay_task(
        self,
        now: float,
        state: AgentState,
        outbound: list[tuple[str, dict[str, object]]],
    ) -> None:
        fresh = [seen for seen in self._task_peer_seen_at.values() if now - seen <= 2.0]
        if len(fresh) >= 2:
            self._low_connectivity_since = None
            return
        if self._low_connectivity_since is None:
            self._low_connectivity_since = now
            return
        if now - self._low_connectivity_since < 2.0:
            return
        epoch = int(now // 5.0)
        task_id = f"relay-{self.vehicle_id}-{epoch}"
        center = tuple(
            (state.position_m[index] + self.contract.rally_position_m[index]) / 2.0
            for index in range(3)
        )
        unit = WorkUnit(task_id, "relay", center, (("creator", str(self.vehicle_id)),))
        existed = task_id in self._work_units
        self.ledger.add_work_unit(unit)
        self._work_units[task_id] = unit
        if not existed:
            outbound.append(("award", {"task_id": task_id, "work_unit": _work_unit_payload(unit)}))

    def _apply_safety(self, now: float, state: AgentState) -> SafetyPhase:
        if self._terminal_safety is not None:
            return self._terminal_safety
        if not _finite_vector(state.position_m) or not _finite_vector(state.velocity_mps):
            self._terminal_safety = "emergency"
            return "emergency"
        if not state.localization_valid:
            self._terminal_safety = "land"
            return "land"
        if state.depth_age_s > 0.5:
            if self._depth_stale_since is None:
                self._depth_stale_since = now
            if now - self._depth_stale_since >= 2.0:
                self._terminal_safety = "land"
                return "land"
            self._safety_phase = "degraded"
            return "degraded"
        self._depth_stale_since = None
        if state.battery_pct <= self.contract.safety.minimum_battery_return_pct:
            self._safety_phase = "return"
            return "return"
        if not self._inside_geofence(state.position_m):
            self._safety_phase = "return"
            return "return"
        self._safety_phase = "nominal"
        return "nominal"

    def _inside_geofence(self, position: tuple[float, float, float]) -> bool:
        margin = self.contract.safety.geofence_margin_m
        xs = [point[0] for point in self.contract.area_polygon_m] + [self.contract.rally_position_m[0]]
        ys = [point[1] for point in self.contract.area_polygon_m] + [self.contract.rally_position_m[1]]
        return min(xs) - margin <= position[0] <= max(xs) + margin and min(ys) - margin <= position[1] <= max(ys) + margin

    def _release_active_task(self, now: float) -> tuple[str, ...]:
        task_id = self._active_task_id
        if task_id is None or task_id in self._released_tasks:
            return ()
        current = self.ledger.assignment(task_id)
        if current.status == "completed" or current.winner_id != self.vehicle_id:
            self._active_task_id = None
            self._active_since = None
            return ()
        self.ledger.release(task_id, winner_id=self.vehicle_id, now=now)
        self._released_tasks.add(task_id)
        self._active_task_id = None
        return (task_id,)

    def _allocate_or_renew(
        self,
        now: float,
        state: AgentState,
        outbound: list[tuple[str, dict[str, object]]],
        *,
        preferred_task_ids: tuple[str, ...] = (),
    ) -> None:
        unknown = [task_id for task_id in preferred_task_ids if task_id not in self._work_units]
        if unknown:
            raise ValueError(f"unknown preferred task: {unknown[0]}")
        preferred_task_id = next(
            (
                task_id
                for task_id in preferred_task_ids
                if self.ledger.assignment(task_id).status != "completed"
            ),
            None,
        )
        if self._active_task_id is not None:
            current = self.ledger.assignment(self._active_task_id)
            if current.winner_id != self.vehicle_id or current.status in {"completed", "failed", "open"}:
                self._active_task_id = None
                self._active_since = None
            elif now - self._last_renew_at >= 0.5:
                renewed = self.ledger.renew(
                    current.task_id,
                    winner_id=self.vehicle_id,
                    allocation_round=current.allocation_round,
                    now=now,
                )
                self._last_renew_at = now
                outbound.append(("lease", {"assignment": asdict(renewed)}))
        if self._active_task_id is not None or now - self._last_bid_at < 0.2:
            return

        capability = AgentCapability(
            self.vehicle_id,
            state.position_m,
            state.battery_pct,
            self.contract.target_classes,
            0,
        )
        candidates: list[Bid] = []
        unfinished_search = any(
            unit.kind == "search_cell" and self.ledger.assignment(task_id).status != "completed"
            for task_id, unit in self._work_units.items()
        )
        for task_id, unit in self._work_units.items():
            if preferred_task_id is not None and task_id != preferred_task_id:
                continue
            if unit.kind == "rally" and unfinished_search:
                continue
            assignment = self.ledger.assignment(task_id)
            if assignment.status not in {"open", "claimed"}:
                continue
            bid = self.ledger.bid_for(task_id, capability, now=now)
            if bid is not None:
                candidates.append(bid)
        self._last_bid_at = now
        if not candidates:
            self._phase = "rally" if not unfinished_search else "auction"
            return
        def candidate_key(item: Bid) -> tuple[int, int, int, float, int, str]:
            kind = self._work_units[item.task_id].kind
            return (
                {"confirm_detection": 4, "search_cell": 3, "relay": 1, "rally": 0}[kind],
                0 if kind == "confirm_detection" else item.allocation_round,
                _confirmation_affinity(item.task_id, self.vehicle_id)
                if kind == "confirm_detection"
                else 0,
                item.utility,
                -item.bidder_id,
                item.task_id,
            )

        bid = max(candidates, key=candidate_key)
        awarded = self.ledger.observe_bid(bid, now=now)
        outbound.append(("bid", asdict(bid)))
        if awarded.winner_id == self.vehicle_id:
            self._released_tasks.discard(awarded.task_id)
            self._active_task_id = awarded.task_id
            self._active_since = now
            self._phase = "transit"

    def _complete_if_ready(
        self,
        now: float,
        state: AgentState,
        outbound: list[tuple[str, dict[str, object]]],
    ) -> None:
        if self._active_task_id is None or self._active_since is None:
            return
        unit = self._work_units[self._active_task_id]
        if math.dist(state.position_m, unit.center_m) > 2.0 or now - self._active_since < 1.0:
            return
        evidence = hashlib.sha256(
            f"{self.contract.digest}|{unit.task_id}|{self.vehicle_id}".encode()
        ).hexdigest()
        assignment = self.ledger.complete(unit.task_id, self.vehicle_id, evidence, now=now)
        outbound.append(("evidence", {"task_id": unit.task_id, "evidence_hash": evidence, "assignment": asdict(assignment)}))
        if assignment.status == "completed":
            self._active_task_id = None
            self._active_since = None
            self._phase = "auction"
        else:
            reopened = self.ledger.release(unit.task_id, winner_id=self.vehicle_id, now=now)
            outbound.append(("award", {"assignment": asdict(reopened)}))
            self._active_task_id = None
            self._active_since = None
            self._phase = "auction"

    def _task_intent(self, state: AgentState) -> NavigationIntent:
        target = self._active_target()
        if target is None:
            return NavigationIntent((0.0, 0.0, 0.0), None, "local-task-planner")
        distance = math.dist(state.position_m, target)
        self._phase = "execute" if distance <= 2.0 else "transit"
        return self._velocity_toward(state.position_m, target, "local-task-planner")

    def _active_target(self) -> tuple[float, float, float] | None:
        if self._active_task_id is None:
            return None
        return self._work_units[self._active_task_id].center_m

    def _velocity_toward(
        self,
        position: tuple[float, float, float],
        target: tuple[float, float, float],
        source: str,
    ) -> NavigationIntent:
        delta = tuple((target[index] - position[index]) * 0.7 for index in range(3))
        velocity = _limit(delta, self.contract.safety.maximum_speed_mps)
        return NavigationIntent(velocity, target, source)

    def _apply_peer_separation(
        self,
        intent: NavigationIntent,
        state: AgentState,
        peer_tracks: list[PeerTrack] | tuple[PeerTrack, ...],
    ) -> NavigationIntent:
        preferred = intent.velocity_mps
        correction = [0.0, 0.0, 0.0]
        active = False
        for track in peer_tracks:
            relative = tuple(track.position[index] - state.position_m[index] for index in range(3))
            _time_s, miss = _closest_approach(
                relative,
                preferred,
                track.velocity,
                3.0,
            )
            distance = math.sqrt(sum(value * value for value in relative))
            required = self.contract.safety.minimum_separation_m + 2.0
            if distance >= required * 1.5 and miss >= required:
                continue
            away = [-value / max(distance, 1e-6) for value in relative]
            away[2] += 0.35 if self.vehicle_id > track.sender_id else -0.35
            for index in range(3):
                correction[index] += away[index] * self.contract.safety.maximum_speed_mps
            active = True
        if not active:
            return intent
        velocity = _limit(
            tuple(preferred[index] * 0.3 + correction[index] for index in range(3)),
            self.contract.safety.maximum_speed_mps,
        )
        return NavigationIntent(
            velocity,
            intent.target_m,
            "local-separation",
        )

    @staticmethod
    def _assignment_from_payload(payload: object) -> TaskAssignment:
        if not isinstance(payload, dict):
            raise ValueError("assignment payload must be an object")
        return TaskAssignment(
            str(payload["task_id"]),
            str(payload["status"]),  # type: ignore[arg-type]
            None if payload.get("winner_id") is None else int(payload["winner_id"]),
            None if payload.get("utility") is None else float(payload["utility"]),
            int(payload["allocation_round"]),
            None if payload.get("lease_until") is None else float(payload["lease_until"]),
            None if payload.get("evidence_hash") is None else str(payload["evidence_hash"]),
            tuple(int(value) for value in payload.get("confirmers", ())),
        )
