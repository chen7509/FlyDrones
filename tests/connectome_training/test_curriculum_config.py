from pathlib import Path

import pytest
import yaml

from flydrones.connectome_training.curriculum_config import (
    load_curriculum_config,
)


def config_dict():
    return {
        "schema": "flydrones-connectome-curriculum-v1",
        "seed": 17,
        "profiles": {
            "smoke": {
                "data_mode": "synthetic-smoke",
                "model_mode": "tiny-connectome",
                "device": "cpu",
                "stages": ["stability", "looming"],
            },
            "desktop": {
                "data_mode": "sequence-directories",
                "model_mode": "full-male-cns",
                "device": "auto",
                "stages": ["stability"],
            },
        },
        "stages": [
            {
                "id": "stability",
                "order": 0,
                "train_seeds": [11, 12],
                "validation_seeds": [101],
                "epochs_per_batch": 2,
                "max_batches": 2,
                "maximum_validation_loss": 0.2,
                "maximum_loss_ratio": 0.8,
                "maximum_regression_ratio": 1.02,
                "train_paths": [],
                "validation_paths": [],
            },
            {
                "id": "looming",
                "order": 1,
                "train_seeds": [21],
                "validation_seeds": [201],
                "epochs_per_batch": 2,
                "max_batches": 3,
                "maximum_validation_loss": 0.1,
                "maximum_loss_ratio": 0.7,
                "maximum_regression_ratio": 1.02,
                "train_paths": [],
                "validation_paths": [],
            },
        ],
    }


def write_config(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "curriculum.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def test_config_resolves_profile_and_has_stable_digest(tmp_path):
    path = write_config(tmp_path, config_dict())
    first = load_curriculum_config(path, "smoke")
    second = load_curriculum_config(path, "smoke")
    assert [stage.id for stage in first.stages] == ["stability", "looming"]
    assert first.profile.data_mode == "synthetic-smoke"
    assert first.digest == second.digest
    assert len(first.digest) == 64


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["stages"][1].update(order=3), "continuous"),
        (
            lambda value: value["stages"][0].update(validation_seeds=[12]),
            "overlap",
        ),
        (lambda value: value["stages"][0].update(max_batches=0), "positive"),
        (lambda value: value.update(extra=True), "unknown"),
    ],
)
def test_config_rejects_invalid_contract(tmp_path, mutate, message):
    value = config_dict()
    mutate(value)
    with pytest.raises(ValueError, match=message):
        load_curriculum_config(write_config(tmp_path, value), "smoke")


def test_only_smoke_profile_can_use_synthetic_data(tmp_path):
    value = config_dict()
    value["profiles"]["desktop"]["data_mode"] = "synthetic-smoke"
    with pytest.raises(ValueError, match="synthetic-smoke is restricted"):
        load_curriculum_config(write_config(tmp_path, value), "desktop")


def test_sequence_profile_requires_paths_for_every_selected_stage(tmp_path):
    with pytest.raises(ValueError, match="sequence paths"):
        load_curriculum_config(write_config(tmp_path, config_dict()), "desktop")


def test_unknown_profile_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown profile"):
        load_curriculum_config(write_config(tmp_path, config_dict()), "missing")
