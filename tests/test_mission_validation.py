from __future__ import annotations

from flydrones.mission_contract import MissionContract
from flydrones.mission_validation import (
    MissionValidationRunner,
    MissionValidationScenario,
)


def contract() -> MissionContract:
    return MissionContract.from_dict(
        {
            "schema_version": 1,
            "mission_id": "validation-test",
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


def test_low_battery_releases_and_healthy_peer_reassigns_without_double_owner():
    evidence = MissionValidationRunner(contract(), vehicle_count=5).run(
        MissionValidationScenario.low_battery(seed=12, vehicle_id=1, at_s=5.0)
    )

    assert evidence.task_release_s <= 3.0
    assert evidence.task_reopen_s <= 3.2
    assert evidence.task_reassign_s <= 5.0
    assert evidence.maximum_simultaneous_owners == 1
    assert evidence.central_control_commands == 0


def test_partition_and_stale_messages_cannot_change_safe_state():
    evidence = MissionValidationRunner(contract(), vehicle_count=5).run(
        MissionValidationScenario.partition_with_stale_replay(seed=13)
    )

    assert evidence.stale_messages_accepted == 0
    assert evidence.safety_violations == 0
    assert evidence.central_control_commands == 0


def test_validation_is_deterministic_for_the_same_seed():
    runner = MissionValidationRunner(contract(), vehicle_count=5)
    scenario = MissionValidationScenario.low_battery(
        seed=21, vehicle_id=2, at_s=4.0
    )

    assert runner.run(scenario) == runner.run(scenario)
