"""Aggregate consecutive PX4/Gazebo hybrid-planner runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flydrones.px4_repeatability import evaluate_px4_repetitions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+")
    parser.add_argument("--required", type=int, default=5)
    parser.add_argument("--output", default="results/px4-hybrid-repeatability")
    args = parser.parse_args()

    result = evaluate_px4_repetitions(args.run_dirs, required=args.required)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metrics = result["metrics"]
    failure_lines = "\n".join(
        f"- 第 {failure['run']} 次：{failure['category']} ({failure['path']})"
        for failure in result["failures"]
    ) or "- 无"
    report = f"""# PX4/Gazebo 混合规划器连续试验

{'**通过。**' if result['accepted'] else '**未通过。**'} 最终连续通过 {metrics['consecutive_passes']} 次，要求 {args.required} 次。

- 总运行：{metrics['runs']}
- 通过运行：{metrics['passing_runs']}
- 最差规划 P95：{metrics['worst_planner_p95_ms']} ms
- 最小树木净空：{metrics['minimum_forest_clearance_m']} m
- 最小机间距：{metrics['minimum_intervehicle_distance_m']} m
- 中央控制命令：{metrics['central_control_commands']}

## 失败分类

{failure_lines}
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
