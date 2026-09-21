"""Run and report 20/100-process broker-free UDP swarm stress trials."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flydrones.distributed_stress import StressTrialConfig, run_udp_process_trial  # noqa: E402


def _plot_trial(output: Path, vehicle_count: int) -> None:
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(9.6, 9.0), constrained_layout=True)
    colors = plt.cm.turbo([index / max(1, vehicle_count - 1) for index in range(vehicle_count)])
    for vehicle_id, color in enumerate(colors):
        with (output / f"agent-{vehicle_id}.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        x = [float(row["x_m"]) for row in rows]
        y = [float(row["y_m"]) for row in rows]
        axis.plot(x, y, color=color, linewidth=0.8 if vehicle_count > 20 else 1.4, alpha=0.8)
        axis.scatter(x[0], y[0], color=color, s=8)
        axis.scatter(x[-1], y[-1], color=color, marker="x", s=12)
    axis.set_aspect("equal")
    axis.grid(alpha=0.2)
    axis.set(xlabel="East (m)", ylabel="North (m)")
    axis.set_title(f"{vehicle_count} independent processes — UDP-local swarm trajectories")
    figure.savefig(output / "trajectories.png", dpi=180)
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="results/distributed-udp-stress")
    parser.add_argument("--vehicles", default="20,100")
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--rate", type=float, default=10.0)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    counts = [int(value) for value in args.vehicles.split(",") if value.strip()]
    summaries = []
    for count in counts:
        layers = max(1, math.ceil(count / 20))
        output = root / f"{count}-processes"
        print(f"running {count} independent UDP agents...", flush=True)
        config = StressTrialConfig(
            vehicle_count=count,
            output_dir=output,
            duration_s=args.duration,
            rate_hz=args.rate,
            altitude_layers=layers,
        )
        summary = run_udp_process_trial(config)
        summaries.append(summary)
        _plot_trial(output, count)
        metrics = summary["metrics"]
        print(
            f"  accepted={summary['accepted']} arrived={metrics['arrived']}/{count} "
            f"min_sep={metrics['minimum_intervehicle_distance_m']}m "
            f"udp_rx={metrics['udp_received_packets']}",
            flush=True,
        )
    checks = {
        "all_scales_accepted": all(summary["accepted"] for summary in summaries),
        "zero_collisions": sum(summary["metrics"]["collisions"] for summary in summaries) == 0,
        "one_process_per_vehicle": all(
            summary["metrics"]["controller_processes"] == count
            for count, summary in zip(counts, summaries)
        ),
        "zero_direct_global_neighbor_reads": all(
            summary["metrics"]["direct_global_neighbor_reads"] == 0 for summary in summaries
        ),
    }
    aggregate = {
        "accepted": all(checks.values()),
        "checks": checks,
        "trials": {str(count): summary for count, summary in zip(counts, summaries)},
    }
    (root / "aggregate-summary.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = "\n".join(
        f"| {count} | {summary['metrics']['controller_processes']} | "
        f"{summary['metrics']['arrived']}/{count} | {summary['metrics']['collisions']} | "
        f"{summary['metrics']['minimum_intervehicle_distance_m']:.3f} | "
        f"{summary['metrics']['udp_attempted_packets']} | {summary['metrics']['udp_received_packets']} | "
        f"{'通过' if summary['accepted'] else '未通过'} |"
        for count, summary in zip(counts, summaries)
    )
    report = f"""# 多进程 UDP 去中心化扩展试验

{'**全部通过。**' if aggregate['accepted'] else '**存在未通过项目。**'} 每一架逻辑无人机由一个独立操作系统进程控制，
父进程只发出静态试验参数和同步开始信号，并在全部进程退出后读取轨迹。控制期间没有中央遥测表或避碰指令。

| 无人机数 | 控制进程 | 抵达 | 碰撞 | 最小机间距 (m) | UDP 尝试发送 | UDP 接收 | 结果 |
|---:|---:|---:|---:|---:|---:|---:|:---:|
{rows}

所有进程使用与五机 PX4 试验相同的 `UdpPeerNode` 二进制报文、延迟队列、随机丢包、断联窗口和本地过期缓存。
轨迹采用多高度层、相邻层反向高速穿越；各控制器只从自己的目标、状态和 UDP 缓存计算速度与局部避让。

本试验验证单机计算机上的进程隔离和 UDP 通信规模，不等于 100 架真实飞行器的无线容量、定位精度或飞行安全认证。
"""
    (root / "报告.md").write_text(report, encoding="utf-8")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2), flush=True)
    return 0 if aggregate["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
