# Connectome-Constrained Training Stage B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible, truth-isolated, differentiable training path that preserves the MaleCNS topology and neurotransmitter signs while training only input gains, cell-type biases, one global membrane time constant, and a descending-neuron readout.

**Architecture:** New modules under `flydrones.connectome_training` consume the Stage A sequence contract without modifying the frozen `Brain`, `LIFNetwork`, benchmark, or formal evidence. A PyTorch surrogate recurrent core stores signed topology as non-trainable sparse buffers, shares dynamics by cell type, carries state across frames, and truncates gradients at configured boundaries. Stage B proves deterministic loss reduction on a small offline sequence and emits a separately labelled full-MaleCNS initialization artifact; PX4/Gazebo closed-loop work remains a later Stage B plan after this offline gate.

**Tech Stack:** Python 3.12, NumPy, SciPy sparse matrices, PyTorch 2.14 CPU, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-connectome-constrained-realtime-training-design.md`

## Global Constraints

- Do not modify any path covered by `results/fly-ego-comparison/freeze/manifest.json`.
- Keep all 166,700 neurons, 25,582,837 connections, topology, and neurotransmitter signs for artifacts labelled `full-male-cns`.
- Only input gains, cell-type biases, one global time constant, and descending-neuron readout are trainable in this stage.
- Student inputs contain only Stage A deployment-visible observation fields; teacher clearance and trajectory remain loss labels.
- Training, validation, and future frozen evaluation seeds and world hashes must be disjoint.
- A fruit-fly-derived student is not produced or claimed in Stage B.
- The approved infrastructure exception is limited to the sealed `test_four_independent_udp_processes_converge` start-file race; it does not waive any connectome-training failure.
- PyTorch is declared in a new `requirements-connectome-training.txt`; the frozen `pyproject.toml` remains unchanged.

## Review Focus

- Sparse topology buffers accidentally becoming trainable or changing sign: Task 2 tests exact indices, signs, and `requires_grad` flags.
- State leakage across sequences or state loss inside a sequence: Task 2 tests both reset isolation and consecutive-frame memory.
- Deployment-input leakage through clearance or teacher horizon: Task 3 tests feature extraction invariance when labels change.
- Curriculum promotion with overlapping seeds/worlds or insufficient safety metrics: Task 4 tests both rejection paths.
- An artifact claiming the full model with incorrect counts or hashes: Tasks 1 and 5 test identity validation against the full MaleCNS NPZ.

---

### Task 1: Versioned parameter and structure artifacts

**Files:**
- Create: `requirements-connectome-training.txt`
- Create: `src/flydrones/connectome_training/parameters.py`
- Modify: `src/flydrones/connectome_training/__init__.py`
- Test: `tests/connectome_training/test_parameters.py`

**Interfaces:**
- Consumes: a `Connectome`, source-model SHA-256, ordered input feature names, ordered output names.
- Produces: `StructureIdentity`, `ParameterSet`, `build_structure_identity`, `initial_parameter_set`, `save_parameter_set`, and `load_parameter_set`.

- [ ] **Step 1: Write failing artifact tests**

```python
from dataclasses import replace
import json

import numpy as np
import pytest
from scipy import sparse

from flydrones.brain.connectome import Connectome
from flydrones.connectome_training.parameters import (
    build_structure_identity,
    initial_parameter_set,
    load_parameter_set,
    save_parameter_set,
)


def tiny_connectome():
    weights = sparse.csc_matrix(np.array([[0, 2, 0], [-3, 0, 1], [0, 0, 0]], np.float32))
    return Connectome("tiny", weights, np.array(["A", "B", "A"]), np.array(["L", "R", "L"]))


def test_identity_hashes_exact_signed_topology_and_type_order():
    identity = build_structure_identity(tiny_connectome(), "a" * 64)
    assert identity.neurons == 3
    assert identity.connections == 3
    assert identity.cell_types == ("A", "B")
    assert len(identity.topology_sha256) == 64
    changed = tiny_connectome()
    changed.weights.data[0] *= -1
    assert build_structure_identity(changed, "a" * 64).topology_sha256 != identity.topology_sha256


def test_parameter_round_trip_is_hashed_and_tamper_evident(tmp_path):
    identity = build_structure_identity(tiny_connectome(), "a" * 64)
    params = initial_parameter_set(identity, ("depth_left", "goal_x"), ("vx", "yaw_rate"), output_neurons=2)
    out = save_parameter_set(tmp_path / "params", params)
    loaded = load_parameter_set(out)
    assert loaded.identity == identity
    assert np.array_equal(loaded.type_bias_mv, params.type_bias_mv)
    arrays = out / "parameters.npz"
    arrays.write_bytes(arrays.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_parameter_set(out)


def test_full_identity_cannot_be_claimed_with_wrong_counts():
    identity = build_structure_identity(tiny_connectome(), "a" * 64)
    with pytest.raises(ValueError, match="full-male-cns requires"):
        initial_parameter_set(identity, ("depth",), ("vx",), 1, label="full-male-cns")
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_parameters.py -q`

Expected: collection fails with `No module named 'flydrones.connectome_training.parameters'`.

- [ ] **Step 3: Implement deterministic identity and atomic artifacts**

Implement frozen dataclasses with these exact fields:

```python
@dataclass(frozen=True)
class StructureIdentity:
    label: str
    model_sha256: str
    topology_sha256: str
    neurons: int
    connections: int
    cell_types: tuple[str, ...]


@dataclass
class ParameterSet:
    identity: StructureIdentity
    input_features: tuple[str, ...]
    outputs: tuple[str, ...]
    input_gain: np.ndarray
    type_bias_mv: np.ndarray
    tau_m_ms: float
    readout: np.ndarray
```

`build_structure_identity` hashes CSC `indptr`, `indices`, signed float32 `data`, shape, and length-prefixed ordered neuron type strings. Cell types use sorted unique non-empty strings, with `"__unknown__"` for empty labels. `initial_parameter_set` initializes gains to one, biases and readout to zero, tau to 20 ms, and refuses `label="full-male-cns"` unless counts equal 166700 and 25582837. `save_parameter_set` writes `parameters.npz` plus schema `flydrones-connectome-parameters-v1`, array hash, and dataclass metadata through a `.writing` directory rename. `load_parameter_set` checks schema, hash, exact NPZ allowlist, array shapes, finite values, positive tau, and full-model counts.

Add `torch>=2.2,<3` to `requirements-connectome-training.txt`. Export all six public names from `connectome_training.__init__`.

- [ ] **Step 4: Run artifact tests**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_parameters.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

Run: `git add requirements-connectome-training.txt src/flydrones/connectome_training tests/connectome_training/test_parameters.py && git commit -m "feat: add connectome training parameter artifacts"`

Expected: one commit containing only the artifact contract, dependency file, exports, and tests.

### Task 2: Differentiable topology-constrained recurrent core

**Files:**
- Create: `src/flydrones/connectome_training/model.py`
- Modify: `src/flydrones/connectome_training/__init__.py`
- Test: `tests/connectome_training/test_model.py`

**Interfaces:**
- Consumes: SciPy signed sparse weights, per-neuron type labels, fixed feature-to-neuron assignment, fixed descending output indices, and `ParameterSet`.
- Produces: `ConnectomeConstrainedCore`, `RecurrentState`, `forward_step(features, state, dt_s)`, and `forward_sequence(features, truncate_steps)`.

- [ ] **Step 1: Write failing topology, state, and gradient tests**

```python
import numpy as np
import pytest
from scipy import sparse
import torch

from flydrones.brain.connectome import Connectome
from flydrones.connectome_training.model import ConnectomeConstrainedCore
from flydrones.connectome_training.parameters import build_structure_identity, initial_parameter_set


def fixture_model():
    weights = sparse.csc_matrix(np.array([[0, 2, 0], [-3, 0, 1], [0, 0, 0]], np.float32))
    connectome = Connectome("tiny", weights, np.array(["A", "B", "A"]), np.array(["L", "R", "L"]))
    identity = build_structure_identity(connectome, "a" * 64)
    params = initial_parameter_set(identity, ("depth", "goal_x"), ("vx", "yaw_rate"), 2)
    model = ConnectomeConstrainedCore(connectome, params, np.array([0, 1]), np.array([1, 2]))
    return weights, model


def test_only_declared_shared_parameters_are_trainable():
    weights, model = fixture_model()
    assert set(dict(model.named_parameters())) == {"raw_input_gain", "type_bias_mv", "raw_tau_m", "readout"}
    assert np.array_equal(model.edge_sign.cpu().numpy(), np.sign(weights.data))
    assert not model.edge_sign.requires_grad
    assert not model.edge_magnitude.requires_grad


def test_state_is_carried_within_sequence_and_reset_between_sequences():
    _, model = fixture_model()
    x = torch.tensor([[1.0, 0.5]])
    first, state1 = model.forward_step(x, model.initial_state(1), 0.05)
    second, _ = model.forward_step(x, state1, 0.05)
    reset, _ = model.forward_step(x, model.initial_state(1), 0.05)
    assert not torch.allclose(second, reset)
    assert torch.allclose(first, reset)


def test_truncated_sequence_backprop_reaches_only_allowed_parameters():
    _, model = fixture_model()
    prediction, _ = model.forward_sequence(torch.ones(1, 5, 2), truncate_steps=2)
    prediction.square().sum().backward()
    assert all(parameter.grad is not None for parameter in model.parameters())


def test_non_finite_features_are_rejected():
    _, model = fixture_model()
    with pytest.raises(ValueError, match="features contain non-finite"):
        model.forward_sequence(torch.tensor([[[float("nan"), 0.0]]]), truncate_steps=1)
```

- [ ] **Step 2: Run and verify the missing model module**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_model.py -q`

Expected: collection fails with `No module named 'flydrones.connectome_training.model'`.

- [ ] **Step 3: Implement the recurrent surrogate**

Use `torch.nn.Module`. Register COO row, column, absolute magnitude, and sign as buffers built from `connectome.weights.tocoo()` in deterministic row-major order. Register type indices, input-neuron indices, and output-neuron indices as buffers. Reject shape mismatches, duplicate input assignments, out-of-range indices, non-finite weights, or parameter identity mismatches.

Trainable tensors are exactly:

```python
self.raw_input_gain = nn.Parameter(inverse_softplus(parameter_set.input_gain))
self.type_bias_mv = nn.Parameter(torch.tensor(parameter_set.type_bias_mv, dtype=torch.float32))
self.raw_tau_m = nn.Parameter(inverse_softplus(torch.tensor(parameter_set.tau_m_ms - 1.0)))
self.readout = nn.Parameter(torch.tensor(parameter_set.readout, dtype=torch.float32))
```

`input_gain = softplus(raw_input_gain)`, `tau_m_ms = 1 + softplus(raw_tau_m)`. The fixed recurrent matrix uses `edge_sign * edge_magnitude / max(1, incoming absolute sum)` and never receives gradients. `forward_step` computes a bounded rate state:

```python
drive = type_bias_mv[type_index].expand(batch, -1)
drive.index_add_(1, input_neuron_index, features * input_gain)
recurrent = torch.sparse.mm(fixed_topology, torch.sigmoid(state.voltage).T).T
alpha = torch.clamp(dt_s * 1000.0 / tau_m_ms, 0.0, 1.0)
voltage = state.voltage + alpha * (-state.voltage + drive + recurrent)
rates = torch.sigmoid(voltage)
command = torch.tanh(rates[:, output_neuron_index] @ readout.T)
```

`forward_sequence` accepts `(batch, time, features)`, carries voltage between frames, and calls `state = state.detached()` after every `truncate_steps` frames except the last frame. Export model names.

- [ ] **Step 4: Run model tests**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_model.py -q`

Expected: `4 passed`.

- [ ] **Step 5: Commit**

Run: `git add src/flydrones/connectome_training tests/connectome_training/test_model.py && git commit -m "feat: add topology-constrained recurrent trainer core"`

Expected: one commit with the differentiable core and its tests.

### Task 3: Deployment-visible features, losses, and truncated sequence training

**Files:**
- Create: `src/flydrones/connectome_training/features.py`
- Create: `src/flydrones/connectome_training/losses.py`
- Create: `src/flydrones/connectome_training/trainer.py`
- Modify: `src/flydrones/connectome_training/__init__.py`
- Test: `tests/connectome_training/test_trainer.py`

**Interfaces:**
- Consumes: `TrainingSequence` and `ConnectomeConstrainedCore`.
- Produces: `FEATURE_NAMES`, `sequence_tensors`, `LossWeights`, `sequence_loss`, `train_epoch`, and `evaluate_sequences`.

- [ ] **Step 1: Write failing feature-isolation and learning tests**

```python
from dataclasses import replace

import numpy as np
from scipy import sparse
import torch

from flydrones.brain.connectome import Connectome
from flydrones.connectome_training.dataset import SequenceFrame, SequenceProvenance, TeacherTarget, TrainingSequence
from flydrones.connectome_training.features import FEATURE_NAMES, sequence_tensors
from flydrones.connectome_training.losses import LossWeights, sequence_loss
from flydrones.connectome_training.model import ConnectomeConstrainedCore
from flydrones.connectome_training.parameters import build_structure_identity, initial_parameter_set
from flydrones.connectome_training.trainer import evaluate_sequences, train_epoch


def toy_sequence(clearance=0.8):
    provenance = SequenceProvenance("train", 11, "teacher@test", "a" * 64, "b" * 64, "training-world")
    frames, targets = [], []
    for i in range(6):
        depth = np.full((4, 6), 2.0 + i * 0.1, np.float32)
        frames.append(SequenceFrame((i + 1) * 50_000_000, (i + 1) * 50_000_000,
            np.full((4, 6, 3), 32 + i, np.uint8), depth,
            np.array([0, 0, 1], np.float32), np.zeros(3, np.float32), 0.0, 0.0,
            np.array([5, 0, 1], np.float32)))
        targets.append(TeacherTarget(np.array([0.4, 0, 0], np.float32), 0.0,
            np.array([[1, 0, 1]], np.float32), clearance, i == 5))
    return TrainingSequence(provenance, frames, targets)


def toy_model():
    n = len(FEATURE_NAMES) + 4
    connectome = Connectome("toy", sparse.eye(n, format="csc", dtype=np.float32),
        np.array(["input"] * len(FEATURE_NAMES) + ["DN"] * 4), np.array([""] * n))
    identity = build_structure_identity(connectome, "c" * 64)
    params = initial_parameter_set(identity, FEATURE_NAMES, ("vx", "vy", "vz", "yaw_rate"), 4)
    return ConnectomeConstrainedCore(connectome, params, np.arange(len(FEATURE_NAMES)), np.arange(n - 4, n))


def test_teacher_labels_do_not_change_deployment_features():
    first = toy_sequence(0.8)
    second = TrainingSequence(first.provenance, first.frames, [replace(t, minimum_clearance_m=0.1) for t in first.targets])
    x1, _, _ = sequence_tensors(first)
    x2, _, _ = sequence_tensors(second)
    assert torch.equal(x1, x2)


def test_loss_reports_safety_imitation_smoothness_and_saturation():
    prediction = torch.tensor([[[2.0, 0, 0, 0], [0.0, 0, 0, 0]]])
    target = torch.zeros_like(prediction)
    clearance = torch.tensor([[0.2, 1.0]])
    total, terms = sequence_loss(prediction, target, clearance, LossWeights())
    assert total > 0
    assert set(terms) == {"imitation", "clearance_weighted", "smoothness", "saturation"}


def test_offline_training_reduces_loss_and_resets_between_sequences():
    torch.manual_seed(4)
    model = toy_model()
    sequences = [toy_sequence(), replace(toy_sequence(), provenance=replace(toy_sequence().provenance, seed=12, world_sha256="d" * 64))]
    optimizer = torch.optim.Adam(model.parameters(), lr=0.03)
    before = evaluate_sequences(model, sequences, truncate_steps=3)["total"]
    for _ in range(40):
        train_epoch(model, sequences, optimizer, truncate_steps=3)
    after = evaluate_sequences(model, sequences, truncate_steps=3)["total"]
    assert after < before * 0.7
```

- [ ] **Step 2: Run and verify missing modules**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_trainer.py -q`

Expected: collection fails on the first missing Stage B module.

- [ ] **Step 3: Implement deployment-only features and losses**

Use this fixed feature order:

```python
FEATURE_NAMES = (
    "depth_left", "depth_center", "depth_right", "luminance",
    "velocity_x", "velocity_y", "velocity_z", "yaw_rate",
    "goal_body_x", "goal_body_y", "goal_z", "goal_distance",
)
```

Depth features are clipped median inverse depth over three equal image columns; luminance is RGB mean divided by 255; velocity and yaw rate are clipped to configured normalization constants; goal delta is rotated into body coordinates and normalized. `sequence_tensors` returns batched float32 `(features, commands, minimum_clearance)` tensors and never reads horizon, terminal, provenance, evidence, obstacle truth, or contacts to construct features.

`sequence_loss` uses mean squared imitation; multiplies per-frame imitation by `1 + relu(clearance_margin - teacher_clearance)` for the safety-weighted term; penalizes adjacent command deltas and `relu(abs(command)-1)^2`. Reject shape mismatch and non-finite inputs. `train_epoch` resets state per sequence, clips gradient norm to 5, and returns sample-weighted component means. `evaluate_sequences` uses `torch.no_grad()` and identical reset semantics. Export public names.

- [ ] **Step 4: Run trainer tests**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_trainer.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

Run: `git add src/flydrones/connectome_training tests/connectome_training/test_trainer.py && git commit -m "feat: train connectome parameters on deployment sequences"`

Expected: one commit with feature extraction, auditable loss, trainer, exports, and tests.

### Task 4: Dataset isolation, curriculum gates, and reproducible checkpoints

**Files:**
- Create: `src/flydrones/connectome_training/governance.py`
- Create: `src/flydrones/connectome_training/checkpoint.py`
- Modify: `src/flydrones/connectome_training/__init__.py`
- Test: `tests/connectome_training/test_governance.py`

**Interfaces:**
- Consumes: sequence provenance, `ParameterSet`, model state dict, optimizer state dict, epoch metrics, and curriculum thresholds.
- Produces: `validate_dataset_partitions`, `CurriculumGate`, `evaluate_gate`, `save_checkpoint`, and `load_checkpoint`.

- [ ] **Step 1: Write failing governance tests**

```python
from dataclasses import replace
import json

import pytest
import torch

from flydrones.connectome_training.checkpoint import load_checkpoint, save_checkpoint
from flydrones.connectome_training.dataset import SequenceProvenance
from flydrones.connectome_training.governance import CurriculumGate, evaluate_gate, validate_dataset_partitions


def provenance(split, seed, world, source="generated-training-world"):
    return SequenceProvenance(split, seed, "ego@test", world, "b" * 64, source)


def test_partition_overlap_and_formal_sources_are_rejected():
    train = [provenance("train", 1, "a" * 64)]
    with pytest.raises(ValueError, match="overlap"):
        validate_dataset_partitions(train, [provenance("val", 1, "c" * 64)])
    with pytest.raises(ValueError, match="formal comparison evidence"):
        validate_dataset_partitions([provenance("train", 2, "d" * 64, "formal-freeze")], [])


def test_curriculum_requires_every_safety_and_quality_gate():
    gate = CurriculumGate(episodes=10, minimum_success_rate=0.9, maximum_collision_rate=0.0,
                          minimum_clearance_m=0.8, maximum_validation_loss=0.2)
    passed, failures = evaluate_gate(gate, {"episodes": 10, "success_rate": 0.95,
        "collision_rate": 0.01, "minimum_clearance_m": 0.9, "validation_loss": 0.1})
    assert not passed
    assert failures == ("collision_rate",)


def test_checkpoint_is_atomic_hashed_and_rng_reproducible(tmp_path):
    generator = torch.Generator().manual_seed(9)
    expected = torch.rand(3, generator=generator)
    out = save_checkpoint(tmp_path / "checkpoint", model_state={"w": torch.tensor([1.0])},
        optimizer_state={"step": 3}, metadata={"epoch": 4, "seed": 9, "dataset_sha256": "a" * 64})
    loaded = load_checkpoint(out)
    assert loaded["metadata"]["epoch"] == 4
    assert torch.equal(loaded["model_state"]["w"], torch.tensor([1.0]))
    payload = out / "checkpoint.pt"
    payload.write_bytes(payload.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_checkpoint(out)
```

- [ ] **Step 2: Run and verify missing governance modules**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_governance.py -q`

Expected: collection fails on a missing module.

- [ ] **Step 3: Implement hard partition and checkpoint gates**

`validate_dataset_partitions` calls `reject_formal_evidence` for every provenance, requires split values to match their partition, and rejects intersecting seeds or world hashes. `CurriculumGate` is frozen with the five fields shown in the test. `evaluate_gate` checks every field, returns `(passed, tuple_of_failed_field_names)` in dataclass field order, and rejects missing/non-finite metrics.

`save_checkpoint` requires metadata keys `epoch`, `seed`, and `dataset_sha256`; captures Python RNG as integer tuples, NumPy RNG as primitive metadata plus an integer tensor, and Torch RNG as a byte tensor; writes `checkpoint.pt` with `torch.save`, hashes it, writes schema `flydrones-connectome-checkpoint-v1`, then atomically renames the directory. `load_checkpoint` verifies schema and SHA-256 before calling `torch.load(..., weights_only=True, map_location="cpu")`, so an artifact cannot execute arbitrary pickle globals. Export public names.

- [ ] **Step 4: Run governance tests**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_governance.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

Run: `git add src/flydrones/connectome_training tests/connectome_training/test_governance.py && git commit -m "feat: govern connectome curricula and checkpoints"`

Expected: one commit with governance, checkpoints, exports, and tests.

### Task 5: Deterministic Stage B smoke training and full-model initialization

**Files:**
- Create: `configs/connectome_training_stage_b_v1.yaml`
- Create: `tools/connectome_training/train_stage_b.py`
- Create: `tests/connectome_training/test_train_stage_b.py`
- Modify: `docs/CONNECTOME_TRAINING.md`
- Create: `results/connectome-training/stage-b/smoke_report.json`
- Create: `results/connectome-training/stage-b/full-initialization/manifest.json`
- Create: `results/connectome-training/stage-b/full-initialization/parameters.npz`

**Interfaces:**
- Consumes: Tasks 1–4, `data/malecns_full.npz`, `configs/forest-trained-v2.yaml`, and deterministic synthetic Stage A `TrainingSequence` objects.
- Produces: a smoke checkpoint/report and a separately labelled, hash-linked full-MaleCNS initialization parameter artifact.

- [ ] **Step 1: Write failing CLI test**

```python
import json
from pathlib import Path
import subprocess
import sys


def test_stage_b_cli_reduces_loss_and_writes_identity_artifacts(tmp_path):
    completed = subprocess.run([sys.executable, "tools/connectome_training/train_stage_b.py",
        "--epochs", "25", "--output", str(tmp_path)], check=True, capture_output=True, text=True)
    report = json.loads((tmp_path / "smoke_report.json").read_text(encoding="utf-8"))
    assert report["schema"] == "flydrones-connectome-stage-b-smoke-v1"
    assert report["identity"] == "connectome-constrained-training-smoke"
    assert report["final_validation_loss"] < report["initial_validation_loss"]
    assert report["trainable"] == ["input_gain", "type_bias_mv", "tau_m_ms", "descending_readout"]
    assert json.loads(completed.stdout)["passed"] is True
```

- [ ] **Step 2: Run and verify missing CLI failure**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_train_stage_b.py -q`

Expected: fails because `tools/connectome_training/train_stage_b.py` does not exist.

- [ ] **Step 3: Add configuration and CLI**

Create this config:

```yaml
schema: flydrones-connectome-training-stage-b-config-v1
seed: 20260922
truncate_steps: 4
optimizer:
  name: adam
  learning_rate: 0.03
  gradient_clip_norm: 5.0
loss:
  imitation: 1.0
  clearance_weighted: 2.0
  smoothness: 0.05
  saturation: 0.1
offline_gate:
  maximum_loss_ratio: 0.8
  require_finite_parameters: true
```

The CLI supports `--epochs`, `--seed`, `--config`, `--output`, and `--initialize-full`. Normal smoke mode constructs the same deterministic toy topology and two disjoint training/validation sequences used by unit tests, validates partitions, trains for the requested epochs, saves `checkpoint/`, and atomically writes a report containing initial/final train and validation losses, all loss terms, seed, topology hash, parameter count, PyTorch version, elapsed wall time, and gate failures. It exits zero even when the gate fails but prints `passed` truthfully.

With `--initialize-full`, load `data/malecns_full.npz`, hash it, resolve groups from `configs/forest-trained-v2.yaml` without mutating the saved NPZ, build a `full-male-cns` `ParameterSet`, and write `full-initialization/`. The artifact must report 166700 neurons and 25582837 connections and contain only the allowed trainable arrays; it does not claim that full-model optimization has run.

- [ ] **Step 4: Run Stage B tests**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training -q`

Expected: all Stage A and Stage B tests pass.

- [ ] **Step 5: Generate real Stage B artifacts**

Run: `$env:PYTHONPATH='src'; python tools/connectome_training/train_stage_b.py --epochs 80 --output results/connectome-training/stage-b`

Expected: exit 0; `smoke_report.json` has `final_validation_loss < initial_validation_loss` and a passing offline gate.

Run: `$env:PYTHONPATH='src'; python tools/connectome_training/train_stage_b.py --initialize-full --output results/connectome-training/stage-b`

Expected: exit 0; the full initialization manifest identifies 166700 neurons, 25582837 connections, and source model hash `b6be8b3dd901e2e0893303c04058a110d6e0fb9922a69022b26514efcf06100c`.

- [ ] **Step 6: Extend documentation**

Document dependency installation, smoke training, full initialization, identity limits, the fact that the smoke run is not a flight-success result, and that PX4/Gazebo remains gated on a later closed-loop plan.

- [ ] **Step 7: Commit**

Run: `git add configs/connectome_training_stage_b_v1.yaml tools/connectome_training/train_stage_b.py tests/connectome_training/test_train_stage_b.py docs/CONNECTOME_TRAINING.md results/connectome-training/stage-b && git commit -m "feat: establish connectome training stage-b offline gate"`

Expected: one commit with reproducible Stage B entry points and measured artifacts.

### Task 6: Stage B regression and freeze audit

**Files:**
- Modify only if a failure requires a fix in files created by Tasks 1–5.
- Test: all connectome-training tests, freeze verification, and project regression evidence.

**Interfaces:**
- Consumes: every Stage B public API and artifact.
- Produces: audited Stage B offline-gate status without modifying formal evidence.

- [ ] **Step 1: Verify the formal freeze**

Run: `$env:PYTHONPATH='src'; python -c "from pathlib import Path; from flydrones.benchmark.runner import verify_freeze_manifest; verify_freeze_manifest(Path('results/fly-ego-comparison/freeze/manifest.json'), Path('.')); print('freeze verified')"`

Expected: `freeze verified`.

- [ ] **Step 2: Run all connectome-training tests**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training -q`

Expected: all tests pass with no failures.

- [ ] **Step 3: Validate artifact identity and loss gate**

Run: `$env:PYTHONPATH='src'; python -c "import json; from pathlib import Path; s=json.loads(Path('results/connectome-training/stage-b/smoke_report.json').read_text()); f=json.loads(Path('results/connectome-training/stage-b/full-initialization/manifest.json').read_text()); assert s['passed_offline_gate']; assert s['final_validation_loss'] < s['initial_validation_loss']; assert f['identity']['neurons']==166700; assert f['identity']['connections']==25582837; print('stage-b artifacts verified')"`

Expected: `stage-b artifacts verified`.

- [ ] **Step 4: Run project regression evidence under the approved exception**

Run: `$env:PYTHONPATH='src'; python -m pytest -q`

Expected: either the entire suite passes, or the only failure is the approved sealed `tests/test_distributed_stress.py::test_four_independent_udp_processes_converge` start-file race. If it fails, run that exact test independently and require it to pass; any other failure blocks Stage B.

- [ ] **Step 5: Commit test-driven corrections if required**

If Tasks 1–5 files required corrections, commit only those files with `git commit -m "fix: harden connectome stage-b offline training"`. Do not commit changes to formal-manifest-covered paths.
