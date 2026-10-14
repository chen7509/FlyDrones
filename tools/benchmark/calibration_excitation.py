"""Time-only raw measurement callback; runtime truth can only abort/audit."""

from __future__ import annotations

import copy
import json
import math
import time
from contextlib import ExitStack

from flydrones.benchmark.gateway import sim_duration_ns
from tools.benchmark.calibration_capture_scene import LIMITS, QUALIFICATION, request, transform
from tools.benchmark.disarmed_motion_probe import MotionPolicy


def journal(stream, row):
    encoded = json.dumps(row, allow_nan=False) + "\n"
    if stream.write(encoded) != len(encoded):
        raise OSError("short calibration motion journal write")
    stream.flush()


class CalibrationPolicy(MotionPolicy):
    def __init__(self, geometry, readiness, persist):
        super().__init__()
        self.geometry = copy.deepcopy(geometry)
        self.readiness, self.persist = readiness, persist
        self.anchor_ns, self.wall_ns = None, None
        self.support_steps = 0

    def step(self, ns, dt_ns, *, unarmed_wall_ns, wall_ns):
        self._available()
        try:
            if (
                type(ns) is not int
                or type(dt_ns) is not int
                or dt_ns != 1_000_000
                or not 0 < ns <= 25_000_000_000
                or type(wall_ns) is not int
                or wall_ns <= 0
                or self.wall_ns is not None
                and wall_ns < self.wall_ns
                or self.last_ns is None
                and ns != 1_000_000
                or self.last_ns is not None
                and ns - self.last_ns != 1_000_000
            ):
                raise ValueError("invalid calibration simulation/wall clock")
            self.last_ns, self.wall_ns = ns, wall_ns
            ready = self.readiness()
            if ready is not None:
                heartbeat = ready.get("records", {}).get("heartbeat", {})
                if (
                    type(heartbeat.get("system_id")) is not int
                    or heartbeat["system_id"] != 9
                    or type(heartbeat.get("base_mode")) is not int
                    or not 0 <= heartbeat["base_mode"] < 128
                    or type(unarmed_wall_ns) is not int
                    or unarmed_wall_ns <= 0
                    or not 0 <= wall_ns - unarmed_wall_ns <= 2_000_000_000
                ):
                    raise ValueError("invalid/armed/stale calibration heartbeat")
            if self.anchor_ns is None:
                if ns >= 8_000_000_000:
                    raise ValueError("calibration readiness startup deadline")
                if ready is not None:
                    anchor = ns + 200_000_000
                    self.persist(dict(anchor_ns=anchor, selected_sim_ns=ns, proof=ready, qualification=QUALIFICATION))
                    self.anchor_ns = anchor
            elif ready is None:
                raise ValueError("calibration readiness lost after anchor")
            relative = None if self.anchor_ns is None else ns - self.anchor_ns
            if relative is None or relative < 0:
                return dict(sim_ns=ns, relative_ns=relative, force_world_n=[0.0, 0.0, 0.0], torque_world_nm=[0.0, 0.0, 0.0])
            row = request(relative / 1e9, self.geometry["mass_kg"], self.geometry["inertia_com_model_kg_m2"])
            if math.hypot(*row["force_world_n"]) > LIMITS["force_n"] or math.hypot(*row["torque_world_nm"]) > LIMITS["torque_nm"]:
                raise ValueError("calibration requested force/torque bound")
            self.support_steps += 1
            return dict(row, sim_ns=ns, relative_ns=relative)
        except Exception as exc:
            self.refuse(repr(exc))

    def finish(self):
        expected = None if self.anchor_ns is None else (25_000_000_000 - self.anchor_ns) // 1_000_000 + 1
        return dict(
            failure=self.failure,
            last_ns=self.last_ns,
            anchor_ns=self.anchor_ns,
            support_steps=self.support_steps,
            expected_support_steps=expected,
            full_profile_requested=self.failure is None
            and self.last_ns == 25_000_000_000
            and self.anchor_ns is not None
            and self.support_steps == expected,
            qualification=QUALIFICATION,
        )


def apply_load(links, ecm, row, geometry, stream, attempt, *, vector):
    attempt.clear()
    attempt.update(dict(row, per_link=[], torque_call_returned=False, all_calls_returned=False))
    for name in sorted(links):
        force = [v * geometry["links"][name]["mass"] / geometry["mass_kg"] for v in row["force_world_n"]]
        attempt["per_link"].append(dict(name=name, force_world_n=force, call_returned=False))
    # Write and flush every requested vector before the first effect.
    journal(stream, dict(attempt, phase="requested"))
    try:
        for call in attempt["per_link"]:
            links[call["name"]].add_world_force(ecm, vector(*call["force_world_n"]))
            call["call_returned"] = True
        if any(row["torque_world_nm"]):
            links["base_link"].add_world_wrench(ecm, vector(0.0, 0.0, 0.0), vector(*row["torque_world_nm"]))
            attempt["torque_call_returned"] = True
        attempt["all_calls_returned"] = True
        journal(stream, dict(attempt, phase="returned"))
    except Exception as exc:
        attempt["partial_failure"] = repr(exc)
        journal(stream, dict(attempt, phase="partial_failure"))
        raise


def resolve_links(ecm, geometry):
    from gz.sim8 import K_NULL_ENTITY, Link, Model, World, world_entity

    world = World(world_entity(ecm))
    entity = world.model_by_name(ecm, "x500_benchmark_8")
    if entity == K_NULL_ENTITY:
        raise ValueError("calibration physical model missing")
    gravity = world.gravity(ecm)
    if gravity is None or [gravity.x(), gravity.y(), gravity.z()] != [0.0, 0.0, -9.81]:
        raise ValueError("calibration runtime gravity changed")
    links = {}
    for ident in Model(entity).links(ecm):
        link = Link(ident)
        name = link.name(ecm)
        if name in links or name not in geometry["links"]:
            raise ValueError("unexpected/duplicate calibration physical link")
        inertial = link.world_inertial(ecm)
        if inertial is None or abs(inertial.mass_matrix().mass() - geometry["links"][name]["mass"]) > 1e-10:
            raise ValueError("calibration runtime link mass changed")
        link.enable_bounding_box_checks(ecm)
        links[name] = link
    if set(links) != set(geometry["links"]):
        raise ValueError("incomplete calibration link set")
    base = links["base_link"]
    base.enable_velocity_checks(ecm)
    base.enable_acceleration_checks(ecm)
    return links


class CalibrationProbe:
    def __init__(
        self,
        output,
        errors,
        unarmed_stamp,
        *,
        scene,
        readiness,
        guard,
        trace,
        clock=time.monotonic_ns,
        resolver=resolve_links,
        vector=None,
    ):
        self.errors, self.unarmed_stamp = errors, unarmed_stamp
        self.geometry = copy.deepcopy(scene["geometry"])
        self.geometry["target_plane_world_x"] = scene["design"]["target_pose_world"][0]
        model = transform(self.geometry["model_pose_world"])
        base = transform(self.geometry["links"]["base_link"]["pose_model"])
        self.initial = (model @ base)[:3, 3]
        self.guard, self.trace, self.clock, self.resolver, self.vector = guard, trace, clock, resolver, vector
        self.links, self.last_attempt = None, None
        self.pre_traced_ns = None
        self.command_steps, self.audit_rows = 0, 0
        with ExitStack() as owned:
            self.commands = owned.enter_context((output / "calibration-load-calls.jsonl").open("x", encoding="utf8"))
            self.audit = owned.enter_context((output / "calibration-collision-audit.jsonl").open("x", encoding="utf8"))
            self.policy = CalibrationPolicy(
                self.geometry, readiness, lambda row: self.persist(output / "calibration-readiness-anchor.json", row)
            )
            owned.pop_all()

    @staticmethod
    def persist(path, row):
        with path.open("x", encoding="utf8") as stream:
            json.dump(row, stream, indent=2, allow_nan=False)
            stream.flush()

    def failed(self, exc):
        self.policy.failure = self.policy.failure or repr(exc)
        if not any(e.startswith("calibration motion:") for e in self.errors):
            self.errors.append("calibration motion: " + repr(exc))

    def check_state(self, ns, ecm, *, phase, enforce=True):
        base = self.links["base_link"]
        pose, velocity, angular = base.world_pose(ecm), base.world_linear_velocity(ecm), base.world_angular_velocity(ecm)
        if any(v is None for v in (pose, velocity, angular)):
            journal(self.audit, dict(sim_ns=ns, phase=phase, state_available=False, truth_abort_audit_only=True))
            self.audit_rows += 1
            if enforce and ns >= 100_000_000:
                self.policy.refuse("missing calibration physical state")
            return

        def xyz(v):
            return [v.x(), v.y(), v.z()]

        pos, vel, omega = xyz(pose.pos()), xyz(velocity), xyz(angular)
        rpy = [pose.rot().roll(), pose.rot().pitch(), pose.rot().yaw()]
        boxes = []
        for name, link in self.links.items():
            box = link.world_axis_aligned_box(ecm)
            if box is None:
                journal(
                    self.audit,
                    dict(sim_ns=ns, phase=phase, state_available=False, missing_collision_box=name, truth_abort_audit_only=True),
                )
                self.audit_rows += 1
                if not enforce or ns < 100_000_000:
                    return
                self.policy.refuse("missing calibration collision envelope")
            low, high = xyz(box.min()), xyz(box.max())
            if not all(math.isfinite(v) for v in low + high) or any(a > b for a, b in zip(low, high)):
                # Keep finite raw coordinates and explicit strings for nonfinite
                # values; JSON NaN is never silently admitted as valid geometry.
                diagnostic = dict(
                    name=name,
                    minimum=[v if math.isfinite(v) else repr(v) for v in low],
                    maximum=[v if math.isfinite(v) else repr(v) for v in high],
                )
                journal(
                    self.audit,
                    dict(
                        sim_ns=ns,
                        phase=phase,
                        state_available=False,
                        invalid_collision_box=diagnostic,
                        truth_abort_audit_only=True,
                    ),
                )
                self.audit_rows += 1
                if enforce:
                    self.policy.refuse("invalid calibration collision envelope")
                return
            boxes.append(dict(name=name, minimum=low, maximum=high))
        ground = min(b["minimum"][2] for b in boxes)
        gap = self.geometry["target_plane_world_x"] - max(b["maximum"][0] for b in boxes)
        row = dict(
            sim_ns=ns,
            phase=phase,
            position=pos,
            velocity_world=vel,
            angular_world=omega,
            rpy=rpy,
            boxes=boxes,
            ground_clearance_m=ground,
            target_plane_gap_m=gap,
            truth_abort_audit_only=True,
            state_available=True,
        )
        journal(self.audit, row)
        self.audit_rows += 1
        if not enforce:
            return
        self.policy.observe(pos, vel, rpy)
        if not all(math.isfinite(v) for v in omega) or math.hypot(*omega) > 0.5 or gap < 0.1:
            self.policy.refuse("calibration angular/target clearance bound")
        if self.policy.anchor_ns is None or ns <= self.policy.anchor_ns:
            if math.dist(pos, self.initial) > 0.001 or max(abs(v) for v in rpy) > 0.001:
                self.policy.refuse("calibration initial/anchor alignment bound")
        if self.policy.anchor_ns is not None and ns >= self.policy.anchor_ns + 2_000_000_000 and ground < 0.1:
            self.policy.refuse("calibration ground clearance bound")

    def pre_update(self, info, ecm):
        if self.errors or self.policy.failure:
            return
        try:
            self.guard()
            if info.paused:
                raise ValueError("paused calibration callback")
            if self.links is None:
                self.links = self.resolver(ecm, self.geometry)
            if self.vector is None:
                from gz.math7 import Vector3d

                self.vector = Vector3d
            ns = sim_duration_ns(info.sim_time)
            self.trace.observe("pre", info, self.links["base_link"], ecm)
            self.pre_traced_ns = ns
            self.check_state(ns, ecm, phase="pre")
            row = self.policy.step(ns, sim_duration_ns(info.dt), unarmed_wall_ns=self.unarmed_stamp(), wall_ns=self.clock())
            self.guard()
            if any(row["force_world_n"]) or any(row["torque_world_nm"]):
                self.last_attempt = {}
                apply_load(self.links, ecm, row, self.geometry, self.commands, self.last_attempt, vector=self.vector)
                self.command_steps += 1
            else:
                journal(self.commands, dict(row, phase="startup_no_calls"))
        except Exception as exc:
            self.failed(exc)

    def post_update(self, info, ecm):
        if self.links is None:
            return
        try:
            ns = sim_duration_ns(info.sim_time)
            matched = self.pre_traced_ns == ns
            if matched:
                try:
                    self.trace.observe("post", info, self.links["base_link"], ecm)
                except Exception as exc:
                    self.failed(exc)
                finally:
                    self.pre_traced_ns = None
            # Even a partial SDK application can affect the completed physics
            # step. Retain its post state without releasing the latched refusal.
            self.check_state(
                ns, ecm, phase="post" if matched else "post_after_refusal", enforce=not (self.errors or self.policy.failure)
            )
        except Exception as exc:
            self.failed(exc)

    def finish(self):
        closes = []
        for name, stream in (("commands", self.commands), ("audit", self.audit)):
            try:
                stream.close()
            except Exception as exc:
                closes.append(dict(stream=name, reason=repr(exc)))
                self.failed(exc)
        summary = self.policy.finish()
        if not summary["full_profile_requested"] or self.command_steps != self.policy.support_steps or self.audit_rows != 50000:
            self.failed(ValueError("incomplete calibration motion/audit"))
        return dict(
            self.policy.finish(),
            command_steps=self.command_steps,
            audit_rows=self.audit_rows,
            last_attempt=self.last_attempt,
            close_errors=closes,
            qualification=QUALIFICATION,
        )
