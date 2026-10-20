import pytest
import torch
from test_learning_roles import config as _base_config
from test_learning_roles import inert_backends as _base_inert
from test_learning_roles import inference_checkpoint, rewrite_payload, save_session, session

from flydrones.connectome_training import curriculum_session as sessions
from flydrones.connectome_training.inference_artifact import CheckpointIdentity, load_inference_core
from flydrones.connectome_training.model import ConnectomeConstrainedCore
from flydrones.connectome_training.training_roles import capture_learning_initialization, initialization_identity_suffix

config = _base_config
inert_backends = _base_inert


def test_default_test_body_boundaries_are_inert_without_recorder_plugin():
    import subprocess

    # Inspect callables only: RED must never call a real resource/CUDA/child API.
    assert subprocess.Popen._execute_child.__module__ == "tools.benchmark.software_process_boundary"
    assert sessions._peak_process_memory_bytes.__module__ == "test_learning_roles"
    assert torch.cuda.is_available.__module__ == "test_learning_roles"


@pytest.mark.parametrize("field", ["input_gain", "type_bias_mv", "tau_m_ms", "readout"])
def test_changed_active_initialization_cannot_reuse_identity_or_restore(config, tmp_path, monkeypatch, field):
    first = session(config, "shared-dynamics-v1")
    save_session(first, tmp_path / "checkpoint")
    original = sessions._smoke_components

    def changed(cfg):
        c, p, d = original(cfg)
        setattr(p, field, getattr(p, field) + 0.125)
        return c, p, d

    monkeypatch.setattr(sessions, "_smoke_components", changed)
    other = session(config, "shared-dynamics-v1")
    assert first.model_identity != other.model_identity
    before = [p.detach().clone() for p in other.model.parameters()]
    with pytest.raises(ValueError, match="metadata mismatch"):
        other.restore_checkpoint(tmp_path / "checkpoint")
    assert all(torch.equal(a, b) for a, b in zip(before, other.model.parameters()))


@pytest.mark.parametrize("drift", ["loss", "truncate", "weights"])
def test_validation_baseline_drift_refuses_checkpoint_output(config, tmp_path, drift):
    current = session(config, "shared-dynamics-v1")
    if drift == "loss":
        current.initial_losses[config.stages[0].id] *= 2
    elif drift == "truncate":
        current.truncate_steps += 1
    else:
        current.loss_weights = type(current.loss_weights)(imitation=2)
    with pytest.raises(ValueError, match="baseline"):
        save_session(current, tmp_path / "checkpoint")
    assert not (tmp_path / "checkpoint").exists()


def test_coherent_baseline_tamper_refuses_before_parameter_copy(config, tmp_path):
    first = session(config, "shared-dynamics-v1")
    first.train_batch(config.stages[0], 1101)
    save_session(first, tmp_path / "checkpoint")
    rewrite_payload(tmp_path / "checkpoint", lambda p: p["metadata"].update(validation_baseline={"fabricated": 1}))
    other = session(config, "shared-dynamics-v1")
    before = [p.detach().clone() for p in other.model.parameters()]
    with pytest.raises(ValueError, match="metadata mismatch"):
        other.restore_checkpoint(tmp_path / "checkpoint")
    assert all(torch.equal(a, b) for a, b in zip(before, other.model.parameters()))


def test_same_initialized_session_restores_without_relabeling_trained_values(config, tmp_path):
    first = session(config, "shared-dynamics-v1")
    identity = first.model_identity
    first.train_batch(config.stages[0], 1101)
    save_session(first, tmp_path / "checkpoint")
    other = session(config, "shared-dynamics-v1")
    other.restore_checkpoint(tmp_path / "checkpoint")
    assert other.model_identity == identity
    assert other.initial_losses == first.initial_losses
    assert all(torch.equal(a, b) for a, b in zip(first.model.parameters(), other.model.parameters()))


@pytest.mark.parametrize("drift", ["initialization", "loss", "truncate"])
@pytest.mark.parametrize("operation", ["evaluate", "train", "restore"])
def test_live_baseline_change_refuses_before_work(config, tmp_path, monkeypatch, drift, operation):
    current = session(config, "shared-dynamics-v1")
    save_session(current, tmp_path / "checkpoint")
    if drift == "initialization":
        current.learning_initialization["parameter_initial_sha256"]["readout"] = "0" * 64
    elif drift == "loss":
        current.initial_losses[config.stages[0].id] *= 2
    else:
        current.truncate_steps += 1
    monkeypatch.setattr(sessions, "evaluate_sequences", lambda *a, **k: pytest.fail("evaluation reached"))
    monkeypatch.setattr(sessions, "train_epoch", lambda *a, **k: pytest.fail("training reached"))
    with pytest.raises(ValueError, match="baseline"):
        if operation == "evaluate":
            current.evaluate(config.stages[0])
        elif operation == "train":
            current.train_batch(config.stages[0], 1101)
        else:
            current.restore_checkpoint(tmp_path / "checkpoint")


@pytest.mark.parametrize("tamper", [None, "hash", "remove"])
def test_initialized_offline_checkpoint_independently_joins_coefficients(tmp_path, tiny_artifacts, tamper):
    from hashlib import sha256

    artifacts = tiny_artifacts()
    source, folder, path, pinned = inference_checkpoint(tmp_path, artifacts, "shared-dynamics-v1")
    init = capture_learning_initialization(ConnectomeConstrainedCore(artifacts[2], artifacts[3]))

    def enrich(p):
        p["metadata"]["learning_initialization"] = init
        p["metadata"]["model_identity"] += initialization_identity_suffix(init)

    rewrite_payload(path, enrich)
    pinned = CheckpointIdentity(sha256((path / "checkpoint.pt").read_bytes()).hexdigest(), "c" * 64, "d" * 64)
    good = load_inference_core(
        source,
        folder,
        mode="tiny-fixture",
        checkpoint_path=path,
        checkpoint_identity=pinned,
        learning_profile="shared-dynamics-v1",
    )
    assert good.provenance["learning_initialization"] == init
    assert not good.provenance["validation_baseline_verified"]

    def alter(p):
        if tamper == "hash":
            p["metadata"]["learning_initialization"]["parameter_initial_sha256"]["readout"] = "0" * 64
        elif tamper == "remove":
            del p["metadata"]["learning_initialization"]
        else:
            p["metadata"]["learning_initialization"] = None

    rewrite_payload(path, alter)
    pinned = CheckpointIdentity(sha256((path / "checkpoint.pt").read_bytes()).hexdigest(), "c" * 64, "d" * 64)
    with pytest.raises(ValueError, match="metadata mismatch"):
        load_inference_core(
            source,
            folder,
            mode="tiny-fixture",
            checkpoint_path=path,
            checkpoint_identity=pinned,
            learning_profile="shared-dynamics-v1",
        )


def test_old_role_checkpoint_is_explicitly_without_initialization_baseline(tmp_path, tiny_artifacts):
    source, folder, path, pinned = inference_checkpoint(tmp_path, tiny_artifacts(), "shared-dynamics-v1")
    loaded = load_inference_core(
        source,
        folder,
        mode="tiny-fixture",
        checkpoint_path=path,
        checkpoint_identity=pinned,
        learning_profile="shared-dynamics-v1",
    )
    assert loaded.provenance["learning_initialization"] is None
    assert not loaded.provenance["validation_baseline_verified"]
