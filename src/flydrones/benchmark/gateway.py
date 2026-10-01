"""Common command shaping and Gazebo/PX4 gateway boundary."""

from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import xml.etree.ElementTree as ET

import numpy as np

from .contract import Command, Observation
from .geometry import segment_box_clearance, segment_cylinder_clearance
from .score import ScoreSample
from .sensors import FrameCache, PoseHistory, camera_pose_from_model
from .worlds import dynamic_center


WORLD_CONTROL_TIMEOUT_MS = 15_000


def shape_command(
    requested: Command,
    previous: Command,
    *,
    dt_s: float,
    speed_max: float,
    acceleration_max: float,
    yaw_rate_max: float,
) -> Command:
    values = np.asarray((*requested.velocity_enu, requested.yaw_rate), dtype=float)
    parameters = np.asarray((dt_s, speed_max, acceleration_max, yaw_rate_max), dtype=float)
    if not np.all(np.isfinite(values)) or not np.all(np.isfinite(parameters)):
        raise ValueError('command and limits must be finite')
    if dt_s <= 0 or speed_max <= 0 or acceleration_max <= 0 or yaw_rate_max <= 0:
        raise ValueError('command limits must be positive')

    desired = values[:3]
    norm = float(np.linalg.norm(desired))
    if norm > speed_max:
        desired = desired * speed_max / norm
    prior = np.asarray(previous.velocity_enu, dtype=float)
    delta = desired - prior
    delta_norm = float(np.linalg.norm(delta))
    max_delta = acceleration_max * dt_s
    if delta_norm > max_delta:
        desired = prior + delta * max_delta / delta_norm
    return Command(tuple(float(v) for v in desired), float(np.clip(requested.yaw_rate, -yaw_rate_max, yaw_rate_max)))


def enu_to_ned(command: Command) -> tuple[float, float, float, float]:
    """Convert world ENU velocity and CCW yaw rate to local NED."""
    x, y, z = command.velocity_enu
    return float(y), float(x), float(-z), float(-command.yaw_rate)


def step_complete(stats: dict, target_ns: int) -> bool:
    return stats.get('sim_ns') == target_ns and stats.get('paused') is True


def direct_step_complete(stats: dict, target_ns: int, *, server_running: bool) -> bool:
    """A finite embedded-server run is paused whenever ``run`` has returned."""
    return stats.get('sim_ns') == target_ns and not bool(server_running)


def sim_duration_ns(duration) -> int:
    """Convert Gazebo's microsecond-resolution timedelta without drift."""
    return ((duration.days * 86_400 + duration.seconds) * 1_000_000
            + duration.microseconds) * 1_000


def control_retry_allowed(*, pause: bool, steps: int) -> bool:
    """Only a pure pause is safe to repeat after a transport timeout."""
    return bool(pause) and int(steps) == 0


def contact_message_involves(message, vehicle_name: str) -> bool:
    prefix = f'{vehicle_name}::'
    return any(
        prefix in _collision_name(contact.collision1)
        or prefix in _collision_name(contact.collision2)
        for contact in message.contact
    )


def _collision_name(value) -> str:
    return value if isinstance(value, str) else str(value.name)


def offboard_evidence_fresh(last_sim_ns, current_sim_ns: int, max_age_ns: int = 2_000_000_000) -> bool:
    if last_sim_ns is None:
        return False
    age = int(current_sim_ns) - int(last_sim_ns)
    return 0 <= age <= int(max_age_ns)


def world_control_request_text(pause: bool, steps: int) -> str:
    return f'pause: {str(bool(pause)).lower()} multi_step: {int(steps)}'


def transport_partition(run_name: str, process_id: int) -> str:
    safe = re.sub(r'[^A-Za-z0-9_]', '_', str(run_name))
    return f'fly_ego_{int(process_id)}_{safe}'


class Gateway:
    """Sequential fixed-step facade around an injected Gazebo/PX4 backend.

    The native backend lives in the WSL process where Gazebo transport and
    pymavlink are installed. Keeping this facade dependency-free makes the
    fairness rules testable on Windows as well.
    """

    def __init__(self, config: dict, backend=None):
        control = config['control']
        self.dt_s = float(control['dt_s'])
        self.speed_max = float(control['speed_max_mps'])
        self.acceleration_max = float(control['acceleration_max_mps2'])
        self.yaw_rate_max = float(control['yaw_rate_max_radps'])
        self.backend = backend
        self.previous = Command((0., 0., 0.), 0.)
        self.started = False

    def start(self, world_path) -> None:
        if self.backend is None:
            raise RuntimeError('Gateway requires a WSL Gazebo/PX4 backend')
        self.backend.start(world_path)
        self.previous = Command((0., 0., 0.), 0.)
        self.started = True

    def observe(self) -> Observation:
        if not self.started:
            raise RuntimeError('Gateway has not started')
        return self.backend.observe()

    def advance(self, command: Command) -> None:
        if not self.started:
            raise RuntimeError('Gateway has not started')
        shaped = shape_command(
            command,
            self.previous,
            dt_s=self.dt_s,
            speed_max=self.speed_max,
            acceleration_max=self.acceleration_max,
            yaw_rate_max=self.yaw_rate_max,
        )
        self.backend.advance(enu_to_ned(shaped), self.dt_s)
        self.previous = shaped

    def close(self) -> None:
        if self.backend is not None:
            self.backend.close()
        self.started = False


def _yaw(quaternion: tuple[float, ...]) -> float:
    x, y, z, w = quaternion
    return float(np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))


def swept_clearance(world: dict, start, finish, start_ns: int, finish_ns: int, radius: float) -> float:
    """Minimum conservative clearance over one physics step."""
    start = np.asarray(start, dtype=float)
    finish = np.asarray(finish, dtype=float)
    result = np.inf
    for box in world['boxes']:
        result = min(result, segment_box_clearance(start, finish, box['lo'], box['hi'], radius))
    for cylinder in world['cylinders']:
        result = min(result, segment_cylinder_clearance(
            start, finish, cylinder['center'], cylinder['radius'],
            cylinder['zlo'], cylinder['zhi'], radius,
        ))
    for obstacle in world.get('dynamic', []):
        before = np.asarray(dynamic_center(obstacle, start_ns))
        after = np.asarray(dynamic_center(obstacle, finish_ns))
        relative_start = start - before
        relative_finish = finish - after
        half = np.asarray(obstacle['size'], dtype=float) / 2
        result = min(result, segment_box_clearance(relative_start, relative_finish, -half, half, radius))
    return float(result)


class NativeGazeboPx4Backend:
    """WSL-only fixed-step backend used by all three controllers."""

    def __init__(self, root: Path, run_dir: Path, world: dict, *, instance: int = 8):
        self.root = Path(root).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.world = world
        self.instance = int(instance)
        self.goal = tuple(world['goal'])
        self.vehicle_name = f'x500_benchmark_{self.instance}'
        self.processes: list[subprocess.Popen] = []
        self.log_handles = []
        self.node = None
        self.control_node = None
        self.drone = None
        self.stats = {
            'sim_ns': None,
            'paused': False,
            'transport_sim_ns': None,
            'transport_paused': False,
        }
        self.frames = {'rgb': {}, 'depth': {}}
        self.frame_cache = FrameCache()
        self.pose_history = PoseHistory(max_samples=4096)
        self.model_samples = deque(maxlen=32)
        self._last_score_position = None
        self._last_score_ns = None
        self._setpoint_condition = threading.Condition()
        self._setpoint = (0., 0., 0., 0.)
        self._setpoint_generation = 0
        self._setpoint_ack = -1
        self._setpoint_stop = threading.Event()
        self._setpoint_thread = None
        self._step_count = 0
        self._contact = False
        self.contact_records = []
        self.contact_message_count = 0
        self._last_offboard_sim_ns = None
        self.offboard_evidence = []
        self.control_records = []
        self.partition = None
        self.server = None
        self.fixture = None
        self._server_startup_stop = threading.Event()
        self._server_startup_thread = None
        self._server_error = None
        self._startup_run_count = 0

    def _launch(self, args, name, cwd, env):
        handle = (self.run_dir / f'{name}.log').open('w', encoding='utf-8')
        self.log_handles.append(handle)
        process = subprocess.Popen(
            args, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        process._benchmark_started = time.time()
        self.processes.append(process)
        self._write_process_manifest()
        return process

    def _write_process_manifest(self):
        manifest = [
            {'pid': process.pid, 'args': process.args, 'started_wall_s': process._benchmark_started}
            if hasattr(process, '_benchmark_started') else
            {'pid': process.pid, 'args': process.args}
            for process in self.processes
        ]
        (self.run_dir / 'processes.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    def _wait_for(self, predicate, timeout=30.):
        deadline = time.monotonic() + timeout
        while not predicate():
            if self._server_error is not None:
                raise RuntimeError('embedded Gazebo server failed') from self._server_error
            exited = [process for process in self.processes if process.poll() is not None]
            if exited:
                raise RuntimeError(f'benchmark process exited early: {[p.pid for p in exited]}')
            if time.monotonic() >= deadline:
                raise TimeoutError('benchmark backend wait expired')
            time.sleep(.01)

    def _run_server_during_startup(self):
        try:
            while not self._server_startup_stop.is_set():
                # Give the PX4-Gazebo transport bridge a continuous one-second
                # window to exchange actuator and sensor messages. Very short
                # stop/start runs can starve the asynchronous motor bridge.
                if not self.server.run(True, 1000, False):
                    raise RuntimeError('embedded Gazebo server rejected startup run')
                self._startup_run_count += 1
        except BaseException as exc:
            self._server_error = exc

    def _stop_startup_server(self):
        self._server_startup_stop.set()
        if self._server_startup_thread is not None:
            self._server_startup_thread.join(timeout=15)
            if self._server_startup_thread.is_alive():
                raise TimeoutError('embedded Gazebo startup loop did not stop')
        if self._server_error is not None:
            raise RuntimeError('embedded Gazebo server failed') from self._server_error

    def _wait_for_stats_quiescent(self, timeout=5., quiet_s=.2):
        deadline = time.monotonic() + timeout
        last = self.stats['sim_ns']
        quiet_since = time.monotonic()
        while time.monotonic() < deadline:
            current = self.stats['sim_ns']
            if current != last:
                last = current
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since >= quiet_s:
                return int(current)
            time.sleep(.01)
        raise TimeoutError('Gazebo statistics did not become quiescent')

    def _on_stats(self, message):
        self.stats['transport_sim_ns'] = (
            int(message.sim_time.sec) * 1_000_000_000 + int(message.sim_time.nsec)
        )
        self.stats['transport_paused'] = bool(message.paused)

    def _on_post_update(self, info, _ecm):
        self.stats['sim_ns'] = sim_duration_ns(info.sim_time)
        self.stats['paused'] = bool(info.paused)

    def _on_image(self, kind):
        def callback(message):
            frame_ns = int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nsec)
            if kind == 'rgb':
                array = np.frombuffer(message.data, np.uint8).reshape(message.height, message.width, 3).copy()
            else:
                array = np.frombuffer(message.data, dtype='<f4').reshape(message.height, message.width).copy()
                array[(array < .2) | (array > 19.1) | ~np.isfinite(array)] = np.nan
            self.frames[kind][frame_ns] = array
            for old in sorted(self.frames[kind])[:-8]:
                del self.frames[kind][old]
        return callback

    def _on_pose(self, message):
        frame_ns = int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nsec)
        for pose in message.pose:
            if pose.name != self.vehicle_name:
                continue
            sample = (
                float(pose.position.x), float(pose.position.y), float(pose.position.z),
                float(pose.orientation.x), float(pose.orientation.y),
                float(pose.orientation.z), float(pose.orientation.w),
            )
            if not self.model_samples or frame_ns > self.model_samples[-1][0]:
                self.pose_history.add(frame_ns, sample)
                self.model_samples.append((frame_ns, sample))
            break

    def _on_contacts(self, message):
        self.contact_message_count += 1
        if not contact_message_involves(message, self.vehicle_name):
            return
        self._contact = True
        for contact in message.contact:
            collision1 = _collision_name(contact.collision1)
            collision2 = _collision_name(contact.collision2)
            if self.vehicle_name in collision1 or self.vehicle_name in collision2:
                self.contact_records.append({
                    'sim_ns': self.stats['sim_ns'],
                    'collision1': collision1,
                    'collision2': collision2,
                })

    def _control(self, pause: bool, steps: int = 0):
        attempts = 5 if control_retry_allowed(pause=pause, steps=steps) else 1
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            request_text = world_control_request_text(pause, steps)
            result = subprocess.run([
                'gz', 'service', '-s', '/world/fly_ego_benchmark/control',
                '--reqtype', 'gz.msgs.WorldControl', '--reptype', 'gz.msgs.Boolean',
                '--timeout', str(WORLD_CONTROL_TIMEOUT_MS), '--req', request_text,
            ], capture_output=True, text=True, timeout=WORLD_CONTROL_TIMEOUT_MS / 1000 + 5)
            output = f'{result.stdout}\n{result.stderr}'.strip()
            ok = result.returncode == 0
            reply_data = ok and 'data: true' in output.lower()
            self.control_records.append({
                'pause': bool(pause),
                'steps': int(steps),
                'attempt': attempt,
                'elapsed_wall_s': time.perf_counter() - started,
                'transport_ok': bool(ok),
                'reply': bool(reply_data),
                'sim_ns_after_request': self.stats['sim_ns'],
                'output': output[-500:],
            })
            if ok and reply_data:
                return
            if attempt < attempts:
                time.sleep(.2)
        raise RuntimeError(
            f'Gazebo world control rejected: transport_ok={ok}, reply={reply_data}, '
            f'sim_ns={self.stats["sim_ns"]}, paused={self.stats["paused"]}, steps={steps}, attempts={attempts}'
        )

    def _set_dynamic_poses(self, sim_ns: int):
        if not self.world.get('dynamic'):
            return
        from gz.msgs10.boolean_pb2 import Boolean
        from gz.msgs10.pose_pb2 import Pose
        for obstacle in self.world['dynamic']:
            request = Pose(name=obstacle['name'])
            center = dynamic_center(obstacle, sim_ns)
            request.position.x, request.position.y, request.position.z = center
            request.orientation.w = 1.
            ok, reply = self.control_node.request(
                '/world/fly_ego_benchmark/set_pose', request, Pose, Boolean, 3000,
            )
            self.control_records.append({
                'method': 'set_pose',
                'obstacle': obstacle['name'],
                'target_sim_ns': int(sim_ns),
                'center': list(center),
                'transport_ok': bool(ok),
                'reply': bool(ok and reply.data),
            })
            if not ok or not reply.data:
                raise RuntimeError(f'failed to position dynamic obstacle {obstacle["name"]}')

    def _ensure_vehicle(self, world_path: Path):
        tree = ET.parse(world_path)
        world = tree.getroot().find('world')
        if not any(include.findtext('name') == self.vehicle_name for include in world.findall('include')):
            include = ET.SubElement(world, 'include')
            ET.SubElement(include, 'uri').text = 'model://x500_benchmark'
            ET.SubElement(include, 'name').text = self.vehicle_name
            start = self.world['start']
            ET.SubElement(include, 'pose').text = f'{start[0]} {start[1]} .24 0 0 0'
            ET.indent(tree.getroot())
            tree.write(world_path, encoding='utf-8', xml_declaration=True)

    def start(self, world_path: Path) -> None:
        from gz.sim8 import TestFixture
        from gz.msgs10.contacts_pb2 import Contacts
        from gz.msgs10.image_pb2 import Image
        from gz.msgs10.pose_v_pb2 import Pose_V
        from gz.msgs10.world_stats_pb2 import WorldStatistics
        from gz.transport13 import Node
        from flydrones.drones.mavlink import MavlinkDrone
        from flydrones.motor.command import FlightCommand

        self.run_dir.mkdir(parents=True, exist_ok=True)
        world_path = Path(world_path).resolve()
        self._ensure_vehicle(world_path)
        px4 = Path.home() / 'PX4-Autopilot'
        build = px4 / 'build/px4_sitl_default'
        runtime = Path.home() / 'fly-ego-benchmark' / 'runtime' / self.run_dir.name
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / 'gz_env.sh').write_text((build / 'rootfs/gz_env.sh').read_text(), encoding='utf-8')
        self.partition = transport_partition(self.run_dir.name, os.getpid())
        os.environ['GZ_PARTITION'] = self.partition
        (self.run_dir / 'gz_partition.txt').write_text(self.partition + '\n', encoding='utf-8')
        env = os.environ.copy()
        env.update(
            HEADLESS='1', PX4_GZ_STANDALONE='1', PX4_SYS_AUTOSTART='4001',
            PX4_GZ_WORLD='fly_ego_benchmark', PX4_SIM_MODEL='gz_x500_benchmark',
            PX4_GZ_MODEL_NAME=self.vehicle_name,
            PX4_GZ_MODEL_POSE=f'{self.world["start"][0]},{self.world["start"][1]},0,0,0,0',
            GZ_PARTITION=self.partition,
        )
        env['GZ_SIM_RESOURCE_PATH'] = ':'.join([
            str(self.root / 'assets/gazebo/models'),
            str(px4 / 'Tools/simulation/gz/models'),
            env.get('GZ_SIM_RESOURCE_PATH', ''),
        ])
        os.environ['GZ_SIM_RESOURCE_PATH'] = env['GZ_SIM_RESOURCE_PATH']

        self.node = Node()
        # Keep synchronous world-control requests isolated from the node that
        # dispatches high-rate sensor callbacks.
        self.control_node = Node()
        self.node.subscribe(WorldStatistics, '/world/fly_ego_benchmark/stats', self._on_stats)
        self.node.subscribe(Pose_V, '/world/fly_ego_benchmark/dynamic_pose/info', self._on_pose)
        self.node.subscribe(Image, '/benchmark/rgbd/image', self._on_image('rgb'))
        self.node.subscribe(Image, '/benchmark/rgbd/depth_image', self._on_image('depth'))
        self.node.subscribe(Contacts, '/benchmark/contacts', self._on_contacts)

        self.fixture = TestFixture(str(world_path))
        self.fixture.on_post_update(self._on_post_update)
        self.fixture.finalize()
        self.server = self.fixture.server()
        (self.run_dir / 'embedded_server.json').write_text(json.dumps({
            'pid': os.getpid(),
            'world': str(world_path),
            'partition': self.partition,
            'physics_step_ns': 1_000_000,
            'method': 'gz.sim8.TestFixture.server.run',
            'startup_chunk_steps': 1000,
        }, indent=2), encoding='utf-8')
        self._server_startup_stop.clear()
        self._server_startup_thread = threading.Thread(
            target=self._run_server_during_startup, daemon=True,
        )
        self._server_startup_thread.start()
        self._wait_for(lambda: self.stats['sim_ns'] is not None)
        self._launch([str(build / 'bin/px4'), '-i', str(self.instance), '-d', str(build / 'etc')], 'px4', runtime, env)
        self._wait_for(lambda: self.model_samples and self.frames['rgb'] and self.frames['depth'], 60.)

        self.drone = MavlinkDrone(
            connection=f'udpin:0.0.0.0:{14540 + self.instance}',
            autopilot='px4', takeoff_alt=1.26, takeoff_timeout=35,
        )
        self.drone.connect()
        for _ in range(240):
            self.drone.send(FlightCommand.hover('benchmark estimator settling'))
            self.drone.telemetry()
            time.sleep(.05)
        try:
            self.drone.takeoff()
        except TimeoutError as exc:
            if 'did not arm' not in str(exc):
                raise
            self.drone.takeoff()
        for _ in range(30):
            self.drone.send(FlightCommand.hover('benchmark hover'))
            time.sleep(.05)

        # PX4 heartbeat timers follow simulation time, so capture authoritative
        # OFFBOARD evidence before pausing the world.
        self._require_offboard()
        self._stop_startup_server()
        paused_ns = self._wait_for_stats_quiescent()
        self.control_records.append({
            'method': 'gz.sim8.Server.run',
            'phase': 'startup',
            'chunk_steps': 1000,
            'run_count': self._startup_run_count,
            'final_sim_ns': paused_ns,
        })
        time.sleep(.3)
        if self.stats['sim_ns'] != paused_ns:
            raise RuntimeError('simulation advanced after embedded server stopped')
        self._setpoint_stop.clear()
        self._setpoint_thread = threading.Thread(target=self._setpoint_loop, daemon=True)
        self._setpoint_thread.start()
        self._set_command((0., 0., 0., 0.))
        self._contact = False
        self.contact_records.clear()
        self.contact_message_count = 0
        current = self._current_model_pose()[0]
        self._last_score_position = tuple(current[:3])
        self._last_score_ns = int(self.stats['sim_ns'])

    def _send_local_ned(self, command):
        drone = self.drone
        drone._send_gcs_heartbeat_if_due()
        drone.m.mav.set_position_target_local_ned_send(
            int(time.monotonic() * 1000) & 0xFFFFFFFF,
            drone.m.target_system, drone.m.target_component,
            drone.mavutil.mavlink.MAV_FRAME_LOCAL_NED,
            0b0000_0101_1100_0111,
            0, 0, 0, command[0], command[1], command[2],
            0, 0, 0, 0, command[3],
        )

    def _setpoint_loop(self):
        while not self._setpoint_stop.is_set():
            with self._setpoint_condition:
                command = self._setpoint
                generation = self._setpoint_generation
            try:
                self._send_local_ned(command)
            except Exception:
                self._setpoint_stop.set()
                return
            with self._setpoint_condition:
                self._setpoint_ack = max(self._setpoint_ack, generation)
                self._setpoint_condition.notify_all()
            self._setpoint_stop.wait(.05)

    def _set_command(self, command):
        with self._setpoint_condition:
            self._setpoint = tuple(float(value) for value in command)
            self._setpoint_generation += 1
            generation = self._setpoint_generation
            deadline = time.monotonic() + .5
            while self._setpoint_ack < generation and not self._setpoint_stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('PX4 setpoint keepalive did not acknowledge command')
                self._setpoint_condition.wait(remaining)

    def _require_offboard(self):
        from .clock import require_offboard
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            heartbeat = self.drone.m.recv_match(type='HEARTBEAT', blocking=True, timeout=.1)
            if self._record_offboard_heartbeat(heartbeat, require_offboard):
                return
        raise TimeoutError('no PX4 OFFBOARD heartbeat')

    def _record_offboard_heartbeat(self, heartbeat, validator=None):
        if heartbeat is None or heartbeat.get_srcSystem() != self.instance + 1 or heartbeat.autopilot != 12:
            return False
        if validator is None:
            from .clock import require_offboard
            validator = require_offboard
        validator(heartbeat.custom_mode, heartbeat.base_mode)
        sim_ns = int(self.stats['sim_ns'])
        self._last_offboard_sim_ns = sim_ns
        self.offboard_evidence.append({
            'sim_ns': sim_ns,
            'custom_mode': int(heartbeat.custom_mode),
            'base_mode': int(heartbeat.base_mode),
        })
        return True

    def _drain_heartbeats(self):
        while True:
            heartbeat = self.drone.m.recv_match(type='HEARTBEAT', blocking=False)
            if heartbeat is None:
                return
            self._record_offboard_heartbeat(heartbeat)

    def _current_model_pose(self):
        sim_ns = int(self.stats['sim_ns'])
        deadline = time.monotonic() + 2
        while True:
            try:
                return self.pose_history.at_or_recent_before(
                    sim_ns, max_age_ns=50_000_000,
                ), sim_ns
            except ValueError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.005)

    def _velocity(self, sim_ns: int):
        samples = [sample for sample in self.model_samples if sample[0] <= sim_ns]
        if len(samples) < 2:
            return (0., 0., 0.), 0.
        (before_ns, before), (after_ns, after) = samples[-2:]
        dt = (after_ns - before_ns) / 1_000_000_000
        if dt <= 0:
            return (0., 0., 0.), 0.
        velocity = (np.asarray(after[:3]) - np.asarray(before[:3])) / dt
        yaw_rate = ((_yaw(after[3:]) - _yaw(before[3:]) + np.pi) % (2 * np.pi) - np.pi) / dt
        return tuple(float(value) for value in velocity), float(yaw_rate)

    def observe(self) -> Observation:
        model_pose, sim_ns = self._current_model_pose()
        common = sorted(set(self.frames['rgb']).intersection(self.frames['depth']))
        eligible = [frame_ns for frame_ns in common if frame_ns <= sim_ns]
        if not eligible:
            raise RuntimeError('no synchronized RGB-D frame at current simulation time')
        frame_ns = eligible[-1]
        if frame_ns > self.frame_cache.frame_ns:
            model_at_frame = self.pose_history.at_or_recent_before(
                frame_ns, max_age_ns=50_000_000,
            )
            self.frame_cache.add(
                frame_ns, self.frames['rgb'][frame_ns], self.frames['depth'][frame_ns],
                camera_pose_from_model(model_at_frame),
            )
        velocity, yaw_rate = self._velocity(sim_ns)
        return Observation(
            sim_ns=sim_ns,
            frame_ns=self.frame_cache.frame_ns,
            rgb=self.frame_cache.rgb.copy(),
            depth_m=self.frame_cache.depth_m.copy(),
            camera_pose=self.frame_cache.camera_pose,
            position=tuple(model_pose[:3]),
            velocity=velocity,
            yaw=_yaw(model_pose[3:]),
            yaw_rate=yaw_rate,
            goal=self.goal,
        )

    def advance(self, local_ned_command, dt_s: float) -> None:
        before = int(self.stats['sim_ns'])
        target = before + round(dt_s * 1_000_000_000)
        steps = round(dt_s / .001)
        if steps <= 0 or steps * 1_000_000 != round(dt_s * 1_000_000_000):
            raise ValueError('dt must be an integer number of 1 ms physics steps')
        self._set_command(local_ned_command)
        self._set_dynamic_poses(target)
        started = time.perf_counter()
        ok = self.server.run(True, steps, False)
        elapsed = time.perf_counter() - started
        self.control_records.append({
            'method': 'gz.sim8.Server.run',
            'steps': int(steps),
            'elapsed_wall_s': elapsed,
            'return_value': bool(ok),
            'sim_ns_before': before,
            'sim_ns_after_run': self.stats['sim_ns'],
        })
        if not ok:
            raise RuntimeError('embedded Gazebo server rejected fixed step')
        self._wait_for(
            lambda: direct_step_complete(
                self.stats, target, server_running=self.server.is_running(),
            ),
            5.,
        )
        if self.stats['sim_ns'] != target:
            raise RuntimeError(f'fixed step mismatch: {before} -> {self.stats["sim_ns"]}, wanted {target}')
        self._drain_heartbeats()
        self._step_count += 1
        if self._step_count % 20 == 0:
            if not offboard_evidence_fresh(self._last_offboard_sim_ns, target):
                raise RuntimeError(
                    f'PX4 OFFBOARD evidence stale in simulation time: '
                    f'last={self._last_offboard_sim_ns}, current={target}'
                )

    def score_sample(self) -> ScoreSample:
        pose, sim_ns = self._current_model_pose()
        position = tuple(pose[:3])
        clearance = swept_clearance(
            self.world, self._last_score_position, position,
            self._last_score_ns, sim_ns,
            float(self.world['vehicle_envelope_radius_m']),
        )
        lo = np.asarray(self.world['bounds'][0])
        hi = np.asarray(self.world['bounds'][1])
        in_bounds = bool(np.all(np.asarray(position)[:2] >= lo[:2]) and np.all(np.asarray(position)[:2] <= hi[:2])
                         and .5 <= position[2] <= 3.5)
        self._last_score_position = position
        self._last_score_ns = sim_ns
        return ScoreSample(sim_ns, position, clearance, self._contact, in_bounds)

    def close(self) -> None:
        self._server_startup_stop.set()
        if self._server_startup_thread is not None:
            self._server_startup_thread.join(timeout=2)
        self._setpoint_stop.set()
        if self._setpoint_thread is not None:
            self._setpoint_thread.join(timeout=2)
        if self.drone is not None:
            try:
                self.drone.land()
            except Exception:
                pass
        for process in reversed(self.processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in reversed(self.processes):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        for handle in self.log_handles:
            handle.close()
        self.server = None
        self.fixture = None
