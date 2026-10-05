"""Externally forced simulation fixture. Ground truth is never a VIO input."""

from __future__ import annotations

import json
import math
import time
from contextlib import ExitStack

from flydrones.benchmark.gateway import sim_duration_ns


def profile():
    return dict(
        name="lateral-wrench-v1",
        start_ns=5_000_000_000,
        stop_ns=6_600_000_000,
        cycle_ns=800_000_000,
        force_world_y_n=26.0,
        physics_step_ns=1_000_000,
        expected_active_steps=1600,
        heartbeat_max_age_ns=2_000_000_000,
        max_displacement_m=1.0,
        max_speed_m_s=3.0,
        max_roll_pitch_rad=math.pi / 4,
        sensor_hz=dict(imu=250, rgbd=10),
        eligible_for_px4_fusion=False,
        scope="external disarmed fixture; truth only in isolated abort/audit monitor",
    )


class MotionPolicy:
    def __init__(self):
        self.failure, self.last_ns, self.origin = None, None, None
        self.active_steps, self.signed_sum, self.absolute_sum = 0, 0.0, 0.0

    def refuse(self, reason):
        self.failure = self.failure or str(reason)
        raise ValueError(self.failure)

    def _available(self):
        if self.failure:
            raise ValueError("motion refusal latched: " + self.failure)

    def step(self, ns, dt_ns, *, unarmed_wall_ns, wall_ns):
        self._available()
        if type(ns) is not int or type(dt_ns) is not int or dt_ns != 1_000_000 or ns < 0:
            self.refuse("invalid simulation step")
        if (self.last_ns is None and ns not in (0, 1_000_000)) or (self.last_ns is not None and ns - self.last_ns != 1_000_000):
            self.refuse("duplicate/regressed/gapped simulation clock")
        self.last_ns = ns
        if not 5_000_000_000 <= ns < 6_600_000_000:
            return 0.0
        if (
            type(unarmed_wall_ns) is not int
            or type(wall_ns) is not int
            or unarmed_wall_ns <= 0
            or not 0 <= wall_ns - unarmed_wall_ns <= 2_000_000_000
        ):
            self.refuse("missing/stale/future disarmed heartbeat")
        phase = (ns - 5_000_000_000) % 800_000_000
        force = -26.0 if 200_000_000 <= phase < 600_000_000 else 26.0
        self.active_steps += 1
        self.signed_sum += force
        self.absolute_sum += abs(force)
        return force

    def observe(self, position, velocity, rpy):
        self._available()
        try:
            valid = all(
                len(v) == 3 and all(type(x) in (float, int) and math.isfinite(x) for x in v) for v in [position, velocity, rpy]
            )
        except (TypeError, OverflowError):
            valid = False
        if not valid:
            self.refuse("invalid fixture physics state")
        if self.origin is None:
            self.origin = list(position)
        displacement = math.dist(position, self.origin)
        speed = math.hypot(*velocity)
        if displacement > 1.0 or speed > 3.0 or max(abs(rpy[0]), abs(rpy[1])) > math.pi / 4:
            self.refuse("fixture displacement/speed/tilt bound exceeded")

    def finish(self):
        return dict(
            failure=self.failure,
            last_ns=self.last_ns,
            active_steps=self.active_steps,
            signed_impulse_ns=self.signed_sum * 0.001,
            absolute_impulse_ns=self.absolute_sum * 0.001,
            full_profile_requested=self.active_steps == 1600 and self.failure is None,
            eligible_for_px4_fusion=False,
        )


class GazeboMotionProbe:
    """Single simulation-thread owner; no reference to the sensor/native writer."""

    def __init__(self, output, errors, unarmed_stamp):
        self.errors, self.unarmed_stamp = errors, unarmed_stamp
        self.policy = MotionPolicy()
        self.link = None
        self.last_force = 0.0
        self.last_attempt = None
        self.recorded_commands = 0
        self.truth_records = 0
        with ExitStack() as owned:
            self.commands = owned.enter_context((output / "motion-force.jsonl").open("x"))
            self.truth = owned.enter_context((output / "motion-ground-truth.jsonl").open("x"))
            with (output / "motion-profile.json").open("x") as stream:
                json.dump(profile(), stream, indent=2)
            owned.pop_all()

    def _failed(self, exc):
        if self.policy.failure is None:
            self.policy.failure = repr(exc)
        if not any(e.startswith("motion fixture:") for e in self.errors):
            self.errors.append("motion fixture: " + repr(exc))

    def pre_update(self, info, ecm):
        if self.errors or self.policy.failure:
            return
        try:
            from gz.math7 import Vector3d
            from gz.sim8 import K_NULL_ENTITY, Link, Model, World, world_entity

            ns = sim_duration_ns(info.sim_time)
            if info.paused:
                self.policy.refuse("paused fixture step")
            if self.link is None:
                model = World(world_entity(ecm)).model_by_name(ecm, "x500_benchmark_8")
                link = Model(model).link_by_name(ecm, "base_link") if model != K_NULL_ENTITY else K_NULL_ENTITY
                if link == K_NULL_ENTITY:
                    self.policy.refuse("required base_link missing")
                self.link = Link(link)
                self.link.enable_velocity_checks(ecm)
                self.link.enable_acceleration_checks(ecm)
            if ns >= 1_000_000_000 and self.policy.origin is None:
                self.policy.refuse("fixture physics state unavailable")
            force = self.policy.step(
                ns, sim_duration_ns(info.dt), unarmed_wall_ns=self.unarmed_stamp(), wall_ns=time.monotonic_ns()
            )
            if force or self.last_force:
                self.last_attempt = dict(
                    sim_ns=ns,
                    dt_ns=sim_duration_ns(info.dt),
                    force_world_n=[0.0, force, 0.0],
                    call_returned=False,
                    wall_ns=time.monotonic_ns(),
                )
                if force:
                    self.link.add_world_force(ecm, Vector3d(0.0, force, 0.0))
                self.last_attempt["call_returned"] = True
                self.commands.write(json.dumps(self.last_attempt, allow_nan=False) + "\n")
                self.recorded_commands += 1
                if force == 0 or self.recorded_commands % 100 == 0:
                    self.commands.flush()
            self.last_force = force
        except Exception as exc:
            self._failed(exc)

    def post_update(self, info, ecm):
        if self.errors or self.policy.failure or self.link is None:
            return
        try:
            pose = self.link.world_pose(ecm)
            velocity = self.link.world_linear_velocity(ecm)
            angular = self.link.world_angular_velocity(ecm)
            accel = self.link.world_linear_acceleration(ecm)
            if any(value is None for value in [pose, velocity, angular, accel]):
                if sim_duration_ns(info.sim_time) >= 100_000_000:
                    self.policy.refuse("missing fixture physics fields")
                return

            def xyz(v):
                return [v.x(), v.y(), v.z()]

            rotation = pose.rot()
            position = xyz(pose.pos())
            vel = xyz(velocity)
            rpy = [rotation.roll(), rotation.pitch(), rotation.yaw()]
            # Record violating samples too; truth stays on this separate stream only.
            ns = sim_duration_ns(info.sim_time)
            record = dict(
                sim_ns=ns,
                position=position,
                velocity_world=vel,
                accel_world=xyz(accel),
                angular_world=xyz(angular),
                quaternion_xyzw=[rotation.x(), rotation.y(), rotation.z(), rotation.w()],
                rpy=rpy,
                truth_for_fixture_audit_only=True,
            )
            # Health checks run at physics frequency, independently of log decimation.
            for field in ("position", "velocity_world", "accel_world", "angular_world", "quaternion_xyzw", "rpy"):
                if not all(type(v) in (int, float) and math.isfinite(v) for v in record[field]):
                    self.policy.refuse("invalid fixture physics field: " + field)
            if ns % 4_000_000 == 0:
                self.truth.write(json.dumps(record, allow_nan=False) + "\n")
                self.truth_records += 1
            try:
                self.policy.observe(position, vel, rpy)
            except ValueError:
                if ns % 4_000_000:
                    self.truth.write(json.dumps(record, allow_nan=False) + "\n")
                    self.truth_records += 1
                self.truth.flush()
                raise
        except Exception as exc:
            self._failed(exc)

    def finish(self):
        close_errors = []
        for name, stream in (("commands", self.commands), ("truth", self.truth)):
            try:
                stream.close()
            except Exception as exc:
                close_errors.append(dict(stream=name, reason=repr(exc)))
                self._failed(exc)
        return dict(
            self.policy.finish(),
            close_errors=close_errors,
            recorded_commands=self.recorded_commands,
            truth_records=self.truth_records,
            last_attempt=self.last_attempt,
            force_scope="one-step API; no persistent wrench",
        )
