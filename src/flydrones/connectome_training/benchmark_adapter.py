"""Offline Observation boundary for the rate core; no flight or source qualification.

This is not registered with run_episode.py. The existing physical benchmark's
truth-derived observations are not VIO, and declaring a source is not verifying it.
"""
from __future__ import annotations

import time

import numpy as np

from flydrones.benchmark.contract import Decision, Observation

from .dataset import SequenceFrame
from .inference import ConnectomeInferenceController, InferenceLimits
from .inference_artifact import LoadedInferenceCore


def observation_frame(observation: Observation) -> SequenceFrame:
    """Copy used fields without changing units, axes, timestamps or image dtype.

    camera_pose is deliberately unused by this core's feature mapping. This
    conversion is not validation: the controller enforces its causal/state gates.
    The caller must own the observation for the duration of this synchronous call.
    """
    if not isinstance(observation, Observation):
        raise ValueError('benchmark Observation required')
    return SequenceFrame(
        observation.sim_ns, observation.frame_ns,
        np.array(observation.rgb, copy=True), np.array(observation.depth_m, copy=True),
        np.array(observation.position, copy=True), np.array(observation.velocity, copy=True),
        observation.yaw, observation.yaw_rate, np.array(observation.goal, copy=True),
    )


class OfflineBenchmarkController:
    """Single-owner Controller protocol adapter, explicitly offline/unqualified.

    Supply limits from the intended comparison; this adapter does not choose or
    freeze a benchmark configuration. Loaded cores remain identity-bound by the
    existing loader. No optimizer, simulator, socket or flight authority is added.
    """

    def __init__(self, loaded: LoadedInferenceCore, *, observation_source: str,
                 limits: InferenceLimits):
        if (type(observation_source) is not str
                or observation_source not in {'synthetic', 'gazebo-model-truth'}):
            raise ValueError('only explicitly unqualified offline observation sources are supported')
        self._source = observation_source
        self._controller = ConnectomeInferenceController(loaded, limits)
        self.failure = None

    def reset(self, seed: int):
        self._controller.reset(seed)
        self.failure = None

    def step(self, observation: Observation) -> Decision:
        if self._controller.closed:
            raise RuntimeError('offline benchmark controller is closed')
        if self.failure is not None:
            raise RuntimeError(f'offline benchmark session failed: {self.failure}')
        started = time.perf_counter_ns()
        try:
            decision = self._controller.step(observation_frame(observation))
            evidence = dict(decision.evidence)
            evidence.update(
                policy_kind='offline-connectome-rate-core',
                observation_source_declared=self._source,
                input_source_verified=False,
                inference_elapsed_wall_s=decision.elapsed_wall_s,
            )
            return Decision(decision.command, (time.perf_counter_ns() - started) / 1e9, evidence)
        except Exception as error:
            self.failure = f'{type(error).__name__}: {error}'
            raise

    def close(self):
        self._controller.close()
