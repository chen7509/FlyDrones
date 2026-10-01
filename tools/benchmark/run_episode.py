#!/usr/bin/env python3
# ruff: noqa: E402 - script inserts repository src before importing FlyDrones
"""Run one controller against one isolated PX4/Gazebo world in WSL."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from flydrones.benchmark.ego import EgoController
from flydrones.benchmark.fly import FullFlyController
from flydrones.benchmark.gateway import Gateway, NativeGazeboPx4Backend
from flydrones.benchmark.provenance import load_benchmark_config
from flydrones.benchmark.runner import snapshot_episode_inputs, verify_freeze_manifest
from flydrones.benchmark.score import EpisodeScorer
from flydrones.benchmark.ulog_capture import episode_exit_code, ulog_evidence_failures
from flydrones.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--controller', choices=('fly_raw', 'fly_guided', 'ego'), required=True)
    parser.add_argument('--world-json', type=Path, required=True)
    parser.add_argument('--world-sdf', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/fly_ego_benchmark.yaml')
    parser.add_argument('--ego-endpoint', default='127.0.0.1:46200')
    parser.add_argument('--freeze-manifest', type=Path)
    args = parser.parse_args()

    config = load_benchmark_config(args.config)
    frozen = verify_freeze_manifest(args.freeze_manifest, ROOT) if args.freeze_manifest else None
    world = json.loads(args.world_json.read_text(encoding='utf-8'))
    args.output.mkdir(parents=True, exist_ok=True)
    result_path = args.output / 'result.json'
    if result_path.exists():
        raise SystemExit(f'refusing to overwrite completed episode: {result_path}')
    (args.output / 'started.json').write_text(json.dumps({
        'controller': args.controller,
        'seed': world['seed'],
        'started_wall_s': time.time(),
    }, indent=2), encoding='utf-8')
    episode_world_json, episode_world_sdf = snapshot_episode_inputs(
        args.world_json, args.world_sdf, args.output,
    )
    world = json.loads(episode_world_json.read_text(encoding='utf-8'))

    if args.controller == 'ego':
        controller = EgoController(args.ego_endpoint, config)
    else:
        fly_config = load_config(config['fly']['config'])
        controller = FullFlyController(
            fly_config, ROOT / config['fly']['model'], guided=args.controller == 'fly_guided',
        )
    backend = NativeGazeboPx4Backend(ROOT, args.output, world)
    gateway = Gateway(config, backend)
    scorer = EpisodeScorer(
        tuple(world['goal']), config['task']['goal_radius_m'],
        config['task']['goal_hold_s'], config['task']['timeout_s'],
    )
    decisions = []
    stage = 'infrastructure'
    started = time.perf_counter()
    try:
        gateway.start(episode_world_sdf)
        first_observation = gateway.observe()
        if args.controller.startswith('fly_'):
            controller.reset(int(world['seed']))
            controller.warmup(first_observation, seconds=2.1)
        else:
            controller.reset(int(world['seed']))
        scorer.update(backend.score_sample())
        while scorer.status is None:
            observation = gateway.observe()
            stage = 'controller'
            decision = controller.step(observation)
            stage = 'infrastructure'
            gateway.advance(decision.command)
            status = scorer.update(backend.score_sample())
            decisions.append({
                'sim_ns': observation.sim_ns,
                'frame_ns': observation.frame_ns,
                'position': observation.position,
                'command': {
                    'velocity_enu': decision.command.velocity_enu,
                    'yaw_rate': decision.command.yaw_rate,
                },
                'decision_wall_s': decision.elapsed_wall_s,
                'evidence': decision.evidence,
                'terminal': status,
            })
    except Exception as exc:
        scorer.fail('controller_error' if stage == 'controller' else 'infrastructure_error', repr(exc))
    finally:
        try:
            controller.close()
        finally:
            gateway.close()

    evidence_failures = ulog_evidence_failures(backend.ulog_evidence, backend.ulog_capture_error)
    payload = scorer.summary()
    payload.update({
        'controller': args.controller,
        'seed': world['seed'],
        'family': world['family'],
        'candidate': world.get('candidate'),
        'wall_s': time.perf_counter() - started,
        'decisions': decisions,
        'simulation': 'Gazebo Sim with PX4 SITL; fixed 50 ms steps while decision computation is paused',
        'contact_truth_available': True,
        'contact_message_count': backend.contact_message_count,
        'contact_records': backend.contact_records,
        'offboard_evidence': backend.offboard_evidence,
        'world_control_records': backend.control_records,
        'gz_partition': backend.partition,
        'freeze_manifest_sha256': frozen['manifest_sha256'] if frozen else None,
        'px4_ulogs': backend.ulog_evidence,
        'px4_ulog_capture_error': backend.ulog_capture_error,
        'evidence_failures': evidence_failures,
        'px4_ulog_capture_accepted': not evidence_failures,
    })
    temporary = args.output / 'result.json.tmp'
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(result_path)
    print(json.dumps({key: payload[key] for key in ('controller', 'seed', 'status', 'elapsed_sim_s', 'wall_s')}, indent=2))
    return episode_exit_code(payload['status'], evidence_failures)


if __name__ == '__main__':
    raise SystemExit(main())
