"""Live MaleCNS descending-neuron policy for the hybrid mission agent.

The mission planner still supplies the destination.  This adapter turns the
planner's nine depth sectors into looming input rates, advances the published
MaleCNS graph, and decodes its descending-neuron rates into a motion
preference.  The existing binary behaviour layer then thresholds that
preference into auditable yes/no votes.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .motor.command import FlightCommand


@dataclass(frozen=True)
class MaleCNSPolicyConfig:
    neural_window_ms: float = 50.0
    refresh_every: int = 5
    looming_max_hz: float = 200.0
    looming_speed_max_hz: float = 150.0
    brightness_hz: float = 20.0

    def __post_init__(self) -> None:
        positive = (
            self.neural_window_ms,
            self.looming_max_hz,
            self.looming_speed_max_hz,
            self.brightness_hz,
        )
        if not all(math.isfinite(value) and value > 0.0 for value in positive):
            raise ValueError("MaleCNS policy rates and window must be finite and positive")
        if not isinstance(self.refresh_every, int) or self.refresh_every < 1:
            raise ValueError("MaleCNS refresh_every must be a positive integer")


class MaleCNSBinaryDecoder:
    """Threshold escape/saccade descending neurons into fixed primitives."""

    def __init__(
        self,
        *,
        trigger_hz: float = 25.0,
        direction_margin_hz: float = 10.0,
        cruise: float = 0.75,
        turn_forward: float = 0.05,
        turn_yaw: float = 0.80,
    ) -> None:
        values = (trigger_hz, direction_margin_hz, cruise, turn_forward, turn_yaw)
        if not all(math.isfinite(value) and value >= 0.0 for value in values):
            raise ValueError("MaleCNS binary decoder values must be finite and non-negative")
        self.trigger_hz = float(trigger_hz)
        self.direction_margin_hz = float(direction_margin_hz)
        self.cruise = float(cruise)
        self.turn_forward = float(turn_forward)
        self.turn_yaw = float(turn_yaw)

    @staticmethod
    def _side_rate(rates: dict[str, float], side: str) -> float:
        values = (
            float(rates.get(f"DNp01_{side}", 0.0)),
            float(rates.get(f"DNp03_{side}", 0.0)),
        )
        if not all(math.isfinite(value) and value >= 0.0 for value in values):
            raise ValueError("descending-neuron rates must be finite and non-negative")
        return max(values)

    def update(self, rates: dict[str, float], _dt: float) -> FlightCommand:
        left = self._side_rate(rates, "L")
        right = self._side_rate(rates, "R")
        if max(left, right) < self.trigger_hz:
            return FlightCommand(forward=self.cruise, note="malecns:go")
        if abs(left - right) <= self.direction_margin_hz:
            return FlightCommand(note="malecns:brake")
        yaw = self.turn_yaw if left > right else -self.turn_yaw
        return FlightCommand(forward=self.turn_forward, yaw=yaw, note="malecns:turn-away")


class MaleCNSPolicy:
    """Expose a live connectome and descending-neuron decoder as ``predict``."""

    source = "malecns-v1.0-live"

    def __init__(self, brain, decoder, *, fallback=None, config: MaleCNSPolicyConfig | None = None) -> None:
        self.brain = brain
        self.decoder = decoder
        self.fallback = fallback
        self.config = config or MaleCNSPolicyConfig()
        self.predict_calls = 0
        self.neural_updates = 0
        self.reused_actions = 0
        self.fallback_calls = 0
        self.last_error = ""
        self.last_neural_rates: dict[str, float] = {}
        self.last_inputs: dict[str, float] = {}
        self.last_action: np.ndarray | None = None
        self.last_command_note: str | None = None
        self._previous_threat = (0.0, 0.0)
        self.update_times_ms: list[float] = []

    @classmethod
    def from_files(
        cls,
        connectome_path: str | Path,
        brain_config_path: str | Path,
        readout_path: str | Path | None = None,
        *,
        seed: int = 0,
        fallback=None,
        config: MaleCNSPolicyConfig | None = None,
        warmup_ms: float = 1500.0,
    ) -> MaleCNSPolicy:
        """Load the full graph and validated readout, then settle neural state."""
        from .brain import Brain, Connectome
        from .config import load_config
        from .motor.decoder import MotorDecoder

        connectome = Connectome.load(connectome_path)
        cfg = load_config(brain_config_path)
        brain = Brain(connectome, cfg, seed=seed)
        if warmup_ms > 0.0:
            brain.tick({}, float(warmup_ms))
        if readout_path is None:
            decoder = MaleCNSBinaryDecoder()
        else:
            cfg["decoder"]["readout_file"] = str(readout_path)
            decoder = MotorDecoder(cfg)
        return cls(brain, decoder, fallback=fallback, config=config)

    def _neural_inputs(self, observation: np.ndarray) -> dict[str, float]:
        proximity = np.clip(observation[5:14], 0.0, 1.0)
        left_threat = float(np.mean(proximity[:5]))
        right_threat = float(np.mean(proximity[4:]))
        left_speed = max(0.0, left_threat - self._previous_threat[0])
        right_speed = max(0.0, right_threat - self._previous_threat[1])
        self._previous_threat = (left_threat, right_threat)
        clear_fraction = 1.0 - max(left_threat, right_threat)
        return {
            "R16_L": self.config.brightness_hz * clear_fraction,
            "R16_R": self.config.brightness_hz * clear_fraction,
            "LPLC2_L": self.config.looming_max_hz * left_threat,
            "LPLC2_R": self.config.looming_max_hz * right_threat,
            "LC4_L": self.config.looming_speed_max_hz * left_speed,
            "LC4_R": self.config.looming_speed_max_hz * right_speed,
        }

    @staticmethod
    def _action_from_command(command: FlightCommand) -> np.ndarray:
        values = (command.forward, command.yaw)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("MaleCNS decoder produced a non-finite command")
        forward = float(np.clip(command.forward, 0.0, 1.0))
        yaw = float(np.clip(command.yaw, -1.0, 1.0))
        return np.asarray((2.0 * forward - 1.0, -yaw), dtype=np.float32)

    def _fallback_action(self, observation: np.ndarray) -> np.ndarray:
        self.fallback_calls += 1
        if self.fallback is None:
            return np.asarray((-1.0, 0.0), dtype=np.float32)
        action = np.asarray(self.fallback.predict(observation), dtype=np.float32).reshape(-1)
        if action.shape != (2,) or not np.all(np.isfinite(action)):
            return np.asarray((-1.0, 0.0), dtype=np.float32)
        return np.clip(action, -1.0, 1.0).astype(np.float32)

    def predict(self, observation: np.ndarray) -> np.ndarray:
        values = np.asarray(observation, dtype=np.float32)
        if values.shape != (16,) or not np.all(np.isfinite(values)):
            raise ValueError("MaleCNS policy observation must contain 16 finite values")

        call_index = self.predict_calls
        self.predict_calls += 1
        refresh = self.last_action is None or call_index % self.config.refresh_every == 0
        if not refresh:
            self.reused_actions += 1
            return self.last_action.copy()

        self.last_inputs = self._neural_inputs(values)
        started = time.perf_counter()
        try:
            rates = self.brain.tick(self.last_inputs, self.config.neural_window_ms)
            command = self.decoder.update(rates, self.config.neural_window_ms / 1000.0)
            action = self._action_from_command(command)
            self.last_command_note = command.note
            self.last_neural_rates = {name: float(rate) for name, rate in rates.items()}
            self.last_error = ""
            self.neural_updates += 1
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.last_command_note = None
            action = self._fallback_action(values)
        self.update_times_ms.append((time.perf_counter() - started) * 1000.0)
        self.last_action = action
        return action.copy()

    @property
    def metrics(self) -> dict:
        ordered = sorted(self.update_times_ms)
        p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)] if ordered else 0.0
        connectome = getattr(self.brain, "connectome", None)
        return {
            "source": self.source,
            "neurons": int(getattr(connectome, "n", 0)),
            "connections": int(getattr(connectome, "n_connections", 0)),
            "predict_calls": self.predict_calls,
            "neural_updates": self.neural_updates,
            "reused_actions": self.reused_actions,
            "fallback_calls": self.fallback_calls,
            "neural_update_p95_ms": round(p95, 5),
            "last_error": self.last_error or None,
        }
