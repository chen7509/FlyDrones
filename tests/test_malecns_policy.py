from __future__ import annotations

import numpy as np
import pytest

from flydrones.malecns_policy import MaleCNSBinaryDecoder, MaleCNSPolicy, MaleCNSPolicyConfig
from flydrones.motor.command import FlightCommand


class FakeBrain:
    def __init__(self, *, rates=None, error: Exception | None = None):
        self.connectome = type("Connectome", (), {"n": 166_700, "n_connections": 25_582_837})()
        self.rates = rates or {"DNp03_L": 0.0, "DNp03_R": 0.0}
        self.error = error
        self.calls = []

    def tick(self, inputs, ms):
        self.calls.append((inputs, ms))
        if self.error is not None:
            raise self.error
        return dict(self.rates)


class FakeDecoder:
    def __init__(self, command: FlightCommand):
        self.command = command
        self.calls = []

    def update(self, rates, dt):
        self.calls.append((rates, dt))
        return self.command


class FallbackPolicy:
    def __init__(self):
        self.predict_calls = 0

    def predict(self, _observation):
        self.predict_calls += 1
        return np.asarray((0.25, -0.50), dtype=np.float32)


def observation(*, rays=None):
    values = np.zeros(16, dtype=np.float32)
    values[0] = 0.7
    values[2] = 1.0
    values[5:14] = np.asarray(rays if rays is not None else (0.0,) * 9, dtype=np.float32)
    return values


def test_depth_threats_are_injected_into_real_connectome_looming_groups():
    brain = FakeBrain()
    decoder = FakeDecoder(FlightCommand(forward=0.75))
    policy = MaleCNSPolicy(brain, decoder, config=MaleCNSPolicyConfig(refresh_every=1))

    policy.predict(observation(rays=(0.9, 0.8, 0.7, 0.6, 0.2, 0.0, 0.0, 0.0, 0.0)))

    inputs, window_ms = brain.calls[-1]
    assert inputs["LPLC2_L"] > inputs["LPLC2_R"]
    assert inputs["LC4_L"] > inputs["LC4_R"]
    assert window_ms == 50.0
    assert policy.source == "malecns-v1.0-live"


def test_descending_neuron_command_is_converted_to_hybrid_policy_action():
    brain = FakeBrain(rates={"DNp03_L": 170.0, "DNp03_R": 0.0})
    decoder = FakeDecoder(FlightCommand(forward=0.1, yaw=0.8))
    policy = MaleCNSPolicy(brain, decoder, config=MaleCNSPolicyConfig(refresh_every=1))

    action = policy.predict(observation(rays=(0.8,) * 4 + (0.2,) + (0.0,) * 4))

    assert action.tolist() == pytest.approx((-0.8, -0.8))
    assert policy.last_neural_rates["DNp03_L"] == 170.0
    assert policy.neural_updates == 1
    assert policy.predict_calls == 1


def test_refresh_stride_reuses_last_neural_action_without_rerunning_connectome():
    brain = FakeBrain()
    decoder = FakeDecoder(FlightCommand(forward=0.75, yaw=-0.4))
    policy = MaleCNSPolicy(brain, decoder, config=MaleCNSPolicyConfig(refresh_every=3))

    actions = [policy.predict(observation()) for _ in range(4)]

    assert len(brain.calls) == 2
    assert policy.neural_updates == 2
    assert policy.reused_actions == 2
    assert all(action.tolist() == pytest.approx((0.5, 0.4)) for action in actions)


def test_connectome_failure_uses_explicit_navigation_fallback():
    brain = FakeBrain(error=RuntimeError("neural runtime stopped"))
    fallback = FallbackPolicy()
    policy = MaleCNSPolicy(
        brain,
        FakeDecoder(FlightCommand()),
        fallback=fallback,
        config=MaleCNSPolicyConfig(refresh_every=1),
    )

    action = policy.predict(observation())

    assert action.tolist() == pytest.approx((0.25, -0.50))
    assert policy.fallback_calls == 1
    assert fallback.predict_calls == 1
    assert "neural runtime stopped" in policy.last_error


def test_invalid_policy_observation_fails_closed_before_neural_simulation():
    brain = FakeBrain()
    policy = MaleCNSPolicy(brain, FakeDecoder(FlightCommand()))

    with pytest.raises(ValueError, match="16 finite values"):
        policy.predict(np.zeros(15, dtype=np.float32))

    assert not brain.calls


def test_binary_decoder_maps_real_escape_neuron_sides_to_avoidance_primitives():
    decoder = MaleCNSBinaryDecoder(trigger_hz=25.0)

    clear = decoder.update({"DNp01_L": 0.0, "DNp01_R": 0.0}, 0.05)
    left_loom = decoder.update({"DNp01_L": 120.0, "DNp01_R": 0.0}, 0.05)
    right_loom = decoder.update({"DNp03_L": 0.0, "DNp03_R": 80.0}, 0.05)
    head_on = decoder.update({"DNp01_L": 90.0, "DNp01_R": 85.0}, 0.05)

    assert clear.forward == 0.75 and clear.yaw == 0.0
    assert left_loom.forward == 0.05 and left_loom.yaw > 0.0
    assert right_loom.forward == 0.05 and right_loom.yaw < 0.0
    assert head_on.forward == 0.0 and head_on.yaw == 0.0
