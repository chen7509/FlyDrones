"""Generate the compact five-lane Gazebo forest used by PX4 SITL."""

from __future__ import annotations

import argparse
from pathlib import Path

from flydrones.sitl_swarm import px4_swarm_obstacles, render_gazebo_forest_world


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="results/px4-sitl-five/flydrones_forest.sdf")
    parser.add_argument("--lane-spacing", type=float, default=1.5)
    parser.add_argument("--preload-vehicles", type=int, choices=(0, 1, 2, 5), default=0)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_gazebo_forest_world(
            px4_swarm_obstacles(lane_spacing_m=args.lane_spacing),
            vehicle_poses_y=(
                tuple(
                    (vehicle_id - (args.preload_vehicles - 1) / 2) * args.lane_spacing
                    for vehicle_id in range(args.preload_vehicles)
                )
                if args.preload_vehicles
                else None
            ),
        ),
        encoding="utf-8",
    )
    print(f"generated: {output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
