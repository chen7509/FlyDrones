# Compact Connectome Fixed Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit CPU CSR representation of the full signed connectome topology without changing the default model or its learned-parameter identity.

**Architecture:** Keep the existing COO constructor as the reference path. Add a compact constructor path that canonicalizes the same sparse weights, normalizes by absolute incoming row sum and retains only one CSR matrix; verify against the reference path on small connectomes before any full-graph run.

**Tech Stack:** Python 3.12, SciPy 1.16, NumPy 2.3, PyTorch 2.14 CPU, pytest.

**Spec:** `docs/superpowers/specs/2026-10-10-connectome-csr-compact-backend-design.md`.

## Global Constraints

- Do not alter frozen comparison data or the existing 12- and 15-channel parameter artifacts.
- Do not remove neurons, connections or signs from an artifact labelled full MaleCNS.
- Only input gains, cell-type biases, global time constant and descending readout remain trainable.
- Keep `coo_reference` as the default; no automatic activation in training or inference loaders before a full-graph parity and resource study.
- Do not call small-fixture or static-memory evidence full-model training or latency success.

## Review Focus

- Duplicate or explicit zero SciPy entries: compact output must agree with the reference coalesced matrix and canonical identity.
- Empty rows and negative weights: normalization must preserve sign and avoid division by zero.
- Non-finite source and index overflow: reject before constructing a misleading CSR matrix.
- Backprop through `torch.sparse.mm`: every allowed trainable parameter must receive the same small-fixture gradient as COO.
- Checkpoint identity: named trainable parameters stay unchanged; fixed buffers remain non-trainable and compact buffers do not carry raw edge duplicates.

---

### Task 1: Compact fixed topology and tiny parity

**Files:** Modify `src/flydrones/connectome_training/model.py`; test `tests/connectome_training/test_model.py`.

**Interfaces:** `ConnectomeConstrainedCore(connectome, parameter_set, *, topology_format="coo_reference")`; alternative `"csr_compact_v1"` retains a CPU `torch.sparse_csr` fixed matrix with int32 pointers/columns.

- [x] Add failing tests for unknown format, signed/empty-row/duplicate/zero topology parity, absence of redundant compact buffers, finite rejection and forward/state/gradient parity across a short truncated sequence.
- [x] Run focused tests and retain expected RED output.
- [x] Implement the compact branch while leaving default COO code behavior unchanged; normalize raw edges by their float64 incoming absolute sum before canonical CSR coalescing, reject index overflow and store int32 indices/float32 values.
- [x] Run final focused and adjacent connectome tests, Ruff and `git diff --check`; retain actual output and any failures.
- [x] Review the changed code and measured bounds, report verified/implemented/untested, seal evidence with hashes and commit.

### Task 2: Full-graph qualification after resources permit

**Files:** New prospective result profile/report; only then consider integration into `curriculum_session.py` and `inference_artifact.py`.

**Interfaces:** Pinned full MaleCNS NPZ and 15-channel parameter artifact from `docs/MASKED_FULL_INITIALIZATION_REPORT.md`.

- [ ] With at least the existing 4 GiB probe resource gate and no competing jobs, load the pinned full graph under a bounded profile and verify neuron/connection counts, canonical hash and signs.
- [ ] Compare default versus compact forward and allowed-parameter gradient behavior on frozen deploy-visible input sequences; record peak RSS, P50/P95/P99 latency, all failures and hashes.
- [ ] If numerical and resource gates pass, separately decide and test version-bound training/inference integration. Until then leave the default path and all learning claims unchanged.
