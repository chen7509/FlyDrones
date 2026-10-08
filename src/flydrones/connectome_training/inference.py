"""Single-owner, CPU-only offline policy inference; never a flight publisher."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from hashlib import sha256

import numpy as np
import torch

from flydrones.benchmark.contract import Command, Decision
from flydrones.benchmark.gateway import shape_command

from .dataset import SequenceFrame
from .features import frame_features
from .inference_artifact import LoadedInferenceCore

DT_NS = 50_000_000
MAX_FRAME_AGE_NS = 100_000_000


@dataclass(frozen=True)
class InferenceLimits:
    speed_max_mps: float = 0.8
    acceleration_max_mps2: float = 1.2
    yaw_rate_max_radps: float = 0.6

    def __post_init__(self):
        for value in (self.speed_max_mps, self.acceleration_max_mps2, self.yaw_rate_max_radps):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("inference limits must be finite positive numbers")


DEFAULT_LIMITS = InferenceLimits()


def _timestamp(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not 0 <= value < 2**63:
        raise ValueError(f"{name} must be a nonnegative int64 timestamp")
    return int(value)


def _image_digest(rgb, depth):
    digest = sha256()
    for value in (rgb, depth):
        digest.update(str((value.shape, value.dtype.str)).encode("ascii"))
        digest.update(np.ascontiguousarray(value).tobytes())
    return digest.hexdigest()


class ConnectomeInferenceController:
    """Own one loaded core/session. Inputs are offline arrays, not VIO proof.

    Source authenticity and the flight safety supervisor are outside this API.
    A returned intent is never permission to arm or publish to a flight stack.
    """

    def __init__(self, loaded: LoadedInferenceCore, limits: InferenceLimits = DEFAULT_LIMITS):
        if not isinstance(loaded, LoadedInferenceCore) or not isinstance(limits, InferenceLimits):
            raise ValueError("loaded core and validated limits required")
        if any(value.device.type != "cpu" for value in loaded.core.parameters()):
            raise ValueError("only synchronous CPU inference is supported")
        self._core = loaded.core
        self._core.eval()
        self._core.requires_grad_(False)
        self.provenance = dict(loaded.provenance)
        self.limits = limits
        self.closed = False
        self.session_index = 0
        self.reset(0)

    def reset(self, seed: int):
        if self.closed:
            raise RuntimeError("inference controller is closed")
        if type(seed) is not int or seed < 0:
            raise ValueError("reset seed must be a nonnegative integer")
        self._state = self._core.initial_state(1)
        self._previous = Command((0., 0., 0.), 0.)
        self.last_sim_ns = None
        self.last_frame_ns = None
        self._last_image_digest = None
        self.call_index = 0
        self.failure = None
        self.session_index += 1
        # Current core is deterministic; record the seed without changing global RNG.
        self.reset_seed = seed

    def step(self, frame: SequenceFrame) -> Decision:
        if self.closed:
            raise RuntimeError("inference controller is closed")
        if self.failure is not None:
            raise RuntimeError(f"inference session failed: {self.failure}")
        started = time.perf_counter_ns()
        try:
            if not isinstance(frame, SequenceFrame):
                raise ValueError("offline SequenceFrame input required")
            sim_ns = _timestamp(frame.sim_ns, "sim_ns")
            frame_ns = _timestamp(frame.frame_ns, "frame_ns")
            if self.last_sim_ns is not None and sim_ns - self.last_sim_ns != DT_NS:
                raise ValueError("inference requires consecutive 50 ms steps")
            if not 0 <= sim_ns - frame_ns <= MAX_FRAME_AGE_NS:
                raise ValueError("camera age is outside the causal window")
            if self.last_frame_ns is not None and frame_ns < self.last_frame_ns:
                raise ValueError("camera timestamp regressed")
            rgb, depth = np.asarray(frame.rgb), np.asarray(frame.depth_m)
            if (rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3
                    or rgb.shape[0] < 1 or rgb.shape[1] < 3 or depth.shape != rgb.shape[:2]):
                raise ValueError("nonempty uint8 RGB and matching depth required")
            features = frame_features(frame)
            if not np.isfinite(features).all():
                raise ValueError("inference features are nonfinite")
            image_digest = _image_digest(rgb, depth)
            reused = frame_ns == self.last_frame_ns
            if reused and image_digest != self._last_image_digest:
                raise ValueError("reused camera timestamp has changed image content")
            if not torch.isfinite(self._state.voltage).all():
                raise ValueError("core prior state is nonfinite")
            core_started = time.perf_counter_ns()
            with torch.inference_mode():
                raw, next_state = self._core.forward_step(
                    torch.from_numpy(features)[None, :], self._state, DT_NS / 1e9,
                )
                if (raw.shape != (1, 4) or next_state.voltage.shape != (1, self._core.n_neurons)
                        or not torch.isfinite(raw).all() or not torch.isfinite(next_state.voltage).all()):
                    raise ValueError("core returned invalid output or state")
                raw_values = raw[0].tolist()
            core_wall_s = (time.perf_counter_ns() - core_started) / 1e9
            requested = Command(tuple(raw_values[:3]), raw_values[3])
            shaped = shape_command(
                requested, self._previous, dt_s=DT_NS / 1e9,
                speed_max=self.limits.speed_max_mps,
                acceleration_max=self.limits.acceleration_max_mps2,
                yaw_rate_max=self.limits.yaw_rate_max_radps,
            )
            evidence = {
                "core_kind": self.provenance["core_kind"],
                "parameter_origin": self.provenance["parameter_origin"],
                "full_topology": self.provenance["full_topology"],
                "model_identity": self.provenance["model_identity"],
                "checkpoint_sha256": self.provenance["checkpoint_sha256"],
                "training_success_verified": False, "flight_eligible": False,
                "raw_command": raw_values, "brain_wall_s": core_wall_s,
                "sim_ns": sim_ns, "frame_ns": frame_ns, "frame_age_ns": sim_ns - frame_ns,
                "camera_reused": reused, "image_sha256": image_digest,
                "call_index": self.call_index + 1, "session_index": self.session_index,
                "reset_seed": self.reset_seed,
            }
            decision = Decision(shaped, (time.perf_counter_ns() - started) / 1e9, evidence)
            # No state/time/command commit until every validation succeeds.
            self._state, self._previous = next_state, shaped
            self.last_sim_ns, self.last_frame_ns = sim_ns, frame_ns
            self._last_image_digest = image_digest
            self.call_index += 1
            return decision
        except Exception as error:
            self.failure = f"{type(error).__name__}: {error}"
            raise

    def close(self):
        self.closed = True
        self._state = None
