from __future__ import annotations

import hashlib
import subprocess
import sys

from flydrones.mission_agent import AgentState, Detection, MissionAgent
from flydrones.mission_contract import MissionContract
from flydrones.peer_udp import PeerTrack
from flydrones.task_consensus import Bid, TaskAssignment
from flydrones.task_udp import TaskMessage


def test_mission_agent_import_is_lightweight_for_100_process_startup() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import flydrones.mission_agent; raise SystemExit('numpy' in sys.modules)",
        ],
        check=False,
    )
    assert result.returncode == 0


def contract() -> MissionContract:
    return MissionContract.from_dict(
        {
            "schema_version": 1,
            "mission_id": "agent-test",
            "mission_type": "search_confirm_rally",
            "area_polygon_m": [[0, 0], [40, 0], [40, 40], [0, 40]],
            "search_cell_size_m": 20,
            "target_classes": ["person"],
            "confirmation_quorum": 2,
            "rally_position_m": [50, 20, 20],
            "deadline_s": 60,
            "safety": {
                "maximum_speed_mps": 8,
                "minimum_separation_m": 3,
                "geofence_margin_m": 5,
                "minimum_battery_return_pct": 30,
            },
        }
    )


def healthy_state(**overrides: object) -> AgentState:
    values: dict[str, object] = {
        "position_m": (10.0, 10.0, 20.0),
        "velocity_mps": (0.0, 0.0, 0.0),
        "battery_pct": 90.0,
        "depth_age_s": 0.0,
        "localization_valid": True,
    }
    values.update(overrides)
    return AgentState(**values)  # type: ignore[arg-type]


def active_agent() -> MissionAgent:
    agent = MissionAgent.for_contract(0, 10, contract())
    agent.step(now=0.0, state=healthy_state(), peer_tracks=[], messages=[], detections=[])
    agent.step(now=0.3, state=healthy_state(), peer_tracks=[], messages=[], detections=[])
    return agent


def test_agent_progresses_without_task_station_or_central_commands() -> None:
    agent = MissionAgent.for_contract(4, 10, contract())
    first = agent.step(0.0, healthy_state(), [], [], [])
    assert first.phase == "auction"
    claimed = agent.step(0.3, healthy_state(), [], [], [])
    assert claimed.phase in {"transit", "execute"}
    assert claimed.intent.source == "local-task-planner"
    assert claimed.central_control_commands == 0


def test_depth_freeze_and_low_battery_release_active_task_once() -> None:
    agent = active_agent()
    held = agent.step(1.0, healthy_state(depth_age_s=0.51), [], [], [])
    assert held.intent.velocity_mps == (0.0, 0.0, 0.0)
    landed = agent.step(3.01, healthy_state(depth_age_s=2.51), [], [], [])
    repeated = agent.step(3.11, healthy_state(depth_age_s=2.61), [], [], [])
    assert landed.safety_phase == "land"
    assert landed.released_task_ids == ("search-0000",)
    assert repeated.released_task_ids == ()

    battery_agent = active_agent()
    decision = battery_agent.step(1.0, healthy_state(battery_pct=29.0), [], [], [])
    assert decision.safety_phase == "return"
    assert decision.released_task_ids == ("search-0000",)
    release_messages = [payload for kind, payload in decision.outbound_messages if kind == "award"]
    assert release_messages[0]["assignment"]["status"] == "open"


def test_invalid_localization_and_geofence_preempt_tasks() -> None:
    invalid = active_agent().step(
        1.0,
        healthy_state(localization_valid=False),
        [],
        [],
        [],
    )
    assert invalid.safety_phase == "land"
    outside = active_agent().step(
        1.0,
        healthy_state(position_m=(-20.0, 10.0, 20.0)),
        [],
        [],
        [],
    )
    assert outside.safety_phase == "return"


def test_contract_rally_point_is_inside_the_allowed_mission_corridor() -> None:
    agent = MissionAgent.for_contract(0, 10, contract())
    decision = agent.step(
        0.0,
        healthy_state(position_m=contract().rally_position_m),
        [],
        [],
        [],
    )
    assert decision.safety_phase == "nominal"


def test_peer_avoidance_overrides_task_velocity_and_clamps_speed() -> None:
    agent = active_agent()
    track = PeerTrack(
        sender_id=1,
        sequence=1,
        sent_at=0.9,
        received_at=0.9,
        position=(11.0, 10.0, 20.0),
        velocity=(-2.0, 0.0, 0.0),
    )
    decision = agent.step(1.0, healthy_state(velocity_mps=(2.0, 0.0, 0.0)), [track], [], [])
    assert decision.intent.source == "local-separation"
    speed = sum(value * value for value in decision.intent.velocity_mps) ** 0.5
    assert speed <= contract().safety.maximum_speed_mps


def test_peer_avoidance_uses_margin_before_contract_minimum_is_breached() -> None:
    agent = active_agent()
    track = PeerTrack(1, 1, 0.9, 0.9, (15.5, 10.0, 20.0), (0.0, 0.0, 0.0))
    decision = agent.step(1.0, healthy_state(), [track], [], [])
    assert decision.intent.source == "local-separation"


def test_higher_vehicle_uses_upward_escape_near_shared_target() -> None:
    agent = MissionAgent.for_contract(5, 10, contract())
    agent.step(0.0, healthy_state(), [], [], [])
    agent.step(0.3, healthy_state(), [], [], [])
    track = PeerTrack(1, 1, 0.9, 0.9, (10.5, 10.0, 20.0), (0.0, 0.0, 0.0))
    decision = agent.step(1.0, healthy_state(), [track], [], [])
    assert decision.intent.source == "local-separation"
    assert decision.intent.velocity_mps[2] > 0.0


def test_low_battery_return_still_passes_through_peer_separation() -> None:
    agent = active_agent()
    track = PeerTrack(1, 1, 0.9, 0.9, (10.5, 10.0, 20.0), (0.0, 0.0, 0.0))
    decision = agent.step(1.0, healthy_state(battery_pct=29.0), [track], [], [])
    assert decision.safety_phase == "return"
    assert decision.intent.source == "local-separation"


def test_safety_preemption_ignores_stale_pointer_to_remotely_reassigned_task() -> None:
    agent = active_agent()
    agent.ledger.expire(now=4.0)
    agent.ledger.observe_bid(Bid("search-0000", 3, 9.0, 1, 4.0), now=4.0)
    decision = agent.step(5.0, healthy_state(battery_pct=29.0), [], [], [])
    assert decision.safety_phase == "return"
    assert decision.released_task_ids == ()


def test_detection_creates_one_deterministic_confirmation_task() -> None:
    agent = MissionAgent.for_contract(0, 10, contract())
    detection = Detection("person", (10.2, 19.7, 20.0), 0.95, "b" * 64)
    first = agent.step(0.0, healthy_state(), [], [], [detection])
    second = agent.step(0.1, healthy_state(), [], [], [detection])
    expected = hashlib.sha256(b"person|10|20|20|" + b"b" * 64).hexdigest()[:12]
    assert f"confirm-{expected}" in agent.work_unit_ids
    assert sum(message[0] == "evidence" for message in first.outbound_messages) == 1
    assert all(message[0] != "evidence" for message in second.outbound_messages)


def test_confirmation_quorum_needs_distinct_vehicle_ids() -> None:
    agent = MissionAgent.for_contract(0, 10, contract())
    detection = Detection("person", (10.0, 20.0, 20.0), 0.9, "b" * 64)
    agent.step(0.0, healthy_state(), [], [], [detection])
    task_id = next(item for item in agent.work_unit_ids if item.startswith("confirm-"))
    agent.ledger.complete(task_id, 3, "c" * 64, now=1.0)
    agent.ledger.complete(task_id, 3, "c" * 64, now=1.1)
    assert agent.ledger.assignment(task_id).status != "completed"
    agent.ledger.complete(task_id, 8, "d" * 64, now=1.2)
    assert agent.ledger.assignment(task_id).status == "completed"


def test_low_connectivity_creates_one_relay_per_five_second_epoch() -> None:
    agent = MissionAgent.for_contract(2, 10, contract())
    agent.step(0.0, healthy_state(), [], [], [])
    first = agent.step(2.01, healthy_state(), [], [], [])
    second = agent.step(2.2, healthy_state(), [], [], [])
    assert "relay-2-0" in agent.work_unit_ids
    assert sum(kind == "award" for kind, _payload in first.outbound_messages) >= 1
    assert agent.work_unit_ids.count("relay-2-0") == 1
    assert all(payload.get("task_id") != "relay-2-0" for _kind, payload in second.outbound_messages)


def test_land_is_terminal_and_completed_tasks_do_not_regress() -> None:
    agent = active_agent()
    landed = agent.step(1.0, healthy_state(localization_valid=False), [], [], [])
    recovered = agent.step(2.0, healthy_state(), [], [], [])
    assert landed.phase == recovered.phase == "land"
    assert recovered.intent.velocity_mps == (0.0, 0.0, 0.0)

    task_id = "search-0000"
    agent.ledger.complete(task_id, 0, "e" * 64, now=2.1)
    agent.ledger.expire(now=100.0)
    assert agent.ledger.assignment(task_id).status == "completed"


def test_agent_merges_batched_terminal_awards() -> None:
    agent = MissionAgent.for_contract(0, 10, contract())
    assignments = [
        TaskAssignment(f"search-{index:04d}", "completed", index, 10.0, 0, None, "e" * 64, (index,))
        for index in (0, 1)
    ]
    message = TaskMessage(
        "award",
        contract().mission_id,
        contract().digest,
        3,
        1,
        1.0,
        {"assignments": [assignment.__dict__ for assignment in assignments]},
    )
    agent.ingest_messages([message], now=1.0)
    assert agent.ledger.assignment("search-0000").status == "completed"
    assert agent.ledger.assignment("search-0001").status == "completed"


def test_reopened_higher_round_task_is_bid_before_fresh_nearby_task() -> None:
    agent = MissionAgent.for_contract(0, 10, contract())
    agent.ledger.merge_assignment(
        TaskAssignment("search-0000", "open", None, None, 2, None, None, ()),
        now=0.0,
    )
    decision = agent.step(
        0.0,
        healthy_state(position_m=(30.0, 30.0, 20.0)),
        [],
        [],
        [],
    )
    bids = [payload for kind, payload in decision.outbound_messages if kind == "bid"]
    assert bids[0]["task_id"] == "search-0000"


def test_active_search_is_not_abandoned_for_remote_reauction() -> None:
    agent = active_agent()
    agent.ledger.merge_assignment(
        TaskAssignment("search-0001", "open", None, None, 2, None, None, ()),
        now=0.9,
    )
    decision = agent.step(1.0, healthy_state(), [], [], [])
    bids = [payload for kind, payload in decision.outbound_messages if kind == "bid"]
    releases = [payload for kind, payload in decision.outbound_messages if kind == "award"]
    assert bids == []
    assert releases == []
