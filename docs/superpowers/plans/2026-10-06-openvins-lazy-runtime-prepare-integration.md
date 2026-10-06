# OpenVINS Lazy Runtime Prepare Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and independently audit a new prepare-only supported-motion package that prospectively declares the single qualified OpenVINS oneTBB allocator mapping.

**Architecture:** Validate the retained PR61 and PR62 packages, generate one strict lazy-runtime contract, merge every referenced file into a fresh runtime-binding baseline, and reconstruct the existing execution contract and worker command without launching them.

**Tech Stack:** Python 3.12, JSON/SHA-256, existing runtime-binding and execution-contract modules, pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-openvins-lazy-runtime-prepare-integration-design.md`

## Constraints

- Do not start OpenVINS, PX4, Gazebo, training, a capture worker, or physics.
- Do not edit or relabel `dry-v5` or the PR62 study.
- Do not broaden the allocator evidence into a wildcard or general unknown-map allowlist.
- Keep whole-runtime closure, physical execution, VIO accuracy/health, fusion, and flight false.

### Task 1: Strict source and contract validator

**Files:**
- Create: `tools/benchmark/openvins_lazy_runtime_prepare.py`
- Create: `tests/benchmark/test_openvins_lazy_runtime_prepare.py`

- [x] Write RED tests for exact PR61 source inputs, passing PR62 audit, stored/recomputed audit equality, exact package/archive/upstream identity, trigger scope, and source member closure.
- [x] Add rejection tests for drift, missing/extra evidence, path replacement, overclaim, wrong package version/hash, and competing resources.
- [x] Implement the validator and generated lazy-runtime contract.
- [x] Run focused tests to GREEN.

### Task 2: Prepare-only binding and command integration

**Files:**
- Modify: `tools/benchmark/openvins_lazy_runtime_prepare.py`
- Modify: `tests/benchmark/test_openvins_lazy_runtime_prepare.py`

- [x] Write RED tests that require every referenced file and generated contract in the runtime inventory and fresh baseline.
- [x] Require the exact allocator identity while preserving v3 unknown-map refusal for all other paths.
- [x] Recompute the policy copy, execution contract, and absolute command without creating `capture-v1` or launching a process.
- [x] Run focused tests to GREEN.

### Task 3: Independent auditor

**Files:**
- Create: `tools/benchmark/audit_openvins_lazy_runtime_prepare.py`
- Create: `tests/benchmark/test_audit_openvins_lazy_runtime_prepare.py`

- [x] Write RED tests for exact member set, source/audit drift, inventory/baseline drift, command changes, missing allocator, output overclaims, and accidental capture creation.
- [x] Implement the independent recomputation.
- [x] Run focused tests to GREEN.

### Task 4: Fixed preparation and publication

**Files:**
- Create: `docs/OPENVINS_LAZY_RUNTIME_PREPARE_REPORT.md`
- Create: `evidence/openvins-lazy-runtime-prepare-dev-1701.zip`

- [ ] Confirm no competing runtime or test process.
- [ ] Run one fixed prepare-only build and its independent audit; do not invoke the generated command.
- [ ] Run focused tests, full regression, changed-file Ruff, source-tree Ruff comparison, and `git diff --check`.
- [ ] Seal every source, output, test, report, and failure with a member manifest and verified ZIP hash/CRC.
- [ ] Commit, push, and open a stacked draft PR.
