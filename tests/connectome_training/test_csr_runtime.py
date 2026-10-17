from hashlib import sha256

import pytest
import torch
from test_learning_roles import config as _base_config
from test_learning_roles import inert_backends as _base_inert
from test_learning_roles import inference_checkpoint, rewrite_payload, save_session

from flydrones.connectome_training import curriculum_session as sessions
from flydrones.connectome_training.inference_artifact import CheckpointIdentity, load_inference_core
from flydrones.connectome_training.model import ConnectomeConstrainedCore
from flydrones.connectome_training.training_roles import capture_learning_initialization, initialization_identity_suffix
from tools.connectome_training import run_curriculum as cli

config = _base_config
inert_backends = _base_inert


def session(config, format):
    return sessions.ConnectomeCurriculumSession(config, device="cpu", topology_format=format)


def test_production_uses_actual_compact_kernel_and_distinct_identity(config, tmp_path):
    csr = session(config, "csr_compact_v1")
    coo = session(config, "coo_reference")
    legacy = sessions.ConnectomeCurriculumSession(config, device="cpu")
    assert legacy.model_identity == coo.model_identity
    assert csr.model.fixed_topology.layout == torch.sparse_csr
    assert coo.model.fixed_topology.layout == torch.sparse_coo
    assert not hasattr(csr.model, "edge_row")
    assert csr.model_identity != coo.model_identity
    csr.train_batch(config.stages[0], 1101)
    save_session(csr, tmp_path / "checkpoint")
    again = session(config, "csr_compact_v1")
    again.restore_checkpoint(tmp_path / "checkpoint")
    assert all(torch.equal(a, b) for a, b in zip(csr.model.parameters(), again.model.parameters()))
    before = [p.detach().clone() for p in coo.model.parameters()]
    with pytest.raises(ValueError, match="metadata mismatch"):
        coo.restore_checkpoint(tmp_path / "checkpoint")
    assert all(torch.equal(a, b) for a, b in zip(before, coo.model.parameters()))


@pytest.mark.parametrize("value", ["invalid", None, []])
def test_selection_rejects_before_data_model_effects(config, monkeypatch, value):
    monkeypatch.setattr(sessions, "_smoke_components", lambda *a: pytest.fail("data/model construction reached"))
    with pytest.raises(ValueError, match="topology format"):
        session(config, value)


@pytest.mark.parametrize("declared", ["csr_compact_v1", None, "invalid"])
def test_contradictory_coo_checkpoint_label_rejects_before_copy(config, tmp_path, declared):
    first = session(config, "coo_reference")
    first.train_batch(config.stages[0], 1101)
    save_session(first, tmp_path / "checkpoint")
    rewrite_payload(tmp_path / "checkpoint", lambda p: p["metadata"].update(topology_format=declared))
    other = session(config, "coo_reference")
    before = [p.detach().clone() for p in other.model.parameters()]
    with pytest.raises(ValueError, match="topology_format"):
        other.restore_checkpoint(tmp_path / "checkpoint")
    assert all(torch.equal(a, b) for a, b in zip(before, other.model.parameters()))


@pytest.mark.parametrize("operation", ["train", "evaluate", "save", "restore"])
@pytest.mark.parametrize("drift", ["layout", "label"])
def test_actual_backend_drift_rejects_before_effects(config, tmp_path, operation, drift):
    current = session(config, "csr_compact_v1")
    save_session(current, tmp_path / "checkpoint")
    if drift == "layout":
        current.model.fixed_topology = current.model.fixed_topology.to_sparse_coo()
    else:
        current.model.topology_format = "coo_reference"
    with pytest.raises(ValueError, match="topology format"):
        if operation == "train":
            current.train_batch(config.stages[0], 1101)
        elif operation == "evaluate":
            current.evaluate(config.stages[0])
        elif operation == "save":
            save_session(current, tmp_path / "other")
        else:
            current.restore_checkpoint(tmp_path / "checkpoint")
    assert not (tmp_path / "other").exists()


def test_real_coo_csr_core_outputs_raw_gradients_and_updates_match(tiny_artifacts):
    _, _, connectome, parameters = tiny_artifacts()
    a = ConnectomeConstrainedCore(connectome, parameters).double()
    b = ConnectomeConstrainedCore(connectome, parameters, topology_format="csr_compact_v1").double()
    features = torch.arange(2 * 5 * a.n_features, dtype=torch.float64).reshape(2, 5, -1) / 100
    for _ in range(2):
        outputs = []
        for model in (a, b):
            model.zero_grad(set_to_none=True)
            prediction, state = model.forward_sequence(features, 3, dt_s=0.001)
            loss = prediction.square().sum() + state.voltage.square().sum()
            loss.backward()
            outputs.append(prediction.detach())
        torch.testing.assert_close(outputs[0], outputs[1], rtol=1e-12, atol=1e-12)
        for x, y in zip(a.parameters(), b.parameters()):
            torch.testing.assert_close(x.grad, y.grad, rtol=1e-10, atol=1e-10)
        for model in (a, b):
            torch.optim.SGD(model.parameters(), lr=0.001).step()
        for x, y in zip(a.parameters(), b.parameters()):
            torch.testing.assert_close(x, y, rtol=1e-10, atol=1e-10)


def test_offline_loader_reconstructs_selected_csr_and_keeps_unqualified(tmp_path, tiny_artifacts):
    artifacts = tiny_artifacts()
    source, folder, path, _ = inference_checkpoint(tmp_path, artifacts, "shared-dynamics-v1")
    init = capture_learning_initialization(
        ConnectomeConstrainedCore(artifacts[2], artifacts[3], topology_format="csr_compact_v1")
    )

    def enrich(p):
        p["metadata"]["topology_format"] = "csr_compact_v1"
        p["metadata"]["learning_initialization"] = init
        p["metadata"]["model_identity"] = p["metadata"]["model_identity"].replace(
            ":device=cpu", ":device=cpu:topology=csr_compact_v1"
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
        topology_format="csr_compact_v1",
    )
    assert loaded.core.fixed_topology.layout == torch.sparse_csr
    assert loaded.provenance["topology_format"] == "csr_compact_v1"
    assert not loaded.provenance["flight_eligible"] and not loaded.provenance["training_success_verified"]
    with pytest.raises(ValueError, match="topology_format"):
        load_inference_core(
            source,
            folder,
            mode="tiny-fixture",
            checkpoint_path=path,
            checkpoint_identity=pinned,
            learning_profile="shared-dynamics-v1",
        )


def test_cli_has_explicit_backend_choice_without_running_training(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_curriculum.py", "--topology-format", "csr_compact_v1"])
    assert cli.parse_args().topology_format == "csr_compact_v1"
    monkeypatch.setattr("sys.argv", ["run_curriculum.py", "--topology-format", "other"])
    with pytest.raises(SystemExit):
        cli.parse_args()


def test_cli_main_routes_selected_backend_in_process(monkeypatch, tmp_path):
    class BoundaryReached(Exception):
        pass

    monkeypatch.setattr(
        "sys.argv", ["run_curriculum.py", "--topology-format", "csr_compact_v1", "--output", str(tmp_path / "not-created")]
    )
    captured = {}

    def factory(config, **kwargs):
        captured.update(kwargs)
        raise BoundaryReached

    monkeypatch.setattr(cli, "ConnectomeCurriculumSession", factory)
    with pytest.raises(BoundaryReached):
        cli.main()
    assert captured["topology_format"] == "csr_compact_v1"
    assert not (tmp_path / "not-created").exists()
