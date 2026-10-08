import json
from hashlib import sha256

import numpy as np
import pytest
import torch

from flydrones.connectome_training.checkpoint import save_checkpoint
from flydrones.connectome_training.dataset import SequenceFrame, SequenceProvenance, TeacherTarget, TrainingSequence
from flydrones.connectome_training.features import FEATURE_NAMES, frame_features, sequence_tensors
from flydrones.connectome_training.inference_artifact import CheckpointIdentity, load_inference_core
from flydrones.connectome_training.model import ConnectomeConstrainedCore
from flydrones.connectome_training.parameters import parameter_mapping_digest


def checkpoint(tmp_path, connectome, parameters, *, mutate=None, metadata_change=None):
    model = ConnectomeConstrainedCore(connectome, parameters)
    tensors = {name: value.detach().clone() for name, value in model.named_parameters()}
    tensors["readout"] *= 2
    if mutate:
        mutate(tensors)
    mapping = parameter_mapping_digest(parameters)
    identity = parameters.identity
    metadata = {
        "epoch": 1, "seed": 3, "config_digest": "c" * 64,
        "dataset_sha256": "d" * 64,
        "topology_sha256": identity.topology_sha256,
        "parameter_mapping_sha256": mapping,
        "model_identity": f"tiny-connectome:{identity.model_sha256}:{identity.topology_sha256}:{mapping}:device=cpu",
    }
    metadata.update(metadata_change or {})
    path = save_checkpoint(tmp_path / "checkpoint", model_state=tensors, optimizer_state={}, metadata=metadata)
    pinned = CheckpointIdentity(sha256((path / "checkpoint.pt").read_bytes()).hexdigest(), "c" * 64, "d" * 64)
    return path, pinned, tensors


def test_frame_features_are_shared_without_teacher_inputs():
    frame = SequenceFrame(50_000_000, 50_000_000, np.full((2, 3, 3), 255, np.uint8),
                          np.array([[1., 2., 4.], [1., 2., 4.]], np.float32),
                          np.zeros(3), np.zeros(3), 0., 0., np.array([10., 0., 0.]))
    expected = [1., .5, .25, 1., 0., 0., 0., 0., 1., 0., 0., .5]
    assert frame_features(frame) == pytest.approx(expected)
    sequence = TrainingSequence(SequenceProvenance("train", 1, "fixture", "a" * 64, "b" * 64, "synthetic"),
                                [frame], [TeacherTarget(np.ones(3), .3, np.zeros((1, 3)), .5, False)])
    assert sequence_tensors(sequence)[0][0, 0].numpy() == pytest.approx(expected)


def test_initialization_load_has_frozen_gradients_and_no_training_claim(tiny_artifacts):
    source, folder, _, _ = tiny_artifacts()
    loaded = load_inference_core(source, folder, mode="tiny-fixture")
    assert not loaded.core.training
    assert all(not value.requires_grad for value in loaded.core.parameters())
    assert loaded.provenance["parameter_origin"] == "initialization-only"
    assert loaded.provenance["full_topology"] is False
    assert loaded.provenance["training_success_verified"] is False
    assert loaded.provenance["files_stable"] is True


def test_tiny_cannot_be_loaded_as_full(tiny_artifacts):
    source, folder, _, _ = tiny_artifacts()
    with pytest.raises(ValueError, match="full"):
        load_inference_core(source, folder)


def test_source_hash_mismatch_refuses(tiny_artifacts):
    source, folder, _, _ = tiny_artifacts()
    source.write_bytes(source.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="source"):
        load_inference_core(source, folder, mode="tiny-fixture")


def test_feature_order_mismatch_refuses(tiny_artifacts):
    source, folder, _, _ = tiny_artifacts(feature_names=tuple(reversed(FEATURE_NAMES)))
    with pytest.raises(ValueError, match="feature"):
        load_inference_core(source, folder, mode="tiny-fixture")


def test_claimed_topology_mismatch_refuses(tiny_artifacts):
    source, folder, _, _ = tiny_artifacts()
    path = folder / "manifest.json"
    data = json.loads(path.read_text())
    data["identity"]["topology_sha256"] = "e" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="topology"):
        load_inference_core(source, folder, mode="tiny-fixture")


def test_checkpoint_loads_only_learned_parameters_and_preserves_rng(tiny_artifacts, tmp_path):
    source, folder, connectome, parameters = tiny_artifacts()
    path, pinned, tensors = checkpoint(tmp_path, connectome, parameters)
    rng = torch.get_rng_state().clone()
    loaded = load_inference_core(source, folder, mode="tiny-fixture", checkpoint_path=path, checkpoint_identity=pinned)
    assert torch.equal(torch.get_rng_state(), rng)
    assert torch.equal(loaded.core.readout, tensors["readout"])
    assert loaded.core.fixed_topology.to_dense().numpy()[0, 1] == pytest.approx(.5)
    assert loaded.core.fixed_topology.to_dense().numpy()[1, 0] == pytest.approx(-1.)
    assert loaded.provenance["parameter_origin"] == "checkpoint-parameters"
    assert loaded.provenance["checkpoint_sha256"] == pinned.checkpoint_sha256
    assert loaded.provenance["training_success_verified"] is False


@pytest.mark.parametrize("change", [
    {"config_digest": "e" * 64}, {"dataset_sha256": "e" * 64},
    {"topology_sha256": "e" * 64}, {"parameter_mapping_sha256": "e" * 64},
    {"model_identity": "other"},
])
def test_checkpoint_metadata_mismatch_refuses(change, tiny_artifacts, tmp_path):
    source, folder, connectome, parameters = tiny_artifacts()
    path, pinned, _ = checkpoint(tmp_path, connectome, parameters, metadata_change=change)
    with pytest.raises(ValueError, match="metadata mismatch"):
        load_inference_core(source, folder, mode="tiny-fixture", checkpoint_path=path, checkpoint_identity=pinned)


@pytest.mark.parametrize("mutation", [
    lambda state: state.update(fixed_topology=torch.ones(16, 16)),
    lambda state: state.pop("raw_tau_m"),
    lambda state: state.update(readout=torch.ones(1, 4)),
    lambda state: state.update(readout=state["readout"].double()),
    lambda state: state.update(readout=torch.full_like(state["readout"], float("nan"))),
    lambda state: state.update(readout=state["readout"].to_sparse()),
])
def test_checkpoint_invalid_tensors_refuse(mutation, tiny_artifacts, tmp_path):
    source, folder, connectome, parameters = tiny_artifacts()
    path, pinned, _ = checkpoint(tmp_path, connectome, parameters, mutate=mutation)
    with pytest.raises(ValueError, match="parameter"):
        load_inference_core(source, folder, mode="tiny-fixture", checkpoint_path=path, checkpoint_identity=pinned)


def test_checkpoint_file_digest_and_explicit_pair_are_required(tiny_artifacts, tmp_path):
    source, folder, connectome, parameters = tiny_artifacts()
    path, pinned, _ = checkpoint(tmp_path, connectome, parameters)
    with pytest.raises(ValueError, match="together"):
        load_inference_core(source, folder, mode="tiny-fixture", checkpoint_path=path)
    with pytest.raises(ValueError, match="checkpoint hash"):
        load_inference_core(source, folder, mode="tiny-fixture", checkpoint_path=path,
                            checkpoint_identity=CheckpointIdentity("f" * 64, "c" * 64, "d" * 64))


def test_input_file_drift_during_loading_refuses(tiny_artifacts, monkeypatch):
    source, folder, _, _ = tiny_artifacts()
    from flydrones.connectome_training import inference_artifact as module
    real = module.ConnectomeConstrainedCore
    def changing_loader(*args):
        model = real(*args)
        source.write_bytes(source.read_bytes() + b"changed while loading")
        return model
    monkeypatch.setattr(module, "ConnectomeConstrainedCore", changing_loader)
    with pytest.raises(ValueError, match="changed"):
        load_inference_core(source, folder, mode="tiny-fixture")
