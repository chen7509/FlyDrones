import math
from dataclasses import replace
from hashlib import sha256

import numpy as np
import pytest
import torch
from scipy import sparse
from test_learning_roles import config as _config
from test_learning_roles import inert_backends as _inert
from test_learning_roles import inference_checkpoint, rewrite_payload, save_session

from flydrones.brain.connectome import Connectome
from flydrones.connectome_training import curriculum_session as sessions
from flydrones.connectome_training.inference_artifact import CheckpointIdentity, load_inference_core
from flydrones.connectome_training.model import ConnectomeConstrainedCore
from flydrones.connectome_training.parameters import build_structure_identity, initial_parameter_set
from flydrones.connectome_training.training_roles import capture_learning_initialization, initialization_identity_suffix
from tools.connectome_training import run_curriculum as cli

config = _config
inert_backends = _inert
EXP = "frozen-drive-exponential-v1"


def scalar_core(**kwargs):
    graph = Connectome("scalar", sparse.csc_matrix((2, 2), dtype=np.float32), np.array(["x", "x"]), np.array(["", ""]))
    parameters = initial_parameter_set(build_structure_identity(graph, "a" * 64), ("feature",), ("out",), np.array([0]))
    parameters = replace(parameters, readout=np.array([[1.0]], np.float32))
    model = ConnectomeConstrainedCore(graph, parameters, **kwargs).double()
    with torch.no_grad():
        model.raw_input_gain.fill_(math.log(math.expm1(1.0)))
    return model


def test_legacy_twenty_hz_clips_timeconstant_gradient_control():
    model = scalar_core()
    command, state = model.forward_step(torch.tensor([[0.4]], dtype=torch.float64), model.initial_state(1), 0.05)
    state.voltage.square().sum().backward()
    assert model.raw_tau_m.grad.item() == 0
    assert state.voltage[0, 0].item() == pytest.approx(0.4)
    assert command.item() == pytest.approx(math.tanh(1 / (1 + math.exp(-0.4))))


@pytest.mark.parametrize("topology", ["coo_reference", "csr_compact_v1"])
def test_actual_twenty_hz_timeconstant_gradient_and_update(topology):
    model = scalar_core(dynamics_format=EXP, topology_format=topology)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    before = model.raw_tau_m.detach().clone()
    _, state = model.forward_step(torch.tensor([[0.4]], dtype=torch.float64), model.initial_state(1), 0.05)
    state.voltage.square().sum().backward()
    assert torch.isfinite(model.raw_tau_m.grad).all() and model.raw_tau_m.grad.abs().item() > 1e-5
    optimizer.step()
    assert not torch.equal(model.raw_tau_m, before)


def test_held_drive_exact_scalar_solution_and_unequal_intervals():
    model = scalar_core(dynamics_format=EXP)
    features = torch.tensor([[0.4]], dtype=torch.float64)
    state = model.initial_state(1)
    elapsed = 0
    tau = model.tau_m_ms.item()
    for dt in (0.012, 0.05, 0.003):
        _, state = model.forward_step(features, state, dt)
        elapsed += dt
        assert state.voltage[0, 0].item() == pytest.approx(0.4 * (1 - math.exp(-elapsed * 1000 / tau)), abs=1e-13)


def test_raw_timeconstant_gradient_matches_independent_derivative_at_twenty_hz():
    model = scalar_core(dynamics_format=EXP)
    _, state = model.forward_step(torch.tensor([[0.4]], dtype=torch.float64), model.initial_state(1), 0.05)
    state.voltage[0, 0].backward()
    tau = model.tau_m_ms.item()
    raw = model.raw_tau_m.item()
    expected = -0.4 * math.exp(-50 / tau) * 50 / tau**2 / (1 + math.exp(-raw))
    assert model.raw_tau_m.grad.item() == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("dt", [1e-10, 0.001, 0.05, 0.3])
def test_selected_scalar_update_preserves_numerical_decay(dt):
    model = scalar_core(dynamics_format=EXP)
    _, state = model.forward_step(torch.tensor([[0.4]], dtype=torch.float64), model.initial_state(1), dt)
    expected = -0.4 * math.expm1(-dt * 1000 / model.tau_m_ms.item())
    assert state.voltage[0, 0].item() == pytest.approx(expected, rel=1e-13, abs=1e-20)


def test_signed_sparse_layouts_match_new_twenty_hz_gradients_and_updates(tiny_artifacts):
    _, _, graph, parameters = tiny_artifacts()
    models = [
        ConnectomeConstrainedCore(graph, parameters, topology_format=layout, dynamics_format=EXP).double()
        for layout in ("coo_reference", "csr_compact_v1")
    ]
    with torch.no_grad():
        for model in models:
            model.readout.fill_(0.02)
    features = torch.arange(2 * 5 * models[0].n_features, dtype=torch.float64).reshape(2, 5, -1) / 100
    for _ in range(2):
        outputs = []
        for model in models:
            model.zero_grad(set_to_none=True)
            prediction, state = model.forward_sequence(features, 3)
            (prediction.square().sum() + state.voltage.square().sum()).backward()
            assert model.raw_tau_m.grad.abs().item() > 1e-5
            outputs.append(prediction.detach())
        torch.testing.assert_close(outputs[0], outputs[1], rtol=1e-12, atol=1e-12)
        for a, b in zip(models[0].parameters(), models[1].parameters()):
            torch.testing.assert_close(a.grad, b.grad, rtol=1e-10, atol=1e-10)
        for model in models:
            torch.optim.SGD(model.parameters(), lr=0.001).step()
        for a, b in zip(models[0].parameters(), models[1].parameters()):
            torch.testing.assert_close(a, b, rtol=1e-10, atol=1e-10)


def test_sequence_uses_actual_twenty_hz_dynamics_and_detach():
    model = scalar_core(dynamics_format=EXP)
    features = torch.tensor([[[0.4], [0.2], [0.3]]], dtype=torch.float64, requires_grad=True)
    _, state = model.forward_sequence(features, truncate_steps=2)
    state.voltage.sum().backward()
    assert features.grad[0, :2].abs().sum().item() == 0
    assert features.grad[0, 2].abs().item() > 0
    assert model.raw_tau_m.grad.abs().item() > 1e-5


@pytest.mark.parametrize("declared", [EXP, None, "invalid"])
def test_conflicting_legacy_checkpoint_mode_rejects_before_copy(config, tmp_path, declared):
    first = sessions.ConnectomeCurriculumSession(config, device="cpu")
    first.train_batch(config.stages[0], 1101)
    save_session(first, tmp_path / "checkpoint")
    rewrite_payload(tmp_path / "checkpoint", lambda p: p["metadata"].update(dynamics_format=declared))
    other = sessions.ConnectomeCurriculumSession(config, device="cpu")
    before = [p.detach().clone() for p in other.model.parameters()]
    with pytest.raises(ValueError, match="dynamics_format"):
        other.restore_checkpoint(tmp_path / "checkpoint")
    assert all(torch.equal(a, b) for a, b in zip(before, other.model.parameters()))


def test_actual_session_learns_tau_and_checkpoint_roundtrips(config, tmp_path):
    current = sessions.ConnectomeCurriculumSession(config, device="cpu", dynamics_format=EXP, topology_format="csr_compact_v1")
    legacy = sessions.ConnectomeCurriculumSession(config, device="cpu")
    explicit = sessions.ConnectomeCurriculumSession(config, device="cpu", dynamics_format="clipped-euler-v1")
    assert explicit.model_identity == legacy.model_identity
    assert current.model_identity != legacy.model_identity
    before = current.model.raw_tau_m.detach().clone()
    for seed in (1101, 1102):
        current.train_batch(config.stages[0], seed)
    assert not torch.equal(current.model.raw_tau_m, before)
    save_session(current, tmp_path / "checkpoint")
    again = sessions.ConnectomeCurriculumSession(config, device="cpu", dynamics_format=EXP, topology_format="csr_compact_v1")
    again.restore_checkpoint(tmp_path / "checkpoint")
    assert all(torch.equal(a, b) for a, b in zip(current.model.parameters(), again.model.parameters()))
    with pytest.raises(ValueError, match="metadata mismatch"):
        legacy.restore_checkpoint(tmp_path / "checkpoint")


@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_invalid_mode_rejects_before_data_or_model(config, monkeypatch, value):
    monkeypatch.setattr(sessions, "_smoke_components", lambda *a: pytest.fail("data/model reached"))
    with pytest.raises(ValueError, match="dynamics format"):
        sessions.ConnectomeCurriculumSession(config, device="cpu", dynamics_format=value)
    with pytest.raises(ValueError, match="dynamics format"):
        load_inference_core("absent", "absent", dynamics_format=value)


@pytest.mark.parametrize("operation", ["train", "evaluate", "save", "restore"])
def test_live_mode_drift_rejects_at_session_boundaries(config, tmp_path, operation):
    current = sessions.ConnectomeCurriculumSession(config, device="cpu", dynamics_format=EXP)
    save_session(current, tmp_path / "checkpoint")
    current.model.dynamics_format = "clipped-euler-v1"
    with pytest.raises(ValueError, match="dynamics format"):
        if operation == "train":
            current.train_batch(config.stages[0], 1101)
        elif operation == "evaluate":
            current.evaluate(config.stages[0])
        elif operation == "save":
            save_session(current, tmp_path / "other")
        else:
            current.restore_checkpoint(tmp_path / "checkpoint")
    assert not (tmp_path / "other").exists()


def test_offline_source_reconstruction_has_correct_dynamics_identity(tmp_path, tiny_artifacts):
    artifacts = tiny_artifacts()
    source, folder, path, _ = inference_checkpoint(tmp_path, artifacts, "shared-dynamics-v1")
    init = capture_learning_initialization(ConnectomeConstrainedCore(artifacts[2], artifacts[3], dynamics_format=EXP))

    def enrich(p):
        p["metadata"]["dynamics_format"] = EXP
        p["metadata"]["learning_initialization"] = init
        p["metadata"]["model_identity"] = p["metadata"]["model_identity"].replace(
            ":device=cpu", ":device=cpu:dynamics=" + EXP
        ) + initialization_identity_suffix(init)

    rewrite_payload(path, enrich)
    pinned = CheckpointIdentity(sha256((path / "checkpoint.pt").read_bytes()).hexdigest(), "c" * 64, "d" * 64)
    loaded = load_inference_core(
        source,
        folder,
        mode="tiny-fixture",
        checkpoint_path=path,
        checkpoint_identity=pinned,
        learning_profile="shared-dynamics-v1",
        dynamics_format=EXP,
    )
    assert loaded.core.dynamics_format == EXP and loaded.provenance["dynamics_format"] == EXP
    assert not loaded.provenance["training_success_verified"] and not loaded.provenance["flight_eligible"]
    with pytest.raises(ValueError, match="dynamics_format"):
        load_inference_core(
            source,
            folder,
            mode="tiny-fixture",
            checkpoint_path=path,
            checkpoint_identity=pinned,
            learning_profile="shared-dynamics-v1",
        )


def test_cli_routes_explicit_dynamics_without_training(monkeypatch, tmp_path):
    class BoundaryReached(Exception):
        pass

    monkeypatch.setattr("sys.argv", ["run_curriculum.py"])
    assert cli.parse_args().dynamics_format == "clipped-euler-v1"
    monkeypatch.setattr("sys.argv", ["run_curriculum.py", "--dynamics-format", EXP, "--output", str(tmp_path / "absent")])
    captured = {}

    def factory(config, **kwargs):
        captured.update(kwargs)
        raise BoundaryReached

    monkeypatch.setattr(cli, "ConnectomeCurriculumSession", factory)
    with pytest.raises(BoundaryReached):
        cli.main()
    assert captured["dynamics_format"] == EXP and not (tmp_path / "absent").exists()
    monkeypatch.setattr("sys.argv", ["run_curriculum.py", "--dynamics-format", "invalid"])
    with pytest.raises(SystemExit):
        cli.parse_args()


@pytest.mark.parametrize("mode", ["clipped-euler-v1", EXP])
@pytest.mark.parametrize("declared", [None, "invalid", "opposite"])
def test_save_rejects_foreign_owned_mode_before_creating_files(config, tmp_path, mode, declared):
    current = sessions.ConnectomeCurriculumSession(config, device="cpu", dynamics_format=mode)
    if declared == "opposite":
        declared = EXP if mode == "clipped-euler-v1" else "clipped-euler-v1"
    metadata = dict(
        stage_index=0,
        batch_index=0,
        seed=11,
        config_digest=config.digest,
        model_identity=current.model_identity,
        dynamics_format=declared,
    )
    before_paths = set(tmp_path.iterdir())
    with pytest.raises(ValueError, match="dynamics_format"):
        current.save_checkpoint(tmp_path / "checkpoint", metadata)
    assert set(tmp_path.iterdir()) == before_paths


def test_legacy_matching_mode_metadata_stays_absent_and_restorable(config, tmp_path):
    current = sessions.ConnectomeCurriculumSession(config, device="cpu")
    metadata = dict(
        stage_index=0,
        batch_index=0,
        seed=11,
        config_digest=config.digest,
        model_identity=current.model_identity,
        dynamics_format="clipped-euler-v1",
    )
    current.save_checkpoint(tmp_path / "checkpoint", metadata)
    payload = torch.load(tmp_path / "checkpoint" / "checkpoint.pt", weights_only=True)
    assert "dynamics_format" not in payload["metadata"]
    assert metadata["dynamics_format"] == "clipped-euler-v1"
    current.restore_checkpoint(tmp_path / "checkpoint")
