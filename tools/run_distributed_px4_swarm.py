"""Launch five independent PX4 workers and score their completed artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from flydrones.distributed_px4 import (
    aggregate_distributed_artifacts,
    build_distributed_agent_commands,
    evaluate_gps_fault_artifacts,
)


def _clean_previous_worker_artifacts(output_dir: Path, vehicle_count: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    names = {"flight.csv", "summary.json", "五进程去中心化报告.md"}
    for vehicle_id in range(vehicle_count):
        names.update({
            f"agent-{vehicle_id}.csv",
            f"agent-{vehicle_id}.json",
            f"agent-{vehicle_id}.stdout.log",
            f"agent-{vehicle_id}.stderr.log",
        })
    for name in names:
        path = output_dir / name
        if path.is_file():
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="results/px4-sitl-five-process-udp")
    parser.add_argument("--model", default="results/autonomous-forest-ppo-v1/autonomous-policy-numpy.npz")
    parser.add_argument("--mission-timeout", type=float, default=70.0)
    parser.add_argument("--process-timeout", type=float, default=150.0)
    parser.add_argument("--peer-base-port", type=int, default=16770)
    parser.add_argument("--gps-failure-vehicle", type=int)
    parser.add_argument("--gps-failure-at", type=float, default=12.0)
    parser.add_argument("--gps-failure-mode", choices=("off", "stuck", "wrong", "fusion-off"), default="off")
    parser.add_argument("--expect-fault-landing", action="store_true")
    args = parser.parse_args()
    if args.expect_fault_landing and args.gps_failure_vehicle is None:
        parser.error("--expect-fault-landing requires --gps-failure-vehicle")

    vehicle_count = 5
    output_dir = Path(args.output).resolve()
    _clean_previous_worker_artifacts(output_dir, vehicle_count)
    script = Path(__file__).with_name("px4_distributed_agent.py")
    commands = build_distributed_agent_commands(
        python_executable=sys.executable,
        agent_script=script,
        output_dir=output_dir,
        model_path=Path(args.model).resolve(),
        vehicle_count=vehicle_count,
        peer_base_port=args.peer_base_port,
        mission_timeout_s=args.mission_timeout,
        gps_failure_vehicle_id=args.gps_failure_vehicle,
        gps_failure_at_s=args.gps_failure_at,
        gps_failure_mode=args.gps_failure_mode,
    )

    processes: list[subprocess.Popen] = []
    log_handles = []
    try:
        for vehicle_id, command in enumerate(commands):
            stdout_handle = (output_dir / f"agent-{vehicle_id}.stdout.log").open("w", encoding="utf-8")
            stderr_handle = (output_dir / f"agent-{vehicle_id}.stderr.log").open("w", encoding="utf-8")
            log_handles.extend((stdout_handle, stderr_handle))
            processes.append(subprocess.Popen(command, stdout=stdout_handle, stderr=stderr_handle))

        deadline = time.monotonic() + args.process_timeout
        while any(process.poll() is None for process in processes):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"distributed PX4 workers exceeded {args.process_timeout:.1f}s")
            time.sleep(0.2)
    except BaseException:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
        raise
    finally:
        for handle in log_handles:
            handle.close()

    exit_codes = [process.returncode for process in processes]
    if any(code != 0 for code in exit_codes) and not args.expect_fault_landing:
        print(json.dumps({"worker_exit_codes": exit_codes}, indent=2))
        return 2

    if args.expect_fault_landing:
        _trace, summary = evaluate_gps_fault_artifacts(
            output_dir,
            fault_vehicle_id=args.gps_failure_vehicle,
            vehicle_count=vehicle_count,
        )
    else:
        _trace, summary = aggregate_distributed_artifacts(output_dir, vehicle_count=vehicle_count)
    summary["metrics"]["worker_exit_codes"] = exit_codes
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
