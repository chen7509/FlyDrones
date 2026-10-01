"""Full MaleCNS adapter with separately labelled, obstacle-blind goal guidance."""

import copy
import math
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from flydrones.brain import Brain, Connectome
from flydrones.motor import MotorDecoder
from flydrones.senses import InputEncoder, Retina

from .contract import Command, Decision, Observation
from .provenance import sha256_file


def body_command_to_enu(raw, yaw: float) -> Command:
    # Exactly the original MavlinkDrone defaults: v_max=1, vz_max=.5, yaw=45 deg/s.
    c, s = math.cos(yaw), math.sin(yaw)
    return Command((raw.forward*c + raw.lateral*s, raw.forward*s - raw.lateral*c, raw.throttle*.5),
                   -raw.yaw*math.pi/4)


def blend_goal(raw: Command, position: tuple, yaw: float, goal: tuple, *, gain: float, limit: float) -> Command:
    dx, dy = goal[0]-position[0], goal[1]-position[1]
    if math.hypot(dx, dy) < 1e-9:
        addition = 0.
    else:
        error = (math.atan2(dy, dx)-yaw+math.pi) % (2*math.pi)-math.pi
        addition = float(np.clip(gain*error, -limit, limit))
    return Command(raw.velocity_enu, float(np.clip(raw.yaw_rate+addition, -limit, limit)))


class FullFlyController:
    def __init__(self, config: dict, model_path: Path, guided: bool):
        self.config = copy.deepcopy(config)
        self.model_path = Path(model_path)
        self.guided = guided
        self.connectome = Connectome.load(self.model_path)
        if self.connectome.n != 166700:
            raise ValueError(f'full model required, got {self.connectome.n} neurons')
        self.model_sha256 = sha256_file(self.model_path)
        self.reset(42)

    def reset(self, seed: int) -> None:
        self.brain = Brain(self.connectome, self.config, seed=seed)
        self.retina = Retina.from_config(self.config)
        self.encoder = InputEncoder(self.connectome, self.config)
        self.decoder = MotorDecoder(self.config)
        self.calls = 0
        self.last_sim_ns = None

    def warmup(self, obs: Observation, seconds: float = 2.1):
        for _ in range(round(seconds/.05)):
            vision = self.retina.encode(obs.rgb)
            rates = self.brain.tick(self.encoder.encode(vision, 0.), ms=50.)
            self.decoder.update(rates, .05)
        self.decoder.reset_transients()

    def step(self, obs: Observation) -> Decision:
        if self.last_sim_ns is not None and obs.sim_ns-self.last_sim_ns != 50_000_000:
            raise ValueError('full brain requires consecutive 50 ms simulation steps')
        started = time.perf_counter()
        vision = self.retina.encode(obs.rgb)
        # Encoder expects degrees/s and clockwise positive, unlike ENU input.
        inputs = self.encoder.encode(vision, -math.degrees(obs.yaw_rate))
        brain_start = time.perf_counter()
        rates = self.brain.tick(inputs, ms=50.)
        brain_wall = time.perf_counter()-brain_start
        raw = self.decoder.update(rates, .05)
        neural = body_command_to_enu(raw, obs.yaw)
        final = blend_goal(neural, obs.position, obs.yaw, obs.goal, gain=.5, limit=.6) if self.guided else neural
        self.calls += 1
        self.last_sim_ns = obs.sim_ns
        return Decision(final, time.perf_counter()-started, {
            'controller': 'fly_guided' if self.guided else 'fly_raw', 'raw': asdict(neural), 'final': asdict(final),
            'guidance_yaw_delta': final.yaw_rate-neural.yaw_rate, 'normalized_neural': raw.as_dict(),
            'spikes': int(self.brain.last_counts.sum()), 'neurons': self.connectome.n,
            'connections': self.connectome.n_connections, 'brain_wall_s': brain_wall,
            'model_sha256': self.model_sha256,
            'frame_age_ns': obs.sim_ns-obs.frame_ns, 'calls': self.calls})

    def close(self) -> None:
        pass
