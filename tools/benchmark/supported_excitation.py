"""Time-only external support; simulator truth is restricted to abort/audit."""

from __future__ import annotations

import hashlib
import json
import math
import time
import xml.etree.ElementTree as ET
from contextlib import ExitStack
from pathlib import Path

from flydrones.benchmark.gateway import sim_duration_ns
from tools.benchmark.disarmed_motion_probe import GazeboMotionProbe, MotionPolicy, profile

MASSES = {"base_link": 2.0, **{f"rotor_{i}": 0.016076923076923075 for i in range(4)}, "camera_link": 0.061}


def validate_gravity_configuration(world, models):
    gravity = [float(v) for v in ET.parse(world).getroot().findtext("world/gravity", "").split()]
    if gravity != [0.0, 0.0, -9.81]:
        raise ValueError("unexpected world gravity configuration")
    names = []
    for path in models:
        root = ET.parse(path).getroot()
        for value in root.findall(".//gravity"):
            if (value.text or "").strip().lower() not in ("1", "true"):
                raise ValueError("disabled/unsupported link gravity")
        names.extend(link.attrib["name"] for link in root.findall(".//link"))
    if sorted(names) != sorted(MASSES):
        raise ValueError("gravity configuration link set mismatch")
    return dict(
        world_gravity=gravity,
        per_link_scope="SDF configuration, not runtime GravityEnabled readback",
        source_hashes={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [world, *models]},
    )


def validate_links(masses):
    if set(masses) != set(MASSES) or any(
        type(masses[k]) not in (float, int) or not math.isfinite(masses[k]) or abs(masses[k] - MASSES[k]) > 1e-10 for k in MASSES
    ):
        raise ValueError("unsupported link/mass profile")
    return sum(MASSES.values())


def supported_profile():
    return dict(
        profile(),
        name="supported-lateral-v1",
        start_ns=2_000_000_000,
        stop_ns=25_001_000_000,
        expected_active_steps=23001,
        lateral_active_steps=1600,
        fixed_masses_kg=MASSES,
        gravity_m_s2=9.81,
        lift_start_s=2,
        lift_end_s=4,
        lift_height_m=0.4,
        minimum_ground_clearance_m=0.1,
        max_total_force_n=40.0,
        force_distribution="each link COM proportional to static mass",
        truth_feedback=False,
    )


class SupportedPolicy(MotionPolicy):
    def __init__(self):
        super().__init__()
        self.support_steps = 0

    def step(self, ns, dt_ns, *, unarmed_wall_ns, wall_ns):
        lateral = super().step(ns, dt_ns, unarmed_wall_ns=unarmed_wall_ns, wall_ns=wall_ns)
        if ns > 25_000_000_000:
            self.refuse("support duration exceeded")
        if ns < 2_000_000_000:
            return [0.0, 0.0, 0.0]
        if (
            type(unarmed_wall_ns) is not int
            or type(wall_ns) is not int
            or unarmed_wall_ns <= 0
            or not 0 <= wall_ns - unarmed_wall_ns <= 2_000_000_000
        ):
            self.refuse("missing/stale/future disarmed heartbeat")
        u = (ns * 1e-9 - 2) / 2
        acceleration = 0.1 * (60 * u - 180 * u * u + 120 * u * u * u) if 0 <= u < 1 else 0.0
        force = [0.0, lateral, sum(MASSES.values()) * (9.81 + acceleration)]
        if not all(math.isfinite(v) for v in force) or math.hypot(*force) > 40:
            self.refuse("external force bound exceeded")
        self.support_steps += 1
        return force

    def check_clearance(self, ns, clearance):
        self._available()
        if type(clearance) not in (int, float) or not math.isfinite(clearance):
            self.refuse("missing/nonfinite geometric clearance")
        if ns >= 4_000_000_000 and clearance < 0.1:
            self.refuse("geometric ground clearance bound exceeded")

    def finish(self):
        out = super().finish()
        out.update(
            support_steps=self.support_steps,
            full_profile_requested=out["full_profile_requested"]
            and self.support_steps == 23001
            and self.last_ns == 25_000_000_000,
        )
        return out


def write_row(stream, row):
    encoded = json.dumps(row, allow_nan=False) + "\n"
    if stream.write(encoded) != len(encoded):
        raise OSError("short fixture journal write")


class SupportedProbe(GazeboMotionProbe):
    def __init__(self, output, errors, unarmed_stamp, *, trace):
        with ExitStack() as owned:
            self.clearance = owned.enter_context((output / "support-clearance.jsonl").open("x"))
            super().__init__(
                output, errors, unarmed_stamp, trace=trace, policy=SupportedPolicy(), profile_data=supported_profile()
            )
            owned.pop_all()
        self.output = output
        self.links = None
        self.clearance_records = 0

    def pre_update(self, info, ecm):
        if self.errors or self.policy.failure:
            return
        try:
            from gz.math7 import Vector3d
            from gz.sim8 import K_NULL_ENTITY, Link, Model, World, world_entity

            ns = sim_duration_ns(info.sim_time)
            if info.paused:
                self.policy.refuse("paused fixture step")
            if self.links is None:
                world = World(world_entity(ecm))
                entity = world.model_by_name(ecm, "x500_benchmark_8")
                if entity == K_NULL_ENTITY:
                    self.policy.refuse("required model missing")
                gravity = world.gravity(ecm)
                if gravity is None or [gravity.x(), gravity.y(), gravity.z()] != [0.0, 0.0, -9.81]:
                    self.policy.refuse("unexpected runtime world gravity")
                px4 = Path.home() / "PX4-Autopilot/Tools/simulation/gz/models"
                assets = Path(__file__).resolve().parents[2] / "assets/gazebo/models"
                gravity_evidence = validate_gravity_configuration(
                    self.output / "world.sdf",
                    [
                        px4 / "x500_base/model.sdf",
                        px4 / "x500/model.sdf",
                        assets / "x500_benchmark/model.sdf",
                        assets / "OakD-Benchmark/model.sdf",
                    ],
                )
                self.links = {}
                masses = {}
                for ident in Model(entity).links(ecm):
                    link = Link(ident)
                    name = link.name(ecm)
                    if name in self.links:
                        self.policy.refuse("duplicate physical link")
                    inertial = link.world_inertial(ecm)
                    if inertial is None:
                        self.policy.refuse("missing mass")
                    masses[name] = inertial.mass_matrix().mass()
                    self.links[name] = link
                    link.enable_bounding_box_checks(ecm)
                validate_links(masses)
                self.link = self.links["base_link"]
                self.link.enable_velocity_checks(ecm)
                self.link.enable_acceleration_checks(ecm)
                with (self.output / "support-links.json").open("x") as f:
                    json.dump(
                        dict(
                            masses=masses, gravity=gravity_evidence, runtime_world_gravity=[gravity.x(), gravity.y(), gravity.z()]
                        ),
                        f,
                        indent=2,
                    )
            self.trace.observe("pre", info, self.link, ecm)
            force = self.policy.step(
                ns, sim_duration_ns(info.dt), unarmed_wall_ns=self.unarmed_stamp(), wall_ns=time.monotonic_ns()
            )
            if any(force):
                self.last_attempt = dict(
                    sim_ns=ns,
                    dt_ns=sim_duration_ns(info.dt),
                    force_world_n=force,
                    per_link=[],
                    call_returned=False,
                    wall_ns=time.monotonic_ns(),
                )
                for name, link in self.links.items():
                    vector = [v * MASSES[name] / sum(MASSES.values()) for v in force]
                    call = dict(name=name, force_world_n=vector, call_returned=False)
                    self.last_attempt["per_link"].append(call)
                    link.add_world_force(ecm, Vector3d(*vector))
                    call["call_returned"] = True
                self.last_attempt["call_returned"] = True
                write_row(self.commands, self.last_attempt)
                self.recorded_commands += 1
                if self.recorded_commands % 100 == 0:
                    self.commands.flush()
        except Exception as exc:
            self._failed(exc)

    def post_update(self, info, ecm):
        super().post_update(info, ecm)
        if self.errors or self.policy.failure or self.links is None:
            return
        try:
            boxes = []
            for name, link in self.links.items():
                box = link.world_axis_aligned_box(ecm)
                if box is None:
                    self.policy.refuse("missing physical bounding box")
                low, high = box.min(), box.max()
                lo = [low.x(), low.y(), low.z()]
                hi = [high.x(), high.y(), high.z()]
                if not all(math.isfinite(v) for v in lo + hi) or any(a > b for a, b in zip(lo, hi)):
                    self.policy.refuse("invalid physical bounding box")
                boxes.append(dict(name=name, minimum=lo, maximum=hi))
            ns = sim_duration_ns(info.sim_time)
            minimum = min(b["minimum"][2] for b in boxes)
            write_row(self.clearance, dict(sim_ns=ns, boxes=boxes, ground_clearance_m=minimum, truth_for_abort_audit_only=True))
            self.clearance_records += 1
            self.policy.check_clearance(ns, minimum)
            if self.clearance_records % 100 == 0:
                self.clearance.flush()
        except Exception as exc:
            self._failed(exc)

    def finish(self):
        clearance_errors = []
        try:
            self.clearance.close()
        except Exception as exc:
            clearance_errors.append(dict(stream="clearance", reason=repr(exc)))
            self._failed(exc)
        if self.clearance_records != 25000 or not self.policy.finish()["full_profile_requested"]:
            self._failed(ValueError("incomplete supported fixture"))
        result = super().finish()
        result["close_errors"].extend(clearance_errors)
        return dict(result, clearance_records=self.clearance_records)
