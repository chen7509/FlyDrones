"""Safety governor: the last word before any command reaches a motor.

The brain is a research model. It can be silent, saturate or do something
unexpected, so every command passes through hard limits that do not depend on
the brain at all.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from .motor.command import AXES, FlightCommand


@dataclass
class Telemetry:
    t: float = field(default_factory=time.monotonic)
    alt_m: float | None = None
    vz_mps: float | None = None
    yaw_deg: float | None = None
    yaw_rate_dps: float = 0.0
    x_m: float | None = None
    y_m: float | None = None
    battery_pct: float | None = None
    flying: bool = False


class VisualAvoidance:
    """Optional camera-level fallback that turns away from asymmetric looming."""

    def __init__(self, cfg: dict):
        spec = cfg.get("safety", {}).get("visual_avoidance", {}) or {}
        self.enabled = bool(spec.get("enabled", False))
        self.threshold = float(spec.get("loom_threshold", 0.2))
        self.yaw_strength = float(spec.get("yaw_strength", 0.45))
        self.hold_s = float(spec.get("hold_s", 0.8))
        self._remaining = 0.0
        self._direction = 0.0

    def update(self, cmd: FlightCommand, vision, dt: float) -> FlightCommand:
        if not self.enabled:
            return cmd
        left = float(vision.eyes["L"].grids["loom"].mean())
        right = float(vision.eyes["R"].grids["loom"].mean())
        looming = max(left, right) >= self.threshold
        if looming and self._remaining <= 0:
            self._direction = -1.0 if right > left else 1.0
        if looming:
            self._remaining = self.hold_s
        elif self._remaining <= 0:
            return cmd
        self._remaining = max(0.0, self._remaining - max(0.0, dt))
        return FlightCommand(cmd.throttle, self._direction * self.yaw_strength, 0.0,
                             cmd.lateral, cmd.escape, "visual avoidance")


class SafetyGovernor:
    def __init__(self, cfg: dict):
        s = cfg.get("safety", {})
        self.max = {"throttle": s.get("max_throttle", 0.6), "yaw": s.get("max_yaw", 0.6),
                    "forward": s.get("max_forward", 0.4), "lateral": s.get("max_lateral", 0.4)}
        self.slew = float(s.get("slew_per_s", 2.5))
        self.min_alt = float(s.get("min_alt_m", 0.3))
        self.floor_recovery = float(s.get("floor_recovery", 0.25))
        self.floor_trigger_margin = float(s.get("floor_trigger_margin", 0.1))
        self.floor_release_margin = float(s.get("floor_release_margin", 0.15))
        self.max_alt = float(s.get("max_alt_m", 2.0))
        self.fence = float(s.get("geofence_radius_m", 3.0))
        self.brain_timeout = float(s.get("brain_timeout_s", 0.5))
        self.min_batt = float(s.get("min_battery_pct", 20))
        self.max_flight = float(s.get("max_flight_s", 180))
        self._prev = FlightCommand()
        self._start = None
        self.land_requested = False
        self.kill = False
        self._floor_recovering = False
        self.events: list[str] = []

    def _event(self, msg: str) -> None:
        if not self.events or self.events[-1] != msg:
            self.events.append(msg)

    def filter(self, cmd: FlightCommand, tel: Telemetry, dt: float, brain_age_s: float = 0.0) -> FlightCommand:
        now = tel.t
        if self._start is None:
            self._start = now
        notes = []
        if self.kill:
            return FlightCommand.hover("KILL")
        if brain_age_s > self.brain_timeout:
            cmd = FlightCommand.hover("brain timeout -> hover")
            self._event("brain timeout")
        out = {a: max(-self.max[a], min(self.max[a], getattr(cmd, a))) for a in AXES}

        if tel.alt_m is not None:
            soft = self.max_alt - 0.3
            if soft < tel.alt_m < self.max_alt and out["throttle"] > 0:
                out["throttle"] *= (self.max_alt - tel.alt_m) / 0.3  # fade climbing out near the ceiling
            if tel.alt_m >= self.max_alt and out["throttle"] > 0:
                out["throttle"] = min(0.0, out["throttle"]) - 0.2
                notes.append("ceiling")
            if not tel.flying:
                self._floor_recovering = False
            elif (tel.alt_m <= self.min_alt or
                  (tel.vz_mps is not None and tel.vz_mps < 0 and
                   tel.alt_m <= self.min_alt + self.floor_trigger_margin)):
                self._floor_recovering = True
            elif self._floor_recovering and tel.alt_m >= self.min_alt + self.floor_release_margin:
                self._floor_recovering = False
            if self._floor_recovering:
                out["throttle"] = max(out["throttle"], self.floor_recovery)
                notes.append("floor recovery")
        if tel.x_m is not None and tel.y_m is not None:
            r = math.hypot(tel.x_m, tel.y_m)
            if r > self.fence and out["forward"] > 0:
                out["forward"] = 0.0
                notes.append("geofence")
        if tel.battery_pct is not None and tel.battery_pct < self.min_batt:
            self.land_requested = True
            notes.append("battery low -> land")
        if now - self._start > self.max_flight:
            self.land_requested = True
            notes.append("max flight time -> land")

        # slew-rate limit, but always allow moving toward zero instantly
        max_step = self.slew * max(dt, 1e-3)
        for a in AXES:
            prev = getattr(self._prev, a)
            v = out[a]
            if abs(v) > abs(prev) or math.copysign(1, v) != math.copysign(1, prev):
                v = max(prev - max_step, min(prev + max_step, v))
            out[a] = v
        safe = FlightCommand(**out, escape=cmd.escape, note="; ".join([cmd.note] + notes).strip("; "))
        for n in notes:
            self._event(n)
        self._prev = safe
        return safe
