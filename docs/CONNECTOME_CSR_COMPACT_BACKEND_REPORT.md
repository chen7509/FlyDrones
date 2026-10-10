# Optional compact fixed topology: development report

Date: 2026-10-10. This stage adds an opt-in CPU CSR representation to `ConnectomeConstrainedCore`. The default COO constructor and all training/inference entry points remain unchanged. The complete MaleCNS graph still means 166,700 neurons and 25,582,837 signed connections; no graph pruning, PPO substitute, training run, PX4 run or flight qualification occurred here.

## Provenance and choice

The existing project core uses PyTorch 2.14.0+cpu, SciPy 1.16.3 and NumPy 2.3.4. [PyTorch's `sparse.mm` documentation](https://docs.pytorch.org/docs/stable/generated/torch.sparse.mm) specifies backward support for CSR × dense multiplication, and its [CSR constructor documentation](https://docs.pytorch.org/docs/stable/generated/torch.sparse_csr_tensor.html) permits 32-bit row/column indices. The [upstream repository](https://github.com/pytorch/pytorch) is maintained and its [license](https://github.com/pytorch/pytorch/blob/main/LICENSE) is BSD-style with three redistribution conditions. We reused the already installed backend and the project's existing canonical topology identity. This avoids another graph engine, conversion format, dependency and checkpoint type; the adaptation cost is the new constructor path and full-graph qualification. PyTorch labels CSR support beta, so full-model behavior remains a separate gate. The design and staged qualification plan are in `docs/superpowers/specs/2026-10-10-connectome-csr-compact-backend-design.md` and `docs/superpowers/plans/2026-10-10-connectome-csr-compact-backend.md`.

## Implementation and direct evidence

The explicit `topology_format="csr_compact_v1"` branch copies the source matrix, keeps `(post, pre)` orientation and signs, computes the float64 absolute incoming sum from **raw edges**, normalizes those edges, then coalesces duplicates and removes explicit zeros in CSR. This order matches the existing COO behavior when duplicate edges have opposite signs. It stores one fixed CSR tensor with int32 pointers/columns and float32 values, without the four redundant per-edge metadata buffers. The original `coo_reference` path is still the default, with the same four trainable parameter names and fixed-topology identity check. The compact constructor rejects unsupported formats, non-finite values and signed-int32 index overflow.

The small three-neuron feasibility probe matched COO commands and recurrent state to `1e-7` and all four parameter gradients exactly in that probe. Unit tests also cover empty rows, negative signs, duplicate and zero entries, source preservation, truncated-sequence backpropagation and rejection paths. Independent review found an initial mixed-sign duplicate mismatch and a zero-gradient test that could not prove gradient parity. Both findings were reproduced, fixed and retested; the revised test uses a nonzero readout and a non-clamped time step and asserts nonzero gradients. The expected pre-implementation RED run recorded four compact-path failures while four existing tests passed. An initial broader run with `PYTHONPATH=src` had two child-process import failures (`No module named tools`), not model failures. With the repository root included, the final post-review connectome-training suite passed **390 tests, with 1 skip and 2 warnings**; changed-file Ruff and `git diff --check` passed. The intermediate 389-pass run occurred before the review fix and is retained separately.

At this graph size, the **theoretical steady-state fixed-buffer storage** is 1,125,644,828 bytes for the current COO topology plus edge metadata, versus 205,329,500 bytes for one int32 CSR topology: 920,315,328 bytes potentially saved. This is arithmetic from tensor dimensions and dtypes, not measured RSS. It excludes the source SciPy matrix, canonicalization and conversion temporaries, allocator behavior, autograd, inputs and the rest of the drone stack. The free host memory observed during this stage was approximately 0.55–0.84 GiB, below the existing 4 GiB full-model probe gate; the full 25.6-million-edge graph was **not** constructed or trained.

## Qualification state

| Item | State | Limit |
| --- | --- | --- |
| Tiny CPU CSR topology, forward and gradient parity | Verified on development fixtures | Does not establish full-graph numerical or runtime behavior |
| Optional compact code path | Implemented and tested | Default training/inference still use COO |
| Full MaleCNS graph identity, peak construction memory, latency | Untested | Host memory below existing gate |
| Full-model curriculum learning, decision rate and flight safety | Untested | No training or PX4/Gazebo run in this stage |
| Existing 5-aircraft camera capacity gate | Still failed | Historical 0.873 RTF remains below 0.95; no load or threshold change |

The next resource-dependent step is a prospectively frozen full-graph parity and peak-memory experiment when at least the existing 4 GiB gate is available and no other simulation/training job competes. Only then can compact training or inference integration be considered. This stage does not change the prior VIO→EKF2, safety or open-source comparison claims.
