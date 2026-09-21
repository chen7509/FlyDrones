"""Run deterministic randomized stress cases for the hybrid local planner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flydrones.local_planner_stress import run_local_planner_stress


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--scenarios", type=int, default=100)
    parser.add_argument("--output", default="results/local-planner-stress")
    args = parser.parse_args()

    result = run_local_planner_stress(args.seed, args.scenarios)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    metrics = result["metrics"]
    report = f"""# 混合局部规划器随机压力测试

{'**通过。**' if result['accepted'] else '**未通过。**'} 共执行 {metrics['scenarios']} 个确定性随机场景。

- 通过：{metrics['passed']}/{metrics['scenarios']}
- 静态障碍接触：{metrics['static_contacts']}
- 邻机接触：{metrics['peer_contacts']}
- 最小静态净空：{metrics['minimum_static_clearance_m']} m
- 最小机间距：{metrics['minimum_peer_separation_m']} m
- 超时：{metrics['timeouts']}
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
