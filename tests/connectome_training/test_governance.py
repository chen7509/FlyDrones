import pytest
import torch

from flydrones.connectome_training.checkpoint import load_checkpoint, save_checkpoint
from flydrones.connectome_training.dataset import SequenceProvenance
from flydrones.connectome_training.governance import (
    CurriculumGate,
    evaluate_gate,
    validate_dataset_partitions,
)


def provenance(split, seed, world, source="generated-training-world"):
    return SequenceProvenance(split, seed, "ego@test", world, "b" * 64, source)


def test_partition_overlap_and_formal_sources_are_rejected():
    train = [provenance("train", 1, "a" * 64)]
    with pytest.raises(ValueError, match="overlap"):
        validate_dataset_partitions(train, [provenance("val", 1, "c" * 64)])
    with pytest.raises(ValueError, match="formal comparison evidence"):
        validate_dataset_partitions(
            [provenance("train", 2, "d" * 64, "formal-freeze")], []
        )


def test_curriculum_requires_every_safety_and_quality_gate():
    gate = CurriculumGate(
        episodes=10,
        minimum_success_rate=0.9,
        maximum_collision_rate=0.0,
        minimum_clearance_m=0.8,
        maximum_validation_loss=0.2,
    )
    passed, failures = evaluate_gate(
        gate,
        {
            "episodes": 10,
            "success_rate": 0.95,
            "collision_rate": 0.01,
            "minimum_clearance_m": 0.9,
            "validation_loss": 0.1,
        },
    )
    assert not passed
    assert failures == ("collision_rate",)


def test_checkpoint_is_atomic_hashed_and_rng_reproducible(tmp_path):
    out = save_checkpoint(
        tmp_path / "checkpoint",
        model_state={"w": torch.tensor([1.0])},
        optimizer_state={"step": 3},
        metadata={"epoch": 4, "seed": 9, "dataset_sha256": "a" * 64},
    )
    loaded = load_checkpoint(out)
    assert loaded["metadata"]["epoch"] == 4
    assert torch.equal(loaded["model_state"]["w"], torch.tensor([1.0]))
    assert loaded["rng_state"]["torch"].dtype == torch.uint8
    payload = out / "checkpoint.pt"
    payload.write_bytes(payload.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_checkpoint(out)
