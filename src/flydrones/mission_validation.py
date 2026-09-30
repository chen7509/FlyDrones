"""Deterministic, read-only validation of decentralized mission reassignment."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .mission_agent import AgentState, MissionAgent
from .mission_contract import MissionContract
from .task_udp import TaskMessage


@dataclass(frozen=True)
class MissionValidationScenario:
    kind: str
    seed: int
    vehicle_id: int | None
    at_s: float
    duration_s: float = 12.0

    def __post_init__(self) -> None:
        if self.kind not in {"low_battery", "partition_stale_replay"}:
            raise ValueError("unsupported mission validation scenario")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("scenario seed must be an integer")
        if not math.isfinite(self.at_s) or self.at_s < 0.0:
            raise ValueError("scenario time must be finite and non-negative")
        if not math.isfinite(self.duration_s) or self.duration_s <= self.at_s:
            raise ValueError("scenario duration must follow its injection time")

    @classmethod
    def low_battery(
        cls, *, seed: int, vehicle_id: int, at_s: float
    ) -> MissionValidationScenario:
        return cls("low_battery", seed, vehicle_id, float(at_s))

    @classmethod
    def partition_with_stale_replay(
        cls, *, seed: int
    ) -> MissionValidationScenario:
        return cls("partition_stale_replay", seed, None, 2.0)


@dataclass(frozen=True)
class MissionValidationEvidence:
    scenario: str
    seed: int
    task_id: str
    task_release_s: float | None
    task_reopen_s: float | None
    task_reassign_s: float | None
    maximum_simultaneous_owners: int
    stale_messages_accepted: int
    stale_messages_rejected: int
    partition_drops: int
    safety_violations: int
    central_control_commands: int

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "seed": self.seed,
            "task_id": self.task_id,
            "task_release_s": self.task_release_s,
            "task_reopen_s": self.task_reopen_s,
            "task_reassign_s": self.task_reassign_s,
            "maximum_simultaneous_owners": self.maximum_simultaneous_owners,
            "stale_messages_accepted": self.stale_messages_accepted,
            "stale_messages_rejected": self.stale_messages_rejected,
            "partition_drops": self.partition_drops,
            "safety_violations": self.safety_violations,
            "central_control_commands": self.central_control_commands,
        }


@dataclass(frozen=True)
class _Envelope:
    deliver_at: float
    target_id: int
    message: TaskMessage


class MissionValidationRunner:
    """Advance independent mission agents over a deterministic message schedule."""

    dt = 0.1

    def __init__(self, contract: MissionContract, *, vehicle_count: int) -> None:
        if not isinstance(contract, MissionContract):
            raise TypeError("contract must be a MissionContract")
        if (
            isinstance(vehicle_count, bool)
            or not isinstance(vehicle_count, int)
            or vehicle_count < 2
        ):
            raise ValueError("vehicle_count must be at least two")
        self.contract = contract
        self.vehicle_count = vehicle_count

    @staticmethod
    def _state(vehicle_id: int, *, battery_pct: float = 90.0) -> AgentState:
        return AgentState(
            position_m=(5.0 + vehicle_id * 0.1, 5.0, 20.0),
            velocity_mps=(0.0, 0.0, 0.0),
            battery_pct=battery_pct,
            depth_age_s=0.0,
            localization_valid=True,
        )

    def run(self, scenario: MissionValidationScenario) -> MissionValidationEvidence:
        if not isinstance(scenario, MissionValidationScenario):
            raise TypeError("scenario must be a MissionValidationScenario")
        owner = 0 if scenario.vehicle_id is None else scenario.vehicle_id
        if not 0 <= owner < self.vehicle_count:
            raise ValueError("scenario vehicle ID falls outside the fleet")
        successor = 0 if owner != 0 else 1
        agents = [
            MissionAgent.for_contract(index, self.vehicle_count, self.contract)
            for index in range(self.vehicle_count)
        ]
        task_id = "search-0000"
        rng = np.random.default_rng(scenario.seed)
        sequences = [0 for _ in agents]
        latest_sequences: dict[tuple[int, int], int] = {}
        queue: list[_Envelope] = []
        replay_message: TaskMessage | None = None
        replay_injected = False
        partition_drops = 0
        stale_accepted = 0
        stale_rejected = 0
        safety_violations = 0
        central_commands = 0
        maximum_owners = 0
        released_at: float | None = None
        reopened_at: float | None = None
        reassigned_at: float | None = None

        def partition_allows(source: int, target: int, sent_at: float) -> bool:
            if scenario.kind != "partition_stale_replay":
                return True
            if not 2.0 <= sent_at < 5.0:
                return True
            midpoint = self.vehicle_count // 2
            return (source < midpoint) == (target < midpoint)

        def schedule(source: int, kind: str, payload: dict[str, object], now: float) -> None:
            nonlocal partition_drops, replay_message
            sequences[source] += 1
            message = TaskMessage(
                kind,  # type: ignore[arg-type]
                self.contract.mission_id,
                self.contract.digest,
                source,
                sequences[source],
                now,
                payload,
            )
            if replay_message is None and source == owner:
                replay_message = message
            for target in range(self.vehicle_count):
                if target == source:
                    continue
                if not partition_allows(source, target, now):
                    partition_drops += 1
                    continue
                delay = int(rng.integers(0, 3)) * self.dt
                queue.append(_Envelope(round(now + delay, 10), target, message))

        steps = int(round(scenario.duration_s / self.dt)) + 1
        for step in range(steps):
            now = round(step * self.dt, 10)
            inboxes: list[list[TaskMessage]] = [[] for _ in agents]
            remaining: list[_Envelope] = []
            for envelope in queue:
                if envelope.deliver_at > now:
                    remaining.append(envelope)
                    continue
                key = (envelope.target_id, envelope.message.sender_id)
                previous = latest_sequences.get(key)
                if previous is not None and envelope.message.sequence <= previous:
                    stale_rejected += 1
                    continue
                latest_sequences[key] = envelope.message.sequence
                inboxes[envelope.target_id].append(envelope.message)
            queue = remaining

            if (
                scenario.kind == "partition_stale_replay"
                and not replay_injected
                and now >= 6.0
                and replay_message is not None
            ):
                replay_injected = True
                for target in range(self.vehicle_count):
                    if target != replay_message.sender_id:
                        queue.append(_Envelope(now, target, replay_message))

            for vehicle_id, agent in enumerate(agents):
                battery = 90.0
                if (
                    scenario.kind == "low_battery"
                    and vehicle_id == owner
                    and now >= scenario.at_s
                ):
                    battery = self.contract.safety.minimum_battery_return_pct - 1.0
                if now < scenario.at_s:
                    bidding_enabled = vehicle_id == owner
                elif scenario.kind == "low_battery":
                    bidding_enabled = vehicle_id == successor
                else:
                    bidding_enabled = vehicle_id == owner
                decision = agent.step(
                    now,
                    self._state(vehicle_id, battery_pct=battery),
                    [],
                    tuple(inboxes[vehicle_id]),
                    [],
                    bidding_enabled=bidding_enabled,
                    preferred_task_ids=(task_id,) if bidding_enabled else (),
                )
                central_commands += decision.central_control_commands
                expected_safety = (
                    scenario.kind == "low_battery"
                    and vehicle_id == owner
                    and now >= scenario.at_s
                )
                if expected_safety:
                    safety_violations += int(decision.safety_phase != "return")
                else:
                    safety_violations += int(decision.safety_phase != "nominal")
                if decision.released_task_ids and released_at is None:
                    released_at = now
                    reopened_at = now
                for kind, payload in decision.outbound_messages:
                    schedule(vehicle_id, kind, payload, now)

            owners = sum(
                agent.ledger.assignment(task_id).status in {"claimed", "active"}
                and agent.ledger.assignment(task_id).winner_id == agent.vehicle_id
                for agent in agents
            )
            maximum_owners = max(maximum_owners, owners)
            if (
                scenario.kind == "low_battery"
                and reassigned_at is None
                and agents[successor].ledger.assignment(task_id).winner_id == successor
                and agents[successor].ledger.assignment(task_id).status
                in {"claimed", "active"}
            ):
                reassigned_at = now

        if replay_injected:
            stale_accepted = sum(
                1
                for (target, sender), sequence in latest_sequences.items()
                if sender == owner and sequence == replay_message.sequence
            )
        origin = scenario.at_s
        return MissionValidationEvidence(
            scenario=scenario.kind,
            seed=scenario.seed,
            task_id=task_id,
            task_release_s=(None if released_at is None else released_at - origin),
            task_reopen_s=(None if reopened_at is None else reopened_at - origin),
            task_reassign_s=(None if reassigned_at is None else reassigned_at - origin),
            maximum_simultaneous_owners=maximum_owners,
            stale_messages_accepted=stale_accepted,
            stale_messages_rejected=stale_rejected,
            partition_drops=partition_drops,
            safety_violations=safety_violations,
            central_control_commands=central_commands,
        )
