"""Own-process PX4/Gazebo clock and RGB-D probe. WSL only; no real adapters."""

import json
import os
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from gz.msgs10.boolean_pb2 import Boolean
from gz.msgs10.image_pb2 import Image
from gz.msgs10.world_control_pb2 import WorldControl
from gz.msgs10.world_stats_pb2 import WorldStatistics
from gz.transport13 import Node

from flydrones.benchmark.clock import StepClock, require_offboard
from flydrones.drones.mavlink import MavlinkDrone
from flydrones.motor.command import FlightCommand


def main():
    output = ROOT / 'results/fly-ego-comparison' / os.environ.get('BENCH_PROBE_RUN', 'clock-probe')
    output.mkdir(parents=True, exist_ok=True)
    run_dir = Path.home() / 'fly-ego-benchmark/clock-probe'
    run_dir.mkdir(parents=True, exist_ok=True)
    px4 = Path.home() / 'PX4-Autopilot'
    build = px4 / 'build/px4_sitl_default'
    env = os.environ.copy()
    env.update(HEADLESS='1', PX4_GZ_STANDALONE='1', PX4_SYS_AUTOSTART='4001',
               PX4_GZ_WORLD='fly_ego_benchmark', PX4_SIM_MODEL='gz_x500_benchmark', PX4_GZ_MODEL_NAME='x500_benchmark_8',
               PX4_GZ_MODEL_POSE='-8,0,0,0,0,0')
    env['GZ_SIM_RESOURCE_PATH'] = ':'.join([str(ROOT / 'assets/gazebo/models'),
        str(px4 / 'Tools/simulation/gz/models'), env.get('GZ_SIM_RESOURCE_PATH', '')])
    (run_dir / 'gz_env.sh').write_text((build / 'rootfs/gz_env.sh').read_text())
    processes = []
    logs = []
    stats = {'sim_ns': None, 'paused': False, 'rgb': [], 'depth': []}
    result = {'accepted': False, 'scope': 'single PX4/Gazebo synchronization probe, not benchmark results'}
    node = Node()

    def on_stats(message):
        stats['sim_ns'] = message.sim_time.sec * 1_000_000_000 + message.sim_time.nsec
        stats['paused'] = message.paused

    def on_image(key):
        def callback(message):
            stats[key].append({'stamp': message.header.stamp.sec*1_000_000_000 + message.header.stamp.nsec,
                               'width': message.width, 'height': message.height, 'format': message.pixel_format_type,
                               'bytes': len(message.data)})
        return callback

    node.subscribe(WorldStatistics, '/world/fly_ego_benchmark/stats', on_stats)
    node.subscribe(Image, '/benchmark/rgbd/image', on_image('rgb'))
    node.subscribe(Image, '/benchmark/rgbd/depth_image', on_image('depth'))

    def launch(args, name):
        handle = (output / f'{name}.log').open('w')
        logs.append(handle)
        proc = subprocess.Popen(args, cwd=run_dir, env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(proc)
        (output / 'processes.json').write_text(json.dumps([{'pid': p.pid, 'args': p.args} for p in processes], indent=2))
        return proc

    def wait_for(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise TimeoutError(f'probe wait expired: {stats}')
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('probe process exited; inspect logs')
            time.sleep(.02)

    def control(pause, steps=0):
        ok, reply = node.request('/world/fly_ego_benchmark/control', WorldControl(pause=pause, multi_step=steps),
                                 WorldControl, Boolean, 3000)
        if not ok or not reply.data:
            raise RuntimeError('Gazebo world control rejected')

    drone = None
    try:
        tree = ET.parse(output / 'world.sdf')
        world = tree.getroot().find('world')
        if not any(i.findtext('name') == 'x500_benchmark_8' for i in world.findall('include')):
            include = ET.SubElement(world, 'include')
            ET.SubElement(include, 'uri').text = 'model://x500_benchmark'
            ET.SubElement(include, 'name').text = 'x500_benchmark_8'
            ET.SubElement(include, 'pose').text = '-8 0 .24 0 0 0'
            tree.write(output / 'world.sdf')
        launch(['gz', 'sim', '-s', '-r', str(output / 'world.sdf')], 'gazebo')
        wait_for(lambda: stats['sim_ns'] is not None)
        launch([str(build / 'bin/px4'), '-i', '8', '-d', str(build / 'etc')], 'px4')
        wait_for(lambda: len(stats['rgb']) > 2 and len(stats['depth']) > 2, 60)
        drone = MavlinkDrone(connection='udpin:0.0.0.0:14548', autopilot='px4', takeoff_alt=1.5, takeoff_timeout=35)
        drone.connect()
        # Let the estimator settle while keeping a GCS heartbeat present.
        for _ in range(240):
            drone.send(FlightCommand.hover('preflight settling'))
            drone.telemetry()
            time.sleep(.05)
        try:
            drone.takeoff()
        except TimeoutError as exc:
            if 'did not arm' not in str(exc):
                raise
            drone.takeoff()
        for _ in range(30):
            drone.send(FlightCommand.hover('clock probe'))
            time.sleep(.05)
        before_tel = drone.telemetry()
        def read_mode():
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                drone.send(FlightCommand.hover('heartbeat validation'))
                heartbeat = drone.m.recv_match(type='HEARTBEAT', blocking=True, timeout=.1)
                if heartbeat is not None and heartbeat.get_srcSystem() == 9 and heartbeat.autopilot == 12:
                    require_offboard(heartbeat.custom_mode, heartbeat.base_mode)
                    return {'custom': int(heartbeat.custom_mode), 'base': int(heartbeat.base_mode), 'mode': 'OFFBOARD'}
            raise TimeoutError('no PX4 heartbeat with known mode')
        before_mode = read_mode()
        control(True)
        wait_for(lambda: stats['paused'])
        # Settle the stats subscription before starting the pause interval.
        time.sleep(.3)
        start = stats['sim_ns']
        for _ in range(100):
            drone.send(FlightCommand.hover('paused clock probe'))
            drone.telemetry()
            time.sleep(.05)
        finish = stats['sim_ns']
        clock = StepClock(50_000_000)
        clock.assert_paused(start, finish)
        after_mode = None
        times = []
        for _ in range(20):
            base = stats['sim_ns']
            drone.send(FlightCommand.hover('fixed step probe'))
            control(True, 50)
            wait_for(lambda: stats['sim_ns'] >= base + 50_000_000)
            if stats['sim_ns'] != base + 50_000_000:
                raise RuntimeError(f'fixed step mismatch: {base} -> {stats["sim_ns"]}')
            times.append(stats['sim_ns'])
            drone.telemetry()
        # Validate actual heartbeat fields, not pymavlink's possibly UNKNOWN label.
        control(False)
        after_mode = read_mode()
        result.update(accepted=True, paused_before_ns=start, paused_after_ns=finish,
                      stepped_ns=times[-1]-finish, step_times_ns=times, mode_before=before_mode, mode_after=after_mode,
                      altitude_before=before_tel.alt_m, rgb_frames=stats['rgb'][-20:], depth_frames=stats['depth'][-20:])
    except Exception as exc:
        result['error'] = repr(exc)
        result['last_stats'] = {k: v[-3:] if isinstance(v, list) else v for k,v in stats.items()}
    finally:
        # Processes launched by this probe only; never broad pkill or port killing.
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in reversed(processes):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        for handle in logs:
            handle.close()
        (output / 'summary.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
    return 0 if result['accepted'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
