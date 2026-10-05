#!/usr/bin/env python3
# ruff: noqa: E402 - script inserts repository src before importing FlyDrones
"""Run one controller against one isolated PX4/Gazebo world in WSL."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from flydrones.benchmark.camera_info_capture import camera_info_capture_failures
from flydrones.benchmark.contract import Command
from flydrones.benchmark.ego import EgoController
from flydrones.benchmark.fly import FullFlyController
from flydrones.benchmark.gateway import Gateway, NativeGazeboPx4Backend
from flydrones.benchmark.provenance import load_benchmark_config
from flydrones.benchmark.rgb_capture import rgb_capture_failures
from flydrones.benchmark.runner import snapshot_episode_inputs, verify_freeze_manifest
from flydrones.benchmark.score import EpisodeScorer
from flydrones.benchmark.ulog_capture import episode_exit_code, ulog_evidence_failures
from flydrones.config import load_config


def prearm_duration(
    seconds: float, *, frozen: bool, record_rgb: bool, record_camera_info: bool,
) -> float:
    """Admit a simulated-time prearm dwell only for raw development capture."""
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0. <= seconds <= 8.:
        raise ValueError('invalid development prearm duration')
    if seconds and (frozen or not record_rgb or not record_camera_info):
        raise ValueError('development prearm requires RGB/camera info and no freeze manifest')
    return float(seconds)


def prelude_step_count(
    seconds: float, dt_s: float, *, frozen: bool,
    record_rgb: bool, record_camera_info: bool,
) -> int:
    """Validate an explicitly requested development-only hover interval."""
    if not math.isfinite(seconds) or seconds < 0 or not math.isfinite(dt_s) or dt_s <= 0:
        raise ValueError('invalid development hover prelude duration or step')
    if seconds == 0:
        return 0
    if frozen or not record_rgb or not record_camera_info:
        raise ValueError('development hover prelude requires RGB/camera info and no freeze manifest')
    steps = round(seconds / dt_s)
    if seconds > 8 or steps < 1 or not math.isclose(steps * dt_s, seconds, abs_tol=1e-9):
        raise ValueError('development hover prelude must be at most 8 s and a whole step')
    return steps


def run_hover_prelude(
    gateway: Gateway, scorer: EpisodeScorer, steps: int, *, progress: dict | None = None,
) -> dict:
    """Advance through PX4; retain advanced/scored counts and last observed time."""
    if steps < 0:
        raise ValueError('development hover prelude steps must be nonnegative')
    result = progress if progress is not None else {}
    result.update({'requested_steps': steps, 'actual_steps': 0, 'scored_steps': 0,
                   'start_sim_ns': None, 'end_sim_ns': None, 'terminal_status': None})
    if steps == 0:
        return result
    initial = gateway.backend.score_sample()
    result['start_sim_ns'] = initial.sim_ns
    result['end_sim_ns'] = initial.sim_ns
    scorer.update(initial)
    for _ in range(steps):
        if scorer.status is not None:
            break
        gateway.advance(Command((0., 0., 0.), 0.))
        result['actual_steps'] += 1
        sample = gateway.backend.score_sample()
        result['end_sim_ns'] = sample.sim_ns
        scorer.update(sample)
        result['scored_steps'] += 1
    result['terminal_status'] = scorer.status
    return result


def mark_prelude_failure(progress: dict, requested_steps: int, status: str) -> None:
    """Retain an infrastructure failure only if prelude scoring was unfinished."""
    if requested_steps and progress['scored_steps'] < requested_steps:
        progress['terminal_status'] = status


def require_unused_episode_output(output: Path) -> None:
    """Reserve a fresh episode directory without overwriting partial evidence."""
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit(f'refusing nonempty or preexisting episode output: {output}') from None


def prepare_development_textures(source: Path, output: Path) -> dict:
    """Copy fixed-world textures into a fresh development episode with hashes."""
    names = ('ground_albedo.png', 'obstacle_albedo.png')
    if (not source.is_dir() or source.is_symlink()
            or (source / 'INCOMPLETE.json').exists()
            or (source / 'INCOMPLETE.json').is_symlink()):
        raise ValueError(f'invalid or incomplete development texture source: {source}')
    source_manifest = source / 'manifest.json'
    if source_manifest.is_symlink():
        raise ValueError('unsafe development texture manifest')
    board_hash = None
    if source_manifest.is_file() and not source_manifest.is_symlink():
        metadata = json.loads(source_manifest.read_text(encoding='utf-8'))
        if metadata.get('schema') == 'flydrones-openvins-board-pattern-dev-v1':
            names += ('board_albedo.png',)
            board_hash = metadata.get('board_albedo_sha256')
    if 'board_albedo.png' not in names and (
            (source / 'board_albedo.png').exists()
            or (source / 'board_albedo.png').is_symlink()):
        raise ValueError('undeclared development board texture')
    manifest_path = output / 'texture_input_manifest.json'
    if manifest_path.exists() or any((output / name).exists() for name in names):
        raise FileExistsError(f'development texture destination already used: {output}')
    contents: dict[str, bytes] = {}
    for name in names:
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'missing or unsafe development texture: {path}')
        contents[name] = path.read_bytes()
        if name == 'board_albedo.png' and hashlib.sha256(contents[name]).hexdigest() != board_hash:
            raise ValueError('development board texture hash mismatch')
    manifest = {'source': str(source.resolve()), 'files': {}}
    for name, data in contents.items():
        with (output / name).open('xb') as target:
            target.write(data)
        manifest['files'][name] = {
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
        }
    with manifest_path.open('x', encoding='utf-8') as target:
        json.dump(manifest, target, indent=2)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--controller', choices=('fly_raw', 'fly_guided', 'ego'), required=True)
    parser.add_argument('--world-json', type=Path, required=True)
    parser.add_argument('--world-sdf', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/fly_ego_benchmark.yaml')
    parser.add_argument('--ego-endpoint', default='127.0.0.1:46200')
    parser.add_argument('--freeze-manifest', type=Path)
    parser.add_argument('--record-rgb', action='store_true',
                        help='development preflight: preserve raw RGB frames and timestamps')
    parser.add_argument('--record-camera-info', action='store_true',
                        help='development preflight: preserve published Gazebo camera info')
    parser.add_argument('--development-hover-prelude-s', type=float, default=0.,
                        help='development capture only: post-takeoff zero-command interval')
    parser.add_argument('--development-prearm-stationary-s', type=float, default=0.,
                        help='development capture only: additional disarmed simulated-time interval')
    parser.add_argument('--development-texture-dir', type=Path,
                        help='development prearm only: copy fixed-world textures into fresh episode')
    args = parser.parse_args()

    config = load_benchmark_config(args.config)
    frozen = verify_freeze_manifest(args.freeze_manifest, ROOT) if args.freeze_manifest else None
    prelude_steps = prelude_step_count(
        args.development_hover_prelude_s, float(config['control']['dt_s']),
        frozen=args.freeze_manifest is not None,
        record_rgb=args.record_rgb, record_camera_info=args.record_camera_info)
    prearm_s = prearm_duration(
        args.development_prearm_stationary_s,
        frozen=args.freeze_manifest is not None,
        record_rgb=args.record_rgb, record_camera_info=args.record_camera_info)
    if args.development_texture_dir is not None and not prearm_s:
        raise ValueError('development texture source requires prearm stationary capture')
    world = json.loads(args.world_json.read_text(encoding='utf-8'))
    require_unused_episode_output(args.output)
    result_path = args.output / 'result.json'
    if args.development_texture_dir is not None:
        prepare_development_textures(args.development_texture_dir, args.output)
    with (args.output / 'started.json').open('x', encoding='utf-8') as target:
        json.dump({
            'controller': args.controller,
            'seed': world['seed'],
            'started_wall_s': time.time(),
        }, target, indent=2)
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
    backend = NativeGazeboPx4Backend(ROOT, args.output, world, record_rgb=args.record_rgb,
                                    record_camera_info=args.record_camera_info,
                                    development_prearm_stationary_s=prearm_s)
    gateway = Gateway(config, backend)
    scorer = EpisodeScorer(
        tuple(world['goal']), config['task']['goal_radius_m'],
        config['task']['goal_hold_s'], config['task']['timeout_s'],
    )
    decisions = []
    stage = 'infrastructure'
    started = time.perf_counter()
    prelude = run_hover_prelude(gateway, scorer, 0)
    prelude['requested_steps'] = prelude_steps
    try:
        gateway.start(episode_world_sdf)
        run_hover_prelude(gateway, scorer, prelude_steps, progress=prelude)
        if scorer.status is None:
            first_observation = gateway.observe()
            if args.controller.startswith('fly_'):
                controller.reset(int(world['seed']))
                controller.warmup(first_observation, seconds=2.1)
            else:
                controller.reset(int(world['seed']))
            if prelude_steps == 0:
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
        mark_prelude_failure(prelude, prelude_steps, scorer.status)
    finally:
        try:
            controller.close()
        finally:
            gateway.close()

    ulog_failures = ulog_evidence_failures(backend.ulog_evidence, backend.ulog_capture_error)
    rgb_failures = rgb_capture_failures(backend.rgb_capture_summary, backend.rgb_capture_error,
                                        required=args.record_rgb)
    camera_info_failures = camera_info_capture_failures(
        backend.camera_info_summary, backend.camera_info_error, required=args.record_camera_info,
    )
    evidence_failures = ulog_failures + rgb_failures + camera_info_failures
    payload = scorer.summary()
    payload.update({
        'controller': args.controller,
        'seed': world['seed'],
        'family': world['family'],
        'candidate': world.get('candidate'),
        'wall_s': time.perf_counter() - started,
        'decisions': decisions,
        'simulation': 'Gazebo Sim with PX4 SITL; fixed 50 ms steps while decision computation is paused',
        'odometry_source': 'gazebo_model_truth',
        'camera_pose_source': 'gazebo_model_truth',
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
        'px4_ulog_capture_accepted': not ulog_failures,
        'rgb_capture_requested': args.record_rgb,
        'rgb_capture_frame_count': len(backend.rgb_capture_summary['frames']) if backend.rgb_capture_summary else 0,
        'rgb_capture_out_of_order_drops': backend.rgb_capture_summary['out_of_order_drops'] if backend.rgb_capture_summary else None,
        'rgb_capture_error': backend.rgb_capture_error,
        'rgb_capture_accepted': not rgb_failures if args.record_rgb else None,
        'camera_info_requested': args.record_camera_info,
        'camera_info_message_count': (backend.camera_info_summary['message_count']
                                      if backend.camera_info_summary else 0),
        'camera_info_changed_stable_fields': (backend.camera_info_summary['changed_stable_fields']
                                              if backend.camera_info_summary else None),
        'camera_info_error': backend.camera_info_error,
        'camera_info_capture_accepted': not camera_info_failures if args.record_camera_info else None,
    })
    if prelude_steps:
        payload['development_hover_prelude'] = prelude
    if prearm_s:
        payload['development_prearm_stationary'] = backend.prearm_stationary_evidence
    temporary = args.output / 'result.json.tmp'
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(result_path)
    print(json.dumps({key: payload[key] for key in ('controller', 'seed', 'status', 'elapsed_sim_s', 'wall_s')}, indent=2))
    return episode_exit_code(payload['status'], evidence_failures)


if __name__ == '__main__':
    raise SystemExit(main())
