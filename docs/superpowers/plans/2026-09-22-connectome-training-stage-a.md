# Connectome Training Stage A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a versioned, truth-isolated teacher-sequence contract and deterministic latency profiler without changing the frozen 2026-09-22 comparison baseline.

**Architecture:** A new `flydrones.connectome_training` package owns training-only data and profiling interfaces. A recorder accepts only the existing deployment-visible `Observation` and teacher `Decision` contracts, writes a fixed-key NPZ plus hashed manifest, and rejects stale or non-monotonic data. A controller-agnostic profiler aggregates component timings and a CLI produces a reproducible Stage A baseline report from the existing complete-connectome controller.

**Tech Stack:** Python 3.12, dataclasses, NumPy NPZ, hashlib/JSON provenance, pytest, existing `flydrones.benchmark` contracts.

**Spec:** `docs/superpowers/specs/2026-09-22-connectome-constrained-realtime-training-design.md`

## Global Constraints

- Do not modify files covered by `results/fly-ego-comparison/freeze/manifest.json`; add new versioned files only.
- The complete-connectome identity remains 166,700 neurons and 25,582,837 connections; Stage A records it but does not alter it.
- Student inputs are defined by an allowlist of deployment-visible fields; world geometry, contacts, collision truth and obstacle truth never enter `samples.npz`.
- Training, development and frozen evaluation seed sets remain disjoint and content-hashed.
- Existing formal results remain evaluation evidence and may not be exported as training sequences.
- Every artifact records schema version, source hashes, controller identity, seed and split.

## Review Focus

- Non-monotonic or duplicated `sim_ns` must be rejected before an artifact is written; Task 1 tests duplicated time and Task 2 tests recorder rollback.
- NaN/Inf in sensor arrays or teacher commands must be rejected with a field-specific error; Task 1 tests depth and Task 2 tests command validation.
- A caller attempting to add world geometry or contact truth must have no serialization path; Task 1 asserts the exact NPZ key allowlist and Task 2 accepts only typed contracts.
- A path or manifest carrying the old formal freeze seal must be rejected as a training split; Task 2 tests formal-evidence rejection.
- Latency summaries with zero samples or missing component keys must fail clearly rather than report misleading zeros; Task 3 tests both cases.

---

### Task 1: Versioned training sequence contract

**Files:**
- Create: `src/flydrones/connectome_training/__init__.py`
- Create: `src/flydrones/connectome_training/dataset.py`
- Test: `tests/connectome_training/test_dataset.py`

**Interfaces:**
- Consumes: `flydrones.benchmark.contract.Observation`, `flydrones.benchmark.contract.Command`.
- Produces: `SequenceProvenance`, `SequenceFrame`, `TeacherTarget`, `TrainingSequence`, `write_sequence(path, sequence) -> Path`, and `load_sequence(path) -> TrainingSequence`.

- [ ] **Step 1: Write the failing round-trip, validation and allowlist tests**

```python
from dataclasses import replace
import json

import numpy as np
import pytest

from flydrones.connectome_training.dataset import (
    INPUT_ARRAY_KEYS,
    SequenceFrame,
    SequenceProvenance,
    TeacherTarget,
    TrainingSequence,
    load_sequence,
    write_sequence,
)


def frame(t: int) -> SequenceFrame:
    return SequenceFrame(
        sim_ns=t,
        frame_ns=t,
        rgb=np.zeros((4, 6, 3), np.uint8),
        depth_m=np.ones((4, 6), np.float32),
        position_enu=np.array([0, 0, 1], np.float32),
        velocity_enu=np.zeros(3, np.float32),
        yaw=0.0,
        yaw_rate=0.0,
        goal_enu=np.array([5, 0, 1], np.float32),
    )


def target() -> TeacherTarget:
    return TeacherTarget(
        velocity_enu=np.array([1, 0, 0], np.float32),
        yaw_rate=0.0,
        horizon_enu=np.array([[1, 0, 1], [2, 0, 1]], np.float32),
        minimum_clearance_m=0.8,
        terminal=False,
    )


def provenance() -> SequenceProvenance:
    return SequenceProvenance(
        split="train",
        seed=101,
        teacher="ego@23a8d5a",
        world_sha256="a" * 64,
        config_sha256="b" * 64,
        source="generated-training-world",
    )


def test_round_trip_uses_exact_student_allowlist(tmp_path):
    sequence = TrainingSequence(provenance(), [frame(50_000_000), frame(100_000_000)], [target(), target()])
    out = write_sequence(tmp_path / "episode", sequence)
    loaded = load_sequence(out)
    assert loaded.provenance == sequence.provenance
    assert np.array_equal(loaded.frames[1].rgb, sequence.frames[1].rgb)
    with np.load(out / "samples.npz") as arrays:
        assert set(arrays.files) == set(INPUT_ARRAY_KEYS) | {
            "teacher_velocity_enu", "teacher_yaw_rate", "teacher_horizon_enu",
            "teacher_minimum_clearance_m", "teacher_terminal",
        }
        assert not any("obstacle" in key or "contact" in key or "truth" in key for key in arrays.files)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "flydrones-connectome-sequence-v1"
    assert len(manifest["samples_sha256"]) == 64


def test_duplicate_sim_time_is_rejected(tmp_path):
    sequence = TrainingSequence(provenance(), [frame(50), frame(50)], [target(), target()])
    with pytest.raises(ValueError, match="strictly increasing sim_ns"):
        write_sequence(tmp_path / "episode", sequence)


def test_non_finite_depth_names_the_field(tmp_path):
    bad = frame(50)
    bad.depth_m[0, 0] = np.nan
    with pytest.raises(ValueError, match="depth_m contains non-finite"):
        write_sequence(tmp_path / "episode", TrainingSequence(provenance(), [bad], [target()]))
```

- [ ] **Step 2: Run the tests and verify import failure**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_dataset.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'flydrones.connectome_training'`.

- [ ] **Step 3: Implement the fixed schema and strict validator**

```python
# src/flydrones/connectome_training/dataset.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

SCHEMA = "flydrones-connectome-sequence-v1"
INPUT_ARRAY_KEYS = (
    "sim_ns", "frame_ns", "rgb", "depth_m", "position_enu",
    "velocity_enu", "yaw", "yaw_rate", "goal_enu",
)


@dataclass(frozen=True)
class SequenceProvenance:
    split: str
    seed: int
    teacher: str
    world_sha256: str
    config_sha256: str
    source: str


@dataclass
class SequenceFrame:
    sim_ns: int
    frame_ns: int
    rgb: np.ndarray
    depth_m: np.ndarray
    position_enu: np.ndarray
    velocity_enu: np.ndarray
    yaw: float
    yaw_rate: float
    goal_enu: np.ndarray


@dataclass
class TeacherTarget:
    velocity_enu: np.ndarray
    yaw_rate: float
    horizon_enu: np.ndarray
    minimum_clearance_m: float
    terminal: bool


@dataclass
class TrainingSequence:
    provenance: SequenceProvenance
    frames: list[SequenceFrame]
    targets: list[TeacherTarget]


def _finite(name: str, value: np.ndarray) -> None:
    if not np.isfinite(value).all():
        raise ValueError(f"{name} contains non-finite values")


def _validate(sequence: TrainingSequence) -> None:
    if not sequence.frames or len(sequence.frames) != len(sequence.targets):
        raise ValueError("frames and targets must have the same non-zero length")
    times = np.asarray([f.sim_ns for f in sequence.frames], np.int64)
    if np.any(np.diff(times) <= 0):
        raise ValueError("frames require strictly increasing sim_ns")
    for f in sequence.frames:
        if f.frame_ns > f.sim_ns:
            raise ValueError("frame_ns cannot be newer than sim_ns")
        for name in ("depth_m", "position_enu", "velocity_enu", "goal_enu"):
            _finite(name, np.asarray(getattr(f, name)))
    for t in sequence.targets:
        _finite("teacher_velocity_enu", np.asarray(t.velocity_enu))
        _finite("teacher_horizon_enu", np.asarray(t.horizon_enu))
        _finite("teacher_yaw_rate", np.asarray(t.yaw_rate))


def _digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _arrays(sequence: TrainingSequence) -> dict[str, np.ndarray]:
    return {
        "sim_ns": np.asarray([f.sim_ns for f in sequence.frames], np.int64),
        "frame_ns": np.asarray([f.frame_ns for f in sequence.frames], np.int64),
        "rgb": np.stack([np.asarray(f.rgb, np.uint8) for f in sequence.frames]),
        "depth_m": np.stack([np.asarray(f.depth_m, np.float32) for f in sequence.frames]),
        "position_enu": np.stack([np.asarray(f.position_enu, np.float32) for f in sequence.frames]),
        "velocity_enu": np.stack([np.asarray(f.velocity_enu, np.float32) for f in sequence.frames]),
        "yaw": np.asarray([f.yaw for f in sequence.frames], np.float32),
        "yaw_rate": np.asarray([f.yaw_rate for f in sequence.frames], np.float32),
        "goal_enu": np.stack([np.asarray(f.goal_enu, np.float32) for f in sequence.frames]),
        "teacher_velocity_enu": np.stack([np.asarray(t.velocity_enu, np.float32) for t in sequence.targets]),
        "teacher_yaw_rate": np.asarray([t.yaw_rate for t in sequence.targets], np.float32),
        "teacher_horizon_enu": np.stack([np.asarray(t.horizon_enu, np.float32) for t in sequence.targets]),
        "teacher_minimum_clearance_m": np.asarray([t.minimum_clearance_m for t in sequence.targets], np.float32),
        "teacher_terminal": np.asarray([t.terminal for t in sequence.targets], np.bool_),
    }


def write_sequence(path: str | Path, sequence: TrainingSequence) -> Path:
    _validate(sequence)
    path = Path(path)
    temporary = path.with_name(path.name + ".writing")
    if path.exists() or temporary.exists():
        raise FileExistsError(path if path.exists() else temporary)
    temporary.mkdir(parents=True)
    samples = temporary / "samples.npz"
    np.savez_compressed(samples, **_arrays(sequence))
    manifest = {
        "schema": SCHEMA,
        "provenance": asdict(sequence.provenance),
        "samples": len(sequence.frames),
        "samples_sha256": _digest(samples),
    }
    (temporary / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.rename(path)
    return path


def load_sequence(path: str | Path) -> TrainingSequence:
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    samples = path / "samples.npz"
    if manifest.get("schema") != SCHEMA:
        raise ValueError("unsupported training sequence schema")
    if manifest.get("samples_sha256") != _digest(samples):
        raise ValueError("samples.npz hash mismatch")
    required = set(INPUT_ARRAY_KEYS) | {
        "teacher_velocity_enu", "teacher_yaw_rate", "teacher_horizon_enu",
        "teacher_minimum_clearance_m", "teacher_terminal",
    }
    with np.load(samples, allow_pickle=False) as a:
        if set(a.files) != required:
            raise ValueError("samples.npz keys do not match the student/teacher contract")
        n = int(a["sim_ns"].shape[0])
        frames = [SequenceFrame(
            int(a["sim_ns"][i]), int(a["frame_ns"][i]), a["rgb"][i].copy(),
            a["depth_m"][i].copy(), a["position_enu"][i].copy(),
            a["velocity_enu"][i].copy(), float(a["yaw"][i]),
            float(a["yaw_rate"][i]), a["goal_enu"][i].copy(),
        ) for i in range(n)]
        targets = [TeacherTarget(
            a["teacher_velocity_enu"][i].copy(), float(a["teacher_yaw_rate"][i]),
            a["teacher_horizon_enu"][i].copy(),
            float(a["teacher_minimum_clearance_m"][i]),
            bool(a["teacher_terminal"][i]),
        ) for i in range(n)]
    sequence = TrainingSequence(SequenceProvenance(**manifest["provenance"]), frames, targets)
    _validate(sequence)
    return sequence
```

- [ ] **Step 4: Run the contract tests**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_dataset.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Export the public names and commit**

```python
# src/flydrones/connectome_training/__init__.py
from .dataset import (
    INPUT_ARRAY_KEYS,
    SequenceFrame,
    SequenceProvenance,
    TeacherTarget,
    TrainingSequence,
    load_sequence,
    write_sequence,
)

__all__ = [
    "INPUT_ARRAY_KEYS", "SequenceFrame", "SequenceProvenance", "TeacherTarget",
    "TrainingSequence", "load_sequence", "write_sequence",
]
```

Run: `git add src/flydrones/connectome_training tests/connectome_training/test_dataset.py && git commit -m "feat: add truth-isolated training sequence contract"`

Expected: one commit containing the contract and its three tests.

### Task 2: Typed teacher recorder and provenance gate

**Files:**
- Create: `src/flydrones/connectome_training/recorder.py`
- Modify: `src/flydrones/connectome_training/__init__.py`
- Test: `tests/connectome_training/test_recorder.py`

**Interfaces:**
- Consumes: `Observation`, `Decision`, `SequenceProvenance`, and an optional teacher horizon supplied as an `(H, 3)` float array.
- Produces: `TeacherSequenceRecorder.append(obs, decision, *, horizon_enu, minimum_clearance_m, terminal)`, `TeacherSequenceRecorder.finish(path) -> Path`, and `reject_formal_evidence(provenance)`.

- [ ] **Step 1: Write failing recorder tests**

```python
import numpy as np
import pytest

from flydrones.benchmark.contract import Command, Decision, Observation
from flydrones.connectome_training.dataset import SequenceProvenance, load_sequence
from flydrones.connectome_training.recorder import TeacherSequenceRecorder

FORMAL_SEAL = "9d10bb72c1fda4048f0439c9dfb823583d8464a8491349f9e732e9cced87d937"


def observation(t: int) -> Observation:
    return Observation(t, t, np.zeros((4, 6, 3), np.uint8), np.ones((4, 6), np.float32),
                       (), (0, 0, 1), (0, 0, 0), 0.0, 0.0, (5, 0, 1))


def provenance(source: str = "training-generator") -> SequenceProvenance:
    return SequenceProvenance("train", 7, "ego@test", "a" * 64, "b" * 64, source)


def test_recorder_converts_only_typed_observation_and_command(tmp_path):
    recorder = TeacherSequenceRecorder(provenance())
    recorder.append(observation(50), Decision(Command((1, 0, 0), 0.2), 0.01, {"world_truth": [1, 2, 3]}),
                    horizon_enu=np.array([[1, 0, 1]], np.float32), minimum_clearance_m=0.7, terminal=False)
    out = recorder.finish(tmp_path / "sequence")
    loaded = load_sequence(out)
    assert loaded.targets[0].yaw_rate == pytest.approx(0.2)
    assert "world_truth" not in (out / "manifest.json").read_text(encoding="utf-8")


def test_recorder_rejects_time_rollback():
    recorder = TeacherSequenceRecorder(provenance())
    decision = Decision(Command((1, 0, 0), 0.0), 0.01, {})
    recorder.append(observation(100), decision, horizon_enu=np.zeros((1, 3)), minimum_clearance_m=1.0, terminal=False)
    with pytest.raises(ValueError, match="strictly newer"):
        recorder.append(observation(50), decision, horizon_enu=np.zeros((1, 3)), minimum_clearance_m=1.0, terminal=False)


def test_formal_evidence_cannot_be_training_source():
    with pytest.raises(ValueError, match="formal comparison evidence"):
        TeacherSequenceRecorder(provenance(f"formal-freeze:{FORMAL_SEAL}"))


def test_non_finite_teacher_command_is_rejected():
    recorder = TeacherSequenceRecorder(provenance())
    bad = Decision(Command((np.nan, 0, 0), 0.0), 0.01, {})
    with pytest.raises(ValueError, match="teacher_velocity_enu"):
        recorder.append(observation(50), bad, horizon_enu=np.zeros((1, 3)), minimum_clearance_m=1.0, terminal=False)
```

- [ ] **Step 2: Run and verify missing recorder module**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_recorder.py -q`

Expected: FAIL during collection with `No module named 'flydrones.connectome_training.recorder'`.

- [ ] **Step 3: Implement recorder with a hard provenance boundary**

```python
from __future__ import annotations

import numpy as np

from flydrones.benchmark.contract import Decision, Observation
from .dataset import SequenceFrame, SequenceProvenance, TeacherTarget, TrainingSequence, write_sequence

FORMAL_FREEZE_SEAL = "9d10bb72c1fda4048f0439c9dfb823583d8464a8491349f9e732e9cced87d937"


def reject_formal_evidence(provenance: SequenceProvenance) -> None:
    source = provenance.source.lower()
    if "formal" in source or FORMAL_FREEZE_SEAL in source:
        raise ValueError("formal comparison evidence cannot be used as training data")


class TeacherSequenceRecorder:
    def __init__(self, provenance: SequenceProvenance):
        reject_formal_evidence(provenance)
        self.provenance = provenance
        self.frames: list[SequenceFrame] = []
        self.targets: list[TeacherTarget] = []

    def append(self, obs: Observation, decision: Decision, *, horizon_enu: np.ndarray,
               minimum_clearance_m: float, terminal: bool) -> None:
        if self.frames and obs.sim_ns <= self.frames[-1].sim_ns:
            raise ValueError("observation sim_ns must be strictly newer")
        velocity = np.asarray(decision.command.velocity_enu, np.float32)
        if not np.isfinite(velocity).all():
            raise ValueError("teacher_velocity_enu contains non-finite values")
        self.frames.append(SequenceFrame(
            obs.sim_ns, obs.frame_ns, np.array(obs.rgb, copy=True), np.array(obs.depth_m, copy=True),
            np.asarray(obs.position, np.float32), np.asarray(obs.velocity, np.float32),
            float(obs.yaw), float(obs.yaw_rate), np.asarray(obs.goal, np.float32),
        ))
        self.targets.append(TeacherTarget(velocity, float(decision.command.yaw_rate),
                                          np.asarray(horizon_enu, np.float32),
                                          float(minimum_clearance_m), bool(terminal)))

    def finish(self, path):
        return write_sequence(path, TrainingSequence(self.provenance, self.frames, self.targets))
```

- [ ] **Step 4: Run recorder and contract tests**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_dataset.py tests/connectome_training/test_recorder.py -q`

Expected: `7 passed`.

- [ ] **Step 5: Export recorder names and commit**

Add `TeacherSequenceRecorder` and `reject_formal_evidence` to `connectome_training.__all__`.

Run: `git add src/flydrones/connectome_training tests/connectome_training/test_recorder.py && git commit -m "feat: record typed teacher sequences"`

Expected: one commit containing the recorder and four tests.

### Task 3: Deterministic component latency profiler

**Files:**
- Create: `src/flydrones/connectome_training/profiling.py`
- Modify: `src/flydrones/connectome_training/__init__.py`
- Test: `tests/connectome_training/test_profiling.py`

**Interfaces:**
- Consumes: iterable decision evidence dictionaries containing `elapsed_wall_s` and optional `components` or legacy `brain_wall_s`.
- Produces: `summarize_latency(samples) -> dict`, `profile_controller(controller, observations) -> dict`, with mean/P50/P95/P99/max for total, neural and residual overhead.

- [ ] **Step 1: Write failing profiler tests**

```python
import pytest

from flydrones.connectome_training.profiling import summarize_latency


def test_latency_summary_has_interpolated_percentiles_and_components():
    samples = [
        {"elapsed_wall_s": 0.10, "brain_wall_s": 0.08},
        {"elapsed_wall_s": 0.20, "brain_wall_s": 0.15},
        {"elapsed_wall_s": 0.30, "brain_wall_s": 0.22},
        {"elapsed_wall_s": 0.40, "brain_wall_s": 0.29},
    ]
    result = summarize_latency(samples)
    assert result["samples"] == 4
    assert result["total_s"]["mean"] == pytest.approx(0.25)
    assert result["total_s"]["p95"] == pytest.approx(0.385)
    assert result["neural_s"]["p99"] > result["neural_s"]["p95"]
    assert result["overhead_s"]["mean"] == pytest.approx(0.065)


def test_empty_latency_samples_are_rejected():
    with pytest.raises(ValueError, match="at least one latency sample"):
        summarize_latency([])


def test_missing_total_latency_is_rejected():
    with pytest.raises(ValueError, match="elapsed_wall_s"):
        summarize_latency([{"brain_wall_s": 0.1}])
```

- [ ] **Step 2: Run and verify missing profiler module**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_profiling.py -q`

Expected: FAIL during collection with `No module named 'flydrones.connectome_training.profiling'`.

- [ ] **Step 3: Implement aggregation and controller profiling**

```python
from __future__ import annotations

import time
from typing import Iterable

import numpy as np


def _stats(values: list[float]) -> dict[str, float]:
    data = np.asarray(values, np.float64)
    return {
        "mean": float(data.mean()),
        "p50": float(np.percentile(data, 50)),
        "p95": float(np.percentile(data, 95)),
        "p99": float(np.percentile(data, 99)),
        "max": float(data.max()),
    }


def summarize_latency(samples: Iterable[dict]) -> dict:
    rows = list(samples)
    if not rows:
        raise ValueError("at least one latency sample is required")
    if any("elapsed_wall_s" not in row for row in rows):
        raise ValueError("every latency sample requires elapsed_wall_s")
    total = [float(row["elapsed_wall_s"]) for row in rows]
    neural = [float(row.get("components", {}).get("neural_s", row.get("brain_wall_s", 0.0))) for row in rows]
    if not np.isfinite(total + neural).all():
        raise ValueError("latency samples contain non-finite values")
    overhead = [max(0.0, t - n) for t, n in zip(total, neural)]
    return {"samples": len(rows), "total_s": _stats(total), "neural_s": _stats(neural),
            "overhead_s": _stats(overhead)}


def profile_controller(controller, observations) -> dict:
    rows = []
    for obs in observations:
        started = time.perf_counter()
        decision = controller.step(obs)
        measured = time.perf_counter() - started
        evidence = dict(decision.evidence)
        evidence["elapsed_wall_s"] = float(decision.elapsed_wall_s)
        evidence["outer_wall_s"] = measured
        rows.append(evidence)
    result = summarize_latency(rows)
    result["outer_s"] = _stats([row["outer_wall_s"] for row in rows])
    return result
```

- [ ] **Step 4: Run profiler tests**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_profiling.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Export profiler names and commit**

Add `profile_controller` and `summarize_latency` to `connectome_training.__all__`.

Run: `git add src/flydrones/connectome_training tests/connectome_training/test_profiling.py && git commit -m "feat: add deterministic connectome latency profiler"`

Expected: one commit containing the profiler and three tests.

### Task 4: Stage A baseline CLI and report artifact

**Files:**
- Create: `configs/connectome_training_v1.yaml`
- Create: `tools/connectome_training/profile_baseline.py`
- Test: `tests/connectome_training/test_profile_baseline.py`
- Create: `docs/CONNECTOME_TRAINING.md`

**Interfaces:**
- Consumes: `profile_controller`, existing `FullFlyController`, full MaleCNS NPZ, and a synthetic sequence of valid deployment-visible observations.
- Produces: `results/connectome-training/stage-a/baseline_profile.json` with environment, model hashes, sample count, warm-up count, latency distributions and pass/fail gates.

- [ ] **Step 1: Write failing CLI artifact test**

```python
import json
from pathlib import Path
import subprocess
import sys


def test_profile_cli_writes_versioned_report_with_fake_controller(tmp_path):
    script = Path("tools/connectome_training/profile_baseline.py")
    completed = subprocess.run([
        sys.executable, str(script), "--fake", "--samples", "4", "--warmup", "1",
        "--output", str(tmp_path / "profile.json"),
    ], check=True, capture_output=True, text=True)
    report = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
    assert report["schema"] == "flydrones-connectome-profile-v1"
    assert report["controller_identity"] == "deterministic-fake"
    assert report["latency"]["samples"] == 4
    assert report["gates"]["complete_fly_p95_s"] == 0.035
    assert json.loads(completed.stdout)["output"].endswith("profile.json")
```

- [ ] **Step 2: Run and verify the missing CLI failure**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training/test_profile_baseline.py -q`

Expected: FAIL because `tools/connectome_training/profile_baseline.py` does not exist.

- [ ] **Step 3: Add configuration and CLI**

```yaml
# configs/connectome_training_v1.yaml
schema: flydrones-connectome-training-config-v1
latency_gates:
  complete_fly_p95_s: 0.035
  derived_student_p95_s: 0.020
profiling:
  warmup: 5
  samples: 30
  seed: 20260922
artifacts:
  root: results/connectome-training
  stage_a: results/connectome-training/stage-a
```

The CLI supports `--fake`, `--samples`, `--warmup`, `--seed`, `--config` and `--output`. The fake controller returns deterministic latencies and avoids loading the full model in tests. Normal mode loads `configs/forest-trained-v2.yaml`, `data/malecns_full.npz`, constructs `FullFlyController(guided=False)`, warms it with a static 160×120 observation, profiles consecutive 50 ms observations and records the full model hash plus neuron/connection counts from decision evidence. Use the following main flow:

```python
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys

import numpy as np
import yaml

from flydrones.benchmark.contract import Command, Decision, Observation
from flydrones.benchmark.fly import FullFlyController
from flydrones.config import load_config
from flydrones.connectome_training.profiling import profile_controller


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260922)
    parser.add_argument("--config", default="configs/connectome_training_v1.yaml")
    parser.add_argument("--output", default="results/connectome-training/stage-a/baseline_profile.json")
    args = parser.parse_args()
    if args.samples < 1 or args.warmup < 0:
        parser.error("samples must be positive and warmup must be non-negative")
    return args


def make_observation(index: int, shape=(120, 160)):
    sim_ns = (index + 1) * 50_000_000
    return Observation(
        sim_ns, sim_ns, np.zeros((*shape, 3), np.uint8), np.full(shape, 8.0, np.float32),
        (), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), 0.0, 0.0, (8.0, 0.0, 1.0),
    )


class DeterministicFakeController:
    identity = "deterministic-fake"
    model_metadata = {"neurons": 0, "connections": 0, "sha256": None}

    def step(self, obs):
        return Decision(Command((0.0, 0.0, 0.0), 0.0), 0.001,
                        {"brain_wall_s": 0.00075, "sim_ns": obs.sim_ns})


def main():
    args = parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    gates = config["latency_gates"]
    if args.fake:
        controller = DeterministicFakeController()
        identity = controller.identity
        model = controller.model_metadata
    else:
        fly_config = load_config("configs/forest-trained-v2.yaml")
        controller = FullFlyController(fly_config, Path("data/malecns_full.npz"), guided=False)
        identity = "full-male-cns"
        model = {"neurons": controller.connectome.n,
                 "connections": controller.connectome.n_connections,
                 "sha256": controller.model_sha256}
    warmup = [make_observation(i) for i in range(args.warmup)]
    for obs in warmup:
        controller.step(obs)
    start = args.warmup
    latency = profile_controller(controller, [make_observation(start + i) for i in range(args.samples)])
    report = {
        "schema": "flydrones-connectome-profile-v1",
        "controller_identity": identity,
        "seed": args.seed,
        "warmup": args.warmup,
        "latency": latency,
        "gates": gates,
        "passed_complete_fly_p95": latency["total_s"]["p95"] <= gates["complete_fly_p95_s"],
        "environment": {"python": sys.version, "numpy": np.__version__,
                        "platform": platform.platform(), "created_utc": datetime.now(timezone.utc).isoformat()},
        "model": model,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".writing")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"output": str(output), "passed": report["passed_complete_fly_p95"]}))
```

- [ ] **Step 4: Run CLI test and all Stage A tests**

Run: `$env:PYTHONPATH='src'; python -m pytest tests/connectome_training -q`

Expected: `11 passed`.

- [ ] **Step 5: Document exact Stage A usage**

```markdown
# Connectome-constrained training

The 2026-09-22 formal comparison is immutable evaluation evidence. New training artifacts live under `results/connectome-training/` and never consume the formal episode directory.

Run the deterministic contract tests:

    $env:PYTHONPATH='src'; python -m pytest tests/connectome_training -q

Profile the complete MaleCNS controller:

    $env:PYTHONPATH='src'; python tools/connectome_training/profile_baseline.py

The generated JSON separates total, neural and residual overhead latency and evaluates the 35 ms P95 Stage A gate. A failed gate is retained as a baseline result.
```

- [ ] **Step 6: Run the real complete-connectome profile**

Run: `$env:PYTHONPATH='src'; python tools/connectome_training/profile_baseline.py --samples 30 --warmup 5`

Expected: exit 0, `results/connectome-training/stage-a/baseline_profile.json` exists, `controller_identity` is `full-male-cns`, `model.neurons` is `166700`, `model.connections` is `25582837`, and the latency gate result is reported without forcing success.

- [ ] **Step 7: Commit Stage A integration**

Run: `git add configs/connectome_training_v1.yaml tools/connectome_training/profile_baseline.py tests/connectome_training/test_profile_baseline.py docs/CONNECTOME_TRAINING.md results/connectome-training/stage-a/baseline_profile.json && git commit -m "feat: establish connectome training stage-a baseline"`

Expected: one commit containing the CLI, configuration, documentation, tests and measured baseline artifact.

### Task 5: Stage A regression gate

**Files:**
- Modify only if a failure requires a fix in files created by Tasks 1–4.
- Test: all existing Python tests plus `tests/connectome_training`.

**Interfaces:**
- Consumes: all Stage A public APIs and existing project APIs.
- Produces: a green full suite and an audit record that frozen manifest-covered files were not modified after the old formal comparison.

- [ ] **Step 1: Verify the old freeze manifest still seals all covered inputs**

Run: `$env:PYTHONPATH='src'; python -c "from pathlib import Path; from flydrones.benchmark.runner import verify_freeze_manifest; verify_freeze_manifest(Path('results/fly-ego-comparison/freeze/manifest.json'), Path('.')); print('freeze verified')"`

Expected: `freeze verified`.

- [ ] **Step 2: Run the complete Python suite**

Run: `$env:PYTHONPATH='src'; python -m pytest -q`

Expected: `315 passed` plus the existing MaleCNS empty-group warning and no failures.

- [ ] **Step 3: Validate artifact hashes and schema**

Run: `$env:PYTHONPATH='src'; python -c "import json; from pathlib import Path; p=Path('results/connectome-training/stage-a/baseline_profile.json'); d=json.loads(p.read_text()); assert d['schema']=='flydrones-connectome-profile-v1'; assert d['latency']['samples']==30; assert d['model']['neurons']==166700; print(p)"`

Expected: prints `results\connectome-training\stage-a\baseline_profile.json`.

- [ ] **Step 4: Commit any test-driven corrections**

If Steps 1–3 required source corrections, commit only those corrections with `git commit -m "fix: harden connectome stage-a validation"`. If no correction was needed, do not create an empty commit.

- [ ] **Step 5: Record Stage A completion**

Use the execution ledger to record the freeze verification, complete suite result and measured P95 latency. Stage B planning may begin only after these three values are present.
