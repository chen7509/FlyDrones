"""Curriculum worlds remain deterministic, passable and separate from evaluation."""

import hashlib
import json

import pytest

from flydrones.benchmark.worlds import dynamic_center, has_route
from flydrones.connectome_training.corpus_config import CorpusJob
from flydrones.connectome_training.corpus_worlds import build_corpus_world, write_corpus_world


@pytest.mark.parametrize("stage,seed", [
    ("stability", 1101), ("looming", 1201), ("corridor", 1301),
    ("forest", 1401), ("dynamic", 1501), ("disturbance", 1601),
])
def test_stage_world_is_deterministic_and_statically_passable(stage, seed):
    job = CorpusJob(stage, "train", seed, 1, 0)
    first = build_corpus_world(job)
    second = build_corpus_world(job)
    def encoded(world):
        return json.dumps(world, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded(first)).hexdigest() == hashlib.sha256(encoded(second)).hexdigest()
    assert first["seed"] == seed
    assert first["corpus_stage"] == stage
    assert first["family"] != "formal"
    assert has_route(first, first["vehicle_envelope_radius_m"])


def test_stability_has_no_obstacle_and_looming_has_real_front_obstacle():
    stable = build_corpus_world(CorpusJob("stability", "train", 1101, 1, 0))
    looming = build_corpus_world(CorpusJob("looming", "train", 1201, 1, 1))
    assert stable["boxes"] == stable["cylinders"] == stable["dynamic"] == []
    assert looming["cylinders"]
    assert any(abs(tree["center"][1]) <= 0.5 for tree in looming["cylinders"])
    assert stable["start"] != stable["goal"]


@pytest.mark.parametrize("stage,seed", [("dynamic", 1501), ("disturbance", 1601)])
def test_moving_obstacle_leaves_a_passable_window(stage, seed):
    world = build_corpus_world(CorpusJob(stage, "train", seed, 1, 0))
    assert world["dynamic"]
    obstacle = world["dynamic"][0]
    windows = []
    for tick in range(8):
        center = dynamic_center(obstacle, tick * int(obstacle["period_s"] * 1e9) // 8)
        half = [size / 2 for size in obstacle["size"]]
        candidate = dict(world)
        candidate["boxes"] = [*world["boxes"], {
            "lo": [c - h for c, h in zip(center, half, strict=True)],
            "hi": [c + h for c, h in zip(center, half, strict=True)],
        }]
        windows.append(has_route(candidate, world["vehicle_envelope_radius_m"]))
    assert any(windows)


def test_disturbance_records_physical_wind_and_nonzero_sensor_disturbance():
    world = build_corpus_world(CorpusJob("disturbance", "train", 1601, 2, 0))
    assert any(abs(value) > 0 for value in world["wind"])
    assert world["sensor_perturbations"]["camera_delay_ms"] > 0
    assert world["sensor_perturbations"]["imu_bias_m_s2"] > 0
    assert world["sensor_perturbations"]["depth_noise_std_m"] > 0
    assert 0 < world["sensor_perturbations"]["max_consecutive_dropped_frames"] <= 3
    assert world["sensor_perturbations"]["truth_to_student"] is False


def test_validation_worlds_are_physically_disjoint_from_training_worlds():
    stages = {
        "stability": ((1101, 1102), 9101),
        "looming": ((1201, 1202), 9201),
        "corridor": ((1301, 1302), 9301),
        "forest": ((1401, 1402), 9401),
        "dynamic": ((1501, 1502), 9501),
        "disturbance": ((1601, 1602), 9601),
    }
    physical_keys = ("bounds", "start", "goal", "vehicle_envelope_radius_m",
                     "boxes", "cylinders", "dynamic", "wind")
    def physical(world):
        return tuple(json.dumps(world[key], sort_keys=True) for key in physical_keys)
    for stage, (train_seeds, val_seed) in stages.items():
        train = {physical(build_corpus_world(CorpusJob(stage, "train", seed, 1, 0)))
                 for seed in train_seeds}
        val = physical(build_corpus_world(CorpusJob(stage, "val", val_seed, 1, 0)))
        assert val not in train, stage


def test_world_writer_preserves_hashes_and_refuses_overwrite(tmp_path):
    job = CorpusJob("looming", "train", 1201, 1, 0)
    target = tmp_path / "world"
    world_json, world_sdf, digest = write_corpus_world(job, target)
    assert json.loads(world_json.read_text(encoding="utf-8"))["corpus_stage"] == "looming"
    assert hashlib.sha256(world_json.read_bytes()).hexdigest() == digest
    assert b"<collision" in world_sdf.read_bytes()
    with pytest.raises(FileExistsError):
        write_corpus_world(job, target)


def test_unknown_or_development_seed_cannot_generate_train_world():
    with pytest.raises(ValueError):
        build_corpus_world(CorpusJob("unknown", "train", 1101, 1, 0))
    with pytest.raises(ValueError):
        build_corpus_world(CorpusJob("forest", "train", 1701, 1, 0))
