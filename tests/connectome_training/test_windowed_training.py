import copy
import gc
import weakref

import pytest
import torch

from flydrones.connectome_training import trainer
from flydrones.connectome_training.losses import LossWeights, sequence_loss
from flydrones.connectome_training.model import ConnectomeConstrainedCore, RecurrentState
from tools.benchmark.software_process_boundary import install


@pytest.fixture(autouse=True)
def no_children(monkeypatch):
    install(monkeypatch)


class TinyCore(torch.nn.Module):
    forward_sequence = ConnectomeConstrainedCore.forward_sequence

    def __init__(self):
        super().__init__()
        self.gain = torch.nn.Parameter(torch.tensor([0.3, -0.2, 0.4, 0.1], dtype=torch.float64))
        self.bias = torch.nn.Parameter(torch.tensor([1.5, -1.3, 0.2, 0.4], dtype=torch.float64))
        self.n_features = 4
        self.calls = []
        self.reset_count = 0

    def initial_state(self, batch_size, *, device=None, dtype=None):
        self.reset_count += 1
        return RecurrentState(torch.zeros(batch_size, 4, device=device, dtype=dtype))

    def forward_step(self, features, state, dt_s):
        self.calls.append(features.shape[0])
        hidden = torch.tanh(state.voltage * 0.65 + features * self.gain)
        return hidden + self.bias, RecurrentState(hidden)


def inputs(length=7, batch=2):
    x = torch.linspace(-0.9, 1.1, batch * length * 4, dtype=torch.float64).reshape(batch, length, 4)
    target = torch.cos(x * 2) * 0.25
    clearance = torch.linspace(0.05, 1.3, batch * length, dtype=torch.float64).reshape(batch, length)
    return x, target, clearance


WEIGHTS = LossWeights(0.7, 1.3, 0.8, 0.6, 0.85)


def reference(model, data, window, *, update=True):
    optimizer = torch.optim.SGD(model.parameters(), lr=0.04)
    optimizer.zero_grad(set_to_none=True)
    prediction, _ = model.forward_sequence(data[0], truncate_steps=window)
    total, terms = sequence_loss(prediction, data[1], data[2], WEIGHTS)
    if update:
        total.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 0.6)
        gradients = [p.grad.clone() for p in model.parameters()]
        optimizer.step()
    else:
        gradients = None
    return {"total": total.item(), **{k: v.item() for k, v in terms.items()}}, gradients


@pytest.mark.parametrize("length,window,batch", [(1, 1, 1), (7, 1, 2), (7, 2, 2), (7, 3, 1), (7, 7, 2), (7, 20, 2)])
def test_exact_original_objective_gradients_and_update(monkeypatch, length, window, batch):
    data = inputs(length, batch)
    actual = TinyCore()
    expected = copy.deepcopy(actual)
    metrics, gradients = reference(expected, data, window)
    monkeypatch.setattr(trainer, "_on_model_device", lambda model, sequence: data)
    observed = trainer.train_epoch(
        actual, [object()], torch.optim.SGD(actual.parameters(), lr=0.04), window, weights=WEIGHTS, gradient_clip_norm=0.6
    )
    assert observed == pytest.approx(metrics, rel=1e-11, abs=1e-12)
    for a, e, gradient in zip(actual.parameters(), expected.parameters(), gradients):
        torch.testing.assert_close(a, e, rtol=1e-11, atol=1e-12)
        torch.testing.assert_close(a.grad, gradient, rtol=1e-11, atol=1e-12)


@pytest.mark.parametrize("evaluate", [False, True])
def test_forward_requests_are_bounded_by_truncation(monkeypatch, evaluate):
    model = TinyCore()
    data = inputs(19)
    monkeypatch.setattr(trainer, "_on_model_device", lambda model, sequence: data)
    original = model.forward_sequence
    sizes = []

    def observe(features, truncate_steps, **kwargs):
        sizes.append(features.shape[1])
        return original(features, truncate_steps, **kwargs)

    monkeypatch.setattr(model, "forward_sequence", observe)
    if evaluate:
        expected, _ = reference(TinyCore(), data, 4, update=False)
        result = trainer.evaluate_sequences(model, [object()], 4, weights=WEIGHTS)
        assert result == pytest.approx(expected, rel=1e-11, abs=1e-12)
    else:
        trainer.train_epoch(model, [object()], torch.optim.SGD(model.parameters(), lr=0.01), 4)
    assert max(sizes) <= 4
    assert sum(sizes) == 19
    assert model.reset_count == 1


def retained_peak(monkeypatch, length):
    model = TinyCore()
    data = inputs(length)
    monkeypatch.setattr(trainer, "_on_model_device", lambda model, sequence: data)
    live = 0
    peak = 0

    class Saved:
        def __init__(self, tensor):
            nonlocal live, peak
            self.tensor = tensor
            live += 1
            peak = max(peak, live)

        def __del__(self):
            nonlocal live
            live -= 1

    with torch.autograd.graph.saved_tensors_hooks(Saved, lambda saved: saved.tensor):
        trainer.train_epoch(model, [object()], torch.optim.SGD(model.parameters(), lr=0.01), 4)
    gc.collect()
    assert live == 0
    return peak


def test_saved_activation_objects_do_not_grow_with_sequence_length(monkeypatch):
    short = retained_peak(monkeypatch, 16)
    long = retained_peak(monkeypatch, 64)
    assert long <= short + 16, (short, long)


def test_multiple_sequences_reset_and_keep_one_step_per_sequence(monkeypatch):
    data = [inputs(7, 1), inputs(5, 2)]
    model = TinyCore()
    expected = TinyCore()
    # Reference uses the same optimizer settings, one update per independent sequence.
    reference_optimizer = torch.optim.SGD(expected.parameters(), lr=0.01)
    expected_metrics = {name: 0.0 for name in ("total", "imitation", "clearance_weighted", "smoothness", "saturation")}
    for tensors in data:
        reference_optimizer.zero_grad(set_to_none=True)
        prediction, _ = expected.forward_sequence(tensors[0], 3)
        total, terms = sequence_loss(prediction, tensors[1], tensors[2], WEIGHTS)
        total.backward()
        torch.nn.utils.clip_grad_norm_(expected.parameters(), 5.0)
        reference_optimizer.step()
        for name, value in {"total": total, **terms}.items():
            expected_metrics[name] += value.item() * tensors[0].shape[1] / 12
    monkeypatch.setattr(trainer, "_on_model_device", lambda model, index: data[index])
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
    original = optimizer.step
    steps = []

    def step(*args, **kwargs):
        steps.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(optimizer, "step", step)
    result = trainer.train_epoch(model, [0, 1], optimizer, 3, weights=WEIGHTS)
    assert result == pytest.approx(expected_metrics, rel=1e-11, abs=1e-12)
    assert len(steps) == model.reset_count == 2
    for actual, reference_parameter in zip(model.parameters(), expected.parameters()):
        torch.testing.assert_close(actual, reference_parameter, rtol=1e-11, atol=1e-12)


@pytest.mark.parametrize("component", [0, 1, 2])
def test_late_invalid_value_never_steps(monkeypatch, component):
    data = inputs(7)
    data[component].reshape(-1)[-1] = float("nan")
    model = TinyCore()
    initial = [p.detach().clone() for p in model.parameters()]
    monkeypatch.setattr(trainer, "_on_model_device", lambda model, sequence: data)
    with pytest.raises(ValueError, match="non-finite"):
        trainer.train_epoch(model, [object()], torch.optim.SGD(model.parameters(), lr=0.01), 3)
    for p, original in zip(model.parameters(), initial):
        assert torch.equal(p, original)
        assert p.grad is None


def test_later_forward_failure_never_steps(monkeypatch):
    data = inputs(12)
    model = TinyCore()
    initial = [p.detach().clone() for p in model.parameters()]
    monkeypatch.setattr(trainer, "_on_model_device", lambda model, sequence: data)
    original = model.forward_step

    def fail(features, state, dt_s):
        if len(model.calls) == 9:
            raise RuntimeError("synthetic later window failure")
        return original(features, state, dt_s)

    monkeypatch.setattr(model, "forward_step", fail)
    with pytest.raises(RuntimeError, match="later window"):
        trainer.train_epoch(model, [object()], torch.optim.SGD(model.parameters(), lr=0.01), 3)
    for p, original in zip(model.parameters(), initial):
        assert torch.equal(p, original)


@pytest.mark.parametrize("window", [1, 3, 20])
def test_actual_tiny_connectome_matches_reference(monkeypatch, tiny_artifacts, window):
    _, _, connectome, parameters = tiny_artifacts()
    model = ConnectomeConstrainedCore(connectome, parameters)
    expected = copy.deepcopy(model)
    length = 7
    features = torch.linspace(-0.8, 0.9, length * model.n_features).reshape(1, length, model.n_features)
    target = torch.full((1, length, 4), 0.12)
    clearance = torch.linspace(0.05, 1.2, length).reshape(1, length)
    data = features, target, clearance
    metrics, gradients = reference(expected, data, window)
    monkeypatch.setattr(trainer, "_on_model_device", lambda model, sequence: data)
    actual = trainer.train_epoch(
        model, [object()], torch.optim.SGD(model.parameters(), lr=0.04), window, weights=WEIGHTS, gradient_clip_norm=0.6
    )
    assert actual == pytest.approx(metrics, rel=2e-6, abs=2e-7)
    for a, e, gradient in zip(model.parameters(), expected.parameters(), gradients):
        torch.testing.assert_close(a, e, rtol=2e-6, atol=2e-7)
        torch.testing.assert_close(a.grad, gradient, rtol=2e-6, atol=2e-7)


@pytest.mark.parametrize("window", [1, 3, 20])
def test_raw_gradients_match_before_clipping(monkeypatch, window):
    data = inputs(7)
    expected = TinyCore()
    prediction, _ = expected.forward_sequence(data[0], window)
    total, _ = sequence_loss(prediction, data[1], data[2], WEIGHTS)
    total.backward()
    raw = [p.grad.clone() for p in expected.parameters()]
    model = TinyCore()
    monkeypatch.setattr(trainer, "_on_model_device", lambda model, sequence: data)
    original = torch.nn.utils.clip_grad_norm_
    before_clip = []

    def clip(parameters, maximum):
        values = list(parameters)
        before_clip.append([p.grad.clone() for p in values])
        return original(values, maximum)

    monkeypatch.setattr(torch.nn.utils, "clip_grad_norm_", clip)
    trainer.train_epoch(
        model, [object()], torch.optim.SGD(model.parameters(), lr=0.04), window, weights=WEIGHTS, gradient_clip_norm=0.6
    )
    assert len(before_clip) == 1
    for actual, reference_gradient in zip(before_clip[0], raw):
        torch.testing.assert_close(actual, reference_gradient, rtol=1e-11, atol=1e-12)


def test_unused_local_loss_graph_is_released_before_advancing(monkeypatch):
    data = inputs(19)
    model = TinyCore()
    monkeypatch.setattr(trainer, "_on_model_device", lambda model, sequence: data)
    local_totals = []
    original_loss = trainer.sequence_loss
    original_forward = model.forward_sequence

    def loss(*args):
        total, terms = original_loss(*args)
        local_totals.append(weakref.ref(total))
        return total, terms

    def forward(*args, **kwargs):
        if local_totals:
            assert local_totals[-1]() is None, "old local loss graph retained during next forward"
        return original_forward(*args, **kwargs)

    monkeypatch.setattr(trainer, "sequence_loss", loss)
    monkeypatch.setattr(model, "forward_sequence", forward)
    trainer.train_epoch(model, [object()], torch.optim.SGD(model.parameters(), lr=0.04), 4)
