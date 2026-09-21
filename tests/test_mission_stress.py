from __future__ import annotations

import json
import time

from flydrones.mission_stress import (
    MissionStressConfig,
    _pop_bounded_assignment_batch,
    _read_start_time,
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
    batch = _pop_bounded_assignment_batch(pending, "mission", "a" * 64)
    encoded = encode_task_message(
        TaskMessage("award", "mission", "a" * 64, 0, 1, 1.0, {"assignments": batch})
    )
    assert len(encoded) <= 1200
    assert len(batch) < 4
    assert pending


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
