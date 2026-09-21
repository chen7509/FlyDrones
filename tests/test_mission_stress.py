from __future__ import annotations

import json
import time

from flydrones.mission_stress import (
    MissionStressConfig,
    _contract_for,
    _convergence_grace_seconds,
    _initial_position,
    _pop_bounded_assignment_batch,
    _preferred_task_sequences,
    _read_start_time,
    _reassignment_latencies,
    _recovery_reserve_map,
    _recovery_reserve_sequences,
    _refresh_grace_pending,
    _reserve_vehicle_ids,
    motion_peer_ids,
    overlay_survivors_converge,
    run_mission_process_trial,
)
from flydrones.task_consensus import TaskAssignment
from flydrones.task_udp import TaskMessage, encode_task_message


def test_start_marker_read_retries_transient_windows_file_lock() -> None:
    class FlakyStartFile:
        calls = 0

        def exists(self) -> bool:
            return True

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            self.calls += 1
            if self.calls == 1:
                raise PermissionError("transient scanner lock")
            return '{"start_at": 42.5}'

    path = FlakyStartFile()
    assert _read_start_time(path, time.monotonic() + 1.0, sleep=lambda _delay: None) == 42.5  # type: ignore[arg-type]
    assert path.calls == 2


def test_assignment_batch_is_sized_by_wire_encoder() -> None:
    pending = {
        f"confirm-{index}": TaskAssignment(
            f"confirm-{index}",
            "completed",
            index,
            10.0,
            2,
            None,
            "e" * 64,
            tuple(range(100)),
        )
        for index in range(4)
    }
    mission_id = "forest-search-confirm-rally"
    batch = _pop_bounded_assignment_batch(pending, mission_id, "a" * 64)
    encoded = encode_task_message(
        TaskMessage(
            "award",
            mission_id,
            "a" * 64,
            99,
            0xFFFFFFFF,
            75.12345678901234,
            {"assignments": batch},
        )
    )
    assert len(encoded) <= 1200
    assert len(batch) < 4
    assert pending


def test_compact_search_batch_uses_available_datagram_capacity() -> None:
    pending = {
        f"search-{index:04d}": TaskAssignment(
            f"search-{index:04d}",
            "completed",
            index,
            10.0,
            1,
            None,
            "e" * 64,
            (index,),
        )
        for index in range(12)
    }
    batch = _pop_bounded_assignment_batch(pending, "mission", "a" * 64)
    encoded = encode_task_message(
        TaskMessage("award", "mission", "a" * 64, 0, 1, 1.0, {"assignments": batch})
    )
    assert len(encoded) <= 1200
    assert len(batch) > 4


def test_terminal_anti_entropy_restarts_as_soon_as_a_full_cycle_is_sent() -> None:
    assignment = TaskAssignment(
        "search-0000", "completed", 0, 10.0, 1, None, "e" * 64, (0,)
    )
    pending: dict[str, TaskAssignment] = {}
    _refresh_grace_pending(pending, (assignment,), force=False)
    assert pending == {"search-0000": assignment}


def test_convergence_tail_scales_with_overlay_and_contract_size() -> None:
    assert _convergence_grace_seconds(5, 7) == 15.0
    assert _convergence_grace_seconds(8, 101) >= 23.0


def test_external_contract_path_is_the_trial_contract(tmp_path) -> None:
    source = {
        "schema_version": 1,
        "mission_id": "external-contract",
        "mission_type": "search_confirm_rally",
        "area_polygon_m": [[0, 0], [20, 0], [20, 20], [0, 20]],
        "search_cell_size_m": 20,
        "target_classes": ["person"],
        "confirmation_quorum": 2,
        "rally_position_m": [30, 10, 10],
        "deadline_s": 60,
        "safety": {
            "maximum_speed_mps": 5,
            "minimum_separation_m": 3,
            "geofence_margin_m": 5,
            "minimum_battery_return_pct": 30,
        },
    }
    path = tmp_path / "mission.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    loaded = _contract_for(
        MissionStressConfig(vehicle_count=2, failed_vehicle_ids=(), contract_path=path)
    )
    assert loaded.mission_id == "external-contract"


def test_reassignment_latency_is_measured_for_each_failed_active_task() -> None:
    failed = {
        "vehicle_id": 2,
        "status": "injected_failure",
        "final_assignments": [
            {"task_id": "search-0002", "status": "active", "winner_id": 2, "allocation_round": 1}
        ],
    }
    survivor = {
        "vehicle_id": 3,
        "status": "completed",
        "assignment_changes": [
            {"task_id": "search-0002", "t_s": 5.9, "winner_id": 3, "allocation_round": 2}
        ],
    }
    assert _reassignment_latencies([failed, survivor], {2}, failure_at_s=2.0) == {
        "search-0002": 3.9
    }


def test_same_round_new_owner_counts_as_task_reassignment() -> None:
    failed = {
        "vehicle_id": 2,
        "status": "injected_failure",
        "final_assignments": [
            {"task_id": "search-0002", "status": "active", "winner_id": 2, "allocation_round": 1}
        ],
    }
    survivor = {
        "vehicle_id": 3,
        "status": "completed",
        "assignment_changes": [
            {
                "task_id": "search-0002",
                "t_s": 5.0,
                "status": "claimed",
                "winner_id": 3,
                "allocation_round": 1,
            }
        ],
    }
    assert _reassignment_latencies([failed, survivor], {2}, failure_at_s=2.0) == {
        "search-0002": 3.0
    }


def test_failed_duplicate_already_completed_before_failure_needs_no_takeover() -> None:
    failed = {
        "vehicle_id": 2,
        "status": "injected_failure",
        "final_assignments": [
            {"task_id": "search-0002", "status": "active", "winner_id": 2, "allocation_round": 1}
        ],
    }
    survivor = {
        "vehicle_id": 3,
        "status": "completed",
        "assignment_changes": [
            {
                "task_id": "search-0002",
                "t_s": 1.5,
                "status": "completed",
                "winner_id": 3,
                "allocation_round": 0,
            }
        ],
    }
    assert _reassignment_latencies([failed, survivor], {2}, failure_at_s=2.0) == {}


def test_six_processes_finish_after_station_exit_and_reassign_failed_agent(tmp_path) -> None:
    config = MissionStressConfig(
        vehicle_count=6,
        output_dir=tmp_path,
        duration_s=8.0,
        rate_hz=10.0,
        search_columns=3,
        search_rows=2,
        failed_vehicle_ids=(2,),
        failure_at_s=2.0,
        partition_window_s=(3.0, 4.0),
        low_battery_vehicle_id=4,
        depth_freeze_vehicle_id=5,
        sensor_fault_at_s=5.0,
        task_udp_base_port=0,
        motion_udp_base_port=0,
    )
    summary = run_mission_process_trial(config)
    assert summary["checks"]["task_station_absent_during_control"]
    assert summary["checks"]["one_process_per_vehicle"]
    assert summary["checks"]["failed_tasks_reassigned"]
    assert summary["checks"]["ledgers_converged_after_partition"]
    assert summary["metrics"]["central_control_commands"] == 0
    assert summary["metrics"]["collisions"] == 0
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "report.md").exists()
    assert len(json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["worker_pids"]) == 6


def test_overlay_anti_entropy_survives_ten_adjacent_failures() -> None:
    removed = tuple(range(7, 17))
    result = overlay_survivors_converge(24, removed)
    assert result["connected"]
    assert result["survivor_count"] == 14
    assert result["all_records_delivered"]


def test_motion_safety_channel_reaches_every_physical_peer() -> None:
    assert motion_peer_ids(50, 100) == tuple(range(100))


def test_injected_failure_vehicle_starts_high_enough_to_hold_an_active_lease() -> None:
    mission = _contract_for(
        MissionStressConfig(vehicle_count=6, failed_vehicle_ids=(2,), search_columns=3, search_rows=2)
    )
    units = [unit for unit in mission.expand_work_units() if unit.kind == "search_cell"]
    normal = _initial_position(1, (2,), units)
    failing = _initial_position(2, (2,), units)
    assert normal[2] == units[1].center_m[2]
    assert failing[2] - units[2].center_m[2] == 60.0


def test_reserve_ids_are_alive_and_exclude_sensor_fault_nodes() -> None:
    config = MissionStressConfig(vehicle_count=24, failed_vehicle_ids=tuple(range(7, 17)))
    reserves = _reserve_vehicle_ids(config)
    assert len(reserves) == 10
    assert not set(reserves) & set(config.failed_vehicle_ids)
    assert config.low_battery_vehicle_id not in reserves
    assert config.depth_freeze_vehicle_id not in reserves
    mission = _contract_for(config)
    units = [unit for unit in mission.expand_work_units() if unit.kind == "search_cell"]
    mapping = _recovery_reserve_map(config, units)
    expected_tasks = {units[item % len(units)].task_id for item in config.failed_vehicle_ids}
    assert set(mapping.values()) == expected_tasks
    sequences = _recovery_reserve_sequences(config, units)
    assert all(sequence[1] == units[reserve_id].task_id for reserve_id, sequence in sequences.items())
    all_sequences = _preferred_task_sequences(config, units)
    assert all_sequences[0] == (units[0].task_id,)
    assert all_sequences[reserves[0]] == sequences[reserves[0]]
