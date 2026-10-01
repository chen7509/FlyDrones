"""Descending-neuron firing rates -> FlightCommand.

The decoder is deliberately a transparent linear read-out:

    axis = gain * sum_i  weight_i * (rate_i - baseline_i)

Baselines are measured while the brain settles with no stimulus. Weights come
from ``defaults.yaml`` (literature-guided) or from ``flydrones calibrate``
(fitted on the connectome you actually use). The brain's own wiring is never
changed.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .command import AXES, FlightCommand


class MotorDecoder:
    def __init__(self, cfg: dict):
        d = cfg.get("decoder", {})
        self.smoothing = float(d.get("smoothing", 0.35))
        self.deadzone = float(d.get("deadzone", 0.04))
        self.settle_s = float(d.get("settle_s", 1.5))
        self.axes = {a: dict(d.get("axes", {}).get(a, {"gain": 0.0, "terms": {}})) for a in AXES}
        self.cruise = float(d.get("cruise", 0.0))
        self.brake_terms = dict(d.get("brake_terms", {}))
        esc = d.get("escape", {}) or {}
        self.escape_terms = list(esc.get("terms", []))
        self.escape_threshold = float(esc.get("threshold_hz", 25))
        self.escape_mode = esc.get("mode", "climb")
        self.escape_duration = float(esc.get("duration_s", 0.7))
        self.escape_strength = float(esc.get("strength", 0.8))
        self.baseline: dict[str, float] = {}
        self._settle_sum: dict[str, float] = {}
        self._settle_n = 0
        self._elapsed = 0.0
        self._state = {a: 0.0 for a in AXES}
        self._escape_until = -1.0
        self._gf = 0.0  # smoothed giant-fiber rate
        self._brake = 0.0
        saccade = d.get("saccade_hold", {}) or {}
        self.saccade_enabled = bool(saccade.get("enabled", False))
        self.saccade_trigger = float(saccade.get("trigger", 0.2))
        self.saccade_duration = float(saccade.get("duration_s", 0.5))
        self.saccade_cooldown = float(saccade.get("cooldown_s", 0.0))
        self.saccade_activation_delay = float(saccade.get("activation_delay_s", 0.0))
        self.saccade_direction_memory = float(saccade.get("direction_memory_s", 0.0))
        self.saccade_strength = float(saccade.get("strength", 0.6))
        self.saccade_forward_max = float(saccade.get("forward_max", 0.05))
        self._saccade_until = -1.0
        self._saccade_cooldown_until = -1.0
        self._saccade_sign = 0.0
        self._saccade_ready_at = self.saccade_activation_delay
        self._saccade_direction_until = -1.0
        if d.get("readout_file"):
            self.load_readout(d["readout_file"])
        self.last_escape_t = None

    def load_readout(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for axis, spec in data.get("axes", {}).items():
            self.axes[axis] = {"gain": float(spec.get("gain", 1.0)), "terms": dict(spec["terms"])}
        if "cruise" in data:
            self.cruise = float(data["cruise"])
        if "baseline" in data:
            self.baseline = {k: float(v) for k, v in data["baseline"].items()}
            self.settle_s = 0.0

    @property
    def settled(self) -> bool:
        return self._elapsed >= self.settle_s

    def reset_transients(self) -> None:
        """Clear motor events accumulated while the brain was warming up."""
        self._escape_until = -1.0
        self._gf = 0.0
        self._saccade_until = -1.0
        self._saccade_cooldown_until = -1.0
        self._saccade_sign = 0.0
        self._saccade_ready_at = self._elapsed + self.saccade_activation_delay
        self._saccade_direction_until = -1.0

    def update(self, rates: dict[str, float], dt: float) -> FlightCommand:
        self._elapsed += dt
        if not self.settled:
            for k, v in rates.items():
                self._settle_sum[k] = self._settle_sum.get(k, 0.0) + v
            self._settle_n += 1
            return FlightCommand.hover("settling: measuring resting rates")
        if self._settle_n and not self.baseline:
            self.baseline = {k: v / self._settle_n for k, v in self._settle_sum.items()}

        raw = {}
        for axis, spec in self.axes.items():
            val = sum(w * (rates.get(g, 0.0) - self.baseline.get(g, 0.0)) for g, w in spec.get("terms", {}).items())
            raw[axis] = float(spec.get("gain", 0.0)) * val
        brake = sum(w * max(0.0, rates.get(g, 0.0) - self.baseline.get(g, 0.0)) for g, w in self.brake_terms.items())
        self._brake = max(brake, self._brake * 0.93)  # a scare keeps the fly cautious for a couple of seconds
        raw["forward"] += self.cruise * max(0.0, 1.0 - self._brake)

        a = self.smoothing
        for axis in AXES:
            v = max(-1.0, min(1.0, raw[axis]))
            self._state[axis] = (1 - a) * self._state[axis] + a * v
        out = {k: (0.0 if abs(v) < self.deadzone else v) for k, v in self._state.items()}
        cmd = FlightCommand(**out)

        # A fly commits to a brief body saccade rather than changing direction
        # on every noisy visual frame. The descending-neuron readout triggers
        # and selects the direction; this block only preserves that decision.
        if self.saccade_enabled:
            ready = self._elapsed + 1e-12 >= self._saccade_ready_at
            if ready and self._elapsed > self._saccade_cooldown_until and abs(cmd.yaw) >= self.saccade_trigger:
                requested_sign = math.copysign(1.0, cmd.yaw)
                if self._elapsed > self._saccade_direction_until or self._saccade_sign == 0.0:
                    self._saccade_sign = requested_sign
                    self._saccade_direction_until = self._elapsed + self.saccade_direction_memory
                self._saccade_until = self._elapsed + self.saccade_duration
                self._saccade_cooldown_until = self._saccade_until + self.saccade_cooldown
            if self._elapsed <= self._saccade_until:
                cmd.yaw = self._saccade_sign * max(abs(cmd.yaw), self.saccade_strength)
                cmd.forward = min(cmd.forward, self.saccade_forward_max)
                cmd.note = "descending-neuron saccade hold"
            elif self._elapsed <= self._saccade_cooldown_until:
                cmd.yaw = 0.0
                cmd.note = "descending-neuron saccade cooldown"

        # giant-fiber escape reflex
        if self.escape_terms:
            gf_now = max(rates.get(g, 0.0) for g in self.escape_terms)
            self._gf = 0.6 * self._gf + 0.4 * gf_now  # ~100 ms memory: one stray spike is not an escape
            if self._gf >= self.escape_threshold and self._elapsed > self._escape_until:
                self._escape_until = self._elapsed + self.escape_duration
                self.last_escape_t = self._elapsed
        if self._elapsed <= self._escape_until:
            cmd.escape = True
            cmd.forward = 0.0
            if self.escape_mode == "climb":
                cmd.throttle = self.escape_strength
            elif self.escape_mode == "drop":
                cmd.throttle = -self.escape_strength
            cmd.note = f"giant fiber escape ({self.escape_mode})"
        return cmd
