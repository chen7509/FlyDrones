import copy
import weakref

import pytest
import torch
from test_inference_artifact import checkpoint
from test_learning_roles import inert_backends as _inert

from flydrones.connectome_training import inference_artifact as artifacts
from flydrones.connectome_training import model as models
from flydrones.connectome_training.inference_artifact import load_inference_core
from flydrones.connectome_training.model import ConnectomeConstrainedCore

inert_backends = _inert


def test_actual_loaded_core_reuses_frozen_coefficients(tiny_artifacts, monkeypatch):
    counters = {"gain": 0, "tau": 0}
    original_gain = ConnectomeConstrainedCore.input_gain
    original_tau = ConnectomeConstrainedCore.tau_m_ms

    def gain(core):
        counters["gain"] += 1
        return original_gain.fget(core)

    def tau(core):
        counters["tau"] += 1
        return original_tau.fget(core)

    monkeypatch.setattr(ConnectomeConstrainedCore, "input_gain", property(gain))
    monkeypatch.setattr(ConnectomeConstrainedCore, "tau_m_ms", property(tau))
    source, folder, _, _ = tiny_artifacts()
    loaded = load_inference_core(source, folder, mode="tiny-fixture")
    counters.update(gain=0, tau=0)
    features = torch.linspace(-0.3, 0.5, loaded.core.n_features).repeat(2, 1)
    state = loaded.core.initial_state(2)
    for _ in range(4):
        _, state = loaded.core.forward_step(features, state, 0.05)
    assert counters == {"gain": 0, "tau": 0}
    assert loaded.provenance["frozen_coefficients_prepared"] is True
    assert not loaded.provenance["training_success_verified"]
    assert not loaded.provenance["flight_eligible"]


@pytest.mark.parametrize("topology", ["coo_reference", "csr_compact_v1"])
@pytest.mark.parametrize("dynamics", ["clipped-euler-v1", "frozen-drive-exponential-v1"])
@pytest.mark.parametrize("dtype", [torch.float32, torch.float64])
def test_cached_actual_recurrent_states_outputs_and_serialization_match_reference(tiny_artifacts, topology, dynamics, dtype):
    source, folder, connectome, parameters = tiny_artifacts()
    loaded = load_inference_core(source, folder, mode="tiny-fixture", topology_format=topology, dynamics_format=dynamics)
    actual = loaded.core.to(dtype=dtype)
    reference = (
        ConnectomeConstrainedCore(connectome, parameters, topology_format=topology, dynamics_format=dynamics)
        .to(dtype=dtype)
        .eval()
        .requires_grad_(False)
    )
    assert set(actual.state_dict()) == set(reference.state_dict())
    before = {n: p.detach().clone() for n, p in actual.named_parameters()}
    a, b = actual.initial_state(2), reference.initial_state(2)
    for i, dt in enumerate([0.05, 0.05, 0.003, 0.017, 0.05, 0.05]):
        features = torch.linspace(-0.7, 0.8, 2 * actual.n_features, dtype=dtype).reshape(2, -1) + i / 100
        ac, a = actual.forward_step(features, a, dt)
        bc, b = reference.forward_step(features, b, dt)
        assert torch.equal(ac, bc) and torch.equal(a.voltage, b.voltage)
    for n, p in actual.named_parameters():
        assert torch.equal(before[n], p)
    assert set(actual.state_dict()) == set(reference.state_dict())


@pytest.mark.parametrize("mutation", ["gain", "bias", "tau", "replacement", "input-index", "type-index", "dynamics"])
def test_ordinary_mutations_rebuild_derived_values(tiny_artifacts, mutation):
    source, folder, _, _ = tiny_artifacts()
    core = load_inference_core(source, folder, mode="tiny-fixture", dynamics_format="frozen-drive-exponential-v1").core
    # Add a second actual bias type for the index mutation protocol. The ordinary
    # core is mutable Python, not a hostile/source-authenticated boundary.
    with torch.no_grad():
        if mutation == "gain":
            core.raw_input_gain.add_(0.9)
        elif mutation == "bias":
            core.type_bias_mv.add_(0.7)
        elif mutation == "tau":
            core.raw_tau_m.add_(70.0)
        elif mutation == "replacement":
            core.raw_input_gain = torch.nn.Parameter(core.raw_input_gain + 0.8, requires_grad=False)
        elif mutation == "input-index":
            core.raw_input_gain.copy_(torch.linspace(0.1, 1.3, core.n_features))
            core.input_feature_index.copy_(core.input_feature_index.flip(0))
        elif mutation == "type-index":
            core.type_bias_mv = torch.nn.Parameter(torch.tensor([0.1, 0.6]), requires_grad=False)
            core.type_index[::2] = 1
        else:
            core.dynamics_format = "clipped-euler-v1"
    reference = copy.deepcopy(core)
    reference.clear_frozen_inference()
    features = torch.linspace(-0.4, 0.8, core.n_features).reshape(1, -1)
    for dt in [0.05, 0.002, 0.05]:
        a, sa = core.forward_step(features, core.initial_state(1), dt)
        b, sb = reference.forward_step(features, reference.initial_state(1), dt)
        assert torch.equal(a, b) and torch.equal(sa.voltage, sb.voltage)


@pytest.mark.parametrize("transition", ["train", "grad"])
def test_gradient_transition_uses_actual_differentiable_path(tiny_artifacts, transition):
    source, folder, _, _ = tiny_artifacts()
    actual = load_inference_core(source, folder, mode="tiny-fixture", dynamics_format="frozen-drive-exponential-v1").core
    reference = copy.deepcopy(actual)
    reference.clear_frozen_inference()
    actual.requires_grad_(True)
    reference.requires_grad_(True)
    if transition == "train":
        actual.train()
        reference.train()
    optimizers = [torch.optim.SGD(c.parameters(), lr=0.01) for c in (actual, reference)]
    for core, optimizer in zip((actual, reference), optimizers):
        x = torch.linspace(-0.5, 0.7, core.n_features).reshape(1, -1)
        command, state = core.forward_step(x, core.initial_state(1), 0.05)
        (command.square().sum() + state.voltage.square().mean()).backward()
        optimizer.step()
    for a, b in zip(actual.parameters(), reference.parameters()):
        assert a.grad is not None and torch.equal(a.grad, b.grad) and torch.equal(a, b)
    assert actual.frozen_inference_prepared is False


def test_inference_tensor_without_versions_falls_back_to_original_math(tiny_artifacts):
    source, folder, _, _ = tiny_artifacts()
    with torch.inference_mode():
        loaded = load_inference_core(source, folder, mode="tiny-fixture")
        assert loaded.provenance["frozen_coefficients_prepared"] is False
        features = torch.zeros(1, loaded.core.n_features)
        result, state = loaded.core.forward_step(features, loaded.core.initial_state(1), 0.05)
        assert torch.isfinite(result).all() and torch.isfinite(state.voltage).all()


def test_preparation_does_not_freeze_a_trainable_model(tiny_artifacts):
    _, _, connectome, parameters = tiny_artifacts()
    core = ConnectomeConstrainedCore(connectome, parameters)
    with pytest.raises(ValueError, match="frozen.*eval"):
        core.prepare_frozen_inference()
    assert core.training and all(p.requires_grad for p in core.parameters())


@pytest.mark.parametrize("case", ["features", "state", "dt", "dynamics"])
def test_cached_invalid_inputs_preserve_existing_rejection(tiny_artifacts, case):
    source, folder, _, _ = tiny_artifacts()
    core = load_inference_core(source, folder, mode="tiny-fixture").core
    features, state, dt = torch.zeros(1, core.n_features), core.initial_state(1), 0.05
    if case == "features":
        features[0, 0] = float("nan")
    elif case == "state":
        state = core.initial_state(2)
    elif case == "dt":
        dt = 0.0
    else:
        core.dynamics_format = "invalid"
    with pytest.raises(ValueError):
        core.forward_step(features, state, dt)


def test_mutable_scalar_interval_cannot_reuse_stale_alpha(tiny_artifacts):
    source, folder, _, _ = tiny_artifacts()
    core = load_inference_core(source, folder, mode="tiny-fixture", dynamics_format="frozen-drive-exponential-v1").core
    reference = copy.deepcopy(core)
    reference.clear_frozen_inference()
    features = torch.ones(1, core.n_features)
    dt = torch.tensor(0.003)
    core.forward_step(features, core.initial_state(1), dt)
    dt.fill_(0.05)
    a, sa = core.forward_step(features, core.initial_state(1), dt)
    b, sb = reference.forward_step(features, reference.initial_state(1), dt)
    assert torch.equal(a, b) and torch.equal(sa.voltage, sb.voltage)


def test_input_gradient_after_inference_mode_keeps_original_backward(tiny_artifacts):
    source, folder, _, _ = tiny_artifacts()
    core = load_inference_core(source, folder, mode="tiny-fixture", dynamics_format="frozen-drive-exponential-v1").core
    reference = copy.deepcopy(core)
    reference.clear_frozen_inference()
    with torch.inference_mode():
        core.forward_step(torch.ones(1, core.n_features), core.initial_state(1), 0.05)
    gradients = []
    for current in (core, reference):
        x = torch.ones(1, current.n_features, requires_grad=True)
        command, state = current.forward_step(x, current.initial_state(1), 0.05)
        (command.sum() + state.voltage.sum()).backward()
        gradients.append(x.grad)
    assert torch.equal(*gradients)


def test_actual_checkpoint_copy_precedes_derived_preparation(tiny_artifacts, tmp_path):
    source, folder, connectome, parameters = tiny_artifacts()
    path, identity, values = checkpoint(tmp_path, connectome, parameters)
    loaded = load_inference_core(source, folder, mode="tiny-fixture", checkpoint_path=path, checkpoint_identity=identity)
    assert loaded.provenance["frozen_coefficients_prepared"]
    reference = ConnectomeConstrainedCore(connectome, parameters).eval().requires_grad_(False)
    with torch.no_grad():
        for name, p in reference.named_parameters():
            p.copy_(values[name])
    x = torch.ones(1, reference.n_features)
    a, sa = loaded.core.forward_step(x, loaded.core.initial_state(1), 0.05)
    b, sb = reference.forward_step(x, reference.initial_state(1), 0.05)
    assert torch.equal(a, b) and torch.equal(sa.voltage, sb.voltage)
    assert loaded.provenance["learning_profile"] == "legacy-unspecified"
    assert not loaded.provenance["validation_baseline_verified"]


def test_loader_rejects_actual_final_file_drift_before_preparation(tiny_artifacts, monkeypatch):
    source, folder, _, _ = tiny_artifacts()
    actual = artifacts.ConnectomeConstrainedCore

    def construct(*args, **kwargs):
        core = actual(*args, **kwargs)
        p = folder / "manifest.json"
        p.write_bytes(p.read_bytes() + b"\n")
        return core

    monkeypatch.setattr(artifacts, "ConnectomeConstrainedCore", construct)
    monkeypatch.setattr(actual, "prepare_frozen_inference", lambda *a: pytest.fail("preparation before final byte gate"))
    with pytest.raises(ValueError, match="changed while loading"):
        artifacts.load_inference_core(source, folder, mode="tiny-fixture")


def test_recycled_id_protocol_cannot_hide_actual_parameter_replacement(tiny_artifacts, monkeypatch):
    # Deterministic metadata protocol for the ABA case; this does not claim to
    # have observed a particular CPython allocator recycle an actual address.
    monkeypatch.setattr(models, "id", lambda value: 42, raising=False)
    source, folder, _, _ = tiny_artifacts()
    core = load_inference_core(source, folder, mode="tiny-fixture", dynamics_format="frozen-drive-exponential-v1").core
    old = weakref.ref(core.raw_input_gain)
    core.raw_input_gain = torch.nn.Parameter(torch.full_like(core.raw_input_gain, 2.0), requires_grad=False)
    assert old() is None  # Cache must not extend replaced-parameter ownership.
    reference = copy.deepcopy(core)
    reference.clear_frozen_inference()
    x = torch.ones(1, core.n_features)
    a, sa = core.forward_step(x, core.initial_state(1), 0.05)
    b, sb = reference.forward_step(x, reference.initial_state(1), 0.05)
    assert torch.equal(a, b) and torch.equal(sa.voltage, sb.voltage)


def test_whole_module_pickle_drops_ephemeral_cache(tiny_artifacts, tmp_path):
    source, folder, _, _ = tiny_artifacts()
    core = load_inference_core(source, folder, mode="tiny-fixture").core
    path = tmp_path / "owned-core.pt"
    torch.save(core, path)
    restored = torch.load(path, weights_only=False)  # This test just created the entire owned payload.
    assert restored.frozen_inference_prepared is False
    assert core.frozen_inference_prepared is True  # Serialization must not mutate the live model.
    features = torch.ones(1, core.n_features)
    a, sa = core.forward_step(features, core.initial_state(1), 0.05)
    b, sb = restored.forward_step(features, restored.initial_state(1), 0.05)
    assert torch.equal(a, b) and torch.equal(sa.voltage, sb.voltage)
