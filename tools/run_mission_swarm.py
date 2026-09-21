from __future__ import annotations

import argparse
import json

from flydrones.mission_stress import MissionStressConfig, run_mission_process_trial


def parse_ids(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in value.split(",") if item.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Run autonomous multi-process mission simulation")
    parser.add_argument("--contract", help="Reserved for a future external validated contract")
    parser.add_argument("--vehicles", type=int, default=100)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--output", default="results/mission-swarm-100")
    parser.add_argument("--failed-ids", type=parse_ids, default=parse_ids("8,17,29,41,52,63,74,85,91,97"))
    parser.add_argument("--failure-at", type=float, default=8.0)
    parser.add_argument("--partition-start", type=float, default=12.0)
    parser.add_argument("--partition-end", type=float, default=17.0)
    parser.add_argument("--low-battery-id", type=int, default=4)
    parser.add_argument("--depth-freeze-id", type=int, default=11)
    parser.add_argument("--sensor-fault-at", type=float, default=6.0)
    parser.add_argument("--seed", type=int, default=20260921)
    args = parser.parse_args()
    summary = run_mission_process_trial(
        MissionStressConfig(
            vehicle_count=args.vehicles,
            output_dir=args.output,
            duration_s=args.duration,
            failed_vehicle_ids=args.failed_ids,
            failure_at_s=args.failure_at,
            partition_window_s=(args.partition_start, args.partition_end),
            low_battery_vehicle_id=args.low_battery_id,
            depth_freeze_vehicle_id=args.depth_freeze_id,
            sensor_fault_at_s=args.sensor_fault_at,
            seed=args.seed,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
