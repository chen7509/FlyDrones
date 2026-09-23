from __future__ import annotations

import numpy as np
import pytest

from flydrones.multitask_contract import LocalObservation, PolicyIntent, Skill
from flydrones.multitask_reflex import MaleCNSReflexBridge


class StubMaleCNS:
    source = "malecns-v1.0-live"

    def __init__(
        self,
        *,
        actions=(),
        fallback_calls: int = 0,
        neurons: int = 166_700,
        connections: int = 25_582_837,
        error: Exception | None = None,
    ) -> None:
        self._actions = iter(actions)
        self._fallback_calls = fallback_calls
        self._neurons = neurons
        self._connections = connections
        self._error = error
        self.last_command_note = None
        self.neural_updates = 0
        self.inputs: list[np.ndarray] = []

    def predict(self, observation):
        values = np.asarray(observation, dtype=np.float32)
        self.inputs.append(values.copy())
        if self._error is not None:
            raise self._error
        forward, yaw, note = next(self._actions)
        self.last_command_note = note
        self.neural_updates += 1
        return np.asarray((forward, yaw), dtype=np.float32)

    @property
    def metrics(self):
        return {
            "source": self.source,
            "neurons": self._neurons,
            "connections": self._connections,
            "neural_updates": self.neural_updates,
            "fallback_calls": self._fallback_calls,
            "neural_update_p95_ms": 1.25,
        }


def local_observation() -> LocalObservation:
    visual = np.zeros(32, dtype=np.float32)
    visual[:16] = np.linspace(0.0, 1.0, 16, dtype=np.float32)
    return LocalObservation.from_arrays(
        visual,
        np.zeros(8),
        np.zeros(8),
        np.zeros(16),
        np.zeros(16),
        np.zeros(4),
        np.ones(6),
        maximum_age_s=0.5,
        age_s=0.0,
    )


def test_live_bridge_returns_none_for_go_and_override_for_escape():
    policy = StubMaleCNS(
        actions=[(0.5, 0.0, "malecns:go"), (-0.9, 0.8, "malecns:turn-away")]
    )
    bridge = MaleCNSReflexBridge(policy)

    clear = bridge.evaluate(local_observation())
    escape = bridge.evaluate(local_observation())

    assert clear.intent is None
    assert escape.intent == PolicyIntent(
        Skill.YIELD_RETURN_LAND, (0.0, 0.8, 0.0, 0.8), 1.0, 0.2
    )
    assert escape.evidence.source == "malecns-v1.0-live"
    assert policy.inputs[0].shape == (16,)
    assert np.count_nonzero(policy.inputs[0][5:14]) == 8


@pytest.mark.parametrize(
    "policy",
    [
        StubMaleCNS(actions=[(0.5, 0.0, "malecns:go")], fallback_calls=1),
        StubMaleCNS(actions=[(0.5, 0.0, "malecns:go")], neurons=10),
    ],
)
def test_required_live_backend_fails_on_fallback_or_wrong_metadata(policy):
    bridge = MaleCNSReflexBridge(policy, require_live=True)

    with pytest.raises(RuntimeError, match="MaleCNS"):
        bridge.evaluate(local_observation())


def test_policy_exception_fails_closed_and_records_fallback():
    bridge = MaleCNSReflexBridge(
        StubMaleCNS(error=RuntimeError("connectome stopped")), require_live=False
    )

    decision = bridge.evaluate(local_observation())

    assert decision.intent == PolicyIntent(
        Skill.YIELD_RETURN_LAND, (0.0, 0.0, 0.0, 0.0), 1.0, 0.2
    )
    assert decision.evidence.fallback_calls == 1


def test_brake_command_produces_zero_motion_override():
    bridge = MaleCNSReflexBridge(
        StubMaleCNS(actions=[(-1.0, 0.0, "malecns:brake")])
    )

    decision = bridge.evaluate(local_observation())

    assert decision.intent == PolicyIntent(
        Skill.YIELD_RETURN_LAND, (0.0, 0.0, 0.0, 0.0), 1.0, 0.2
    )
