#!/usr/bin/env python3
"""Run the real 166,700-neuron controller for warmup plus ten scored ticks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from flydrones.benchmark.contract import Observation
from flydrones.benchmark.fly import FullFlyController
from flydrones.config import load_config


def observation(sim_ns: int) -> Observation:
    return Observation(
        sim_ns=sim_ns,
        frame_ns=sim_ns,
        rgb=np.full((120, 160, 3), 127, np.uint8),
        depth_m=np.full((120, 160), 8.0, np.float32),
        camera_pose=(0.0, 0.0, 1.5, 0.0, 0.0, 0.0, 1.0),
        position=(0.0, 0.0, 1.5),
        velocity=(0.0, 0.0, 0.0),
        yaw=0.0,
        yaw_rate=0.0,
        goal=(8.0, 0.0, 1.5),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cfg = load_config('configs/forest-trained-v2.yaml')
    controller = FullFlyController(cfg, Path('data/malecns_full.npz'), guided=False)
    controller.warmup(observation(0), seconds=2.1)
    decisions = [controller.step(observation((index + 1) * 50_000_000)) for index in range(10)]
    payload = {
        'accepted': True,
        'scope': 'full-connectome adapter integration probe, not benchmark results',
        'cycles': len(decisions),
        'neurons': decisions[-1].evidence['neurons'],
        'connections': decisions[-1].evidence['connections'],
        'model_sha256': decisions[-1].evidence['model_sha256'],
        'brain_wall_s': [decision.evidence['brain_wall_s'] for decision in decisions],
        'spikes': [decision.evidence['spikes'] for decision in decisions],
        'commands': [
            {
                'velocity_enu': decision.command.velocity_enu,
                'yaw_rate': decision.command.yaw_rate,
            }
            for decision in decisions
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
