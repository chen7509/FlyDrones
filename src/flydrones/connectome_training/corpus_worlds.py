"""Deterministic development-only worlds for the complete-connectome corpus."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from flydrones.benchmark.worlds import (
    dynamic_center,
    generate_development_world,
    generate_world,
    has_route,
    write_sdf,
)
from flydrones.connectome_training.corpus_config import STAGE_SEEDS, CorpusJob


def _dynamic_window_passable(world: dict) -> bool:
    if not world["dynamic"]:
        return True
    obstacle = world["dynamic"][0]
    period_ns = round(float(obstacle["period_s"]) * 1_000_000_000)
    for tick in range(8):
        center = dynamic_center(obstacle, tick * period_ns // 8)
        half = [float(value) / 2 for value in obstacle["size"]]
        candidate = dict(world)
        candidate["boxes"] = [*world["boxes"], {
            "lo": [float(c - h) for c, h in zip(center, half, strict=True)],
            "hi": [float(c + h) for c, h in zip(center, half, strict=True)],
        }]
        if has_route(candidate, world["vehicle_envelope_radius_m"]):
            return True
    return False


def _complex_world(job: CorpusJob) -> dict:
    family = {
        "corridor": "corridor", "forest": "forest",
        "dynamic": "disturbed", "disturbance": "disturbed",
    }[job.stage_id]
    for attempt in range(8):
        generator_seed = job.world_seed if attempt == 0 else int(
            np.random.SeedSequence([job.world_seed, attempt]).generate_state(1)[0])
        world = generate_world(generator_seed, family)
        if job.stage_id == "dynamic":
            world["wind"] = [0., 0., 0.]
        if _dynamic_window_passable(world):
            world["seed"] = job.world_seed
            world["source_generator_seed"] = generator_seed
            world["corpus_candidate"] = attempt
            return world
    raise ValueError("no passable dynamic obstacle window in eight candidates")


def _simple_world(job: CorpusJob) -> dict:
    world = copy.deepcopy(generate_development_world(1701))
    world["seed"] = job.world_seed
    world["source_generator_seed"] = 1701
    world["corpus_candidate"] = 0
    lane_y = round((job.world_seed // 1000 - 1) * .2, 3)
    world["start"][1] = lane_y
    world["goal"][1] = lane_y
    if job.stage_id == "stability":
        world["cylinders"] = []
        if job.world_seed % 2 == 0:
            world["start"], world["goal"] = world["goal"], world["start"]
    else:
        side = 1 if job.world_seed % 2 else -1
        world["cylinders"] = [
            {"center": [-2., lane_y], "radius": .6, "zlo": 0., "zhi": 4.5},
            {"center": [1.5, round(lane_y + side * 2., 3)],
             "radius": .45, "zlo": 0., "zhi": 3.},
        ]
    return world


def build_corpus_world(job: CorpusJob) -> dict:
    """Generate one world from fixed non-formal stage/split seed assignments."""
    if (not isinstance(job, CorpusJob) or job.stage_id not in STAGE_SEEDS
            or job.split not in ("train", "val")
            or job.world_seed not in STAGE_SEEDS[job.stage_id][job.split]
            or job.rollout_seed not in (1, 2, 3) or job.ordinal < 0):
        raise ValueError("unknown curriculum world job")
    world = (_simple_world(job) if job.stage_id in ("stability", "looming")
             else _complex_world(job))
    world["family"] = job.stage_id
    world["corpus_stage"] = job.stage_id
    world["corpus_split"] = job.split
    world["rollout_seed"] = job.rollout_seed
    rng = np.random.default_rng(np.random.SeedSequence([job.world_seed, job.rollout_seed]))
    world["sensor_perturbations"] = {
        "camera_delay_ms": (round(float(rng.uniform(20., 80.)), 3)
                            if job.stage_id == "disturbance" else 0.),
        "imu_bias_m_s2": (round(float(rng.uniform(.01, .05)), 5)
                          if job.stage_id == "disturbance" else 0.),
        "depth_noise_std_m": (round(float(rng.uniform(.01, .05)), 5)
                              if job.stage_id == "disturbance" else 0.),
        "max_consecutive_dropped_frames": (int(rng.integers(1, 4))
                                           if job.stage_id == "disturbance" else 0),
        "truth_to_student": False,
    }
    if not has_route(world, world["vehicle_envelope_radius_m"]):
        raise ValueError("curriculum world has no static route")
    return world


def write_corpus_world(job: CorpusJob, directory: Path) -> tuple[Path, Path, str]:
    """Write a non-overwriting JSON/SDF pair; return the JSON content digest."""
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError(f"refusing to overwrite {directory}")
    world = build_corpus_world(job)
    directory.mkdir(parents=True)
    json_path, sdf_path = directory / "world.json", directory / "world.sdf"
    payload = (json.dumps(world, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with json_path.open("xb") as stream:
        stream.write(payload)
    write_sdf(world, sdf_path)
    return json_path, sdf_path, hashlib.sha256(payload).hexdigest()
