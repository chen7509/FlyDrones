"""Collect Gazebo clock, process, and optional GPU evidence for one trial."""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import threading
import time
from pathlib import Path


def _stat_fields(text: str) -> list[str]:
    closing = text.rfind(")")
    if closing < 0:
        raise ValueError("malformed /proc stat")
    return text[closing + 1:].split()


def read_proc_metrics(
    pid: int,
    *,
    proc_root: Path = Path("/proc"),
    clock_ticks: int | None = None,
    page_size: int | None = None,
) -> dict[str, float | int]:
    ticks = clock_ticks or os.sysconf("SC_CLK_TCK")
    page = page_size or os.sysconf("SC_PAGE_SIZE")
    fields = _stat_fields((proc_root / str(pid) / "stat").read_text(encoding="utf-8"))
    statm = (proc_root / str(pid) / "statm").read_text(encoding="utf-8").split()
    return {
        "cpu_user_s": int(fields[11]) / ticks,
        "cpu_system_s": int(fields[12]) / ticks,
        "rss_bytes": int(statm[1]) * page,
        "threads": int(fields[17]),
    }


def parse_nvidia_smi(text: str) -> dict[str, float | str]:
    try:
        utilization, memory = (part.strip() for part in text.strip().split(",", 1))
        return {
            "gpu_utilization_percent": float(utilization),
            "memory_used_mib": float(memory),
        }
    except (TypeError, ValueError):
        return {
            "gpu_utilization_percent": "unavailable",
            "memory_used_mib": "unavailable",
        }


def _gpu_metrics() -> dict[str, float | str]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi.exe",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        return parse_nvidia_smi(result.stdout) if result.returncode == 0 else parse_nvidia_smi("")
    except (OSError, subprocess.SubprocessError):
        return parse_nvidia_smi("")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--completion-marker", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, default=300.0)
    args = parser.parse_args()

    from gz.msgs10.clock_pb2 import Clock
    from gz.transport13 import Node

    args.output_dir.mkdir(parents=True, exist_ok=True)
    clock_handle = (args.output_dir / "clock-probe.csv").open("w", newline="", encoding="utf-8", buffering=1)
    resource_handle = (args.output_dir / "resource-probe.csv").open(
        "w", newline="", encoding="utf-8", buffering=1
    )
    gpu_handle = (args.output_dir / "gpu-probe.csv").open("w", newline="", encoding="utf-8", buffering=1)
    clock_writer = csv.writer(clock_handle)
    resource_writer = csv.DictWriter(
        resource_handle,
        fieldnames=("monotonic_s", "pid", "cpu_user_s", "cpu_system_s", "rss_bytes", "threads"),
    )
    gpu_writer = csv.DictWriter(
        gpu_handle,
        fieldnames=("monotonic_s", "gpu_utilization_percent", "memory_used_mib"),
    )
    clock_writer.writerow(("monotonic_s", "sim_ns", "wall_gap_ms", "sim_gap_ms", "seen"))
    resource_writer.writeheader()
    gpu_writer.writeheader()

    lock = threading.Lock()
    last_clock: tuple[float, int] | None = None
    seen = 0

    def on_clock(message) -> None:
        nonlocal last_clock, seen
        now = time.monotonic()
        sim_ns = int(message.sim.sec) * 1_000_000_000 + int(message.sim.nsec)
        with lock:
            previous = last_clock
            last_clock = (now, sim_ns)
            seen += 1
            clock_writer.writerow((
                f"{now:.6f}",
                sim_ns,
                f"{(now - previous[0]) * 1000 if previous else 0:.6f}",
                f"{(sim_ns - previous[1]) / 1e6 if previous else 0:.6f}",
                seen,
            ))

    node = Node()
    if not node.subscribe(Clock, "/clock", on_clock):
        raise RuntimeError("failed to subscribe to Gazebo /clock")

    deadline = time.monotonic() + args.duration_s
    gazebo_pid = None
    next_gpu = 0.0
    try:
        while time.monotonic() < deadline and not args.completion_marker.exists():
            now = time.monotonic()
            if gazebo_pid is None and (args.run_dir / "gazebo.pid").exists():
                gazebo_pid = int((args.run_dir / "gazebo.pid").read_text(encoding="utf-8").strip())
            if gazebo_pid is not None:
                try:
                    resource_writer.writerow({"monotonic_s": f"{now:.6f}", "pid": gazebo_pid,
                                              **read_proc_metrics(gazebo_pid)})
                except (FileNotFoundError, ProcessLookupError):
                    gazebo_pid = None
            if now >= next_gpu:
                gpu_writer.writerow({"monotonic_s": f"{now:.6f}", **_gpu_metrics()})
                next_gpu = now + 0.5
            time.sleep(0.05)
    finally:
        node.unsubscribe("/clock")
        clock_handle.close()
        resource_handle.close()
        gpu_handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
